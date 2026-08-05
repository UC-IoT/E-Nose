from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List


BOARD_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,15}$")
SUPPORTED_PARSERS = {"json_line", "framed_key_value", "sectioned_report", "board3_auto", "libelium"}


class BoardRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data.get("boards"), dict):
                raise ValueError("boards.json must contain a 'boards' object")
            for board_id, board in data["boards"].items():
                self._validate(board_id, board)
            self._data = data

    def _validate(self, board_id: str, board: Dict[str, Any]) -> None:
        if not BOARD_ID_RE.match(board_id):
            raise ValueError(f"Invalid board ID: {board_id}")
        if board.get("parser") not in SUPPORTED_PARSERS:
            raise ValueError(f"Unsupported parser for {board_id}: {board.get('parser')}")
        baud = int(board.get("baud", 0))
        if baud <= 0:
            raise ValueError(f"Invalid baud rate for {board_id}")

    def all(self, enabled_only: bool = False) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            result = {key: dict(value) for key, value in self._data["boards"].items()}
        if enabled_only:
            result = {key: value for key, value in result.items() if value.get("enabled", True)}
        return result

    def get(self, board_id: str) -> Dict[str, Any]:
        board = self.all().get(board_id)
        if not board:
            raise KeyError(f"Unknown board: {board_id}")
        return board

    def upsert(self, board_id: str, config: Dict[str, Any]) -> None:
        board_id = board_id.strip().upper()
        normalized = {
            "name": str(config.get("name") or board_id).strip(),
            "enabled": bool(config.get("enabled", True)),
            "transport": "serial",
            "baud": int(config.get("baud", 9600)),
            "parser": str(config.get("parser", "json_line")),
            "firebase_id": str(config.get("firebase_id") or board_id).strip().upper(),
            "notes": str(config.get("notes") or "").strip(),
        }
        self._validate(board_id, normalized)
        with self._lock:
            self._data["boards"][board_id] = normalized
            text = json.dumps(self._data, indent=2, ensure_ascii=False) + "\n"
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(self.path)

    def table_rows(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": board_id,
                "name": board["name"],
                "baud": board["baud"],
                "parser": board["parser"],
                "firebase": board.get("firebase_id", board_id),
                "enabled": "Yes" if board.get("enabled", True) else "No",
            }
            for board_id, board in self.all().items()
        ]


def discover_serial_ports() -> List[Dict[str, str]]:
    try:
        from serial.tools import list_ports

        ports = sorted(list_ports.comports(), key=lambda item: item.device)
        return [
            {
                "label": f"{port.device} — {port.description or 'Serial device'}",
                "value": port.device,
            }
            for port in ports
        ]
    except Exception:
        return []
