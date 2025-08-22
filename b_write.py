
import os, re, time, csv, threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import serial

PREFIX_MAP = {"Testing": "T", "Experiment": "E", "Deployment": "D", "Baseline": "B"}
BAUD_ARDUINO_DEFAULT = 9600

# ===== Public state for UI =====
STATE = {
    "active": False,
    "first_read_epoch": None,       
    "duration_sec": 0,              
    "stage": None,
    "substance": None,
    "flowrate": None,
    "interval": 1.0,
    "session_csv": None,
    "cumulative_csv": None,
    "folder": None,
    "per_board_status": {},         
}

# Trackers
_THREADS: Dict[str, "BSerialReader"] = {}
_LATEST_BLOCKS: Dict[str, Dict[str, Tuple[float, Optional[str]]]] = {}

PAIR_RE = re.compile(r"^\s*([A-Za-z0-9µμ°/%\-\s\(\)\.\[\]]+?)\s*:\s*([\-+]?[0-9]*\.?[0-9]+)\s*([A-Za-z°%/\.]+)?\s*$")
NEW_DATA_RE = re.compile(r"^\s*new\s*data\s*$", re.IGNORECASE)

def _clean_ascii(s: str) -> str:
    return re.sub(r"[^\x20-\x7E\n\r\t]", "", s)

def _fmt(v):
    if isinstance(v, float):
        return round(v, 3)
    return v

def _make_paths(stage: str, substance: Optional[str]):
    prefix = PREFIX_MAP.get(stage, "X")
    if stage == "Baseline":
        folder = os.path.join("Baseline", "baseline")
        sub = "baseline"
    else:
        sub = (substance or "").title()
        folder = os.path.join(stage, sub)
    os.makedirs(folder, exist_ok=True)

    run_no = len([f for f in os.listdir(folder) if f.lower().endswith(".csv") and f.lower().startswith((prefix + sub).lower())]) + 1
    session_name = f"{prefix}{sub}{run_no:04d}"
    return {
        "folder": folder,
        "session_csv": os.path.join(folder, f"{session_name}_B.csv"),
        "cumulative_csv": os.path.join(folder, f"{sub}_B_Readings.csv"),
    }

def _parse_line(line: str):
    m = PAIR_RE.match(line)
    if not m:
        return None
    label, val, unit = m.group(1).strip(), m.group(2), m.group(3)
    try:
        f = float(val)
    except ValueError:
        return None
    unit = unit.strip() if unit else None
    if unit == "C":
        unit = "°C"
    return label, f, unit

class BSerialReader(threading.Thread):
    daemon = True
    def __init__(self, board_id: str, port: str, interval_s: float):
        super().__init__(name=f"{board_id}-B-reader")
        self.board_id = board_id
        self.port = port
        self.interval_s = interval_s
        self.stop_flag = threading.Event()
        self.ser: Optional[serial.Serial] = None

    def stop(self):
        self.stop_flag.set()

    def run(self):
        STATE["per_board_status"][self.board_id] = "starting"
        try:
            self.ser = serial.Serial(self.port, BAUD_ARDUINO_DEFAULT, timeout=1)
            time.sleep(1.0)
            STATE["per_board_status"][self.board_id] = "listening"
        except Exception as e:
            STATE["per_board_status"][self.board_id] = f"error open: {e}"
            return

        buffer: List[str] = []
        in_block = False

        while not self.stop_flag.is_set():
            try:
                raw = self.ser.readline().decode(errors="ignore")
            except Exception:
                time.sleep(0.25)
                continue

            line = _clean_ascii(raw).strip()
            if not line:
                continue

            if NEW_DATA_RE.match(line):
                if buffer:
                    self._emit_block(buffer)
                    buffer = []
                    time.sleep(self.interval_s)
                in_block = True
                continue

            if in_block:
                if line.startswith("*"):
                    self._emit_block(buffer)
                    buffer = []
                    in_block = False
                    time.sleep(self.interval_s)
                    continue
                buffer.append(line)

        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass

    def _emit_block(self, lines: List[str]):
        parsed: Dict[str, Tuple[float, Optional[str]]] = {}
        for ln in lines:
            tup = _parse_line(ln)
            if tup:
                label, val, unit = tup
                parsed[label] = (val, unit)
        if not parsed:
            return
        parsed["_captured_at_"] = (time.time(), None)
        _LATEST_BLOCKS[self.board_id] = parsed

        if STATE["first_read_epoch"] is None:
            STATE["first_read_epoch"] = parsed["_captured_at_"][0]
        STATE["per_board_status"][self.board_id] = "capturing"

