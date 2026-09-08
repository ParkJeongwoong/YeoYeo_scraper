"""Opt-in real Chrome checks; all pages and credentials are synthetic.

TW28_CHROME=/path/to/chrome TW28_DRIVER=/path/to/chromedriver pytest -q -s test_browser_runtime.py
"""
import json
import os
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from chromeDriver import ChromeDriver
import chromeDriver
from syncManager import ReservationLookupError, _checkAuthenticationProtection


@pytest.fixture
def local_page():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/headers":
                payload = json.dumps({name: self.headers.get(name) for name in (
                    "User-Agent", "Accept-Language", "Sec-CH-UA",
                    "Sec-CH-UA-Platform")}).encode()
                content_type = "application/json"
            else:
                payload = Path(__file__).with_name("browser_diagnostics.html").read_bytes()
                content_type = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(not os.getenv("TW28_CHROME") or not os.getenv("TW28_DRIVER"),
                    reason="Explicit isolated Chrome binaries required")
@pytest.mark.parametrize("headed", [False, True])
def test_real_browser_input_and_fingerprint(tmp_path, headed):
    if headed and not os.getenv("DISPLAY"):
        pytest.skip("GUI comparison requires an isolated DISPLAY")
    options = webdriver.ChromeOptions()
    options.binary_location = os.environ["TW28_CHROME"]
    if not headed:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-data-dir={tmp_path / 'profile'}")
    browser = webdriver.Chrome(service=Service(os.environ["TW28_DRIVER"]), options=options)
    adapter = ChromeDriver.__new__(ChromeDriver)
    adapter._closed = True
    adapter.driver = browser
    try:
        browser.get(Path(__file__).with_name("browser_diagnostics.html").as_uri())
        baseline = WebDriverWait(browser, 10).until(
            lambda d: d.execute_script("return window.browserDiagnostics"))
        adapter._applyLanguageOverrides(browser)
        browser.refresh()
        configured = WebDriverWait(browser, 10).until(
            lambda d: d.execute_script("return window.browserDiagnostics"))
        print(json.dumps({"headed": headed, "baseline": baseline, "configured": configured}, ensure_ascii=False))
        assert "HeadlessChrome/" not in configured["userAgent"]
        assert "Chrome/" in configured["userAgent"]
        assert configured["userAgentData"] == baseline["userAgentData"]
        html = '''<input id="id" value="old"><input id="pw" type="password" value="old">
          <input id="keep" type="checkbox"><button id="next">Next</button>
          <label for="toggle">Available</label><input id="toggle" type="checkbox" hidden>
          <script>window.events=[]; window.values={};
          for(const type of ['input','keydown','click']) document.addEventListener(type,e=>{
            events.push({type:e.type,id:e.target.id,trusted:e.isTrusted});
                if(type==='input' && ['id','pw'].includes(e.target.id)) values[e.target.id]=e.target.value;
          });</script>'''
        adapter.goTo("data:text/html," + quote(html))
        adapter.login("test-user", "test-password")
        assert browser.execute_script("return window.values") == {
            "id": "test-user", "pw": "test-password"}
        browser.find_element(By.CSS_SELECTOR, 'label[for="toggle"]').click()
        assert browser.find_element(By.ID, "toggle").is_selected()
        browser.find_element(By.ID, "next").click()
        events = browser.execute_script("return window.events")
        assert all(e["trusted"] for e in events if e["type"] in ("input", "keydown"))
        assert any(e["id"] == "next" and e["trusted"] for e in events)
        browser.execute_script("""
const captcha = document.createElement('input');
captcha.id = 'captcha'; captcha.hidden = true; document.body.append(captcha);
""")
        _checkAuthenticationProtection(adapter, "synthetic-test")
        browser.execute_script("document.getElementById('captcha').hidden = false")
        with pytest.raises(ReservationLookupError, match="CAPTCHA"):
            _checkAuthenticationProtection(adapter, "synthetic-test")
    finally:
        browser.quit()


@pytest.mark.skipif(not os.getenv("TW28_CHROME") or not os.getenv("TW28_DRIVER"),
                    reason="Explicit isolated Chrome binaries required")
def test_scraper_startup_language_and_persistent_profile(tmp_path, monkeypatch, local_page):
    profile = tmp_path / "scraper-profile"
    monkeypatch.setenv("CHROME_PROFILE_PATH", str(profile))
    monkeypatch.setenv("DEBUG_MODE", "false")
    monkeypatch.setenv("UC_USER_MULTI_PROCS", "false")
    binary = tmp_path / "chromedriver"
    shutil.copy2(os.environ["TW28_DRIVER"], binary)
    original = chromeDriver.uc.Chrome

    def isolated_chrome(self, options):
        return original(options=options, version_main=146,
                        use_subprocess=self.use_subprocess,
                        user_multi_procs=self.user_multi_procs,
                        driver_executable_path=str(binary),
                        browser_executable_path=os.environ["TW28_CHROME"])

    page = local_page
    with patch.object(ChromeDriver, "_startBrowser", isolated_chrome):
        for run in range(2):
            adapter = ChromeDriver()
            try:
                adapter.goTo(page)
                values = WebDriverWait(adapter.driver, 10).until(
                    lambda d: d.execute_script("return window.browserDiagnostics"))
                print(json.dumps({"scraperRun": run, "fingerprint": values}, ensure_ascii=False))
                assert values["language"] == "ko-KR"
                assert "HeadlessChrome/" not in values["userAgent"]
                assert "Chrome/" in values["userAgent"]
                assert values["languages"][0] == "ko-KR"
                assert values["intl"]["locale"] == "ko-KR"
                assert values["userAgentData"]["platform"] == "Linux"
                assert values["userAgentData"]["brands"]
                assert values["screen"]["width"] == 1920
                assert values["screen"]["height"] == 1080
                assert values["viewport"]["width"] <= values["screen"]["width"]
                headers = adapter.driver.execute_async_script("""
const done = arguments[arguments.length - 1];
fetch('/headers').then(r => r.json()).then(done).catch(e => done({error: String(e)}));
""")
                assert headers["Accept-Language"].startswith("ko-KR")
                assert "HeadlessChrome/" not in headers["User-Agent"]
                assert "Chrome/" in headers["User-Agent"]
                assert "Chromium" in headers["Sec-CH-UA"]
                assert headers["Sec-CH-UA-Platform"] == '"Linux"'
                if run == 0:
                    adapter.executeScript("localStorage.setItem('tw28-test', 'persisted')")
                    adapter.driver.add_cookie({"name": "tw28-test", "value": "persisted",
                                               "expiry": int(time.time()) + 3600})
                else:
                    assert adapter.executeScript("return localStorage.getItem('tw28-test')") == "persisted"
                    assert adapter.driver.get_cookie("tw28-test")["value"] == "persisted"
            finally:
                adapter.close()
