from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .models import Reading, SessionSpec, firebase_safe_key


def firebase_safe_payload(value: Any) -> Any:
    """Recursively make dictionary keys valid for Firebase Realtime Database."""
    if isinstance(value, dict):
        return {firebase_safe_key(key): firebase_safe_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [firebase_safe_payload(item) for item in value]
    return value


class FirebaseClient:
    """Firebase writer with a durable JSONL queue when cloud writes are unavailable."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.settings = self._load_settings()
        self.ready = False
        self.message = "Not initialised"
        self._lock = threading.RLock()
        self._db = None
        self._rest = False

    def initialize(self) -> bool:
        with self._lock:
            if self.ready:
                return True
            try:
                import firebase_admin
                from firebase_admin import credentials, db

                url = os.getenv("DATABASE_URL") or os.getenv("databaseURL") or self.settings.get("database_url")
                if not url:
                    self.message = "Offline: DATABASE_URL is not set"
                    return False
                if not firebase_admin._apps:
                    key = os.getenv("FIREBASE_KEY")
                    if key:
                        service = json.loads(key)
                        service["private_key"] = service.get("private_key", "").replace("\\n", "\n")
                        credential = credentials.Certificate(service)
                    else:
                        configured = os.getenv("FIREBASE_CREDENTIALS_PATH") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                        candidates = [
                            Path(configured) if configured else None,
                            self.project_root / "serviceAccountKey.json",
                            self.project_root.parent / "serviceAccountKey.json",
                        ]
                        credential_path = next((path for path in candidates if path and path.is_file()), None)
                        if credential_path is None:
                            self._rest = True
                            self.ready = True
                            self.message = "REST mode (verifying access)"
                            return True
                        credential = credentials.Certificate(str(credential_path))
                    firebase_admin.initialize_app(credential, {"databaseURL": url})
                self._db = db
                self.ready = True
                self.message = "Online"
                return True
            except Exception as exc:
                if self.database_url:
                    self._rest = True
                    self.ready = True
                    self.message = "REST mode (verifying access)"
                    return True
                self.ready = False
                self.message = f"Offline: {exc}"
                return False

    def check_connection(self) -> bool:
        """Perform a real read against the configured Realtime Database."""
        if not self.initialize():
            return False
        try:
            # A real read verifies URL, credentials, network access and database rules.
            # This path already belongs to the existing dashboard's diagnostic namespace.
            if self._rest:
                self._rest_request("GET", "test_connection")
            else:
                self._db.reference("test_connection").get()
            self.ready = True
            self.message = "Online and verified"
            return True
        except Exception as exc:
            self.ready = False
            self.message = f"Offline: {exc}"
            return False

    @property
    def database_url(self) -> str:
        return str(os.getenv("DATABASE_URL") or os.getenv("databaseURL") or self.settings.get("database_url") or "")

    @property
    def console_url(self) -> str:
        return str(os.getenv("FIREBASE_CONSOLE_URL") or self.settings.get("firebase_console_url") or self.database_url)

    def _load_settings(self) -> Dict[str, Any]:
        path = self.project_root / "config" / "settings.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def write_session_metadata(self, spec: SessionSpec) -> bool:
        if not self.initialize():
            return False
        try:
            root = self._session_root(spec)
            self._set(
                f"{root}/metadata",
                {
                    "schema_version": 2,
                    "stage": spec.stage,
                    "substance": spec.substance,
                    "session_id": spec.session_id,
                    "capture_type": spec.capture_type,
                    "selected_boards": list(spec.selected_boards),
                    "flowrate_l_min": spec.flowrate,
                    "interval_seconds": spec.interval_seconds,
                    "duration_seconds": spec.duration_seconds,
                    "baseline_session_id": spec.baseline_session_id,
                    "created_at": spec.created_at,
                    "status": "running",
                }
            )
            return True
        except Exception as exc:
            self.ready = False
            self.message = f"Offline: {exc}"
            return False

    def write_reading(
        self,
        spec: SessionSpec,
        reading: Reading,
        firebase_board_id: str,
        queue_file: Path,
    ) -> bool:
        payload = reading.firebase_payload()
        operation = {
            "path": f"{self._session_root(spec)}/boards/{firebase_board_id}/readings/{reading.timestamp_ms}",
            "live_path": f"live/{firebase_board_id}/readings/{reading.timestamp_ms}",
            "payload": payload,
        }
        if self.initialize():
            try:
                self._set(operation["path"], payload)
                self._set(operation["live_path"], payload)
                return True
            except Exception as exc:
                self.ready = False
                self.message = f"Offline: {exc}"
        with self._lock:
            self._append_queue(queue_file, operation)
        return False

    def sync_queue(self, queue_file: Path) -> Tuple[int, int]:
        path = Path(queue_file)
        if not path.exists() or path.stat().st_size == 0:
            return 0, 0
        if not self.initialize():
            return 0, self.queue_count(path)
        with self._lock:
            lines = path.read_text(encoding="utf-8").splitlines()
            failed = []
            uploaded = 0
            for line in lines:
                try:
                    item = json.loads(line)
                    payload = firebase_safe_payload(item["payload"])
                    self._set(item["path"], payload)
                    self._set(item["live_path"], payload)
                    uploaded += 1
                except Exception:
                    failed.append(line)
            temporary = path.with_suffix(".jsonl.tmp")
            temporary.write_text("\n".join(failed) + ("\n" if failed else ""), encoding="utf-8")
            temporary.replace(path)
            return uploaded, len(failed)

    @staticmethod
    def queue_count(queue_file: Path) -> int:
        path = Path(queue_file)
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    @staticmethod
    def _append_queue(queue_file: Path, operation: Dict[str, Any]) -> None:
        path = Path(queue_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(operation, separators=(",", ":")) + "\n")

    @staticmethod
    def _session_root(spec: SessionSpec) -> str:
        substance = "baseline" if spec.capture_type == "baseline" else spec.substance
        return "/".join(firebase_safe_key(part) for part in (spec.stage, substance, spec.session_id))

    def _set(self, path: str, payload: Any) -> None:
        payload = firebase_safe_payload(payload)
        if self._rest:
            self._rest_request("PUT", path, payload)
        else:
            self._db.reference(path).set(payload)

    def _rest_request(self, method: str, path: str, payload: Any = None) -> Any:
        base = self.database_url.rstrip("/")
        safe_path = "/".join(urllib.parse.quote(part, safe="") for part in path.strip("/").split("/"))
        url = f"{base}/{safe_path}.json"
        secret = os.getenv("FIREBASE_DATABASE_SECRET")
        if secret:
            url += "?auth=" + urllib.parse.quote(secret, safe="")
        data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Firebase REST {exc.code}: {detail}") from exc
