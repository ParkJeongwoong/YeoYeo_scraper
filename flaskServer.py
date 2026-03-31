# -*- coding:utf-8 -*-

from flask import Flask, request, send_from_directory, render_template
from flask_restx import Api, Resource, fields, Namespace
import syncManager
import chromeDriver

from dotenv import load_dotenv
import datetime
import json
import os
import logging
import mimetypes
import shutil
import log

load_dotenv()

activationKey = os.environ.get("ACTIVATION_KEY")
domDiagnosticDir = os.environ.get("DOM_DIAGNOSTIC_DIR", "logs/dom_diagnostics")

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
debug_ns = api.namespace('debug', description='진단 파일 조회 API')


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


@app.get("/debug/view")
def debug_diagnostic_view():
    return render_template("debug_diagnostics.html")


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
        driver = None
        res: dict
        httpStatus: int

        try:
            req = request.get_json()
            if checkActivationKey(req) == False:
                res = {"message": "Invalid Access Key", "data": req}
                httpStatus = 401
            else:
                targetDatesStr = req.get("targetDatesStr")
                targetRoom = req["targetRoom"]
                driver = chromeDriver.ChromeDriver()
                log.info(f"targetDatesStr: {targetDatesStr}, targetRoom: {targetRoom}")
                successDates = syncManager.SyncNaver(driver, targetDatesStr, targetRoom)
                res = {"message": "Sync Naver Reservation", "successDates": successDates, "data": req}
                httpStatus = 200
        except Exception as e:
            log.error("네이버 예약 정보 변경 실패", e)
            res = {"message": "Sync Naver Reservation Failed"}
            httpStatus = 500
        finally:
            if driver is not None:
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

diagnostic_file_model = api.model('DiagnosticFile', {
    'name': fields.String(description='파일명'),
    'contentType': fields.String(description='MIME 타입'),
    'size': fields.Integer(description='파일 크기(Byte)'),
    'url': fields.String(description='조회 URL')
})

diagnostic_status_model = api.model('DiagnosticStatus', {
    'code': fields.String(description='상태 코드'),
    'label': fields.String(description='상태 라벨'),
    'reason': fields.String(description='상태 판단 근거'),
    'suspicious': fields.Boolean(description='문제 의심 여부')
})

diagnostic_session_model = api.model('DiagnosticSession', {
    'sessionId': fields.String(description='진단 세션 ID'),
    'files': fields.List(fields.Nested(diagnostic_file_model), description='세션 파일 목록'),
    'status': fields.Nested(diagnostic_status_model, description='세션 상태 요약'),
    'updatedAt': fields.String(description='세션 최종 수정 시각'),
    'defaultFileUrl': fields.String(description='기본 미리보기 파일 URL'),
    'currentUrl': fields.String(description='대표 URL'),
    'title': fields.String(description='대표 페이지 제목'),
    'userAgent': fields.String(description='대표 User-Agent')
})

diagnostic_list_response_model = api.model('DiagnosticListResponse', {
    'message': fields.String(description='응답 메시지'),
    'sessions': fields.List(fields.Nested(diagnostic_session_model), description='진단 세션 목록')
})

diagnostic_error_response_model = api.model('DiagnosticErrorResponse', {
    'message': fields.String(description='에러 메시지')
})

diagnostic_delete_response_model = api.model('DiagnosticDeleteResponse', {
    'message': fields.String(description='응답 메시지'),
    'sessionId': fields.String(description='삭제된 세션 ID')
})

diagnostic_bulk_delete_response_model = api.model('DiagnosticBulkDeleteResponse', {
    'message': fields.String(description='응답 메시지'),
    'deletedSessionIds': fields.List(fields.String, description='삭제된 세션 ID 목록'),
    'mode': fields.String(description='삭제 모드')
})

@sync_ns.route('/out')
class GetNaverReservation(Resource):
    @sync_ns.expect(sync_out_request_model, validate=True)
    @sync_ns.response(200, 'Success', sync_out_success_response_model)
    @sync_ns.response(401, 'Unauthorized', sync_out_error_response_model)
    @sync_ns.response(500, 'Internal Server Error', sync_out_error_response_model)
    def post(self):
        """네이버 예약 정보 조회 (N개월치 예약 내역)"""
        driver = None
        res: dict
        httpStatus: int

        try:
            req = request.get_json()
            if checkActivationKey(req) == False:
                res = {"message": "Invalid Access Key", "data": {}}
                httpStatus = 401
            else:
                driver = chromeDriver.ChromeDriver()
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
            res = {"message": f"Get Naver Reservation Failed: {str(e)}"}
            httpStatus = 500
        finally:
            if driver is not None:
                driver.close()
        
        return res, httpStatus


