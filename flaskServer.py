from flask import Flask, jsonify, request
import syncManager
import chromeDriver

from dotenv import load_dotenv
import os

load_dotenv()

activationKey = os.environ.get("ACTIVATION_KEY")

app = Flask(__name__)


@app.route("/", methods=["GET"])
def hello_world():
    return "Hello, World!"


@app.route("/", methods=["POST"])
def hello_world_post():
    req = request.get_json()
    res = {"message": "Hello, World!", "data": req}
    return jsonify(res), 200


@app.route("/sync/in", methods=["POST"])
def sync_naver_reservation():
    driver = chromeDriver.ChromeDriver()
    res: dict
    httpStatus: int

    try:
        req = request.get_json()
        # TODO : 마이그레이션 이후 targetDatesStr 삭제 예정
        targetDatesStr = req["targetDateStr"]
        # targetDateStr에서 targetDatesStr로 마이그레이션
        if req["targetDatesStr"] != None:
            targetDatesStr = req["targetDatesStr"]
        targetRoom = req["targetRoom"]
        if checkActivationKey(req) == False:
            res = {"message": "Invalid Access Key", "data": req}
            return jsonify(res), 401
        print(targetDatesStr, targetRoom)
        syncManager.SyncNaver(targetDatesStr, targetRoom)
        res = {"message": "Sync Naver Reservation", "data": req}
        httpStatus = 200
    except Exception as e:
        res = {"message": "Sync Naver Reservation Failed", "error": e}
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
        print("monthSize: ", monthSize)
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
    except Exception as e:
        res = {"message": "Get Naver Reservation Failed", "error": e}
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
