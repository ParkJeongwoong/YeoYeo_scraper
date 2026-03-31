import driver
import logging
import os
import platform
import signal
import subprocess
import time
from urllib.parse import urlparse

import pyperclip
import undetected_chromedriver as uc
from dotenv import load_dotenv
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

logger = logging.getLogger(__name__)
FORCE_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


class ChromeDriver(driver.Driver):
    BROWSER_LANGUAGE = "ko-KR"
    ACCEPT_LANGUAGES = "ko-KR,ko,en-US,en"
    CDP_LOCALE = "ko_KR"
    TRUE_ENV_VALUES = ("1", "true", "yes", "on")
    DISPLAY_ENV_VARS = ("DISPLAY", "WAYLAND_DISPLAY")

    def __init__(self):
        self.debug_mode = self._get_bool_env("DEBUG_MODE")
        self.chrome_profile_path = os.getenv("CHROME_PROFILE_PATH")
        self.use_subprocess = self._get_bool_env("UC_USE_SUBPROCESS", default=True)
        self.has_display_server = self._has_display_server()
        self.run_headless = self._should_run_headless()
        self.driver = None
        self._closed = False
        self._cleanup_metadata = {}
        self.options = self.getOptions()
        self.driver = self.getDriver(self.options)
        self.driver.implicitly_wait(0)

    def _get_bool_env(self, name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in self.TRUE_ENV_VALUES

    def _has_display_server(self) -> bool:
        return any(os.getenv(name) for name in self.DISPLAY_ENV_VARS)

    def _should_run_headless(self) -> bool:
        if not self.debug_mode:
            return True
        if platform.system() == "Linux" and not self.has_display_server:
            return True
        return False

    def getOptions(self) -> uc.ChromeOptions:
        options = uc.ChromeOptions()

        # headless 옵션 설정 (디버그 모드에서는 비활성화)
        if self.run_headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        # 브라우저 윈도우 사이즈
        options.add_argument("--window-size=1920,1080")

        # 사람처럼 보이게 하는 옵션들
        options.add_argument("--disable-gpu")
        options.add_argument(f"--lang={self.BROWSER_LANGUAGE}")
        options.add_experimental_option(
            "prefs",
            {"intl.accept_languages": self.ACCEPT_LANGUAGES},
        )

        # 불필요한 에러메시지 노출 방지
        options.add_argument("--log-level=3")

        if self.chrome_profile_path:
            options.add_argument(f"--user-data-dir={self.chrome_profile_path}")

        return options

    def getDriver(self, options) -> uc.Chrome:
        logger.info(
            "Starting Chrome driver with debugMode=%s headless=%s useSubprocess=%s hasDisplayServer=%s profile=%s",
            self.debug_mode,
            self.run_headless,
            self.use_subprocess,
            self.has_display_server,
            self.chrome_profile_path,
        )
        browser = uc.Chrome(
            options=options,
            use_subprocess=self.use_subprocess,
            version_main=146,
        )
        self._cleanup_metadata = self._capture_cleanup_metadata(browser)
        logger.info("Chrome driver started: %s", self._cleanup_metadata)
        try:
            self._applyLanguageOverrides(browser)
        except Exception:
            logger.exception(
                "Failed to apply Chrome language overrides; continuing with browser defaults"
            )
        return browser

    def _capture_cleanup_metadata(self, browser) -> dict:
        service = getattr(browser, "service", None)
        service_process = getattr(service, "process", None)
        service_url = getattr(service, "service_url", None)
        if not service_url:
            command_executor = getattr(browser, "command_executor", None)
            service_url = getattr(command_executor, "_url", None)

        service_port = None
        if service_url:
            try:
                service_port = urlparse(service_url).port
            except ValueError:
                service_port = None

        service_pid = getattr(service_process, "pid", None)
        browser_pid = getattr(browser, "browser_pid", None)
        service_path = getattr(service, "path", None)

        return {
            "debugMode": self.debug_mode,
            "headless": self.run_headless,
            "useSubprocess": self.use_subprocess,
            "hasDisplayServer": self.has_display_server,
            "chromeProfilePath": self.chrome_profile_path,
            "servicePath": service_path,
            "servicePort": service_port,
            "servicePid": service_pid,
            "browserPid": browser_pid,
        }

    def _applyLanguageOverrides(self, browser):
        language = self.BROWSER_LANGUAGE
        cdpLocale = self.CDP_LOCALE
        languages = self.ACCEPT_LANGUAGES.split(",")
        userAgent = browser.execute_script("return navigator.userAgent;")
        platform_name = browser.execute_script("return navigator.platform;")

        browser.execute_cdp_cmd("Network.enable", {})
        browser.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {
                "userAgent": userAgent,
                "acceptLanguage": self.ACCEPT_LANGUAGES,
                "platform": platform_name,
            },
        )
        browser.execute_cdp_cmd("Emulation.setLocaleOverride", {"locale": cdpLocale})
        browser.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": f"""
