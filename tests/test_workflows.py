"""End-to-end runs with the offline mock provider (needs ffmpeg, no network)."""
import unittest

from helpers import IsolatedTest

from motionworkflow import jobs, media, workflows


class WorkflowTests(IsolatedTest):
    def run_job(self, workflow, params, files=None):
        job = jobs.create(workflow, params, files or {})
        workflows.run(job)
        self.assertNotEqual(job.data["state"], "error", job.data.get("error"))
        return job

    def finals(self, job):
        return [job.folder / o["path"] for o in job.data["outputs"] if o.get("final")]

    def test_image_batch(self):
        job = self.run_job("image", {"prompt": "a cat", "num_images": 3, "model": "mock:image"})
        self.assertEqual(len(self.finals(job)), 3)
        self.assertTrue(job.data["used_mock"])

    def test_image_edit_with_reference(self):
        job = self.run_job("image", {"prompt": "make it blue", "tier": "budget"}, {"refs": [self.make_image()]})
        self.assertEqual(job.step("image-0")["model"], "mock:image-edit")

    def test_video_draft_waits_for_approval(self):
        job = self.run_job("video", {"prompt": "a dog", "duration": 2, "model": "mock:video", "final_model": "mock:video"})
        self.assertEqual(job.data["state"], "awaiting_approval")
        self.assertNotIn("final", job.data["steps"])
        job.approve("final")
        workflows.run(job)
        self.assertEqual(job.data["state"], "done")
        self.assertTrue(job.path("final.mp4").exists())

    def test_image_to_video(self):
        job = self.run_job("video", {"prompt": "wave", "duration": 2, "tier": "free"}, {"image": [self.make_image()]})
        self.assertEqual(job.step("draft")["model"], "mock:image-to-video")

    def test_short_slideshow_has_voice_captions_and_post_kit(self):
        job = self.run_job("short", {"idea": "a cat CEO", "shots": 2, "mode": "slideshow", "image_model": "mock:image"})
        self.assertEqual(job.data["state"], "done")
        final = job.path("final.mp4")
        info = media.probe(final)
        self.assertTrue(info["has_audio"])
        self.assertEqual((info["width"], info["height"]), (720, 1280))
        self.assertTrue(job.path("captions.srt").read_text().strip())
        self.assertIn("## LinkedIn", job.path("POSTS.md").read_text())

    def test_short_animated_storyboard_gate_and_redo(self):
        params = {"idea": "grandma DJ", "shots": 2, "mode": "animated", "shot_seconds": 2,
                  "image_model": "mock:image", "aspect_ratio": "16:9"}
        job = self.run_job("short", params)
        self.assertEqual(job.data["state"], "awaiting_approval")
        self.assertFalse(any(k.startswith("clip-") for k in job.data["steps"]))
        # Editing a shot regenerates it and withdraws approval.
        job.approve("storyboard")
        workflows.redo(job, ["key-1"], {"1": {"visual": "grandma on stage, crowd cheering"}})
        self.assertFalse(job.approved("storyboard"))
        workflows.run(job)
        self.assertEqual(job.data["state"], "awaiting_approval")
        self.assertEqual(job.data["plan"]["shots"][1]["visual"], "grandma on stage, crowd cheering")
        job.approve("storyboard")
        workflows.run(job)
        self.assertEqual(job.data["state"], "done")
        self.assertEqual(media.probe(job.path("final.mp4"))["width"], 1280)

    def test_swap_restores_original_audio(self):
        source = self.make_video(seconds=3)
        job = self.run_job("swap", {"model": "mock:swap"}, {"video": [source], "refs": [self.make_image()]})
        self.assertEqual(job.data["state"], "awaiting_approval")
        self.assertTrue(job.path("draft-preview.mp4").exists())
        job.approve("final")
        workflows.run(job)
        final = media.probe(job.path("final.mp4"))
        self.assertTrue(final["has_audio"])
        self.assertAlmostEqual(final["duration"], media.probe(source)["duration"], delta=0.15)

    def test_swap_rejects_video_reference_for_wan(self):
        self.env(FAL_KEY="x")
        job = jobs.create("swap", {"model": "fal:wan-animate-replace"},
                          {"video": [self.make_video(2)], "refs": [self.make_video(2, name="ref.mp4")]})
        workflows.run(job)
        self.assertEqual(job.data["state"], "error")
        self.assertIn("image reference", job.data["error"])

    def test_restore_audio_pads_short_generation(self):
        source = self.make_video(seconds=3)
        generated = self.make_video(seconds=2.4, audio=False, name="gen.mp4")
        result = media.restore_audio(generated, source, self.tmp / "out.mp4")
        self.assertIn("held last frame", result["adjustment"])
        limited = media.restore_audio(generated, source, self.tmp / "limited.mp4", limit=2.4)
        self.assertAlmostEqual(media.probe(self.tmp / "limited.mp4")["duration"], 2.4, delta=0.1)
        self.assertIn("untouched", limited["audio"])
        too_short = self.make_video(seconds=1, audio=False, name="short.mp4")
        with self.assertRaises(media.MediaError):
            media.restore_audio(too_short, source, self.tmp / "bad.mp4")


