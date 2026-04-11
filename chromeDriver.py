import atexit
import driver
import logging
import os
import platform
import signal
import subprocess
import threading
import time
import weakref
from contextlib import contextmanager
from typing import Optional
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

# FD monitoring thresholds
FD_WARNING_THRESHOLD = int(os.getenv("FD_WARNING_THRESHOLD", "800"))
FD_CRITICAL_THRESHOLD = int(os.getenv("FD_CRITICAL_THRESHOLD", "950"))
MAX_CONCURRENT_BROWSERS = int(os.getenv("MAX_CONCURRENT_BROWSERS", "3"))

# Global browser semaphore for concurrency control
_browser_semaphore = threading.Semaphore(MAX_CONCURRENT_BROWSERS)
_active_drivers = weakref.WeakSet()
_driver_lock = threading.Lock()


def get_fd_count() -> int:
    """Get current process file descriptor count (Linux/macOS only)."""
    if platform.system() == "Windows":
        return -1
    try:
        fd_dir = "/proc/self/fd"
        if os.path.isdir(fd_dir):
            return len(os.listdir(fd_dir))
        # macOS fallback
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return soft  # Return limit as approximation
    except Exception:
        return -1


def get_fd_limit() -> int:
    """Get file descriptor limit (Linux/macOS only)."""
    if platform.system() == "Windows":
        return -1
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return soft
    except Exception:
        return -1


def log_fd_status(context: str = ""):
    """Log current FD usage with warning if high."""
    fd_count = get_fd_count()
    fd_limit = get_fd_limit()
    if fd_count < 0:
        return
    
    prefix = f"[{context}] " if context else ""
    
    if fd_count >= FD_CRITICAL_THRESHOLD:
        logger.critical(
            "%sFD CRITICAL: %d/%d (%.1f%%) - Risk of 'Too many open files' error",
            prefix, fd_count, fd_limit, (fd_count / fd_limit) * 100
        )
    elif fd_count >= FD_WARNING_THRESHOLD:
        logger.warning(
            "%sFD WARNING: %d/%d (%.1f%%) - Consider reducing concurrent browsers",
            prefix, fd_count, fd_limit, (fd_count / fd_limit) * 100
        )
    else:
        logger.info(
            "%sFD status: %d/%d (%.1f%%)",
            prefix, fd_count, fd_limit, (fd_count / fd_limit) * 100
        )


def get_active_driver_count() -> int:
    """Get count of active ChromeDriver instances."""
    with _driver_lock:
        return len(_active_drivers)


def cleanup_all_drivers():
    """Emergency cleanup of all tracked drivers."""
    with _driver_lock:
        drivers = list(_active_drivers)
    
    for driver_instance in drivers:
        try:
            driver_instance.close()
        except Exception:
            logger.exception("Failed to cleanup driver during emergency shutdown")
    
    logger.info("Emergency driver cleanup completed: %d drivers processed", len(drivers))


# Register emergency cleanup on process exit
atexit.register(cleanup_all_drivers)


@contextmanager
def create_browser(timeout: float = 30.0, skip_fd_check: bool = False):
    """
    Context manager for safe browser lifecycle management.
    
    Features:
    - Concurrency control via semaphore
    - Guaranteed cleanup on exit
    - FD monitoring
    - Timeout for acquiring browser slot
    
    Usage:
        with create_browser() as driver:
            driver.goTo("https://example.com")
            # driver is automatically closed on exit
    
    Args:
        timeout: Max seconds to wait for browser slot (default 30)
        skip_fd_check: Skip FD availability check (default False)
    
    Raises:
        TimeoutError: If browser slot not available within timeout
        FDExhaustedError: If FD count is critically high
        BrowserStartupError: If browser fails to start
    """
    acquired = _browser_semaphore.acquire(timeout=timeout)
    if not acquired:
        active_count = get_active_driver_count()
        raise TimeoutError(
            f"Could not acquire browser slot within {timeout}s. "
            f"Active browsers: {active_count}/{MAX_CONCURRENT_BROWSERS}"
        )
    
    driver_instance = None
    try:
        log_fd_status("create_browser: slot acquired")
        driver_instance = ChromeDriver(skip_fd_check=skip_fd_check)
        yield driver_instance
    finally:
        if driver_instance is not None:
            try:
                driver_instance.close()
            except Exception:
                logger.exception("Failed to close browser in context manager")
        _browser_semaphore.release()
        log_fd_status("create_browser: slot released")


class BrowserStartupError(Exception):
    """Raised when browser fails to start after all retries."""
    pass


class FDExhaustedError(Exception):
    """Raised when FD count is critically high."""
    pass


