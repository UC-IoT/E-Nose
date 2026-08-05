from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import serial

from .firebase_client import FirebaseClient
from .models import Reading, SessionSpec
from .parsers import make_parser
from .registry import BoardRegistry
from .storage import SessionStore


class BoardWorker(threading.Thread):
    daemon = True

    def __init__(self, manager: "CaptureManager", board_id: str, port: str, config: Dict[str, Any]):
        super().__init__(name=f"capture-{board_id}")
        self.manager = manager
        self.board_id = board_id
        self.port = port
        self.config = config
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        self.manager._set_status(self.board_id, "connecting", "Connecting to serial port")
        connection: Optional[serial.Serial] = None
        try:
            for attempt in range(1, 6):
                try:
                    connection = serial.Serial(self.port, int(self.config["baud"]), timeout=1)
                    break
                except (PermissionError, serial.SerialException) as exc:
                    if attempt == 5 or "access is denied" not in str(exc).lower():
                        raise
                    self.manager._set_status(
                        self.board_id,
                        "connecting",
                        f"{self.port} is busy; retrying ({attempt}/5). Close Waspmote/Serial Monitor if it remains busy.",
                    )
                    time.sleep(1)
            if connection is None:
                raise RuntimeError(f"Could not open {self.port}")
            time.sleep(0.6)
            parser = make_parser(self.config["parser"], self.board_id)
            if self.config["parser"] == "board3_auto":
                message = "COM port open · Board3 is initialising (first reading can take about 60 seconds)"
            else:
                message = "COM port open · waiting for a complete reading"
            self.manager._set_status(self.board_id, "listening", message)
            connected_at = time.monotonic()
            last_wait_report = connected_at
            line_count = 0
            has_reading = False
            while not self.stop_event.is_set() and not self.manager.stop_event.is_set():
                try:
                    raw = connection.readline().decode("utf-8", errors="ignore")
                except Exception as exc:
                    self.manager._set_status(self.board_id, "error", f"Serial read error: {exc}")
                    time.sleep(0.5)
                    continue
                if not raw:
                    now = time.monotonic()
                    if not has_reading and now - last_wait_report >= 5:
                        elapsed = int(now - connected_at)
                        self.manager._set_status(
                            self.board_id,
                            "listening",
                            f"COM port open · no serial data received for {elapsed}s",
                            lines_received=line_count,
                        )
                        last_wait_report = now
                    continue
                line_count += 1
                reading = parser.feed(raw)
                if reading is not None:
                    has_reading = True
                    self.manager.accept(reading, self.config)
                elif not has_reading and time.monotonic() - last_wait_report >= 5:
                    self.manager._set_status(
                        self.board_id,
                        "listening",
                        f"{line_count} serial lines received · waiting for a complete sample",
                        lines_received=line_count,
                    )
                    last_wait_report = time.monotonic()
        except Exception as exc:
            detail = str(exc)
            if "access is denied" in detail.lower():
                detail += ". Close Waspmote Monitor, Arduino Serial Monitor, and any other dashboard using this COM port, then retry."
            self.manager._set_status(self.board_id, "error", f"Could not open {self.port}: {detail}")
        finally:
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass
            if self.manager.statuses.get(self.board_id, {}).get("state") != "error":
                self.manager._set_status(self.board_id, "stopped", "Serial connection closed")


