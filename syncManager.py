import driver
import chromeDriver
import simpleManagementController
import bookingListExtractor
from random import randint
import datetime
from enum import Enum
import time

from dotenv import load_dotenv
import os

class RoomType(Enum):
    Yeoyu = 0
    Yeohang = 1

# Constant
naverBizUrl = 'https://nid.naver.com/nidlogin.login?svctype=1&locale=ko_KR&url=https%3A%2F%2Fnew.smartplace.naver.com%2F%3Fnext%3Dbooking-order-management&area=bbt'
naverLoginUrl = 'https://nid.naver.com/nidlogin.login'
simpleReservationManagementUrl = 'https://partner.booking.naver.com/bizes/899762/simple-management'
bookingListUrl = 'https://partner.booking.naver.com/bizes/899762/booking-list-view'

load_dotenv()

id = os.environ.get('ID')
pw = os.environ.get('PASSWORD')

# Temporary Variable
# targetDateStr = '2024-09-02,2024-09-03'
# targetRoom = RoomType.Yeohang

def randomSleep(dirver: driver.Driver):
    sleepTime = randint(15, 30)/10
    print(f'Random Sleep: {sleepTime}')
    dirver.wait(sleepTime)

def randomRealSleep():
    sleepTime = randint(15, 30)/5
    print(f'Long Sleep: {sleepTime}')
    time.sleep(sleepTime)

def makeTargetDateList(dateListStr: str)->list:
    dateList = dateListStr.split(',')
    dateList.sort()
    targetDateList = list(map(lambda x: makeTargetDate(x), dateList))
    return targetDateList
    
def makeTargetDate(dateStr: str)->datetime.date:
    dateList = dateStr.split('-')
    return datetime.date(int(dateList[0]), int(dateList[1]), int(dateList[2]))

def SyncNaver(targetDateStr: str, targetRoom: str):
    targetRoom = RoomType[targetRoom]

    reservationManager = simpleManagementController.SimpleManagementController()
    driver = chromeDriver.ChromeDriver()
    driver.goTo(naverLoginUrl)
    print('네이버 로그인 페이지 이동')

    # 로그인
    driver.login(id, pw)

    driver.findBySelector('#log\.login').click()
    print('로그인 성공')
    randomSleep(driver)

    driver.goTo(simpleReservationManagementUrl)
    print('간단예약관리 페이지 이동')
    randomSleep(driver)
    randomRealSleep()

    # 날짜 변경
    targetDateList = makeTargetDateList(targetDateStr)
    for targetDate in targetDateList:
        print(targetDate, '예약 상태 변경 시작')
        idxOfDate = reservationManager.findTargetPage(driver, targetDate)
        if idxOfDate == -1:
            print('해당 날짜가 존재하지 않습니다.')
            print(targetDate, '예약 변경 실패')
            driver.close()
            return
        
        # 예약 상태 변경
        print(targetDate, '예약 상태 변경 중')
        reservationManager.findTargetBtn(driver, idxOfDate, targetRoom.value).click()

        randomSleep(driver)
        print(targetDate, targetRoom.name, '예약 변경 완료')
    driver.close()
    
def getNaverReservation(monthSize: int)-> tuple:
    driver = chromeDriver.ChromeDriver()
    driver.goTo(naverLoginUrl)
    # 로그인

    driver.login(id, pw)

    driver.findBySelector('#log\.login').click()
    print('로그인 성공')
    randomSleep(driver)

    driver.goTo(bookingListUrl)
    print('예약자관리 페이지 이동')
    randomSleep(driver)
    randomSleep(driver)
    randomRealSleep()

    # 예약자 정보 가져오기
    bookingList = []
    for i in range(monthSize):
        print(f'{i+1}번째 월 예약자 정보 가져오기 시작')
        randomSleep(driver)
        monthBookingList = bookingListExtractor.extractBookingList(driver.getPageSource())
        print("length: ", len(monthBookingList))
        print(monthBookingList)
        bookingList.extend(monthBookingList)
        driver.findByXpath('//button[contains(@class, "DatePeriodCalendar__next")]').click()
        randomRealSleep()
    # bookingList에서 중복 제거
    bookingList = list({booking['reservationNumber']: booking for booking in bookingList}.values())
    # 체크인 날짜가 오늘 이후인 예약만 남기기
    kst = datetime.timezone(datetime.timedelta(hours=9), 'Asia/Seoul')
    now = datetime.datetime.now().replace(tzinfo=kst)
    bookingList = list(filter(lambda x: datetime.datetime.strptime(x['startDate'], '%Y%m%d').replace(tzinfo=kst) > now, bookingList))
    print("취소 포함 총 예약 수 : ", len(bookingList))
    print(bookingList)
    driver.close()
    notCanceledBookingList = list(filter(lambda x: x['status'] != '취소', bookingList))
    print("취소 미포함 확정 예약 수 : ", len(notCanceledBookingList))
    print(notCanceledBookingList)
    return notCanceledBookingList, bookingList