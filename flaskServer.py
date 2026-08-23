# -*- coding:utf-8 -*-

from flask import Flask, request, send_from_directory, render_template
from flask_restx import Api, Resource
from api_models import register_api_models
from auth_utils import is_valid_activation_key, is_valid_activation_request
from diagnostic_service import DiagnosticService
import syncManager
import simpleManagementController
import chromeDriver
from chromeDriver import (
    create_browser,
    BrowserStartupError,
    FDExhaustedError,
    ensure_chromedriver_patched,
)

from dotenv import load_dotenv
import datetime
import os
import logging
import mimetypes
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
models = register_api_models(api)

@ns.route('/')
class HealthCheck(Resource):
    def get(self):
        """헬스체크"""
        log.info("Hello, World!")
        return "Hello, World!"
    
    @ns.expect(models.test_request, validate=False)
    @ns.marshal_with(models.test_response)
    def post(self):
        """테스트용 엔드포인트"""
        req = request.get_json()
        log.info("테스트 - Hello, World!")
        return {"message": "Hello, World!", "data": req}, 200


@app.get("/debug/view")
def debug_diagnostic_view():
    return render_template("debug_diagnostics.html")


@sync_ns.route('/in')
class SyncNaverReservation(Resource):
    @sync_ns.expect(models.sync_in_request, validate=True)
    @sync_ns.response(200, 'Success', models.sync_in_success_response)
    @sync_ns.response(401, 'Unauthorized', models.sync_in_error_response)
    @sync_ns.response(500, 'Internal Server Error', models.sync_in_error_response)
    @sync_ns.response(503, 'Service Unavailable', models.sync_in_error_response)
    def post(self):
        """네이버 예약 상태 변경 (예약 가능/불가능 토글)"""
        req = request.get_json()
        
        if checkActivationKey(req) == False:
            return {"message": "Invalid Access Key", "data": req}, 401
        
        targetDatesStr = req.get("targetDatesStr")
        targetRoom = req["targetRoom"]
        
        try:
            # Use context manager for guaranteed cleanup
            with create_browser() as driver:
                log.info(f"targetDatesStr: {targetDatesStr}, targetRoom: {targetRoom}")
                successDates = syncManager.SyncNaver(driver, targetDatesStr, targetRoom)
                return {
                    "message": "Sync Naver Reservation",
                    "successDates": successDates,
                    "data": req
                }, 200
        except FDExhaustedError as e:
            log.error("FD exhausted - cannot start browser", e)
            return {
                "message": f"Server resource exhausted: {str(e)}",
                "data": req
            }, 503
        except TimeoutError as e:
            log.error("Browser slot timeout", e)
            return {
                "message": f"Server busy: {str(e)}",
                "data": req
            }, 503
        except BrowserStartupError as e:
            log.error("Browser startup failed", e)
            return {
                "message": f"Browser startup failed: {str(e)}",
                "data": req
            }, 500
        except Exception as e:
            log.error("네이버 예약 정보 변경 실패", e)
            return {"message": "Sync Naver Reservation Failed"}, 500


