from __future__ import annotations

import argparse
import json
import os
import threading
import webbrowser
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import plotly.graph_objects as go
from dash import ALL, MATCH, Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update

from core.capture import CaptureManager
from core.diagnostics import BoardHealthManager
from core.firebase_client import FirebaseClient
from core.models import SessionSpec, minutes_to_seconds
from core.registry import BoardRegistry, SUPPORTED_PARSERS, discover_serial_ports
from core.storage import discover_legacy_csvs, discover_sessions, make_session_id


ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
LEGACY_ROOT = ROOT.parent
REGISTRY = BoardRegistry(ROOT / "config" / "boards.json")
FIREBASE = FirebaseClient(ROOT)
CAPTURE = CaptureManager(REGISTRY, DATA_ROOT, FIREBASE)
HEALTH = BoardHealthManager(REGISTRY)
threading.Thread(target=FIREBASE.check_connection, daemon=True, name="firebase-startup-check").start()

NAV_ITEMS = [
    ("Overview", "/", "◈"),
    ("Capture", "/capture", "●"),
    ("Live", "/live", "⌁"),
    ("Sessions", "/sessions", "▤"),
    ("Research", "/research", "⌁"),
    ("Baselines", "/baselines", "◎"),
    ("Boards", "/boards", "⬡"),
    ("Firebase", "/firebase", "↻"),
    ("Guide", "/guide", "?"),
]


def card(title: str, value: Any, detail: str = "", tone: str = "teal") -> html.Div:
    return html.Div(
        [html.Div(title, className="metric-label"), html.Div(str(value), className=f"metric-value {tone}"), html.Div(detail, className="metric-detail")],
        className="metric-card",
    )


def section(title: str, description: str, children: List[Any]) -> html.Div:
    return html.Div(
        [html.Div([html.H2(title), html.P(description)], className="section-heading"), *children],
        className="panel",
    )


def field(label: str, component: Any, hint: str = "") -> html.Div:
    return html.Div([html.Label(label), component, html.Small(hint) if hint else None], className="field")


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, remaining = divmod(total, 60)
    return f"{minutes}m {remaining:02d}s" if minutes else f"{remaining}s"


def battery_indicator(percent: Any, volts: Any) -> html.Div:
    if percent is None and volts is None:
        return html.Div("Battery: waiting for Libelium telemetry", className="battery-waiting")
    try:
        level = max(0.0, min(100.0, float(percent))) if percent is not None else 0.0
    except (TypeError, ValueError):
        level = 0.0
    parts = [f"{level:.0f}%" if percent is not None else "percentage unavailable"]
    if volts is not None:
        try:
            parts.append(f"{float(volts):.2f} V")
        except (TypeError, ValueError):
            pass
    tone = "low" if level < 20 else ""
    return html.Div(
        [
            html.Div([html.Span("Battery"), html.Strong(" · ".join(parts))], className="battery-label"),
            html.Div(html.Div(className=f"battery-fill {tone}", style={"width": f"{level}%"}), className="battery-track"),
        ],
        className="battery-readout",
    )


def board_graph_group(board_id: str, graphs: List[Any]) -> html.Details:
    name = REGISTRY.all().get(board_id, {}).get("name", board_id)
    return html.Details(
        [
            html.Summary([html.H2(board_id), html.Span(name), html.Span("Expand / collapse", className="collapse-hint")], className="board-group-heading"),
            html.Div(graphs, className="sensor-graph-grid"),
        ],
        open=True,
        className="board-graph-group",
    )


def board_capture_controls() -> List[html.Div]:
    port_options = discover_serial_ports()
    rows = []
    for board_id, board in REGISTRY.all(enabled_only=True).items():
        rows.append(
            html.Div(
                [
                    dcc.Checklist(
                        id={"type": "capture-enable", "index": board_id},
                        options=[{"label": "", "value": "on"}],
                        value=[],
                        className="board-toggle",
                    ),
                    html.Div([html.Strong(board_id), html.Span(board["name"])], className="board-identity"),
                    html.Div([html.Span(board["parser"].replace("_", " ")), html.Span(f"{board['baud']} baud")], className="board-tags"),
                    dcc.Dropdown(
                        id={"type": "capture-port", "index": board_id},
                        options=port_options,
                        placeholder="Select COM port",
                        clearable=True,
                        className="port-select",
                    ),
                ],
                className="board-row",
            )
        )
    return rows


def board_health_controls() -> List[html.Div]:
    port_options = discover_serial_ports()
    return [
        html.Div(
            [
                dcc.Checklist(
                    id={"type": "health-enable", "index": board_id},
                    options=[{"label": "", "value": "on"}],
                    value=["on"],
                    className="board-toggle",
                ),
                html.Div([html.Strong(board_id), html.Span(board["name"])], className="board-identity"),
                dcc.Dropdown(
                    id={"type": "health-port", "index": board_id},
                    options=port_options,
                    placeholder="Select COM port",
                    clearable=True,
                    className="port-select",
                ),
            ],
            className="health-row",
        )
        for board_id, board in REGISTRY.all(enabled_only=True).items()
    ]


