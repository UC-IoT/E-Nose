
import os, re, time, csv, threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import serial

# ===== Config / naming =====
PREFIX_MAP = {"Testing": "T", "Experiment": "E", "Deployment": "D", "Baseline": "B"}
BAUD_LIBELIUM = 115200
SER_TIMEOUT = 1.0

# Sensors per board (edit if firmware changes)
EXPECTED_SENSORS: Dict[str, List[str]] = {
    "LB1": ["SO2", "NO2", "H2S", "CH4"],
    "LB2": ["NO", "CO", "NO2", "NH3", "O2"],
}

# Default unit 
DEFAULT_UNIT = {"O2": "%"}  

# ===== Public state for UI =====
STATE = {
    "active": False,
    "stage": None,
    "substance": None,
    "flowrate": None,
    "interval": 1.0,
    "duration_sec": None,
    "folder": None,
    "session_csv": None,
    "cumulative_csv": None,
    "per_board_status": {},    
}

# ===== Internals =====
_LOCK = threading.Lock()
_THREADS: Dict[str, "LBSerialReader"] = {}
_STOP_EVENT = threading.Event()

# Latest battery snapshot per board
_LAST_BATT: Dict[str, Tuple[Optional[float], Optional[float]]] = {}


_HEADER: List[str] = []
_ROWS: List[Dict[str, Optional[float]]] = []

_LAST_TS_BY_BOARD: Dict[str, str] = {}

# ===== Regexes =====
NEW_DATA_RE = re.compile(r"^\s*new\s*data\s*$", re.IGNORECASE)
PAIR_RE = re.compile(r"^\s*([A-Za-z0-9µμ°/%\-\s\(\)\.\[\]]+?)\s*:\s*([\-+]?[0-9]*\.?\d+)\s*([A-Za-z°%/\.]+)?\s*$")
BAT_RE = re.compile(r"Battery\s+Level\s*:\s*(\d+)\s*%\s*\|\s*Battery\s*\(Volts\)\s*:\s*([\-+]?[0-9]*\.?\d+)")

# ===== Helpers =====
def _fmt(v):
    if isinstance(v, float):
        return round(v, 3)
    return v

def _canon_unit(gas: str, unit: Optional[str]) -> str:
    if not unit:
        return DEFAULT_UNIT.get(gas.upper(), "ppm")
    return unit

def _clean_ascii(s: str) -> str:
    return re.sub(r"[^\x20-\x7E\n\r\t]", "", s)

def _make_paths(stage: str, substance: Optional[str]):
    prefix = PREFIX_MAP.get(stage, "X")
    if stage == "Baseline":
        folder = os.path.join("Baseline", "baseline")
        sub = "baseline"
    else:
        sub = (substance or "").title()
        folder = os.path.join(stage, sub)
    os.makedirs(folder, exist_ok=True)
    run_no = len([f for f in os.listdir(folder)
                  if f.lower().endswith(".csv") and f.lower().startswith((prefix + sub).lower())]) + 1
    session_name = f"{prefix}{sub}{run_no:04d}"
    return folder, os.path.join(folder, f"{session_name}_LB.csv"), os.path.join(folder, f"{sub}_LB_Readings.csv")

def _build_header(enabled: List[str]) -> List[str]:
    cols = ["Timestamp", "Flowrate (L/min)"]
    for b in enabled:
        cols += [f"{b} - Battery (%)", f"{b} - Battery (V)"]
        for gas in EXPECTED_SENSORS.get(b, []):
            unit = _canon_unit(gas, None)
            cols.append(f"{b} - {gas.upper()} ({unit})")
    return cols

def _row_base(ts_str: str, flow: float) -> Dict[str, Optional[float]]:
    return {"Timestamp": ts_str, "Flowrate (L/min)": _fmt(flow)}

def _append_row(row: Dict[str, Optional[float]]):
    with _LOCK:
        _ROWS.append(row)

# ===== Serial Reader =====
class LBSerialReader(threading.Thread):
    daemon = True
    def __init__(self, board_id: str, port: str, interval_s: float):
        super().__init__(name=f"{board_id}-LB-reader")
        self.board_id = board_id
        self.port = port
        self.interval_s = interval_s
        self.stop_flag = threading.Event()
        self.ser: Optional[serial.Serial] = None
        self._buffer: List[str] = []
        self._in_block = False

    def stop(self):
        self.stop_flag.set()

    def run(self):
        STATE["per_board_status"][self.board_id] = "starting"
        try:
            self.ser = serial.Serial(self.port, BAUD_LIBELIUM, timeout=SER_TIMEOUT)
            time.sleep(0.6)
            STATE["per_board_status"][self.board_id] = "listening"
        except Exception as e:
            STATE["per_board_status"][self.board_id] = f"error open: {e}"
            return

        while not self.stop_flag.is_set() and not _STOP_EVENT.is_set():
            try:
                raw = self.ser.readline().decode(errors="ignore")
            except Exception:
                time.sleep(0.2)
                continue

            line = _clean_ascii(raw).strip()
            if not line:
                continue

            mb = BAT_RE.search(line)
            if mb:
                try:
                    pct = float(mb.group(1))
                    v = float(mb.group(2))
                    with _LOCK:
                        _LAST_BATT[self.board_id] = (pct, v)
                except ValueError:
                    pass
                continue

            if NEW_DATA_RE.match(line):
                if self._buffer:
                    self._emit_block(self._buffer)
                    self._buffer = []
                    time.sleep(self.interval_s)
                self._in_block = True
                STATE["per_board_status"][self.board_id] = "capturing"
                continue

            if self._in_block:
                self._buffer.append(line)


        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        if self._buffer:
            self._emit_block(self._buffer)

    def _emit_block(self, lines: List[str]):
        gases: Dict[str, Tuple[float, str]] = {}
        for ln in lines:
            m = PAIR_RE.match(ln)
            if not m:
                continue
            label, num, unit = m.group(1).strip(), m.group(2), (m.group(3) or "").strip()
            try:
                val = float(num)
            except ValueError:
                continue
            gas = label.upper()
            unit_final = _canon_unit(gas, unit)
            gases[gas] = (val, unit_final)

        if not gases and self.board_id not in _LAST_BATT:
            return

        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        
        with _LOCK:
            if _LAST_TS_BY_BOARD.get(self.board_id) == ts_str:
                return
            _LAST_TS_BY_BOARD[self.board_id] = ts_str

        row = _row_base(ts_str, float(STATE["flowrate"]))

        # battery
        with _LOCK:
            pct, volts = _LAST_BATT.get(self.board_id, (None, None))
        row[f"{self.board_id} - Battery (%)"] = _fmt(pct) if pct is not None else None
        row[f"{self.board_id} - Battery (V)"] = _fmt(volts) if volts is not None else None

        # gases
        for gas, (val, unit) in gases.items():
            col = f"{self.board_id} - {gas} ({unit})"
            if col in _HEADER:   
                row[col] = _fmt(val)

        _append_row(row)

