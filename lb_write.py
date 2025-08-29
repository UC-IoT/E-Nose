#lb_write.py
import os, re, time, csv, threading, json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import serial

class _FirebaseGate:
    def __init__(self):
        self.ready = False
        self.disabled_reason = None
        self._seq_cache: Dict[str, int] = {}  # "<stage>/<sub>/<test>/<L?>/readings"
        self._errors = 0
        self._max_errors = 3

    def disable(self, reason: str):
        self.ready = False
        self.disabled_reason = reason

    def init(self):
        if self.ready or self.disabled_reason:
            return
        try:
            import firebase_admin  
            from firebase_admin import credentials  
            if getattr(firebase_admin, "_apps", None):
                self.ready = True
                return

            db_url = os.getenv("DATABASE_URL") or os.getenv("databaseURL")
            if not db_url:
                self.disable("DATABASE_URL missing")
                return

            key_env = os.getenv("FIREBASE_KEY")
            if key_env:
                svc = json.loads(key_env)
                if isinstance(svc.get("private_key"), str):
                    svc["private_key"] = svc["private_key"].replace("\\n", "\n")
                cred = credentials.Certificate(svc)
            else:
                path = (
                    os.getenv("FIREBASE_CREDENTIALS_PATH")
                    or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                    or "serviceAccountKey.json"
                )
                cred = credentials.Certificate(path)

            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
            self.ready = True
        except Exception as e:
            self.disable(f"init error: {e}")

    def _with_db(self, fn) -> bool:
        if not self.ready or self.disabled_reason:
            return False
        try:
            from firebase_admin import db  
            fn(db)
            return True
        except Exception as e:
            self._errors += 1
            if self._errors >= self._max_errors:
                self.disable(f"write error: {e}")
            return False

    def _seq_path(self, stage:str, sub:str, test_id:str, board:str)->str:
        fb_board = "L1" if board.upper()=="LB1" else "L2"
        return f"{stage}/{sub}/{test_id}/{fb_board}/readings"

    def load_seq_if_needed(self, stage: str, substance: str, test_id: str, boards: List[str]):
        if not self.ready or self.disabled_reason:
            for b in boards:
                self._seq_cache[self._seq_path(stage, substance, test_id, b)] = 1
            return

        def _op(db):
            base = f"{stage}/{substance}/{test_id}"
            for b in boards:
                fb_board = "L1" if b.upper()=="LB1" else "L2"
                path = f"{base}/{fb_board}/readings"
                snap = db.reference(path).get()
                if isinstance(snap, dict) and snap:
                    try:
                        mx = max(int(k) for k in snap.keys() if str(k).isdigit())
                    except ValueError:
                        mx = 0
                else:
                    mx = 0
                self._seq_cache[path] = mx + 1

        self._with_db(_op)

    def put_reading(self, stage: str, substance: str, test_id: str,
                    board_id: str, ts_epoch: float, readings: Dict[str, float],
                    batt_pct: Optional[float], batt_v: Optional[float]):
        path = self._seq_path(stage, substance, test_id, board_id)
        n = self._seq_cache.get(path, 1)
        ts_label = datetime.fromtimestamp(ts_epoch).strftime("%H-%M-%S %d-%m-%Y")
        payload = {"timestamp": ts_label, "readings": readings}
        if batt_pct is not None or batt_v is not None:
            payload["battery"] = {
                "percent": None if batt_pct is None else float(batt_pct),
                "volts": None if batt_v is None else float(batt_v),
            }

        def _op(db):
            db.reference(f"{path}/{n}").set(payload)

        ok = self._with_db(_op)
        if ok or not self.ready or self.disabled_reason:
            self._seq_cache[path] = n + 1

_FB = _FirebaseGate()

# ===== Config / naming =====
PREFIX_MAP = {"Testing": "T", "Experiment": "E", "Deployment": "D", "Baseline": "B"}
BAUD_LIBELIUM = 115200
SER_TIMEOUT = 1.0

EXPECTED_SENSORS: Dict[str, List[str]] = {
    "LB1": ["SO2", "NO2", "H2S", "CH4"],
    "LB2": ["NO", "CO", "NO2", "NH3", "O2"],
}
DEFAULT_UNIT = {"O2": "%"}  

# ===== Public state =====
STATE = {
    "active": False,
    "stage": None,
    "substance": None,
    "test_id": None,
    "flowrate": None,
    "interval": 1.0,
    "duration_sec": None,
    "folder": None,
    "per_board_status": {},  
}