@debug_ns.route('/diagnostics')
class DiagnosticSessionList(Resource):
    @debug_ns.response(200, 'Success', diagnostic_list_response_model)
    @debug_ns.response(401, 'Unauthorized', diagnostic_error_response_model)
    def get(self):
        """DOM 진단 세션 목록 조회"""
        if not checkActivationKeyFromRequest():
            return {"message": "Invalid Access Key"}, 401

        sessions = listDiagnosticSessions(getRequestActivationKey())
        return {"message": "Diagnostic Sessions", "sessions": sessions}, 200

    @debug_ns.response(200, 'Success', diagnostic_bulk_delete_response_model)
    @debug_ns.response(401, 'Unauthorized', diagnostic_error_response_model)
    def delete(self):
        """DOM 진단 세션 일괄 삭제"""
        if not checkActivationKeyFromRequest():
            return {"message": "Invalid Access Key"}, 401

        mode = request.args.get("mode", "all")
        deletedSessionIds = deleteDiagnosticSessions(mode)
        return {
            "message": "Diagnostic Sessions Deleted",
            "deletedSessionIds": deletedSessionIds,
            "mode": mode,
        }, 200


@debug_ns.route('/diagnostics/<string:session_id>/<path:filename>')
class DiagnosticFile(Resource):
    @debug_ns.response(401, 'Unauthorized', diagnostic_error_response_model)
    @debug_ns.response(404, 'Not Found', diagnostic_error_response_model)
    def get(self, session_id: str, filename: str):
        """DOM 진단 파일 조회"""
        if not checkActivationKeyFromRequest():
            return {"message": "Invalid Access Key"}, 401

        sessionDir = os.path.abspath(os.path.join(domDiagnosticDir, session_id))
        baseDir = os.path.abspath(domDiagnosticDir)
        targetPath = os.path.abspath(os.path.join(sessionDir, filename))

        if not os.path.isdir(sessionDir):
            return {"message": "Diagnostic Session Not Found"}, 404
        if os.path.commonpath([baseDir, targetPath]) != baseDir or not os.path.isfile(targetPath):
            return {"message": "Diagnostic File Not Found"}, 404

        contentType = mimetypes.guess_type(targetPath)[0]
        return send_from_directory(
            sessionDir,
            filename,
            mimetype=contentType,
            as_attachment=False,
        )


@debug_ns.route('/diagnostics/<string:session_id>')
class DiagnosticSession(Resource):
    @debug_ns.response(200, 'Success', diagnostic_delete_response_model)
    @debug_ns.response(401, 'Unauthorized', diagnostic_error_response_model)
    @debug_ns.response(404, 'Not Found', diagnostic_error_response_model)
    def delete(self, session_id: str):
        """DOM 진단 세션 삭제"""
        if not checkActivationKeyFromRequest():
            return {"message": "Invalid Access Key"}, 401

        sessionDir = os.path.abspath(os.path.join(domDiagnosticDir, session_id))
        baseDir = os.path.abspath(domDiagnosticDir)
        if os.path.commonpath([baseDir, sessionDir]) != baseDir or not os.path.isdir(sessionDir):
            return {"message": "Diagnostic Session Not Found"}, 404

        shutil.rmtree(sessionDir, ignore_errors=True)
        return {"message": "Diagnostic Session Deleted", "sessionId": session_id}, 200


def checkActivationKey(req):
    if "activationKey" not in req:
        return False
    if activationKey != req["activationKey"]:
        return False
    return True


def checkActivationKeyFromRequest():
    return checkActivationKeyValue(getRequestActivationKey())


def getRequestActivationKey():
    return request.headers.get("X-Activation-Key") or request.args.get("activationKey")


def checkActivationKeyValue(value):
    if value is None:
        return False
    return activationKey == value


