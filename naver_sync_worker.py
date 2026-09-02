#!/usr/bin/env python3
import fcntl
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv

import syncManager
from application_client import ApplicationApiError, ApplicationClient
from chromeDriver import create_browser


class SyncWorker:
    def __init__(self, application_client, browser_factory=create_browser, logger=None):
        self.application = application_client
        self.browser_factory = browser_factory
        self.logger = logger or logging.getLogger("naver_sync_worker")
        self.authentication_failed = False

    def _event(self, run_id, direction, status, stage, **counts):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "runId": run_id,
            "direction": direction,
            "status": status,
            "stage": stage,
            **counts,
        }
        self.logger.info(json.dumps(record, ensure_ascii=False, sort_keys=True))

    def run(self):
        plan = self.application.get_plan()
        run_id = plan["runId"]
        self._event(run_id, "ALL", "STARTED", "PLAN")
        outbound_enabled = plan["serverToNaver"]["enabled"]
        inbound_enabled = plan["naverToServer"]["enabled"]
        results = {"runId": run_id, "serverToNaver": "DISABLED", "naverToServer": "DISABLED"}

        if not outbound_enabled:
            self._event(run_id, "SERVER_TO_NAVER", "DISABLED", "PLAN")
        if not inbound_enabled:
            self._event(run_id, "NAVER_TO_SERVER", "DISABLED", "PLAN")
        if not outbound_enabled and not inbound_enabled:
            self._event(run_id, "ALL", "SUCCESS", "COMPLETE",
                        serverToNaver="DISABLED", naverToServer="DISABLED")
            return results

        with self.browser_factory() as driver:
            if outbound_enabled:
                results["serverToNaver"] = self._run_outbound(driver, run_id)
            if inbound_enabled:
                if self.authentication_failed:
                    results["naverToServer"] = "FAILED"
                    self._event(run_id, "NAVER_TO_SERVER", "FAILED", "LOGIN_SESSION",
                                errorCode="SKIPPED_AFTER_AUTH_FAILURE")
                else:
                    results["naverToServer"] = self._run_inbound(driver, run_id, plan.get("monthSize", 6))
        overall = "FAILED" if "FAILED" in results.values() else (
            "PARTIAL_FAILURE" if "PARTIAL_FAILURE" in results.values() else "SUCCESS"
        )
        self._event(run_id, "ALL", overall, "COMPLETE",
                    serverToNaver=results["serverToNaver"],
                    naverToServer=results["naverToServer"])
        return results

    def _run_outbound(self, driver, run_id):
        try:
            claim = self.application.claim_outbound(run_id)
            operations = claim["operations"]
            result_items = []
            for operation in operations:
                authentication_failed = False
                try:
                    response = syncManager.SyncNaverIdempotent(
                        driver, operation["date"], operation["room"], operation["desiredState"]
                    )
                    date_results = response.get("results", [])
                    status = date_results[0].get("result") if date_results else "FAILED"
                    error_code = date_results[0].get("errorCode") if date_results else "MISSING_RESULT"
                except Exception as exception:
                    status = "FAILED"
                    error_code = type(exception).__name__
                    authentication_failed = isinstance(exception, syncManager.ReservationLookupError)
                result_items.append({
                    "operationId": operation["operationId"],
                    "status": status,
                    "errorCode": error_code,
                })
                if authentication_failed:
                    self.authentication_failed = True
                    break
            self.application.submit_outbound_results(run_id, claim["leaseToken"], result_items)
            success_count = sum(item["status"] in ("SUCCESS", "ALREADY_APPLIED") for item in result_items)
            status = "SUCCESS" if success_count == len(result_items) else (
                "PARTIAL_FAILURE" if success_count else "FAILED"
            )
            self._event(run_id, "SERVER_TO_NAVER", status, "NAVER_APPLY",
                        requested=len(result_items), succeeded=success_count,
                        failed=len(result_items) - success_count)
            return status
        except ApplicationApiError as exception:
            status = "DISABLED" if exception.code == "SYNC_DIRECTION_DISABLED" else "FAILED"
            self._event(run_id, "SERVER_TO_NAVER", status, "CLAIM", errorCode=exception.code)
            return status

    def _run_inbound(self, driver, run_id, month_size):
        try:
            not_canceled, all_bookings = syncManager.getNaverReservation(driver, month_size)
            self.application.submit_inbound_snapshot(run_id, not_canceled, all_bookings)
            self._event(run_id, "NAVER_TO_SERVER", "SUCCESS", "SNAPSHOT_APPLY",
                        requested=len(all_bookings), succeeded=len(not_canceled), failed=0)
            return "SUCCESS"
        except ApplicationApiError as exception:
            status = "DISABLED" if exception.code == "SYNC_DIRECTION_DISABLED" else "FAILED"
            self._event(run_id, "NAVER_TO_SERVER", status, "SNAPSHOT_APPLY", errorCode=exception.code)
            return status
        except Exception as exception:
            self._event(run_id, "NAVER_TO_SERVER", "FAILED", "LOGIN_SESSION",
                        errorCode=type(exception).__name__)
            return "FAILED"


@contextmanager
def exclusive_lock(path):
    lock_file = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    base_url = os.environ.get("APPLICATION_SERVER_URL")
    access_key = os.environ.get("APPLICATION_SYNC_ACCESS_KEY")
    if not base_url or not access_key:
        logging.error(json.dumps({"status": "FAILED", "stage": "CONFIG", "errorCode": "MISSING_CONFIG"}))
        return 2
    lock_path = os.environ.get("NAVER_SYNC_LOCK_FILE", "/tmp/yeoyeo_naver_sync.lock")
    with exclusive_lock(lock_path) as acquired:
        if not acquired:
            logging.info(json.dumps({"status": "SKIPPED_OVERLAP", "stage": "LOCK"}))
            return 0
        result = SyncWorker(ApplicationClient(base_url, access_key)).run()
        return 0 if "FAILED" not in result.values() and "PARTIAL_FAILURE" not in result.values() else 1


if __name__ == "__main__":
    sys.exit(main())
