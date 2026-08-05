from __future__ import annotations

import threading
import time
from typing import Any, Dict

import serial

from .parsers import make_parser
from .registry import BoardRegistry


class BoardHealthManager:
    """Read one complete sample from each selected board without starting a capture."""

    def __init__(self, registry: BoardRegistry):
        self.registry = registry
        self.lock = threading.RLock()
        self.statuses: Dict[str, Dict[str, Any]] = {}
        self.running = False
        self._remaining = 0

    def start(self, ports: Dict[str, str]) -> None:
        with self.lock:
            if self.running:
                raise RuntimeError("A board health check is already running")
            if not ports:
                raise ValueError("Select at least one board and COM port")
            self.running = True
            self._remaining = len(ports)
            self.statuses = {
                board_id: {"state": "queued", "message": f"Preparing {port}"}
                for board_id, port in ports.items()
            }
        for board_id, port in ports.items():
            thread = threading.Thread(
                target=self._test_one,
                args=(board_id, port),
                daemon=True,
                name=f"health-{board_id}",
            )
            thread.start()

    def _test_one(self, board_id: str, port: str) -> None:
        config = self.registry.get(board_id)
        parser_name = config.get("parser")
        if parser_name == "libelium":
            timeout_seconds = 180
        elif parser_name == "board3_auto":
            timeout_seconds = 90
        else:
            timeout_seconds = 45
        connection = None
        started = time.monotonic()
        line_count = 0
        self._set(board_id, "connecting", f"Opening {port} at {config['baud']} baud")
        try:
            connection = serial.Serial(port, int(config["baud"]), timeout=1)
            parser = make_parser(config["parser"], board_id)
            self._set(board_id, "listening", f"Connected to {port} · waiting for one complete sample")
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                raw = connection.readline()
                if not raw:
                    continue
                line_count += 1
                reading = parser.feed(raw.decode("utf-8", errors="ignore"))
                if reading is None:
                    continue
                names = list(reading.sensors)
                preview = ", ".join(names[:4]) + ("…" if len(names) > 4 else "")
                elapsed = time.monotonic() - started
                self._set(
                    board_id,
                    "passed",
                    f"Connected and sending data · {len(names)} sensors · {elapsed:.1f}s",
                    port=port,
                    sensors=names,
                    preview=preview,
                )
                return
            self._set(
                board_id,
                "failed",
                f"Port opened but no complete sample arrived in {timeout_seconds}s ({line_count} lines received)",
                port=port,
            )
        except Exception as exc:
            self._set(board_id, "failed", f"Could not test {port}: {exc}", port=port)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            with self.lock:
                self._remaining -= 1
                if self._remaining <= 0:
                    self.running = False

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "statuses": {key: dict(value) for key, value in self.statuses.items()},
            }

    def _set(self, board_id: str, state: str, message: str, **extra: Any) -> None:
        with self.lock:
            self.statuses[board_id] = {"state": state, "message": message, **extra}