# === CSV writer thread ===
class BWriter(threading.Thread):
    daemon = True
    def __init__(self):
        super().__init__(name="B-Writer")
        self.stop_flag = threading.Event()
        self.header: Optional[List[str]] = None
        self.session_fh = None
        self.session_writer = None

    def stop(self):
        self.stop_flag.set()

    def run(self):
        paths = _make_paths(STATE["stage"], STATE["substance"])
        STATE["folder"] = paths["folder"]
        STATE["session_csv"] = paths["session_csv"]
        STATE["cumulative_csv"] = paths["cumulative_csv"]

        enabled = [b for b in STATE["per_board_status"].keys() if b in ("B1", "B2")]
        while not self.stop_flag.is_set():
            if any(b in _LATEST_BLOCKS for b in enabled):
                break
            time.sleep(0.1)

        if self.stop_flag.is_set():
            return

        # Build header
        cols = ["Timestamp", "Flowrate (L/min)"]
        
        seen: Dict[str, None] = {}
        for b in enabled:
            blk = _LATEST_BLOCKS.get(b, {})
            for k, (_v, unit) in blk.items():
                if k == "_captured_at_":
                    continue
                unit_sfx = f" ({unit})" if unit else ""
                colname = f"{b} - {k}{unit_sfx}"
                seen[colname] = None
        cols.extend(sorted(seen.keys(), key=str.lower))
        self.header = cols


        os.makedirs(os.path.dirname(STATE["session_csv"]), exist_ok=True)
        self.session_fh = open(STATE["session_csv"], "w", newline="", encoding="utf-8")
        self.session_writer = csv.writer(self.session_fh)
        self.session_writer.writerow(self.header)
        self.session_fh.flush()

        # write loop
        while not self.stop_flag.is_set():

            fresh_blocks = [(_LATEST_BLOCKS[b]["_captured_at_"][0], b)
                            for b in enabled if b in _LATEST_BLOCKS]
            if not fresh_blocks:
                time.sleep(0.05)
                continue
            ts_epoch = max(t for t, _ in fresh_blocks)
            ts = datetime.fromtimestamp(ts_epoch).strftime("%Y-%m-%d %H:%M:%S")

            row = [ts, _fmt(STATE["flowrate"])]
            for c in self.header[2:]:
                try:
                    b, rest = c.split(" - ", 1)
                except ValueError:
                    row.append(None)
                    continue
                src = _LATEST_BLOCKS.get(b, {})

                val = None
                for k, (v, unit) in src.items():
                    if k == "_captured_at_": 
                        continue
                    unit_sfx = f" ({unit})" if unit else ""
                    formed = f"{b} - {k}{unit_sfx}"
                    if formed == c:
                        val = v
                        break
                row.append(_fmt(val) if val is not None else None)

            # write session and cumulative
            self.session_writer.writerow(row)
            self.session_fh.flush()

            write_header = not os.path.exists(STATE["cumulative_csv"]) or os.path.getsize(STATE["cumulative_csv"]) == 0
            with open(STATE["cumulative_csv"], "a", newline="", encoding="utf-8") as cumfh:
                cw = csv.writer(cumfh)
                if write_header:
                    cw.writerow(self.header)
                cw.writerow(row)

            time.sleep(STATE["interval"])

        try:
            if self.session_fh:
                self.session_fh.close()
        except Exception:
            pass


# ===== Public API =====

_WRITER_THREAD: Optional[BWriter] = None

def start_capture(stage: str, substance: Optional[str], flowrate: float, duration_sec: int,
                  interval: float, ports: Dict[str, Optional[str]]):
    """
    ports: {"B1": "COM3", "B2": "COM8"} (None to skip)
    """
    stop_capture()
    STATE.update({
        "active": True,
        "first_read_epoch": None,
        "duration_sec": duration_sec,
        "stage": stage,
        "substance": None if stage == "Baseline" else (substance or "").title(),
        "flowrate": flowrate,
        "interval": interval,
        "session_csv": None,
        "cumulative_csv": None,
        "folder": None,
        "per_board_status": {k: "idle" for k in ("B1", "B2") if ports.get(k)},
    })
    _LATEST_BLOCKS.clear()

    # readers
    for b, p in ports.items():
        if p:
            r = BSerialReader(b, p, interval)
            _THREADS[b] = r
            r.start()

    # writer
    global _WRITER_THREAD
    _WRITER_THREAD = BWriter()
    _WRITER_THREAD.start()

def stop_capture():
    for r in list(_THREADS.values()):
        r.stop()
    for r in list(_THREADS.values()):
        r.join(timeout=2.0)
    _THREADS.clear()

    global _WRITER_THREAD
    if _WRITER_THREAD:
        _WRITER_THREAD.stop()
        _WRITER_THREAD.join(timeout=2.0)
        _WRITER_THREAD = None
    STATE["active"] = False

def snapshot():
    """
    Returns a dict:
      {
        "first_read_epoch": float|None,
        "pct": int,
        "paths": {"session_csv":..., "cumulative_csv":..., "folder":...},
        "status_lines": [..]
      }
    """
    pct = 0
    if STATE["first_read_epoch"] is not None and STATE["duration_sec"] > 0:
        elapsed = time.time() - STATE["first_read_epoch"]
        pct = int(max(0, min(100, (elapsed / STATE["duration_sec"]) * 100)))

    lines = []
    for b, st in STATE["per_board_status"].items():
        lines.append(f"{b}: {st}")
    if STATE.get("session_csv"):
        lines.append(f"Session CSV (B): {STATE['session_csv']}")
        lines.append(f"Cumulative (B): {STATE['cumulative_csv']}")

    return {
        "first_read_epoch": STATE["first_read_epoch"],
        "pct": pct,
        "paths": {
            "session_csv": STATE.get("session_csv"),
            "cumulative_csv": STATE.get("cumulative_csv"),
            "folder": STATE.get("folder"),
        },
        "status_lines": lines
    }
