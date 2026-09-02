import requests


class ApplicationApiError(RuntimeError):
    def __init__(self, code, status_code=None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class ApplicationClient:
    def __init__(self, base_url, access_key, timeout=30, session=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.headers = {"X-Sync-Key": access_key, "Content-Type": "application/json"}

    def _request(self, method, path, payload=None):
        response = self.session.request(
            method, self.base_url + path, headers=self.headers, json=payload,
            timeout=self.timeout,
        )
        if response.status_code == 503:
            body = response.json()
            raise ApplicationApiError(body.get("code", "SYNC_DIRECTION_DISABLED"), 503)
        if not response.ok:
            raise ApplicationApiError("APPLICATION_API_ERROR", response.status_code)
        return response.json()

    def get_plan(self):
        return self._request("GET", "/internal/naver-sync/plan")

    def claim_outbound(self, run_id):
        return self._request("POST", "/internal/naver-sync/outbound/claim", {"runId": run_id})

    def submit_outbound_results(self, run_id, lease_token, results):
        return self._request("POST", "/internal/naver-sync/outbound/result", {
            "runId": run_id, "leaseToken": lease_token, "results": results,
        })

    def submit_inbound_snapshot(self, run_id, not_canceled, all_bookings):
        return self._request("POST", "/internal/naver-sync/inbound/snapshot", {
            "runId": run_id,
            "complete": True,
            "notCanceledBookingList": not_canceled,
            "allBookingList": all_bookings,
        })