def baseline_options() -> List[Dict[str, str]]:
    return [
        {"label": f"{row['session_id']} · {row['boards']}", "value": row["session_id"]}
        for row in discover_sessions(DATA_ROOT)
        if (row["type"] == "baseline" or row["stage"] == "Baseline") and row["status"] in {"completed", "stopped"}
    ]


def session_rows() -> List[Dict[str, Any]]:
    return discover_sessions(DATA_ROOT)


def navigation(pathname: str = "/") -> html.Nav:
    return html.Nav(
        [
            html.A(
                f"{icon}  {label}",
                href=path,
                target="enose_capture" if path == "/capture" else "enose_secondary",
                className="nav-link active" if pathname == path else "nav-link",
                title=("Switch to the Capture tab" if path == "/capture" else f"Open {label} in the shared dashboard tab"),
            )
            for label, path, icon in NAV_ITEMS
        ],
        className="nav-links",
    )


def overview_layout() -> html.Div:
    sessions = session_rows()
    enabled = REGISTRY.all(enabled_only=True)
    baseline_count = sum(1 for item in sessions if item["type"] == "baseline" or item["stage"] == "Baseline")
    return html.Div(
        [
            html.Div(
                [
                    card("Configured boards", len(enabled), "Registry-driven hardware", "teal"),
                    card("V2 sessions", len(sessions), "Independent board files", "blue"),
                    card("Baselines", baseline_count, "Reusable reference captures", "green"),
                    card("Firebase", FIREBASE.message, "Local capture works offline", "amber"),
                ],
                className="metrics-grid",
                id="overview-metrics",
            ),
            section(
                "System overview",
                "The V2 pipeline isolates every board while keeping capture, plotting and cloud sync configuration-driven.",
                [
                    html.Div(
                        [
                            html.Div([html.H3("1. Connect"), html.P("Plug in the boards, then open Capture and press Refresh COM ports."), html.A("Open Capture", href="/capture", target="_blank", className="button primary")], className="feature-card"),
                            html.Div([html.H3("2. Record"), html.P("Choose the boards, enter a label and duration, then press Start. The progress bar shows time remaining."), html.A("Read the simple guide", href="/guide", target="_blank", className="button secondary")], className="feature-card"),
                            html.Div([html.H3("3. Review"), html.P("Open Live or Sessions in another tab. Capture keeps updating in its own tab."), html.A("Open Sessions", href="/sessions", target="_blank", className="button secondary")], className="feature-card"),
                        ],
                        className="feature-grid",
                    )
                ],
            ),
            section(
                "Recent V2 sessions",
                "Original datasets remain untouched and are not counted here.",
                [session_table("overview-session-table", sessions[:8])],
            ),
        ],
        className="page-content",
    )


def session_table(table_id: str, rows: List[Dict[str, Any]]) -> dash_table.DataTable:
    columns = [
        {"name": "Session", "id": "session_id"},
        {"name": "Type", "id": "type"},
        {"name": "Stage", "id": "stage"},
        {"name": "Substance", "id": "substance"},
        {"name": "Boards", "id": "boards"},
        {"name": "Status", "id": "status"},
        {"name": "Created", "id": "created"},
    ]
    return dash_table.DataTable(id=table_id, data=rows, columns=columns, page_size=8, sort_action="native", style_table={"overflowX": "auto"})


def capture_layout() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Strong("Simple capture: "),
                    html.Span("1. Plug boards in  →  2. Refresh ports  →  3. Select each COM port  →  4. Choose the capture type  →  5. Press Start"),
                    html.A("Open the full beginner guide", href="/guide", target="_blank", className="inline-link"),
                ],
                className="simple-instructions",
            ),
            section(
                "Capture setup",
                "",
                [
                    html.Div(
                        [
                            field("Capture type", dcc.RadioItems(id="capture-type", options=[{"label": name, "value": name.lower()} for name in ("Testing", "Experiment", "Deployment", "Baseline")], value="testing", inline=True)),
                            field("Substance / label", dcc.Input(id="capture-substance", value="", placeholder="e.g. Ethanol or Clean air", type="text")),
                            field("Flow rate (L/min)", dcc.Input(id="capture-flow", value=1.0, min=0, step=0.1, type="number")),
                            field(
                                "Duration (minutes)",
                                dcc.Input(
                                    id="capture-duration", value=5, min=0.1, step=0.1,
                                    type="number", persistence=True, persistence_type="session",
                                ),
                                "Enter 5 for five minutes. Decimals are allowed; 0.5 is 30 seconds.",
                            ),
                            field("Write interval (seconds)", dcc.Input(id="capture-interval", value=1, min=0.2, step=0.2, type="number")),
                            field("Warm-up countdown (seconds)", dcc.Input(id="capture-warmup", value=0, min=0, step=5, type="number"), "Recorded as session metadata; capture starts after the countdown."),
                            field("Reference baseline", dcc.Dropdown(id="capture-baseline", options=baseline_options(), placeholder="Optional baseline", clearable=True)),
                        ],
                        className="form-grid",
                    ),
                    field("Session notes", dcc.Textarea(id="capture-notes", placeholder="Sample preparation, conditions, operator notes…", className="textarea")),
                    html.Div("Timer duration: 5m 00s (300 seconds)", id="capture-duration-preview", className="duration-preview"),
                    html.Div([html.Div([html.H3("Boards and serial ports"), html.P("Enable only boards that are physically connected.")]), html.Button("Refresh COM ports", id="refresh-ports", className="button ghost")], className="row-between"),
                    html.Div(board_capture_controls(), id="capture-board-controls", className="board-list"),
                    html.Div(
                        [
                            html.Button("Start capture", id="capture-start", className="button primary", n_clicks=0),
                            html.Button("Pause / resume", id="capture-pause", className="button secondary", n_clicks=0),
                            html.Button("Stop", id="capture-stop", className="button danger", n_clicks=0),
                        ],
                        className="action-row",
                    ),
                    dcc.ConfirmDialog(
                        id="capture-background-warning",
                        message=(
                            "Capture is now running in the background. You may switch dashboard pages or close browser tabs. "
                            "Do not close the Python dashboard program, disconnect USB boards, or open these COM ports in "
                            "Waspmote/Arduino Serial Monitor until capture has stopped."
                        ),
                    ),
                    html.Div("Ready to configure a session.", id="capture-message", className="notice"),
                ],
            ),
            section(
                "Capture progress",
                "Capture continues in the background while the dashboard program remains running.",
                [
                    html.Div([html.Div(id="capture-progress-fill", className="progress-fill")], className="progress-track"),
                    html.Div("Not started", id="capture-progress-label", className="progress-label"),
                    html.Div(id="capture-status", className="status-grid"),
                ],
            ),
        ],
        className="page-content",
    )


