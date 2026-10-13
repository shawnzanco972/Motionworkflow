"""Asset library, Presenter workflow and their API, offline with mocks."""
import json
import os
import time
import unittest

from fastapi.testclient import TestClient
from helpers import IsolatedTest

from motionworkflow import jobs, library, media, workflows


class LibraryTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        os.environ["MW_LIBRARY_DIR"] = str(self.tmp / "library")

    def tearDown(self):
        os.environ.pop("MW_LIBRARY_DIR", None)
        super().tearDown()

    def portrait(self):
        from PIL import Image

        path = self.tmp / "me.png"
        Image.new("RGB", (600, 800), (120, 90, 80)).save(path)
        return path

    def test_consent_is_required(self):
        with self.assertRaises(library.LibraryError):
            library.add_avatar(self.portrait(), "Me", consent=False)
        self.assertEqual(library.items("avatars"), [])

    def test_photo_and_video_avatars(self):
        photo = library.add_avatar(self.portrait(), "Me", consent=True)
        self.assertEqual(photo["kind"], "image")
        video = library.add_avatar(self.make_video(4), "Me moving", consent=True)
        self.assertEqual(video["kind"], "video")
        self.assertFalse(media.probe(library.get("avatars", video["id"])["path"])["has_audio"])
        self.assertEqual(len(library.items("avatars")), 2)
        library.delete("avatars", photo["id"])
        self.assertEqual(len(library.items("avatars")), 1)

    def test_voice_is_cleaned_and_has_a_short_reference(self):
        voice = library.add_voice(self.make_video(20), "My voice", consent=True, transcript="hello")
        item = library.get("voices", voice["id"])
        self.assertLessEqual(media.probe(item["reference_path"])["duration"], library.REF_SECONDS + 0.1)
        with self.assertRaises(library.LibraryError):
            library.add_voice(self.make_video(1, name="short.mp4"), "Too short", consent=True)

    def test_paths_cannot_escape(self):
        voice = library.add_voice(self.make_video(5), "V", consent=True)
        with self.assertRaises(library.LibraryError):
            library.file_path("voices", voice["id"], "../../../etc/passwd")
        with self.assertRaises(library.LibraryError):
            library.file_path("voices", "../x", "voice.wav")


class PresenterTests(IsolatedTest):
    def test_photo_avatar_with_cutaways_waits_for_voice_approval(self):
        params = {"topic": "why sleep matters", "seconds": 20, "tier": "free", "broll": True, "image_model": "mock:image"}
        job = jobs.create("presenter", params, {"avatar": [self.make_image("me.png")]})
        workflows.run(job)
        self.assertEqual(job.data["state"], "awaiting_approval", job.data.get("error"))
        self.assertEqual(job.data["awaiting"]["stage"], "voice")
        self.assertFalse(any(k.startswith("face-") for k in job.data["steps"]))
        self.assertTrue(job.path("voice.wav").exists())
        job.approve("voice")
        workflows.run(job)
        self.assertEqual(job.data["state"], "done", job.data.get("error"))
        self.assertTrue(any(k.startswith("broll-") for k in job.data["steps"]))
        final = media.probe(job.path("final.mp4"))
        self.assertTrue(final["has_audio"])
        self.assertEqual((final["width"], final["height"]), (720, 1280))
        self.assertAlmostEqual(final["duration"], media.probe(job.path("voice.wav"))["duration"], delta=0.3)
        self.assertIn("## LinkedIn", job.path("POSTS.md").read_text())

    def test_video_avatar_uses_lipsync_and_cloned_voice(self):
        files = {"avatar": [self.make_video(3, audio=False, name="me.mp4")], "voice_sample": [self.make_video(6, name="voice.mp4")]}
        job = jobs.create("presenter", {"script": "One. Two is here. Three!", "tier": "free", "review": False}, files)
        workflows.run(job)
        self.assertEqual(job.data["state"], "done", job.data.get("error"))
        models = {s["model"] for s in job.data["steps"].values()}
        self.assertIn("mock:voice-clone", models)
        self.assertIn("mock:lipsync", models)
        self.assertEqual(len(job.data["plan"]["lines"]), 3)

    def test_editing_a_line_revoices_it_and_reanimates(self):
        job = jobs.create("presenter", {"script": "First line. Second line.", "tier": "free"}, {"avatar": [self.make_image("me.png")]})
        workflows.run(job)
        job.approve("voice")
        workflows.run(job)
        self.assertEqual(job.data["state"], "done")
        workflows.redo(job, ["voice-1"], {"1": {"text": "A better second line."}})
        self.assertFalse(job.approved("voice"))
        self.assertNotIn("face-0", job.data["steps"])
        self.assertIn("voice-0", job.data["steps"])
        workflows.run(job)
        self.assertEqual(job.data["awaiting"]["stage"], "voice")
        self.assertEqual(job.data["plan"]["lines"][1]["text"], "A better second line.")

    def test_long_audio_is_split_for_the_avatar_model(self):
        from motionworkflow.workflows.presenter import _segments

        times = [(i * 10.0, i * 10.0 + 9.5) for i in range(7)]
        parts = _segments(times, 30)
        self.assertTrue(all(b - a <= 30 for a, b in parts))
        self.assertAlmostEqual(parts[0][0], 0)
        self.assertAlmostEqual(parts[-1][1], 69.5 + 0.28)
        self.assertEqual([round(p[0], 2) for p in parts], [0, 30, 60])

    def test_estimate_prices_the_avatar_by_length(self):
        self.env(FAL_KEY="x")
        quote = workflows.estimate("presenter", {"topic": "x", "seconds": 40}, {"voice_sample": 1})
        face = next(i for i in quote["items"] if i["label"].startswith("Animate"))
        self.assertEqual(face["model"], "fal:kling-avatar-std")
        self.assertAlmostEqual(face["usd"], 0.0562 * 40, places=3)
        voice = next(i for i in quote["items"] if i["label"] == "Your voice")
        self.assertEqual(voice["model"], "fal:chatterbox-clone")
        video = workflows.estimate("presenter", {"topic": "x", "seconds": 40}, {"avatar_is_video": True})
        self.assertEqual(next(i for i in video["items"] if i["label"].startswith("Animate"))["model"], "fal:sync-lipsync")


class LibraryApiTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        os.environ["MW_LIBRARY_DIR"] = str(self.tmp / "library")
        from motionworkflow.server import app

        self.client = TestClient(app, base_url="http://127.0.0.1")

    def tearDown(self):
        os.environ.pop("MW_LIBRARY_DIR", None)
        super().tearDown()

    def wait(self, job_id):
        for _ in range(300):
            data = self.client.get(f"/api/jobs/{job_id}").json()
            if data["state"] in ("done", "error", "awaiting_approval") and not data["active"]:
                return data
            time.sleep(0.1)
        self.fail("job did not settle")

    def test_upload_then_use_by_id(self):
        image = self.make_image("me.png")
        from PIL import Image

        Image.new("RGB", (600, 800), (100, 100, 100)).save(image)
        with image.open("rb") as f:
            r = self.client.post("/api/library/avatars", files={"file": ("me.png", f, "image/png")}, data={"name": "Me"})
        self.assertEqual(r.status_code, 400)  # no consent
        with image.open("rb") as f:
            r = self.client.post("/api/library/avatars", files={"file": ("me.png", f, "image/png")},
                                 data={"name": "Me", "consent": "true"})
        self.assertEqual(r.status_code, 200, r.text)
        avatar = r.json()
        with self.make_video(6, name="v.mp4").open("rb") as f:
            voice = self.client.post("/api/library/voices", files={"file": ("v.mp4", f, "video/mp4")},
                                     data={"name": "Me", "consent": "true", "transcript": "hi"}).json()
        lib = self.client.get("/api/library").json()
        self.assertEqual(len(lib["avatars"]), 1)
        self.assertEqual(self.client.get(lib["avatars"][0]["thumb_url"]).status_code, 200)
        params = {"script": "Hello there. Bye now.", "tier": "free", "avatar_id": avatar["id"], "voice_id": voice["id"]}
        job = self.client.post("/api/jobs", data={"workflow": "presenter", "params": json.dumps(params)}).json()
        job = self.wait(job["id"])
        self.assertEqual(job["state"], "awaiting_approval", job.get("error"))
        self.assertIn("avatar", job["inputs"])
        self.assertIn("voice_sample", job["inputs"])
        self.assertTrue(job["thumb"].startswith(f"/files/{job['id']}/inputs/"))
        # Deleting the library item doesn't break the job: it kept a copy.
        self.assertEqual(self.client.delete(f"/api/library/avatars/{avatar['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/files/{job['id']}/{job['inputs']['avatar'][0]}").status_code, 200)

    def test_unknown_library_id_is_a_clear_error(self):
        params = {"script": "Hi.", "avatar_id": "0123456789"}
        r = self.client.post("/api/jobs", data={"workflow": "presenter", "params": json.dumps(params)})
        self.assertEqual(r.status_code, 400)

    def test_static_app_is_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        for path in ("/static/app.css", "/static/js/app.js", "/static/js/forms.js", "/static/js/pages.js"):
            self.assertEqual(self.client.get(path).status_code, 200, path)


if __name__ == "__main__":
    unittest.main()
