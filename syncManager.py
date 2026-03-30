import datetime
import json
import os
import shutil
import time
from enum import Enum
from random import randint
from typing import Optional, Tuple

from dotenv import load_dotenv

import bookingListExtractor
import driver
import log
import simpleManagementController


class RoomType(Enum):
    Yeoyu = 0
    Yeohang = 1


class ReservationLookupError(RuntimeError):
    def __init__(self, reason: str, sessionId: Optional[str] = None):
        self.reason = reason
        self.sessionId = sessionId
        if sessionId:
            super().__init__(f"{reason} (sessionId={sessionId})")
        else:
            super().__init__(reason)


# Constant
naverBizUrl = "https://nid.naver.com/nidlogin.login?svctype=1&locale=ko_KR&url=https%3A%2F%2Fnew.smartplace.naver.com%2F%3Fnext%3Dbooking-order-management&area=bbt"
naverLoginUrl = "https://nid.naver.com/nidlogin.login"
naverMainUrl = "https://www.naver.com"
simpleReservationManagementUrl = (
    "https://partner.booking.naver.com/bizes/899762/simple-management"
)
bookingListUrl = "https://partner.booking.naver.com/bizes/899762/booking-list-view"
domDiagnosticDir = os.environ.get("DOM_DIAGNOSTIC_DIR", "logs/dom_diagnostics")
enableDomDiagnostics = os.environ.get("ENABLE_DOM_DIAGNOSTICS", "").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
bookingListReadySelectors = [
    'a[class^="BookingListView__contents-user"]',
    'a[class^="DatePeriodCalendar__date-info"]',
    'button[class*="DatePeriodCalendar__next"]',
]
pageStateSelectors = {
    "bookingCards": 'a[class^="BookingListView__contents-user"]',
    "calendarDateInfo": 'a[class^="DatePeriodCalendar__date-info"]',
    "calendarNextButton": 'button[class*="DatePeriodCalendar__next"]',
    "simpleManagementTable": 'div[class*="SimpleManagement__management-tbody"]',
}
securityKeywords = [
    "로그인",
    "인증",
    "보안",
    "차단",
    "캡차",
    "captcha",
    "2단계",
    "본인확인",
    "휴대전화",
]


def getDiagnosticRetentionDays() -> int:
    try:
        return max(0, int(os.environ.get("DOM_DIAGNOSTIC_RETENTION_DAYS", "0")))
    except ValueError:
        return 0


load_dotenv()

id = os.environ.get("ID")
pw = os.environ.get("PASSWORD")


def checkLoginSession(driverInstance: driver.Driver) -> bool:
    """
    네이버 메인 페이지에서 로그인 세션이 유지되어 있는지 확인
    Returns: True if logged in, False otherwise
    """
    try:
        driverInstance.goTo(naverMainUrl)
        log.info("[Session Check] 네이버 메인 페이지 이동")
        
        # 로그인 상태 확인: 로그인 버튼 존재 여부로 판단
        loginBtnCount = _countSelector(driverInstance, 'a.MyView-module__link_login___HpHMW')
        logoutBtnCount = _countSelector(driverInstance, 'a.MyView-module__link_logout___HLv1Y')
        
        if logoutBtnCount > 0:
            log.info("[Session Check] ✓ 프로필 로그인 세션 유지됨 - 로그인 스킵")
            return True
        elif loginBtnCount > 0:
            log.info("[Session Check] ✗ 로그인 세션 없음 - 로그인 필요")
            return False
        else:
            # 다른 방법으로 확인: 페이지 소스에서 로그인 관련 텍스트 확인
            pageSource = driverInstance.getPageSource()
            if '로그아웃' in pageSource or 'logout' in pageSource.lower():
                log.info("[Session Check] ✓ 프로필 로그인 세션 유지됨 (텍스트 확인) - 로그인 스킵")
                return True
            else:
                log.info("[Session Check] ✗ 로그인 상태 불명확 - 로그인 진행")
                return False
    except Exception as e:
        log.error("[Session Check] 세션 확인 중 오류 발생", e)
        return False


def performLogin(driverInstance: driver.Driver):
    """
    네이버 로그인 수행
    """
    driverInstance.goTo(naverLoginUrl)
    log.info("네이버 로그인 페이지 이동")
    driverInstance.login(id, pw)
    driverInstance.findBySelector("#log\\.login").click()
    log.info("로그인 성공")
    randomSleep(driverInstance)
    randomRealSleep()


