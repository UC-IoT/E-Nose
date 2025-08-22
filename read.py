import os
import re
import glob
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import dcc, html, Input, Output, State
from write import PREFIX_MAP


def layout(nav_fn):
    return html.Div(
        [
            nav_fn(),
            html.H3("eNose Sensor Data", style={"textAlign": "center", "marginTop": "25px"}),

            html.Div(
                [
                    html.Label("Project Stage"),
                    dcc.Dropdown(id="r-stage", options=[{"label": s, "value": s} for s in PREFIX_MAP],
                                 placeholder="Select stage"),
                    html.Br(),
                    html.Label("Substance"),
                    dcc.Dropdown(id="r-substance", placeholder="Select substance"),
                    html.Br(),
                    html.Label("Flowrate"),
                    dcc.Dropdown(id="r-flow", placeholder="Select flowrate"),
                    html.Br(),

                    html.H4("B1 Voltage + Gas (ppm/ppb)"),
                    dcc.Graph(id="b1-graph"),

                    html.H4("B1 Raw Data"),
                    dcc.Graph(id="b1-raw-graph"),

                    html.H4("B2 Voltage + Gas (ppm/ppb)"),
                    dcc.Graph(id="b2-graph"),

                    html.H4("B2 Raw Data"),
                    dcc.Graph(id="b2-raw-graph"),

                    html.H4("Environmental Sensors (B1 Voltage + Env Native Units)"),
                    dcc.Checklist(
                        id="env-sensor-select",
                        options=[
                            {"label": "Pressure (KPa)", "value": "pres"},
                            {"label": "Humidity (%)", "value": "hum"},
                            {"label": "Temperature (°C)", "value": "temp"},
                        ],
                        value=["temp"],
                        labelStyle={'display': 'inline-block', 'margin-right': '15px'}
                    ),
                    html.Br(),
                    dcc.Graph(id="env-b1-graph"),

                    html.H4("Environmental Sensors (B2 Voltage + Env Native Units)"),
                    dcc.Graph(id="env-b2-graph"),

                    html.H4("Libelium Gases (LB1 + LB2)"),
                    dcc.Graph(id="lb-graph"),
                    dcc.Store(id="r-file-paths")  
                ],
                style={"maxWidth": "95%", "margin": "auto", "marginTop": "30px"},
            ),
        ]
    )


def _discover_files(stage: str, substance: str):
    """
    Inside <stage>/<substance>/ auto-pick the newest B csv and its paired LB csv.

    Expected filenames (examples):
      Test Today 2_B_Readings.csv
      Test Today 2_LB_Readings.csv

    Returns:
      dict with keys: {'b_csv': <path or None>, 'lb_csv': <path or None>, 'base': <str or None>}
    """
    folder = os.path.join(stage, substance)
    if not os.path.isdir(folder):
        return {"b_csv": None, "lb_csv": None, "base": None}


    b_candidates = glob.glob(os.path.join(folder, "*_B_Readings.csv"))
    if not b_candidates:

        fallback = os.path.join(folder, f"{substance}_Readings.csv")
        if os.path.isfile(fallback):
            return {"b_csv": fallback, "lb_csv": None, "base": None}
        return {"b_csv": None, "lb_csv": None, "base": None}


    newest_b = max(b_candidates, key=os.path.getmtime)

    base = os.path.basename(newest_b).replace("_B_Readings.csv", "")
    lb_path = os.path.join(folder, f"{base}_LB_Readings.csv")
    if not os.path.isfile(lb_path):

        generic_lb = os.path.join(folder, f"{substance}_LB_Readings.csv")
        lb_path = generic_lb if os.path.isfile(generic_lb) else None

    return {"b_csv": newest_b, "lb_csv": lb_path, "base": base}


def _safe_read_csv(path):
    try:
        return pd.read_csv(path, on_bad_lines="skip")
    except Exception as e:
        print(f"[read.py] CSV read error for {path}: {e}")
        return None


