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
        self.assertIn("#", job.path("post.txt").read_text())

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
