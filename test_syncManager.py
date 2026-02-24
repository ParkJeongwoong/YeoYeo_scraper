import pytest
import datetime
from unittest.mock import Mock, MagicMock, patch
from syncManager import (
    makeTargetDateList,
    makeTargetDate,
    SyncNaver,
    getNaverReservation,
    RoomType,
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
    def test_sync_naver_single_date_yeoyu(
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

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")

        mock_extract.return_value = [
            {
                "reservationNumber": "12345",
                "startDate": future_date_str,
                "status": "예약확정",
            }
        ]

        result = getNaverReservation(mock_driver, 1)

        assert len(result) == 2
        not_canceled, all_bookings = result
        assert len(not_canceled) == 1
        assert len(all_bookings) == 1
        assert not_canceled[0]["reservationNumber"] == "12345"

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

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")

        mock_extract.return_value = [
            {
                "reservationNumber": f"1234{i}",
                "startDate": future_date_str,
                "status": "예약확정",
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
    def test_get_naver_reservation_filters_canceled(
        self, mock_extract, mock_real_sleep, mock_sleep
    ):
        mock_driver = MagicMock()
        mock_driver.findBySelector.return_value.click = MagicMock()
        mock_driver.getPageSource.return_value = "<html></html>"
        mock_driver.findByXpath.return_value = MagicMock()

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")

        mock_extract.return_value = [
            {
                "reservationNumber": "12345",
                "startDate": future_date_str,
                "status": "예약확정",
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
        assert not_canceled[0]["status"] == "예약확정"

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

        future_date = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        ) + datetime.timedelta(days=7)
        future_date_str = future_date.strftime("%Y%m%d")

        mock_extract.side_effect = [
            [
                {
                    "reservationNumber": "12345",
                    "startDate": future_date_str,
                    "status": "예약확정",
                }
            ],
            [
                {
                    "reservationNumber": "12345",
                    "startDate": future_date_str,
                    "status": "예약확정",
                },
                {
                    "reservationNumber": "67890",
                    "startDate": future_date_str,
                    "status": "예약확정",
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

        kst = datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
        now = datetime.datetime.now(datetime.timezone.utc).astimezone(kst)
        
        past_date = (now - datetime.timedelta(days=7)).strftime("%Y%m%d")
        future_date = (now + datetime.timedelta(days=7)).strftime("%Y%m%d")

        mock_extract.return_value = [
            {
                "reservationNumber": "12345",
                "startDate": past_date,
                "status": "예약확정",
            },
            {
                "reservationNumber": "67890",
                "startDate": future_date,
                "status": "예약확정",
            },
        ]

        result = getNaverReservation(mock_driver, 1)

        not_canceled, all_bookings = result
        assert len(all_bookings) == 1
        assert all_bookings[0]["reservationNumber"] == "67890"


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
