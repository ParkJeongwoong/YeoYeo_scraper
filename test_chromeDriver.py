import gc
import logging
import signal
from unittest.mock import MagicMock, call, patch

import pytest

from chromeDriver import (
    BrowserStartupError,
    ChromeDriver,
    FDExhaustedError,
    FORCE_KILL_SIGNAL,
    _is_pid_alive,
)


class TestChromeDriverClose:
    def test_flushes_profile_before_uc_quit(self):
        browser = MagicMock()
        instance = self._make_instance(driver=browser)
        with patch("chromeDriver._is_pid_alive", return_value=False), patch.object(
            instance, "_verify_and_force_terminate_processes", return_value=True
        ):
            instance.close()
        assert browser.mock_calls.index(call.execute_cdp_cmd("Browser.close", {})) < browser.mock_calls.index(call.quit())

    def test_graceful_close_failure_still_runs_existing_cleanup(self):
        browser = MagicMock()
        browser.execute_cdp_cmd.side_effect = RuntimeError("disconnected")
        instance = self._make_instance(driver=browser)
        with patch.object(instance, "_verify_and_force_terminate_processes", return_value=True):
            instance.close()
        browser.quit.assert_called_once_with()
        assert instance._closed

    def _make_instance(self, driver=None, debug_mode=False):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = debug_mode
        instance.has_display_server = debug_mode
        instance.run_headless = not debug_mode
        instance.chrome_profile_path = "/tmp/profile"
        instance.active_chrome_profile_path = "/tmp/profile"
        instance.use_subprocess = False
        instance.user_multi_procs = False
        instance.driver = driver
        instance._closed = False
        instance._cleanup_metadata = {
            "chromeProfilePath": "/tmp/profile",
            "servicePort": 34967,
            "servicePid": 111,
            "browserPid": 222,
        }
        instance.options = MagicMock(arguments=["--headless=new"])
        return instance

    def test_close_does_not_run_fallback_when_quit_succeeds(self):
        browser = MagicMock()
        browser.command_executor = MagicMock()
        instance = self._make_instance(driver=browser)

        with patch.object(instance, "_cleanup_linux_processes", return_value=True) as mock_cleanup:
            instance.close()
            instance.close()

        browser.quit.assert_called_once()
        browser.command_executor.close.assert_called_once()
        mock_cleanup.assert_not_called()
        assert instance.driver is None
        assert instance._closed is True

    def test_close_closes_webdriver_transport_after_uc_quit(self):
        browser = MagicMock()
        browser.command_executor = MagicMock()
        instance = self._make_instance(driver=browser)

        with patch.object(instance, "_verify_and_force_terminate_processes", return_value=True):
            instance.close()

        browser.quit.assert_called_once()
        browser.command_executor.close.assert_called_once()

    def test_close_runs_fallback_when_quit_fails(self):
        browser = MagicMock()
        browser.quit.side_effect = RuntimeError("tab crashed")
        instance = self._make_instance(driver=browser)

        with patch.object(
            instance, "_verify_and_force_terminate_processes", return_value=False
        ) as mock_verify, patch.object(instance, "_cleanup_linux_processes", return_value=True) as mock_cleanup:
            instance.close()

        browser.quit.assert_called_once()
        mock_verify.assert_called_once()
        mock_cleanup.assert_called_once()
        assert instance.driver is None
        assert instance._closed is True

    def test_close_skips_cleanup_in_debug_mode(self):
        browser = MagicMock()
        instance = self._make_instance(driver=browser, debug_mode=True)

        with patch.object(instance, "_cleanup_linux_processes", return_value=True) as mock_cleanup:
            instance.close()

        browser.quit.assert_not_called()
        mock_cleanup.assert_not_called()
        assert instance.driver is browser
        assert instance._closed is True

    def test_close_remains_idempotent_when_quit_fails_without_fallback(self):
        browser = MagicMock()
        browser.quit.side_effect = RuntimeError("tab crashed")
        instance = self._make_instance(driver=browser)

        with patch.object(
            instance, "_verify_and_force_terminate_processes", return_value=False
        ) as mock_verify, patch.object(instance, "_cleanup_linux_processes", return_value=False) as mock_cleanup:
            instance.close()
            instance.close()

        assert browser.quit.call_count == 1
        assert mock_verify.call_count == 1
        assert mock_cleanup.call_count == 1
        assert instance.driver is None
        assert instance._closed is True


