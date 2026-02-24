# -*- coding:utf-8 -*-

from flask import Flask, request
from flask_restx import Api, Resource, fields, Namespace
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
app.config["RESTX_MASK_SWAGGER"] = False

api = Api(
    app,
    version='1.0',
    title='Yeoyeo Scraper API',
    description='네이버 예약 관리 시스템 자동화 API',
    doc='/docs'
)

ns = api.namespace('', description='예약 관리 API')
sync_ns = api.namespace('sync', description='예약 동기화 API')


test_request_model = api.model('TestRequest', {
    'data': fields.Raw(description='테스트 데이터')
})

test_response_model = api.model('TestResponse', {
    'message': fields.String(description='응답 메시지'),
    'data': fields.Raw(description='요청 데이터')
})

@ns.route('/')
class HealthCheck(Resource):
    def get(self):
        """헬스체크"""
        log.info("Hello, World!")
        return "Hello, World!"
    
    @ns.expect(test_request_model, validate=False)
    @ns.marshal_with(test_response_model)
    def post(self):
        """테스트용 엔드포인트"""
        req = request.get_json()
        log.info("테스트 - Hello, World!")
        return {"message": "Hello, World!", "data": req}, 200


sync_in_request_model = api.model('SyncInRequest', {
    'activationKey': fields.String(required=True, description='인증 키'),
    'targetDatesStr': fields.String(required=True, description='날짜 문자열 (예: "2024-09-02,2024-09-03")', example='2024-09-02,2024-09-03'),
    'targetRoom': fields.String(required=True, description='방 타입 ("Yeoyu" 또는 "Yeohang")', enum=['Yeoyu', 'Yeohang'])
})

sync_in_success_response_model = api.model('SyncInSuccessResponse', {
    'message': fields.String(description='응답 메시지'),
    'successDates': fields.List(fields.String, description='성공한 날짜 리스트'),
    'data': fields.Raw(description='요청 데이터')
})

sync_in_error_response_model = api.model('SyncInErrorResponse', {
    'message': fields.String(description='에러 메시지'),
    'data': fields.Raw(description='요청 데이터', required=False)
})

@sync_ns.route('/in')
class SyncNaverReservation(Resource):
    @sync_ns.expect(sync_in_request_model, validate=True)
    @sync_ns.response(200, 'Success', sync_in_success_response_model)
    @sync_ns.response(401, 'Unauthorized', sync_in_error_response_model)
    @sync_ns.response(500, 'Internal Server Error', sync_in_error_response_model)
    def post(self):
        """네이버 예약 상태 변경 (예약 가능/불가능 토글)"""
        driver = chromeDriver.ChromeDriver()
        res: dict
        httpStatus: int

        try:
            req = request.get_json()
            if req["targetDatesStr"] != None:
                targetDatesStr = req["targetDatesStr"]
            targetRoom = req["targetRoom"]
            if checkActivationKey(req) == False:
                res = {"message": "Invalid Access Key", "data": req}
                httpStatus = 401
            else:
                log.info(f"targetDatesStr: {targetDatesStr}, targetRoom: {targetRoom}")
                successDates = syncManager.SyncNaver(driver, targetDatesStr, targetRoom)
                res = {"message": "Sync Naver Reservation", "successDates": successDates, "data": req}
                httpStatus = 200
        except Exception as e:
            log.error("네이버 예약 정보 변경 실패", e)
            res = {"message": "Sync Naver Reservation Failed"}
            httpStatus = 500
        finally:
            driver.close()
        
        return res, httpStatus


booking_model = api.model('Booking', {
    'name': fields.String(description='예약자명'),
    'phone': fields.String(description='전화번호'),
    'reservationNumber': fields.String(description='예약번호'),
    'startDate': fields.String(description='체크인 날짜 (YYYYMMDD)'),
    'endDate': fields.String(description='체크아웃 날짜 (YYYYMMDD)'),
    'room': fields.String(description='객실명'),
    'option': fields.String(description='예약 옵션', allow_null=True),
    'comment': fields.String(description='요청사항', allow_null=True),
    'price': fields.String(description='총 가격'),
    'status': fields.String(description='예약 상태 (예: "예약확정", "취소")')
})

sync_out_request_model = api.model('SyncOutRequest', {
    'activationKey': fields.String(required=True, description='인증 키'),
    'monthSize': fields.Integer(required=False, default=1, description='조회할 월 개수')
})

sync_out_success_response_model = api.model('SyncOutSuccessResponse', {
    'message': fields.String(description='응답 메시지'),
    'notCanceledBookingList': fields.List(fields.Nested(booking_model), description='취소 미포함 예약 리스트'),
    'allBookingList': fields.List(fields.Nested(booking_model), description='전체 예약 리스트')
})

sync_out_error_response_model = api.model('SyncOutErrorResponse', {
    'message': fields.String(description='에러 메시지'),
    'data': fields.Raw(description='요청 데이터', required=False)
})

@sync_ns.route('/out')
class GetNaverReservation(Resource):
    @sync_ns.expect(sync_out_request_model, validate=True)
    @sync_ns.response(200, 'Success', sync_out_success_response_model)
    @sync_ns.response(401, 'Unauthorized', sync_out_error_response_model)
    @sync_ns.response(500, 'Internal Server Error', sync_out_error_response_model)
    def post(self):
        """네이버 예약 정보 조회 (N개월치 예약 내역)"""
        driver = chromeDriver.ChromeDriver()
        res: dict
        httpStatus: int

        try:
            req = request.get_json()
            if checkActivationKey(req) == False:
                res = {"message": "Invalid Access Key", "data": {}}
                httpStatus = 401
            else:
                monthSize = req.get("monthSize", 1)
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
        finally:
            driver.close()
        
        return res, httpStatus


def checkActivationKey(req):
    if "activationKey" not in req:
        return False
    if activationKey != req["activationKey"]:
        return False
    return True


if __name__ == "__main__":
    app.run("0.0.0.0", port=5000, debug=True)
