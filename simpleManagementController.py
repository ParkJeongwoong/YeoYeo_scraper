from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import NoSuchElementException
from bs4 import BeautifulSoup as bs
import re
import datetime
from time import sleep
import log


class SimpleManagementController:
    ROOM_NAMES = ("Yeoyu", "Yeohang")

    def findTargetPage(self, driver, targetDate: datetime.date) -> int:
        html = driver.getPageSource()
        searchLimit = 35
        while searchLimit > 0:
            idx = self.findTargetPeriod(targetDate, html, driver)
            if idx != -1:
                return idx
            html = driver.getPageSource()
            searchLimit -= 1
            sleep(1)
        return -1

    def findTargetPeriod(self, targetDate: datetime.date, html: str, driver) -> int:
        soup = bs(html, "html.parser")
        dateInfo = soup.select('a[class^="DatePeriodCalendar__date-info"]')
        rawDateData = re.search(">(.*?)<", str(dateInfo)).group(1).split(" ~ ")
        log.info(rawDateData)
        endDateParts = [part.strip() for part in rawDateData[1].split(".") if part.strip()]
        if len(endDateParts) == 2:
            startYear = rawDateData[0].split(".")[0].strip()
            rawDateData[1] = f"{startYear}.{rawDateData[1]}"
            log.info("NEW " + rawDateData[1])
        startDate: datetime.date = self.parseDateInfo(rawDateData[0])
        endDate: datetime.date = self.parseDateInfo(rawDateData[1])
        log.info(f"startDate: {startDate}, endDate: {endDate}")

        if targetDate >= startDate and targetDate <= endDate:
            log.info("Target 범위에 존재")
            diff = targetDate - startDate
            log.info(f"idx: {diff.days}")
            return diff.days
        else:
            log.info("Target 범위에 존재하지 않음")
            btn = driver.findByXpath(
                '//button[contains(@class, "DatePeriodCalendar__next")]'
            )
            driver.executeScript("arguments[0].click();", btn)
            return -1

    def parseDateInfo(self, dateInfoData: str) -> datetime.date:
        dateInfoList = dateInfoData.split(".")
        dateInfoList = list(map(lambda x: x.strip(), dateInfoList))
        if len(dateInfoList[0]) == 2:
            dateInfoList[0] = "20" + dateInfoList[0]
        log.info(dateInfoList)
        return datetime.date(
            int(dateInfoList[0]), int(dateInfoList[1]), int(dateInfoList[2])
        )

    def findTargetBtn(self, driver, idxOfDate: int, targetRoomValue: int) -> WebElement:
        reservationTable = driver.findByXpath(
            '//div[contains(@class, "SimpleManagement__management-tbody")]'
        )
        roomList = driver.findChildElementsByXpath(
            reservationTable,
            './div[contains(@class, "SimpleManagement__management-row")]',
        )
        log.info(f"roomList length: {len(roomList)}")
        reservationList = driver.findChildElementsByXpath(
            roomList[targetRoomValue],
            './div[contains(@class, "SimpleManagement__content")]',
        )
        log.info(f"reservationList length: {len(reservationList)}")
        targetCell = reservationList[idxOfDate]
        labelList = driver.findChildElementsByXpath(targetCell, ".//label")
        if len(labelList) > 0:
            return labelList[0]

        log.info(
            "Target reservation label missing: "
            f"roomIndex={targetRoomValue}, dateIndex={idxOfDate}, "
            f"cellText={self._safeElementText(targetCell)}, "
            f"cellHtml={self._safeOuterHtml(targetCell)}"
        )
        raise NoSuchElementException(
            "Unable to locate reservation label in target cell "
            f"(roomIndex={targetRoomValue}, dateIndex={idxOfDate})"
        )

    def inspectToggleStates(self, driver, targetDate: datetime.date) -> list:
        """Read reservation counts and toggle properties without clicking controls."""
        idxOfDate = self.findTargetPage(driver, targetDate)
        if idxOfDate == -1:
            raise ToggleStateInspectionError("DATE_NOT_AVAILABLE_IN_NAVER_CALENDAR")

        dateHeaders = self.extractDateHeaders(driver.getPageSource())
        if idxOfDate >= len(dateHeaders) or dateHeaders[idxOfDate] != targetDate:
            raise ToggleStateInspectionError("TARGET_CELL_NOT_FOUND")

        reservationTable = driver.findByXpath(
            '//div[contains(@class, "SimpleManagement__management-tbody")]'
        )
        roomRows = driver.findChildElementsByXpath(
            reservationTable,
            './div[contains(@class, "SimpleManagement__management-row")]',
        )
        if len(roomRows) < len(self.ROOM_NAMES):
            raise ToggleStateInspectionError("DOM_STRUCTURE_CHANGED")

        results = []
        for roomName, roomRow in zip(self.ROOM_NAMES, roomRows):
            cells = driver.findChildElementsByXpath(
                roomRow,
                './div[contains(@class, "SimpleManagement__content")]',
            )
            if len(cells) != len(dateHeaders):
                raise ToggleStateInspectionError("DOM_STRUCTURE_CHANGED")

            targetCell = cells[idxOfDate]
            checkboxes = driver.findChildElementsByXpath(
                targetCell,
                './/input[contains(concat(" ", normalize-space(@class), " "), " switch-input-check ")]',
            )
            if not checkboxes:
                raise ToggleStateInspectionError("TARGET_TOGGLE_NOT_FOUND")

            countButtons = driver.findChildElementsByXpath(targetCell, ".//button")
            if not countButtons:
                raise ToggleStateInspectionError("TARGET_CELL_NOT_FOUND")

            checkbox = checkboxes[0]
            switchOn = bool(checkbox.is_selected())
            results.append({
                "room": roomName,
                "date": str(targetDate),
                "reservationCount": countButtons[0].text.strip(),
                "switchOn": switchOn,
                "externallyBlocked": not switchOn,
            })
        return results

    def extractDateHeaders(self, html: str) -> list:
        soup = bs(html, "html.parser")
        dateInfo = soup.select('a[class^="DatePeriodCalendar__date-info"]')
        if not dateInfo:
            raise ToggleStateInspectionError("DOM_STRUCTURE_CHANGED")

        rawDateData = dateInfo[0].get_text(strip=True).split(" ~ ")
        if len(rawDateData) != 2:
            raise ToggleStateInspectionError("DOM_STRUCTURE_CHANGED")
        endDateParts = [part.strip() for part in rawDateData[1].split(".") if part.strip()]
        if len(endDateParts) == 2:
            startYear = rawDateData[0].split(".")[0].strip()
            rawDateData[1] = f"{startYear}.{rawDateData[1]}"

        startDate = self.parseDateInfo(rawDateData[0])
        endDate = self.parseDateInfo(rawDateData[1])
        if endDate < startDate:
            raise ToggleStateInspectionError("DOM_STRUCTURE_CHANGED")
        return [
            startDate + datetime.timedelta(days=offset)
            for offset in range((endDate - startDate).days + 1)
        ]

    def _safeElementText(self, element: WebElement) -> str:
        try:
            return str(element.text)[:500]
        except Exception:
            return ""

    def _safeOuterHtml(self, element: WebElement) -> str:
        try:
            return str(element.get_attribute("outerHTML"))[:1000]
        except Exception:
            return ""


class ToggleStateInspectionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