class TestChromeDriverLinuxCleanup:
    def _make_instance(self, metadata):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = False
        instance.has_display_server = False
        instance.run_headless = True
        instance.chrome_profile_path = metadata.get("chromeProfilePath")
        instance.active_chrome_profile_path = metadata.get("chromeProfilePath")
        instance.use_subprocess = False
        instance.user_multi_procs = False
        instance.driver = None
        instance._closed = False
        instance._cleanup_metadata = metadata
        instance.options = MagicMock(arguments=["--headless=new"])
        return instance

    def test_cleanup_linux_processes_signals_known_pids(self):
        instance = self._make_instance(
            {
                "chromeProfilePath": "/tmp/profile",
                "servicePort": 34967,
                "servicePid": 111,
                "browserPid": 222,
            }
        )

        with patch("chromeDriver.platform.system", return_value="Linux"), patch(
            "chromeDriver.os.kill"
        ) as mock_kill, patch("chromeDriver.time.sleep"):
            assert instance._cleanup_linux_processes() is True

        mock_kill.assert_any_call(222, signal.SIGTERM)
        mock_kill.assert_any_call(111, signal.SIGTERM)
        mock_kill.assert_any_call(222, FORCE_KILL_SIGNAL)
        mock_kill.assert_any_call(111, FORCE_KILL_SIGNAL)

    def test_cleanup_linux_processes_uses_pkill_patterns_without_pids(self):
        instance = self._make_instance(
            {
                "chromeProfilePath": "/tmp/profile",
                "servicePort": 34967,
                "servicePid": None,
                "browserPid": None,
            }
        )

        completed = MagicMock(returncode=0)
        with patch("chromeDriver.platform.system", return_value="Linux"), patch(
            "chromeDriver.subprocess.run", return_value=completed
        ) as mock_run, patch("chromeDriver.time.sleep"):
            assert instance._cleanup_linux_processes() is True

        patterns = [command.args[0][-1] for command in mock_run.call_args_list]
        assert "--user-data-dir=/tmp/profile" in patterns
        assert "--port=34967" in patterns

    def test_cleanup_linux_processes_is_noop_outside_linux(self):
        instance = self._make_instance(
            {
                "chromeProfilePath": "/tmp/profile",
                "servicePort": 34967,
                "servicePid": 111,
                "browserPid": 222,
            }
        )

        with patch("chromeDriver.platform.system", return_value="Windows"), patch(
            "chromeDriver.os.kill"
        ) as mock_kill, patch("chromeDriver.subprocess.run") as mock_run:
            assert instance._cleanup_linux_processes() is False

        mock_kill.assert_not_called()
        mock_run.assert_not_called()


