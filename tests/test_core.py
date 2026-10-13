import json
import unittest
from unittest import mock

from helpers import IsolatedTest

from motionworkflow import budget, catalog, config, jobs, planner
from motionworkflow.providers import base
from motionworkflow.providers.fal import FalProvider
from motionworkflow.workflows import common


class CatalogTests(IsolatedTest):
    def test_defaults_reference_real_models_of_the_right_kind(self):
        data = catalog._load()
        for kind, tiers in data["defaults"].items():
            for tier, ids in tiers.items():
                for model_id in ids:
                    model = catalog.get(model_id)
                    self.assertIn(kind, catalog.kinds_of(model), f"{model_id} listed under {kind}/{tier}")

    def test_every_kind_has_a_mock(self):
        for kind in catalog.KINDS:
            catalog.get("mock:" + kind.replace("_", "-"))

    def test_without_keys_falls_back_to_free_models(self):
        self.assertEqual(catalog.resolve("video", "premium")["provider"], "mock")
        self.assertEqual(catalog.resolve("image", "budget")["id"], "pollinations:flux")

    def test_key_unlocks_tier_default(self):
        self.env(FAL_KEY="test")
        self.assertEqual(catalog.resolve("image", "budget")["id"], "fal:flux-schnell")
        self.assertEqual(catalog.resolve("video", "premium")["id"], "fal:veo31-fast")

    def test_explicit_model_without_key_is_refused(self):
        with self.assertRaises(config.MissingKey):
            catalog.resolve("image", model_id="fal:flux-schnell")

    def test_build_input_maps_fields(self):
        model = catalog.get("fal:flux-schnell")
        body = catalog.build_input(model, {"prompt": "cat", "aspect_ratio": "9:16", "num_images": 2, "unused": 1})
        self.assertEqual(body["image_size"], "portrait_16_9")
        self.assertEqual(body["num_images"], 2)
        self.assertNotIn("unused", body)
        veo = catalog.build_input(catalog.get("fal:veo31-fast"), {"prompt": "x", "duration": 8, "audio": False})
        self.assertEqual(veo["duration"], "8s")
        self.assertIs(veo["generate_audio"], False)

    def test_estimates(self):
        wan = catalog.get("fal:wan-25-t2v")
        self.assertAlmostEqual(catalog.estimate(wan, {"duration": 7, "resolution": "720p"}), 0.10 * 5)
        self.assertAlmostEqual(catalog.estimate(wan, {"duration": 9}), 0.05 * 10)
        kokoro = catalog.get("fal:kokoro")
        self.assertAlmostEqual(catalog.estimate(kokoro, {"text": "x" * 500}), 0.01)
        seedance = catalog.get("enhancor:seedance-edit")
        self.assertEqual(catalog.pick_duration(seedance, 45), 30)
        self.assertEqual(catalog.pick_duration(seedance, 2), 4)

    def test_local_override_file(self):
        local = config.ROOT / "models.local.json"
        self.assertFalse(local.exists(), "remove your models.local.json before running tests")
        try:
            local.write_text(json.dumps({"models": [{"id": "fal:flux-schnell", "price": {"unit": "image", "usd": 0.5}}]}))
            catalog.reload()
            self.assertEqual(catalog.get("fal:flux-schnell")["price"]["usd"], 0.5)
            self.assertEqual(catalog.get("fal:flux-schnell")["endpoint"], "fal-ai/flux/schnell")
        finally:
            local.unlink()
            catalog.reload()


class BudgetTests(IsolatedTest):
    def test_daily_cap(self):
        self.env(MW_DAILY_BUDGET="1.00", MW_MAX_COST_PER_JOB="5")
        budget.charge("a", "m", 0.6)
        with self.assertRaises(budget.BudgetExceeded):
            budget.charge("b", "m", 0.6)
        budget.refund("a", "m", 0.6)
        budget.charge("b", "m", 0.6)
        self.assertAlmostEqual(budget.spent_today(), 0.6)

    def test_job_cap(self):
        self.env(MW_MAX_COST_PER_JOB="0.50")
        with self.assertRaises(budget.BudgetExceeded):
            budget.check_job(0.51)
        budget.charge("j", "m", 0.3)
        with self.assertRaises(budget.BudgetExceeded):
            budget.charge("j", "m", 0.3)


class FakeProvider(base.Provider):
    """Counts paid submits; can fail on demand."""
    name = "fake"

    def __init__(self):
        self.submits = 0
        self.fail_wait = 0
        self.reject = False

    def prepare_media(self, path):
        return "https://example.com/" + path.name

    def submit(self, model, body, workdir):
        if self.reject:
            raise base.RejectedError("bad input")
        self.submits += 1
        return {"request_id": f"req-{self.submits}", "body": body}

    def wait(self, model, handle, status, timeout=0):
        if self.fail_wait:
            self.fail_wait -= 1
            raise base.StillRunning("still going")
        return {"url": "https://example.com/out.png"}

    def collect(self, model, handle, result, dest_stem):
        path = dest_stem.with_suffix(".png")
        path.write_bytes(b"png")
        return [path]


class GenerateTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.fake = FakeProvider()
        self.patch = mock.patch("motionworkflow.providers._REGISTRY", {"fake": self.fake})
        self.patch.start()
        self.model = {"id": "fake:img", "name": "Fake", "provider": "fake", "kind": "image",
                      "price": {"unit": "image", "usd": 0.01}, "inputs": {"prompt": "prompt", "image": "image_url"}}

    def tearDown(self):
        self.patch.stop()
        super().tearDown()

    def test_step_is_paid_once_and_resumes_without_resubmitting(self):
        job = jobs.create("image", {})
        self.fake.fail_wait = 1
        with self.assertRaises(common.StepFailed):
            common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertEqual(self.fake.submits, 1)
        self.assertEqual(job.step("s")["state"], "running")
        # A restart reloads the job from disk and continues polling only.
        jobs._live.clear()
        job = jobs.load(job.id)
        files = common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertEqual(self.fake.submits, 1)
        self.assertTrue(files[0].exists())
        common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertEqual(self.fake.submits, 1)
        self.assertAlmostEqual(budget.spent_on_job(job.id), 0.01)

    def test_crash_during_submit_is_never_resubmitted(self):
        job = jobs.create("image", {})
        job.update_step("s", state="submitting", model="fake:img")  # process died mid-request
        with self.assertRaises(common.StepFailed):
            common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertEqual(self.fake.submits, 0)
        self.assertEqual(job.step("s")["state"], "unknown")
        from motionworkflow import workflows

        workflows.retry(job)  # without force, unclear steps stay blocked
        with self.assertRaises(common.StepFailed):
            common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        workflows.retry(job, force=True)
        common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertEqual(self.fake.submits, 1)

    def test_media_is_prepared_and_mapped(self):
        job = jobs.create("image", {})
        image = self.make_image()
        common.generate(job, "s", self.model, {"prompt": "x", "image": str(image)}, "Step")
        body = job.step("s")["handle"]["body"]
        self.assertEqual(body["image_url"], "https://example.com/ref.png")

    def test_rejected_submit_is_refunded_and_needs_retry(self):
        job = jobs.create("image", {})
        self.fake.reject = True
        with self.assertRaises(common.StepFailed):
            common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertAlmostEqual(budget.spent_on_job(job.id), 0.0)
        self.fake.reject = False
        with self.assertRaises(common.StepFailed):  # failed steps never auto-resubmit
            common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        from motionworkflow import workflows

        workflows.retry(job)
        common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertEqual(self.fake.submits, 1)


    def test_stop_before_submit_spends_nothing(self):
        job = jobs.create("image", {})
        job.request_stop()
        with self.assertRaises(jobs.JobStopped):
            common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertEqual(self.fake.submits, 0)
        self.assertAlmostEqual(budget.spent_on_job(job.id), 0.0)

    def test_stop_while_polling_keeps_the_request_and_resume_collects_it(self):
        job = jobs.create("image", {})

        def wait(model, handle, status, timeout=0):
            job.request_stop()  # pressed Stop while the provider is generating
            status("")
            return {"url": "x"}

        with mock.patch.object(self.fake, "wait", side_effect=wait):
            with self.assertRaises(jobs.JobStopped):
                common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertEqual(job.step("s")["state"], "running")
        self.assertTrue(job.step("s")["handle"])
        job.clear_stop()
        files = common.generate(job, "s", self.model, {"prompt": "x"}, "Step")
        self.assertTrue(files[0].exists())
        self.assertEqual(self.fake.submits, 1)  # resumed, not paid twice
        self.assertAlmostEqual(budget.spent_on_job(job.id), 0.01)

    def test_run_marks_a_stopped_job_and_resume_finishes_it(self):
        from motionworkflow import workflows

        self.patch.stop()  # use the real offline mock provider
        try:
            job = jobs.create("image", {"prompt": "x", "model": "mock:image"})
            stop_once = lambda j, message: j.request_stop() if message == "Working" else None  # noqa: E731
            jobs.listeners.append(stop_once)
            try:
                workflows.run(job)
            finally:
                jobs.listeners.remove(stop_once)
            self.assertEqual(job.data["state"], "stopped", job.data.get("error"))
            self.assertFalse(job.stop_requested())  # the flag never outlives a run
            self.assertFalse(any(st.get("handle") for st in job.data["steps"].values()))  # nothing was sent
            workflows.run(job)
            self.assertEqual(job.data["state"], "done")
        finally:
            self.patch.start()

    def test_stop_requested_while_nothing_runs_it(self):
        from motionworkflow import workflows

        job = jobs.create("image", {"prompt": "x", "model": "mock:image"})
        job.status("Working", "running")  # e.g. left over after the app was closed
        job.request_stop()  # `mw stop` from another terminal
        workflows.resume_all()
        self.assertEqual(job.data["state"], "stopped")
        with self.assertRaises(ValueError):
            workflows.stop(job)


