#b_write.py
import os, re, time, csv, threading, json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import serial


class _FirebaseGate:
    def __init__(self):
        self.ready = False
        self.disabled_reason = None
        self._seq_cache: Dict[str, int] = {}  # "<stage>/<sub>/<test>/<B?>/readings" -> next int
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
        """Run a db op, returning True on success; on repeated failures go offline."""
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
        return f"{stage}/{sub}/{test_id}/{board}/readings"

    def load_seq_if_needed(self, stage: str, substance: str, test_id: str, boards: List[str]):
        if not self.ready or self.disabled_reason:
            for b in boards:
                self._seq_cache[self._seq_path(stage, substance, test_id, b)] = 1
            return

        def _op(db):
            base = f"{stage}/{substance}/{test_id}"
            for b in boards:
                path = f"{base}/{b}/readings"
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
                    board_id: str, ts_epoch: float, readings: Dict[str, float]):

        path = self._seq_path(stage, substance, test_id, board_id)
        n = self._seq_cache.get(path, 1)
        ts_label = datetime.fromtimestamp(ts_epoch).strftime("%H-%M-%S %d-%m-%Y")

        def _op(db):
            db.reference(f"{path}/{n}").set({"timestamp": ts_label, "readings": readings})

        ok = self._with_db(_op)
        
        if ok or not self.ready or self.disabled_reason:
            self._seq_cache[path] = n + 1

_FB = _FirebaseGate()


PREFIX_MAP = {"Testing": "T", "Experiment": "E", "Deployment": "D", "Baseline": "B"}
BAUD_ARDUINO_DEFAULT = 9600

STATE = {
    "active": False,
    "first_read_epoch": None,
    "duration_sec": 0,
    "stage": None,
    "substance": None,
    "test_id": None,
    "flowrate": None,
    "interval": 1.0,
    "cumulative_csv": None,
    "folder": None,
    "per_board_status": {},  
}

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

def _make_paths(stage: str, substance: str):
    folder = os.path.join("Baseline","baseline") if stage=="Baseline" else os.path.join(stage, substance)
    os.makedirs(folder, exist_ok=True)
    cumulative_csv = os.path.join(folder, f"{('baseline' if stage=='Baseline' else substance)}_B_Readings.csv")
    return {"folder": folder, "cumulative_csv": cumulative_csv}

def _parse_line(line: str):
    m = PAIR_RE.match(line)
    if not m: return None
    label, val, unit = m.group(1).strip(), m.group(2), m.group(3)
    try:
        f = float(val)
    except ValueError:
        return None
    unit = (unit or "").strip() or None
    if unit == "C": unit = "°C"
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

    def stop(self): self.stop_flag.set()

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
                time.sleep(0.25); continue

            line = _clean_ascii(raw).strip()
            if not line: continue

            if NEW_DATA_RE.match(line):
                if buffer:
                    self._emit_block(buffer); buffer = []
                    time.sleep(self.interval_s)
                in_block = True; continue

            if in_block:
                if line.startswith("*"):
                    self._emit_block(buffer); buffer = []
                    in_block = False; time.sleep(self.interval_s); continue
                buffer.append(line)

        try:
            if self.ser: self.ser.close()
        except Exception:
            pass

    def _emit_block(self, lines: List[str]):
        parsed: Dict[str, Tuple[float, Optional[str]]] = {}
        for ln in lines:
            tup = _parse_line(ln)
            if tup:
                label, val, unit = tup
                parsed[label] = (val, unit)
        if not parsed: return
        parsed["_captured_at_"] = (time.time(), None)
        _LATEST_BLOCKS[self.board_id] = parsed

        if STATE["first_read_epoch"] is None:
            STATE["first_read_epoch"] = parsed["_captured_at_"][0]
        STATE["per_board_status"][self.board_id] = "capturing"

