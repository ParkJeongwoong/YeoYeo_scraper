import datetime


KST = datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")


def parse_target_date(value: str) -> datetime.date:
    return datetime.datetime.strptime(value, "%Y-%m-%d").date()


def parse_target_dates(value: str) -> list:
    return sorted(parse_target_date(item) for item in value.split(","))


def normalize_booking_lists(bookings: list, now=None) -> tuple:
    """Deduplicate bookings and return future non-canceled/all booking lists."""
    unique_bookings = list({
        booking["reservationNumber"]: booking for booking in bookings
    }.values())
    current_time = now or datetime.datetime.now(datetime.timezone.utc).astimezone(KST)
    future_bookings = [
        booking for booking in unique_bookings
        if datetime.datetime.strptime(booking["startDate"], "%Y%m%d").replace(
            tzinfo=KST
        ) > current_time
    ]
    not_canceled = [
        booking for booking in future_bookings
        if str(booking.get("status", "")).strip() != "취소"
    ]
    return not_canceled, future_bookings
