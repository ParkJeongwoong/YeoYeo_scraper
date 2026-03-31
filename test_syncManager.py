import pytest
import datetime
from unittest.mock import Mock, MagicMock, patch
import bookingListExtractor
from syncManager import (
    makeTargetDateList,
    makeTargetDate,
    SyncNaver,
    getNaverReservation,
    ReservationLookupError,
    RoomType,
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


class TestSyncNaver:
    @patch("syncManager.id", "test_id")
    @patch("syncManager.pw", "test_pw")
    @patch("syncManager.randomSleep")
    @patch("syncManager.randomRealSleep")
    @patch("syncManager.checkLoginSession", return_value=False)
    def test_sync_naver_single_date_yeoyu(
        self, mock_check_session, mock_real_sleep, mock_sleep
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
            result = SyncNaver(mock_driver, "2024-08-19", "Yeoyu")

        assert len(result) == 1
        assert result[0] == "2024-08-19"
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
            result = SyncNaver(
                mock_driver, "2024-08-19,2024-08-20,2024-08-21", "Yeohang"
            )

        assert len(result) == 3
        assert result[0] == "2024-08-19"
        assert result[1] == "2024-08-20"
        assert result[2] == "2024-08-21"
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
            result = SyncNaver(mock_driver, "2024-08-19", "Yeoyu")

        assert len(result) == 0
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

        with patch(
            "syncManager.simpleManagementController.SimpleManagementController",
            return_value=mock_controller,
        ):
            result = SyncNaver(
                mock_driver, "2024-08-19,2024-08-20,2024-08-21", "Yeoyu"
            )

        assert len(result) == 2
        assert "2024-08-19" in result
        assert "2024-08-21" in result
        assert "2024-08-20" not in result


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