class TestChromeDriverInitialization:
    def _make_instance(self):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = False
        instance.has_display_server = False
        instance.run_headless = True
        instance.chrome_profile_path = "/tmp/profile"
        instance.active_chrome_profile_path = "/tmp/profile"
        instance.use_subprocess = False
        instance.user_multi_procs = False
        instance.driver = None
        instance._closed = False
        instance._cleanup_metadata = {}
        instance._partial_browser = None
        instance.options = MagicMock(arguments=["--headless=new"])
        return instance

    def test_get_driver_keeps_browser_when_language_overrides_fail(self):
        """
        CD-003: Language override failure is non-fatal.

        If the browser started successfully AND passed the health check, a
        subsequent CDP failure in _applyLanguageOverrides must NOT kill the
        browser or raise BrowserStartupError - the browser is still usable
        for the actual request. We only log a warning and return the browser.
        """
        instance = self._make_instance()
        options = MagicMock()
        browser = MagicMock()

        with patch.object(instance, "_startBrowser", return_value=browser) as mock_start_browser, patch.object(
            instance, "_capture_cleanup_metadata", return_value={"servicePort": 1234}
        ) as mock_capture, patch.object(
            instance, "_perform_startup_health_check", return_value=True
        ) as mock_health_check, patch.object(
            instance, "_applyLanguageOverrides", side_effect=RuntimeError("cdp failed")
        ) as mock_apply, patch.object(
            instance, "_force_kill_browser"
        ) as mock_force_kill:
            result = instance.getDriver(options)

        assert result is browser
        assert instance._cleanup_metadata == {"servicePort": 1234}
        mock_start_browser.assert_called_once_with(options)
        mock_capture.assert_called_once_with(browser)
        mock_health_check.assert_called_once_with(browser)
        mock_apply.assert_called_once_with(browser)
        mock_force_kill.assert_not_called()

    def test_start_browser_safe_treats_timeout_exceedance_as_failure(self):
        instance = self._make_instance()
        options = MagicMock()
        browser = MagicMock()

        with patch.object(instance, "_startBrowser", return_value=browser), patch(
            "chromeDriver.time.time", side_effect=[100.0, 161.2]
        ), patch(
            "chromeDriver.logger.error"
        ), patch.object(instance, "_cleanup_partial_browser") as mock_cleanup:
            with pytest.raises(TimeoutError, match="Browser startup exceeded timeout"):
                instance._startBrowserSafe(options, timeout=60.0)

        assert instance._partial_browser is browser
        mock_cleanup.assert_called_once_with()
        instance._closed = True

    def test_force_kill_browser_closes_transport_when_quit_terminates_processes(self):
        instance = self._make_instance()
        browser = MagicMock()
        browser.browser_pid = 222
        browser.command_executor = MagicMock()
        service_process = MagicMock()
        service_process.pid = 111
        service_process.stdin = MagicMock()
        service_process.stdout = MagicMock()
        service_process.stderr = MagicMock()
        browser.service.process = service_process

        with patch("chromeDriver._is_pid_alive", return_value=False), patch("chromeDriver.time.sleep"):
            instance._force_kill_browser(browser)

        browser.quit.assert_called_once()
        browser.command_executor.close.assert_called_once()
        service_process.stdin.close.assert_called_once()
        service_process.stdout.close.assert_called_once()
        service_process.stderr.close.assert_called_once()

    def test_get_driver_wipes_profile_and_retries_with_same_profile_on_failure(self):
        """
        When attempt 1 with the configured profile fails, attempt 2 MUST:
        - wipe the profile directory in-place (preserving the lock file),
        - retry with the SAME profile path (NOT fall back to no-profile),
        so that the subsequent login re-populates the profile and the
        next request can skip login. Re-login on every request is
        blocked by Naver (captcha / IP block), see AGENTS.md.
        """
        instance = self._make_instance()
        initial_options = MagicMock()
        browser = MagicMock()

        with patch.object(
            instance,
            "_startBrowser",
            side_effect=[RuntimeError("profile locked"), browser],
        ) as mock_start_browser, patch.object(
            instance, "_capture_cleanup_metadata", return_value={"servicePort": 1234}
        ) as mock_capture, patch.object(
            instance, "_perform_startup_health_check", return_value=True
        ) as mock_health_check, patch.object(
            instance, "_applyLanguageOverrides"
        ) as mock_apply, patch.object(
            instance, "_wipe_profile_directory_preserving_lock", return_value=True
        ) as mock_wipe, patch(
            "chromeDriver._cleanup_orphan_processes_for_profile"
        ) as mock_orphan_cleanup:
            result = instance.getDriver(initial_options)

        retry_options = mock_start_browser.call_args_list[1].args[0]
        assert result is browser
        assert instance.options is retry_options
        assert instance._cleanup_metadata == {"servicePort": 1234}
        assert retry_options is not initial_options
        # attempt 2 must KEEP the configured profile, not drop it
        assert any(
            argument.startswith(ChromeDriver.USER_DATA_DIR_ARGUMENT_PREFIX)
            and argument.endswith(instance.chrome_profile_path)
            for argument in retry_options.arguments
        )
        assert mock_start_browser.call_count == 2
        mock_wipe.assert_called_once_with(instance.chrome_profile_path)
        mock_orphan_cleanup.assert_called_once_with("/tmp/profile")
        mock_capture.assert_called_once_with(browser)
        mock_health_check.assert_called_once_with(browser)
        mock_apply.assert_called_once_with(browser)

    def test_get_driver_retries_after_startup_timeout(self):
        instance = self._make_instance()
        initial_options = MagicMock()
        retry_browser = MagicMock()

        with patch.object(
            instance,
            "_startBrowserSafe",
            side_effect=[TimeoutError("Browser startup exceeded timeout"), retry_browser],
        ) as mock_start_browser_safe, patch.object(
            instance, "_capture_cleanup_metadata", return_value={"servicePort": 1234}
        ) as mock_capture, patch.object(
            instance, "_perform_startup_health_check", return_value=True
        ) as mock_health_check, patch.object(
            instance, "_applyLanguageOverrides"
        ) as mock_apply, patch.object(
            instance, "_wipe_profile_directory_preserving_lock", return_value=True
        ) as mock_wipe, patch(
            "chromeDriver._cleanup_orphan_processes_for_profile"
        ) as mock_orphan_cleanup:
            result = instance.getDriver(initial_options)

        retry_options = mock_start_browser_safe.call_args_list[1].args[0]
        assert result is retry_browser
        assert retry_options is instance.options
        assert retry_options is not initial_options
        assert any(
            argument.startswith(ChromeDriver.USER_DATA_DIR_ARGUMENT_PREFIX)
            and argument.endswith(instance.chrome_profile_path)
            for argument in retry_options.arguments
        )
        assert mock_start_browser_safe.call_count == 2
        mock_wipe.assert_called_once_with(instance.chrome_profile_path)
        mock_orphan_cleanup.assert_called_once_with("/tmp/profile")
        mock_capture.assert_called_once_with(retry_browser)
        mock_health_check.assert_called_once_with(retry_browser)
        mock_apply.assert_called_once_with(retry_browser)


