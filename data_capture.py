import os, re, threading, time
from datetime import datetime, timedelta

import pandas as pd
import serial
from dash import Dash, html, dcc, Input, Output, State
from dash.dependencies import ALL

# === Configuration ===
BAUD_RATE = 9600
BASE_DIR = os.path.abspath(".")
PREFIX_MAP = {"Testing": "T", "Experiment": "E", "Deployment": "D", "Baseline": "B"}

# === Global Trackers ===
CAPTURE_THREADS = {}
CAPTURE_PROGRESS = {}

# === Utility Functions ===
def clean_text(text):
    return re.sub(r"[^\x00-\x7F°]", "", text)

def extract_numeric(value):
    return re.sub(r"[^\d\.]+", "", value)

# === Data Capture Function ===
def capture_data(stage, substance, flowrate, duration_minutes, interval_seconds,
                 board_number, com_port, session_key):

    folder_prefix = PREFIX_MAP.get(stage, "X")
    
    if stage == "Baseline":
        folder = os.path.join("Baseline", "baseline")
        substance = "baseline"
    else:
        folder = os.path.join(stage, substance.title())
    
    os.makedirs(folder, exist_ok=True)

    run_no = len([
        f for f in os.listdir(folder)
        if f.lower().startswith((folder_prefix + substance).lower()) and f.endswith(".csv")
    ]) + 1

    serial_id = f"{run_no:04d}"
    session_name = f"{folder_prefix}{substance}{serial_id}"
    csv_file = os.path.join(folder, f"{session_name}.csv")
    cumulative_file = os.path.join(folder, f"{substance}_Readings.csv")

    try:
        ser = serial.Serial(com_port, BAUD_RATE, timeout=2)
        time.sleep(2)
    except Exception as e:
        print(f"[ERROR] Could not open {com_port}: {e}")
        return

    end_time = datetime.now() + timedelta(minutes=duration_minutes)
    readings = []
    current_data = {}
    group = "General"
    capturing = False

    while datetime.now() < end_time:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            line = clean_text(line)

            if line == "New Data":
                if current_data:
                    current_data["Timestamp"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                    current_data["Flowrate (L/min)"] = flowrate
                    readings.append(current_data)
                    current_data = {}
                    time.sleep(interval_seconds)

                capturing = True
                group = "General"
                elapsed = (datetime.now() - (end_time - timedelta(minutes=duration_minutes))).total_seconds()
                CAPTURE_PROGRESS[session_key] = min(100, int(elapsed / (duration_minutes * 60) * 100))
                continue

            if not capturing:
                continue

            if line.startswith("Reading "):
                group = line.replace("Reading", "").replace("...", "").strip()
                continue

            parts = [p.strip() for p in line.replace(":", ": ").split(":", maxsplit=2)]

            if len(parts) == 3:
                key, val1, val2 = parts
                if any(u in val1 for u in ("ppm", "ppb", "%", "°C", "KPa", "Kohms")):
                    unit_match = re.search(r"(ppm|ppb|%|°C|KPa|Kohms)", val1)
                    if unit_match:
                        unit = unit_match.group(1)
                        colname_val = f"{board_number} - {group} - {key} - {unit}"
                        colname_volt = f"{board_number} - {group} - {key} - V"
                        current_data[colname_val] = val1
                        current_data[colname_volt] = extract_numeric(val2)
                else:
                    current_data[f"{board_number} - {group} - {key} - raw"] = f"{val1}:{val2}"

            elif len(parts) == 2:
                key, val = parts
                key = clean_text(key)
                val = clean_text(val)
                if val.endswith("V"):
                    try:
                        colname = f"{board_number} - {group} - {key} - V"
                        current_data[colname] = float(val.replace("V", "").strip())
                    except ValueError:
                        current_data[f"{board_number} - {group} - {key} - raw"] = val
                else:
                    current_data[f"{board_number} - {group} - {key} - raw"] = val
        except Exception as err:
            print(f"[ERROR] {err}")
            continue

    ser.close()
    CAPTURE_PROGRESS[session_key] = 100

    if not readings:
        print(f"[INFO] No data recorded from {board_number}.")
        return

    if "MERGED_DATA" not in CAPTURE_PROGRESS:
        CAPTURE_PROGRESS["MERGED_DATA"] = {}

    CAPTURE_PROGRESS["MERGED_DATA"][board_number] = readings

    all_done = all(progress == 100 for key, progress in CAPTURE_PROGRESS.items()
                   if key != "MERGED_DATA")

    if not all_done:
        return

    combined_rows = []
    board_data = CAPTURE_PROGRESS["MERGED_DATA"]
    max_len = max(len(r) for r in board_data.values())

    for i in range(max_len):
        row = {}
        for b, board_readings in board_data.items():
            if i < len(board_readings):
                row.update(board_readings[i])
        combined_rows.append(row)

    df = pd.DataFrame(combined_rows)
    ordered_cols = ["Timestamp", "Flowrate (L/min)"] + \
                   [c for c in df.columns if c not in ["Timestamp", "Flowrate (L/min)"]]
    df = df[ordered_cols]

    df.columns = [clean_text(c).replace("Â", "").strip() for c in df.columns]

    df.to_csv(csv_file, index=False, encoding="utf-8-sig")

    if os.path.exists(cumulative_file):
        df.to_csv(cumulative_file, mode="a", index=False, header=False, encoding="utf-8-sig")
    else:
        df.to_csv(cumulative_file, index=False, encoding="utf-8-sig")

    print(f"[✓] Session saved: {csv_file}")
    print(f"[✓] Cumulative updated: {cumulative_file}")

# === Thread Start Wrapper ===
def start_capture_thread(**kwargs):
    now = datetime.now().isoformat()
    key = "|".join(str(kwargs[k]) for k in ("stage", "substance", "board_number", "com_port")) + "|" + now
    if key in CAPTURE_THREADS and CAPTURE_THREADS[key].is_alive():
        return key
    t = threading.Thread(target=capture_data, kwargs={**kwargs, "session_key": key}, daemon=True)
    CAPTURE_THREADS[key] = t
    CAPTURE_PROGRESS[key] = 0
    t.start()
    return key

# === UI Layout ===
def layout(nav):
    return html.Div([
        nav(),
        html.H3("Capture data from multiple boards", style={"textAlign": "center", "marginTop": "25px"}),
        html.Div([
            html.Label("Project Stage"),
            dcc.Dropdown(id="w-stage",
                         options=[{"label": s, "value": s} for s in PREFIX_MAP],
                         placeholder="Select stage"),

            html.Br(),
            html.Div(id="substance-field"),

            html.Label("Flow-rate (L/min)"),
            dcc.Input(id="w-flow", type="number", min=1, max=5, step=0.1),

            html.Br(), html.Br(),
            html.Label("Duration (minutes)"),
            dcc.Input(id="w-duration", type="number", min=0.1, step=0.1),

            html.Br(), html.Br(),
            html.Label("Interval between readings (s)"),
            dcc.Input(id="w-interval", type="number", min=0.1, step=0.1, value=1),

            html.Br(), html.Br(),
            html.Label("Number of boards"),
            dcc.Input(id="w-nboards", type="number", min=1, max=10, value=2),

            html.Br(), html.Br(),
            html.Div(id="board-fields"),

            html.Button("Start Multi-Board Capture", id="w-start", n_clicks=0,
                        style={"background": "#28a745", "color": "white", "padding": "8px 25px",
                               "border": "none", "marginTop": "20px"}),

            html.Div(id="w-status", style={"marginTop": "25px", "fontWeight": "bold"}),

            html.Div([
                html.Div(id="progress-fill",
                         style={"height": "25px", "width": "0%", "background": "#28a745",
                                "color": "white", "textAlign": "center"}),

            ], id="progress-container",
                style={"width": "100%", "background": "#ddd", "marginTop": "10px", "display": "none"}),

            dcc.Interval(id="progress-interval", interval=1000, n_intervals=0),
            dcc.Store(id="w-session"),
        ], style={"maxWidth": "420px", "margin": "auto"})
    ])

# === Callbacks ===
def register_callbacks(app):
    @app.callback(
        Output("substance-field", "children"),
        Input("w-stage", "value")
    )
    def show_substance_input(stage):
        if stage == "Baseline":
            return html.Div()
        return html.Div([
            html.Label("Substance"),
            dcc.Input(id="w-substance", type="text", placeholder="e.g. Ethanol"),
            html.Br(), html.Br()
        ])

    @app.callback(
        Output("board-fields", "children"),
        Input("w-nboards", "value")
    )
    def update_board_inputs(n):
        if not n or n < 1:
            return []
        return [html.Div([
            html.Label(f"Board {i + 1} ID"),
            dcc.Dropdown(
                options=[{"label": f"B{j}", "value": f"B{j}"} for j in range(1, 11)],
                id={"type": "board-id", "index": i},
                placeholder="Select board"
            ),
            html.Label("COM Port"),
            dcc.Input(type="number", min=1, placeholder="e.g. 3", id={"type": "board-com", "index": i}),
            html.Br(), html.Br()
        ]) for i in range(n)]

    @app.callback(
        Output("w-status", "children"),
        Output("w-session", "data"),
        Output("progress-container", "style"),
        Input("w-start", "n_clicks"),
        State("w-stage", "value"),
        State("w-substance", "value"),
        State("w-flow", "value"),
        State("w-duration", "value"),
        State("w-interval", "value"),
        State({"type": "board-id", "index": ALL}, "value"),
        State({"type": "board-com", "index": ALL}, "value"),
        prevent_initial_call=True
    )
    def start_multi_capture(n, stage, sub, flow, dur, inter, boards, coms):
        if not all([stage, flow, dur, inter]) or not all(boards) or not all(coms):
            return "⚠️ Please complete all fields.", None, {"display": "none"}

        if stage != "Baseline" and not sub:
            return "⚠️ Substance is required for non-Baseline stages.", None, {"display": "none"}

        sub = sub.title() if sub else "baseline"
        keys = []
        for board, com in zip(boards, coms):
            k = start_capture_thread(stage=stage, substance=sub, flowrate=float(flow),
                                     duration_minutes=float(dur), interval_seconds=float(inter),
                                     board_number=board, com_port=f"COM{int(com)}")
            keys.append(k)
        return f"Capture started on boards: {', '.join(boards)}", keys, {
            "width": "100%", "background": "#ddd", "marginTop": "10px"
        }

    @app.callback(
        Output("progress-fill", "style"),
        Input("progress-interval", "n_intervals"),
        State("w-session", "data"),
        prevent_initial_call=True
    )
    def update_progress_bar(_n, keys):
        if not keys:
            return {"display": "none"}
        avg = sum(CAPTURE_PROGRESS.get(k, 0) for k in keys) / len(keys)
        return {
            "height": "25px",
            "width": f"{avg:.2f}%",
            "background": "#28a745",
            "color": "white",
            "textAlign": "center",
            "display": "block"
        }
