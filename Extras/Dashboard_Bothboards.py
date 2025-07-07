import os, re, threading, time, argparse, webbrowser
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, ctx
from dash.dependencies import ALL
from plotly.subplots import make_subplots

try:
    import serial
except ImportError:
    serial = None

# ───────────────────────── CONFIG ──────────────────────────
BASE_DIR   = os.path.abspath(".")
BAUD_RATE  = 9600
PREFIX_MAP = {"Testing": "T", "Experiment": "E", "Deployment": "D"}

CAPTURE_THREADS  = {}  # session_key ➜ Thread
CAPTURE_PROGRESS = {}  # session_key ➜ 0-100%

# ─────────────────── helpers ──────────────────────
def get_stage_options():
    return [d for d in os.listdir(BASE_DIR)
            if os.path.isdir(os.path.join(BASE_DIR, d)) and d in PREFIX_MAP]

def get_substance_options(stage):
    p = os.path.join(BASE_DIR, stage)
    return [d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d))] if os.path.isdir(p) else []

def clean_text(txt):  return re.sub(r'[^\x00-\x7F°]', '', txt)
def extract_numeric(v): return re.sub(r'[^0-9\.]+', '', v)

# ───────────── serial-capture worker ──────────────
def capture_data(stage, substance, flowrate, duration_minutes,
                 interval_seconds, board_number, com_port, session_key):
    if serial is None:
        print("[WRITE] pyserial missing – capture disabled.")
        return

    folder_prefix = PREFIX_MAP.get(stage, "X")
    folder        = os.path.join(stage, substance)
    os.makedirs(folder, exist_ok=True)
    run_no        = len([f for f in os.listdir(folder)
                         if f.lower().startswith((folder_prefix+substance).lower())]) + 1
    sn            = f"{run_no:04d}"
    stamp         = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
    csv_path      = os.path.join(folder, f"{board_number}{folder_prefix}{substance}{sn}_{stamp}.csv")

    try:
        ser = serial.Serial(com_port, BAUD_RATE, timeout=2)
        time.sleep(2)
    except Exception as e:
        print(f"[WRITE] Couldn’t open {com_port}: {e}")
        return

    end_time = datetime.now() + timedelta(minutes=duration_minutes)
    data_sets, capturing = [], False
    cur_data, group = {}, "General"

    while datetime.now() < end_time:
        raw = ser.readline().decode("utf-8", errors="ignore").strip()
        if not raw: continue
        line = clean_text(raw)

        if line == "New Data":
            if cur_data:
                cur_data["Timestamp"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                cur_data["Flowrate (L/min)"] = flowrate
                cur_data["Board"] = board_number
                data_sets.append(cur_data)
                cur_data = {}
                time.sleep(interval_seconds)
            capturing, group = True, "General"
            elapsed = (datetime.now() - (end_time - timedelta(minutes=duration_minutes))).total_seconds()
            CAPTURE_PROGRESS[session_key] = min(100, int(elapsed / (duration_minutes * 60) * 100))
            continue
        if not capturing: continue
        if line.startswith("Reading "):
            group = line.replace("Reading", "").replace("...", "").strip()
            continue

        parts = [p.strip() for p in line.replace(":", ": ").split(":", 2)]
        if len(parts) == 3:
            k, v1, v2 = parts
            if any(u in v1 for u in ("ppm", "ppb", "%", "°C", "KPa", "Kohms")):
                unit = re.search(r"(ppm|ppb|%|°C|KPa|Kohms)", v1).group(1)
                base = f"{group} - {k}"
                cur_data[f"{base} ({unit})"] = v1
                cur_data[f"{base} (V)"]     = extract_numeric(v2)
            else:
                cur_data[f"{group} - {k}"] = f"{v1}:{v2}"
        elif len(parts) == 2:
            k, v = parts
            cur_data[f"{group} - {k} (V)"] = float(v[:-1]) if v.endswith("V") else v

    ser.close()
    CAPTURE_PROGRESS[session_key] = 100
    if not data_sets:
        print("[WRITE] No rows captured.")
        return

    df = pd.DataFrame(data_sets)
    order = ["Timestamp","Flowrate (L/min)","Board"] + [c for c in df.columns if c not in ("Timestamp","Flowrate (L/min)","Board")]
    df = df[order]
    df.columns = [clean_text(c) for c in df.columns]
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    cum = os.path.join(folder, f"{substance}_Readings.csv")
    df.to_csv(cum, mode="a" if os.path.isfile(cum) else "w",
              header=not os.path.isfile(cum), index=False, encoding="utf-8-sig")

def start_capture_thread(**kw):
    timestamp = datetime.now().isoformat()
    key = "|".join(str(kw[k]) for k in ("stage","substance","board_number","com_port")) + "|" + timestamp
    if key in CAPTURE_THREADS and CAPTURE_THREADS[key].is_alive():
        return key
    t = threading.Thread(target=capture_data, kwargs={**kw,"session_key":key}, daemon=True)
    CAPTURE_THREADS[key] = t
    CAPTURE_PROGRESS[key] = 0
    t.start()
    return key

# ───────────────────────────── DASH UI ───────────────────────────
app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "eNose Dashboard"

def nav():
    return html.Div([
        html.A("Home", href="/", style={"marginRight":"20px"}),
        html.A("Write Data", href="/write", style={"marginRight":"20px"}),
        html.A("Read / Plot", href="/read")
    ], style={"padding":"10px 20px", "background":"#f0f0f0"})

def write():
    return html.Div([nav(),
        html.H3("Capture data from multiple boards", style={"textAlign":"center","marginTop":"25px"}),
        html.Div([
            html.Label("Project Stage"),
            dcc.Dropdown(id="w-stage",
                         options=[{"label":s,"value":s} for s in PREFIX_MAP],
                         placeholder="Select stage"),
            html.Br(),
            html.Label("Substance"),
            dcc.Input(id="w-substance", type="text", placeholder="e.g. Ethanol"),
            html.Br(), html.Br(),
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
                        style={"background":"#28a745","color":"white",
                               "padding":"8px 25px","border":"none","marginTop":"20px"}),
            html.Div(id="w-status", style={"marginTop":"25px","fontWeight":"bold"}),
            html.Div([
                html.Div(id="progress-fill",
                         style={"height":"25px","width":"0%","background":"#28a745",
                                "color":"white","textAlign":"center"}),
            ], id="progress-container",
               style={"width":"100%","background":"#ddd","marginTop":"10px","display":"none"}),
            dcc.Interval(id="progress-interval", interval=1000, n_intervals=0),
            dcc.Store(id="w-session"),
        ], style={"maxWidth":"420px","margin":"auto"})
    ])

