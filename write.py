#write.py 
from datetime import datetime

from dash import html, dcc, Input, Output, State
from dash.dependencies import ALL

import b_write
import lb_write

PREFIX_MAP = {"Testing": "T", "Experiment": "E", "Deployment": "D", "Baseline": "B"}

def _stage_letter(stage: str) -> str: return PREFIX_MAP.get(stage, "X")

def _make_test_id(stage: str, substance: str) -> str:
    stage_letter = _stage_letter(stage)
    sub = "baseline" if stage == "Baseline" else (substance or "").title()
    tstamp = datetime.now().strftime("%H-%M-%S %d-%m-%Y")
    return f"{stage_letter}_{sub}_{tstamp}"

def _board_row(board_id: str, lbl: str):
    return html.Div([
        dcc.Checklist(options=[{"label": f" Enable {board_id}", "value": "on"}],
                      value=[], id={"type":"w-enable","index":board_id},
                      style={"display":"inline-block","width":"40%"}),
        html.Span("COM", style={"marginRight":"6px"}),
        dcc.Input(type="number", min=1, placeholder="e.g., 8",
                  id={"type":"w-com","index":board_id}, style={"width":"90px"}),
        html.Span(f"({lbl})", style={"marginLeft":"10px","color":"#666"})
    ], style={"display":"flex","alignItems":"center","gap":"6px","marginTop":"6px"})

def layout(nav):
    return html.Div([
        nav(),
        html.H3("Write Data (starts both B and LB engines)", style={"textAlign":"center","marginTop":"20px"}),
        html.Div([
            html.Label("Project Stage"),
            dcc.Dropdown(id="w-stage", options=[{"label": s, "value": s} for s in PREFIX_MAP],
                         placeholder="Select stage"),
            html.Br(), html.Div(id="w-substance-wrap"),
            html.Label("Flow-rate (L/min)"), dcc.Input(id="w-flow", type="number", min=0.1, step=0.1),
            html.Br(), html.Br(),
            html.Label("Duration (minutes)"), dcc.Input(id="w-duration", type="number", min=0.1, step=0.1),
            html.Br(), html.Br(),
            html.Label("Interval between readings (s)"), dcc.Input(id="w-interval", type="number", min=0.2, step=0.2, value=1.0),
            html.Hr(), html.H4("Boards"),
            _board_row("B1","Arduino"), _board_row("B2","Arduino"),
            _board_row("LB1","Libelium"), _board_row("LB2","Libelium"),
            html.Br(),
            html.Button("Start Capture", id="w-start", n_clicks=0,
                        style={"background":"#28a745","color":"white","padding":"8px 22px","border":"none"}),
            html.Button("Stop", id="w-stop", n_clicks=0,
                        style={"background":"#dc3545","color":"white","padding":"8px 22px","border":"none","marginLeft":"10px"}),
            html.Div(id="w-status", style={"marginTop":"15px","fontWeight":"bold"}),
            html.Div([ html.Div(id="w-progress-fill",
                                style={"height":"22px","width":"0%","background":"#28a745",
                                       "color":"white","textAlign":"center","fontSize":"12px"}) ],
                     id="w-progress-container", style={"width":"100%","background":"#e9ecef","marginTop":"10px","display":"none"}),
            html.Div(id="w-board-status", style={"marginTop":"10px","fontFamily":"monospace","whiteSpace":"pre-wrap"})
        ], style={"maxWidth":"560px","margin":"auto"}),
        dcc.Interval(id="w-tick", interval=750, n_intervals=0),
        dcc.Store(id="w-session")
    ])