class FalAdapterTests(IsolatedTest):
    def test_submit_and_wait(self):
        self.env(FAL_KEY="k")
        model = catalog.get("fal:flux-schnell")
        provider = FalProvider()
        posted = mock.Mock(ok=True, status_code=200)
        posted.json.return_value = {"request_id": "r1", "status_url": "https://queue/s", "response_url": "https://queue/r"}
        with mock.patch("requests.post", return_value=posted) as post:
            handle = provider.submit(model, {"prompt": "x"}, self.tmp)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Key k")
        self.assertTrue(post.call_args.args[0].endswith("fal-ai/flux/schnell"))
        status = mock.Mock(); status.json.return_value = {"status": "COMPLETED"}; status.raise_for_status = lambda: None
        result = mock.Mock(ok=True); result.json.return_value = {"images": [{"url": "https://cdn/x.png"}], "seed": 1}
        with mock.patch("requests.get", side_effect=[status, result]):
            payload = provider.wait(model, handle, lambda m: None)
        self.assertEqual(base.find_urls(payload), ["https://cdn/x.png"])

    def test_http_error_is_a_rejection(self):
        self.env(FAL_KEY="k")
        bad = mock.Mock(ok=False, status_code=422, text="field required")
        with mock.patch("requests.post", return_value=bad):
            with self.assertRaises(base.RejectedError):
                FalProvider().submit(catalog.get("fal:flux-schnell"), {}, self.tmp)

    def test_timeout_is_ambiguous(self):
        import requests

        self.env(FAL_KEY="k")
        with mock.patch("requests.post", side_effect=requests.Timeout()):
            with self.assertRaises(base.AmbiguousError):
                FalProvider().submit(catalog.get("fal:flux-schnell"), {}, self.tmp)


class PlannerTests(IsolatedTest):
    def test_script_lines(self):
        plan, warning = planner.make_plan("", script="Hello there | a cat waving | zoom\nSecond line\n")
        self.assertIsNone(warning)
        self.assertEqual(len(plan["shots"]), 2)
        self.assertEqual(plan["shots"][0]["visual"], "a cat waving")
        self.assertEqual(plan["shots"][1]["visual"], "Second line")

    def test_template_without_key(self):
        for n in (1, 2, 5, 9):
            plan, warning = planner.make_plan("a dog CEO", shots=n)
            self.assertEqual(len(plan["shots"]), n)
            self.assertIn("ANTHROPIC_API_KEY", warning)


if __name__ == "__main__":
    unittest.main()


class ClaudePlannerTests(IsolatedTest):
    """Drives the real Anthropic SDK against a fake HTTP transport (no network)."""

    def run_planner(self, tier):
        import anthropic
        import httpx2 as httpx

        plan = {"title": "T", "style_bible": "clay", "caption": "c", "hashtags": ["#fun", "ai"],
                "shots": [{"visual": f"v{i}", "motion": "m", "narration": "n"} for i in range(3)]}
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            seen["headers"] = request.headers
            return httpx.Response(200, json={
                "id": "msg_1", "type": "message", "role": "assistant", "model": seen["body"]["model"],
                "content": [{"type": "text", "text": json.dumps(plan)}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 20}})

        real = anthropic.Anthropic

        def fake_client(**kwargs):
            return real(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

        self.env(ANTHROPIC_API_KEY="sk-test")
        with mock.patch("anthropic.Anthropic", side_effect=fake_client):
            result, warning = planner.make_plan("a cat CEO", shots=2, tier=tier)
        return result, warning, seen

    def test_budget_tier_uses_haiku_with_structured_output(self):
        result, warning, seen = self.run_planner("budget")
        self.assertIsNone(warning)
        self.assertEqual(len(result["shots"]), 2)  # trimmed to the requested count
        self.assertEqual(result["hashtags"], ["fun", "ai"])
        self.assertEqual(seen["body"]["model"], "claude-haiku-5-5")
        self.assertEqual(seen["body"]["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("fallbacks", seen["body"])

    def test_standard_tier_uses_opus_with_server_fallback(self):
        _, _, seen = self.run_planner("standard")
        self.assertEqual(seen["body"]["model"], "claude-opus-5-5")
        self.assertEqual(seen["body"]["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", seen["headers"].get("anthropic-beta", ""))
