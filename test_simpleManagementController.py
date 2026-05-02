import pytest
import datetime
from simpleManagementController import SimpleManagementController
from unittest.mock import Mock, MagicMock
from bs4 import BeautifulSoup as bs
from selenium.common.exceptions import NoSuchElementException


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


class TestFindTargetBtn:
    def test_searches_entire_date_cell_when_first_child_has_no_label(self):
        controller = SimpleManagementController()
        mock_driver = MagicMock()
        table = MagicMock()
        rows = [MagicMock(), MagicMock()]
        cells = [MagicMock() for _ in range(7)]
        target_label = MagicMock()

        mock_driver.findByXpath.return_value = table

        def find_children(element, selector):
            if element is table:
                return rows
            if element is rows[1]:
                return cells
            if element is cells[6] and selector == ".//label":
                return [target_label]
            return []

        mock_driver.findChildElementsByXpath.side_effect = find_children
        mock_driver.findChildElement.side_effect = [
            MagicMock(),
            NoSuchElementException("first wrapper has no label"),
        ]

        result = controller.findTargetBtn(mock_driver, 6, 1)

        assert result is target_label
        mock_driver.findChildElement.assert_not_called()

    def test_raises_with_indexes_when_target_cell_has_no_label(self):
        controller = SimpleManagementController()
        mock_driver = MagicMock()
        table = MagicMock()
        row = MagicMock()
        cell = MagicMock()
        cell.text = "closed"
        cell.get_attribute.return_value = "<div>closed</div>"

        mock_driver.findByXpath.return_value = table

        def find_children(element, selector):
            if element is table:
                return [row]
            if element is row:
                return [cell]
            if element is cell and selector == ".//label":
                return []
            return []

        mock_driver.findChildElementsByXpath.side_effect = find_children

        with pytest.raises(NoSuchElementException) as exc_info:
            controller.findTargetBtn(mock_driver, 0, 0)

        assert "roomIndex=0" in str(exc_info.value)
        assert "dateIndex=0" in str(exc_info.value)
