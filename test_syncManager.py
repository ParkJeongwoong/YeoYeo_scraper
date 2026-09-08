import pytest
import datetime
from unittest.mock import Mock, MagicMock, patch
import bookingListExtractor
from syncManager import (
    makeTargetDateList,
    makeTargetDate,
    SyncNaver,
    SyncNaverIdempotent,
    getNaverReservation,
    ReservationLookupError,
    RoomType,
    checkLoginSession,
    _isNaverFinalizeUrl,
    openAuthenticatedTargetPage,
    performLogin,
    waitForBookingListDom,
)


class TestMakeTargetDate:
    def test_valid_date_format(self):
        result = makeTargetDate("2024-08-19")
        assert result == datetime.date(2024, 8, 19)

    def test_single_digit_month_day(self):
        result = makeTargetDate("2024-1-5")
        assert result == datetime.date(2024, 1, 5)

    def test_double_digit_all(self):
        result = makeTargetDate("2024-12-31")
        assert result == datetime.date(2024, 12, 31)

    def test_different_year(self):
        result = makeTargetDate("2025-3-7")
        assert result == datetime.date(2025, 3, 7)

    def test_start_of_year(self):
        result = makeTargetDate("2024-1-1")
        assert result == datetime.date(2024, 1, 1)

    def test_end_of_year(self):
        result = makeTargetDate("2024-12-31")
        assert result == datetime.date(2024, 12, 31)


class TestAuthenticationProtection:
    @patch("syncManager.collectPageDiagnostics")
    @patch("syncManager._resumeFromNaverFinalize")
    def test_protection_does_not_enter_finalize_recovery(self, resume, diagnostics):
        browser = MagicMock()
        browser.executeScript.return_value = "CAPTCHA"
        browser.getCurrentUrl.return_value = "https://nid.naver.com/signin/v4/finalize"
        with pytest.raises(ReservationLookupError, match="CAPTCHA"):
            performLogin(browser, "test-session")
        browser.login.assert_not_called()
        resume.assert_not_called()
        diagnostics.assert_not_called()

    def test_unknown_destination_is_not_logged_as_reused(self, caplog):
        import logging
        browser = MagicMock()
        browser.executeScript.return_value = None
        browser.getCurrentUrl.return_value = "https://nid.naver.com/new-challenge"
        with caplog.at_level(logging.INFO):
            openAuthenticatedTargetPage(browser, "https://partner.example", "test-session")
        assert '"status": "SESSION_UNCONFIRMED"' in caplog.text
        assert '"status": "SESSION_REUSED"' not in caplog.text

    @pytest.mark.parametrize("status", ["CAPTCHA", "ACCESS_BLOCKED", "ADDITIONAL_AUTH"])
    def test_protection_stops_before_login(self, status, caplog):
        import logging
        browser = MagicMock()
        browser.executeScript.return_value = status
        with caplog.at_level(logging.INFO), pytest.raises(ReservationLookupError):
            openAuthenticatedTargetPage(browser, "https://partner.example", "test-session")
        browser.login.assert_not_called()
        assert f'"status": "{status}"' in caplog.text

    def test_normal_page_does_not_log_credentials(self, caplog):
        import logging
        browser = MagicMock()
        browser.executeScript.return_value = None
        browser.getCurrentUrl.return_value = "https://partner.example"
        with caplog.at_level(logging.INFO):
            openAuthenticatedTargetPage(browser, "https://partner.example", "test-session")
        assert '"status": "SESSION_REUSED"' in caplog.text
        browser.login.assert_not_called()

class TestMakeTargetDateList:
    def test_single_date(self):
        result = makeTargetDateList("2024-08-19")
        assert len(result) == 1
        assert result[0] == datetime.date(2024, 8, 19)

    def test_multiple_dates(self):
        result = makeTargetDateList("2024-08-19,2024-08-20,2024-08-21")
        assert len(result) == 3
        assert result[0] == datetime.date(2024, 8, 19)
        assert result[1] == datetime.date(2024, 8, 20)
        assert result[2] == datetime.date(2024, 8, 21)

    def test_dates_are_sorted(self):
        result = makeTargetDateList("2024-08-25,2024-08-19,2024-08-22")
        assert len(result) == 3
        assert result[0] == datetime.date(2024, 8, 19)
        assert result[1] == datetime.date(2024, 8, 22)
        assert result[2] == datetime.date(2024, 8, 25)

    def test_dates_across_months(self):
        result = makeTargetDateList("2024-08-30,2024-09-01,2024-09-05")
        assert len(result) == 3
        assert result[0] == datetime.date(2024, 8, 30)
        assert result[1] == datetime.date(2024, 9, 1)
        assert result[2] == datetime.date(2024, 9, 5)

    def test_dates_across_years(self):
        result = makeTargetDateList("2024-12-30,2025-01-02,2025-01-05")
        assert len(result) == 3
        assert result[0] == datetime.date(2024, 12, 30)
        assert result[1] == datetime.date(2025, 1, 2)
        assert result[2] == datetime.date(2025, 1, 5)

    def test_duplicate_dates(self):
        result = makeTargetDateList("2024-08-19,2024-08-19,2024-08-20")
        assert len(result) == 3