_LOCK = threading.Lock()
_THREADS: Dict[str, "LBSerialReader"] = {}
_STOP_EVENT = threading.Event()

_LAST_BATT: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
_CUM_PATHS: Dict[str, str] = {}
_CUM_HEADERS: Dict[str, List[str]] = {}

NEW_DATA_RE = re.compile(r"^\s*new\s*data\s*$", re.IGNORECASE)
PAIR_RE = re.compile(r"^\s*([A-Za-z0-9µμ°/%\-\s\(\)\.\[\]]+?)\s*:\s*([\-+]?[0-9]*\.?\d+)\s*([A-Za-z°%/\.]+)?\s*$")
BAT_RE  = re.compile(r"Battery\s+Level\s*:\s*(\d+)\s*%\s*\|\s*Battery\s*\(Volts\)\s*:\s*([\-+]?[0-9]*\.?\d+)")

def _fmt(v): return round(v,3) if isinstance(v,float) else v
def _canon_unit(g: str, u: Optional[str])->str: return ("°C" if u=="C" else (u or DEFAULT_UNIT.get(g.upper(),"ppm")))
def _clean_ascii(s: str)->str: return re.sub(r"[^\x20-\x7E\n\r\t]","",s)

def _make_paths(stage:str, substance:str, board_id:str):
    folder = os.path.join("Baseline","baseline") if stage=="Baseline" else os.path.join(stage, substance)
    os.makedirs(folder, exist_ok=True)
    return folder, os.path.join(folder, f"{('baseline' if stage=='Baseline' else substance)}_{board_id}_Readings.csv")

def _row_base(ts: str, flow: float)->Dict[str, Optional[float]]:
    return {"Timestamp": ts, "Flowrate (L/min)": _fmt(flow)}

class LBSerialReader(threading.Thread):
    daemon = True
    def __init__(self, board_id: str, port: str, interval_s: float):
        super().__init__(name=f"{board_id}-LB-reader")
        self.board_id = board_id; self.port = port; self.interval_s = interval_s
        self.stop_flag = threading.Event(); self.ser: Optional[serial.Serial] = None
        self._buffer: List[str] = []; self._in_block = False

    def stop(self): self.stop_flag.set()

    def run(self):
        STATE["per_board_status"][self.board_id] = "starting"
        try:
            self.ser = serial.Serial(self.port, BAUD_LIBELIUM, timeout=SER_TIMEOUT)
            time.sleep(0.6); STATE["per_board_status"][self.board_id] = "listening"
        except Exception as e:
            STATE["per_board_status"][self.board_id] = f"error open: {e}"; return

        while not self.stop_flag.is_set() and not _STOP_EVENT.is_set():
            try:
                raw = self.ser.readline().decode(errors="ignore")
            except Exception:
                time.sleep(0.2); continue

            line = _clean_ascii(raw).strip()
            if not line: continue

            mb = BAT_RE.search(line)
            if mb:
                try:
                    pct = float(mb.group(1)); v = float(mb.group(2))
                    with _LOCK: _LAST_BATT[self.board_id] = (pct, v)
                except ValueError: pass
                continue

            if NEW_DATA_RE.match(line):
                if self._buffer:
                    self._emit_block(self._buffer); self._buffer=[]
                    time.sleep(self.interval_s)
                self._in_block = True; STATE["per_board_status"][self.board_id] = "capturing"; continue

            if self._in_block:
                self._buffer.append(line)

        try:
            if self.ser: self.ser.close()
        except Exception: pass
        if self._buffer: self._emit_block(self._buffer)

    def _ensure_writer_ready(self, header_cols: List[str]):
        if self.board_id in _CUM_HEADERS: return
        folder, cum_csv = _make_paths(STATE["stage"], STATE["substance"], self.board_id)
        _CUM_PATHS[self.board_id] = cum_csv
        need_header = (not os.path.exists(cum_csv)) or os.path.getsize(cum_csv)==0
        if need_header:
            with open(cum_csv,"a",newline="",encoding="utf-8") as fh:
                csv.DictWriter(fh, fieldnames=header_cols).writeheader()
        _CUM_HEADERS[self.board_id] = header_cols

    def _emit_block(self, lines: List[str]):
        gases: Dict[str, Tuple[float,str]] = {}
        for ln in lines:
            m = PAIR_RE.match(ln)
            if not m: continue
            label, num, unit = m.group(1).strip(), m.group(2), (m.group(3) or "").strip()
            try: val = float(num)
            except ValueError: continue
            gas = label.upper(); unit_final = _canon_unit(gas, unit)
            gases[gas] = (val, unit_final)

        if not gases and self.board_id not in _LAST_BATT: return

        ts_epoch = time.time()
        ts_str = datetime.fromtimestamp(ts_epoch).strftime("%Y-%m-%d %H:%M:%S")

        row = _row_base(ts_str, float(STATE["flowrate"]))
        with _LOCK: pct, volts = _LAST_BATT.get(self.board_id, (None, None))
        row[f"{self.board_id} - Battery (%)"] = _fmt(pct) if pct is not None else None
        row[f"{self.board_id} - Battery (V)"] = _fmt(volts) if volts is not None else None

        readings_fb: Dict[str,float] = {}
        for gas,(val,unit) in gases.items():
            col = f"{self.board_id} - {gas} ({unit})"
            row[col] = _fmt(val); readings_fb[f"{gas} ({unit})"] = _fmt(val)

        header_cols = list(row.keys())
        self._ensure_writer_ready(header_cols)
        cum_csv = _CUM_PATHS[self.board_id]
        try:
            with open(cum_csv,"a",newline="",encoding="utf-8") as fh:
                csv.DictWriter(fh, fieldnames=_CUM_HEADERS[self.board_id]).writerow(row)
        except PermissionError:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            alt = os.path.splitext(cum_csv)[0] + f"_pending_{stamp}.csv"
            with open(alt,"a",newline="",encoding="utf-8") as fh:
                cw = csv.DictWriter(fh, fieldnames=_CUM_HEADERS[self.board_id])
                if os.path.getsize(alt)==0: cw.writeheader()
                cw.writerow(row)

        # Firebase numbered write
        _FB.put_reading(STATE["stage"], STATE["substance"], STATE["test_id"] or "",
                        self.board_id, ts_epoch, readings_fb, pct, volts)
        if _FB.disabled_reason:
            STATE["per_board_status"]["Firebase"] = f"offline ({_FB.disabled_reason})"

