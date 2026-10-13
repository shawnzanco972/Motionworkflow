"""Edge cases: bad input, odd text, races, money limits and partial failures. Offline."""
import json
import time
from unittest import mock

from fastapi.testclient import TestClient
from helpers import IsolatedTest

from motionworkflow import budget, catalog, config, jobs, media, validation, workflows
from motionworkflow.providers.local import MockProvider
from motionworkflow.server import app


class ValidationTests(IsolatedTest):
    def test_numbers_are_coerced_and_clamped(self):
        p = validation.coerce("short", {"shots": "40", "shot_seconds": "1", "music_volume": ""})
        self.assertEqual((p["shots"], p["shot_seconds"], p["music_volume"]), (12, 2, 0.18))
        p = validation.coerce("image", {"num_images": "2.6", "seed": " "})
        self.assertEqual(p["num_images"], 3)
        self.assertNotIn("seed", p)
        for bad in ("abc", "nan", "inf", True):
            with self.assertRaises(validation.InputError, msg=bad):
                validation.coerce("image", {"num_images": bad})

    def test_text_is_trimmed_and_limited(self):
        self.assertEqual(validation.coerce("image", {"prompt": "  hi  "})["prompt"], "hi")
        with self.assertRaises(validation.InputError) as ctx:
            validation.coerce("image", {"prompt": "x" * 4001})
        self.assertIn("4,000", str(ctx.exception))

    def test_required_fields(self):
        for workflow, params, counts in [("image", {"prompt": "   "}, {}), ("voice", {}, {}),
                                         ("short", {}, {}), ("presenter", {"topic": "x"}, {}),
                                         ("swap", {}, {"video": 1})]:
            with self.assertRaises(validation.InputError, msg=workflow):
                validation.require(workflow, validation.coerce(workflow, params), counts)
        validation.require("presenter", {"topic": "x", "avatar_id": "abc"}, {})

    def test_bad_media_is_caught(self):
        empty = self.tmp / "empty.png"
        empty.write_bytes(b"")
        fake = self.tmp / "fake.png"
        fake.write_bytes(b"not a png at all")
        from PIL import Image

        tiny = self.tmp / "tiny.png"
        Image.new("RGB", (20, 20)).save(tiny)
        silent = self.make_video(1, audio=False, name="silent.mp4")
        junk = self.tmp / "junk.mp4"
        junk.write_bytes(b"\x00" * 2000)
        cases = [(empty, "refs", "empty"), (fake, "refs", "readable"), (tiny, "refs", "too small"),
                 (silent, "voice_sample", "no sound"), (junk, "video", "can't be read")]
        for path, field, words in cases:
            with self.assertRaises(validation.InputError, msg=path.name) as ctx:
                validation.check_media(path, field)
            self.assertIn(words, str(ctx.exception))
        validation.check_media(self.make_image(), "refs")
        validation.check_media(self.make_video(1), "video")


class CaptionTests(IsolatedTest):
    def test_formatting_characters_cannot_reach_the_renderer(self):
        safe = media.caption_safe(r"{\an8}<b>x</b> \N")
        for ch in "{}<>\\":
            self.assertNotIn(ch, safe)

    def test_odd_text_burns_without_error(self):
        video = self.make_video(3, audio=False)
        lines = ["{\\an8} braces and \\ backslash", "Ünïcödé — “quotes” & 'apostrophes'", "emoji 🎬🔥 ok", "עברית בסדר",
                 "a" * 60]
        cues = []
        t = 0.0
        for text in lines:
            cues += media.caption_chunks(text, t, t + 0.6)
            t += 0.6
        for _, _, text in cues:
            self.assertNotIn("{", text.replace("<font", ""))
        srt = media.write_srt(cues, video.parent / "c.srt")
        for aspect in ("16:9", "9:16", "1:1"):
            out = media.burn_captions(video, srt, video.parent / f"out-{aspect.replace(':', 'x')}.mp4", aspect=aspect)
            self.assertGreater(media.probe(out)["duration"], 2.5)

    def test_captions_never_flash(self):
        words = "one two three four five six seven eight nine ten eleven twelve"
        cues = media.caption_chunks(words, 0, 5.0)
        self.assertGreater(len(cues), 1)
        self.assertTrue(all(b - a >= 1.2 for a, b, _ in cues))
        # A line too quick to split stays one caption for its whole time rather than flashing.
        self.assertEqual([(a, b) for a, b, _ in media.caption_chunks(words, 0, 1.0)], [(0, 1.0)])


class SettingsTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def save(self, **settings):
        return self.client.post("/api/settings", json={"settings": settings})

    def test_bad_values_are_refused_with_a_reason(self):
        for name, value, words in [("MW_DAILY_BUDGET", "ten", "number"), ("MW_DAILY_BUDGET", "-1", "zero or more"),
                                   ("MW_DAILY_BUDGET", "nan", "zero or more"), ("MW_MAX_PARALLEL", "0", "1 to 8"),
                                   ("MW_MAX_PARALLEL", "2.5", "1 to 8"), ("MW_DEFAULT_TIER", "ultra", "one of"),
                                   ("MW_MAX_COST_PER_JOB", "30000", "too high"), ("NOT_A_SETTING", "1", "cannot be set")]:
            r = self.save(**{name: value})
            self.assertEqual(r.status_code, 400, (name, value))
            self.assertIn(words, r.json()["detail"])
        self.assertFalse(config.ENV_FILE.exists())  # nothing half-saved

    def test_dollar_sign_and_blank_are_fine(self):
        self.assertEqual(self.save(MW_DAILY_BUDGET="$5").status_code, 200)
        self.assertEqual(config.number("MW_DAILY_BUDGET"), 5.0)
        self.assertEqual(self.save(MW_DAILY_BUDGET="").status_code, 200)
        self.assertEqual(config.number("MW_DAILY_BUDGET"), 10.0)  # blank means the default

    def test_a_broken_env_value_falls_back_to_the_safe_default(self):
        for value in ("abc", "nan", "-5", "inf"):
            self.env(MW_DAILY_BUDGET=value)
            self.assertEqual(config.number("MW_DAILY_BUDGET"), 10.0, value)


class ServerEdgeTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def wait(self, job_id, states=("done", "error", "awaiting_approval", "stopped")):
        for _ in range(200):
            data = self.client.get(f"/api/jobs/{job_id}").json()
            if data["state"] in states and not data["active"]:
                return data
            time.sleep(0.05)
        self.fail("job did not finish")

    def create(self, workflow, params, **files):
        return self.client.post("/api/jobs", data={"workflow": workflow, "params": json.dumps(params)}, files=files or None)

    def test_bad_requests_never_create_a_project(self):
        cases = [
            ({"workflow": "image", "params": "not json"}, None),
            ({"workflow": "image", "params": "[1, 2]"}, None),
            ({"workflow": "nope", "params": "{}"}, None),
            ({"workflow": "image", "params": json.dumps({"prompt": ""})}, None),
            ({"workflow": "image", "params": json.dumps({"prompt": "x", "num_images": "lots"})}, None),
            ({"workflow": "image", "params": json.dumps({"prompt": "x", "model": "fal:does-not-exist"})}, None),
            ({"workflow": "image", "params": json.dumps({"prompt": "x"})}, {"refs": ("a.png", b"", "image/png")}),
            ({"workflow": "image", "params": json.dumps({"prompt": "x"})}, {"refs": ("a.png", b"garbage", "image/png")}),
            ({"workflow": "swap", "params": "{}"}, {"video": ("v.mp4", b"\x00" * 100, "video/mp4")}),
            ({"workflow": "presenter", "params": json.dumps({"topic": "x", "avatar_id": "0000000000"})}, None),
            ({"workflow": "presenter", "params": json.dumps({"topic": "x", "avatar_id": "../../etc"})}, None),
        ]
        for data, files in cases:
            r = self.client.post("/api/jobs", data=data, files=files)
            self.assertEqual(r.status_code, 400, (data, r.text))
            self.assertIsInstance(r.json()["detail"], str)
        self.assertEqual(jobs.all_jobs(), [])
        self.assertEqual([p.name for p in config.RUNS.iterdir() if p.is_dir()], [])  # no upload leftovers

    def test_estimate_never_500s(self):
        for body in [{}, {"workflow": "image"}, {"workflow": "image", "params": {"num_images": "x"}},
                     {"workflow": "zzz", "params": {}}, {"workflow": "video", "params": {"duration": "1e9"}}]:
            r = self.client.post("/api/estimate", json=body)
            self.assertIn(r.status_code, (200, 400), (body, r.text))

    def test_unknown_and_malformed_ids(self):
        for path in ("/api/jobs/abc", "/api/jobs/000000000000", "/api/jobs/..%2F..%2Fetc"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.post("/api/jobs/000000000000/approve", json={}).status_code, 404)
        self.assertEqual(self.client.get("/files/000000000000/x.png").status_code, 404)
        self.assertEqual(self.client.get("/library/avatars/../voices/x").status_code, 404)

    def test_double_approve_is_refused(self):
        params = {"prompt": "x", "duration": 2, "model": "mock:video", "final_model": "mock:video"}
        job = self.wait(self.create("video", params).json()["id"])
        first = self.client.post(f"/api/jobs/{job['id']}/approve", json={"stage": "final"})
        second = self.client.post(f"/api/jobs/{job['id']}/approve", json={"stage": "final"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(self.wait(job["id"], ("done", "error"))["state"], "done")

    def test_no_edits_or_delete_while_running(self):
        job = self.wait(self.create("image", {"prompt": "x", "model": "mock:image"}).json()["id"])
        workflows._active.add(job["id"])  # as if a step were in flight
        try:
            for method, path in [("delete", ""), ("post", "/retry"), ("post", "/redo")]:
                r = getattr(self.client, method)(f"/api/jobs/{job['id']}{path}", **({"json": {}} if method == "post" else {}))
                self.assertEqual(r.status_code, 409, path)
            self.assertTrue(jobs.load(job["id"]).folder.exists())
        finally:
            workflows._active.discard(job["id"])

    def test_list_limit_is_bounded(self):
        self.assertEqual(self.client.get("/api/jobs?limit=-5").status_code, 200)
        self.assertEqual(self.client.get("/api/jobs?limit=99999999").status_code, 200)
        self.assertEqual(self.client.get("/api/spend?days=100000").status_code, 200)

    def test_without_mock_and_keys_the_message_says_what_to_do(self):
        self.env(MW_ALLOW_MOCK="0")
        catalog.reload()
        r = self.create("image", {"prompt": "x", "tier": "budget"})
        if r.status_code == 200:  # a free provider (Pollinations) may still serve images
            self.assertNotEqual(r.json()["cost"]["planned"][0]["model"].split(":")[0], "mock")
        r = self.create("video", {"prompt": "x", "tier": "budget"})
        self.assertEqual(r.status_code, 400)
        self.assertRegex(r.json()["detail"], "KEY|key")
        self.assertEqual([j for j in jobs.all_jobs() if j.data["workflow"] == "video"], [])


class MoneyEdgeTests(IsolatedTest):
    """Limits hit in the middle of a run, and failures in one of several parallel steps."""

    def short(self, shots=4):
        return jobs.create("short", {"idea": "a cat CEO", "shots": shots, "mode": "slideshow", "image_model": "mock:image"})

    def test_daily_budget_hit_mid_run_stops_before_the_next_request(self):
        self.env(MW_DAILY_BUDGET="1.00", MW_MAX_COST_PER_JOB="5", MW_MAX_PARALLEL="1")
        submits = []
        real = MockProvider.submit

        def counting(provider, model, body, workdir):
            submits.append(model["id"])
            return real(provider, model, body, workdir)

        priced = lambda model, params: 0.4 if model["kind"] == "image" else 0.0  # noqa: E731
        with mock.patch.object(catalog, "estimate", side_effect=priced), \
             mock.patch.object(MockProvider, "submit", counting):
            job = self.short(4)
            workflows.run(job)
        self.assertEqual(job.data["state"], "error")
        self.assertIn("MW_DAILY_BUDGET", job.data["error"])
        self.assertEqual(submits.count("mock:image"), 2)  # the third would pass $1.00, so it never went out
        self.assertAlmostEqual(budget.spent_on_job(job.id), 0.8)
        self.assertFalse(job.data["steps"].get("key-2", {}).get("handle"))

    def test_one_failed_shot_keeps_the_others_and_retry_sends_only_it(self):
        self.env(MW_MAX_PARALLEL="1")
        calls = {"n": 0}
        real = MockProvider.submit

        def flaky(provider, model, body, workdir):
            if model["kind"] == "image":
                calls["n"] += 1
                if calls["n"] == 2:
                    from motionworkflow.providers.base import RejectedError
                    raise RejectedError("content policy")
            return real(provider, model, body, workdir)

        with mock.patch.object(MockProvider, "submit", flaky):
            job = self.short(3)
            workflows.run(job)
            self.assertEqual(job.data["state"], "error")
            self.assertIn("content policy", job.data["error"])
            states = {k: v["state"] for k, v in job.data["steps"].items() if k.startswith("key-")}
            self.assertEqual(states["key-0"], "done")
            self.assertEqual(states["key-1"], "failed")
            before = calls["n"]
            workflows.retry(job)
            workflows.run(job)
        self.assertEqual(job.data["state"], "done", job.data.get("error"))
        self.assertEqual(calls["n"] - before, 2)  # key-1 again, key-2 for the first time; key-0 reused

    def test_restart_resumes_a_job_that_was_mid_flight(self):
        job = jobs.create("image", {"prompt": "x", "model": "mock:image"})
        job.status("Working", "running")
        jobs._live.clear()  # the app was closed
        resumed = workflows.resume_all()
        self.assertEqual(resumed, [job.id])
        for _ in range(100):
            if not workflows.is_active(job.id):
                break
            time.sleep(0.05)
        self.assertEqual(jobs.load(job.id).data["state"], "done")
