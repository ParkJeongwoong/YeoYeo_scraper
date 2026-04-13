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
from typing import Optional, List
from urllib.parse import urlparse

# fcntl is Linux/Unix only - used for profile locking
if platform.system() != "Windows":
    import fcntl
else:
    fcntl = None  # type: ignore

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

# Timeout configurations (seconds)
BROWSER_STARTUP_TIMEOUT = int(os.getenv("BROWSER_STARTUP_TIMEOUT", "60"))
BROWSER_CLEANUP_TIMEOUT = int(os.getenv("BROWSER_CLEANUP_TIMEOUT", "10"))
PROCESS_KILL_TIMEOUT = int(os.getenv("PROCESS_KILL_TIMEOUT", "5"))
PROFILE_LOCK_TIMEOUT = int(os.getenv("PROFILE_LOCK_TIMEOUT", "30"))

# Global browser semaphore for concurrency control
_browser_semaphore = threading.Semaphore(MAX_CONCURRENT_BROWSERS)
_active_drivers = weakref.WeakSet()
_driver_lock = threading.Lock()
_profile_locks: dict = {}  # profile_path -> (lock_file_handle, lock_file_path)
_profile_locks_mutex = threading.Lock()


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
    
    # Guard against division by zero
    if fd_limit <= 0:
        logger.debug("%sFD status: count=%d, limit unavailable", prefix, fd_count)
        return
    
    fd_percentage = (fd_count / fd_limit) * 100
    
    if fd_count >= FD_CRITICAL_THRESHOLD:
        logger.critical(
            "%sFD CRITICAL: %d/%d (%.1f%%) - Risk of 'Too many open files' error",
            prefix, fd_count, fd_limit, fd_percentage
        )
    elif fd_count >= FD_WARNING_THRESHOLD:
        logger.warning(
            "%sFD WARNING: %d/%d (%.1f%%) - Consider reducing concurrent browsers",
            prefix, fd_count, fd_limit, fd_percentage
        )
    else:
        logger.info(
            "%sFD status: %d/%d (%.1f%%)",
            prefix, fd_count, fd_limit, fd_percentage
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


# =============================================================================
# Profile Lock Management (fcntl-based for Linux)
# =============================================================================

class ProfileLockError(Exception):
    """Raised when profile lock cannot be acquired."""
    pass


def _get_profile_lock_path(profile_path: str) -> str:
    """Get the lock file path for a profile."""
    return os.path.join(profile_path, ".profile.lock")


def _acquire_profile_lock(profile_path: str, timeout: float = PROFILE_LOCK_TIMEOUT) -> bool:
    """
    Acquire exclusive lock on profile directory.
    Returns True if lock acquired, False if timeout.
    """
    if platform.system() == "Windows":
        logger.debug("Profile locking not supported on Windows, skipping")
        return True
    
    if not profile_path or not os.path.isdir(profile_path):
        logger.debug("Profile path does not exist, skipping lock: %s", profile_path)
        return True
    
    lock_path = _get_profile_lock_path(profile_path)
    
    with _profile_locks_mutex:
        if profile_path in _profile_locks:
            logger.warning("Profile lock already held by this process: %s", profile_path)
            return True
    
    start_time = time.time()
    lock_file = None
    
    try:
        # Create lock file if not exists
        lock_file = open(lock_path, "w")
        
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Lock acquired
                lock_file.write(f"pid={os.getpid()}\ntime={time.time()}\n")
                lock_file.flush()
                
                with _profile_locks_mutex:
                    _profile_locks[profile_path] = (lock_file, lock_path)
                
                logger.info("Profile lock acquired: %s (pid=%d)", profile_path, os.getpid())
                return True
                
            except (IOError, OSError) as e:
                if e.errno not in (11, 35):  # EAGAIN, EWOULDBLOCK
                    raise
                
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    logger.error(
                        "Profile lock timeout after %.1fs: %s",
                        elapsed, profile_path
                    )
                    lock_file.close()
                    return False
                
                time.sleep(0.5)
                
    except Exception:
        logger.exception("Failed to acquire profile lock: %s", profile_path)
        if lock_file:
            try:
                lock_file.close()
            except Exception:
                pass
        return False


def _release_profile_lock(profile_path: str):
    """Release profile lock."""
    if platform.system() == "Windows":
        return
    
    if not profile_path:
        return
    
    with _profile_locks_mutex:
        lock_info = _profile_locks.pop(profile_path, None)
    
    if lock_info is None:
        logger.debug("No profile lock to release: %s", profile_path)
        return
    
    lock_file, lock_path = lock_info
    
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
        logger.info("Profile lock released: %s", profile_path)
    except Exception:
        logger.exception("Failed to release profile lock: %s", profile_path)


# =============================================================================
# Process Detection and Management
# =============================================================================

def _is_pid_alive(pid: int) -> bool:
    """Check if a process with given PID is alive."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # Signal 0 just checks if process exists
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we don't have permission
    except Exception:
        return False


def _find_processes_using_profile(profile_path: str) -> List[dict]:
    """
    Find Chrome/ChromeDriver processes using the given profile path.
    Returns list of dicts with 'pid', 'cmdline', 'name'.
    """
    if platform.system() != "Linux":
        return []
    
    if not profile_path:
        return []
    
    processes = []
    pattern = f"--user-data-dir={profile_path}"
    
    try:
        # Use pgrep to find matching processes
        result = subprocess.run(
            ["pgrep", "-af", pattern],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                parts = line.split(maxsplit=1)
                if len(parts) >= 1:
                    try:
                        pid = int(parts[0])
                        cmdline = parts[1] if len(parts) > 1 else ""
                        processes.append({
                            "pid": pid,
                            "cmdline": cmdline,
                            "name": "chrome" if "chrome" in cmdline.lower() else "unknown"
                        })
                    except ValueError:
                        continue
    except subprocess.TimeoutExpired:
        logger.warning("pgrep timeout while searching for profile processes")
    except FileNotFoundError:
        logger.debug("pgrep not available")
    except Exception:
        logger.exception("Failed to find processes using profile")
    
    # Note: We intentionally do NOT search for all chromedriver processes here.
    # Searching "pgrep -af chromedriver" would return ALL chromedriver instances,
    # including those from other sessions/profiles, which could lead to
    # unintended termination of unrelated browser sessions.
    # Chrome processes with --user-data-dir are sufficient for profile-based cleanup.
    
    logger.debug("Found %d processes using profile %s: %s", 
                 len(processes), profile_path, [p["pid"] for p in processes])
    return processes


def _get_child_pids(parent_pid: int) -> List[int]:
    """Get all child PIDs of a process (Linux only)."""
    if platform.system() != "Linux":
        return []
    
    children = []
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(parent_pid)],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                try:
                    children.append(int(line.strip()))
                except ValueError:
                    continue
    except Exception:
        pass
    
    return children


def _wait_for_pid_exit(pid: int, timeout: float = PROCESS_KILL_TIMEOUT) -> bool:
    """
    Wait for a process to exit.
    Returns True if process exited, False if timeout.
    """
    if not _is_pid_alive(pid):
        return True
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.1)
    
    return not _is_pid_alive(pid)


def _terminate_process_tree(pid: int, timeout: float = PROCESS_KILL_TIMEOUT) -> bool:
    """
    Terminate a process and all its children.
    First tries SIGTERM, then SIGKILL if needed.
    Returns True if all processes terminated.
    """
    if not _is_pid_alive(pid):
        logger.debug("Process already dead: pid=%d", pid)
        return True
    
    # Collect all PIDs in the tree
    all_pids = [pid]
    children = _get_child_pids(pid)
    all_pids.extend(children)
    
    # Recursively get grandchildren
    for child in children:
        all_pids.extend(_get_child_pids(child))
    
    all_pids = list(set(all_pids))  # Remove duplicates
    logger.info("Terminating process tree: root=%d, all_pids=%s", pid, all_pids)
    
    # Phase 1: SIGTERM
    for p in all_pids:
        try:
            os.kill(p, signal.SIGTERM)
            logger.debug("Sent SIGTERM to pid=%d", p)
        except ProcessLookupError:
            pass
        except Exception:
            logger.debug("Failed to send SIGTERM to pid=%d", p)
    
    # Wait for graceful termination using actual timeout
    term_timeout = min(timeout / 2, 3.0)  # Cap at 3 seconds for SIGTERM phase
    wait_interval = 0.2
    elapsed = 0.0
    
    while elapsed < term_timeout:
        still_alive = [p for p in all_pids if _is_pid_alive(p)]
        if not still_alive:
            break
        time.sleep(wait_interval)
        elapsed += wait_interval
    
    still_alive = [p for p in all_pids if _is_pid_alive(p)]
    
    if not still_alive:
        logger.info("All processes terminated gracefully: %s", all_pids)
        return True
    
    # Phase 2: SIGKILL for remaining
    logger.warning("Processes still alive after SIGTERM, sending SIGKILL: %s", still_alive)
    for p in still_alive:
        try:
            os.kill(p, FORCE_KILL_SIGNAL)
            logger.debug("Sent SIGKILL to pid=%d", p)
        except ProcessLookupError:
            pass
        except Exception:
            logger.debug("Failed to send SIGKILL to pid=%d", p)
    
    # Final wait
    time.sleep(0.5)
    final_alive = [p for p in still_alive if _is_pid_alive(p)]
    
    if final_alive:
        logger.error("Failed to kill processes: %s", final_alive)
        return False
    
    logger.info("All processes terminated after SIGKILL: %s", all_pids)
    return True


def _cleanup_orphan_processes_for_profile(profile_path: str) -> bool:
    """
    Find and terminate any orphan Chrome/ChromeDriver processes using the profile.
    Returns True if cleanup was performed.
    """
    if platform.system() != "Linux":
        return False
    
    if not profile_path:
        return False
    
    processes = _find_processes_using_profile(profile_path)
    
    if not processes:
        logger.debug("No orphan processes found for profile: %s", profile_path)
        return False
    
    logger.warning(
        "Found %d orphan processes for profile %s: %s",
        len(processes), profile_path, [p["pid"] for p in processes]
    )
    
    all_terminated = True
    for proc in processes:
        pid = proc["pid"]
        if not _terminate_process_tree(pid):
            all_terminated = False
    
    if all_terminated:
        logger.info("All orphan processes terminated for profile: %s", profile_path)
    else:
        logger.error("Some orphan processes could not be terminated for profile: %s", profile_path)
    
    return True


def _cleanup_profile_artifacts_if_safe(profile_path: str, stale_files: tuple) -> bool:
    """
    Clean up stale profile files only if no processes are using the profile.
    Returns True if cleanup was performed.
    """
    if not profile_path or not os.path.isdir(profile_path):
        return False
    
    # Check if any processes are using this profile
    processes = _find_processes_using_profile(profile_path)
    
    if processes:
        logger.warning(
            "Cannot clean profile artifacts - %d processes still using profile: %s",
            len(processes), profile_path
        )
        return False
    
    cleaned = False
    for file_name in stale_files:
        target_path = os.path.join(profile_path, file_name)
        try:
            if os.path.lexists(target_path):
                os.remove(target_path)
                logger.info("Removed stale profile file: %s (no active processes)", target_path)
                cleaned = True
        except FileNotFoundError:
            continue
        except Exception:
            logger.exception("Failed to remove stale profile file: %s", target_path)
    
    return cleaned


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
        self._profile_lock_acquired = False  # Track if we hold the profile lock
        
        log_fd_status("ChromeDriver.__init__ start")
        
        try:
            # Step 1: Acquire profile lock (if using profile)
            # If lock acquisition fails, try cleaning orphan processes first and retry
            if self.chrome_profile_path:
                if not self._try_acquire_profile_lock_with_orphan_cleanup():
                    raise ProfileLockError(
                        f"Could not acquire profile lock within {PROFILE_LOCK_TIMEOUT}s "
                        f"(even after orphan cleanup): {self.chrome_profile_path}"
                    )
            
            # Step 2: Clean up stale profile artifacts (only if safe)
            # Note: Orphan cleanup is now done in _try_acquire_profile_lock_with_orphan_cleanup
            if self.chrome_profile_path:
                _cleanup_profile_artifacts_if_safe(
                    self.chrome_profile_path, 
                    self.STALE_PROFILE_FILES
                )
            
            # Step 4: Build options and start browser
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
    
    def _try_acquire_profile_lock_with_orphan_cleanup(self) -> bool:
        """
        Try to acquire profile lock. If it fails, clean up orphan processes and retry.
        Returns True if lock acquired, False otherwise.
        """
        if not self.chrome_profile_path:
            return True
        
        # First attempt: try to acquire lock with short timeout
        short_timeout = min(PROFILE_LOCK_TIMEOUT / 3, 5.0)
        if _acquire_profile_lock(self.chrome_profile_path, timeout=short_timeout):
            self._profile_lock_acquired = True
            return True
        
        # Lock acquisition failed - likely orphan process holding it
        logger.warning(
            "Profile lock acquisition failed (timeout=%.1fs), attempting orphan cleanup: %s",
            short_timeout, self.chrome_profile_path
        )
        
        # Clean up orphan processes
        _cleanup_orphan_processes_for_profile(self.chrome_profile_path)
        
        # Wait briefly for processes to fully terminate
        time.sleep(0.5)
        
        # Second attempt: try again with remaining timeout
        remaining_timeout = PROFILE_LOCK_TIMEOUT - short_timeout - 0.5
        if remaining_timeout > 0 and _acquire_profile_lock(self.chrome_profile_path, timeout=remaining_timeout):
            self._profile_lock_acquired = True
            logger.info("Profile lock acquired after orphan cleanup: %s", self.chrome_profile_path)
            return True
        
        logger.error(
            "Profile lock acquisition failed even after orphan cleanup: %s",
            self.chrome_profile_path
        )
        return False
    
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
        logger.info("Emergency cleanup triggered")
        
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
        
        # Release profile lock if held
        if self._profile_lock_acquired and self.chrome_profile_path:
            _release_profile_lock(self.chrome_profile_path)
            self._profile_lock_acquired = False

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
        """
        Resolve profile path for browser options.
        Note: Stale file cleanup is now done in __init__ before browser start,
        not here, to ensure proper process checking.
        """
        if not include_profile:
            self.active_chrome_profile_path = None
            return None

        if not self.chrome_profile_path:
            self.active_chrome_profile_path = None
            return None

        # Stale file cleanup is already done in __init__ via _cleanup_profile_artifacts_if_safe
        self.active_chrome_profile_path = self.chrome_profile_path
        return self.chrome_profile_path

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
        startup_start_time = time.time()
        
        # Attempt 1: With profile (if configured)
        try:
            browser = self._startBrowserSafe(options, timeout=BROWSER_STARTUP_TIMEOUT)
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
                browser = self._startBrowserSafe(retry_options, timeout=BROWSER_STARTUP_TIMEOUT)
            except Exception as e:
                # CRITICAL: Clean up any partial browser from failed retry
                self._cleanup_partial_browser()
                raise BrowserStartupError(
                    f"Chrome failed to start after retry: {e}"
                ) from last_exception

        if browser is None:
            raise BrowserStartupError("Chrome failed to start: no browser instance created")

        self._cleanup_metadata = self._capture_cleanup_metadata(browser)
        startup_elapsed = time.time() - startup_start_time
        logger.info(
            "Chrome driver started in %.1fs: %s", 
            startup_elapsed, self._cleanup_metadata
        )
        
        # Step 5: Startup health check - verify session is actually working
        if not self._perform_startup_health_check(browser):
            logger.error("Startup health check failed, cleaning up browser")
            self._force_kill_browser(browser)
            raise BrowserStartupError(
                "Browser started but session health check failed (InvalidSessionIdException or DevTools disconnected)"
            )
        
        # Step 6: Apply language overrides (only after health check passes)
        try:
            self._applyLanguageOverrides(browser)
            logger.debug("Language overrides applied successfully")
        except Exception as e:
            # Language override failure after health check is a critical error
            logger.error("Failed to apply language overrides after health check: %s", e)
            self._force_kill_browser(browser)
            raise BrowserStartupError(
                f"Browser started but language override failed: {e}"
            ) from e
        
        return browser
    
    def _perform_startup_health_check(self, browser) -> bool:
        """
        Perform startup health check to verify browser session is working.
        Returns True if healthy, False otherwise.
        """
        try:
            # Simple script execution test
            result = browser.execute_script("return 1 + 1")
            if result != 2:
                logger.warning("Health check: unexpected result %s", result)
                return False
            
            # Verify we can access basic browser properties
            _ = browser.current_url
            _ = browser.title
            
            logger.info("Startup health check passed")
            return True
            
        except Exception as e:
            error_str = str(e).lower()
            if "invalid session" in error_str or "not connected" in error_str:
                logger.error(
                    "Startup health check failed with session error: %s "
                    "(entering forced cleanup path)", e
                )
            else:
                logger.error("Startup health check failed: %s", e)
            return False
    
    def _startBrowserSafe(self, options, timeout: float = BROWSER_STARTUP_TIMEOUT) -> uc.Chrome:
        """
        Start browser with tracking for cleanup on failure.
        Includes timeout monitoring for startup.
        """
        browser = None
        start_time = time.time()
        
        try:
            browser = self._startBrowser(options)
            
            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.warning(
                    "Browser startup took %.1fs (exceeded timeout of %.1fs)",
                    elapsed, timeout
                )
            
            self._partial_browser = None  # Success, clear partial tracking
            return browser
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                "Browser startup failed after %.1fs (timeout=%.1fs): %s",
                elapsed, timeout, e
            )
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
        """Force kill a browser instance and its processes including children."""
        if browser is None:
            return
        
        # Extract PIDs before quit attempt (they may become unavailable after)
        service = getattr(browser, "service", None)
        service_process = getattr(service, "process", None)
        service_pid = getattr(service_process, "pid", None)
        browser_pid = getattr(browser, "browser_pid", None)
        
        logger.info(
            "Force killing browser: browser_pid=%s, service_pid=%s",
            browser_pid, service_pid
        )
        
        # Try graceful quit first
        try:
            browser.quit()
            # Wait briefly and check if processes actually terminated
            time.sleep(0.5)
            browser_alive = _is_pid_alive(browser_pid) if browser_pid else False
            service_alive = _is_pid_alive(service_pid) if service_pid else False
            
            if not browser_alive and not service_alive:
                logger.info("Browser quit successfully, all processes terminated")
                return
            else:
                logger.warning(
                    "Browser quit returned but processes still alive: "
                    "browser_pid=%s (alive=%s), service_pid=%s (alive=%s)",
                    browser_pid, browser_alive, service_pid, service_alive
                )
        except Exception as e:
            logger.debug("Graceful quit failed: %s, attempting force kill", e)
        
        # Force terminate process trees (including children)
        for name, pid in [("browser", browser_pid), ("service", service_pid)]:
            if pid and _is_pid_alive(pid):
                logger.info("Force terminating %s process tree: pid=%d", name, pid)
                if not _terminate_process_tree(pid, timeout=PROCESS_KILL_TIMEOUT):
                    logger.error("Failed to terminate %s process tree: pid=%d", name, pid)
        
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
        cleanup_start_time = time.time()

        if browser is None:
            self._closed = True
            self._release_profile_lock_if_held()
            return

        if self.debug_mode and self.has_display_server:
            logger.info("Skipping Chrome driver close because DEBUG_MODE is enabled")
            self._closed = True
            self._release_profile_lock_if_held()
            return

        # Capture PIDs before quit attempt (they may become unavailable after)
        metadata = self._cleanup_metadata or {}
        browser_pid = metadata.get("browserPid")
        service_pid = metadata.get("servicePid")
        
        quit_succeeded = False
        try:
            browser.quit()
            quit_succeeded = True
            logger.info("Chrome driver quit() returned successfully")
        except Exception as e:
            error_str = str(e).lower()
            if "invalid session" in error_str or "not connected" in error_str:
                logger.warning(
                    "Chrome driver quit failed with session error: %s "
                    "(entering forced cleanup path)", e
                )
            else:
                logger.exception("Chrome driver quit failed; starting fallback cleanup")
        
        # Step 1: Verify actual process termination (regardless of quit success)
        all_terminated = self._verify_and_force_terminate_processes(
            browser_pid, service_pid, timeout=BROWSER_CLEANUP_TIMEOUT
        )
        
        if not all_terminated:
            logger.warning(
                "Some processes still alive after cleanup timeout, forcing kill"
            )
            # Force kill any remaining processes
            self._cleanup_linux_processes()
        
        # Step 2: Close subprocess pipes
        self._close_subprocess_pipes(browser)
        
        # Step 3: Final cleanup
        cleanup_elapsed = time.time() - cleanup_start_time
        logger.info(
            "Chrome driver close completed in %.1fs: quit_succeeded=%s, "
            "browser_pid=%s, service_pid=%s, all_terminated=%s",
            cleanup_elapsed, quit_succeeded, browser_pid, service_pid, all_terminated
        )
        
        self.driver = None
        self._closed = True
        
        # Unregister from tracking
        with _driver_lock:
            _active_drivers.discard(self)
        
        # Release profile lock
        self._release_profile_lock_if_held()
        
        log_fd_status("ChromeDriver.close complete")
    
    def _release_profile_lock_if_held(self):
        """Release profile lock if this instance holds it."""
        if self._profile_lock_acquired and self.chrome_profile_path:
            _release_profile_lock(self.chrome_profile_path)
            self._profile_lock_acquired = False
    
    def _verify_and_force_terminate_processes(
        self, 
        browser_pid: Optional[int], 
        service_pid: Optional[int],
        timeout: float = BROWSER_CLEANUP_TIMEOUT
    ) -> bool:
        """
        Verify browser and service processes have terminated.
        If not, force terminate them.
        Returns True if all processes are terminated.
        """
        pids_to_check = []
        if browser_pid:
            pids_to_check.append(("browser", browser_pid))
        if service_pid:
            pids_to_check.append(("service", service_pid))
        
        if not pids_to_check:
            logger.debug("No PIDs to verify for termination")
            return True
        
        # First, wait briefly for graceful termination
        time.sleep(0.5)
        
        still_alive = []
        for name, pid in pids_to_check:
            if _is_pid_alive(pid):
                still_alive.append((name, pid))
                logger.warning("Process still alive after quit: %s (pid=%d)", name, pid)
        
        if not still_alive:
            logger.info(
                "All processes terminated gracefully: %s",
                [(name, pid) for name, pid in pids_to_check]
            )
            return True
        
        # Force terminate remaining processes
        all_terminated = True
        for name, pid in still_alive:
            logger.info("Force terminating %s process tree: pid=%d", name, pid)
            if not _terminate_process_tree(pid, timeout=timeout):
                all_terminated = False
                logger.error("Failed to terminate %s process: pid=%d", name, pid)
        
        return all_terminated
    
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
            logger.warning(
                "ChromeDriver was not properly closed, cleaning up in __del__ "
                "(profile=%s, browser_pid=%s)",
                self.chrome_profile_path,
                self._cleanup_metadata.get("browserPid") if self._cleanup_metadata else None
            )
            try:
                self.close()
            except Exception:
                # Last resort: at least try to release profile lock
                try:
                    self._release_profile_lock_if_held()
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

        # Use arguments[0] to safely pass values and avoid JavaScript injection
        self.driver.execute_script(
            "document.querySelector('input[id=\"id\"]').setAttribute('value', arguments[0])",
            id
        )
        self.wait(1)
        self.driver.execute_script(
            "document.querySelector('input[id=\"pw\"]').setAttribute('value', arguments[0])",
            pw
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
        
        try:
            # 전체 페이지 크기 계산
            totalWidth = self.driver.execute_script("return document.body.scrollWidth")
            totalHeight = self.driver.execute_script("return document.body.scrollHeight")
            
            # 윈도우 사이즈를 전체 페이지 크기로 변경
            self.driver.set_window_size(totalWidth, totalHeight)
            time.sleep(0.5)  # 리사이즈 완료 대기
            
            # 스크린샷 촬영
            result = self.driver.save_screenshot(path)
            return result
        finally:
            # 원래 윈도우 사이즈로 복원 (예외 발생 시에도 실행)
            self.driver.set_window_size(originalSize['width'], originalSize['height'])

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