class TestWipeProfileDirectory:
    def _make_instance(self):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.chrome_profile_path = None
        instance.active_chrome_profile_path = None
        return instance

    def test_wipe_preserves_profile_lock_file(self, tmp_path):
        profile = tmp_path / "profile"
        profile.mkdir()
        # Lock file (simulated flock target) MUST be preserved
        lock_file = profile / ".profile.lock"
        lock_file.write_text("pid=123\n")
        # Arbitrary profile content that MUST be removed
        (profile / "Cookies").write_text("session-junk")
        (profile / "Preferences").write_text("{}")
        subdir = profile / "Default"
        subdir.mkdir()
        (subdir / "History").write_text("history-junk")

        instance = self._make_instance()
        result = instance._wipe_profile_directory_preserving_lock(str(profile))

        assert result is True
        assert lock_file.exists()
        assert lock_file.read_text() == "pid=123\n"
        assert not (profile / "Cookies").exists()
        assert not (profile / "Preferences").exists()
        assert not subdir.exists()

    def test_wipe_returns_false_when_profile_path_missing(self, tmp_path):
        instance = self._make_instance()
        missing = tmp_path / "does-not-exist"
        assert instance._wipe_profile_directory_preserving_lock(str(missing)) is False
        assert instance._wipe_profile_directory_preserving_lock("") is False


class TestChromeDriverRuntimeFlags:
    def _make_instance(self, debug_mode=False, has_display_server=False):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = debug_mode
        instance.has_display_server = has_display_server
        return instance

    def test_should_not_run_headless_by_default(self):
        instance = self._make_instance(debug_mode=False, has_display_server=True)
        with patch("chromeDriver.os.getenv", return_value=None):
            assert instance._should_run_headless() is False

    def test_should_not_silently_fall_back_to_headless_without_display(self):
        instance = self._make_instance(debug_mode=True, has_display_server=False)
        with patch("chromeDriver.os.getenv", return_value=None):
            assert instance._should_run_headless() is False

    def test_headless_requires_explicit_opt_in(self):
        instance = self._make_instance(debug_mode=False, has_display_server=False)
        with patch("chromeDriver.os.getenv", return_value="true"):
            assert instance._should_run_headless() is True

    def test_get_bool_env_uses_default_when_variable_is_missing(self):
        instance = self._make_instance()
        with patch("chromeDriver.os.getenv", return_value=None):
            assert instance._get_bool_env("UC_USE_SUBPROCESS", default=False) is False

    def test_should_enable_uc_multi_procs_defaults_to_false_when_env_is_missing(self):
        instance = self._make_instance()

        with patch("chromeDriver.os.getenv", return_value=None), patch(
            "chromeDriver.uc.Patcher"
        ) as mock_patcher:
            assert instance._should_enable_uc_multi_procs() is False

        mock_patcher.assert_not_called()

    def test_should_enable_uc_multi_procs_when_env_opt_in_is_true(self):
        instance = self._make_instance()

        with patch("chromeDriver.os.getenv", return_value="true"):
            assert instance._should_enable_uc_multi_procs() is True

    def test_start_browser_passes_uc_stability_flags(self):
        instance = self._make_instance()
        instance.use_subprocess = False
        instance.user_multi_procs = True
        options = MagicMock()

        with patch("chromeDriver.uc.Chrome", return_value=MagicMock()) as mock_uc_chrome:
            instance._startBrowser(options)

        mock_uc_chrome.assert_called_once_with(
            options=options,
            use_subprocess=False,
            user_multi_procs=True,
            version_main=146,
        )


