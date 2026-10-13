"""Test isolation: every test gets its own runs/ folder and an empty .env."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from motionworkflow import catalog, config, jobs

KEY_NAMES = [*config.KEYS, "MW_DEFAULT_TIER", "MW_CONFIRM_ABOVE", "MW_DAILY_BUDGET", "MW_MAX_COST_PER_JOB",
             "MW_ALLOW_MOCK", "MW_MAX_PARALLEL", "ENHANCOR_WEBHOOK_URL"]


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mw-test-"))
        self._saved_env = {k: os.environ.pop(k) for k in KEY_NAMES if k in os.environ}
        self._saved = (config.RUNS, config.ENV_FILE)
        config.RUNS = self.tmp / "runs"
        config.ENV_FILE = self.tmp / ".env"
        config.RUNS.mkdir()
        jobs._live.clear()
        catalog.reload()

    def tearDown(self):
        import time

        from motionworkflow import workflows

        for _ in range(100):  # let background jobs finish before their folder is deleted
            if not workflows._active:
                break
            time.sleep(0.05)
        for key in KEY_NAMES:
            os.environ.pop(key, None)
        os.environ.update(self._saved_env)
        config.RUNS, config.ENV_FILE = self._saved
        jobs._live.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, **values):
        for key, value in values.items():
            os.environ[key] = value

    def make_video(self, seconds: float = 3, audio: bool = True, name: str = "source.mp4") -> Path:
        path = self.tmp / name
        args = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=24:duration={seconds}"]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}", "-c:a", "aac"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
        subprocess.run(args, check=True)
        return path

    def make_image(self, name: str = "ref.png") -> Path:
        from PIL import Image

        path = self.tmp / name
        Image.new("RGB", (256, 256), (200, 60, 90)).save(path)
        return path