@app.callback(
    Output("board-fields","children"),
    Input("w-nboards","value")
)
def update_board_inputs(n):
    if not n or n<1: return []
    return [html.Div([
                html.Label(f"Board {i+1} ID"),
                dcc.Dropdown(options=[{"label":"B1","value":"B1"},{"label":"B2","value":"B2"},{"label":"B3","value":"B3"}],
                             id={"type":"board-id","index":i}, placeholder="Select board"),
                html.Label(f"COM Port"),
                dcc.Input(type="number", min=1, placeholder="e.g. 3", id={"type":"board-com","index":i}),
                html.Br(), html.Br()
            ]) for i in range(n)]

@app.callback(
    Output("w-status","children"),
    Output("w-session","data"),
    Output("progress-container","style"),
    Input("w-start","n_clicks"),
    State("w-stage","value"), State("w-substance","value"), State("w-flow","value"),
    State("w-duration","value"), State("w-interval","value"),
    State({"type":"board-id","index":ALL},"value"), State({"type":"board-com","index":ALL},"value"),
    prevent_initial_call=True)
def start_multi_capture(n, stage, sub, flow, dur, inter, boards, coms):
    if not all([stage, sub, flow, dur, inter]) or not all(boards) or not all(coms):
        return "⚠️ Please complete all fields.", None, {"display":"none"}
    sub = sub.title()
    keys = []
    for board, com in zip(boards, coms):
        k = start_capture_thread(stage=stage, substance=sub, flowrate=float(flow),
                                 duration_minutes=float(dur), interval_seconds=float(inter),
                                 board_number=board, com_port=f"COM{int(com)}")
        keys.append(k)
    return f"✅ Capture started on boards: {', '.join(boards)}", keys, {"width":"100%","background":"#ddd","marginTop":"10px"}

@app.callback(
    Output("progress-fill","style"),
    Input("progress-interval","n_intervals"), State("w-session","data"),
    prevent_initial_call=True)
def update_bar(_n, keys):
    if not keys: return {"display":"none"}
    avg = sum(CAPTURE_PROGRESS.get(k,0) for k in keys) / len(keys)
    return {"height":"25px","width":f"{avg}%","background":"#28a745",
            "color":"white","textAlign":"center","display":"block"}