class TestChromeDriverOptions:
    def _make_instance(self):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = False
        instance.has_display_server = False
        instance.run_headless = True
        instance.chrome_profile_path = None
        instance.active_chrome_profile_path = None
        return instance

    def test_build_options_uses_native_language_preferences(self):
        instance = self._make_instance()

        options = instance._buildOptions(include_profile=False)

        assert ChromeDriver.STARTUP_LANGUAGE == "ko-KR"
        assert "--lang=ko-KR" in options.arguments
        assert options.experimental_options["prefs"]["intl.accept_languages"] == ChromeDriver.ACCEPT_LANGUAGES

    def test_chrome_selects_its_renderer(self):
        options = self._make_instance()._buildOptions(include_profile=False)
        assert "--disable-gpu" not in options.arguments

    def test_build_options_uses_resolved_chrome_binary(self):
        instance = self._make_instance()
        instance.chrome_binary_path = "/opt/google/chrome/google-chrome"
        options = instance._buildOptions(include_profile=False)
        assert options.binary_location == "/opt/google/chrome/google-chrome"

    def test_configured_chrome_binary_must_be_executable(self, tmp_path, monkeypatch):
        binary = tmp_path / "chrome"
        binary.write_text("not executable")
        monkeypatch.setenv("CHROME_BINARY_PATH", str(binary))
        instance = ChromeDriver.__new__(ChromeDriver)
        with pytest.raises(BrowserStartupError, match="not executable"):
            instance._resolve_chrome_binary_path()

    def test_headless_ua_uses_desktop_token_with_real_ua_ch_metadata(self):
        instance = self._make_instance()
        browser = MagicMock()
        browser.execute_script.return_value = (
            "Mozilla/5.0 HeadlessChrome/146.0.0.0 Safari/537.36"
        )
        browser.execute_async_script.return_value = {
            "brands": [{"brand": "Chromium", "version": "146"}],
            "mobile": False,
            "platform": "Linux",
            "uaFullVersion": "146.0.7680.165",
            "unsupported": "discarded",
        }

        instance._applyLanguageOverrides(browser)

        assert browser.execute_cdp_cmd.call_args_list[0] == call(
            "Network.setUserAgentOverride",
            {
                "userAgent": "Mozilla/5.0 Chrome/146.0.0.0 Safari/537.36",
                "userAgentMetadata": {
                    "brands": [{"brand": "Chromium", "version": "146"}],
                    "mobile": False,
                    "platform": "Linux",
                    "fullVersion": "146.0.7680.165",
                },
            },
        )
        assert browser.execute_cdp_cmd.call_args_list[1] == call(
            "Emulation.setLocaleOverride", {"locale": "ko_KR"}
        )

    def test_headless_ua_is_not_changed_without_ua_ch_metadata(self):
        instance = self._make_instance()
        browser = MagicMock()
        browser.execute_script.return_value = "HeadlessChrome/146.0.0.0"
        browser.execute_async_script.return_value = None

        instance._applyLanguageOverrides(browser)

        browser.execute_cdp_cmd.assert_called_once_with(
            "Emulation.setLocaleOverride", {"locale": "ko_KR"}
        )


