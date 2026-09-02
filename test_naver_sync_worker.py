import fcntl
import logging
from unittest.mock import MagicMock

import syncManager
from naver_sync_worker import SyncWorker, exclusive_lock


def test_disabled_directions_do_not_open_browser():
    application = MagicMock()
    application.get_plan.return_value = {
        "runId": "run-1",
        "serverToNaver": {"enabled": False},
        "naverToServer": {"enabled": False},
        "monthSize": 6,
    }
    browser_factory = MagicMock()

    result = SyncWorker(application, browser_factory, logging.getLogger("test")).run()

    assert result["serverToNaver"] == "DISABLED"
    assert result["naverToServer"] == "DISABLED"
    browser_factory.assert_not_called()


def test_direction_failures_are_independent(monkeypatch):
    application = MagicMock()
    application.get_plan.return_value = {
        "runId": "run-2",
        "serverToNaver": {"enabled": True},
        "naverToServer": {"enabled": True},
        "monthSize": 6,
    }
    application.claim_outbound.return_value = {"operations": [], "leaseToken": "lease"}
    driver = MagicMock()
    browser_factory = MagicMock()
    browser_factory.return_value.__enter__.return_value = driver
    monkeypatch.setattr("naver_sync_worker.syncManager.getNaverReservation", MagicMock(side_effect=RuntimeError("protected")))

    result = SyncWorker(application, browser_factory, logging.getLogger("test")).run()

    assert result["serverToNaver"] == "SUCCESS"
    assert result["naverToServer"] == "FAILED"
    application.submit_outbound_results.assert_called_once_with("run-2", "lease", [])
    application.submit_inbound_snapshot.assert_not_called()


def test_exclusive_lock_skips_overlapping_run(tmp_path):
    lock_path = str(tmp_path / "worker.lock")
    first = open(lock_path, "a+")
    fcntl.flock(first.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with exclusive_lock(lock_path) as acquired:
            assert acquired is False
    finally:
        fcntl.flock(first.fileno(), fcntl.LOCK_UN)
        first.close()


def test_auth_failure_stops_remaining_work_and_inbound(monkeypatch):
    application = MagicMock()
    application.get_plan.return_value = {
        "runId": "run-auth",
        "serverToNaver": {"enabled": True},
        "naverToServer": {"enabled": True},
        "monthSize": 6,
    }
    application.claim_outbound.return_value = {
        "leaseToken": "lease",
        "operations": [
            {"operationId": "op-1", "date": "2026-09-03", "room": "Yeoyu", "desiredState": "available"},
            {"operationId": "op-2", "date": "2026-09-04", "room": "Yeoyu", "desiredState": "available"},
        ],
    }
    browser_factory = MagicMock()
    browser_factory.return_value.__enter__.return_value = MagicMock()
    apply = MagicMock(side_effect=syncManager.ReservationLookupError("protected"))
    monkeypatch.setattr("naver_sync_worker.syncManager.SyncNaverIdempotent", apply)
    inbound = MagicMock()
    monkeypatch.setattr("naver_sync_worker.syncManager.getNaverReservation", inbound)

    result = SyncWorker(application, browser_factory, logging.getLogger("test")).run()

    assert result == {"runId": "run-auth", "serverToNaver": "FAILED", "naverToServer": "FAILED"}
    assert apply.call_count == 1
    inbound.assert_not_called()
    application.submit_outbound_results.assert_called_once()


def test_end_to_end_orchestration_sends_outbound_result_and_complete_snapshot(monkeypatch):
    application = MagicMock()
    application.get_plan.return_value = {
        "runId": "run-e2e",
        "serverToNaver": {"enabled": True},
        "naverToServer": {"enabled": True},
        "monthSize": 6,
    }
    application.claim_outbound.return_value = {
        "leaseToken": "lease",
        "operations": [{
            "operationId": "op-1", "date": "2026-09-05", "room": "Yeoyu",
            "desiredState": "externallyBlocked",
        }],
    }
    browser_factory = MagicMock()
    browser_factory.return_value.__enter__.return_value = MagicMock()
    monkeypatch.setattr("naver_sync_worker.syncManager.SyncNaverIdempotent", MagicMock(return_value={
        "results": [{"date": "2026-09-05", "result": "SUCCESS", "errorCode": None}],
    }))
    monkeypatch.setattr("naver_sync_worker.syncManager.getNaverReservation", MagicMock(return_value=([], [])))

    result = SyncWorker(application, browser_factory, logging.getLogger("test")).run()

    assert result == {"runId": "run-e2e", "serverToNaver": "SUCCESS", "naverToServer": "SUCCESS"}
    application.submit_outbound_results.assert_called_once_with("run-e2e", "lease", [{
        "operationId": "op-1", "status": "SUCCESS", "errorCode": None,
    }])
    application.submit_inbound_snapshot.assert_called_once_with("run-e2e", [], [])
