from dataclasses import dataclass

from flask_restx import Api, fields


@dataclass(frozen=True)
class ApiModels:
    test_request: object
    test_response: object
    sync_in_request: object
    sync_in_success_response: object
    sync_in_error_response: object
    booking: object
    sync_out_request: object
    sync_out_success_response: object
    sync_out_error_response: object
    diagnostic_file: object
    diagnostic_status: object
    diagnostic_session: object
    diagnostic_list_response: object
    diagnostic_error_response: object
    toggle_state_request: object
    toggle_state_result: object
    toggle_state_response: object
    toggle_state_error: object
    diagnostic_delete_response: object
    diagnostic_bulk_delete_response: object


def register_api_models(api: Api) -> ApiModels:
    """Register all Swagger request/response contracts in one place."""
    test_request = api.model("TestRequest", {
        "data": fields.Raw(description="테스트 데이터"),
    })
    test_response = api.model("TestResponse", {
        "message": fields.String(description="응답 메시지"),
        "data": fields.Raw(description="요청 데이터"),
    })
    sync_in_request = api.model("SyncInRequest", {
        "activationKey": fields.String(required=True, description="인증 키"),
        "targetDatesStr": fields.String(
            required=True,
            description='날짜 문자열 (예: "2024-09-02,2024-09-03")',
            example="2024-09-02,2024-09-03",
        ),
        "targetRoom": fields.String(
            required=True, description='방 타입 ("Yeoyu" 또는 "Yeohang")',
            enum=["Yeoyu", "Yeohang"],
        ),
        "desiredState": fields.String(
            required=False,
            description="목표 외부 판매 상태. 생략 시 레거시 토글 방식 사용",
            enum=["available", "externallyBlocked"],
        ),
    })
    sync_in_result = api.model("SyncInResult", {
        "date": fields.String(description="대상 날짜"),
        "result": fields.String(
            description="날짜별 처리 결과",
            enum=["SUCCESS", "ALREADY_APPLIED", "DEFERRED", "FAILED"],
        ),
        "reason": fields.String(description="실패 또는 지연 사유", allow_null=True),
        "retryable": fields.Boolean(description="재시도 가능 여부"),
        "durationMs": fields.Integer(description="처리 소요 시간(ms)"),
    })
    sync_in_success_response = api.model("SyncInSuccessResponse", {
        "message": fields.String(description="응답 메시지"),
        "status": fields.String(
            description="전체 처리 상태",
            enum=["SUCCESS", "PARTIAL_SUCCESS", "FAILED"],
        ),
        "results": fields.List(fields.Nested(sync_in_result), description="날짜별 결과"),
        "successDates": fields.List(fields.String, description="성공한 날짜 리스트"),
        "data": fields.Raw(description="요청 데이터"),
    })
    sync_in_error_response = api.model("SyncInErrorResponse", {
        "message": fields.String(description="에러 메시지"),
        "data": fields.Raw(description="요청 데이터", required=False),
    })
    booking = api.model("Booking", {
        "name": fields.String(description="예약자명"),
        "phone": fields.String(description="전화번호"),
        "reservationNumber": fields.String(description="예약번호"),
        "startDate": fields.String(description="체크인 날짜 (YYYYMMDD)"),
        "endDate": fields.String(description="체크아웃 날짜 (YYYYMMDD)"),
        "room": fields.String(description="객실명"),
        "option": fields.String(description="예약 옵션", allow_null=True),
        "comment": fields.String(description="요청사항", allow_null=True),
        "price": fields.String(description="총 가격"),
        "status": fields.String(description='예약 상태 (예: "예약확정", "취소")'),
    })
    sync_out_request = api.model("SyncOutRequest", {
        "activationKey": fields.String(required=True, description="인증 키"),
        "monthSize": fields.Integer(required=False, default=1, description="조회할 월 개수"),
    })
    sync_out_success_response = api.model("SyncOutSuccessResponse", {
        "message": fields.String(description="응답 메시지"),
        "notCanceledBookingList": fields.List(
            fields.Nested(booking), description="취소 미포함 예약 리스트"
        ),
        "allBookingList": fields.List(fields.Nested(booking), description="전체 예약 리스트"),
    })
    sync_out_error_response = api.model("SyncOutErrorResponse", {
        "message": fields.String(description="에러 메시지"),
        "data": fields.Raw(description="요청 데이터", required=False),
    })
    diagnostic_file = api.model("DiagnosticFile", {
        "name": fields.String(description="파일명"),
        "contentType": fields.String(description="MIME 타입"),
        "size": fields.Integer(description="파일 크기(Byte)"),
        "url": fields.String(description="조회 URL"),
    })
    diagnostic_status = api.model("DiagnosticStatus", {
        "code": fields.String(description="상태 코드"),
        "label": fields.String(description="상태 라벨"),
        "reason": fields.String(description="상태 판단 근거"),
        "suspicious": fields.Boolean(description="문제 의심 여부"),
    })
    diagnostic_session = api.model("DiagnosticSession", {
        "sessionId": fields.String(description="진단 세션 ID"),
        "files": fields.List(fields.Nested(diagnostic_file), description="세션 파일 목록"),
        "status": fields.Nested(diagnostic_status, description="세션 상태 요약"),
        "updatedAt": fields.String(description="세션 최종 수정 시각"),
        "defaultFileUrl": fields.String(description="기본 미리보기 파일 URL"),
        "currentUrl": fields.String(description="대표 URL"),
        "title": fields.String(description="대표 페이지 제목"),
        "userAgent": fields.String(description="대표 User-Agent"),
    })
    diagnostic_list_response = api.model("DiagnosticListResponse", {
        "message": fields.String(description="응답 메시지"),
        "sessions": fields.List(fields.Nested(diagnostic_session), description="진단 세션 목록"),
    })
    diagnostic_error_response = api.model("DiagnosticErrorResponse", {
        "message": fields.String(description="에러 메시지"),
    })
    toggle_state_request = api.model("ReservationToggleStateRequest", {
        "activationKey": fields.String(required=True, description="인증 키"),
        "targetDate": fields.String(
            required=True, description="조회 날짜 (YYYY-MM-DD)", example="2026-08-22"
        ),
    })
    toggle_state_result = api.model("ReservationToggleStateResult", {
        "room": fields.String(description="객실", enum=["Yeoyu", "Yeohang"]),
        "date": fields.String(description="조회 날짜"),
        "reservationCount": fields.String(description="예약 수량"),
        "status": fields.String(
            description="판매 상태",
            enum=["available", "naverBlocked", "externallyBlocked", "error"],
        ),
        "errorDescription": fields.String(description="status가 error인 경우 상세 사유"),
    })
    toggle_state_response = api.model("ReservationToggleStateResponse", {
        "message": fields.String(description="응답 메시지"),
        "targetDate": fields.String(description="조회 날짜"),
        "results": fields.List(fields.Nested(toggle_state_result)),
    })
    toggle_state_error = api.model("ReservationToggleStateError", {
        "message": fields.String(description="에러 메시지"),
        "code": fields.String(description="오류 코드"),
    })
    diagnostic_delete_response = api.model("DiagnosticDeleteResponse", {
        "message": fields.String(description="응답 메시지"),
        "sessionId": fields.String(description="삭제된 세션 ID"),
    })
    diagnostic_bulk_delete_response = api.model("DiagnosticBulkDeleteResponse", {
        "message": fields.String(description="응답 메시지"),
        "deletedSessionIds": fields.List(fields.String, description="삭제된 세션 ID 목록"),
        "mode": fields.String(description="삭제 모드"),
    })
    return ApiModels(
        test_request, test_response, sync_in_request, sync_in_success_response,
        sync_in_error_response, booking, sync_out_request, sync_out_success_response,
        sync_out_error_response, diagnostic_file, diagnostic_status,
        diagnostic_session, diagnostic_list_response, diagnostic_error_response,
        toggle_state_request, toggle_state_result, toggle_state_response,
        toggle_state_error, diagnostic_delete_response,
        diagnostic_bulk_delete_response,
    )