def register_callbacks(app):

    @app.callback(Output("r-substance", "options"), Input("r-stage", "value"))
    def sub_opts(stage):
        if not stage:
            return []
        p = os.path.join(stage)
        subs = [d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d))] if os.path.isdir(p) else []
        return [{"label": s, "value": s} for s in subs]

    @app.callback(
        Output("r-file-paths", "data"),
        Output("r-flow", "options"),
        Input("r-stage", "value"),
        Input("r-substance", "value")
    )
    def discover_and_flows(stage, sub):
        if not (stage and sub):
            return None, []

        found = _discover_files(stage, sub)
        b_csv, lb_csv = found["b_csv"], found["lb_csv"]

        flows = set()

        if b_csv and os.path.isfile(b_csv):
            dfb = _safe_read_csv(b_csv)
            if dfb is not None and "Flowrate (L/min)" in dfb.columns:
                flows.update(dfb["Flowrate (L/min)"].dropna().unique().tolist())


        if lb_csv and os.path.isfile(lb_csv):
            dfl = _safe_read_csv(lb_csv)
            if dfl is not None and "Flowrate (L/min)" in dfl.columns:
                flows.update(dfl["Flowrate (L/min)"].dropna().unique().tolist())

        flow_opts = [{"label": f"{f} L/min", "value": f} for f in sorted(flows)]
        return found, flow_opts

    @app.callback(
        Output("b1-graph", "figure"),
        Output("b1-raw-graph", "figure"),
        Output("b2-graph", "figure"),
        Output("b2-raw-graph", "figure"),
        Output("env-b1-graph", "figure"),
        Output("env-b2-graph", "figure"),
        Output("lb-graph", "figure"),
        Input("r-flow", "value"),
        State("r-stage", "value"),
        State("r-substance", "value"),
        State("r-file-paths", "data"),
        Input("env-sensor-select", "value"),
    )
    def plot_all(flow, stage, sub, files_data, selected_sensors):
        empty_fig = go.Figure()
        if not all([stage, sub, flow]) or not files_data:
            return (empty_fig,)*7

        b_csv = files_data.get("b_csv")
        lb_csv = files_data.get("lb_csv")


        if not b_csv or not os.path.isfile(b_csv):
            return (empty_fig,)*7

        dfb = _safe_read_csv(b_csv)
        if dfb is None or "Timestamp" not in dfb.columns or "Flowrate (L/min)" not in dfb.columns:
            return (empty_fig,)*7

        
        dfb["Timestamp"] = pd.to_datetime(dfb["Timestamp"], errors="coerce")
        dfb = dfb.dropna(subset=["Timestamp"])
        dfb = dfb[dfb["Flowrate (L/min)"] == flow].sort_values("Timestamp")

    
        dfl = None
        if lb_csv and os.path.isfile(lb_csv):
            dfl = _safe_read_csv(lb_csv)
            if dfl is not None and "Timestamp" in dfl.columns and "Flowrate (L/min)" in dfl.columns:
                dfl["Timestamp"] = pd.to_datetime(dfl["Timestamp"], errors="coerce")
                dfl = dfl.dropna(subset=["Timestamp"])
                dfl = dfl[dfl["Flowrate (L/min)"] == flow].sort_values("Timestamp")
            else:
                dfl = None  


        def cols_startswith(prefix, suffix=None, contains_any=None):
            out = []
            for c in dfb.columns:
                if not c.startswith(prefix):
                    continue
                if suffix and not c.endswith(suffix):
                    continue
                if contains_any and not any(u in c for u in contains_any):
                    continue
                out.append(c)
            return out

        voltage_b1 = cols_startswith("B1", suffix=" - V")
        voltage_b2 = cols_startswith("B2", suffix=" - V")
        ppm_b1 = cols_startswith("B1", contains_any=["ppm", "ppb"])
        ppm_b2 = cols_startswith("B2", contains_any=["ppm", "ppb"])


        raw_b1 = cols_startswith("B1", suffix=" - raw")
        raw_b2 = cols_startswith("B2", suffix=" - raw")


        temperature_cols = [c for c in dfb.columns if re.search(r"(°C|\(C\))$", c)]
        humidity_cols = [c for c in dfb.columns if re.search(r"%$", c) and "humidity" in c.lower()]
        pressure_cols = [c for c in dfb.columns if c.endswith("KPa")]

        def create_fig(df, voltage_cols, ppm_cols, title):
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            for v_col in voltage_cols:
                sensor_id = v_col.replace(" - V", "")
                fig.add_trace(
                    go.Scatter(x=df["Timestamp"], y=df[v_col], name=v_col,
                               mode="lines+markers", line_shape="spline", legendgroup=sensor_id),
                    secondary_y=False
                )

                for g_col in [c for c in ppm_cols if sensor_id in c]:
                    fig.add_trace(
                        go.Scatter(x=df["Timestamp"], y=_to_float_safe(df[g_col]),
                                   name=g_col, mode="lines+markers",
                                   line_shape="spline", legendgroup=sensor_id),
                        secondary_y=True
                    )
            fig.update_xaxes(title_text="Time")
            fig.update_yaxes(title_text="Voltage (V)", secondary_y=False, range=[0, 5])
            fig.update_yaxes(title_text="ppm / ppb", secondary_y=True)
            fig.update_layout(title=title, hovermode="x unified", height=500)
            return fig

        def create_env_fig(df, voltage_cols, title):
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            for col in voltage_cols:
                fig.add_trace(
                    go.Scatter(x=df["Timestamp"], y=df[col], name=col,
                               mode="lines+markers", line_shape="spline"),
                    secondary_y=False
                )

            for sensor_type, cols in zip(
                ["temp", "hum", "pres"], [temperature_cols, humidity_cols, pressure_cols]
            ):
                if sensor_type in selected_sensors:
                    for col in cols:
                        fig.add_trace(
                            go.Scatter(x=df["Timestamp"], y=_to_float_safe(df[col]), name=col,
                                       mode="lines+markers", line_shape="spline",
                                       line=dict(dash="dash")),
                            secondary_y=True
                        )

            fig.update_xaxes(title_text="Time")
            fig.update_yaxes(title_text="Gas Sensor Voltage (V)", secondary_y=False, range=[0, 5])
            fig.update_yaxes(title_text="Unit", secondary_y=True)
            fig.update_layout(title=title, height=600, hovermode="x unified",
                              legend=dict(orientation="h", x=0, y=-0.2))
            return fig

        def create_raw_fig(df, raw_cols, sensor_hints, title):
            fig = go.Figure()
            for col in raw_cols:
               
                sensor_name = next((s for s in sensor_hints if s in col), col)
                fig.add_trace(go.Scatter(
                    x=df["Timestamp"],
                    y=_to_float_safe(df[col]),
                    mode="lines+markers",
                    name=sensor_name,
                    line_shape="spline"
                ))
            fig.update_layout(
                title=title,
                xaxis_title="Time",
                yaxis_title="Raw Value",
                yaxis=dict(range=[0, 1023]),
                height=400,
                hovermode="x unified"
            )
            return fig


        fig_b1 = create_fig(dfb, voltage_b1, ppm_b1, "B1 Voltage + Gas")
        fig_b1_raw = create_raw_fig(dfb, raw_b1, ["TGS2600", "TGS2602", "TGS2603", "MQ2"], "B1 Raw Data")
        fig_b2 = create_fig(dfb, voltage_b2, ppm_b2, "B2 Voltage + Gas")
        fig_b2_raw = create_raw_fig(dfb, raw_b2, ["TGS2610", "TGS2611", "TGS2612", "MQ9"], "B2 Raw Data")
        fig_env_b1 = create_env_fig(dfb, voltage_b1, "Environmental Sensors B1")
        fig_env_b2 = create_env_fig(dfb, voltage_b2, "Environmental Sensors B2")


        if dfl is None or dfl.empty:
            fig_lb = empty_fig
        else:

            gases = ["NO", "CO", "NO2", "NH3", "O2"]
            fig_lb = go.Figure()
            for gas in gases:
                lb1_col = _first_match(dfl.columns, rf"^LB1\s*-\s*{gas}\s*\((ppm|%)\)$")
                lb2_col = _first_match(dfl.columns, rf"^LB2\s*-\s*{gas}\s*\((ppm|%)\)$")

                if lb1_col:
                    fig_lb.add_trace(go.Scatter(
                        x=dfl["Timestamp"],
                        y=_to_float_safe(dfl[lb1_col]),
                        name=f"LB1 - {gas}",
                        mode="lines+markers",
                        line_shape="spline"
                    ))
                if lb2_col:
                    fig_lb.add_trace(go.Scatter(
                        x=dfl["Timestamp"],
                        y=_to_float_safe(dfl[lb2_col]),
                        name=f"LB2 - {gas}",
                        mode="lines+markers",
                        line_shape="spline"
                    ))
            fig_lb.update_layout(title="Libelium Gases (LB1 + LB2)",
                                 xaxis_title="Time", yaxis_title="Concentration",
                                 height=500, hovermode="x unified")

        return fig_b1, fig_b1_raw, fig_b2, fig_b2_raw, fig_env_b1, fig_env_b2, fig_lb


def _first_match(columns, pattern):
    rx = re.compile(pattern)
    for c in columns:
        if rx.search(c):
            return c
    return None


def _to_float_safe(series):
    """
    Convert a series that might contain strings like '1.23 ppm' to float safely.
    """
    def _num(x):
        if pd.isna(x):
            return None
        if isinstance(x, (int, float)):
            return x
        
        s = re.sub(r"[^0-9\.\-]+", "", str(x))
        try:
            return float(s) if s not in ("", "-", ".", "-.") else None
        except Exception:
            return None
    return series.apply(_num)