def randomSleep(dirver: driver.Driver):
    sleepTime = randint(15, 30) / 10
    log.info(f"Random Sleep: {sleepTime}")
    dirver.wait(sleepTime)


def randomRealSleep():
    sleepTime = randint(15, 30) / 5
    log.info(f"Long Sleep: {sleepTime}")
    time.sleep(sleepTime)


def _safeDriverCall(callback, default=None):
    try:
        return callback()
    except Exception:
        return default


def _countSelector(driverInstance: driver.Driver, selector: str) -> int:
    result = _safeDriverCall(
        lambda: driverInstance.executeScript(
            "return document.querySelectorAll(arguments[0]).length;", selector
        ),
        0,
    )
    return int(result or 0)


def _getPageState(driverInstance: driver.Driver) -> dict:
    bodyText = _safeDriverCall(
        lambda: driverInstance.executeScript(
            "return document.body ? document.body.innerText : '';"
        ),
        "",
    )
    if bodyText is None:
        bodyText = ""
    elif not isinstance(bodyText, str):
        bodyText = str(bodyText)

    selectorCounts = {
        key: _countSelector(driverInstance, selector)
        for key, selector in pageStateSelectors.items()
    }
    lowerBodyText = bodyText.lower()
    detectedKeywords = [
        keyword for keyword in securityKeywords if keyword.lower() in lowerBodyText
    ]

    return {
        "currentUrl": _safeDriverCall(driverInstance.getCurrentUrl, ""),
        "title": _safeDriverCall(driverInstance.getTitle, ""),
        "readyState": _safeDriverCall(
            lambda: driverInstance.executeScript("return document.readyState;"), None
        ),
        "userAgent": _safeDriverCall(
            lambda: driverInstance.executeScript("return navigator.userAgent;"), None
        ),
        "bodyTextPreview": bodyText[:500],
        "hasBookingListEmptyState": bookingListExtractor.hasBookingListEmptyText(bodyText),
        "selectorCounts": selectorCounts,
        "detectedKeywords": detectedKeywords,
        "browserInfo": _safeDriverCall(driverInstance.getBrowserInfo, {}),
    }


def cleanupOldDiagnosticSessions():
    retentionDays = getDiagnosticRetentionDays()
    if retentionDays <= 0 or not os.path.isdir(domDiagnosticDir):
        return

    cutoff = time.time() - (retentionDays * 24 * 60 * 60)
    for sessionId in os.listdir(domDiagnosticDir):
        sessionDir = os.path.join(domDiagnosticDir, sessionId)
        if not os.path.isdir(sessionDir):
            continue
        sessionMtime = os.path.getmtime(sessionDir)
        if sessionMtime < cutoff:
            shutil.rmtree(sessionDir, ignore_errors=True)
            log.info(
                f"Deleted expired diagnostic session: {sessionDir} (retentionDays={retentionDays})"
            )


def collectPageDiagnostics(
    driverInstance: driver.Driver, stage: str, sessionId: str, forceWrite: bool = False
) -> dict:
    pageState = _getPageState(driverInstance)
    log.info(
        f"DOM state [{stage}]: {json.dumps(pageState, ensure_ascii=False, default=str)}"
    )

    if not (enableDomDiagnostics or forceWrite):
        return pageState

    cleanupOldDiagnosticSessions()
    snapshotDir = os.path.join(domDiagnosticDir, sessionId)
    os.makedirs(snapshotDir, exist_ok=True)

    fileBase = os.path.join(snapshotDir, stage)
    htmlPath = f"{fileBase}.html"
    jsonPath = f"{fileBase}.json"
    screenshotPath = f"{fileBase}.png"

    html = _safeDriverCall(
        lambda: driverInstance.executeScript(
            "return document.documentElement ? document.documentElement.outerHTML : '';"
        ),
        "",
    )
    if not html:
        html = _safeDriverCall(driverInstance.getPageSource, "")
    if html is None:
        html = ""
    elif not isinstance(html, str):
        html = str(html)

    with open(htmlPath, "w", encoding="utf-8") as htmlFile:
        htmlFile.write(html or "")
    with open(jsonPath, "w", encoding="utf-8") as jsonFile:
        json.dump(pageState, jsonFile, ensure_ascii=False, indent=2, default=str)

    screenshotSaved = _safeDriverCall(
        lambda: driverInstance.saveScreenshot(screenshotPath), False
    )
    log.info(
        f"DOM diagnostics saved [{stage}]: html={htmlPath}, json={jsonPath}, screenshot={screenshotPath}, screenshotSaved={screenshotSaved}"
    )

    return pageState