class TestChromeDriverInput:
    def test_login_types_into_live_fields_without_script_injection(self):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance._closed = True
        instance.driver = MagicMock()
        username, password = MagicMock(), MagicMock()
        with patch("chromeDriver.WebDriverWait") as wait, patch.object(
            instance, "moveAndClick"
        ) as moveAndClick, patch.object(instance, "wait"):
            wait.return_value.until.side_effect = [username, username, password]
            instance.login("test-user", "test-password")
        for field, value in ((username, "test-user"), (password, "test-password")):
            moveAndClick.assert_any_call(field)
            typed = [c.args[0] for c in field.send_keys.call_args_list[1:]]
            assert "".join(typed) == value
        instance.driver.execute_script.assert_not_called()

    def test_login_spreads_keystrokes_over_randomized_delays(self):
        """Naver flags the uniform, near-zero intervals of a bulk send_keys."""
        instance = ChromeDriver.__new__(ChromeDriver)
        instance._closed = True
        instance.driver = MagicMock()
        field = MagicMock()
        with patch.object(instance, "wait") as sleep:
            instance._typeLikeHuman(field, "abc")
        assert field.send_keys.call_args_list == [call("a"), call("b"), call("c")]
        lower, upper = ChromeDriver.KEYSTROKE_DELAY_RANGE
        delays = [c.args[0] for c in sleep.call_args_list]
        assert len(delays) == 3
        assert all(lower <= delay <= upper for delay in delays)

    def test_move_and_click_emits_pointer_movement_before_clicking(self):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance._closed = True
        instance.driver = MagicMock()
        element = MagicMock()
        with patch("chromeDriver.ActionChains") as actionChains:
            chain = actionChains.return_value
            chain.move_to_element.return_value = chain
            chain.pause.return_value = chain
            chain.click.return_value = chain
            instance.moveAndClick(element)
        chain.move_to_element.assert_called_once_with(element)
        chain.click.assert_called_once_with(element)
        chain.perform.assert_called_once_with()

    def test_navigation_waits_for_document_state(self):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance._closed = True
        instance.driver = MagicMock()
        with patch.object(instance, "waitForDocumentReady") as ready, patch.object(instance, "wait") as sleep:
            instance.goTo("https://example.test")
        ready.assert_called_once_with()
        sleep.assert_not_called()


class TestChromeDriverProfiles:
    def _make_instance(self):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = False
        instance.has_display_server = False
        instance.run_headless = True
        instance.chrome_profile_path = "/tmp/profile"
        instance.active_chrome_profile_path = None
        return instance

    def test_resolve_profile_path_uses_direct_profile_and_cleans_stale_files(self):
        instance = self._make_instance()
        with patch.object(instance, "_cleanup_stale_profile_files") as mock_cleanup:
            result = instance._resolve_profile_path(include_profile=True)

        assert result == "/tmp/profile"
        assert instance.active_chrome_profile_path == "/tmp/profile"
        mock_cleanup.assert_called_once_with("/tmp/profile")

    def test_resolve_profile_path_returns_none_when_profile_is_disabled(self):
        instance = self._make_instance()

        result = instance._resolve_profile_path(include_profile=False)

        assert result is None
        assert instance.active_chrome_profile_path is None

    def test_cleanup_stale_profile_files_removes_only_known_stale_files(self, tmp_path):
        instance = self._make_instance()
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        removed_candidates = {
            "SingletonLock",
            "SingletonSocket",
            "SingletonCookie",
            "DevToolsActivePort",
        }
        for file_name in removed_candidates:
            (profile_dir / file_name).write_text("stale", encoding="utf-8")
        keep_file = profile_dir / "Preferences"
        keep_file.write_text("keep", encoding="utf-8")

        instance._cleanup_stale_profile_files(str(profile_dir))

        for file_name in removed_candidates:
            assert not (profile_dir / file_name).exists()
        assert keep_file.exists()


class TestChromeDriverCleanupGuards:
    def test_close_handles_partially_initialized_instance(self):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.driver = None

        instance.close()

        assert instance._closed is True

    def test_fd_check_failure_does_not_log_not_properly_closed_warning(self, caplog):
        gc.collect()
        caplog.set_level(logging.WARNING, logger="chromeDriver")
        caplog.clear()

        with patch("chromeDriver.get_fd_count", return_value=999), patch(
            "chromeDriver.log_fd_status"
        ):
            with pytest.raises(FDExhaustedError):
                ChromeDriver()

        gc.collect()
        assert "ChromeDriver was not properly closed" not in caplog.text

    def test_del_handles_missing_internal_state(self):
        instance = ChromeDriver.__new__(ChromeDriver)

        instance.__del__()

    def test_is_pid_alive_rejects_non_integer_values(self):
        assert _is_pid_alive(None) is False
        assert _is_pid_alive(-1) is False
        assert _is_pid_alive("123") is False
        assert _is_pid_alive(MagicMock()) is False
