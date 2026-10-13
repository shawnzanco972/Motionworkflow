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
