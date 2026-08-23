import pytest
import datetime
from simpleManagementController import SimpleManagementController, ToggleStateInspectionError
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


class TestReadTargetToggleState:
    def test_reads_live_checkbox_property_from_target_cell(self):
        controller = SimpleManagementController()
        driver = MagicMock()
        table = MagicMock()
        rows = [MagicMock(), MagicMock()]
        cells = [MagicMock() for _ in range(7)]
        checkbox = MagicMock()
        checkbox.is_selected.return_value = False
        driver.findByXpath.return_value = table

        def find_children(element, selector):
            if element is table:
                return rows
            if element is rows[1]:
                return cells
            if element is cells[3] and "input" in selector:
                return [checkbox]
            return []

        driver.findChildElementsByXpath.side_effect = find_children

        assert controller.readTargetToggleState(driver, 3, 1) is False

    def test_rejects_missing_checkbox_instead_of_guessing_state(self):
        controller = SimpleManagementController()
        driver = MagicMock()
        table = MagicMock()
        row = MagicMock()
        cell = MagicMock()
        driver.findByXpath.return_value = table
        driver.findChildElementsByXpath.side_effect = [[row], [cell], []]

        with pytest.raises(ToggleStateInspectionError) as exc_info:
            controller.readTargetToggleState(driver, 0, 0)

        assert exc_info.value.code == "STATE_UNDETERMINED"


class TestInspectToggleStates:
    def _build_driver(self, switch_states=(True, False), counts=("1/1", "0/1")):
        driver = MagicMock()
        table = MagicMock()
        rows = [MagicMock(), MagicMock()]
        cells = [[MagicMock() for _ in range(7)] for _ in rows]
        driver.getPageSource.return_value = (
            '<a class="DatePeriodCalendar__date-info">26. 8. 19 ~ 8. 25</a>'
        )
        driver.findByXpath.return_value = table

        def find_children(element, selector):
            if element is table:
                return rows
            for row_index, row in enumerate(rows):
                if element is row:
                    return cells[row_index]
                if element is cells[row_index][3]:
                    if "input" in selector:
                        checkbox = MagicMock()
                        checkbox.is_selected.return_value = switch_states[row_index]
                        return [checkbox]
                    if selector == ".//button":
                        button = MagicMock()
                        button.text = counts[row_index]
                        return [button]
            return []

        driver.findChildElementsByXpath.side_effect = find_children
        return driver

    def test_maps_each_room_and_reads_checkbox_property(self, monkeypatch):
        controller = SimpleManagementController()
        driver = self._build_driver()
        monkeypatch.setattr(controller, "findTargetPage", lambda *_: 3)

        result = controller.inspectToggleStates(driver, datetime.date(2026, 8, 22))

        assert result == [
            {
                "room": "Yeoyu", "date": "2026-08-22",
                "reservationCount": "1/1", "status": "naverBlocked",
            },
            {
                "room": "Yeohang", "date": "2026-08-22",
                "reservationCount": "0/1", "status": "externallyBlocked",
            },
        ]
        driver.executeScript.assert_not_called()

    @pytest.mark.parametrize(
        ("reservation_count", "switch_on", "expected"),
        [
            ("0/1", True, "available"),
            ("1/1", True, "naverBlocked"),
            ("0/1", False, "externallyBlocked"),
            ("1/1", False, "externallyBlocked"),
        ],
    )
    def test_classifies_normalized_status(
        self, reservation_count, switch_on, expected
    ):
        controller = SimpleManagementController()

        assert controller.classifyStatus(reservation_count, switch_on) == expected

    def test_rejects_unrecognized_reservation_count(self):
        controller = SimpleManagementController()

        with pytest.raises(ToggleStateInspectionError) as exc_info:
            controller.classifyStatus("예약 마감", True)

        assert exc_info.value.code == "DOM_STRUCTURE_CHANGED"

    def test_rejects_date_and_cell_count_mismatch(self, monkeypatch):
        controller = SimpleManagementController()
        driver = self._build_driver()
        monkeypatch.setattr(controller, "findTargetPage", lambda *_: 3)
        driver.findChildElementsByXpath.side_effect = lambda element, selector: (
            [MagicMock(), MagicMock()] if "management-row" in selector else []
        )

        with pytest.raises(ToggleStateInspectionError) as exc_info:
            controller.inspectToggleStates(driver, datetime.date(2026, 8, 22))

        assert exc_info.value.code == "DOM_STRUCTURE_CHANGED"

    def test_rejects_missing_checkbox(self, monkeypatch):
        controller = SimpleManagementController()
        driver = self._build_driver()
        monkeypatch.setattr(controller, "findTargetPage", lambda *_: 3)
        original = driver.findChildElementsByXpath.side_effect

        def without_checkbox(element, selector):
            if "input" in selector:
                return []
            return original(element, selector)

        driver.findChildElementsByXpath.side_effect = without_checkbox

        result = controller.inspectToggleStates(driver, datetime.date(2026, 8, 22))

        assert result[0]["status"] == "error"
        assert result[0]["errorDescription"] == "TARGET_TOGGLE_NOT_FOUND"