Object.defineProperty(navigator, 'language', {{
    get: () => '{language}'
}});
Object.defineProperty(navigator, 'languages', {{
    get: () => {languages}
}});
""".strip()
            },
        )

    def close(self):
        if self._closed:
            return

        browser = self.driver

        if browser is None:
            self._closed = True
            return

        if self.debug_mode and self.has_display_server:
            logger.info("Skipping Chrome driver close because DEBUG_MODE is enabled")
            return

        quit_succeeded = False
        try:
            browser.quit()
            quit_succeeded = True
            logger.info("Chrome driver quit completed successfully")
        except Exception:
            logger.exception("Chrome driver quit failed; starting Linux fallback cleanup")
        finally:
            if quit_succeeded:
                self.driver = None
                self._closed = True
            else:
                fallback_used = self._cleanup_linux_processes()
                logger.info(
                    "Chrome driver fallback cleanup executed: %s", fallback_used
                )
                if fallback_used:
                    self.driver = None
                    self._closed = True

    def _cleanup_linux_processes(self) -> bool:
        if platform.system() != "Linux":
            return False

        metadata = self._cleanup_metadata or {}
        service_pid = metadata.get("servicePid")
        browser_pid = metadata.get("browserPid")
        service_port = metadata.get("servicePort")
        profile_path = metadata.get("chromeProfilePath")

        attempted = False
        for pid in (browser_pid, service_pid):
            attempted = self._signal_pid(pid, signal.SIGTERM) or attempted

        if profile_path and browser_pid is None:
            attempted = self._pkill_pattern(
                "TERM", f"--user-data-dir={profile_path}"
            ) or attempted

        if service_port and service_pid is None:
            attempted = self._pkill_pattern(
                "TERM", f"--port={service_port}"
            ) or attempted

        if attempted:
            time.sleep(0.5)

        for pid in (browser_pid, service_pid):
            attempted = self._signal_pid(pid, FORCE_KILL_SIGNAL) or attempted

        if profile_path and browser_pid is None:
            attempted = self._pkill_pattern(
                "KILL", f"--user-data-dir={profile_path}"
            ) or attempted

        if service_port and service_pid is None:
            attempted = self._pkill_pattern(
                "KILL", f"--port={service_port}"
            ) or attempted

        return attempted

    def _signal_pid(self, pid, sig) -> bool:
        if not pid:
            return False

        try:
            os.kill(pid, sig)
            logger.info("Sent signal %s to pid=%s", sig, pid)
            return True
        except ProcessLookupError:
            return False
        except Exception:
            logger.exception("Failed to signal pid=%s with signal=%s", pid, sig)
            return False

    def _pkill_pattern(self, signal_name: str, pattern: str) -> bool:
        try:
            completed = subprocess.run(
                ["pkill", f"-{signal_name}", "-f", "--", pattern],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if completed.returncode == 0:
                logger.info(
                    "Executed pkill fallback with signal=%s pattern=%s",
                    signal_name,
                    pattern,
                )
                return True
            return False
        except FileNotFoundError:
            logger.exception("pkill is not available for Chrome fallback cleanup")
            return False
        except Exception:
            logger.exception(
                "Failed to execute pkill fallback with signal=%s pattern=%s",
                signal_name,
                pattern,
            )
            return False

    def goTo(self, url):
        self.driver.get(url)
        self.wait(3)  # 페이지가 완전히 로딩되도록 3초동안 기다림

    def findBySelector(self, value):
        return self.driver.find_element(By.CSS_SELECTOR, value)

    def findByID(self, value):
        return self.driver.find_element(By.ID, value)

    def findByXpath(self, value):
        return self.driver.find_element(By.XPATH, value)

    def copyPaste(self, text):
        pyperclip.copy(text)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("v").key_up(
            Keys.CONTROL
        ).perform()

    def login(self, id, pw):
        # 페이지가 완전히 로드될 때까지 대기
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "id"))
        )

        self.driver.execute_script(
            f"document.querySelector('input[id=\"id\"]').setAttribute('value', '{id}')"
        )
        self.wait(1)
        self.driver.execute_script(
            f"document.querySelector('input[id=\"pw\"]').setAttribute('value', '{pw}')"
        )
        self.wait(1)

        # 로그인 상태 유지 체크박스 클릭
        try:
            keep_login_checkbox = self.driver.find_element(By.ID, "keep")
            if not keep_login_checkbox.is_selected():
                keep_login_checkbox.click()
                self.wait(0.5)
        except Exception:
            pass  # 체크박스가 없거나 이미 선택된 경우 무시

    def getPageSource(self):
        return self.driver.page_source

    def findChildElementsByXpath(self, element: WebElement, selector):
        return element.find_elements(By.XPATH, selector)

    def findChildElement(self, element: WebElement, selector) -> WebElement:
        return element.find_element(By.TAG_NAME, selector)

    def wait(self, seconds):
        time.sleep(seconds)

    def waitForDocumentReady(self, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            lambda current_driver: current_driver.execute_script(
                "return document.readyState"
            )
            == "complete"
        )

    def waitForAnySelector(self, selectors, timeout=10):
        def find_matching_selector(current_driver):
            for selector in selectors:
                elements = current_driver.find_elements(By.CSS_SELECTOR, selector)
                if len(elements) > 0:
                    return {
                        "selector": selector,
                        "count": len(elements),
                    }
            return False

        return WebDriverWait(self.driver, timeout).until(find_matching_selector)

    def getCurrentUrl(self):
        return self.driver.current_url

    def getTitle(self):
        return self.driver.title

    def saveScreenshot(self, path):
        return self.driver.save_screenshot(path)

    def saveFullPageScreenshot(self, path):
        """전체 페이지 스크린샷 (스크롤 포함)"""
        # 원래 윈도우 사이즈 저장
        originalSize = self.driver.get_window_size()
        
        # 전체 페이지 크기 계산
        totalWidth = self.driver.execute_script("return document.body.scrollWidth")
        totalHeight = self.driver.execute_script("return document.body.scrollHeight")
        
        # 윈도우 사이즈를 전체 페이지 크기로 변경
        self.driver.set_window_size(totalWidth, totalHeight)
        time.sleep(0.5)  # 리사이즈 완료 대기
        
        # 스크린샷 촬영
        result = self.driver.save_screenshot(path)
        
        # 원래 윈도우 사이즈로 복원
        self.driver.set_window_size(originalSize['width'], originalSize['height'])
        
        return result

    def getBrowserInfo(self):
        capabilities = self.driver.capabilities
        chrome_info = capabilities.get("chrome", {})
        chromedriver_version = chrome_info.get("chromedriverVersion", "")
        if chromedriver_version:
            chromedriver_version = chromedriver_version.split(" ")[0]
        return {
            "browserName": capabilities.get("browserName"),
            "browserVersion": capabilities.get("browserVersion"),
            "chromedriverVersion": chromedriver_version,
            "platformName": capabilities.get("platformName"),
            "seleniumVersion": uc.__version__,
            "headless": any(
                argument.startswith("--headless") for argument in self.options.arguments
            ),
            "language": self.executeScript("return navigator.language;"),
            "languages": self.executeScript("return navigator.languages;"),
            "intlLocale": self.executeScript(
                "return Intl.DateTimeFormat().resolvedOptions().locale;"
            ),
        }

    def executeScript(self, script, *args):
        return self.driver.execute_script(script, *args)