class CaptureManager:
    def __init__(self, registry: BoardRegistry, data_root: Path, firebase: FirebaseClient):
        self.registry = registry
        self.data_root = Path(data_root)
        self.firebase = firebase
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.active = False
        self.paused = False
        self.store: Optional[SessionStore] = None
        self.spec: Optional[SessionSpec] = None
        self.workers: Dict[str, BoardWorker] = {}
        self.statuses: Dict[str, Dict[str, Any]] = {}
        self.live: Dict[str, Deque[Dict[str, Any]]] = {}
        self.started_monotonic = 0.0
        self.stop_reason = ""
        self.pending_timer: Optional[threading.Timer] = None
        self.last_accepted: Dict[str, float] = {}
        self.pause_started = 0.0
        self.paused_total = 0.0
        self.elapsed_at_stop = 0.0
        self.first_seen: set[str] = set()
        self.capture_clock_started = False
        self.timer_required_boards: set[str] = set()
        self.cloud_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="firebase-upload")

    def schedule(self, spec: SessionSpec, delay_seconds: int) -> None:
        with self.lock:
            if self.active or self.pending_timer is not None:
                raise RuntimeError("A capture or warm-up is already active")
            self.spec = spec
            self.statuses = {
                board_id: {"state": "warm-up", "message": f"Capture starts in {delay_seconds} seconds"}
                for board_id in spec.selected_boards
            }
            timer = threading.Timer(delay_seconds, self._start_scheduled, args=(spec,))
            timer.daemon = True
            self.pending_timer = timer
            timer.start()

    def _start_scheduled(self, spec: SessionSpec) -> None:
        with self.lock:
            self.pending_timer = None
        try:
            self.start(spec)
        except Exception as exc:
            for board_id in spec.selected_boards:
                self._set_status(board_id, "error", f"Scheduled capture failed: {exc}")

    def start(self, spec: SessionSpec) -> Path:
        with self.lock:
            if self.active:
                raise RuntimeError("A capture is already active")
            if not spec.selected_boards:
                raise ValueError("Select at least one board and COM port")
            self.stop_event.clear()
            self.spec = spec
            self.store = SessionStore(self.data_root, spec)
            self.active = True
            self.paused = False
            self.started_monotonic = 0.0
            self.stop_reason = ""
            self.last_accepted = {}
            self.pause_started = 0.0
            self.paused_total = 0.0
            self.elapsed_at_stop = 0.0
            self.first_seen = set()
            self.timer_required_boards = {
                board_id
                for board_id in spec.selected_boards
                if self.registry.get(board_id).get("parser") != "libelium"
            }
            self.capture_clock_started = not self.timer_required_boards
            if self.capture_clock_started:
                self.started_monotonic = time.monotonic()
            self.statuses = {}
            self.live = {board_id: deque(maxlen=300) for board_id in spec.selected_boards}
            self.firebase.write_session_metadata(spec)
            for board_id, port in spec.selected_boards.items():
                config = self.registry.get(board_id)
                worker = BoardWorker(self, board_id, port, config)
                self.workers[board_id] = worker
                worker.start()
            if spec.duration_seconds > 0:
                threading.Thread(target=self._duration_watch, daemon=True).start()
            return self.store.path

    def _duration_watch(self) -> None:
        assert self.spec is not None
        duration = self.spec.duration_seconds
        while self.active and not self.stop_event.wait(0.25):
            if self._elapsed() >= duration:
                self.stop("duration complete")
                break

    def accept(self, reading: Reading, board_config: Dict[str, Any]) -> None:
        with self.lock:
            if not self.active or self.paused or self.store is None or self.spec is None:
                return
            now = time.monotonic()
            self.first_seen.add(reading.board_id)
            if not self.capture_clock_started and self.first_seen.issuperset(self.timer_required_boards):
                self.started_monotonic = now
                self.capture_clock_started = True
            last = self.last_accepted.get(reading.board_id, 0.0)
            if now - last < self.spec.interval_seconds:
                return
            self.last_accepted[reading.board_id] = now
            store = self.store
            spec = self.spec

        path = store.append(reading)
        point = {
            "timestamp": reading.timestamp,
            "timestamp_ms": reading.timestamp_ms,
            "sensors": {name: sensor.value for name, sensor in reading.sensors.items()},
            "battery_percent": reading.battery_percent,
            "battery_volts": reading.battery_volts,
        }
        with self.lock:
            self.live.setdefault(reading.board_id, deque(maxlen=300)).append(point)
            self._set_status(
                reading.board_id,
                "capturing",
                f"{store._counts.get(reading.board_id, 0)} samples · {path.name}",
                firebase="syncing",
                last_seen=reading.timestamp,
                battery_percent=reading.battery_percent,
                battery_volts=reading.battery_volts,
            )
        self.cloud_executor.submit(
            self._upload_reading,
            spec,
            reading,
            board_config.get("firebase_id", reading.board_id),
            store.path / "firebase_pending.jsonl",
        )

    def _upload_reading(self, spec: SessionSpec, reading: Reading, firebase_board_id: str, queue: Path) -> None:
        online = self.firebase.write_reading(spec, reading, firebase_board_id, queue)
        with self.lock:
            status = self.statuses.get(reading.board_id)
            if status is not None:
                status["firebase"] = "synced" if online else "queued"

    def pause(self) -> bool:
        with self.lock:
            if not self.active:
                return False
            self.paused = not self.paused
            if self.paused:
                self.pause_started = time.monotonic()
            elif self.pause_started:
                self.paused_total += time.monotonic() - self.pause_started
                self.pause_started = 0.0
            return self.paused

    def stop(self, reason: str = "stopped by user") -> None:
        with self.lock:
            if self.pending_timer is not None:
                self.pending_timer.cancel()
                self.pending_timer = None
                self.stop_reason = "warm-up cancelled"
                for board_id in self.statuses:
                    self.statuses[board_id] = {"state": "stopped", "message": "Warm-up cancelled"}
                return
            if not self.active:
                return
            self.elapsed_at_stop = self._elapsed()
            self.active = False
            self.stop_reason = reason
            self.stop_event.set()
            workers = list(self.workers.values())
        for worker in workers:
            worker.stop()
            if threading.current_thread() is not worker:
                worker.join(timeout=2)
        with self.lock:
            self.workers.clear()
            if self.store:
                self.store.complete("completed" if reason == "duration complete" else "stopped")

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            elapsed = self._elapsed() if self.active else self.elapsed_at_stop
            duration = self.spec.duration_seconds if self.spec else 0
            progress = min(100.0, elapsed * 100 / duration) if duration else 0.0
            return {
                "active": self.active,
                "scheduled": self.pending_timer is not None,
                "waiting_for_boards": self.active and not self.capture_clock_started,
                "timer_required_boards": sorted(self.timer_required_boards),
                "paused": self.paused,
                "elapsed_seconds": round(elapsed, 1),
                "duration_seconds": duration,
                "remaining_seconds": max(0, round(duration - elapsed, 1)) if duration else 0,
                "progress_percent": round(progress, 1),
                "session_id": self.spec.session_id if self.spec else None,
                "session_path": str(self.store.path) if self.store else None,
                "statuses": {key: dict(value) for key, value in self.statuses.items()},
                "live": {key: list(value) for key, value in self.live.items()},
                "firebase": self.firebase.message,
                "pending": self.firebase.queue_count(self.store.path / "firebase_pending.jsonl") if self.store else 0,
                "stop_reason": self.stop_reason,
            }

    def _elapsed(self) -> float:
        if not self.started_monotonic:
            return 0.0
        now = self.pause_started if self.paused and self.pause_started else time.monotonic()
        return max(0.0, now - self.started_monotonic - self.paused_total)

    def _set_status(self, board_id: str, state: str, message: str, **extra: Any) -> None:
        with self.lock:
            status = dict(self.statuses.get(board_id, {}))
            status.update({"state": state, "message": message, **extra})
            self.statuses[board_id] = status