@sync_ns.route('/out')
class GetNaverReservation(Resource):
    @sync_ns.expect(models.sync_out_request, validate=True)
    @sync_ns.response(200, 'Success', models.sync_out_success_response)
    @sync_ns.response(401, 'Unauthorized', models.sync_out_error_response)
    @sync_ns.response(500, 'Internal Server Error', models.sync_out_error_response)
    @sync_ns.response(503, 'Service Unavailable', models.sync_out_error_response)
    def post(self):
        """네이버 예약 정보 조회 (N개월치 예약 내역)"""
        req = request.get_json()
        
        if checkActivationKey(req) == False:
            return {"message": "Invalid Access Key", "data": {}}, 401
        
        monthSize = req.get("monthSize", 1)
        if monthSize is None:
            monthSize = 1
        
        try:
            # Use context manager for guaranteed cleanup
            with create_browser() as driver:
                log.info(f"monthSize: {monthSize}")
                notCanceledBookingList, allBookingList = syncManager.getNaverReservation(
                    driver, monthSize
                )
                log.info(
                    f"네이버 예약 정보 가져오기 성공(notCanceledBookingList): {notCanceledBookingList}"
                )
                return {
                    "message": "Sync Naver Reservation",
                    "notCanceledBookingList": notCanceledBookingList,
                    "allBookingList": allBookingList,
                }, 200
        except FDExhaustedError as e:
            log.error("FD exhausted - cannot start browser", e)
            return {
                "message": f"Server resource exhausted: {str(e)}"
            }, 503
        except TimeoutError as e:
            log.error("Browser slot timeout", e)
            return {
                "message": f"Server busy: {str(e)}"
            }, 503
        except BrowserStartupError as e:
            log.error("Browser startup failed", e)
            return {
                "message": f"Browser startup failed: {str(e)}"
            }, 500
        except Exception as e:
            log.error("네이버 예약 정보 가져오기 실패", e)
            return {"message": f"Get Naver Reservation Failed: {str(e)}"}, 500


@debug_ns.route('/diagnostics')
class DiagnosticSessionList(Resource):
    @debug_ns.response(200, 'Success', models.diagnostic_list_response)
    @debug_ns.response(401, 'Unauthorized', models.diagnostic_error_response)
    def get(self):
        """DOM 진단 세션 목록 조회"""
        if not checkActivationKeyFromRequest():
            return {"message": "Invalid Access Key"}, 401

        sessions = listDiagnosticSessions(getRequestActivationKey())
        return {"message": "Diagnostic Sessions", "sessions": sessions}, 200

    @debug_ns.response(200, 'Success', models.diagnostic_bulk_delete_response)
    @debug_ns.response(401, 'Unauthorized', models.diagnostic_error_response)
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


@debug_ns.route('/reservation-toggle-state')
class ReservationToggleState(Resource):
    @debug_ns.expect(models.toggle_state_request, validate=True)
    @debug_ns.response(200, 'Success', models.toggle_state_response)
    @debug_ns.response(400, 'Bad Request', models.toggle_state_error)
    @debug_ns.response(401, 'Unauthorized', models.toggle_state_error)
    @debug_ns.response(500, 'Internal Server Error', models.toggle_state_error)
    @debug_ns.response(503, 'Service Unavailable', models.toggle_state_error)
    def post(self):
        """날짜별 객실 예약 수량과 판매 스위치를 읽기 전용으로 조회"""
        req = request.get_json()
        if not checkActivationKey(req):
            return {"message": "Invalid Access Key"}, 401

        try:
            targetDate = datetime.datetime.strptime(
                req["targetDate"], "%Y-%m-%d"
            ).date()
        except (TypeError, ValueError):
            return {
                "message": "Invalid targetDate format",
                "code": "INVALID_TARGET_DATE",
            }, 400

        try:
            with create_browser() as driver:
                results = syncManager.inspectReservationToggleState(driver, targetDate)
            return {
                "message": "Reservation toggle state inspected",
                "targetDate": str(targetDate),
                "results": results,
            }, 200
        except simpleManagementController.ToggleStateInspectionError as e:
            log.error(f"판매 상태 조회 실패: {e.code}", e)
            expectedInspectionErrors = {
                "DATE_NOT_AVAILABLE_IN_NAVER_CALENDAR",
                "TARGET_CELL_NOT_FOUND",
                "TARGET_TOGGLE_NOT_FOUND",
            }
            if e.code in expectedInspectionErrors:
                return {
                    "message": "Reservation toggle state inspected with errors",
                    "targetDate": str(targetDate),
                    "results": [
                        {
                            "room": room,
                            "date": str(targetDate),
                            "reservationCount": None,
                            "status": "error",
                            "errorDescription": e.code,
                        }
                        for room in simpleManagementController.SimpleManagementController.ROOM_NAMES
                    ],
                }, 200
            return {
                "message": "Reservation toggle state inspection failed",
                "code": e.code,
            }, 500
        except (FDExhaustedError, TimeoutError) as e:
            log.error("판매 상태 조회를 위한 브라우저 리소스 확보 실패", e)
            return {"message": "Service unavailable"}, 503
        except BrowserStartupError as e:
            log.error("판매 상태 조회 브라우저 기동 실패", e)
            return {"message": "Browser startup failed"}, 500
        except Exception as e:
            log.error("판매 상태 조회 실패", e)
            return {"message": "Reservation toggle state inspection failed"}, 500