def live_layout() -> html.Div:
    return html.Div(
        [section("Live monitor", "", [html.Div(id="live-empty", className="notice"), html.Div(id="live-graphs", className="board-graph-groups")])],
        className="page-content",
    )


def sessions_layout() -> html.Div:
    sessions = session_rows()
    options = [{"label": f"{row['session_id']} · {row['boards']}", "value": row["path"]} for row in sessions]
    legacy = discover_legacy_csvs(LEGACY_ROOT)
    return html.Div(
        [
            section("V2 sessions", "Choose a session. Results appear by board, with one graph for each recorded gas or sensor.", [session_table("sessions-table", sessions), field("Plot a session", dcc.Dropdown(id="session-select", options=options, placeholder="Select a V2 session")), html.Div(id="session-graphs", className="board-graph-groups")]),
            section("Legacy data compatibility", "", [html.P(f"Detected {len(legacy)} legacy CSV files under Testing, Experiment, Deployment and Baseline."), dash_table.DataTable(data=legacy[:200], columns=[{"name": "Stage", "id": "stage"}, {"name": "File", "id": "file"}, {"name": "Path", "id": "path"}], page_size=8, sort_action="native", style_table={"overflowX": "auto"})]),
        ],
        className="page-content",
    )


def research_layout() -> html.Div:
    sessions = session_rows()
    baseline_rows = [row for row in sessions if row["type"] == "baseline" or row["stage"] == "Baseline"]
    baseline_choices = [
        {"label": f"{row['session_id']} · {row['boards']}", "value": row["path"]}
        for row in baseline_rows
    ]
    session_choices = [
        {"label": f"{row['stage']} · {row['session_id']} · {row['boards']}", "value": row["path"]}
        for row in sessions
    ]
    return html.Div(
        [
            section(
                "Research comparison",
                "Overlay a selected clean-air baseline with any available session. Matching board sensors share one graph and use elapsed seconds for comparison.",
                [
                    html.Div(
                        [
                            field("Baseline", dcc.Dropdown(id="research-baseline", options=baseline_choices, placeholder="Select a baseline")),
                            field("Session", dcc.Dropdown(id="research-session", options=session_choices, placeholder="Select any session")),
                        ],
                        className="form-grid",
                    ),
                    html.Div("Select both datasets to create the comparison.", id="research-message", className="notice"),
                    html.Div(id="research-graphs", className="board-graph-groups"),
                ],
            )
        ],
        className="page-content",
    )


def baselines_layout() -> html.Div:
    rows = [row for row in session_rows() if row["type"] == "baseline" or row["stage"] == "Baseline"]
    return html.Div(
        [
            section(
                "Baseline library",
                "Baseline captures use the same reliable pipeline and save per-sensor quality statistics in summary.json.",
                [
                    html.Div([html.Div([html.Span("1", className="step-number"), html.Strong("Select Baseline on the Capture page")]), html.Div([html.Span("2", className="step-number"), html.Strong("Choose clean-air boards, duration and warm-up")]), html.Div([html.Span("3", className="step-number"), html.Strong("Capture, validate, then reuse it in experiments")])], className="steps"),
                    session_table("baseline-table", rows),
                ],
            )
        ],
        className="page-content",
    )


