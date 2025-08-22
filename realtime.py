
import os, re, threading, time, math
from datetime import datetime, timedelta
import pandas as pd
import serial
from dash import dcc, html, Input, Output, State
import plotly.graph_objs as go

import firebase_admin
from firebase_admin import credentials, db
from dotenv import load_dotenv
load_dotenv()

# === Firebase Setup ===
BASE_DIR = os.path.abspath(".")
service_key_path = os.path.join(BASE_DIR, "serviceAccountKey.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(service_key_path)
    firebase_admin.initialize_app(cred, {
        'databaseURL': os.getenv("databaseURL")
    })

# === Config ===
BAUD_RATE = 9600
PREFIX_MAP = {"Testing": "T", "Experiment": "E", "Deployment": "D", "Baseline": "B"}
BASELINE_FILE = os.path.join("Baseline", "baseline.csv")

# === Load Baseline ===
BASELINE_VALUES = {}
if os.path.exists(BASELINE_FILE):
    baseline_df = pd.read_csv(BASELINE_FILE)
    for col in baseline_df.columns:
        if col != "Timestamp":
            BASELINE_VALUES[col] = baseline_df[col].iloc[0]
    print("[INFO] Baseline loaded:", BASELINE_VALUES)

# === Globals ===
LIVE_THREADS = {}     
LIVE_DATA = {}        
RECORDING_PARAMS = {
    "recording": False,
    "stage": None,
    "substance": None,
    "flow": None,
    "duration": None,
    "interval": None,
    "start_time": None,
    "csv_file": None,
    "folder": None
}
MERGED_BUFFER = []    

# === Helpers ===
def clean_text(text):
    return re.sub(r"[^\x00-\x7F°]", "", text)

def extract_numeric(value):
    return re.sub(r"[^\d\.]+", "", value)

def get_file_paths(stage, substance):
    folder_prefix = PREFIX_MAP.get(stage, "X")
    timestamp_folder = datetime.now().strftime("%H-%M-%S %d-%m-%Y")
    folder = os.path.join(stage, substance.title(), timestamp_folder)
    os.makedirs(folder, exist_ok=True)

    run_no = len([f for f in os.listdir(folder) if f.endswith(".csv")]) + 1
    serial_id = f"{run_no:04d}"
    session_name = f"{folder_prefix}{substance}{serial_id}"
    csv_file = os.path.join(folder, f"{session_name}.csv")
    cumulative_file = os.path.join(folder, f"{substance}_Readings.csv")
    return folder, csv_file, cumulative_file

def push_to_firebase(stage, substance, data):
    try:
        clean_data = {}
        for k, v in data.items():
            if isinstance(v, datetime):
                clean_data[k] = v.strftime("%Y-%m-%d %H:%M:%S")
            elif hasattr(v, "item"):
                clean_data[k] = v.item()
            elif v is None or (isinstance(v, float) and math.isnan(v)):
                clean_data[k] = None
            else:
                clean_data[k] = v

        timestamp_path = datetime.now().strftime("%H-%M-%S %d-%m-%Y")
        db.reference(f"{stage}/{substance}/{timestamp_path}").push(clean_data)
    except Exception as e:
        print("[FIREBASE ERROR]", e)

# === Save merged CSV row ===
def save_merged_row(timestamp):
    global MERGED_BUFFER
    if not MERGED_BUFFER:
        return

    merged_row = {"Timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S")}
    for board_data in MERGED_BUFFER:
        merged_row.update(board_data)

    df = pd.DataFrame([merged_row])
    header = not os.path.exists(RECORDING_PARAMS["csv_file"])
    df.to_csv(RECORDING_PARAMS["csv_file"], mode="a", index=False,
              encoding="utf-8-sig", header=header)

    cumulative_file = os.path.join(RECORDING_PARAMS["folder"],
                                   f"{RECORDING_PARAMS['substance']}_Readings.csv")
    df.to_csv(cumulative_file, mode="a", index=False,
              encoding="utf-8-sig", header=not os.path.exists(cumulative_file))

    push_to_firebase(RECORDING_PARAMS["stage"], RECORDING_PARAMS["substance"], merged_row)
    MERGED_BUFFER = []

