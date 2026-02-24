import pytest
import datetime
from simpleManagementController import SimpleManagementController
from unittest.mock import Mock, MagicMock
from bs4 import BeautifulSoup as bs


class TestParseDateInfo:
    def setUp(self):
        self.controller = SimpleManagementController()

    def test_parse_date_with_full_year(self):
        controller = SimpleManagementController()
        result = controller.parseDateInfo("2024. 8. 19")
        assert result == datetime.date(2024, 8, 19)

    def test_parse_date_with_short_year(self):
        controller = SimpleManagementController()
        result = controller.parseDateInfo("24. 8. 19")
        assert result == datetime.date(2024, 8, 19)

    def test_parse_date_single_digit_month_day(self):
        controller = SimpleManagementController()
        result = controller.parseDateInfo("24. 1. 5")
        assert result == datetime.date(2024, 1, 5)

    def test_parse_date_double_digit_all(self):
        controller = SimpleManagementController()
        result = controller.parseDateInfo("24. 12. 31")
        assert result == datetime.date(2024, 12, 31)

    def test_parse_date_with_spaces(self):
        controller = SimpleManagementController()
        result = controller.parseDateInfo(" 24 . 9 . 15 ")
        assert result == datetime.date(2024, 9, 15)

    def test_parse_date_different_year(self):
        controller = SimpleManagementController()
        result = controller.parseDateInfo("25. 3. 7")
        assert result == datetime.date(2025, 3, 7)


class TestDateCalculation:
    def test_date_difference_same_month(self):
        targetDate = datetime.date(2024, 8, 22)
        startDate = datetime.date(2024, 8, 19)
        diff = targetDate - startDate
        assert diff.days == 3

    def test_date_in_range(self):
        targetDate = datetime.date(2024, 8, 22)
        startDate = datetime.date(2024, 8, 19)
        endDate = datetime.date(2024, 8, 25)
        assert targetDate >= startDate and targetDate <= endDate

    def test_date_out_of_range(self):
        targetDate = datetime.date(2024, 8, 30)
        startDate = datetime.date(2024, 8, 19)
        endDate = datetime.date(2024, 8, 25)
        assert not (targetDate >= startDate and targetDate <= endDate)

    def test_date_at_start_boundary(self):
        targetDate = datetime.date(2024, 8, 19)
        startDate = datetime.date(2024, 8, 19)
        diff = targetDate - startDate
        assert diff.days == 0

    def test_date_at_end_boundary(self):
        targetDate = datetime.date(2024, 8, 25)
        startDate = datetime.date(2024, 8, 19)
        diff = targetDate - startDate
        assert diff.days == 6

    def test_date_across_months(self):
        targetDate = datetime.date(2024, 9, 2)
        startDate = datetime.date(2024, 8, 30)
        diff = targetDate - startDate
        assert diff.days == 3
