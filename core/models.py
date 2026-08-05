from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import math
from typing import Any, Dict, Optional


FIREBASE_KEY_TRANSLATION = str.maketrans({
    ".": "．",
    "$": "＄",
    "#": "＃",
    "[": "［",
    "]": "］",
    "/": "∕",
})


def firebase_safe_key(value: Any) -> str:
    """Preserve readable labels while replacing Firebase-forbidden key characters."""
    text = str(value).translate(FIREBASE_KEY_TRANSLATION)
    text = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in text)
    return text or "_"


def minutes_to_seconds(value: Any) -> int:
    """Convert a positive minute value to seconds without silent fallbacks."""
    if value is None or isinstance(value, bool):
        raise ValueError("Enter a capture duration in minutes")
    try:
        minutes = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Duration must be a number of minutes") from exc
    if not math.isfinite(minutes) or minutes <= 0:
        raise ValueError("Duration must be greater than 0 minutes")
    return max(1, int(round(minutes * 60)))


@dataclass(frozen=True)
class SensorValue:
    value: float
    unit: str = ""

    @property
    def label(self) -> str:
        return f" ({self.unit})" if self.unit else ""


@dataclass
class Reading:
    board_id: str
    timestamp_ms: int
    sensors: Dict[str, SensorValue]
    battery_percent: Optional[float] = None
    battery_volts: Optional[float] = None
    raw: str = ""

    @property
    def timestamp(self) -> str:
        return datetime.fromtimestamp(self.timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

    def firebase_payload(self) -> Dict[str, Any]:
        readings: Dict[str, float] = {}
        sensor_labels: Dict[str, str] = {}
        for name, sensor in self.sensors.items():
            original = f"{name}{sensor.label}"
            safe = firebase_safe_key(original)
            readings[safe] = round(float(sensor.value), 6)
            if safe != original:
                sensor_labels[safe] = original
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(self.timestamp_ms / 1000).strftime("%H-%M-%S %d-%m-%Y"),
            "timestamp_ms": self.timestamp_ms,
            "readings": readings,
        }
        if sensor_labels:
            payload["sensor_labels"] = sensor_labels
        if self.battery_percent is not None or self.battery_volts is not None:
            payload["battery"] = {
                "percent": self.battery_percent,
                "volts": self.battery_volts,
            }
        return payload

    def serializable(self) -> Dict[str, Any]:
        result = asdict(self)
        result["timestamp"] = self.timestamp
        return result


@dataclass
class SessionSpec:
    stage: str
    substance: str
    session_id: str
    selected_boards: Dict[str, str]
    flowrate: float
    interval_seconds: float
    duration_seconds: int
    capture_type: str = "experiment"
    baseline_session_id: Optional[str] = None
    notes: str = ""
    warmup_seconds: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