class ChromeDriver(driver.Driver):
    BROWSER_LANGUAGE = "ko-KR"
    ACCEPT_LANGUAGES = "ko-KR,ko,en-US,en"
    CDP_LOCALE = "ko_KR"
    STARTUP_LANGUAGE = "ko_KR"
    TRUE_ENV_VALUES = ("1", "true", "yes", "on")
    DISPLAY_ENV_VARS = ("DISPLAY", "WAYLAND_DISPLAY")
    USER_DATA_DIR_ARGUMENT_PREFIX = "--user-data-dir="
    STALE_PROFILE_FILES = (
        "SingletonLock",
        "SingletonSocket",
        "SingletonCookie",
        "DevToolsActivePort",
    )

    def __init__(self, skip_fd_check: bool = False):
        # Pre-flight FD check
        if not skip_fd_check:
            self._check_fd_availability()
        
        self.debug_mode = self._get_bool_env("DEBUG_MODE")
        self.chrome_profile_path = os.getenv("CHROME_PROFILE_PATH")
        self.use_subprocess = self._get_bool_env("UC_USE_SUBPROCESS", default=True)
        self.has_display_server = self._has_display_server()
        self.run_headless = self._should_run_headless()
        self.active_chrome_profile_path = None
        self.driver = None
        self._closed = False
        self._cleanup_metadata = {}
        self._partial_browser = None  # Track partially started browser for cleanup
        
        log_fd_status("ChromeDriver.__init__ start")
        
        try:
            self.options = self.getOptions()
            self.driver = self.getDriver(self.options)
            self.driver.implicitly_wait(0)
            
            # Register this driver for tracking
            with _driver_lock:
                _active_drivers.add(self)
            
            log_fd_status("ChromeDriver.__init__ complete")
        except Exception:
            # Ensure cleanup on init failure
            self._emergency_cleanup()
            raise
    
    def _check_fd_availability(self):
        """Check if FD count is safe before starting browser."""
        fd_count = get_fd_count()
        if fd_count >= FD_CRITICAL_THRESHOLD:
            log_fd_status("FD check failed")
            raise FDExhaustedError(
                f"File descriptor count ({fd_count}) exceeds critical threshold ({FD_CRITICAL_THRESHOLD}). "
                "Cannot start new browser. Consider closing existing browsers or increasing ulimit."
            )
    
    def _emergency_cleanup(self):
        """Clean up any partial resources on initialization failure."""
        if self._partial_browser is not None:
            try:
                self._force_kill_browser(self._partial_browser)
            except Exception:
                logger.exception("Failed to cleanup partial browser")
            finally:
                self._partial_browser = None
        
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

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
        return self._buildOptions(include_profile=True)

    def _buildOptions(self, include_profile: bool) -> uc.ChromeOptions:
        options = uc.ChromeOptions()
        profile_path = self._resolve_profile_path(include_profile)

        # headless 옵션 설정 (디버그 모드에서는 비활성화)
        if self.run_headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        # 브라우저 윈도우 사이즈
        options.add_argument("--window-size=1920,1080")

        # 사람처럼 보이게 하는 옵션들
        options.add_argument("--disable-gpu")
        options.add_argument(f"--lang={self.STARTUP_LANGUAGE}")

        # 불필요한 에러메시지 노출 방지
        options.add_argument("--log-level=3")

        if profile_path:
            options.add_argument(
                f"{self.USER_DATA_DIR_ARGUMENT_PREFIX}{profile_path}"
            )

        return options

    def _resolve_profile_path(self, include_profile: bool):
        if not include_profile:
            self.active_chrome_profile_path = None
            return None

        if not self.chrome_profile_path:
            self.active_chrome_profile_path = None
            return None

        self._cleanup_stale_profile_files(self.chrome_profile_path)
        self.active_chrome_profile_path = self.chrome_profile_path
        return self.chrome_profile_path

    def _cleanup_stale_profile_files(self, profile_path: str):
        if not profile_path or not os.path.isdir(profile_path):
            return
        for file_name in self.STALE_PROFILE_FILES:
            target_path = os.path.join(profile_path, file_name)
            try:
                if os.path.lexists(target_path):
                    os.remove(target_path)
                    logger.info("Removed stale Chrome profile file: %s", target_path)
            except FileNotFoundError:
                continue
            except Exception:
                logger.exception(
                    "Failed to remove stale Chrome profile file: %s", target_path
                )

    def getDriver(self, options) -> uc.Chrome:
        logger.info(
            "Starting Chrome driver with debugMode=%s headless=%s useSubprocess=%s hasDisplayServer=%s profile=%s activeProfile=%s",
            self.debug_mode,
            self.run_headless,
            self.use_subprocess,
            self.has_display_server,
            self.chrome_profile_path,
            self.active_chrome_profile_path,
        )
        
        browser = None
        last_exception = None
        
        # Attempt 1: With profile (if configured)
        try:
            browser = self._startBrowserSafe(options)
        except Exception as e:
            last_exception = e
            logger.exception(
                "Chrome start failed with configured profile (attempt 1)"
            )
            # CRITICAL: Clean up any partial browser from failed attempt
            self._cleanup_partial_browser()
            
            if not self.chrome_profile_path:
                raise BrowserStartupError(
                    f"Chrome failed to start: {e}"
                ) from e
        
        # Attempt 2: Without profile (if first attempt failed and profile was configured)
        if browser is None and self.chrome_profile_path:
            logger.info("Retrying Chrome start without profile (attempt 2)")
            log_fd_status("Before retry without profile")
            
            try:
                retry_options = self._buildOptions(include_profile=False)
                self.options = retry_options
                browser = self._startBrowserSafe(retry_options)
            except Exception as e:
                # CRITICAL: Clean up any partial browser from failed retry
                self._cleanup_partial_browser()
                raise BrowserStartupError(
                    f"Chrome failed to start after retry: {e}"
                ) from last_exception

        if browser is None:
            raise BrowserStartupError("Chrome failed to start: no browser instance created")

        self._cleanup_metadata = self._capture_cleanup_metadata(browser)
        logger.info("Chrome driver started: %s", self._cleanup_metadata)
        
        try:
            self._applyLanguageOverrides(browser)
        except Exception:
            logger.exception(
                "Failed to apply Chrome language overrides; continuing with browser defaults"
            )
        return browser
    
    def _startBrowserSafe(self, options) -> uc.Chrome:
        """Start browser with tracking for cleanup on failure."""
        browser = None
        try:
            browser = self._startBrowser(options)
            self._partial_browser = None  # Success, clear partial tracking
            return browser
        except Exception:
            # Track partial browser for cleanup
            if browser is not None:
                self._partial_browser = browser
            raise
    
    def _cleanup_partial_browser(self):
        """Clean up any partially started browser."""
        if self._partial_browser is None:
            return
        
        logger.info("Cleaning up partial browser from failed startup")
        try:
            self._force_kill_browser(self._partial_browser)
        except Exception:
            logger.exception("Failed to cleanup partial browser")
        finally:
            self._partial_browser = None
            log_fd_status("After partial browser cleanup")
    
    def _force_kill_browser(self, browser):
        """Force kill a browser instance and its processes."""
        if browser is None:
            return
        
        # Try graceful quit first
        try:
            browser.quit()
            return
        except Exception:
            logger.debug("Graceful quit failed, attempting force kill")
        
        # Extract PIDs before they become unavailable
        service = getattr(browser, "service", None)
        service_process = getattr(service, "process", None)
        service_pid = getattr(service_process, "pid", None)
        browser_pid = getattr(browser, "browser_pid", None)
        
        # Kill processes
        for pid in (browser_pid, service_pid):
            if pid:
                try:
                    os.kill(pid, FORCE_KILL_SIGNAL)
                    logger.info("Force killed process pid=%s", pid)
                except ProcessLookupError:
                    pass
                except Exception:
                    logger.exception("Failed to kill pid=%s", pid)
        
        # Close subprocess pipes if accessible
        if service_process is not None:
            for pipe in (service_process.stdin, service_process.stdout, service_process.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except Exception:
                        pass

    def _startBrowser(self, options) -> uc.Chrome:
        return uc.Chrome(
            options=options,
            use_subprocess=self.use_subprocess,
            version_main=146,
        )

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
            "configuredChromeProfilePath": self.chrome_profile_path,
            "chromeProfilePath": self.active_chrome_profile_path,
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

        log_fd_status("ChromeDriver.close start")
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
            logger.exception("Chrome driver quit failed; starting fallback cleanup")
        finally:
            if quit_succeeded:
                self.driver = None
                self._closed = True
            else:
                # Try Linux-specific cleanup
                fallback_used = self._cleanup_linux_processes()
                
                # Also try to close subprocess pipes directly
                self._close_subprocess_pipes(browser)
                
                logger.info(
                    "Chrome driver fallback cleanup executed: %s", fallback_used
                )
                # Mark as closed even if fallback didn't fully work
                # to prevent repeated close attempts
                self.driver = None
                self._closed = True
            
            # Unregister from tracking
            with _driver_lock:
                _active_drivers.discard(self)
            
            log_fd_status("ChromeDriver.close complete")
    
    def _close_subprocess_pipes(self, browser):
        """Close any open subprocess pipes to prevent FD leaks."""
        try:
            service = getattr(browser, "service", None)
            if service is None:
                return
            
            process = getattr(service, "process", None)
            if process is None:
                return
            
            for pipe_name in ("stdin", "stdout", "stderr"):
                pipe = getattr(process, pipe_name, None)
                if pipe is not None:
                    try:
                        pipe.close()
                        logger.debug("Closed subprocess %s pipe", pipe_name)
                    except Exception:
                        pass
        except Exception:
            logger.exception("Failed to close subprocess pipes")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.close()
        return False  # Don't suppress exceptions
    
    def __del__(self):
        """Destructor - last resort cleanup."""
        if not self._closed:
            logger.warning("ChromeDriver was not properly closed, cleaning up in __del__")
            try:
                self.close()
            except Exception:
                pass

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