def boards_layout() -> html.Div:
    return html.Div(
        [
            section(
                "Check boards before capture",
                "This opens each selected COM port and waits for one complete sensor sample. It does not save data or create a Firebase session.",
                [
                    html.Div([html.Button("Refresh COM ports", id="refresh-health-ports", className="button ghost"), html.Span("Close Arduino Serial Monitor before testing.", className="muted")], className="row-between"),
                    html.Div(board_health_controls(), className="health-list"),
                    html.Button("Check selected boards", id="health-start", className="button primary", n_clicks=0),
                    html.Div("Choose the correct COM port for each enabled board, then run the check.", id="health-message", className="notice"),
                    html.Div(id="health-status", className="status-grid"),
                ],
            ),
            section(
                "Board Manager",
                "The registry is the single source of truth for capture, storage, live monitoring and Firebase naming.",
                [
                    dash_table.DataTable(id="board-table", data=REGISTRY.table_rows(), columns=[{"name": name, "id": key} for name, key in [("ID", "id"), ("Name", "name"), ("Baud", "baud"), ("Parser", "parser"), ("Firebase ID", "firebase"), ("Enabled", "enabled")]], page_size=10),
                    html.H3("Add or update a board"),
                    html.Div(
                        [
                            field("Board ID", dcc.Input(id="board-id", placeholder="B4", type="text")),
                            field("Display name", dcc.Input(id="board-name", placeholder="New sensor board", type="text")),
                            field("Baud rate", dcc.Input(id="board-baud", value=9600, min=1, step=1, type="number")),
                            field("Parser", dcc.Dropdown(id="board-parser", options=sorted(SUPPORTED_PARSERS), value="json_line", clearable=False)),
                            field("Firebase ID", dcc.Input(id="board-firebase", placeholder="Defaults to board ID", type="text")),
                            field("Enabled", dcc.RadioItems(id="board-enabled", options=[{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}], value="yes", inline=True)),
                        ],
                        className="form-grid",
                    ),
                    field("Notes", dcc.Input(id="board-notes", placeholder="Firmware, sensor set or deployment notes", type="text")),
                    html.Button("Save board", id="board-save", className="button primary", n_clicks=0),
                    html.Div(id="board-message", className="notice"),
                ],
            ),
            section("Supported protocols", "Choose a protocol already understood by the generic collector.", [html.Div([html.Div([html.H3("JSON line"), html.Code('{"CO2":{"value":450,"unit":"ppm"}}'), html.P("Recommended for B3 and all future firmware.")], className="feature-card"), html.Div([html.H3("Framed key/value"), html.Code("new data … sensor: value unit … *"), html.P("Compatibility with existing Arduino output.")], className="feature-card"), html.Div([html.H3("Libelium"), html.Code("new data … gas: value …"), html.P("Compatibility with current Libelium boards and battery lines.")], className="feature-card")], className="feature-grid")]),
        ],
        className="page-content",
    )


def sync_layout() -> html.Div:
    queue_files = list(DATA_ROOT.rglob("firebase_pending.jsonl")) if DATA_ROOT.exists() else []
    pending = sum(FIREBASE.queue_count(path) for path in queue_files)
    return html.Div(
        [section("Firebase", "Check the connection, retry anything stored offline, or open the Firebase database console.", [html.Div([card("Connection", FIREBASE.message), card("Pending records", pending), card("Database", "Configured" if FIREBASE.database_url else "Not configured", FIREBASE.database_url)], className="metrics-grid three"), html.Div([html.Button("Check Firebase connection", id="firebase-check", className="button secondary", n_clicks=0), html.Button("Retry pending records", id="sync-all", className="button primary", n_clicks=0), html.A("Visit Firebase console ↗", href=FIREBASE.console_url, target="_blank", rel="noopener", className="button external")], className="action-row"), html.Div(id="firebase-check-message", className="notice"), html.Div(id="sync-message", className="notice"), html.P("Your data is always written to local CSV first. If Firebase is unavailable, nothing is lost—the dashboard queues those records for retry.", className="muted")])],
        className="page-content",
    )


