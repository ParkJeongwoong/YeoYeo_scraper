from selenium.webdriver.remote.webelement import WebElement
from bs4 import BeautifulSoup as bs
import re
import datetime
from time import sleep
import log


class SimpleManagementController:
    def findTargetPage(self, driver, targetDate: datetime.date) -> int:
        html = driver.getPageSource()
        searchLimit = 10
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
        if rawDateData[1].count(".") == 2:
            rawDateData[1] = rawDateData[0][:2] + "." + rawDateData[1]
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
            driver.findByXpath(
                '//button[contains(@class, "DatePeriodCalendar__next")]'
            ).click()
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
        targetDiv = driver.findChildElement(reservationList[idxOfDate], "div")
        targetButton = driver.findChildElement(targetDiv, "input")
        return targetButton
