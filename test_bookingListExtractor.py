import pytest
from bookingListExtractor import (
    extractBookingInfo,
    getStartEndDate,
    hasBookingListEmptyState,
    hasBookingListEmptyText,
    parseDateInfo,
)
from bs4 import BeautifulSoup as bs


class TestParseDateInfo:
    def test_single_digit_month_and_day(self):
        result = parseDateInfo("24. 8. 9.(월)")
        assert result == "20240809"

    def test_double_digit_month_and_day(self):
        result = parseDateInfo("24. 12. 25.(수)")
        assert result == "20241225"

    def test_mixed_digit_month_and_day(self):
        result = parseDateInfo("24. 1. 15.(월)")
        assert result == "20240115"

    def test_different_year_format(self):
        result = parseDateInfo("25. 3. 7.(금)")
        assert result == "20250307"

    def test_end_of_year_date(self):
        result = parseDateInfo("24. 12. 31.(화)")
        assert result == "20241231"

    def test_start_of_year_date(self):
        result = parseDateInfo("24. 1. 1.(월)")
        assert result == "20240101"

    def test_with_extra_spaces(self):
        result = parseDateInfo(" 24 . 8 . 19 .(월)")
        assert result == "20240819"


class TestGetStartEndDate:
    def test_valid_date_range(self):
        dateStr = "24. 8. 19.(월)~24. 8. 21.(수)"
        result = getStartEndDate(dateStr)
        assert result == ("20240819", "20240821")

    def test_single_digit_dates(self):
        dateStr = "24. 1. 5.(토)~24. 1. 7.(월)"
        result = getStartEndDate(dateStr)
        assert result == ("20240105", "20240107")

    def test_month_transition(self):
        dateStr = "24. 8. 30.(금)~24. 9. 1.(일)"
        result = getStartEndDate(dateStr)
        assert result == ("20240830", "20240901")

    def test_year_transition(self):
        dateStr = "24. 12. 30.(월)~25. 1. 2.(목)"
        result = getStartEndDate(dateStr)
        assert result == ("20241230", "20250102")


class TestExtractBookingInfo:
    def test_extract_booking_with_all_fields(self):
        html = """
        <a class="BookingListView__contents-user">
            <div class="BookingListView__name"><span>홍길동</span></div>
            <div class="BookingListView__phone"><span>010-1234-5678</span></div>
            <div class="BookingListView__book-number">12345678</div>
            <div class="BookingListView__book-date">24. 8. 19.(월)~24. 8. 21.(수)</div>
            <div class="BookingListView__host">여유</div>
            <div class="BookingListView__option">조식 포함</div>
            <div class="BookingListView__comment">늦은 체크인 요청</div>
            <div class="BookingListView__total-price">150,000원</div>
            <div class="BookingListView__state"><span>예약확정</span></div>
        </a>
        """
        soup = bs(html, "html.parser")
        booking = soup.select_one("a")
        result = extractBookingInfo(booking)

        assert result["name"] == "홍길동"
        assert result["phone"] == "010-1234-5678"
        assert result["reservationNumber"] == "12345678"
        assert result["startDate"] == "20240819"
        assert result["endDate"] == "20240821"
        assert result["room"] == "여유"
        assert result["option"] == "조식 포함"
        assert result["comment"] == "늦은 체크인 요청"
        assert result["price"] == "150,000원"
        assert result["status"] == "예약확정"

    def test_extract_booking_with_missing_fields(self):
        html = """
        <a class="BookingListView__contents-user">
            <div class="BookingListView__name"><span>김철수</span></div>
            <div class="BookingListView__phone"><span>010-9876-5432</span></div>
            <div class="BookingListView__book-number">87654321</div>
            <div class="BookingListView__book-date">24. 9. 1.(일)~24. 9. 3.(화)</div>
            <div class="BookingListView__host">여행</div>
            <div class="BookingListView__total-price">200,000원</div>
            <div class="BookingListView__state"><span>취소</span></div>
        </a>
        """
        soup = bs(html, "html.parser")
        booking = soup.select_one("a")
        result = extractBookingInfo(booking)

        assert result["name"] == "김철수"
        assert result["phone"] == "010-9876-5432"
        assert result["reservationNumber"] == "87654321"
        assert result["startDate"] == "20240901"
        assert result["endDate"] == "20240903"
        assert result["room"] == "여행"
        assert result["option"] is None
        assert result["comment"] is None
        assert result["price"] == "200,000원"
        assert result["status"] == "취소"

    def test_extract_booking_with_no_comment(self):
        html = """
        <a class="BookingListView__contents-user">
            <div class="BookingListView__name"><span>이영희</span></div>
            <div class="BookingListView__phone"><span>010-1111-2222</span></div>
            <div class="BookingListView__book-number">11112222</div>
            <div class="BookingListView__book-date">24. 10. 15.(화)~24. 10. 17.(목)</div>
            <div class="BookingListView__host">여유</div>
            <div class="BookingListView__option">바베큐 세트</div>
            <div class="BookingListView__total-price">180,000원</div>
            <div class="BookingListView__state"><span>예약확정</span></div>
        </a>
        """
        soup = bs(html, "html.parser")
        booking = soup.select_one("a")
        result = extractBookingInfo(booking)

        assert result["name"] == "이영희"
        assert result["comment"] is None
        assert result["option"] == "바베큐 세트"


class TestHasBookingListEmptyState:
    def test_returns_true_for_known_empty_text(self):
        text = "예약0건 조회된 예약내역이 없습니다. 기간과 기준,필터를 확인한 후 다시 조회해 주세요."

        assert hasBookingListEmptyText(text) is True

    def test_returns_true_for_naver_empty_booking_message(self):
        html = """
        <html>
            <body>
                <div>예약0건</div>
                <div>조회된 예약내역이 없습니다.</div>
                <div>기간과 기준,필터를 확인한 후 다시 조회해 주세요.</div>
            </body>
        </html>
        """

        assert hasBookingListEmptyState(html) is True

    def test_returns_false_when_empty_state_message_is_absent(self):
        html = """
        <html>
            <body>
                <a class="BookingListView__contents-user">예약 카드</a>
            </body>
        </html>
        """

        assert hasBookingListEmptyState(html) is False
