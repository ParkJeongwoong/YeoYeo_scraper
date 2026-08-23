import datetime

from reservation_utils import KST, normalize_booking_lists, parse_target_dates


def test_parse_target_dates_sorts_values():
    assert parse_target_dates("2026-08-25,2026-08-23") == [
        datetime.date(2026, 8, 23), datetime.date(2026, 8, 25)
    ]


def test_parse_target_dates_allows_whitespace_around_tokens():
    assert parse_target_dates("2026-08-23, 2026-08-24 ") == [
        datetime.date(2026, 8, 23), datetime.date(2026, 8, 24)
    ]


def test_normalize_booking_lists_deduplicates_and_filters():
    now = datetime.datetime(2026, 8, 23, 12, tzinfo=KST)
    bookings = [
        {"reservationNumber": "past", "startDate": "20260822", "status": "확정"},
        {"reservationNumber": "stay", "startDate": "20260824", "status": "확정"},
        {"reservationNumber": "stay", "startDate": "20260825", "status": "확정"},
        {"reservationNumber": "cancel", "startDate": "20260826", "status": "취소"},
    ]

    not_canceled, all_bookings = normalize_booking_lists(bookings, now=now)

    assert [item["reservationNumber"] for item in all_bookings] == ["stay", "cancel"]
    assert [item["reservationNumber"] for item in not_canceled] == ["stay"]
    assert all_bookings[0]["startDate"] == "20260825"