# ===== File writing =====
def _safe_write_csv(path: str, header: List[str], rows: List[Dict[str, Optional[float]]], mode: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, mode, newline="", encoding="utf-8") as fh:
            cw = csv.writer(fh)
            if mode == "w":
                cw.writerow(header)
            for r in rows:
                cw.writerow([r.get(col) for col in header])
    except PermissionError:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        alt = os.path.splitext(path)[0] + f"_pending_{stamp}.csv"
        with open(alt, "w", newline="", encoding="utf-8") as fh:
            cw = csv.writer(fh)
            cw.writerow(header)
            for r in rows:
                cw.writerow([r.get(col) for col in header])

def _finalise_and_write():
    # Guard: only finalise if we have rows and a valid stage
    if not _ROWS or not STATE.get("stage"):
        return

    folder, session_csv, cumulative_csv = _make_paths(STATE["stage"], STATE["substance"])
    STATE["folder"] = folder
    STATE["session_csv"] = session_csv
    STATE["cumulative_csv"] = cumulative_csv

    with _LOCK:
        header = list(_HEADER)
        rows = [dict(r) for r in _ROWS]

    # Write session 
    _safe_write_csv(session_csv, header, rows, mode="w")

    # Write cumulative 
    if not os.path.exists(cumulative_csv) or os.path.getsize(cumulative_csv) == 0:
        _safe_write_csv(cumulative_csv, header, rows, mode="w")
    else:
        _safe_write_csv(cumulative_csv, header, rows, mode="a")

# ===== Public API =====
def start_capture(stage: str, substance: Optional[str], flowrate: float,
                  interval: float, ports: Dict[str, Optional[str]], duration_sec: Optional[int] = None):
    """
    ports: {"LB1": "COM12", "LB2": "COM13"}  (None to skip)
    duration_sec (optional): auto-finalise after N seconds.
    """
    for r in list(_THREADS.values()):
        try:
            r.stop()
            r.join(timeout=1.0)
        except Exception:
            pass
    _THREADS.clear()
    _STOP_EVENT.clear()

    with _LOCK:
        STATE.update({
            "active": True,
            "stage": stage,
            "substance": None if stage == "Baseline" else (substance or "").title(),
            "flowrate": float(flowrate),
            "interval": float(interval),
            "duration_sec": int(duration_sec) if duration_sec else None,
            "folder": None,
            "session_csv": None,
            "cumulative_csv": None,
            "per_board_status": {},
        })
        enabled = []
        for b in ("LB1", "LB2"):
            if ports.get(b):
                STATE["per_board_status"][b] = "idle"
                enabled.append(b)

        global _HEADER, _ROWS, _LAST_TS_BY_BOARD, _LAST_BATT
        _HEADER = _build_header(enabled)
        _ROWS = []
        _LAST_TS_BY_BOARD = {}
        _LAST_BATT = {b: (None, None) for b in enabled}

    for b, p in ports.items():
        if not p:
            continue
        r = LBSerialReader(b, p, float(interval))
        _THREADS[b] = r
        r.start()

    if duration_sec and duration_sec > 0:
        def _auto():
            t0 = time.time()
            while time.time() - t0 < duration_sec and not _STOP_EVENT.is_set():
                time.sleep(0.25)
            if not _STOP_EVENT.is_set():
                stop_capture()
        threading.Thread(target=_auto, daemon=True).start()

def stop_capture():
    _STOP_EVENT.set()

    for r in list(_THREADS.values()):
        try:
            r.stop()
            r.join(timeout=2.0)
        except Exception:
            pass
    _THREADS.clear()


    try:
        _finalise_and_write()
    finally:
        with _LOCK:
            STATE["active"] = False

def snapshot():
    lines = []
    with _LOCK:
        for b, st in STATE.get("per_board_status", {}).items():
            lines.append(f"{b}: {st}")
        if STATE.get("session_csv"):
            lines.append(f"Session CSV (LB): {STATE['session_csv']}")
            lines.append(f"Cumulative (LB): {STATE['cumulative_csv']}")
        lines.append(f"Buffered rows: {len(_ROWS)}")

        return {
            "paths": {
                "session_csv": STATE.get("session_csv"),
                "cumulative_csv": STATE.get("cumulative_csv"),
                "folder": STATE.get("folder"),
            },
            "status_lines": lines
        }