def loadDiagnosticJson(filePath: str):
    try:
        with open(filePath, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return None


def buildDiagnosticStatus(sessionDir: str):
    jsonPayloads = []
    fileNames = []
    for filename in os.listdir(sessionDir):
        filePath = os.path.join(sessionDir, filename)
        if not os.path.isfile(filePath):
            continue
        fileNames.append(filename)
        if filename.endswith(".json"):
            payload = loadDiagnosticJson(filePath)
            if payload is not None:
                jsonPayloads.append((filename, payload))

    protectedKeywords = []
    emptyDomDetected = False
    emptySnapshotDetected = False
    for filename, payload in jsonPayloads:
        detectedKeywords = payload.get("detectedKeywords") or []
        if detectedKeywords:
            protectedKeywords.extend(detectedKeywords)

        selectorCounts = payload.get("selectorCounts") or {}
        bookingCards = selectorCounts.get("bookingCards", 0)
        calendarDateInfo = selectorCounts.get("calendarDateInfo", 0)
        calendarNextButton = selectorCounts.get("calendarNextButton", 0)
        if bookingCards == 0 and calendarDateInfo == 0 and calendarNextButton == 0:
            emptyDomDetected = True
        if filename.endswith("_empty.json"):
            emptySnapshotDetected = True

    protectedKeywords = sorted(set(protectedKeywords))
    if protectedKeywords:
        return {
            "code": "protected",
            "label": "보호/인증 의심",
            "reason": ", ".join(protectedKeywords[:5]),
            "suspicious": True,
        }
    if emptyDomDetected:
        return {
            "code": "empty_dom",
            "label": "빈 DOM 의심",
            "reason": "예약 카드와 캘린더 셀렉터가 모두 비어 있습니다.",
            "suspicious": True,
        }
    if emptySnapshotDetected:
        return {
            "code": "empty_result",
            "label": "빈 결과/렌더 지연 의심",
            "reason": "예약 목록 추출 결과가 비어 있습니다.",
            "suspicious": True,
        }
    return {
        "code": "ok",
        "label": "정상 후보",
        "reason": "특이한 진단 신호가 없습니다.",
        "suspicious": False,
    }


def buildDiagnosticSummary(sessionDir: str):
    preferredJsonFiles = [
        "booking_list_month_1_empty.json",
        "booking_list_loaded.json",
        "after_login.json",
    ]

    for preferredFile in preferredJsonFiles:
        payload = loadDiagnosticJson(os.path.join(sessionDir, preferredFile))
        if payload is not None:
            return {
                "currentUrl": payload.get("currentUrl"),
                "title": payload.get("title"),
                "userAgent": payload.get("userAgent"),
            }

    for filename in sorted(os.listdir(sessionDir)):
        if not filename.endswith(".json"):
            continue
        payload = loadDiagnosticJson(os.path.join(sessionDir, filename))
        if payload is None:
            continue
        return {
            "currentUrl": payload.get("currentUrl"),
            "title": payload.get("title"),
            "userAgent": payload.get("userAgent"),
        }

    return {
        "currentUrl": None,
        "title": None,
        "userAgent": None,
    }


def pickDefaultDiagnosticFile(files: list, statusCode: str):
    if len(files) == 0:
        return None

    if statusCode != "ok":
        preferredStageKeywords = [
            "_next_error",
            "_next_missing",
            "_timeout",
            "_empty",
            "booking_list_loaded",
            "after_login",
        ]
        preferredExtensions = [".png", ".html", ".json"]
        for keyword in preferredStageKeywords:
            for extension in preferredExtensions:
                for file in files:
                    if keyword in file["name"] and file["name"].endswith(extension):
                        return file["url"]

    for extension in [".png", ".html", ".json"]:
        for file in files:
            if file["name"].endswith(extension):
                return file["url"]
    return files[0]["url"]


def listDiagnosticSessions(requestActivationKey: str):
    sessions = []
    if not checkActivationKeyValue(requestActivationKey):
        return sessions
    if not os.path.isdir(domDiagnosticDir):
        return sessions

    for sessionId in os.listdir(domDiagnosticDir):
        sessionDir = os.path.join(domDiagnosticDir, sessionId)
        if not os.path.isdir(sessionDir):
            continue
        files = []
        latestTimestamp = 0.0
        for filename in sorted(os.listdir(sessionDir)):
            filePath = os.path.join(sessionDir, filename)
            if not os.path.isfile(filePath):
                continue
            latestTimestamp = max(latestTimestamp, os.path.getmtime(filePath))
            contentType = mimetypes.guess_type(filePath)[0] or "application/octet-stream"
            files.append({
                "name": filename,
                "contentType": contentType,
                "size": os.path.getsize(filePath),
                "url": f"/debug/diagnostics/{sessionId}/{filename}",
            })
        status = buildDiagnosticStatus(sessionDir)
        summary = buildDiagnosticSummary(sessionDir)
        sessions.append({
            "sessionId": sessionId,
            "files": files,
            "status": status,
            "updatedAt": datetime.datetime.fromtimestamp(
                latestTimestamp or os.path.getmtime(sessionDir),
                tz=datetime.timezone.utc,
            ).isoformat(),
            "defaultFileUrl": pickDefaultDiagnosticFile(files, status["code"]),
            "currentUrl": summary["currentUrl"],
            "title": summary["title"],
            "userAgent": summary["userAgent"],
        })
    sessions.sort(
        key=lambda session: (session["updatedAt"], session["sessionId"]),
        reverse=True,
    )
    return sessions


def deleteDiagnosticSessions(mode: str):
    if not os.path.isdir(domDiagnosticDir):
        return []

    deletedSessionIds = []
    sessions = listDiagnosticSessions(activationKey)
    suspiciousIds = {
        session["sessionId"]
        for session in sessions
        if session.get("status", {}).get("suspicious")
    }

    for sessionId in os.listdir(domDiagnosticDir):
        sessionDir = os.path.join(domDiagnosticDir, sessionId)
        if not os.path.isdir(sessionDir):
            continue
        if mode == "suspicious" and sessionId not in suspiciousIds:
            continue
        if mode not in {"all", "suspicious"}:
            continue
        shutil.rmtree(sessionDir, ignore_errors=True)
        deletedSessionIds.append(sessionId)

    deletedSessionIds.sort(reverse=True)
    return deletedSessionIds


if __name__ == "__main__":
    debugMode = os.environ.get("DEBUG_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    app.run("0.0.0.0", port=5000, debug=debugMode, use_reloader=debugMode)