# === Reader: Standard board (B1/B2) ===
def read_board(board_id, com_port):
    try:
        ser = serial.Serial(com_port, BAUD_RATE, timeout=1)
        time.sleep(2)
    except Exception as e:
        print(f"[ERROR] Could not open {com_port}: {e}")
        return

    current_data = {}
    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            line = clean_text(line)

            if line == "New Data":
                if current_data:
                    timestamp = datetime.now()
                    current_data["Timestamp"] = timestamp
                    LIVE_DATA.setdefault(board_id, []).append(current_data.copy())

                    one_min_ago = datetime.now() - timedelta(seconds=60)
                    LIVE_DATA[board_id] = [d for d in LIVE_DATA[board_id] if d["Timestamp"] >= one_min_ago]

                    if RECORDING_PARAMS["recording"]:
                        now = datetime.now()
                        if RECORDING_PARAMS["start_time"] is None:
                            RECORDING_PARAMS["start_time"] = now
                        elapsed = (now - RECORDING_PARAMS["start_time"]).total_seconds()
                        if elapsed <= RECORDING_PARAMS["duration"] * 60:
                            safe_data = {}
                            for k, v in current_data.items():
                                if k == "Timestamp":
                                    continue
                                safe_data[k] = v
                            MERGED_BUFFER.append(safe_data)
                            if len(MERGED_BUFFER) >= len([t for t in LIVE_THREADS.values() if t.is_alive()]):
                                save_merged_row(timestamp)
                            time.sleep(RECORDING_PARAMS["interval"])

                current_data = {}
                continue

            parts = [p.strip() for p in line.split(":", maxsplit=1)]
            if len(parts) == 2:
                key, val = parts
                val_clean = val.strip()

                # ppm/ppb values
                match = re.search(r"([\d\.]+)\s*(ppm|ppb)", val_clean, re.IGNORECASE)
                if match:
                    value = float(match.group(1))
                    unit = match.group(2).lower()
                    colname = f"{board_id} - {key.strip()} ({unit})"
                    current_data[colname] = value
                    continue

                # Raw sensors
                if re.match(r"^(TGS|MQ)", key.strip(), re.IGNORECASE):
                    try:
                        value = float(extract_numeric(val_clean))
                        colname = f"{board_id} - {key.strip()} (raw)"
                        current_data[colname] = value
                    except:
                        pass
                    continue

                current_data[f"{board_id} - {key.strip()}"] = val_clean

        except Exception:
            continue

# === Reader: Libelium board (LB1/LB2) ===
LIBELIUM_KEYS_ORDER = ["NO", "CO", "NO2", "NH3", "O2"]  

def read_libelium(board_id, com_port):
    """
    Parse lines like:
      NO: 0.12 ppm
      CO: 1.23 ppm
      ...
      O2: 20.8 ppm(or % depending on config)
    The Libelium sketch prints a separator; we'll treat seeing O2 as end-of-cycle.
    """
    try:
        ser = serial.Serial(com_port, BAUD_RATE, timeout=1)
        time.sleep(2)
    except Exception as e:
        print(f"[ERROR] Could not open {com_port}: {e}")
        return

    current = {}
    seen_keys = set()
    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            line = clean_text(line)

            
            if set(line) == {"*"}:

                if current:
                    _flush_libelium_sample(board_id, current)
                    current, seen_keys = {}, set()
                continue


            m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*([-+]?\d*\.?\d+)\s*([A-Za-z%/]+)?\s*$", line)
            if not m:
                continue

            key, value, unit = m.groups()
            key = key.strip()
            try:
                value = float(value)
            except ValueError:
                continue


            unit = (unit or "ppm").lower()
            if unit == "%":
                colname = f"{board_id} - {key} (%)"
            else:
                colname = f"{board_id} - {key} ({unit})"

            current[colname] = value
            seen_keys.add(key.upper())


            if key.upper() == "O2" or seen_keys.issuperset(set(LIBELIUM_KEYS_ORDER)):
                _flush_libelium_sample(board_id, current)
                current, seen_keys = {}, set()

        except Exception:

            time.sleep(0.2)
            continue