def register_callbacks(app):
    @app.callback(Output("w-substance-wrap","children"), Input("w-stage","value"))
    def _substance_field(stage):
        if stage=="Baseline": return html.Div()
        return html.Div([html.Label("Substance"), dcc.Input(id="w-substance", type="text", placeholder="e.g. Ethanol"), html.Br(), html.Br()])

    @app.callback(
        Output("w-status","children"),
        Output("w-progress-container","style"),
        Output("w-session","data"),
        Input("w-start","n_clicks"),
        State("w-stage","value"), State("w-substance","value"),
        State("w-flow","value"), State("w-duration","value"), State("w-interval","value"),
        State({"type":"w-enable","index":ALL}, "value"), State({"type":"w-enable","index":ALL}, "id"),
        State({"type":"w-com","index":ALL}, "value"),  State({"type":"w-com","index":ALL}, "id"),
        prevent_initial_call=True
    )
    def _start(_n, stage, substance, flow, dur_min, inter_s, enabled_vals, enabled_ids, com_vals, com_ids):
        b_write.stop_capture(); lb_write.stop_capture()
        if not all([stage, flow, dur_min, inter_s]): return "Please complete stage, flow-rate, duration and interval.", {"display":"none"}, None
        if stage!="Baseline" and not (substance and substance.strip()): return "Substance is required for non-Baseline stages.", {"display":"none"}, None

        enabled_map = {e["index"]:("on" in v) for v,e in zip(enabled_vals, enabled_ids)}
        com_map = {e["index"]:(f"COM{int(v)}" if v else None) for v,e in zip(com_vals, com_ids)}
        ports_b  = {b:(com_map.get(b) if enabled_map.get(b) else None) for b in ("B1","B2")}
        ports_lb = {b:(com_map.get(b) if enabled_map.get(b) else None) for b in ("LB1","LB2")}
        if not any(ports_b.values()) and not any(ports_lb.values()):
            return "Please enable at least one board and provide its COM port.", {"display":"none"}, None

        duration_sec = int(float(dur_min)*60); flow=float(flow); inter=float(inter_s)
        sub_norm = None if stage=="Baseline" else substance.title()
        test_id = _make_test_id(stage, sub_norm or "baseline")

        if any(ports_b.values()):
            b_write.start_capture(stage=stage, substance=sub_norm, test_id=test_id,
                                  flowrate=flow, duration_sec=duration_sec, interval=inter, ports=ports_b)
        if any(ports_lb.values()):
            lb_write.start_capture(stage=stage, substance=sub_norm, test_id=test_id,
                                   flowrate=flow, interval=inter, ports=ports_lb, duration_sec=duration_sec)

        extra = " (LB may take ~2–3 min to warm up)" if any(ports_lb.values()) else ""
        status = f"Capture started. test_id: {test_id}. B: {', '.join([k for k,v in ports_b.items() if v]) or '-'}; LB: {', '.join([k for k,v in ports_lb.items() if v]) or '-'}{extra}"
        return status, {"width":"100%","background":"#e9ecef","marginTop":"10px"}, {"running":True,"test_id":test_id}

    @app.callback(
        Output("w-progress-fill","style"),
        Output("w-board-status","children"),
        Input("w-tick","n_intervals"), State("w-session","data"),
        prevent_initial_call=True
    )
    def _tick(_n, sess):
        if not sess or not sess.get("running"): return {"display":"none"}, ""
        b_snap = b_write.snapshot(); lb_snap = lb_write.snapshot()
        pct = b_snap.get("pct",0) or 0
        style = {"height":"22px","width":f"{pct}%","background":"#28a745","color":"white","textAlign":"center","fontSize":"12px","display":"block"}
        if b_snap.get("first_read_epoch") is None: style["width"]="0%"
        lines=[]
        if b_snap.get("first_read_epoch") is None: lines.append("B-family: waiting for first reading...")
        lines.extend(b_snap.get("status_lines",[])); lines.extend(lb_snap.get("status_lines",[]))
        return style, "\n".join([ln for ln in lines if ln])

    @app.callback(Output("w-status","children", allow_duplicate=True), Input("w-stop","n_clicks"), prevent_initial_call=True)
    def _stop(_n):
        b_write.stop_capture(); lb_write.stop_capture()
        return "Stopped capture for B and LB."