class TestPerformLogin:
    @pytest.mark.parametrize(
        "version",
        ["v3", "v4", "v5", "v10"],
    )
    def test_recognizes_versioned_naver_finalize_urls(self, version):
        assert _isNaverFinalizeUrl(
            f"https://nid.naver.com/signin/{version}/finalize?url=https%3A%2F%2Fexample.com"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://nid.naver.com/nidlogin.login",
            "https://nid.naver.com/signin/v4/captcha",
            "https://evil.example/signin/v4/finalize",
            "https://nid.naver.com/signin/version4/finalize",
        ],
    )
    def test_does_not_treat_other_login_urls_as_finalize(self, url):
        assert not _isNaverFinalizeUrl(url)

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.collectPageDiagnostics")
    def test_captures_diagnostics_when_login_button_is_missing(
        self, mock_collect_diagnostics
    ):
        mock_driver = MagicMock()
        mock_driver.waitForAnySelector.side_effect = TimeoutError("button missing")
        mock_driver.getCurrentUrl.return_value = "https://nid.naver.com/nidlogin.login"

        with pytest.raises(ReservationLookupError) as exc_info:
            performLogin(mock_driver, "login_test_session")

        assert exc_info.value.sessionId == "login_test_session"
        mock_collect_diagnostics.assert_called_once_with(
            mock_driver, "login_failed", "login_test_session", forceWrite=True
        )
        mock_driver.findBySelector.assert_not_called()

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.collectPageDiagnostics")
    def test_resumes_at_target_when_login_has_moved_to_finalize(
        self, mock_collect_diagnostics
    ):
        finalize_url = (
            "https://nid.naver.com/signin/v3/finalize?"
            "url=https%3A%2F%2Fprod-partner.io.naver.com%2Fbizes%2F899762%2F"
            "simple-management&svctype=1"
        )
        target_url = "https://partner.booking.naver.com/bizes/899762/booking-list-view"
        mock_driver = MagicMock()
        mock_driver.waitForAnySelector.side_effect = TimeoutError("button missing")
        mock_driver.getCurrentUrl.side_effect = [finalize_url, finalize_url, target_url]

        target_loaded = performLogin(
            mock_driver, "login_test_session", targetUrl=target_url
        )

        assert target_loaded is True
        mock_driver.wait.assert_called_once_with(10)
        mock_driver.goTo.assert_any_call(target_url)
        mock_collect_diagnostics.assert_called_once_with(
            mock_driver,
            "login_finalize_detected",
            "login_test_session",
            forceWrite=True,
        )

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    def test_waits_for_login_button_before_clicking(self, mock_real_sleep, mock_sleep):
        mock_driver = MagicMock()
        mock_driver.getCurrentUrl.return_value = "https://www.naver.com/"
        mock_driver.waitForAnySelector.return_value = {
            "selector": "#loginBtn_row",
            "count": 1,
        }

        target_loaded = performLogin(mock_driver, "login_test_session")

        assert target_loaded is False
        mock_driver.waitForAnySelector.assert_called_once_with(
            ["#loginBtn_row", "#log\\.login"], timeout=10
        )
        mock_driver.findBySelector.assert_called_once_with("#loginBtn_row")
        mock_driver.findBySelector.return_value.click.assert_called_once_with()

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    def test_falls_back_to_legacy_login_button(self, mock_real_sleep, mock_sleep):
        mock_driver = MagicMock()
        mock_driver.getCurrentUrl.return_value = "https://www.naver.com/"
        mock_driver.waitForAnySelector.return_value = {
            "selector": "#log\\.login",
            "count": 1,
        }

        performLogin(mock_driver, "login_test_session")

        mock_driver.findBySelector.assert_called_once_with("#log\\.login")
        mock_driver.findBySelector.return_value.click.assert_called_once_with()


