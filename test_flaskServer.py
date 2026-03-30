import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from flaskServer import app, checkActivationKey
import os


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def valid_activation_key():
    return os.environ.get("ACTIVATION_KEY", "test_key")


class TestHealthCheck:
    def test_debug_view_page(self, client):
        response = client.get('/debug/view')

        assert response.status_code == 200
        assert b"DOM Diagnostics Viewer" in response.data
        assert b"\xec\x84\xa0\xed\x83\x9d \xec\x84\xb8\xec\x85\x98 \xec\x82\xad\xec\xa0\x9c" in response.data
        assert b"\xeb\xac\xb8\xec\xa0\x9c \xec\x84\xb8\xec\x85\x98 \xec\x82\xad\xec\xa0\x9c" in response.data
        assert b"\xec\xa0\x84\xec\xb2\xb4 \xec\x84\xb8\xec\x85\x98 \xec\x82\xad\xec\xa0\x9c" in response.data
        assert b"\xec\x9b\x90\xeb\xb3\xb8 \xed\x81\xac\xea\xb8\xb0 \xeb\xb3\xb4\xea\xb8\xb0" in response.data

    def test_post_health_check(self, client):
        test_data = {"data": "test"}
        response = client.post(
            '/',
            data=json.dumps(test_data),
            content_type='application/json'
        )
        assert response.status_code == 200
        result = response.get_json()
        assert result["message"] == "Hello, World!"
        assert result["data"] == test_data


class TestCheckActivationKey:
    def test_valid_activation_key(self, valid_activation_key):
        req = {"activationKey": valid_activation_key}
        assert checkActivationKey(req) == True

    def test_invalid_activation_key(self):
        req = {"activationKey": "wrong_key"}
        assert checkActivationKey(req) == False

    def test_missing_activation_key(self):
        req = {}
        assert checkActivationKey(req) == False


