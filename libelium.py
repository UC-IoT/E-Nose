# === libelium.py ===

import re
import time
import threading
from datetime import datetime
from typing import Dict, Optional

import serial
from serial.tools import list_ports

# === Configuration ===
DEFAULT_BAUD = 9600
READ_TIMEOUT = 1.0   
LINE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:\s*([-+]?\d*\.?\d+)\s*([A-Za-z%/]+)?\s*$")

SENSOR_KEYS = ["NO", "CO", "NO2", "NH3", "O2"]  

# === State ===
_readers = {}         
_latest = {}           
_latest_lock = threading.Lock()


def list_serial_ports() -> Dict[str, str]:
    """Return a dict {device: description} of available serial ports."""
    ports = {}
    for p in list_ports.comports():
        ports[p.device] = p.description or ""
    return ports


class SerialReader(threading.Thread):
    def __init__(self, name: str, port: str, baud: int = DEFAULT_BAUD):
        super().__init__(daemon=True)
        self.name = name          
        self.port = port
        self.baud = baud
        self.stop_flag = threading.Event()
        self.ser: Optional[serial.Serial] = None
        self.current: Dict[str, float] = {}  
    def run(self):
        while not self.stop_flag.is_set():
            try:
                if self.ser is None or not self.ser.is_open:
                    self.ser = serial.Serial(self.port, self.baud, timeout=READ_TIMEOUT)
                    time.sleep(0.5)  # settle

                line = self.ser.readline().decode(errors="ignore").strip()
                if not line:
                    continue

                if line.startswith("*"):
                    self._flush_current()
                    continue

                m = LINE_RE.match(line)
                if m:
                    key, value, unit = m.groups()
                    key_norm = key.upper()
                    if key_norm in {"TEMP", "TEMPERATURE"}:
                        key_norm = "Temperature"
                    elif key_norm in {"HUM", "HUMIDITY"}:
                        key_norm = "Humidity"
                    elif key_norm in {"PRES", "PRESSURE"}:
                        key_norm = "Pressure"

                    if key_norm in SENSOR_KEYS or key_norm in {"Temperature", "Humidity", "Pressure"}:
                        try:
                            self.current[key_norm] = float(value)
                        except ValueError:
                            pass  # ignore bad numeric

                if self.current and len(self.current) >= 2:

                    pass

            except Exception:
                # soft-retry on any serial hiccup
                time.sleep(1.0)
                try:
                    if self.ser:
                        self.ser.close()
                except Exception:
                    pass
                self.ser = None

        # on exit
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self._flush_current()

    def _flush_current(self):
        if not self.current:
            return
        with _latest_lock:
            payload = dict(self.current)
            payload["Timestamp"] = datetime.now()
            _latest[self.name] = payload
        self.current.clear()

    def stop(self):
        self.stop_flag.set()


# === Public API ===

def start_reader(board_name: str, port: str, baud: int = DEFAULT_BAUD):
    """Start a reader thread for a Libelium board (LB1 or LB2)."""
    stop_reader(board_name)
    r = SerialReader(board_name, port, baud)
    _readers[board_name] = r
    r.start()


def stop_reader(board_name: str):
    r = _readers.get(board_name)
    if r:
        r.stop()
        r.join(timeout=2.0)
        _readers.pop(board_name, None)


def stop_all():
    for name in list(_readers.keys()):
        stop_reader(name)


def get_latest(board_name: str) -> Dict[str, float]:
    """Return latest sample dict for LB1/LB2 with keys in SENSOR_KEYS + Timestamp if available."""
    with _latest_lock:
        return dict(_latest.get(board_name, {}))


def format_for_csv(board_name: str, sample: Dict[str, float]) -> Dict[str, float]:
    """
    Map parsed keys to your CSV schema:
      LB1 - NO (ppm), LB1 - CO (ppm), LB1 - NO2 (ppm), LB1 - NH3 (ppm), LB1 - O2 (%)
    """
    prefix = f"{board_name} - "
    out = {}
    if not sample:
        return out
    # gases
    if "NO" in sample:
        out[prefix + "NO (ppm)"] = sample["NO"]
    if "CO" in sample:
        out[prefix + "CO (ppm)"] = sample["CO"]
    if "NO2" in sample:
        out[prefix + "NO2 (ppm)"] = sample["NO2"]
    if "NH3" in sample:
        out[prefix + "NH3 (ppm)"] = sample["NH3"]
    if "O2" in sample:
        out[prefix + "O2 (%)"] = sample["O2"]
    if "Temperature" in sample:
        out[prefix + "Temperature (C)"] = sample["Temperature"]
    if "Humidity" in sample:
        out[prefix + "Humidity (%)"] = sample["Humidity"]
    if "Pressure" in sample:
        out[prefix + "Pressure (Pa)"] = sample["Pressure"]
    return out