class TestLoginSession:
    def test_does_not_trust_logout_text_without_a_visible_session_control(self):
        mock_driver = MagicMock()
        mock_driver.executeScript.return_value = 0
        mock_driver.getPageSource.return_value = '<script>const action = "logout";</script>'

        assert checkLoginSession(mock_driver) is False
        mock_driver.getPageSource.assert_not_called()

    def test_recognizes_stable_logout_destination(self):
        mock_driver = MagicMock()
        mock_driver.executeScript.side_effect = [0, 0, 1, 0]

        assert checkLoginSession(mock_driver) is True

    @patch("syncManager.performLogin")
    def test_recovers_when_partner_page_redirects_to_login(
        self, mock_perform_login
    ):
        mock_driver = MagicMock()
        mock_driver.getCurrentUrl.side_effect = [
            "https://nid.naver.com/nidlogin.login?url=partner",
            "https://partner.booking.naver.com/bizes/899762/simple-management",
        ]
        target_url = (
            "https://partner.booking.naver.com/bizes/899762/simple-management"
        )

        openAuthenticatedTargetPage(mock_driver, target_url, "session-id")

        mock_perform_login.assert_called_once_with(
            mock_driver, "session-id", target_url
        )
        assert mock_driver.goTo.call_count == 2

    @patch("syncManager.performLogin")
    def test_does_not_repeat_login_when_first_attempt_still_redirects(
        self, mock_perform_login
    ):
        mock_driver = MagicMock()
        mock_driver.getCurrentUrl.side_effect = [
            "https://nid.naver.com/nidlogin.login?url=partner",
            "https://nid.naver.com/nidlogin.login?url=partner",
        ]

        with pytest.raises(ReservationLookupError):
            openAuthenticatedTargetPage(mock_driver, "https://partner.example", "sid")

        mock_perform_login.assert_called_once()

    @patch("syncManager.performLogin")
    @patch("syncManager.checkLoginSession")
    def test_reuses_partner_session_without_main_page_or_login(
        self, mock_check_session, mock_perform_login
    ):
        mock_driver = MagicMock()
        mock_driver.getCurrentUrl.return_value = (
            "https://partner.booking.naver.com/bizes/899762/simple-management"
        )

        openAuthenticatedTargetPage(mock_driver, "https://partner.example", "sid")

        mock_check_session.assert_not_called()
        mock_perform_login.assert_not_called()
        mock_driver.goTo.assert_called_once_with("https://partner.example")

