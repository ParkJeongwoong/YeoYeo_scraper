import datetime
import json
import mimetypes
import os
import shutil
from typing import Optional


class DiagnosticService:
    """Read and manage browser diagnostic snapshots in one configured directory."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def resolve_session_dir(self, session_id: str) -> Optional[str]:
        base_dir = os.path.abspath(self.base_dir)
        if not session_id:
            return None
        session_dir = os.path.abspath(os.path.join(base_dir, session_id))
        if session_dir == base_dir or os.path.commonpath([base_dir, session_dir]) != base_dir:
            return None
        return session_dir

    def resolve_file(self, session_id: str, filename: str) -> Optional[str]:
        session_dir = self.resolve_session_dir(session_id)
        if session_dir is None:
            return None
        target_path = os.path.abspath(os.path.join(session_dir, filename))
        if os.path.commonpath([session_dir, target_path]) != session_dir:
            return None
        return target_path

    @staticmethod
    def load_json(file_path: str):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError):
            return None

    def build_status(self, session_dir: str) -> dict:
        json_payloads = []
        for filename in os.listdir(session_dir):
            file_path = os.path.join(session_dir, filename)
            if filename.endswith(".json") and os.path.isfile(file_path):
                payload = self.load_json(file_path)
                if payload is not None:
                    json_payloads.append((filename, payload))

        protected_keywords = []
        empty_dom_detected = False
        empty_snapshot_detected = False
        for filename, payload in json_payloads:
            protected_keywords.extend(payload.get("detectedKeywords") or [])
            selector_counts = payload.get("selectorCounts") or {}
            if all(
                selector_counts.get(key, 0) == 0
                for key in ("bookingCards", "calendarDateInfo", "calendarNextButton")
            ):
                empty_dom_detected = True
            if filename.endswith("_empty.json"):
                empty_snapshot_detected = True

        protected_keywords = sorted(set(protected_keywords))
        if protected_keywords:
            return {
                "code": "protected", "label": "보호/인증 의심",
                "reason": ", ".join(protected_keywords[:5]), "suspicious": True,
            }
        if empty_dom_detected:
            return {
                "code": "empty_dom", "label": "빈 DOM 의심",
                "reason": "예약 카드와 캘린더 셀렉터가 모두 비어 있습니다.",
                "suspicious": True,
            }
        if empty_snapshot_detected:
            return {
                "code": "empty_result", "label": "빈 결과/렌더 지연 의심",
                "reason": "예약 목록 추출 결과가 비어 있습니다.",
                "suspicious": True,
            }
        return {
            "code": "ok", "label": "정상 후보",
            "reason": "특이한 진단 신호가 없습니다.", "suspicious": False,
        }

    def build_summary(self, session_dir: str) -> dict:
        preferred = [
            "booking_list_month_1_empty.json", "booking_list_loaded.json",
            "after_login.json",
        ]
        candidates = preferred + [
            name for name in sorted(os.listdir(session_dir))
            if name.endswith(".json") and name not in preferred
        ]
        for filename in candidates:
            payload = self.load_json(os.path.join(session_dir, filename))
            if payload is not None:
                return {
                    "currentUrl": payload.get("currentUrl"),
                    "title": payload.get("title"),
                    "userAgent": payload.get("userAgent"),
                }
        return {"currentUrl": None, "title": None, "userAgent": None}

    @staticmethod
    def pick_default_file(files: list, status_code: str):
        if not files:
            return None
        if status_code != "ok":
            keywords = [
                "login_failed", "login_finalize_detected", "_next_error",
                "_next_missing", "_timeout", "_empty", "booking_list_loaded",
                "after_login",
            ]
            for keyword in keywords:
                for extension in (".png", ".html", ".json"):
                    for file in files:
                        if keyword in file["name"] and file["name"].endswith(extension):
                            return file["url"]
        for extension in (".png", ".html", ".json"):
            for file in files:
                if file["name"].endswith(extension):
                    return file["url"]
        return files[0]["url"]

    def list_sessions(self) -> list:
        if not os.path.isdir(self.base_dir):
            return []
        sessions = []
        for session_id in os.listdir(self.base_dir):
            session_dir = os.path.join(self.base_dir, session_id)
            if not os.path.isdir(session_dir):
                continue
            files = []
            latest_timestamp = 0.0
            for filename in sorted(os.listdir(session_dir)):
                file_path = os.path.join(session_dir, filename)
                if not os.path.isfile(file_path):
                    continue
                latest_timestamp = max(latest_timestamp, os.path.getmtime(file_path))
                files.append({
                    "name": filename,
                    "contentType": mimetypes.guess_type(file_path)[0] or "application/octet-stream",
                    "size": os.path.getsize(file_path),
                    "url": f"/debug/diagnostics/{session_id}/{filename}",
                })
            status = self.build_status(session_dir)
            summary = self.build_summary(session_dir)
            sessions.append({
                "sessionId": session_id, "files": files, "status": status,
                "updatedAt": datetime.datetime.fromtimestamp(
                    latest_timestamp or os.path.getmtime(session_dir),
                    tz=datetime.timezone.utc,
                ).isoformat(),
                "defaultFileUrl": self.pick_default_file(files, status["code"]),
                **summary,
            })
        sessions.sort(
            key=lambda session: (session["updatedAt"], session["sessionId"]), reverse=True
        )
        return sessions

    def delete_session(self, session_id: str) -> bool:
        session_dir = self.resolve_session_dir(session_id)
        if session_dir is None or not os.path.isdir(session_dir):
            return False
        shutil.rmtree(session_dir, ignore_errors=True)
        return not os.path.exists(session_dir)

    def delete_sessions(self, mode: str) -> list:
        if mode not in {"all", "suspicious"} or not os.path.isdir(self.base_dir):
            return []
        suspicious_ids = {
            session["sessionId"] for session in self.list_sessions()
            if session.get("status", {}).get("suspicious")
        }
        deleted = []
        for session_id in os.listdir(self.base_dir):
            if mode == "suspicious" and session_id not in suspicious_ids:
                continue
            if self.delete_session(session_id):
                deleted.append(session_id)
        return sorted(deleted, reverse=True)