def _flush_libelium_sample(board_id, payload):
    if not payload:
        return
    timestamp = datetime.now()
    payload = dict(payload) 
    payload["Timestamp"] = timestamp
    LIVE_DATA.setdefault(board_id, []).append(payload)

    one_min_ago = datetime.now() - timedelta(seconds=60)
    LIVE_DATA[board_id] = [d for d in LIVE_DATA[board_id] if d["Timestamp"] >= one_min_ago]

    if RECORDING_PARAMS["recording"]:
        now = datetime.now()
        if RECORDING_PARAMS["start_time"] is None:
            RECORDING_PARAMS["start_time"] = now
        elapsed = (now - RECORDING_PARAMS["start_time"]).total_seconds()
        if elapsed <= RECORDING_PARAMS["duration"] * 60:

            safe = {k: v for k, v in payload.items() if k != "Timestamp"}
            MERGED_BUFFER.append(safe)
            if len(MERGED_BUFFER) >= len([t for t in LIVE_THREADS.values() if t.is_alive()]):
                save_merged_row(timestamp)
            time.sleep(RECORDING_PARAMS["interval"])

# === Layout ===
def layout(nav):
    return html.Div([
        nav(),
        html.H3("Realtime Sensor Data", style={"textAlign": "center", "marginTop": "20px"}),

        # ---inputs: B1, B2, LB1, LB2 ---
        html.Div([
            html.Div([
                html.Label("B1 COM Port"),
                dcc.Input(id="rt-b1-com", type="number", min=1, placeholder="e.g. 3"),
                html.Br(), html.Br(),

                html.Label("B2 COM Port"),
                dcc.Input(id="rt-b2-com", type="number", min=1, placeholder="e.g. 4"),
                html.Br(), html.Br(),

                html.Label("LB1 COM Port"),
                dcc.Input(id="rt-lb1-com", type="number", min=1, placeholder="e.g. 5"),
                html.Br(), html.Br(),

                html.Label("LB2 COM Port"),
                dcc.Input(id="rt-lb2-com", type="number", min=1, placeholder="e.g. 6"),
                html.Br(), html.Br(),
            ]),

            html.Button("Preview Live Data", id="rt-preview", n_clicks=0,
                        style={"background": "#007bff", "color": "white", "padding": "8px 25px",
                               "border": "none", "marginRight": "10px"}),

            html.Button("Start Recording", id="rt-record", n_clicks=0,
                        style={"background": "#28a745", "color": "white", "padding": "8px 25px", "border": "none"}),

            html.Div(id="rt-controls", style={"marginTop": "15px"}),

            html.Div(id="rt-status", style={"marginTop": "15px", "fontWeight": "bold"}),
        ], style={"maxWidth": "500px", "margin": "auto"}),

        html.Div(id="rt-graphs", style={"marginTop": "30px"}),

        dcc.Interval(id="rt-interval", interval=2000, n_intervals=0),
        dcc.Store(id="rt-active-boards"),
    ])