if __name__ == "__main__":
    unittest.main()


FAKE_GENJUTSU = r'''
import argparse, shutil, sys, uuid
from pathlib import Path
p = argparse.ArgumentParser(); p.add_argument("cmd"); p.add_argument("video")
p.add_argument("--mode"); p.add_argument("--subject"); p.add_argument("--provider")
a = p.parse_args()
if a.subject == "fail":
    print("JOB:", "f" * 32); print("SAM 3 found no subject"); sys.exit(1)
folder = Path(__file__).parent / "runs" / uuid.uuid4().hex
folder.mkdir(parents=True)
print("JOB:", folder.name, flush=True)
print("Video Depth Anything · generating depth", flush=True)
for name in ("upload.mp4", "mask.mp4", "composite-silent.mp4", "seedance-input.mp4"):
    shutil.copy(a.video, folder / name)
'''


class GenjutsuSwapTests(IsolatedTest):
    def setUp(self):
        import os
        import sys

        super().setUp()
        root = self.tmp / "genjutsu"
        (root / ".venv" / "bin").mkdir(parents=True)
        (root / ".venv" / "bin" / "python").symlink_to(sys.executable)
        (root / "workflow.py").write_text(FAKE_GENJUTSU)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "rubberband").write_text("#!/bin/sh\n")
        (bin_dir / "rubberband").chmod(0o755)
        self._path = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}:{self._path}"
        self.env(MW_GENJUTSU_DIR=str(root), REPLICATE_API_TOKEN="r")

    def tearDown(self):
        import os

        os.environ["PATH"] = self._path
        os.environ.pop("MW_GENJUTSU_DIR", None)
        super().tearDown()

    def test_prep_then_mask_review_then_draft(self):
        from motionworkflow import budget

        files = {"video": [self.make_video(3)], "refs": [self.make_image()]}
        job = jobs.create("swap", {"model": "mock:swap", "prep": "genjutsu-depth"}, files)
        workflows.run(job)
        self.assertEqual(job.data["state"], "awaiting_approval", job.data.get("error"))
        self.assertEqual(job.data["awaiting"]["stage"], "mask")
        self.assertNotIn("draft", job.data["steps"])
        self.assertTrue(job.path("genjutsu/mask.mp4").exists())
        self.assertAlmostEqual(budget.spent_on_job(job.id), 0.30)
        job.approve("mask")
        workflows.run(job)
        self.assertEqual(job.data["awaiting"]["stage"], "final")
        job.approve("final")
        workflows.run(job)
        self.assertEqual(job.data["state"], "done", job.data.get("error"))
        self.assertTrue(media.probe(job.path("final.mp4"))["has_audio"])
        # Redoing the prep withdraws every approval and the draft.
        workflows.redo(job, ["prep"])
        self.assertEqual(job.approvals(), {})
        self.assertNotIn("draft", job.data["steps"])

    def test_failed_prep_is_not_retried_silently(self):
        files = {"video": [self.make_video(2)], "refs": [self.make_image()]}
        job = jobs.create("swap", {"model": "mock:swap", "prep": "genjutsu-depth", "subject": "fail"}, files)
        workflows.run(job)
        self.assertEqual(job.data["state"], "error")
        self.assertIn("SAM 3 found no subject", job.data["error"])
        workflows.run(job)
        self.assertIn("Retry", job.data["error"])

    def test_missing_install_spends_nothing(self):
        from motionworkflow import budget

        self.env(MW_GENJUTSU_DIR=str(self.tmp / "nowhere"))
        files = {"video": [self.make_video(2)], "refs": [self.make_image()]}
        job = jobs.create("swap", {"model": "mock:swap", "prep": "genjutsu-face-mesh"}, files)
        workflows.run(job)
        self.assertIn("install-skills.sh", job.data["error"])
        self.assertEqual(budget.spent_on_job(job.id), 0)

    def test_direct_skips_the_draft(self):
        files = {"video": [self.make_video(2)], "refs": [self.make_image()]}
        quote = workflows.estimate("swap", {"model": "mock:swap", "direct": True}, {"video": 1})
        self.assertEqual([i["label"] for i in quote["items"]], ["Final (no draft)"])
        job = jobs.create("swap", {"model": "mock:swap", "direct": True}, files)
        workflows.run(job)
        self.assertEqual(job.data["state"], "done")
        self.assertNotIn("draft", job.data["steps"])


