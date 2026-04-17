import signal
from unittest.mock import MagicMock, call, patch

import pytest

from chromeDriver import BrowserStartupError, ChromeDriver, FORCE_KILL_SIGNAL, _is_pid_alive


class TestChromeDriverClose:
    def _make_instance(self, driver=None, debug_mode=False):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = debug_mode
        instance.has_display_server = debug_mode
        instance.run_headless = not debug_mode
        instance.chrome_profile_path = "/tmp/profile"
        instance.active_chrome_profile_path = "/tmp/profile"
        instance.use_subprocess = False
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
        instance = self._make_instance(driver=browser)

        with patch.object(instance, "_cleanup_linux_processes", return_value=True) as mock_cleanup:
            instance.close()
            instance.close()

        browser.quit.assert_called_once()
        mock_cleanup.assert_not_called()
        assert instance.driver is None
        assert instance._closed is True

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
        instance.driver = None
        instance._closed = False
        instance._cleanup_metadata = {}
        instance._partial_browser = None
        instance.options = MagicMock(arguments=["--headless=new"])
        return instance

    def test_get_driver_fails_when_language_overrides_fail(self):
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
            with pytest.raises(BrowserStartupError):
                instance.getDriver(options)

        assert instance._cleanup_metadata == {"servicePort": 1234}
        mock_start_browser.assert_called_once_with(options)
        mock_capture.assert_called_once_with(browser)
        mock_health_check.assert_called_once_with(browser)
        mock_apply.assert_called_once_with(browser)
        mock_force_kill.assert_called_once_with(browser)

    def test_get_driver_retries_without_profile_when_profile_start_fails(self):
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
        ) as mock_apply:
            result = instance.getDriver(initial_options)

        retry_options = mock_start_browser.call_args_list[1].args[0]
        assert result is browser
        assert instance.options is retry_options
        assert instance._cleanup_metadata == {"servicePort": 1234}
        assert retry_options is not initial_options
        assert all(
            not argument.startswith(ChromeDriver.USER_DATA_DIR_ARGUMENT_PREFIX)
            for argument in retry_options.arguments
        )
        assert mock_start_browser.call_count == 2
        mock_capture.assert_called_once_with(browser)
        mock_health_check.assert_called_once_with(browser)
        mock_apply.assert_called_once_with(browser)


class TestChromeDriverRuntimeFlags:
    def _make_instance(self, debug_mode=False, has_display_server=False):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = debug_mode
        instance.has_display_server = has_display_server
        return instance

    def test_should_run_headless_when_debug_mode_is_disabled(self):
        instance = self._make_instance(debug_mode=False, has_display_server=True)
        assert instance._should_run_headless() is True

    def test_should_run_headless_on_linux_without_display(self):
        instance = self._make_instance(debug_mode=True, has_display_server=False)
        with patch("chromeDriver.platform.system", return_value="Linux"):
            assert instance._should_run_headless() is True

    def test_should_not_run_headless_in_debug_mode_with_display(self):
        instance = self._make_instance(debug_mode=True, has_display_server=True)
        with patch("chromeDriver.platform.system", return_value="Linux"):
            assert instance._should_run_headless() is False

    def test_get_bool_env_uses_default_when_variable_is_missing(self):
        instance = self._make_instance()
        with patch("chromeDriver.os.getenv", return_value=None):
            assert instance._get_bool_env("UC_USE_SUBPROCESS", default=True) is True


class TestChromeDriverOptions:
    def _make_instance(self):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = False
        instance.has_display_server = False
        instance.run_headless = True
        instance.chrome_profile_path = None
        instance.active_chrome_profile_path = None
        return instance

    def test_build_options_uses_stable_startup_language_without_prefs(self):
        instance = self._make_instance()

        options = instance._buildOptions(include_profile=False)

        assert f"--lang={ChromeDriver.STARTUP_LANGUAGE}" in options.arguments
        assert "prefs" not in options.experimental_options


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

    def test_del_handles_missing_internal_state(self):
        instance = ChromeDriver.__new__(ChromeDriver)

        instance.__del__()

    def test_is_pid_alive_rejects_non_integer_values(self):
        assert _is_pid_alive(None) is False
        assert _is_pid_alive(-1) is False
        assert _is_pid_alive("123") is False
        assert _is_pid_alive(MagicMock()) is False