class TestSyncNaver:
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    def test_legacy_sync_naver_unconditionally_clicks(
        self, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_controller = MagicMock()
        mock_controller.findTargetPage.return_value = 0
        target_button = MagicMock()
        mock_controller.findTargetBtn.return_value = target_button

        with patch(
            "syncManager.simpleManagementController.SimpleManagementController",
            return_value=mock_controller,
        ):
            result = SyncNaver(mock_driver, "2024-08-19", "Yeoyu")

        assert result == ["2024-08-19"]
        target_button.click.assert_called_once_with()

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    def test_sync_naver_single_date_yeoyu(
        self, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.executeScript = MagicMock()
        mock_driver.waitForAnySelector.return_value = {
            "selector": "#loginBtn_row",
            "count": 1,
        }
        mock_driver.getCurrentUrl.side_effect = [
            "https://nid.naver.com/nidlogin.login?url=partner",
            "https://www.naver.com/",
            "https://partner.booking.naver.com/bizes/899762/simple-management",
        ]

        mock_controller = MagicMock()
        mock_controller.findTargetPage.return_value = 0
        mock_controller.findTargetBtn.return_value = MagicMock()

        with patch(
            "syncManager.simpleManagementController.SimpleManagementController",
            return_value=mock_controller,
        ):
            mock_controller.readTargetToggleState.side_effect = [False, True]
            result = SyncNaverIdempotent(
                mock_driver, "2024-08-19", "Yeoyu", "available"
            )

        assert result["status"] == "SUCCESS"
        assert result["successDates"] == ["2024-08-19"]
        assert result["results"][0]["result"] == "SUCCESS"
        mock_driver.goTo.assert_called()
        mock_driver.login.assert_called_once()

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    def test_sync_naver_multiple_dates(
        self, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.executeScript = MagicMock()

        mock_controller = MagicMock()
        mock_controller.findTargetPage.return_value = 0
        mock_controller.findTargetBtn.return_value = MagicMock()

        with patch(
            "syncManager.simpleManagementController.SimpleManagementController",
            return_value=mock_controller,
        ):
            mock_controller.readTargetToggleState.side_effect = [True, True, True]
            result = SyncNaverIdempotent(
                mock_driver,
                "2024-08-19,2024-08-20,2024-08-21",
                "Yeohang",
                "available",
            )

        assert result["status"] == "SUCCESS"
        assert result["successDates"] == [
            "2024-08-19", "2024-08-20", "2024-08-21"
        ]
        assert all(item["result"] == "ALREADY_APPLIED" for item in result["results"])
        click_calls = [
            call for call in mock_driver.executeScript.call_args_list
            if call.args and call.args[0] == "arguments[0].click();"
        ]
        assert click_calls == []
        assert mock_controller.findTargetPage.call_count == 3

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    def test_sync_naver_date_not_found(
        self, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()

        mock_controller = MagicMock()
        mock_controller.findTargetPage.return_value = -1

        with patch(
            "syncManager.simpleManagementController.SimpleManagementController",
            return_value=mock_controller,
        ):
            result = SyncNaverIdempotent(
                mock_driver, "2024-08-19", "Yeoyu", "externallyBlocked"
            )

        assert result["status"] == "FAILED"
        assert result["results"][0]["result"] == "DEFERRED"
        assert result["results"][0]["reason"] == "DATE_NOT_AVAILABLE_IN_NAVER_CALENDAR"
        mock_controller.findTargetBtn.assert_not_called()

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    def test_sync_naver_partial_success(
        self, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.executeScript = MagicMock()

        mock_controller = MagicMock()
        mock_controller.findTargetPage.side_effect = [0, -1, 2]
        mock_controller.findTargetBtn.return_value = MagicMock()
        mock_controller.readTargetToggleState.side_effect = [True, True]

        with patch(
            "syncManager.simpleManagementController.SimpleManagementController",
            return_value=mock_controller,
        ):
            result = SyncNaverIdempotent(
                mock_driver,
                "2024-08-19,2024-08-20,2024-08-21",
                "Yeoyu",
                "available",
            )

        assert result["status"] == "PARTIAL_SUCCESS"
        assert result["successDates"] == ["2024-08-19", "2024-08-21"]
        assert [item["result"] for item in result["results"]] == [
            "ALREADY_APPLIED", "DEFERRED", "ALREADY_APPLIED"
        ]

    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    def test_sync_naver_continues_after_click_failure(self, mock_real_sleep, mock_sleep):
        mock_driver = MagicMock()
        mock_controller = MagicMock()
        mock_controller.findTargetBtn.return_value.click.side_effect = RuntimeError("click failed")
        mock_controller.findTargetPage.return_value = 0
        mock_controller.readTargetToggleState.side_effect = [False, True]

        with patch(
            "syncManager.simpleManagementController.SimpleManagementController",
            return_value=mock_controller,
        ):
            result = SyncNaverIdempotent(
                mock_driver,
                "2024-08-19,2024-08-20",
                "Yeoyu",
                "available",
            )

        assert result["status"] == "PARTIAL_SUCCESS"
        assert [item["result"] for item in result["results"]] == [
            "FAILED", "ALREADY_APPLIED"
        ]
        assert result["results"][0]["reason"] == "CLICK_FAILED"

    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    def test_sync_naver_requires_post_click_state_verification(
        self, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_controller = MagicMock()
        mock_controller.findTargetPage.return_value = 0
        mock_controller.readTargetToggleState.side_effect = [False, False]

        with patch(
            "syncManager.simpleManagementController.SimpleManagementController",
            return_value=mock_controller,
        ):
            result = SyncNaverIdempotent(
                mock_driver, "2024-08-19", "Yeoyu", "available"
            )

        assert result["status"] == "FAILED"
        assert result["successDates"] == []
        assert result["results"][0]["reason"] == "STATE_VERIFICATION_FAILED"


class TestGetNaverReservation:
    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.bookingListExtractor.extractBookingList")
    def test_get_naver_reservation_single_month(
        self, mock_extract, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.getPageSource.return_value = "<html></html>"
        mock_driver.findByXpath.return_value = MagicMock()
        mock_driver.getBrowserInfo.return_value = {}

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")

        mock_extract.return_value = [
            {
                "reservationNumber": "12345",
                "startDate": future_date_str,
                "status": "confirmed",
            }
        ]

        result = getNaverReservation(mock_driver, 1)

        assert len(result) == 2
        not_canceled, all_bookings = result
        assert len(not_canceled) == 1
        assert len(all_bookings) == 1
        assert not_canceled[0]["reservationNumber"] == "12345"
        mock_driver.findByXpath.assert_not_called()

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.bookingListExtractor.extractBookingList")
    def test_get_naver_reservation_multiple_months(
        self, mock_extract, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.getPageSource.return_value = "<html></html>"
        mock_driver.findByXpath.return_value = MagicMock()
        mock_driver.getBrowserInfo.return_value = {}

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")

        mock_extract.return_value = [
            {
                "reservationNumber": f"1234{i}",
                "startDate": future_date_str,
                "status": "confirmed",
            }
            for i in range(3)
        ]

        result = getNaverReservation(mock_driver, 3)

        assert mock_extract.call_count == 3
        not_canceled, all_bookings = result
        assert len(all_bookings) >= 3

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.bookingListExtractor.extractBookingList")
    def test_get_naver_reservation_allows_empty_month(
        self, mock_extract, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        empty_state_text = bookingListExtractor.EMPTY_BOOKING_LIST_MARKERS[0]
        mock_driver.getPageSource.side_effect = [
            "<html><body><a class=\"BookingListView__contents-user\"></a></body></html>",
            f"<html><body><div>{empty_state_text}</div></body></html>",
        ]
        mock_driver.findByXpath.return_value = MagicMock()
        mock_driver.getBrowserInfo.return_value = {}

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")

        mock_extract.side_effect = [
            [
                {
                    "reservationNumber": "12345",
                    "startDate": future_date_str,
                    "status": "confirmed",
                }
            ],
            [],
        ]

        not_canceled, all_bookings = getNaverReservation(mock_driver, 2)

        assert len(all_bookings) == 1
        assert len(not_canceled) == 1
        assert all_bookings[0]["reservationNumber"] == "12345"
        mock_driver.findByXpath.assert_called_once()
    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.bookingListExtractor.extractBookingList")
    def test_get_naver_reservation_filters_canceled(
        self, mock_extract, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.getPageSource.return_value = "<html></html>"
        mock_driver.findByXpath.return_value = MagicMock()
        mock_driver.getBrowserInfo.return_value = {}

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")

        mock_extract.return_value = [
            {
                "reservationNumber": "12345",
                "startDate": future_date_str,
                "status": "confirmed",
            },
            {
                "reservationNumber": "67890",
                "startDate": future_date_str,
                "status": "취소",
            },
        ]

        result = getNaverReservation(mock_driver, 1)

        not_canceled, all_bookings = result
        assert len(all_bookings) == 2
        assert len(not_canceled) == 1
        assert not_canceled[0]["status"] == "confirmed"

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.bookingListExtractor.extractBookingList")
    def test_get_naver_reservation_removes_duplicates(
        self, mock_extract, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.getPageSource.return_value = "<html></html>"
        mock_driver.findByXpath.return_value = MagicMock()
        mock_driver.getBrowserInfo.return_value = {}

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")

        mock_extract.side_effect = [
            [
                {
                    "reservationNumber": "12345",
                    "startDate": future_date_str,
                "status": "confirmed",
                }
            ],
            [
                {
                    "reservationNumber": "12345",
                    "startDate": future_date_str,
                "status": "confirmed",
                },
                {
                    "reservationNumber": "67890",
                    "startDate": future_date_str,
                "status": "confirmed",
                },
            ],
        ]

        result = getNaverReservation(mock_driver, 2)

        not_canceled, all_bookings = result
        assert len(all_bookings) == 2
        reservation_numbers = [b["reservationNumber"] for b in all_bookings]
        assert "12345" in reservation_numbers
        assert "67890" in reservation_numbers

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.bookingListExtractor.extractBookingList")
    def test_get_naver_reservation_filters_past_dates(
        self, mock_extract, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.getPageSource.return_value = "<html></html>"
        mock_driver.findByXpath.return_value = MagicMock()
        mock_driver.getBrowserInfo.return_value = {}

        kst = datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        now = datetime.datetime.now(datetime.timezone.utc).astimezone(kst)
        
        past_date = (now - datetime.timedelta(days=7)).strftime("%Y%m%d")
        future_date = (now + datetime.timedelta(days=7)).strftime("%Y%m%d")

        mock_extract.return_value = [
            {
                "reservationNumber": "12345",
                "startDate": past_date,
                "status": "confirmed",
            },
            {
                "reservationNumber": "67890",
                "startDate": future_date,
                "status": "confirmed",
            },
        ]

        result = getNaverReservation(mock_driver, 1)

        not_canceled, all_bookings = result
        assert len(all_bookings) == 1
        assert all_bookings[0]["reservationNumber"] == "67890"

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.collectPageDiagnostics")
    @patch("syncManager.waitForBookingListDom")
    @patch("syncManager.bookingListExtractor.extractBookingList")
    def test_get_naver_reservation_raises_when_dom_is_empty(
        self,
        mock_extract,
        mock_wait_for_booking_list,
        mock_collect_diagnostics,
        mock_real_sleep,
        mock_sleep,
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.getPageSource.return_value = "<html></html>"
        mock_driver.getBrowserInfo.return_value = {}
        mock_extract.return_value = []
        mock_collect_diagnostics.side_effect = [
            {"selectorCounts": {"calendarNextButton": 0}},
            {"selectorCounts": {"calendarNextButton": 0}},
            {"selectorCounts": {"calendarNextButton": 0}},
            {"selectorCounts": {"calendarNextButton": 0}},
            {"selectorCounts": {"calendarNextButton": 0}},
        ]

        with pytest.raises(ReservationLookupError) as exc_info:
            getNaverReservation(mock_driver, 2)

        assert "booking list DOM is empty" in str(exc_info.value)
        stages = [call.args[1] for call in mock_collect_diagnostics.call_args_list]
        assert "after_login" in stages
        assert "booking_list_loaded" in stages
        wait_stages = [call.args[2] for call in mock_wait_for_booking_list.call_args_list]
        assert "booking_list_initial" in wait_stages


class TestWaitForBookingListDom:
    def test_accepts_empty_state_without_ready_selectors(self):
        mock_driver = MagicMock()
        empty_state_text = bookingListExtractor.EMPTY_BOOKING_LIST_MARKERS[0]

        def execute_script(script, *args):
            if "querySelectorAll" in script:
                return 0
            if "document.body ? document.body.innerText" in script:
                return empty_state_text
            if "document.readyState" in script:
                return "complete"
            return None

        mock_driver.executeScript.side_effect = execute_script

        result = waitForBookingListDom(
            mock_driver, "test_session", "booking_list_month_1", timeout=1
        )

        assert result == {"emptyState": True}


class TestRoomType:
    def test_room_type_enum_values(self):
        assert RoomType.Yeoyu.value == 0
        assert RoomType.Yeohang.value == 1

    def test_room_type_enum_names(self):
        assert RoomType.Yeoyu.name == "Yeoyu"
        assert RoomType.Yeohang.name == "Yeohang"

    def test_room_type_from_string(self):
        assert RoomType["Yeoyu"] == RoomType.Yeoyu
        assert RoomType["Yeohang"] == RoomType.Yeohang

class TestDriverOwnership:
    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.bookingListExtractor.extractBookingList")
    def test_get_naver_reservation_does_not_close_driver_on_success(
        self, mock_extract, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.getPageSource.return_value = "<html></html>"
        mock_driver.findByXpath.return_value = MagicMock()
        mock_driver.getBrowserInfo.return_value = {}

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")
        mock_extract.return_value = [
            {
                "reservationNumber": "12345",
                "startDate": future_date_str,
                "status": "confirmed",
            }
        ]

        getNaverReservation(mock_driver, 1)

        mock_driver.close.assert_not_called()

    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.collectPageDiagnostics")
    @patch("syncManager.waitForBookingListDom", return_value=None)
    def test_get_naver_reservation_does_not_close_driver_on_error(
        self,
        mock_wait_for_booking_list,
        mock_collect_diagnostics,
        mock_real_sleep,
        mock_sleep,
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.getBrowserInfo.return_value = {}

        with pytest.raises(ReservationLookupError):
            getNaverReservation(mock_driver, 1)

        mock_driver.close.assert_not_called()