def documentation_layout() -> html.Div:
    return html.Div(
        [
            section(
                "How to capture data",
                "No technical knowledge is needed. Follow these steps in order.",
                [
                    html.Div(
                        [
                            guide_step("1", "Plug in the boards", "Connect every sensor board to the computer with USB. Wait a few seconds for Windows to recognise them."),
                            guide_step("2", "Open Capture", "Click Capture at the top. Capture stays in its own tab while the other dashboard pages share one second tab."),
                            guide_step("3", "Find COM ports in Windows", "Right-click the Windows Start button, open Device Manager, expand Ports (COM & LPT), and note the COM number shown for each connected board. Close Device Manager or any serial monitor that has opened a port."),
                            guide_step("4", "Refresh and select COM ports", "Press Refresh COM ports, then select the correct port beside each board. Selecting a port enables that board automatically. Never give two boards the same COM port."),
                            guide_step("5", "Choose the capture type", "Select Testing, Experiment, Deployment or Baseline. This choice decides where the session is stored; the separate Stage menu is no longer needed. Then enter the substance or sample name, duration and flow rate."),
                            guide_step("6", "Start", "Press Start capture. The progress bar moves from 0% to 100% and shows the remaining time."),
                            guide_step("7", "Watch or stop", "Open Live in the shared dashboard tab to see each gas separately. Capture continues in the background while the Python dashboard program remains running. Press Stop only if you need to end early."),
                            guide_step("8", "Find the result", "Open Sessions, select the completed session, and view the graphs grouped under B1, B2, B3 or the Libelium boards."),
                        ],
                        className="guide-steps",
                    )
                ],
            ),
            section(
                "Capture a baseline",
                "A baseline is a clean-air reference that can be compared with a later sample.",
                [html.Ol([html.Li("Open Capture and choose Baseline."), html.Li("Place the selected sensors in clean air."), html.Li("Choose the boards and COM ports exactly as above."), html.Li("Press Start and let the progress reach 100%."), html.Li("The baseline will appear automatically in the Reference Baseline list for later experiments.")], className="easy-list")],
            ),
            section(
                "Compare data for research",
                "Research overlays a clean-air baseline with any saved session.",
                [html.Ol([html.Li("Open Research from the navigation bar."), html.Li("Select a completed baseline."), html.Li("Select any Testing, Experiment, Deployment or Baseline session."), html.Li("Each matching board and sensor appears as an expandable graph group."), html.Li("The dashed blue line is the baseline and the solid light line is the selected session; both use elapsed seconds.")], className="easy-list")],
            ),
            section(
                "If something does not work",
                "These checks solve the most common capture problems.",
                [html.Div([html.Div([html.Strong("No COM ports"), html.P("Check the USB cable, wait five seconds and press Refresh COM ports again.")], className="help-card"), html.Div([html.Strong("Board says error"), html.P("Another program may be using that COM port. Close Arduino Serial Monitor and try again.")], className="help-card"), html.Div([html.Strong("Firebase says offline"), html.P("Keep capturing. Local CSV still works. Restore internet, open Firebase, then press Retry pending records.")], className="help-card"), html.Div([html.Strong("No graph yet"), html.P("Wait for the first complete board reading. B3 normally sends one reading about every three seconds.")], className="help-card")], className="help-grid")],
            ),
        ],
        className="page-content",
    )


def guide_step(number: str, title: str, description: str) -> html.Div:
    return html.Div([html.Span(number, className="step-number"), html.Div([html.H3(title), html.P(description)])], className="guide-step")


def render_page(pathname: str) -> html.Div:
    return {
        "/": overview_layout,
        "/capture": capture_layout,
        "/live": live_layout,
        "/sessions": sessions_layout,
        "/research": research_layout,
        "/baselines": baselines_layout,
        "/boards": boards_layout,
        "/firebase": sync_layout,
        "/guide": documentation_layout,
    }.get(pathname, overview_layout)()


