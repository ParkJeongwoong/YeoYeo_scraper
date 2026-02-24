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
        assert result["message"] == "Get Naver Reservation Failed"
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
