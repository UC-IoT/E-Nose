from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from .models import Reading, SensorValue


PAIR_RE = re.compile(
    r"^\s*([^:]+?)\s*:\s*([-+]?[0-9]*\.?[0-9]+)\s*(\S+)?\s*$"
)
BATTERY_RE = re.compile(
    r"Battery\s+Level\s*:\s*(\d+(?:\.\d+)?)\s*%\s*\|\s*Battery\s*\(Volts\)\s*:\s*([-+]?[0-9]*\.?[0-9]+)",
    re.IGNORECASE,
)


def _unit(value: str) -> str:
    cleaned = value.replace("Â", "").replace("μ", "µ").strip()
    lowered = cleaned.lower()
    if "g/m" in lowered:
        return "ug/m3"
    if lowered in {"°c", "c"}:
        return "C"
    return cleaned


class StreamParser(ABC):
    def __init__(self, board_id: str):
        self.board_id = board_id

    @abstractmethod
    def feed(self, line: str) -> Optional[Reading]:
        raise NotImplementedError


class JsonLineParser(StreamParser):
    """Parse one JSON object per serial line.

    Values may be numeric, or objects shaped as {"value": 1.2, "unit": "ppm"}.
    Optional top-level keys beginning with '_' carry metadata.
    """

    def feed(self, line: str) -> Optional[Reading]:
        line = line.strip()
        if not line.startswith("{"):
            return None
        try:
            data = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            return None
        sensors: Dict[str, SensorValue] = {}
        for name, item in data.items():
            if str(name).startswith("_"):
                continue
            try:
                if isinstance(item, dict):
                    value = float(item["value"])
                    unit = _unit(str(item.get("unit", "")))
                else:
                    value = float(item)
                    unit = ""
                sensors[str(name).strip()] = SensorValue(value, unit)
            except (KeyError, TypeError, ValueError):
                continue
        if not sensors:
            return None
        return Reading(
            board_id=self.board_id,
            timestamp_ms=int(data.get("_timestamp_ms") or time.time() * 1000),
            sensors=sensors,
            battery_percent=_float_or_none(data.get("_battery_percent")),
            battery_volts=_float_or_none(data.get("_battery_volts")),
            raw=line,
        )


class FramedKeyValueParser(StreamParser):
    """Parse legacy `new data` / `*` blocks of key-value sensor lines."""

    def __init__(self, board_id: str, accept_separator_end: bool = False):
        super().__init__(board_id)
        self.in_block = False
        self.buffer: List[str] = []
        self.battery: Tuple[Optional[float], Optional[float]] = (None, None)
        self.accept_separator_end = accept_separator_end

    def feed(self, line: str) -> Optional[Reading]:
        clean = line.replace("Â", "").strip()
        if not clean:
            return None
        battery = BATTERY_RE.search(clean)
        if battery:
            self.battery = (float(battery.group(1)), float(battery.group(2)))
            return None
        # Waspmote firmware prints "New Data..." while older Arduino
        # firmware prints "new data". Accept punctuation after the marker.
        if re.match(r"^new\s+data\b[^\w]*$", clean, re.IGNORECASE):
            reading = self._emit() if self.buffer else None
            self.in_block = True
            return reading
        is_end = clean.startswith("*") or (
            self.accept_separator_end and clean.startswith("====")
        )
        if is_end and self.in_block:
            return self._emit()
        if self.in_block:
            self.buffer.append(clean)
        return None

    def _emit(self) -> Optional[Reading]:
        lines, self.buffer, self.in_block = self.buffer, [], False
        sensors: Dict[str, SensorValue] = {}
        for line in lines:
            match = PAIR_RE.match(line)
            if not match:
                continue
            try:
                sensors[match.group(1).strip()] = SensorValue(
                    float(match.group(2)), _unit(match.group(3) or "")
                )
            except ValueError:
                continue
        if not sensors:
            return None
        return Reading(
            board_id=self.board_id,
            timestamp_ms=int(time.time() * 1000),
            sensors=sensors,
            battery_percent=self.battery[0],
            battery_volts=self.battery[1],
            raw="\n".join(lines),
        )


class LibeliumParser(FramedKeyValueParser):
    def __init__(self, board_id: str):
        super().__init__(board_id)
        self.expected_sensors = {
            "LB1": {"NO", "CO", "NO2", "NH3"},
            "LB2": {"SO2", "O3", "H2S", "O2", "CH4"},
        }.get(board_id.upper(), set())

    def feed(self, line: str) -> Optional[Reading]:
        reading = super().feed(line)
        if reading is not None or not self.in_block or not self.expected_sensors:
            return reading
        names = {
            match.group(1).strip()
            for buffered in self.buffer
            if (match := PAIR_RE.match(buffered)) is not None
        }
        return self._emit() if self.expected_sensors.issubset(names) else None


class SectionedReportParser(StreamParser):
    """Parse Board3's human-readable report ending in a line of equals signs."""

    def __init__(self, board_id: str):
        super().__init__(board_id)
        self.in_block = False
        self.buffer: List[str] = []

    def feed(self, line: str) -> Optional[Reading]:
        clean = line.replace("Â", "").strip()
        if not clean:
            return None
        # Firmware variants use different separator widths.
        if re.fullmatch(r"-{5,}", clean):
            self.in_block = True
            return None
        if re.fullmatch(r"={5,}", clean):
            return self._emit() if self.in_block else None
        # Some sketches omit the first dashed separator.
        if clean.startswith("[") and clean.endswith("]"):
            self.in_block = True
            self.buffer.append(clean)
            return None
        if self.in_block:
            self.buffer.append(clean)
        return None

    def _emit(self) -> Optional[Reading]:
        lines, self.buffer, self.in_block = self.buffer, [], False
        sensors: Dict[str, SensorValue] = {}
        for line in lines:
            match = PAIR_RE.match(line)
            if not match:
                continue
            try:
                label = re.sub(r"\s+", " ", match.group(1)).strip()
                sensors[label] = SensorValue(float(match.group(2)), _unit(match.group(3) or ""))
            except ValueError:
                continue
        if not sensors:
            return None
        return Reading(
            board_id=self.board_id,
            timestamp_ms=int(time.time() * 1000),
            sensors=sensors,
            raw="\n".join(lines),
        )


class Board3AutoParser(StreamParser):
    """Accept both the currently flashed Board3 report and V2 JSON-line output."""

    def __init__(self, board_id: str):
        super().__init__(board_id)
        self.json_parser = JsonLineParser(board_id)
        self.report_parser = SectionedReportParser(board_id)

    def feed(self, line: str) -> Optional[Reading]:
        if line.lstrip().startswith("{"):
            return self.json_parser.feed(line)
        return self.report_parser.feed(line)


def make_parser(parser_name: str, board_id: str) -> StreamParser:
    if parser_name == "json_line":
        return JsonLineParser(board_id)
    if parser_name == "libelium":
        return LibeliumParser(board_id)
    if parser_name == "framed_key_value":
        return FramedKeyValueParser(board_id)
    if parser_name == "sectioned_report":
        return SectionedReportParser(board_id)
    if parser_name == "board3_auto":
        return Board3AutoParser(board_id)
    raise ValueError(f"Unsupported parser: {parser_name}")


def _float_or_none(value: object) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