def create_app() -> Dash:
    app = Dash(__name__, suppress_callback_exceptions=True, title="eNose V2")
    app.layout = html.Div(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Interval(id="heartbeat", interval=1000, n_intervals=0),
            dcc.Store(id="window-role"),
            html.Header([html.Div([html.Div("eN", className="brand-mark"), html.Div([html.H1("eNose V2"), html.Span("Sensor operations platform")])], className="brand"), html.Div([html.Span("LOCAL-FIRST", className="system-pill"), html.Span(id="header-status", className="header-status")], className="header-actions")], className="topbar"),
            html.Div(id="navigation", children=navigation("/")),
            html.Main(id="page", children=overview_layout()),
        ],
        className="app-shell",
    )

    @app.callback(Output("page", "children"), Output("navigation", "children"), Input("url", "pathname"))
    def switch_page(pathname: str):
        path = pathname or "/"
        return render_page(path), navigation(path)

    app.clientside_callback(
        """
        function(pathname) {
            window.name = pathname === '/capture' ? 'enose_capture' : 'enose_secondary';
            return window.name;
        }
        """,
        Output("window-role", "data"),
        Input("url", "pathname"),
    )

    @app.callback(Output("capture-duration-preview", "children"), Input("capture-duration", "value"))
    def preview_capture_duration(duration):
        try:
            seconds = minutes_to_seconds(duration)
            return f"Timer duration: {format_duration(seconds)} ({seconds} seconds)"
        except ValueError as exc:
            return f"Duration required: {exc}"

    @app.callback(
        Output("capture-message", "children"),
        Input("capture-start", "n_clicks"),
        State("capture-type", "value"), State("capture-substance", "value"),
        State("capture-flow", "value"), State("capture-duration", "value"), State("capture-interval", "value"),
        State("capture-warmup", "value"), State("capture-baseline", "value"), State("capture-notes", "value"),
        State({"type": "capture-enable", "index": ALL}, "value"), State({"type": "capture-enable", "index": ALL}, "id"),
        State({"type": "capture-port", "index": ALL}, "value"), State({"type": "capture-port", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def start_capture(_n, capture_type, substance, flow, duration, interval, warmup, baseline, notes, enabled_values, enabled_ids, port_values, port_ids):
        try:
            enabled = {item["index"] for value, item in zip(enabled_values, enabled_ids) if "on" in (value or [])}
            ports = {item["index"]: value for value, item in zip(port_values, port_ids)}
            selected = {board_id: ports.get(board_id) for board_id in enabled if ports.get(board_id)}
            missing = sorted(board_id for board_id in enabled if not ports.get(board_id))
            if missing:
                return f"Select a COM port for: {', '.join(missing)}"
            if not selected:
                return "Enable at least one board and select its COM port."
            duplicates = sorted({port for port in selected.values() if list(selected.values()).count(port) > 1})
            if duplicates:
                return f"Each board needs its own COM port. Used more than once: {', '.join(duplicates)}"
            actual_stage = str(capture_type or "testing").title()
            label = "clean-air" if capture_type == "baseline" and not substance else (substance or "untitled")
            duration_seconds = minutes_to_seconds(duration)
            spec = SessionSpec(
                stage=actual_stage,
                substance=label.strip(),
                session_id=make_session_id(actual_stage, label),
                selected_boards=selected,
                flowrate=float(flow or 0),
                interval_seconds=float(interval or 1),
                duration_seconds=duration_seconds,
                capture_type=capture_type,
                baseline_session_id=baseline,
                notes=notes or "",
                warmup_seconds=max(0, int(warmup or 0)),
            )
            if spec.warmup_seconds:
                CAPTURE.schedule(spec, spec.warmup_seconds)
                return (
                    f"Warm-up started. Session {spec.session_id} begins in {spec.warmup_seconds} seconds. "
                    f"Capture timer: {format_duration(spec.duration_seconds)}."
                )
            path = CAPTURE.start(spec)
            return f"Capture started: {spec.session_id} · duration {format_duration(spec.duration_seconds)} · {path}"
        except Exception as exc:
            return f"Could not start capture: {exc}"

    @app.callback(
        Output("capture-background-warning", "displayed"),
        Input("capture-message", "children"),
        prevent_initial_call=True,
    )
    def show_capture_background_warning(message):
        text = str(message or "")
        return text.startswith("Capture started:") or text.startswith("Warm-up started.")

    @app.callback(Output("capture-message", "children", allow_duplicate=True), Input("capture-pause", "n_clicks"), prevent_initial_call=True)
    def pause_capture(_n):
        paused = CAPTURE.pause()
        return "Capture paused; serial connections remain open." if paused else ("Capture resumed." if CAPTURE.active else "No active capture to pause.")

    @app.callback(Output("capture-message", "children", allow_duplicate=True), Input("capture-stop", "n_clicks"), prevent_initial_call=True)
    def stop_capture(_n):
        snap = CAPTURE.snapshot()
        if not CAPTURE.active and not snap["scheduled"]:
            return "No active capture."
        CAPTURE.stop()
        return "Warm-up cancelled." if snap["scheduled"] else "Capture stopped. CSV files and summary metadata were finalised."

    @app.callback(Output({"type": "capture-port", "index": ALL}, "options"), Input("refresh-ports", "n_clicks"), prevent_initial_call=True)
    def refresh_ports(_n):
        options = discover_serial_ports()
        return [options for _ in REGISTRY.all(enabled_only=True)]

    @app.callback(
        Output({"type": "capture-enable", "index": MATCH}, "value"),
        Input({"type": "capture-port", "index": MATCH}, "value"),
    )
    def enable_board_when_port_selected(port):
        return ["on"] if port else []

    @app.callback(Output("capture-status", "children"), Output("capture-progress-fill", "style"), Output("capture-progress-label", "children"), Input("heartbeat", "n_intervals"))
    def update_capture_status(_tick):
        snap = CAPTURE.snapshot()
        progress = snap["progress_percent"]
        progress_style = {"width": f"{progress}%"}
        if snap["scheduled"]:
            progress_label = f"Warming up · capture duration {format_duration(snap['duration_seconds'])}"
        elif snap["waiting_for_boards"]:
            required = ", ".join(snap["timer_required_boards"])
            progress_label = (
                f"Timer set for {format_duration(snap['duration_seconds'])} · "
                f"starting after {required} are sending data"
            )
        elif snap["active"]:
            pause_text = " · PAUSED" if snap["paused"] else ""
            progress_label = (
                f"{progress:.1f}% · {format_duration(snap['elapsed_seconds'])} elapsed / "
                f"{format_duration(snap['duration_seconds'])} total · "
                f"{format_duration(snap['remaining_seconds'])} remaining{pause_text}"
            )
        elif snap["session_id"]:
            progress_label = f"Stopped at {progress:.1f}% · {format_duration(snap['elapsed_seconds'])} recorded"
        else:
            progress_label = "Not started"
        if not snap["statuses"]:
            idle_cards = [card("Capture", "Idle", "Start a session from Capture")]
            for board_id in ("LB1", "LB2"):
                if board_id in REGISTRY.all(enabled_only=True):
                    idle_cards.append(card(board_id, "IDLE", battery_indicator(None, None)))
            idle_cards.append(card("Firebase", snap["firebase"], f"{snap['pending']} queued"))
            return idle_cards, progress_style, progress_label
        items = []
        for board_id, status in snap["statuses"].items():
            detail: List[Any] = [html.Div(status.get("message", ""))]
            board_config = REGISTRY.all().get(board_id, {})
            if board_config.get("parser") == "libelium":
                if status.get("lines_received") is not None:
                    detail.append(html.Div(f"Serial lines received: {status['lines_received']}", className="serial-count"))
                detail.append(battery_indicator(status.get("battery_percent"), status.get("battery_volts")))
            items.append(card(board_id, status["state"].upper(), detail, "green" if status["state"] == "capturing" else "amber"))
        items.append(card(
            "Session",
            "PAUSED" if snap["paused"] else ("ACTIVE" if snap["active"] else "STOPPED"),
            f"{format_duration(snap['elapsed_seconds'])} / {format_duration(snap['duration_seconds'])} · {snap['pending']} queued",
        ))
        return items, progress_style, progress_label

    @app.callback(Output("header-status", "children"), Input("heartbeat", "n_intervals"))
    def header_status(_tick):
        snap = CAPTURE.snapshot()
        return f"● {snap['session_id']}" if snap["active"] else "○ System idle"

    @app.callback(Output("live-graphs", "children"), Output("live-empty", "children"), Input("heartbeat", "n_intervals"))
    def update_live_graphs(_tick):
        live = CAPTURE.snapshot()["live"]
        groups = []
        for board_id, points in live.items():
            if not points:
                continue
            sensor_names = sorted({name for point in points for name in point.get("sensors", {})})
            sensor_graphs = []
            for sensor in sensor_names:
                x, y = [], []
                for point in points:
                    if sensor in point["sensors"]:
                        x.append(point["timestamp"])
                        y.append(point["sensors"][sensor])
                figure = go.Figure(go.Scatter(x=x, y=y, mode="lines", name=sensor, line={"color": "#e2e2e2", "width": 2}))
                style_figure(figure, sensor)
                sensor_graphs.append(dcc.Graph(figure=figure, className="chart sensor-chart"))
            groups.append(board_graph_group(board_id, sensor_graphs))
        return groups, ("Start a capture to populate local live graphs." if not groups else "")

    @app.callback(Output("session-graphs", "children"), Input("session-select", "value"))
    def plot_session(path_value):
        if not path_value:
            return []
        groups = []
        for csv_path in sorted(Path(path_value).glob("*_Readings.csv")):
            try:
                frame = pd.read_csv(csv_path, on_bad_lines="skip")
            except Exception:
                continue
            x = frame["Elapsed_seconds"] if "Elapsed_seconds" in frame else frame.get("Timestamp", frame.index)
            ignored = {"Timestamp", "Timestamp_ms", "Elapsed_seconds", "Flowrate (L/min)", "Battery (%)", "Battery (V)"}
            sensor_graphs = []
            for column in frame.columns:
                if column in ignored:
                    continue
                values = pd.to_numeric(frame[column], errors="coerce")
                if values.notna().any():
                    figure = go.Figure(go.Scatter(x=x, y=values, mode="lines", name=column, line={"color": "#e2e2e2", "width": 2}))
                    style_figure(figure, column)
                    sensor_graphs.append(dcc.Graph(figure=figure, className="chart sensor-chart"))
            if sensor_graphs:
                groups.append(board_graph_group(csv_path.name.replace("_Readings.csv", ""), sensor_graphs))
        return groups or [html.Div("No plottable numeric readings in this session.", className="notice")]

    @app.callback(
        Output("research-graphs", "children"),
        Output("research-message", "children"),
        Input("research-baseline", "value"),
        Input("research-session", "value"),
    )
    def plot_research_comparison(baseline_path, session_path):
        if not baseline_path or not session_path:
            return [], "Select both a baseline and a session to create the comparison."
        roots = {"Baseline": Path(baseline_path), "Session": Path(session_path)}
        datasets: Dict[str, Dict[str, pd.DataFrame]] = {}
        for label, root in roots.items():
            datasets[label] = {}
            for csv_path in root.glob("*_Readings.csv"):
                try:
                    datasets[label][csv_path.stem.replace("_Readings", "")] = pd.read_csv(csv_path, on_bad_lines="skip")
                except Exception:
                    continue
        ignored = {"Timestamp", "Timestamp_ms", "Elapsed_seconds", "Flowrate (L/min)", "Battery (%)", "Battery (V)"}
        groups = []
        for board_id in sorted(set(datasets["Baseline"]) | set(datasets["Session"])):
            baseline_frame = datasets["Baseline"].get(board_id)
            session_frame = datasets["Session"].get(board_id)
            columns = set()
            for frame in (baseline_frame, session_frame):
                if frame is not None:
                    columns.update(column for column in frame.columns if column not in ignored)
            sensor_graphs = []
            for sensor in sorted(columns):
                figure = go.Figure()
                for label, frame, colour, dash in (
                    ("Baseline", baseline_frame, "#5ec8e5", "dash"),
                    ("Selected session", session_frame, "#e2e2e2", "solid"),
                ):
                    if frame is None or sensor not in frame:
                        continue
                    values = pd.to_numeric(frame[sensor], errors="coerce")
                    if not values.notna().any():
                        continue
                    x = pd.to_numeric(frame["Elapsed_seconds"], errors="coerce") if "Elapsed_seconds" in frame else frame.index
                    figure.add_trace(go.Scatter(x=x, y=values, mode="lines", name=label, line={"color": colour, "width": 2, "dash": dash}))
                if figure.data:
                    style_figure(figure, sensor)
                    figure.update_xaxes(title="Elapsed seconds")
                    figure.update_layout(showlegend=True)
                    sensor_graphs.append(dcc.Graph(figure=figure, className="chart sensor-chart"))
            if sensor_graphs:
                groups.append(board_graph_group(board_id, sensor_graphs))
        if not groups:
            return [], "No numeric board measurements were available for this comparison."
        return groups, f"Comparing {Path(baseline_path).name} with {Path(session_path).name}."

    @app.callback(Output("board-message", "children"), Output("board-table", "data"), Input("board-save", "n_clicks"), State("board-id", "value"), State("board-name", "value"), State("board-baud", "value"), State("board-parser", "value"), State("board-firebase", "value"), State("board-enabled", "value"), State("board-notes", "value"), prevent_initial_call=True)
    def save_board(_n, board_id, name, baud, parser, firebase_id, enabled, notes):
        try:
            if not board_id:
                raise ValueError("Board ID is required")
            REGISTRY.upsert(board_id, {"name": name, "baud": baud, "parser": parser, "firebase_id": firebase_id, "enabled": enabled == "yes", "notes": notes})
            return f"{board_id.strip().upper()} saved. Capture controls will include it when the Capture page is reopened.", REGISTRY.table_rows()
        except Exception as exc:
            return f"Could not save board: {exc}", REGISTRY.table_rows()

    @app.callback(
        Output("health-message", "children"),
        Input("health-start", "n_clicks"),
        State({"type": "health-enable", "index": ALL}, "value"),
        State({"type": "health-enable", "index": ALL}, "id"),
        State({"type": "health-port", "index": ALL}, "value"),
        State({"type": "health-port", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def start_health_check(_n, enabled_values, enabled_ids, port_values, port_ids):
        try:
            if CAPTURE.active or CAPTURE.snapshot()["scheduled"]:
                return "Stop the active capture before checking board connections."
            enabled = {item["index"] for value, item in zip(enabled_values, enabled_ids) if "on" in (value or [])}
            ports = {item["index"]: value for value, item in zip(port_values, port_ids)}
            missing = sorted(board_id for board_id in enabled if not ports.get(board_id))
            if missing:
                return f"Select a COM port for: {', '.join(missing)}"
            HEALTH.start({board_id: ports[board_id] for board_id in enabled})
            return "Board checks started. B3 can take about 60 seconds after its COM port opens."
        except Exception as exc:
            return f"Could not start board checks: {exc}"

    @app.callback(Output({"type": "health-port", "index": ALL}, "options"), Input("refresh-health-ports", "n_clicks"), prevent_initial_call=True)
    def refresh_health_ports(_n):
        options = discover_serial_ports()
        return [options for _ in REGISTRY.all(enabled_only=True)]

    @app.callback(Output("health-status", "children"), Input("heartbeat", "n_intervals"))
    def update_health_status(_tick):
        snap = HEALTH.snapshot()
        if not snap["statuses"]:
            return []
        output = []
        for board_id, status in snap["statuses"].items():
            state = status["state"]
            detail = status.get("message", "")
            if status.get("preview"):
                detail = f"{detail} · {status['preview']}"
            output.append(card(board_id, state.upper(), detail, "green" if state == "passed" else "amber"))
        return output

    @app.callback(Output("sync-message", "children"), Input("sync-all", "n_clicks"), prevent_initial_call=True)
    def sync_all(_n):
        uploaded = failed = 0
        for queue in DATA_ROOT.rglob("firebase_pending.jsonl") if DATA_ROOT.exists() else []:
            done, remaining = FIREBASE.sync_queue(queue)
            uploaded += done
            failed += remaining
        return f"Sync finished: {uploaded} uploaded, {failed} still queued. Firebase: {FIREBASE.message}"

    @app.callback(Output("firebase-check-message", "children"), Input("firebase-check", "n_clicks"), prevent_initial_call=True)
    def check_firebase(_n):
        online = FIREBASE.check_connection()
        return f"Firebase is online and responding: {FIREBASE.database_url}" if online else f"Firebase check failed: {FIREBASE.message}"

    return app


def style_figure(figure: go.Figure, title: str) -> None:
    figure.update_layout(
        title=title,
        paper_bgcolor="#151515",
        plot_bgcolor="#0b0b0b",
        font={"color": "#e5e5e5", "family": "Inter, Segoe UI, sans-serif"},
        colorway=["#eeeeee", "#bdbdbd", "#969696", "#737373"],
        margin={"l": 45, "r": 20, "t": 55, "b": 45},
        legend={"orientation": "h", "y": -0.2},
        hovermode="x unified",
    )
    figure.update_xaxes(gridcolor="#303030", zerolinecolor="#303030")
    figure.update_yaxes(gridcolor="#303030", zerolinecolor="#303030")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the eNose V2 dashboard")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8051)
    args = parser.parse_args()
    dashboard = create_app()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    dashboard.run(debug=args.debug, port=args.port)
