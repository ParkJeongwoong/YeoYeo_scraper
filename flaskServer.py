# -*- coding:utf-8 -*-

from flask import Flask, jsonify, request
import syncManager
import chromeDriver

from dotenv import load_dotenv
import os
import logging
import log

load_dotenv()

activationKey = os.environ.get("ACTIVATION_KEY")

if not os.path.isdir("logs"):
    os.mkdir("logs")

logger: logging.Logger = log.getLogger("logs/server.log")
logger.setLevel(logging.INFO)

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


@app.route("/", methods=["GET"])
def hello_world():
    log.info("Hello, World!")
    return "Hello, World!"


@app.route("/", methods=["POST"])
def hello_world_post():
    req = request.get_json()
    res = {"message": "Hello, World!", "data": req}
    log.info("테스트 - Hello, World!")
    return jsonify(res), 200


@app.route("/sync/in", methods=["POST"])
def sync_naver_reservation():
    driver = chromeDriver.ChromeDriver()
    res: dict
    httpStatus: int

    try:
        req = request.get_json()
        # TODO : 마이그레이션 이후 targetDateStr 삭제 예정
        targetDatesStr = req["targetDateStr"]
        # targetDateStr에서 targetDatesStr로 마이그레이션
        if req["targetDatesStr"] != None:
            targetDatesStr = req["targetDatesStr"]
        targetRoom = req["targetRoom"]
        if checkActivationKey(req) == False:
            res = {"message": "Invalid Access Key", "data": req}
            return jsonify(res), 401
        log.info(f"targetDatesStr: {targetDatesStr}, targetRoom: {targetRoom}")
        syncManager.SyncNaver(driver, targetDatesStr, targetRoom)
        res = {"message": "Sync Naver Reservation", "data": req}
        httpStatus = 200
    except Exception as e:
        log.error("네이버 예약 정보 변경 실패", e)
        res = {"message": "Sync Naver Reservation Failed"}
        httpStatus = 500

    driver.close()
    return jsonify(res), httpStatus


@app.route("/sync/out", methods=["POST"])
def get_naver_reservation():
    driver = chromeDriver.ChromeDriver()
    res: dict
    httpStatus: int

    try:
        req = request.get_json()
        if checkActivationKey(req) == False:
            res = {"message": "Invalid Access Key", "data": {}}
            return jsonify(res), 401
        monthSize = req["monthSize"]
        log.info(f"monthSize: {monthSize}")
        if monthSize == None:
            monthSize = 1
        notCanceledBookingList, allBookingList = syncManager.getNaverReservation(
            driver, monthSize
        )
        res = {
            "message": "Sync Naver Reservation",
            "notCanceledBookingList": notCanceledBookingList,
            "allBookingList": allBookingList,
        }
        httpStatus = 200
        log.info(
            f"네이버 예약 정보 가져오기 성공(notCanceledBookingList): {notCanceledBookingList}"
        )
    except Exception as e:
        log.error("네이버 예약 정보 가져오기 실패", e)
        res = {"message": "Get Naver Reservation Failed"}
        httpStatus = 500

    driver.close()
    return jsonify(res), httpStatus


def checkActivationKey(req):
    if "activationKey" not in req:
        return False
    if activationKey != req["activationKey"]:
        return False
    return True


if __name__ == "__main__":
    app.run("0.0.0.0", port=5000, debug=True)
