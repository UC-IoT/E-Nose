#realtime.py


import os, re, json, threading, time
from datetime import datetime
from typing import Dict, Optional, List, Tuple

import pandas as pd
import serial
from dash import dcc, html, Input, Output, State
from dash.dependencies import ALL
import plotly.graph_objs as go

import b_write
import lb_write

PREFIX_MAP = {"Testing": "T", "Experiment": "E", "Deployment": "D", "Baseline": "B"}
BAUD_ARDUINO = 9600

_PREVIEW_THREADS: Dict[str, Tuple[threading.Thread, threading.Event]] = {}
_LIVE_DATA: Dict[str, List[dict]] = {"B1": [], "B2": []}

def _clean_text(s: str) -> str:
    return re.sub(r"[^\x00-\x7F°]", "", s or "")

def _extract_numeric(value: str) -> str:
    return re.sub(r"[^\d\.]+", "", value or "")

def _stage_letter(stage: str) -> str:
    return PREFIX_MAP.get(stage, "X")

def _make_test_id(stage: str, substance: Optional[str]) -> str:
    sub = "baseline" if stage == "Baseline" else (substance or "").title()
    return f"{_stage_letter(stage)}_{sub}_{datetime.now().strftime('%H-%M-%S %d-%m-%Y')}"

def _prime_firebase() -> str:
    try:
        import firebase_admin
        from firebase_admin import credentials

        if firebase_admin._apps:
            return "online"

        db_url = os.getenv("DATABASE_URL") or os.getenv("databaseURL")
        if not db_url:
            return "offline: no DATABASE_URL"

        key_blob = os.getenv("FIREBASE_KEY")
        if key_blob:
            svc = json.loads(key_blob)
            if "private_key" in svc and isinstance(svc["private_key"], str):

                svc["private_key"] = svc["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(svc)
        else:
            key_path = (
                os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                or os.getenv("FIREBASE_CREDENTIALS_PATH")
                or "serviceAccountKey.json"
            )
            cred = credentials.Certificate(key_path)

        firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        print("[Firebase] Initialized (realtime)")
        return "online"
    except Exception as e:
        print(f"[Firebase init error (realtime)] {e}")
        return f"offline: {e}"

#B1/B2 live preview
def _b_preview_reader(board_id: str, com_port: str, stop_evt: threading.Event):
    ser = None
    try:
        ser = serial.Serial(com_port, BAUD_ARDUINO, timeout=1)
        time.sleep(1.5)
        print(f"[Preview] {board_id} opened {com_port}")
    except Exception as e:
        print(f"[Preview ERROR] Could not open {com_port} for {board_id}: {e}")
        return

    current = {}
    try:
        while not stop_evt.is_set():
            try:
                raw = ser.readline().decode("utf-8", errors="ignore")
            except Exception:
                time.sleep(0.1); continue

            line = _clean_text((raw or "").strip())
            if not line:
                continue

            if line == "New Data":
                if current:
                    row = {"Timestamp": datetime.now()}
                    row.update(current)
                    _LIVE_DATA.setdefault(board_id, []).append(row)
                current = {}
                continue

            parts = [p.strip() for p in line.split(":", maxsplit=1)]
            if len(parts) != 2:
                continue
            key, val = parts
            val_clean = val.strip()

            m = re.search(r"([\d\.]+)\s*(ppm|ppb|%)", val_clean, re.IGNORECASE)
            if m:
                value = float(m.group(1)); unit = m.group(2).lower()
                current[f"{board_id} - {key.strip()} ({unit})"] = value
                continue

            if re.match(r"^(TGS|MQ)", key.strip(), re.IGNORECASE):
                try:
                    value = float(_extract_numeric(val_clean))
                    current[f"{board_id} - {key.strip()} (raw)"] = value
                except Exception:
                    pass
                continue

            if val_clean.endswith("V"):
                try:
                    v = float(val_clean[:-1].strip())
                    current[f"{board_id} - {key.strip()} - V"] = v
                    continue
                except Exception:
                    pass

            current[f"{board_id} - {key.strip()}"] = val_clean
    finally:
        try:
            if ser and ser.is_open:
                ser.close()
                print(f"[Preview] {board_id} closed {com_port}")
        except Exception:
            pass

def _board_row(board_id: str, default_baud_label: str):
    return html.Div([
        dcc.Checklist(
            options=[{"label": f" Enable {board_id}", "value": "on"}],
            value=[],
            id={"type": "rt-enable", "index": board_id},
            style={"display": "inline-block", "width": "40%"}
        ),
        html.Span("COM", style={"marginRight": "6px"}),
        dcc.Input(type="number", min=1, placeholder="e.g., 8",
                  id={"type": "rt-com", "index": board_id},
                  style={"width": "90px"}),
        html.Span(f"({default_baud_label})", style={"marginLeft": "10px", "color": "#666"})
    ], style={"display": "flex", "alignItems": "center", "gap": "6px", "marginTop": "6px"})

# ---------- Layout ----------
def layout(nav):
    return html.Div([
        nav(),
        html.H3("Live Data (B1/B2 graphs) + Capture (B & LB engines)",
                style={"textAlign": "center", "marginTop": "20px"}),

        html.Div([
            html.Label("Project Stage"),
            dcc.Dropdown(id="rt-stage",
                         options=[{"label": s, "value": s} for s in PREFIX_MAP],
                         placeholder="Select stage"),

            html.Br(),
            html.Div(id="rt-substance-wrap"),

            html.Label("Flow-rate (L/min)"),
            dcc.Input(id="rt-flow", type="number", min=0.1, step=0.1),

            html.Br(), html.Br(),
            html.Label("Duration (minutes)"),
            dcc.Input(id="rt-duration", type="number", min=0.1, step=0.1),

            html.Br(), html.Br(),
            html.Label("Interval between readings (s)"),
            dcc.Input(id="rt-interval", type="number", min=0.2, step=0.2, value=1.0),

            html.Hr(),
            html.H4("Boards"),
            _board_row("B1", "Arduino"),
            _board_row("B2", "Arduino"),
            _board_row("LB1", "Libelium"),
            _board_row("LB2", "Libelium"),

            html.Br(),
            html.Button("Preview Live Data (B1/B2)", id="rt-preview", n_clicks=0,
                        style={"background": "#0d6efd", "color": "white", "padding": "8px 22px", "border": "none"}),
            html.Button("Start Capture", id="rt-start", n_clicks=0,
                        style={"background": "#28a745", "color": "white", "padding": "8px 22px",
                               "border": "none", "marginLeft": "10px"}),
            html.Button("Stop", id="rt-stop", n_clicks=0,
                        style={"background": "#dc3545", "color": "white", "padding": "8px 22px",
                               "border": "none", "marginLeft": "10px"}),

            html.Div(id="rt-status", style={"marginTop": "15px", "fontWeight": "bold"}),

            html.Div([
                html.Div(id="rt-progress-fill",
                         style={"height": "22px", "width": "0%", "background": "#28a745",
                                "color": "white", "textAlign": "center", "fontSize": "12px"})
            ], id="rt-progress-container",
               style={"width": "100%", "background": "#e9ecef", "marginTop": "10px", "display": "none"}),

            html.Div(id="rt-board-status",
                     style={"marginTop": "10px", "fontFamily": "monospace", "whiteSpace": "pre-wrap"})
        ], style={"maxWidth": "560px", "margin": "auto"}),

        html.Hr(),
        html.H4("Realtime B1 / B2"),
        html.Div(id="rt-graphs", style={"marginTop": "10px"}),

        dcc.Interval(id="rt-tick", interval=750, n_intervals=0),
        dcc.Interval(id="rt-plot-tick", interval=2000, n_intervals=0),
        dcc.Store(id="rt-session"),
        dcc.Store(id="rt-preview-running")
    ])

#Callbacks
def register_callbacks(app):

    @app.callback(
        Output("rt-substance-wrap", "children"),
        Input("rt-stage", "value")
    )
    def _substance_field(stage):
        if stage == "Baseline":
            return html.Div()
        return html.Div([
            html.Label("Substance"),
            dcc.Input(id="rt-substance", type="text", placeholder="e.g. Ethanol"),
            html.Br(), html.Br()
        ])

    @app.callback(
        Output("rt-status", "children"),
        Output("rt-preview-running", "data"),
        Input("rt-preview", "n_clicks"),
        State("rt-stage", "value"),
        State("rt-substance", "value"),
        State({"type": "rt-enable", "index": ALL}, "value"),
        State({"type": "rt-enable", "index": ALL}, "id"),
        State({"type": "rt-com", "index": ALL}, "value"),
        State({"type": "rt-com", "index": ALL}, "id"),
        prevent_initial_call=True
    )
    def _preview(_n, stage, substance, enabled_vals, enabled_ids, com_vals, com_ids):
        enabled_map = {e["index"]: ("on" in v) for v, e in zip(enabled_vals, enabled_ids)}
        com_map = {e["index"]: (f"COM{int(v)}" if v else None) for v, e in zip(com_vals, com_ids)}

        preview_ports = {b: com_map.get(b) for b in ("B1", "B2")
                         if enabled_map.get(b) and com_map.get(b)}
        if not preview_ports:
            return "To preview graphs, enable B1/B2 and set their COM ports.", {}

        for bid, port in preview_ports.items():
            if bid not in _PREVIEW_THREADS:
                stop_evt = threading.Event()
                t = threading.Thread(target=_b_preview_reader, args=(bid, port, stop_evt), daemon=True)
                _PREVIEW_THREADS[bid] = (t, stop_evt)
                t.start()

        sub = "baseline" if stage == "Baseline" else (substance or "").title()
        return f"Preview running for {', '.join(preview_ports.keys())} — Stage: {stage}, Substance: {sub}", {
            "previewing": list(preview_ports.keys())
        }

    def _stop_preview_for(b_boards: List[str]):
        for bid in b_boards:
            tup = _PREVIEW_THREADS.get(bid)
            if not tup:
                continue
            t, stop_evt = tup
            try:
                stop_evt.set()
                t.join(timeout=2.0)
            except Exception:
                pass
            _PREVIEW_THREADS.pop(bid, None)

    @app.callback(
        Output("rt-status", "children", allow_duplicate=True),
        Output("rt-progress-container", "style"),
        Output("rt-session", "data"),
        Input("rt-start", "n_clicks"),
        State("rt-stage", "value"),
        State("rt-substance", "value"),
        State("rt-flow", "value"),
        State("rt-duration", "value"),
        State("rt-interval", "value"),
        State({"type": "rt-enable", "index": ALL}, "value"),
        State({"type": "rt-enable", "index": ALL}, "id"),
        State({"type": "rt-com", "index": ALL}, "value"),
        State({"type": "rt-com", "index": ALL}, "id"),
        State("rt-preview-running", "data"),
        prevent_initial_call=True
    )
    def _start_capture(_n, stage, substance, flow, dur_min, inter_s,
                       enabled_vals, enabled_ids, com_vals, com_ids, preview_running):
        b_write.stop_capture()
        lb_write.stop_capture()

        if not all([stage, flow, dur_min, inter_s]):
            return "Please complete stage, flow-rate, duration and interval.", {"display": "none"}, None
        if stage != "Baseline" and not (substance and substance.strip()):
            return "Substance is required for non-Baseline stages.", {"display": "none"}, None

        enabled_map = {e["index"]: ("on" in v) for v, e in zip(enabled_vals, enabled_ids)}
        com_map = {e["index"]: (f"COM{int(v)}" if v else None) for v, e in zip(com_vals, com_ids)}

        ports_b = {b: (com_map.get(b) if enabled_map.get(b) else None) for b in ("B1", "B2")}
        ports_lb = {b: (com_map.get(b) if enabled_map.get(b) else None) for b in ("LB1", "LB2")}

        if not any(ports_b.values()) and not any(ports_lb.values()):
            return "Please enable at least one board and provide its COM port.", {"display": "none"}, None

        to_stop = [k for k, v in ports_b.items() if v]
        _stop_preview_for(to_stop)

        duration_sec = int(float(dur_min) * 60)
        flow = float(flow); inter = float(inter_s)
        sub_norm = None if stage == "Baseline" else (substance or "").title()
        test_id = _make_test_id(stage, sub_norm or "baseline")

        fb_status = _prime_firebase()
        fb_line = f"Firebase: {fb_status}"

        if any(ports_b.values()):
            b_write.start_capture(stage=stage, substance=sub_norm, test_id=test_id,
                                  flowrate=flow, duration_sec=duration_sec,
                                  interval=inter, ports=ports_b)
        if any(ports_lb.values()):
            lb_write.start_capture(stage=stage, substance=sub_norm, test_id=test_id,
                                   flowrate=flow, interval=inter, ports=ports_lb,
                                   duration_sec=duration_sec)

        extra = " (LB may take ~2–3 min to warm up)" if any(ports_lb.values()) else ""
        status = f"{fb_line}\nCapture started. test_id: {test_id}. " \
                 f"B: {', '.join([k for k,v in ports_b.items() if v]) or '-'}; " \
                 f"LB: {', '.join([k for k,v in ports_lb.items() if v]) or '-'}{extra}"

        return status, {"width": "100%", "background": "#e9ecef", "marginTop": "10px"}, {
            "running": True,
            "test_id": test_id
        }

    @app.callback(
        Output("rt-status", "children", allow_duplicate=True),
        Input("rt-stop", "n_clicks"),
        prevent_initial_call=True
    )
    def _stop(_n):
        b_write.stop_capture()
        lb_write.stop_capture()
        for bid in list(_PREVIEW_THREADS.keys()):
            t, ev = _PREVIEW_THREADS.pop(bid)
            try:
                ev.set(); t.join(timeout=2.0)
            except Exception:
                pass
        return "Stopped capture for B and LB."

    @app.callback(
        Output("rt-progress-fill", "style"),
        Output("rt-board-status", "children"),
        Input("rt-tick", "n_intervals"),
        State("rt-session", "data"),
        prevent_initial_call=True
    )
    def _tick(_n, sess):
        if not sess or not sess.get("running"):
            return {"display": "none"}, ""

        b_snap = b_write.snapshot()
        lb_snap = lb_write.snapshot()

        pct = b_snap.get("pct", 0) or 0
        style = {
            "height": "22px",
            "width": f"{pct}%",
            "background": "#28a745",
            "color": "white",
            "textAlign": "center",
            "fontSize": "12px",
            "display": "block"
        }
        if b_snap.get("first_read_epoch") is None:
            style["width"] = "0%"
        lines: List[str] = []
   
        fb = _prime_firebase()
        if fb:
            lines.append(f"Firebase: {fb}")

        if b_snap.get("first_read_epoch") is None:
            lines.append("B-family: waiting for first reading...")
        for ln in (b_snap.get("status_lines", []) + lb_snap.get("status_lines", [])):
            if ln and ln not in lines:
                lines.append(ln)

        return style, "\n".join(lines)

    @app.callback(
        Output("rt-graphs", "children"),
        Input("rt-plot-tick", "n_intervals"),
        prevent_initial_call=True
    )
    def _update_graphs(_n):
        graphs = []

        for b in ("B1", "B2"):
            if not _LIVE_DATA.get(b):
                continue
            df = pd.DataFrame(_LIVE_DATA[b])
            if df.empty or "Timestamp" not in df.columns:
                continue

            df["Timestamp"] = pd.to_datetime(df["Timestamp"])
            df = df.sort_values("Timestamp")
            t0 = df["Timestamp"].min()

            for col in df.columns:
                if col == "Timestamp":
                    continue
                if not any(tok in col.lower() for tok in ["ppm", "ppb", "(raw)", "- v"]):
                    continue

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=(df["Timestamp"] - t0).dt.total_seconds(),
                    y=df[col], mode="lines+markers", name="Live"
                ))
                if col.endswith("(raw)"):
                    fig.update_yaxes(range=[0, 1023])
                if col.lower().endswith("- v"):
                    fig.update_yaxes(range=[0, 5])
                fig.update_layout(
                    title=col,
                    xaxis_title="Elapsed time (s) — full session",
                    yaxis_title="Value",
                    margin=dict(l=40, r=10, t=50, b=40),
                    height=350
                )
                graphs.append(html.Div([dcc.Graph(figure=fig)],
                                       style={"width": "48%", "display": "inline-block", "margin": "1%"}))
        return graphs
