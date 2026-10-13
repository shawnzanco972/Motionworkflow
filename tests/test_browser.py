"""Browser end-to-end test of the web app (offline, mock models).

Skipped unless Playwright and a Chromium are available:
    .venv/bin/pip install playwright && .venv/bin/playwright install chromium
Set MW_CHROMIUM to use a specific browser binary, and AXE_JS to the path of
axe.min.js (npm package axe-core) to also run an accessibility audit.
"""
import os
import socket
import threading
import time
import unittest
from pathlib import Path

from helpers import IsolatedTest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dependency
    sync_playwright = None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class BrowserTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        import uvicorn

        from motionworkflow.server import app

        self.env(MW_LIBRARY_DIR=str(self.tmp / "library"))
        self.port = _free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error"))
        threading.Thread(target=self.server.run, daemon=True).start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        self.pw = sync_playwright().start()
        kwargs = {"executable_path": os.environ["MW_CHROMIUM"]} if os.environ.get("MW_CHROMIUM") else {}
        try:
            self.browser = self.pw.chromium.launch(**kwargs)
        except Exception as exc:  # noqa: BLE001 - no browser installed
            self.pw.stop()
            self.server.should_exit = True
            self.skipTest(f"no Chromium available: {exc}")
        self.errors = []

    def tearDown(self):
        self.browser.close()
        self.pw.stop()
        self.server.should_exit = True
        time.sleep(0.2)
        super().tearDown()

    def page(self, scheme="dark", width=1366):
        page = self.browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme).new_page()
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        return page

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}/"

    def test_make_an_image_then_see_its_cost_and_find_it(self):
        page = self.page()
        page.goto(self.base)
        page.wait_for_selector("text=What are we making today?")
        page.click("nav >> text=Image")
        page.fill("textarea[name=prompt]", "a corgi giving a TED talk")
        # Pin the offline mock model (the free tier would call Pollinations over the network).
        page.eval_on_selector("select[name=model]", "el => { el.value = 'mock:image'; el.dispatchEvent(new Event('change', {bubbles: true})); }")
        page.wait_for_function("document.querySelector('[data-price]').textContent.includes('$')")
        page.click("form .summary button[type=submit]")
        page.wait_for_url("**/#/projects/*")
        page.wait_for_selector(".badge.done", timeout=30000)  # the page updates itself when the job ends
        self.assertIn("a corgi giving a TED talk", page.inner_text("h1"))
        self.assertIn("Cost", page.inner_text(".cost-card"))
        self.assertTrue(page.query_selector(".cost-pill"))

        page.click("summary[aria-label='More actions']")
        self.assertTrue(page.is_visible("text=Download everything"))
        page.keyboard.press("Escape")

        page.goto(self.base + "#/projects")
        page.fill("#projSearch", "corgi")
        page.wait_for_function("document.querySelector('#projCount').textContent.startsWith('1 project')")
        page.fill("#projSearch", "no such thing")
        page.wait_for_selector("text=No matches")

        page.goto(self.base + "#/spending")
        page.wait_for_selector("h1:has-text('Spending')")
        self.assertIn("Nothing spent yet", page.inner_text("#page"))  # mock models are free
        self.assertEqual(self.errors, [])

    def test_form_errors_are_shown_not_thrown(self):
        page = self.page("light", 390)
        page.goto(self.base + "#/create/image")
        page.wait_for_selector("textarea[name=prompt]")
        page.click(".mobile-cta button[type=submit]")
        page.wait_for_timeout(500)
        self.assertIn("#/create/image", page.url)  # stayed on the form
        self.assertEqual(page.evaluate("document.documentElement.scrollWidth"), 390)  # no sideways scroll
        self.assertEqual(self.errors, [])

    def test_every_page_renders(self):
        page = self.page()
        routes = ["#/", "#/create/presenter", "#/create/short", "#/create/image", "#/create/video", "#/create/voice",
                  "#/create/swap", "#/projects", "#/assets", "#/spending", "#/settings/keys", "#/settings/budget",
                  "#/settings/models", "#/settings/skills", "#/settings/appearance", "#/nowhere"]
        axe = Path(os.environ["AXE_JS"]).read_text() if os.environ.get("AXE_JS") else None
        problems = []
        for route in routes:
            page.goto(self.base + route)
            page.wait_for_timeout(600)
            self.assertNotIn("Couldn't load this page", page.inner_text("#page"), route)
            if axe:
                page.add_script_tag(content=axe)
                found = page.evaluate("async () => (await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa']}))"
                                      ".violations.map(v => v.id)")
                problems += [f"{route}: {v}" for v in found]
        self.assertEqual(problems, [])
        self.assertEqual(self.errors, [])
