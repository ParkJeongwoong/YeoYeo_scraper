import signal
from unittest.mock import MagicMock, call, patch

from chromeDriver import ChromeDriver, FORCE_KILL_SIGNAL


class TestChromeDriverClose:
    def _make_instance(self, driver=None, debug_mode=False):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = debug_mode
        instance.has_display_server = debug_mode
        instance.run_headless = not debug_mode
        instance.chrome_profile_path = "/tmp/profile"
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

        with patch.object(instance, "_cleanup_linux_processes", return_value=True) as mock_cleanup:
            instance.close()

        browser.quit.assert_called_once()
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
        assert instance._closed is False

    def test_close_keeps_driver_available_for_retry_when_quit_fails_without_fallback(self):
        browser = MagicMock()
        browser.quit.side_effect = RuntimeError("tab crashed")
        instance = self._make_instance(driver=browser)

        with patch.object(instance, "_cleanup_linux_processes", return_value=False) as mock_cleanup:
            instance.close()
            instance.close()

        assert browser.quit.call_count == 2
        assert mock_cleanup.call_count == 2
        assert instance.driver is browser
        assert instance._closed is False


class TestChromeDriverLinuxCleanup:
    def _make_instance(self, metadata):
        instance = ChromeDriver.__new__(ChromeDriver)
        instance.debug_mode = False
        instance.has_display_server = False
        instance.run_headless = True
        instance.chrome_profile_path = metadata.get("chromeProfilePath")
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

        mock_kill.assert_has_calls(
            [
                call(222, signal.SIGTERM),
                call(111, signal.SIGTERM),
                call(222, FORCE_KILL_SIGNAL),
                call(111, FORCE_KILL_SIGNAL),
            ]
        )

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
        instance.use_subprocess = False
        instance.driver = None
        instance._closed = False
        instance._cleanup_metadata = {}
        instance.options = MagicMock(arguments=["--headless=new"])
        return instance

    def test_get_driver_keeps_browser_when_language_overrides_fail(self):
        instance = self._make_instance()
        options = MagicMock()
        browser = MagicMock()

        with patch.object(instance, "_startBrowser", return_value=browser) as mock_start_browser, patch.object(
            instance, "_capture_cleanup_metadata", return_value={"servicePort": 1234}
        ) as mock_capture, patch.object(
            instance, "_applyLanguageOverrides", side_effect=RuntimeError("cdp failed")
        ) as mock_apply:
            result = instance.getDriver(options)

        assert result is browser
        assert instance._cleanup_metadata == {"servicePort": 1234}
        mock_start_browser.assert_called_once_with(options)
        mock_capture.assert_called_once_with(browser)
        mock_apply.assert_called_once_with(browser)
        browser.quit.assert_not_called()

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