class TestDiagnosticEndpoints:
    def test_list_diagnostic_sessions(self, client, valid_activation_key, tmp_path, monkeypatch):
        ok_session_dir = tmp_path / "20260321_090000_000001"
        ok_session_dir.mkdir(parents=True)
        (ok_session_dir / "booking_list_loaded.json").write_text(
            json.dumps({
                "currentUrl": "https://partner.booking.naver.com/example",
                "title": "예약자관리",
                "userAgent": "Mozilla/5.0 Test",
                "selectorCounts": {
                    "bookingCards": 2,
                    "calendarDateInfo": 1,
                    "calendarNextButton": 1
                },
                "detectedKeywords": []
            }),
            encoding="utf-8"
        )
        (ok_session_dir / "booking_list_loaded.html").write_text("<html></html>", encoding="utf-8")

        protected_session_dir = tmp_path / "20260321_100000_000002"
        protected_session_dir.mkdir(parents=True)
        (protected_session_dir / "booking_list_month_1_empty.json").write_text(
            json.dumps({
                "selectorCounts": {
                    "bookingCards": 0,
                    "calendarDateInfo": 0,
                    "calendarNextButton": 0
                },
                "detectedKeywords": ["로그인", "보안"]
            }),
            encoding="utf-8"
        )
        (protected_session_dir / "booking_list_month_1_empty.png").write_text("png", encoding="utf-8")

        monkeypatch.setattr("flaskServer.domDiagnosticDir", str(tmp_path))

        response = client.get(
            f'/debug/diagnostics?activationKey={valid_activation_key}'
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result["message"] == "Diagnostic Sessions"
        assert len(result["sessions"]) == 2
        assert result["sessions"][0]["sessionId"] == "20260321_100000_000002"
        assert result["sessions"][0]["status"]["code"] == "protected"
        assert result["sessions"][0]["status"]["suspicious"] is True
        assert result["sessions"][0]["defaultFileUrl"].endswith(".png")
        assert result["sessions"][0]["currentUrl"] is None
        assert result["sessions"][0]["title"] is None
        assert result["sessions"][0]["userAgent"] is None
        file_names = [file["name"] for file in result["sessions"][1]["files"]]
        assert "booking_list_loaded.json" in file_names
        assert "booking_list_loaded.html" in file_names
        assert result["sessions"][1]["files"][0]["url"].startswith("/debug/diagnostics/")
        assert result["sessions"][1]["currentUrl"] == "https://partner.booking.naver.com/example"
        assert result["sessions"][1]["title"] == "예약자관리"
        assert result["sessions"][1]["userAgent"] == "Mozilla/5.0 Test"

    def test_delete_diagnostic_session(self, client, valid_activation_key, tmp_path, monkeypatch):
        session_dir = tmp_path / "20260321_090000_000001"
        session_dir.mkdir(parents=True)
        (session_dir / "booking_list_loaded.json").write_text('{"ok": true}', encoding="utf-8")

        monkeypatch.setattr("flaskServer.domDiagnosticDir", str(tmp_path))

        response = client.delete(
            '/debug/diagnostics/20260321_090000_000001',
            headers={"X-Activation-Key": valid_activation_key},
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result["message"] == "Diagnostic Session Deleted"
        assert result["sessionId"] == "20260321_090000_000001"
        assert not session_dir.exists()

    def test_delete_all_diagnostic_sessions(self, client, valid_activation_key, tmp_path, monkeypatch):
        for session_id in ["20260321_090000_000001", "20260321_100000_000002"]:
            session_dir = tmp_path / session_id
            session_dir.mkdir(parents=True)
            (session_dir / "booking_list_loaded.json").write_text('{"ok": true}', encoding="utf-8")

        monkeypatch.setattr("flaskServer.domDiagnosticDir", str(tmp_path))

        response = client.delete(
            '/debug/diagnostics?mode=all',
            headers={"X-Activation-Key": valid_activation_key},
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result["message"] == "Diagnostic Sessions Deleted"
        assert result["mode"] == "all"
        assert set(result["deletedSessionIds"]) == {"20260321_090000_000001", "20260321_100000_000002"}
        assert not any(tmp_path.iterdir())

    def test_delete_suspicious_diagnostic_sessions(self, client, valid_activation_key, tmp_path, monkeypatch):
        ok_session_dir = tmp_path / "20260321_090000_000001"
        ok_session_dir.mkdir(parents=True)
        (ok_session_dir / "booking_list_loaded.json").write_text(
            json.dumps({
                "selectorCounts": {
                    "bookingCards": 1,
                    "calendarDateInfo": 1,
                    "calendarNextButton": 1
                },
                "detectedKeywords": []
            }),
            encoding="utf-8"
        )

        protected_session_dir = tmp_path / "20260321_100000_000002"
        protected_session_dir.mkdir(parents=True)
        (protected_session_dir / "booking_list_month_1_empty.json").write_text(
            json.dumps({
                "selectorCounts": {
                    "bookingCards": 0,
                    "calendarDateInfo": 0,
                    "calendarNextButton": 0
                },
                "detectedKeywords": ["로그인"]
            }),
            encoding="utf-8"
        )

        monkeypatch.setattr("flaskServer.domDiagnosticDir", str(tmp_path))

        response = client.delete(
            '/debug/diagnostics?mode=suspicious',
            headers={"X-Activation-Key": valid_activation_key},
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result["mode"] == "suspicious"
        assert result["deletedSessionIds"] == ["20260321_100000_000002"]
        assert ok_session_dir.exists()
        assert not protected_session_dir.exists()

    def test_list_diagnostic_sessions_requires_activation_key(self, client):
        response = client.get('/debug/diagnostics?activationKey=wrong_key')

        assert response.status_code == 401
        result = response.get_json()
        assert result["message"] == "Invalid Access Key"

    def test_get_diagnostic_file(self, client, valid_activation_key, tmp_path, monkeypatch):
        session_dir = tmp_path / "20260321_090000_000001"
        session_dir.mkdir(parents=True)
        file_path = session_dir / "booking_list_loaded.html"
        file_path.write_text("<html><body>ok</body></html>", encoding="utf-8")

        monkeypatch.setattr("flaskServer.domDiagnosticDir", str(tmp_path))

        response = client.get(
            f'/debug/diagnostics/20260321_090000_000001/booking_list_loaded.html?activationKey={valid_activation_key}'
        )

        assert response.status_code == 200
        assert b"ok" in response.data

    def test_get_diagnostic_file_with_header_key(self, client, valid_activation_key, tmp_path, monkeypatch):
        session_dir = tmp_path / "20260321_090000_000001"
        session_dir.mkdir(parents=True)
        file_path = session_dir / "booking_list_loaded.json"
        file_path.write_text('{"ok": true}', encoding="utf-8")

        monkeypatch.setattr("flaskServer.domDiagnosticDir", str(tmp_path))

        response = client.get(
            '/debug/diagnostics/20260321_090000_000001/booking_list_loaded.json',
            headers={"X-Activation-Key": valid_activation_key},
        )

        assert response.status_code == 200
        assert b'"ok": true' in response.data

    def test_get_diagnostic_file_blocks_path_traversal(self, client, valid_activation_key, tmp_path, monkeypatch):
        session_dir = tmp_path / "20260321_090000_000001"
        session_dir.mkdir(parents=True)
        monkeypatch.setattr("flaskServer.domDiagnosticDir", str(tmp_path))

        response = client.get(
            f'/debug/diagnostics/20260321_090000_000001/../secret.txt?activationKey={valid_activation_key}'
        )

        assert response.status_code == 404


class TestSyncNaverReservation:
    @patch('flaskServer.syncManager.SyncNaver')
    @patch('flaskServer.chromeDriver.ChromeDriver')
    def test_sync_in_success(self, mock_chrome_driver, mock_sync_naver, client, valid_activation_key):
        mock_driver_instance = MagicMock()
        mock_chrome_driver.return_value = mock_driver_instance
        mock_sync_naver.return_value = ["2024-09-02", "2024-09-03"]

        request_data = {
            "activationKey": valid_activation_key,
            "targetDatesStr": "2024-09-02,2024-09-03",
            "targetRoom": "Yeoyu"
        }

        response = client.post(
            '/sync/in',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result["message"] == "Sync Naver Reservation"
        assert result["successDates"] == ["2024-09-02", "2024-09-03"]
        assert result["data"] == request_data
        mock_driver_instance.close.assert_called_once()

    @patch('flaskServer.chromeDriver.ChromeDriver')
    def test_sync_in_invalid_key(self, mock_chrome_driver, client):
        mock_driver_instance = MagicMock()
        mock_chrome_driver.return_value = mock_driver_instance

        request_data = {
            "activationKey": "wrong_key",
            "targetDatesStr": "2024-09-02",
            "targetRoom": "Yeoyu"
        }

        response = client.post(
            '/sync/in',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 401
        result = response.get_json()
        assert result["message"] == "Invalid Access Key"
        mock_driver_instance.close.assert_called_once()

    @patch('flaskServer.syncManager.SyncNaver')
    @patch('flaskServer.chromeDriver.ChromeDriver')
    def test_sync_in_server_error(self, mock_chrome_driver, mock_sync_naver, client, valid_activation_key):
        mock_driver_instance = MagicMock()
        mock_chrome_driver.return_value = mock_driver_instance
        mock_sync_naver.side_effect = Exception("Test error")

        request_data = {
            "activationKey": valid_activation_key,
            "targetDatesStr": "2024-09-02",
            "targetRoom": "Yeoyu"
        }

        response = client.post(
            '/sync/in',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 500
        result = response.get_json()
        assert result["message"] == "Sync Naver Reservation Failed"
        mock_driver_instance.close.assert_called_once()

    @patch('flaskServer.syncManager.SyncNaver')
    @patch('flaskServer.chromeDriver.ChromeDriver')
    def test_sync_in_yeohang_room(self, mock_chrome_driver, mock_sync_naver, client, valid_activation_key):
        mock_driver_instance = MagicMock()
        mock_chrome_driver.return_value = mock_driver_instance
        mock_sync_naver.return_value = ["2024-09-05"]

        request_data = {
            "activationKey": valid_activation_key,
            "targetDatesStr": "2024-09-05",
            "targetRoom": "Yeohang"
        }

        response = client.post(
            '/sync/in',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result["successDates"] == ["2024-09-05"]
        mock_sync_naver.assert_called_once_with(mock_driver_instance, "2024-09-05", "Yeohang")


class TestGetNaverReservation:
    @patch('flaskServer.syncManager.getNaverReservation')
    @patch('flaskServer.chromeDriver.ChromeDriver')
    def test_sync_out_success(self, mock_chrome_driver, mock_get_reservation, client, valid_activation_key):
        mock_driver_instance = MagicMock()
        mock_chrome_driver.return_value = mock_driver_instance
        
        not_canceled_list = [
            {
                "name": "홍길동",
                "phone": "010-1234-5678",
                "reservationNumber": "12345678",
                "startDate": "20240819",
                "endDate": "20240821",
                "room": "여유",
                "option": "조식 포함",
                "comment": "늦은 체크인 요청",
                "price": "150,000원",
                "status": "예약확정"
            }
        ]
        all_list = not_canceled_list + [
            {
                "name": "김철수",
                "phone": "010-9876-5432",
                "reservationNumber": "87654321",
                "startDate": "20240901",
                "endDate": "20240903",
                "room": "여행",
                "option": None,
                "comment": None,
                "price": "200,000원",
                "status": "취소"
            }
        ]
        mock_get_reservation.return_value = (not_canceled_list, all_list)

        request_data = {
            "activationKey": valid_activation_key,
            "monthSize": 2
        }

        response = client.post(
            '/sync/out',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result["message"] == "Sync Naver Reservation"
        assert len(result["notCanceledBookingList"]) == 1
        assert len(result["allBookingList"]) == 2
        assert result["notCanceledBookingList"][0]["name"] == "홍길동"
        mock_driver_instance.close.assert_called_once()

    @patch('flaskServer.chromeDriver.ChromeDriver')
    def test_sync_out_invalid_key(self, mock_chrome_driver, client):
        mock_driver_instance = MagicMock()
        mock_chrome_driver.return_value = mock_driver_instance

        request_data = {
            "activationKey": "wrong_key"
        }

        response = client.post(
            '/sync/out',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 401
        result = response.get_json()
        assert result["message"] == "Invalid Access Key"
        mock_driver_instance.close.assert_called_once()

    @patch('flaskServer.syncManager.getNaverReservation')
    @patch('flaskServer.chromeDriver.ChromeDriver')
    def test_sync_out_default_month_size(self, mock_chrome_driver, mock_get_reservation, client, valid_activation_key):
        mock_driver_instance = MagicMock()
        mock_chrome_driver.return_value = mock_driver_instance
        mock_get_reservation.return_value = ([], [])

        request_data = {
            "activationKey": valid_activation_key
        }

        response = client.post(
            '/sync/out',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 200
        mock_get_reservation.assert_called_once_with(mock_driver_instance, 1)

    @patch('flaskServer.syncManager.getNaverReservation')
    @patch('flaskServer.chromeDriver.ChromeDriver')
    def test_sync_out_server_error(self, mock_chrome_driver, mock_get_reservation, client, valid_activation_key):
        mock_driver_instance = MagicMock()
        mock_chrome_driver.return_value = mock_driver_instance
        mock_get_reservation.side_effect = Exception("Test error")

        request_data = {
            "activationKey": valid_activation_key,
            "monthSize": 1
        }

        response = client.post(
            '/sync/out',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 500
        result = response.get_json()
        assert result["message"] == "Get Naver Reservation Failed: Test error"
        mock_driver_instance.close.assert_called_once()

    @patch('flaskServer.syncManager.getNaverReservation')
    @patch('flaskServer.chromeDriver.ChromeDriver')
    def test_sync_out_with_zero_month_size(self, mock_chrome_driver, mock_get_reservation, client, valid_activation_key):
        mock_driver_instance = MagicMock()
        mock_chrome_driver.return_value = mock_driver_instance
        mock_get_reservation.return_value = ([], [])

        request_data = {
            "activationKey": valid_activation_key,
            "monthSize": 0
        }

        response = client.post(
            '/sync/out',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 200
        mock_get_reservation.assert_called_once_with(mock_driver_instance, 0)