def waitForBookingListDom(
    driverInstance: driver.Driver, sessionId: str, stage: str, timeout: int = 20
):
    _safeDriverCall(lambda: driverInstance.waitForDocumentReady(timeout), None)
    deadline = time.time() + timeout
    while time.time() < deadline:
        for selector in bookingListReadySelectors:
            selectorCount = _countSelector(driverInstance, selector)
            if selectorCount > 0:
                matchedSelector = {"selector": selector, "count": selectorCount}
                log.info(
                    f"Booking list DOM ready [{stage}]: {json.dumps(matchedSelector, ensure_ascii=False, default=str)}"
                )
                return matchedSelector

        bodyText = _safeDriverCall(
            lambda: driverInstance.executeScript(
                "return document.body ? document.body.innerText : '';"
            ),
            "",
        )
        if bodyText and bookingListExtractor.hasBookingListEmptyText(str(bodyText)):
            emptyState = {"emptyState": True}
            log.info(
                f"Booking list DOM ready [{stage}]: {json.dumps(emptyState, ensure_ascii=False, default=str)}"
            )
            return emptyState

        time.sleep(0.5)

    log.error(f"Booking list DOM wait timeout [{stage}]", TimeoutError(stage))
    collectPageDiagnostics(driverInstance, f"{stage}_timeout", sessionId, forceWrite=True)
    return None


def _isPageStateSuspicious(pageState: Optional[dict]) -> Tuple[bool, Optional[str]]:
    if not pageState:
        return True, "page state is unavailable"

    detectedKeywords = pageState.get("detectedKeywords") or []
    if detectedKeywords:
        return (
            True,
            f"security or verification page detected: {', '.join(detectedKeywords[:5])}",
        )

    if pageState.get("hasBookingListEmptyState"):
        return False, None

    selectorCounts = pageState.get("selectorCounts") or {}
    bookingCards = selectorCounts.get("bookingCards", 0)
    calendarDateInfo = selectorCounts.get("calendarDateInfo", 0)
    calendarNextButton = selectorCounts.get("calendarNextButton", 0)

    if bookingCards == 0 and calendarDateInfo == 0 and calendarNextButton == 0:
        return True, "booking list DOM is empty"

    return False, None


def makeTargetDateList(dateListStr: str) -> list:
    dateList = dateListStr.split(",")
    dateList.sort()
    targetDateList = list(map(lambda x: makeTargetDate(x), dateList))
    return targetDateList


def makeTargetDate(dateStr: str) -> datetime.date:
    dateList = dateStr.split("-")
    return datetime.date(int(dateList[0]), int(dateList[1]), int(dateList[2]))


def SyncNaver(driver: driver.Driver, targetDateStr: str, targetRoom: str) -> list:
    targetRoomEnum = RoomType[targetRoom]
    successDates = []

    reservationManager = simpleManagementController.SimpleManagementController()
    
    # 세션 확인 후 로그인 스킵 또는 진행
    if not checkLoginSession(driver):
        performLogin(driver)

    driver.goTo(simpleReservationManagementUrl)
    log.info("간단예약관리 페이지 이동")
    randomSleep(driver)
    randomRealSleep()

    targetDateList = makeTargetDateList(targetDateStr)
    for targetDate in targetDateList:
        log.info(f"{targetDate} 예약 변경 시작")
        idxOfDate = reservationManager.findTargetPage(driver, targetDate)
        if idxOfDate == -1:
            log.info("해당 날짜가 존재하지 않습니다.")
            log.info(f"{targetDate} 예약 변경 종료")
            continue

        targetBtn = reservationManager.findTargetBtn(
            driver, idxOfDate, targetRoomEnum.value
        )
        driver.executeScript("arguments[0].click();", targetBtn)

        randomSleep(driver)
        successDates.append(str(targetDate))
        log.info(f"{targetDate}, {targetRoomEnum.name}, 예약 변경 완료")

    return successDates