# ───────────── Read & Plot ─────────────
def read():
    return html.Div([nav(),
        html.H3("Plot historical data", style={"textAlign":"center","marginTop":"25px"}),
        html.Div([
            html.Label("Project Stage"),
            dcc.Dropdown(id="r-stage",
                         options=[{"label":s,"value":s} for s in PREFIX_MAP],
                         placeholder="Select stage"),
            html.Br(),
            html.Label("Substance"),
            dcc.Dropdown(id="r-substance", placeholder="Select substance"),
            html.Br(),
            html.Label("Flowrate"),
            dcc.Dropdown(id="r-flow", placeholder="Select flowrate"),
            html.Br(),
            dcc.Graph(id="r-graph")
        ], style={"maxWidth":"600px","margin":"auto","marginTop":"30px"})
    ])

@app.callback(Output("r-substance","options"), Input("r-stage","value"))
def sub_opts(stage):
    return [{"label":s,"value":s} for s in get_substance_options(stage)] if stage else []

@app.callback(Output("r-flow","options"),
    Input("r-stage","value"), Input("r-substance","value"))
def flow_opts(stage, sub):
    if not (stage and sub): return []
    csv = os.path.join(stage, sub, f"{sub}_Readings.csv")
    if not os.path.isfile(csv): return []
    df = pd.read_csv(csv)
    return [{"label":f"{f} L/min","value":f} for f in sorted(df["Flowrate (L/min)"].dropna().unique())]

@app.callback(Output("r-graph","figure"),
    Input("r-flow","value"), State("r-stage","value"), State("r-substance","value"))
def plot(flow, stage, sub):
    if not all([stage, sub, flow]): return go.Figure()
    csv = os.path.join(stage, sub, f"{sub}_Readings.csv")
    if not os.path.isfile(csv): return go.Figure()
    df = pd.read_csv(csv); df["Timestamp"]=pd.to_datetime(df["Timestamp"])
    df = df[df["Flowrate (L/min)"]==flow]

    volt_cols=[c for c in df.columns if c.endswith("(V)") and not any(x in c for x in ("Temperature","Humidity","Pressure","BME688"))]
    fig=make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                      row_heights=[0.45,0.2,0.2,0.15],
                      subplot_titles=[f"{stage} — {sub} @ {flow} L/min","Temperature","Humidity","Pressure"])
    for b in df["Board"].dropna().unique():
        d = df[df["Board"]==b]
        for c in volt_cols:
            fig.add_trace(go.Scatter(x=d["Timestamp"],y=d[c],name=f"{c.replace(' (V)','')} [{b}]",
                                     mode="lines"),row=1,col=1)
    for full,(row,label) in {
        "BME688 - temperature (°C)":(2,"Temperature"),
        "BME688 - humidity (%)":    (3,"Humidity"),
        "BME688 - pressure (KPa)":  (4,"Pressure")}.items():
        if full in df.columns:
            fig.add_trace(go.Scatter(x=df["Timestamp"],y=df[full],name=label,mode="lines"),row=row,col=1)
    fig.update_yaxes(title_text="Voltage (V)",row=1,col=1,range=[0,5])
    fig.update_xaxes(title_text="Time",row=4,col=1)
    fig.update_layout(height=900, legend=dict(orientation="h"))
    return fig

app.layout = html.Div([dcc.Location(id="url"), html.Div(id="page")])
@app.callback(Output("page","children"), Input("url","pathname"))
def router(path): return write() if path=="/write" else read() if path=="/read" else home()

def home():
    return html.Div([nav(),
        html.H2("eNose Dashboard", style={"textAlign":"center", "marginTop":"40px"}),
        html.Div([
            html.A("→ Go to Write Data", href="/write",
                   style={"marginRight":"40px","fontSize":"20px"}),
            html.A("→ Go to Read / Plot", href="/read", style={"fontSize":"20px"})
        ], style={"textAlign":"center","marginTop":"60px"})])

# ─────────────────────────── main ───────────────────────────
if __name__=="__main__":
    arg=argparse.ArgumentParser(); arg.add_argument("--debug",action="store_true"); a=arg.parse_args()
    url="http://127.0.0.1:8050/"; print(f"⇢ Dashboard running on {url}")
    try: webbrowser.open(url)
    except: pass
    app.run(debug=a.debug, port=8050)