class ReviewerTests(IsolatedTest):
    def test_verdict_comes_from_the_bar_and_reviewer_sees_only_frames(self):
        import json
        from unittest import mock

        import anthropic
        import httpx2

        from motionworkflow import reviewer

        seen = {}
        report = {"retell": "A pigeon trades stocks.", "looks_off": "",
                  "scores": [{"axis": a, "score": 9, "reason": "ok"} for a in reviewer.AXES if a != "variety"]
                  + [{"axis": "variety", "score": 7, "reason": "same layout"}],
                  "problems": [{"time": 4.0, "problem": "b"}, {"time": 1.0, "problem": "a"},
                               {"time": 2.0, "problem": "c"}, {"time": 3.0, "problem": "d"}]}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return httpx2.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": seen["body"]["model"],
                "content": [{"type": "text", "text": json.dumps(report)}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})

        real = anthropic.Anthropic
        self.env(ANTHROPIC_API_KEY="sk-test")
        video = self.make_video(3)
        with mock.patch("anthropic.Anthropic",
                        side_effect=lambda **kw: real(**kw, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))):
            result = reviewer.review(video, [(0.1, 2.0, "Nobody suspects the pigeon.")], self.tmp / "review")
        self.assertEqual(result["verdict"], "RETURN")
        self.assertEqual([p["time"] for p in result["problems"]], [1.0, 2.0, 3.0])
        self.assertTrue((self.tmp / "review" / "REVIEW.md").exists())
        sent = seen["body"]["messages"][0]["content"]
        self.assertEqual(sum(1 for c in sent if c["type"] == "image"), 3)
        self.assertIn("Nobody suspects the pigeon.", sent[-1]["text"])
        self.assertEqual(seen["body"]["model"], "claude-haiku-5-5")


class VoiceAndCliTests(IsolatedTest):
    def test_voice_workflow(self):
        job = jobs.create("voice", {"text": "Nobody suspects the pigeon.", "tier": "free"})
        workflows.run(job)
        self.assertEqual(job.data["state"], "done")
        self.assertTrue(job.path("voice.wav").exists())

    def test_cli_json_output_for_agents(self):
        import contextlib
        import io
        import json

        from motionworkflow import cli

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--json", "image", "a pigeon", "--model", "mock:image", "-n", "2"])
        cli.JSON_OUTPUT = False
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["state"], "done")
        self.assertEqual(len([o for o in data["outputs"] if o["final"]]), 2)
