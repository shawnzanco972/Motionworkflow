import json
import time
import unittest

from fastapi.testclient import TestClient
from helpers import IsolatedTest

from motionworkflow import config, jobs
from motionworkflow.server import app


class ServerTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def wait(self, job_id, states=("done", "error", "awaiting_approval")):
        for _ in range(200):
            data = self.client.get(f"/api/jobs/{job_id}").json()
            if data["state"] in states and not data["active"]:
                return data
            time.sleep(0.1)
        self.fail("job did not finish")

    def test_status_and_models(self):
        status = self.client.get("/api/status").json()
        self.assertTrue(status["providers"]["mock"])
        models = self.client.get("/api/models?kind=tts").json()
        self.assertTrue(all("tts" in m["kinds"] for m in models))

    def test_foreign_host_and_origin_are_blocked(self):
        self.assertEqual(self.client.get("/api/status", headers={"host": "evil.example"}).status_code, 403)
        r = self.client.post("/api/settings", json={}, headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_codespace_hosts_only_when_allowed(self):
        h = {"host": "me-abc-8770.app.github.dev"}
        self.assertEqual(self.client.get("/api/status", headers=h).status_code, 403)
        self.env(MW_ALLOWED_HOSTS=".app.github.dev")
        self.assertEqual(self.client.get("/api/status", headers=h).status_code, 200)
        for bad in ("app.github.dev", "evil.app.github.dev.example.com", "app.github.dev.evil.com"):
            self.assertEqual(self.client.get("/api/status", headers={"host": bad}).status_code, 403, bad)
        same = {**h, "origin": "https://me-abc-8770.app.github.dev"}
        self.assertEqual(self.client.post("/api/settings", json={}, headers=same).status_code, 200)
        other = {**h, "origin": "https://attacker-8770.app.github.dev"}
        self.assertEqual(self.client.post("/api/settings", json={}, headers=other).status_code, 403)

    def test_create_image_job_and_download(self):
        r = self.client.post("/api/jobs", data={"workflow": "image", "params": json.dumps({"prompt": "cat", "model": "mock:image"})})
        self.assertEqual(r.status_code, 200, r.text)
        job = self.wait(r.json()["id"])
        self.assertEqual(job["state"], "done")
        url = job["outputs"][0]["url"]
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(f"/files/{job['id']}/../../.env").status_code, 404)
        self.assertEqual(self.client.get(f"/files/{job['id']}/job.json").status_code, 404)

    def test_expensive_job_needs_confirmation(self):
        self.env(FAL_KEY="x", MW_CONFIRM_ABOVE="0.10")
        params = {"prompt": "x", "model": "fal:veo31-fast", "duration": 8}
        r = self.client.post("/api/jobs", data={"workflow": "video", "params": json.dumps(params)})
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.json()["needs_confirmation"])
        self.assertEqual(jobs.all_jobs(), [])

    def test_over_job_cap_is_refused(self):
        self.env(FAL_KEY="x", MW_MAX_COST_PER_JOB="0.05")
        params = {"prompt": "x", "model": "fal:veo31-fast", "duration": 8}
        r = self.client.post("/api/jobs", data={"workflow": "video", "params": json.dumps(params), "confirm": "true"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("MW_MAX_COST_PER_JOB", r.json()["detail"])

    def test_approve_flow(self):
        params = {"prompt": "x", "duration": 2, "model": "mock:video", "final_model": "mock:video"}
        job = self.client.post("/api/jobs", data={"workflow": "video", "params": json.dumps(params)}).json()
        job = self.wait(job["id"])
        self.assertEqual(job["state"], "awaiting_approval")
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/approve", json={"stage": "wrong"}).status_code, 409)
        self.client.post(f"/api/jobs/{job['id']}/approve", json={"stage": "final"})
        job = self.wait(job["id"], ("done", "error"))
        self.assertEqual(job["state"], "done")

    def test_cost_breakdown_and_spend_summary(self):
        from motionworkflow import budget

        r = self.client.post("/api/jobs", data={"workflow": "image", "params": json.dumps({"prompt": "cat", "model": "mock:image"})})
        job = self.wait(r.json()["id"])
        budget.charge(job["id"], "fal:flux-schnell", 0.25, note="image-1")
        budget.charge(job["id"], "fal:flux-schnell", 0.10, note="image-2")
        budget.refund(job["id"], "fal:flux-schnell", 0.10, note="image-2: rejected")
        budget.charge(job["id"], "claude:review", 0.03, note="review")
        cost = self.client.get(f"/api/jobs/{job['id']}").json()["cost"]
        self.assertAlmostEqual(cost["spent"], 0.28)
        self.assertEqual(len(cost["ledger"]), 4)
        self.assertEqual(cost["ledger"][0]["note"], "review")  # newest first
        extra = {s["key"]: s for s in cost["steps"]}
        self.assertAlmostEqual(extra["review"]["spent"], 0.03)
        self.assertEqual(extra["review"]["label"], "Fresh-eyes review")
        self.assertTrue(cost["mock"])

        spend = self.client.get("/api/spend?days=3").json()
        self.assertEqual(len(spend["by_day"]), 7)  # clamped to at least a week
        self.assertAlmostEqual(spend["today"], 0.28)
        self.assertAlmostEqual(spend["by_day"][-1]["usd"], 0.28)
        self.assertEqual(spend["by_workflow"], [{"workflow": "image", "usd": 0.28}])
        self.assertEqual(spend["recent"][0]["title"], job["title"])
        self.assertNotIn("by_job", spend)
        # A deleted project keeps its spend, labelled as deleted.
        self.client.delete(f"/api/jobs/{job['id']}")
        spend = self.client.get("/api/spend").json()
        self.assertEqual(spend["by_workflow"][0]["workflow"], "deleted")
        self.assertEqual(spend["recent"][0]["title"], "Deleted project")

    def test_stop_duplicate_download_and_resume_rules(self):
        import io
        import zipfile

        r = self.client.post("/api/jobs", data={"workflow": "image", "params": json.dumps({"prompt": "a fox", "tier": "free"})},
                             files={"refs": ("ref.png", self.make_image().read_bytes(), "image/png")})
        job = self.wait(r.json()["id"])
        self.assertEqual(job["state"], "done")
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/stop").status_code, 409)  # not running
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/resume").status_code, 409)  # nothing to resume

        z = self.client.get(f"/api/jobs/{job['id']}/download")
        self.assertEqual(z.status_code, 200)
        self.assertIn("a-fox", z.headers["content-disposition"])
        names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
        self.assertEqual(len(names), len(job["outputs"]))
        self.assertFalse(any(n.startswith("inputs/") or n == "job.json" for n in names))
        self.assertEqual(list(config.RUNS.glob("*.zip")), [])  # temp zip cleaned up

        copy = self.client.post(f"/api/jobs/{job['id']}/duplicate", json={}).json()
        self.assertNotEqual(copy["id"], job["id"])
        self.assertEqual(copy["duplicate_of"], job["id"])
        self.assertEqual(copy["params"]["prompt"], "a fox")
        self.assertEqual(len(copy["inputs"]["refs"]), 1)  # inputs travel with the copy
        self.assertEqual(self.wait(copy["id"])["state"], "done")

    def test_duplicate_asks_before_a_large_spend(self):
        self.env(FAL_KEY="x", MW_CONFIRM_ABOVE="0.10")
        src = jobs.create("video", {"prompt": "x", "model": "fal:veo31-fast", "duration": 8})
        r = self.client.post(f"/api/jobs/{src.id}/duplicate", json={})
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.json()["needs_confirmation"])
        self.assertEqual(len(jobs.all_jobs()), 1)

    def test_download_with_nothing_yet(self):
        src = jobs.create("image", {"prompt": "x"})
        self.assertEqual(self.client.get(f"/api/jobs/{src.id}/download").status_code, 404)

    def test_status_lists_what_needs_attention(self):
        params = {"prompt": "x", "duration": 2, "model": "mock:video", "final_model": "mock:video"}
        job = self.client.post("/api/jobs", data={"workflow": "video", "params": json.dumps(params)}).json()
        self.wait(job["id"])
        attention = self.client.get("/api/status").json()["attention"]
        self.assertEqual(attention[0]["id"], job["id"])
        self.assertEqual(attention[0]["stage"], "final")

    def test_spend_with_empty_ledger(self):
        spend = self.client.get("/api/spend").json()
        self.assertEqual(spend["all_time"], 0)
        self.assertEqual(len(spend["by_day"]), 14)
        self.assertEqual(spend["recent"], [])

    def test_rejects_bad_upload_type(self):
        files = {"refs": ("x.exe", b"MZ", "application/octet-stream")}
        r = self.client.post("/api/jobs", data={"workflow": "image", "params": "{}"}, files=files)
        self.assertEqual(r.status_code, 400)

    def test_settings_write_env_without_echoing_keys(self):
        r = self.client.post("/api/settings", json={"keys": {"FAL_KEY": "secret-123"}, "settings": {"MW_DAILY_BUDGET": "4"}})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("secret-123", r.text)
        self.assertTrue(r.json()["keys"]["FAL_KEY"])
        self.assertIn("FAL_KEY=secret-123", config.ENV_FILE.read_text())
        self.assertEqual(config.ENV_FILE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.client.post("/api/settings", json={"settings": {"PATH": "x"}}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
