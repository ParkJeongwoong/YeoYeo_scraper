from bs4 import BeautifulSoup as bs


def extractBookingList(html: str) -> list:
    soup = bs(html, "html.parser")
    bookingList = soup.select('a[class^="BookingListView__contents-user"]')
    bookingInfoList = list(map(extractBookingInfo, bookingList))
    return bookingInfoList


def extractBookingInfo(booking: bs) -> dict:
    bookingInfo = {}
    name = booking.select_one('div[class*="BookingListView__name"]')
    phone = booking.select_one('div[class*="BookingListView__phone"]')
    reservationNumber = booking.select_one('div[class*="BookingListView__book-number"]')
    dateInfo = booking.select_one('div[class*="BookingListView__book-date"]')
    startDate, endDate = (
        getStartEndDate(dateInfo.get_text(strip=True)) if dateInfo else (None, None)
    )
    room = booking.select_one('div[class*="BookingListView__host"]')
    option = booking.select_one('div[class*="BookingListView__option"]')
    comment = booking.select_one('div[class*="BookingListView__comment"]')
    price = booking.select_one('div[class*="BookingListView__total-price"]')
    status = booking.select_one('div[class*="BookingListView__state"]')

    bookingInfo["name"] = name.find("span").get_text(strip=True) if name else None
    bookingInfo["phone"] = phone.find("span").get_text(strip=True) if phone else None
    bookingInfo["reservationNumber"] = (
        reservationNumber.get_text(strip=True) if reservationNumber else None
    )
    bookingInfo["startDate"] = startDate
    bookingInfo["endDate"] = endDate
    bookingInfo["room"] = room.get_text(strip=True) if room else None
    bookingInfo["option"] = option.get_text(strip=True) if option else None
    bookingInfo["comment"] = comment.get_text(strip=True) if comment else None
    bookingInfo["price"] = price.get_text(strip=True) if price else None
    bookingInfo["status"] = status.find("span").get_text(strip=True) if status else None
    return bookingInfo


def getStartEndDate(dateStr: str) -> tuple:
    dateList = dateStr.split("~")
    return (parseDateInfo(dateList[0]), parseDateInfo(dateList[1]))


def parseDateInfo(dateStr: str) -> str:
    # input은 '24. 8. 19.(월)' 형태로 들어옴
    # output은 '2024-08-19' 형태로 반환
    dateInfo = ""
    dateList = list(map(str.strip, dateStr.split(".")))
    dateInfo += "20" + dateList[0][-2:]
    if len(dateList[1]) == 1:
        dateInfo += "0" + dateList[1]
    else:
        dateInfo += dateList[1]
    if len(dateList[2]) == 1:
        dateInfo += "0" + dateList[2]
    else:
        dateInfo += dateList[2]

    return dateInfo