# === Callbacks ===
def register_callbacks(app):
    @app.callback(
        Output("rt-active-boards", "data"),
        Output("rt-status", "children"),
        Input("rt-preview", "n_clicks"),
        State("rt-b1-com", "value"),
        State("rt-b2-com", "value"),
        State("rt-lb1-com", "value"),
        State("rt-lb2-com", "value"),
        prevent_initial_call=True
    )
    def start_preview(_n, b1, b2, lb1, lb2):
        requested = []
        if b1: requested.append(("B1", f"COM{int(b1)}", "std"))
        if b2: requested.append(("B2", f"COM{int(b2)}", "std"))
        if lb1: requested.append(("LB1", f"COM{int(lb1)}", "lib"))
        if lb2: requested.append(("LB2", f"COM{int(lb2)}", "lib"))

        if not requested:
            return None, "Please enter at least one COM port."

        started = []
        for board, port, kind in requested:
            if board not in LIVE_THREADS or not LIVE_THREADS[board].is_alive():
                target = read_libelium if kind == "lib" else read_board
                t = threading.Thread(target=target, args=(board, port), daemon=True)
                LIVE_THREADS[board] = t
                LIVE_DATA.setdefault(board, [])
                t.start()
            started.append(board)

        return [b for b, _, _ in requested], f"Preview started for: {', '.join(started)}"

    @app.callback(
        Output("rt-controls", "children"),
        Input("rt-record", "n_clicks"),
        prevent_initial_call=True
    )
    def show_recording_controls(_n):
        return html.Div([
            html.Label("Project Stage"),
            dcc.Dropdown(id="rt-stage", options=[{"label": s, "value": s} for s in PREFIX_MAP],
                         placeholder="Select stage"),

            html.Br(),
            html.Label("Substance"),
            dcc.Input(id="rt-substance", type="text", placeholder="e.g. Ethanol"),

            html.Br(), html.Br(),
            html.Label("Flow-rate (L/min)"),
            dcc.Input(id="rt-flow", type="number", min=1, max=5, step=0.1),

            html.Br(), html.Br(),
            html.Label("Duration (minutes)"),
            dcc.Input(id="rt-duration", type="number", min=0.1, step=0.1),

            html.Br(), html.Br(),
            html.Label("Interval (seconds)"),
            dcc.Input(id="rt-interval-sec", type="number", min=0.1, step=0.1, value=1),

            html.Br(), html.Br(),
            html.Button("Confirm & Start Recording", id="rt-confirm", n_clicks=0,
                        style={"background": "#dc3545", "color": "white", "padding": "8px 25px", "border": "none"})
        ])

    @app.callback(
        Output("rt-status", "children", allow_duplicate=True),
        Input("rt-confirm", "n_clicks"),
        State("rt-stage", "value"),
        State("rt-substance", "value"),
        State("rt-flow", "value"),
        State("rt-duration", "value"),
        State("rt-interval-sec", "value"),
        prevent_initial_call=True
    )
    def confirm_recording(_n, stage, substance, flow, dur, inter):
        if not all([stage, substance, flow, dur, inter]):
            return "Please complete all fields."

        folder, csv_file, _ = get_file_paths(stage, substance.title())
        RECORDING_PARAMS.update({
            "recording": True,
            "stage": stage,
            "substance": substance.title(),
            "flow": float(flow),
            "duration": float(dur),
            "interval": float(inter),
            "start_time": None,
            "csv_file": csv_file,
            "folder": folder
        })
        return f"Recording started: {stage} - {substance.title()}, Flow: {flow} L/min"

    @app.callback(
        Output("rt-graphs", "children"),
        Input("rt-interval", "n_intervals"),
        State("rt-active-boards", "data"),
        prevent_initial_call=True
    )
    def update_graphs(_n, boards):
        if not boards:
            return []
        graphs = []

        for board in boards:
            if board not in LIVE_DATA or not LIVE_DATA[board]:
                continue
            df = pd.DataFrame(LIVE_DATA[board])
            if "Timestamp" not in df:
                continue

            df["Timestamp"] = pd.to_datetime(df["Timestamp"])
            df = df.sort_values("Timestamp")

            one_min_ago = datetime.now() - timedelta(seconds=60)
            df = df[df["Timestamp"] >= one_min_ago]
            if df.empty:
                continue

            for col in df.columns:
                if col == "Timestamp":
                    continue
                if not ("ppm" in col.lower() or "ppb" in col.lower() or "(raw)" in col.lower()):
                    continue

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=(df["Timestamp"] - df["Timestamp"].min()).dt.total_seconds(),
                    y=df[col], mode="lines+markers", name="Live"
                ))


                if col in BASELINE_VALUES:
                    fig.add_trace(go.Scatter(
                        x=[0, 60], y=[BASELINE_VALUES[col], BASELINE_VALUES[col]],
                        mode="lines", line=dict(dash="dash"), name="Baseline"
                    ))

                fig.update_xaxes(range=[0, 60], tickvals=[0, 15, 30, 45, 60])
                if col.endswith("(raw)"):
                    fig.update_yaxes(range=[0, 1023])

                fig.update_layout(
                    title=col,
                    xaxis_title="Time (s, last 60s)",
                    yaxis_title="Value"
                )
                graphs.append(html.Div([dcc.Graph(figure=fig)],
                                       style={"width": "48%", "display": "inline-block", "margin": "1%"}))

        return graphs