def getNaverReservation(driver: driver.Driver, monthSize: int) -> tuple:
    sessionId = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    # 세션 확인 후 로그인 스킵 또는 진행
    if not checkLoginSession(driver):
        performLogin(driver)
    
    log.info(
        f"Browser runtime info: {json.dumps(driver.getBrowserInfo(), ensure_ascii=False, default=str)}"
    )
    collectPageDiagnostics(driver, "after_login", sessionId)

    driver.goTo(bookingListUrl)
    log.info("예약자관리 페이지 이동")
    randomSleep(driver)
    randomRealSleep()
    if waitForBookingListDom(driver, sessionId, "booking_list_initial") is None:
        raise ReservationLookupError("booking list page did not become ready", sessionId)
    initialPageState = collectPageDiagnostics(driver, "booking_list_loaded", sessionId)
    isSuspicious, suspiciousReason = _isPageStateSuspicious(initialPageState)
    if isSuspicious:
        raise ReservationLookupError(suspiciousReason, sessionId)

    bookingList = []
    for i in range(monthSize):
        monthIndex = i + 1
        stageBase = f"booking_list_month_{monthIndex}"
        log.info(f"{monthIndex}번째 월 예약자 정보 가져오기 시작")
        if waitForBookingListDom(driver, sessionId, stageBase) is None:
            raise ReservationLookupError(
                f"booking list DOM wait timed out at {stageBase}", sessionId
            )
        randomRealSleep()
        pageState = collectPageDiagnostics(driver, stageBase, sessionId)
        isSuspicious, suspiciousReason = _isPageStateSuspicious(pageState)
        if isSuspicious:
            raise ReservationLookupError(
                f"{suspiciousReason} at {stageBase}", sessionId
            )

        pageSource = driver.getPageSource()
        monthBookingList = bookingListExtractor.extractBookingList(pageSource)
        log.info(f"length: {len(monthBookingList)}")
        log.info(monthBookingList)
        if len(monthBookingList) == 0:
            if bookingListExtractor.hasBookingListEmptyState(pageSource):
                log.info(f"No reservations found for {stageBase}; treating as empty month")
            else:
                collectPageDiagnostics(driver, f"{stageBase}_empty", sessionId, True)
                selectorCounts = pageState.get("selectorCounts") or {}
                if selectorCounts.get("bookingCards", 0) == 0:
                    raise ReservationLookupError(
                        f"no booking cards found in DOM at {stageBase}", sessionId
                    )
                raise ReservationLookupError(
                    f"booking list parsing returned no items at {stageBase}", sessionId
                )
        bookingList.extend(monthBookingList)

        if i < monthSize - 1:
            nextButtonCount = pageState["selectorCounts"].get("calendarNextButton", 0)
            if nextButtonCount == 0:
                log.info(f"Next calendar button missing before click [{stageBase}]")
                collectPageDiagnostics(
                    driver, f"{stageBase}_next_missing", sessionId, True
                )
                raise ReservationLookupError(
                    f"next calendar button is missing at {stageBase}", sessionId
                )
            try:
                driver.waitForAnySelector(
                    ['button[class*="DatePeriodCalendar__next"]'], 10
                )
                btn = driver.findByXpath(
                    '//button[contains(@class, "DatePeriodCalendar__next")]'
                )
                if btn.is_enabled():
                    driver.executeScript("arguments[0].click();", btn)
                    _safeDriverCall(lambda: driver.waitForDocumentReady(10), None)
                    randomRealSleep()
                else:
                    log.info(f"Next calendar button disabled [{stageBase}]")
                    collectPageDiagnostics(
                        driver, f"{stageBase}_next_disabled", sessionId, True
                    )
                    raise ReservationLookupError(
                        f"next calendar button is disabled at {stageBase}", sessionId
                    )
            except Exception as e:
                log.error(f"Failed to advance booking calendar [{stageBase}]", e)
                collectPageDiagnostics(
                    driver, f"{stageBase}_next_error", sessionId, True
                )
                raise ReservationLookupError(
                    f"failed to advance booking calendar at {stageBase}: {e}",
                    sessionId,
                ) from e

    bookingList = list(
        {booking["reservationNumber"]: booking for booking in bookingList}.values()
    )
    kst = datetime.timezone(datetime.timedelta(hours=9), "Asia/Seoul")
    now = datetime.datetime.now(datetime.timezone.utc).astimezone(kst)
    for booking in bookingList:
        start = datetime.datetime.strptime(booking["startDate"], "%Y%m%d").replace(
            tzinfo=kst
        )
        log.info(f"{start} {now} {start > now}")
    bookingList = list(
        filter(
            lambda x: datetime.datetime.strptime(x["startDate"], "%Y%m%d").replace(
                tzinfo=kst
            )
            > now,
            bookingList,
        )
    )
    log.info(f"취소 포함 총 예약 수 : {len(bookingList)}")
    log.info(bookingList)
    driver.close()
    notCanceledBookingList = list(filter(lambda x: x["status"] != "취소", bookingList))
    log.info(f"취소 미포함 확정 예약 수 : {len(notCanceledBookingList)}")
    log.info(notCanceledBookingList)
    return notCanceledBookingList, bookingList