# ===== Public API =====
def start_capture(stage: str, substance: Optional[str], test_id: str,
                  flowrate: float, interval: float, ports: Dict[str, Optional[str]],
                  duration_sec: Optional[int] = None):
    stop_capture(); _STOP_EVENT.clear()
    with _LOCK:
        STATE.update({
            "active": True, "stage": stage,
            "substance": "baseline" if stage=="Baseline" else (substance or "").title(),
            "test_id": test_id, "flowrate": float(flowrate),
            "interval": float(interval), "duration_sec": int(duration_sec) if duration_sec else None,
            "folder": None, "per_board_status": {},
        })
        _LAST_BATT.clear(); _CUM_PATHS.clear(); _CUM_HEADERS.clear()

    for b,p in ports.items():
        if not p: continue
        STATE["per_board_status"][b] = "idle"
        r = LBSerialReader(b,p,float(interval)); _THREADS[b]=r; r.start()

    # Firebase: attempt init & prime counters
    _FB.init()
    if _FB.ready:
        STATE["per_board_status"]["Firebase"] = "online"
        _FB.load_seq_if_needed(STATE["stage"], STATE["substance"], STATE["test_id"] or "",
                               [b for b,p in ports.items() if p])
    else:
        STATE["per_board_status"]["Firebase"] = f"offline ({_FB.disabled_reason})"

    if duration_sec and duration_sec>0:
        def _auto():
            t0=time.time()
            while time.time()-t0<duration_sec and not _STOP_EVENT.is_set(): time.sleep(0.25)
            if not _STOP_EVENT.is_set(): stop_capture()
        threading.Thread(target=_auto, daemon=True).start()

def stop_capture():
    _STOP_EVENT.set()
    for r in list(_THREADS.values()):
        try: r.stop(); r.join(timeout=2.0)
        except Exception: pass
    _THREADS.clear()
    with _LOCK: STATE["active"]=False

def snapshot():
    lines=[]
    with _LOCK:
        for b,st in STATE.get("per_board_status",{}).items(): lines.append(f"{b}: {st}")
        for b in ("LB1","LB2"):
            if b in _CUM_PATHS: lines.append(f"Cumulative ({b}): {_CUM_PATHS[b]}")
        if STATE.get("test_id"): lines.append(f"Firebase test_id: {STATE['test_id']}")
    return {"status_lines": lines}