@debug_ns.route('/diagnostics/<string:session_id>/<path:filename>')
class DiagnosticFile(Resource):
    @debug_ns.response(401, 'Unauthorized', models.diagnostic_error_response)
    @debug_ns.response(404, 'Not Found', models.diagnostic_error_response)
    def get(self, session_id: str, filename: str):
        """DOM 진단 파일 조회"""
        if not checkActivationKeyFromRequest():
            return {"message": "Invalid Access Key"}, 401

        diagnosticService = DiagnosticService(domDiagnosticDir)
        sessionDir = diagnosticService.resolve_session_dir(session_id)
        targetPath = diagnosticService.resolve_file(session_id, filename)
        if sessionDir is None or not os.path.isdir(sessionDir):
            return {"message": "Diagnostic Session Not Found"}, 404
        if targetPath is None or not os.path.isfile(targetPath):
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
    @debug_ns.response(200, 'Success', models.diagnostic_delete_response)
    @debug_ns.response(401, 'Unauthorized', models.diagnostic_error_response)
    @debug_ns.response(404, 'Not Found', models.diagnostic_error_response)
    def delete(self, session_id: str):
        """DOM 진단 세션 삭제"""
        if not checkActivationKeyFromRequest():
            return {"message": "Invalid Access Key"}, 401

        if not DiagnosticService(domDiagnosticDir).delete_session(session_id):
            return {"message": "Diagnostic Session Not Found"}, 404
        return {"message": "Diagnostic Session Deleted", "sessionId": session_id}, 200


def checkActivationKey(req):
    return is_valid_activation_request(req, activationKey)


def checkActivationKeyFromRequest():
    return checkActivationKeyValue(getRequestActivationKey())


def getRequestActivationKey():
    return request.headers.get("X-Activation-Key") or request.args.get("activationKey")


def checkActivationKeyValue(value):
    return is_valid_activation_key(value, activationKey)


def loadDiagnosticJson(filePath: str):
    return DiagnosticService.load_json(filePath)


def buildDiagnosticStatus(sessionDir: str):
    return DiagnosticService(domDiagnosticDir).build_status(sessionDir)


def buildDiagnosticSummary(sessionDir: str):
    return DiagnosticService(domDiagnosticDir).build_summary(sessionDir)


def pickDefaultDiagnosticFile(files: list, statusCode: str):
    return DiagnosticService.pick_default_file(files, statusCode)


def listDiagnosticSessions(requestActivationKey: str):
    if not checkActivationKeyValue(requestActivationKey):
        return []
    return DiagnosticService(domDiagnosticDir).list_sessions()


def deleteDiagnosticSessions(mode: str):
    return DiagnosticService(domDiagnosticDir).delete_sessions(mode)


if __name__ == "__main__":
    debugMode = os.environ.get("DEBUG_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    
    # Pre-patch chromedriver at startup to avoid race conditions
    logger.info("Pre-patching chromedriver at server startup...")
    if ensure_chromedriver_patched():
        logger.info("Chromedriver pre-patching completed successfully")
    else:
        logger.warning("Chromedriver pre-patching failed - will attempt patching on first request")
    
    app.run("0.0.0.0", port=5000, debug=debugMode, use_reloader=debugMode)