# === CSV writer thread (cumulative only) ===
class BCumulativeWriter(threading.Thread):
    daemon = True
    def __init__(self):
        super().__init__(name="B-Cumulative-Writer")
        self.stop_flag = threading.Event()
        self.header: Optional[List[str]] = None

    def stop(self): self.stop_flag.set()

    def run(self):
        paths = _make_paths(STATE["stage"], STATE["substance"])
        STATE["folder"] = paths["folder"]
        STATE["cumulative_csv"] = paths["cumulative_csv"]

        enabled = [b for b in STATE["per_board_status"].keys() if b in ("B1","B2")]

        # Wait briefly for first blocks so header includes all sensors.
        t0 = time.time()
        while not self.stop_flag.is_set():
            if all(b in _LATEST_BLOCKS for b in enabled) or (time.time()-t0>15):
                break
            time.sleep(0.1)
        if self.stop_flag.is_set(): return

        # Build header
        cols = ["Timestamp","Flowrate (L/min)"]
        seen = {}
        for b in enabled:
            blk = _LATEST_BLOCKS.get(b,{})
            for k,(_v,unit) in blk.items():
                if k == "_captured_at_": continue
                colname = f"{b} - {k}{f' ({unit})' if unit else ''}"
                seen[colname]=None
        cols.extend(sorted(seen.keys(), key=str.lower))
        self.header = cols

        need_header = (not os.path.exists(STATE["cumulative_csv"])) or os.path.getsize(STATE["cumulative_csv"])==0
        if need_header:
            os.makedirs(os.path.dirname(STATE["cumulative_csv"]), exist_ok=True)
            with open(STATE["cumulative_csv"],"a",newline="",encoding="utf-8") as fh:
                csv.writer(fh).writerow(self.header)

        
        _FB.init()
        if _FB.ready:
            STATE["per_board_status"]["Firebase"] = "online"
            _FB.load_seq_if_needed(STATE["stage"], STATE["substance"], STATE["test_id"] or "", enabled)
        else:
            STATE["per_board_status"]["Firebase"] = f"offline ({_FB.disabled_reason})"

    
        while not self.stop_flag.is_set():
            fresh = [(_LATEST_BLOCKS[b]["_captured_at_"][0], b) for b in enabled if b in _LATEST_BLOCKS]
            if not fresh:
                time.sleep(0.05); continue

            ts_epoch = max(t for t,_ in fresh)
            ts_human = datetime.fromtimestamp(ts_epoch).strftime("%Y-%m-%d %H:%M:%S")
            row = [ts_human, _fmt(STATE["flowrate"])]

    
            fb_payloads: List[Tuple[str, Dict[str,float]]] = []
            for b in enabled:
                blk = _LATEST_BLOCKS.get(b,{})
                rds = {}
                for k,(v,unit) in blk.items():
                    if k == "_captured_at_": continue
                    rds[f"{k}{f' ({unit})' if unit else ''}"] = _fmt(v)
                if rds: fb_payloads.append((b, rds))

            
            for c in self.header[2:]:
                try: b,_ = c.split(" - ",1)
                except ValueError: row.append(None); continue
                src = _LATEST_BLOCKS.get(b,{})
                val=None
                for k,(v,unit) in src.items():
                    if k == "_captured_at_": continue
                    if f"{b} - {k}{f' ({unit})' if unit else ''}" == c:
                        val=v; break
                row.append(_fmt(val) if val is not None else None)

            # write CSV
            try:
                with open(STATE["cumulative_csv"],"a",newline="",encoding="utf-8") as fh:
                    csv.writer(fh).writerow(row)
            except PermissionError:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                alt = os.path.splitext(STATE["cumulative_csv"])[0] + f"_pending_{stamp}.csv"
                with open(alt,"a",newline="",encoding="utf-8") as fh:
                    cw = csv.writer(fh)
                    if need_header and os.path.getsize(alt)==0: cw.writerow(self.header)
                    cw.writerow(row)

        
            if STATE["test_id"] and _FB.ready:
                for board_id, readings in fb_payloads:
                    _FB.put_reading(STATE["stage"], STATE["substance"], STATE["test_id"],
                                    board_id, ts_epoch, readings)
                if _FB.disabled_reason:
                    STATE["per_board_status"]["Firebase"] = f"offline ({_FB.disabled_reason})"

        
            if STATE["first_read_epoch"] is not None and STATE["duration_sec"]>0:
                if time.time()-STATE["first_read_epoch"] >= STATE["duration_sec"]:
                    break

            time.sleep(STATE["interval"])

# ===== Public API =====
_WRITER_THREAD: Optional[BCumulativeWriter] = None
_AUTO_THREAD: Optional[threading.Thread] = None

def start_capture(stage: str, substance: Optional[str], test_id: str,
                  flowrate: float, duration_sec: int, interval: float,
                  ports: Dict[str, Optional[str]]):
    stop_capture()
    sub_name = "baseline" if stage=="Baseline" else (substance or "").title()
    STATE.update({
        "active": True,
        "first_read_epoch": None,
        "duration_sec": duration_sec,
        "stage": stage,
        "substance": sub_name,
        "test_id": test_id,
        "flowrate": float(flowrate),
        "interval": float(interval),
        "cumulative_csv": None,
        "folder": None,
        "per_board_status": {k:"idle" for k in ("B1","B2") if ports.get(k)},
    })
    _LATEST_BLOCKS.clear()

    for b,p in ports.items():
        if p:
            r = BSerialReader(b,p,interval); _THREADS[b]=r; r.start()

    global _WRITER_THREAD
    _WRITER_THREAD = BCumulativeWriter(); _WRITER_THREAD.start()

    def _auto_watch():
        while STATE["first_read_epoch"] is None and STATE["active"]: time.sleep(0.1)
        if not STATE["active"] or STATE["first_read_epoch"] is None: return
        while STATE["active"]:
            if STATE["duration_sec"]>0 and (time.time()-STATE["first_read_epoch"]>=STATE["duration_sec"]): break
            time.sleep(0.25)
        if STATE["active"]: stop_capture()
    global _AUTO_THREAD
    _AUTO_THREAD = threading.Thread(target=_auto_watch, daemon=True); _AUTO_THREAD.start()

def stop_capture():
    for r in list(_THREADS.values()):
        r.stop()
    for r in list(_THREADS.values()):
        r.join(timeout=2.0)
    _THREADS.clear()

    global _WRITER_THREAD
    if _WRITER_THREAD:
        _WRITER_THREAD.stop(); _WRITER_THREAD.join(timeout=2.0); _WRITER_THREAD=None
    STATE["active"]=False

def snapshot():
    pct=0
    if STATE["first_read_epoch"] is not None and STATE["duration_sec"]>0:
        elapsed=time.time()-STATE["first_read_epoch"]
        pct=int(max(0,min(100,(elapsed/STATE["duration_sec"])*100)))
    lines=[]
    for b,st in STATE["per_board_status"].items(): lines.append(f"{b}: {st}")
    if "Firebase" in STATE["per_board_status"]:
        lines.append(f"Firebase: {STATE['per_board_status']['Firebase']}")
    if STATE.get("cumulative_csv"): lines.append(f"Cumulative (B): {STATE['cumulative_csv']}")
    if STATE.get("test_id"): lines.append(f"Firebase test_id: {STATE['test_id']}")
    if pct>=100: lines.append("Test complete.")
    return {"first_read_epoch": STATE["first_read_epoch"], "pct": pct,
            "paths":{"cumulative_csv": STATE.get("cumulative_csv"), "folder": STATE.get("folder")},
            "status_lines": lines}
