from __future__ import annotations

import csv
import json
import os
import re
import statistics
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import Reading, SessionSpec


SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
BASE_COLUMNS = [
    "Timestamp",
    "Elapsed_seconds",
    "Flowrate (L/min)",
    "Battery (%)",
    "Battery (V)",
]


def safe_name(value: str, fallback: str = "unnamed") -> str:
    cleaned = SAFE_RE.sub("_", str(value).strip()).strip("._")
    return cleaned or fallback


def make_session_id(stage: str, substance: str) -> str:
    prefix = {"Testing": "T", "Experiment": "E", "Deployment": "D", "Baseline": "B"}.get(stage, "X")
    return f"{prefix}-{safe_name(substance)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


class SessionStore:
    """Own a single capture session and one evolving CSV schema per board."""

    def __init__(self, data_root: Path, spec: SessionSpec):
        self.data_root = Path(data_root)
        self.spec = spec
        substance = "baseline" if spec.capture_type == "baseline" else safe_name(spec.substance)
        self.path = self.data_root / safe_name(spec.stage) / substance / safe_name(spec.session_id)
        self.path.mkdir(parents=True, exist_ok=False)
        self.started_ms = int(datetime.now().timestamp() * 1000)
        self._locks: Dict[str, threading.RLock] = {}
        self._headers: Dict[str, List[str]] = {}
        self._counts: Dict[str, int] = {board_id: 0 for board_id in spec.selected_boards}
        self._write_metadata("running")

    def _write_metadata(self, status: str, **extra: Any) -> None:
        payload: Dict[str, Any] = {
            "schema_version": 2,
            "status": status,
            "stage": self.spec.stage,
            "substance": self.spec.substance,
            "session_id": self.spec.session_id,
            "capture_type": self.spec.capture_type,
            "selected_boards": list(self.spec.selected_boards),
            "ports": self.spec.selected_boards,
            "flowrate_l_min": self.spec.flowrate,
            "interval_seconds": self.spec.interval_seconds,
            "duration_seconds": self.spec.duration_seconds,
            "warmup_seconds": self.spec.warmup_seconds,
            "baseline_session_id": self.spec.baseline_session_id,
            "notes": self.spec.notes,
            "created_at": self.spec.created_at,
            "started_at": datetime.fromtimestamp(self.started_ms / 1000).astimezone().isoformat(timespec="seconds"),
            "sample_counts": self._counts,
        }
        payload.update(extra)
        target = self.path / "session.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(target)

    def append(self, reading: Reading) -> Path:
        board_id = safe_name(reading.board_id)
        lock = self._locks.setdefault(board_id, threading.RLock())
        path = self.path / f"{board_id}_Readings.csv"
        sensor_values = {
            f"{name}{sensor.label}": round(float(sensor.value), 6)
            for name, sensor in reading.sensors.items()
        }
        row: Dict[str, Any] = {
            "Timestamp": reading.timestamp,
            "Elapsed_seconds": round((reading.timestamp_ms - self.started_ms) / 1000, 3),
            "Flowrate (L/min)": self.spec.flowrate,
            "Battery (%)": reading.battery_percent,
            "Battery (V)": reading.battery_volts,
            **sensor_values,
        }
        with lock:
            header = self._headers.get(board_id)
            if header is None:
                header = self._read_header(path) or list(row)
            new_columns = [column for column in row if column not in header]
            if new_columns:
                header = header + new_columns
                if path.exists() and path.stat().st_size:
                    self._expand_existing_csv(path, header)
            self._headers[board_id] = header
            is_new = not path.exists() or path.stat().st_size == 0
            with path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
                if is_new:
                    writer.writeheader()
                writer.writerow(row)
            self._counts[reading.board_id] = self._counts.get(reading.board_id, 0) + 1
        return path

    @staticmethod
    def _read_header(path: Path) -> Optional[List[str]]:
        if not path.exists() or path.stat().st_size == 0:
            return None
        with path.open("r", newline="", encoding="utf-8") as handle:
            return next(csv.reader(handle), None)

    @staticmethod
    def _expand_existing_csv(path: Path, header: List[str]) -> None:
        with path.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        temporary = path.with_suffix(".csv.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)

    def complete(self, status: str = "completed") -> None:
        summary = self.calculate_statistics()
        if summary:
            (self.path / "summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        self._write_metadata(
            status,
            ended_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            summary_file="summary.json" if summary else None,
        )

    def calculate_statistics(self) -> Dict[str, Any]:
        output: Dict[str, Any] = {}
        for path in sorted(self.path.glob("*_Readings.csv")):
            board_id = path.name.replace("_Readings.csv", "")
            with path.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            sensors: Dict[str, Dict[str, Any]] = {}
            for column in (rows[0].keys() if rows else []):
                if column in BASE_COLUMNS:
                    continue
                values = [_number(row.get(column)) for row in rows]
                numeric = [value for value in values if value is not None]
                if not numeric:
                    continue
                sensors[column] = {
                    "mean": round(statistics.fmean(numeric), 6),
                    "median": round(statistics.median(numeric), 6),
                    "min": min(numeric),
                    "max": max(numeric),
                    "stdev": round(statistics.stdev(numeric), 6) if len(numeric) > 1 else 0.0,
                    "sample_count": len(numeric),
                    "missing_percent": round((len(rows) - len(numeric)) * 100 / len(rows), 2) if rows else 0,
                }
            output[board_id] = {"sample_count": len(rows), "sensors": sensors}
        return output


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def discover_sessions(data_root: Path) -> List[Dict[str, Any]]:
    sessions: List[Dict[str, Any]] = []
    root = Path(data_root)
    if not root.exists():
        return sessions
    for metadata_path in root.glob("*/*/*/session.json"):
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sessions.append(
            {
                "session_id": meta.get("session_id", metadata_path.parent.name),
                "type": meta.get("capture_type", "experiment"),
                "stage": meta.get("stage", ""),
                "substance": meta.get("substance", ""),
                "status": meta.get("status", "unknown"),
                "boards": ", ".join(meta.get("selected_boards", [])),
                "created": meta.get("created_at", ""),
                "path": str(metadata_path.parent),
            }
        )
    return sorted(sessions, key=lambda item: item["created"], reverse=True)


def discover_legacy_csvs(legacy_root: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for stage in ("Testing", "Experiment", "Deployment", "Baseline"):
        folder = Path(legacy_root) / stage
        if not folder.exists():
            continue
        for path in folder.rglob("*_Readings.csv"):
            rows.append({"stage": stage, "file": path.name, "path": str(path)})
    return rows
