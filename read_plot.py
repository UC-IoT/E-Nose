import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import dcc, html, Input, Output, State
from data_capture import PREFIX_MAP


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

                    html.H4("B2 Voltage + Gas (ppm/ppb)"),
                    dcc.Graph(id="b2-graph"),

                    html.H4("Environmental Sensors"),
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

                    dcc.Graph(id="env-graph"),
                ],
                style={"maxWidth": "95%", "margin": "auto", "marginTop": "30px"},
            ),
        ]
    )


def register_callbacks(app):

    @app.callback(Output("r-substance", "options"), Input("r-stage", "value"))
    def sub_opts(stage):
        if not stage:
            return []
        p = os.path.join(stage)
        subs = [d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d))] if os.path.isdir(p) else []
        return [{"label": s, "value": s} for s in subs]

    @app.callback(Output("r-flow", "options"),
                  Input("r-stage", "value"), Input("r-substance", "value"))
    def flow_opts(stage, sub):
        if not (stage and sub):
            return []

        csv = os.path.join(stage, sub, f"{sub}_Readings.csv")
        if not os.path.isfile(csv):
            return []

        try:
            df = pd.read_csv(csv, on_bad_lines='skip')
        except pd.errors.ParserError as e:
            print(f"Error reading CSV: {e}")
            return []

        if 'Flowrate (L/min)' not in df.columns:
            return []

        return [{"label": f"{f} L/min", "value": f} for f in sorted(df["Flowrate (L/min)"].dropna().unique())]

    @app.callback(
        Output("b1-graph", "figure"),
        Output("b2-graph", "figure"),
        Output("env-graph", "figure"),
        Input("r-flow", "value"),
        State("r-stage", "value"),
        State("r-substance", "value"),
        Input("env-sensor-select", "value"),
    )
    def plot_all(flow, stage, sub, selected_sensors):
        if not all([stage, sub, flow]):
            return go.Figure(), go.Figure(), go.Figure()

        csv = os.path.join(stage, sub, f"{sub}_Readings.csv")
        if not os.path.isfile(csv):
            return go.Figure(), go.Figure(), go.Figure()

        try:
            df = pd.read_csv(csv, on_bad_lines='skip')
        except pd.errors.ParserError as e:
            print(f"Error reading CSV: {e}")
            return go.Figure(), go.Figure(), go.Figure()

        if 'Timestamp' not in df.columns or 'Flowrate (L/min)' not in df.columns:
            return go.Figure(), go.Figure(), go.Figure()

        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
        df = df[df["Flowrate (L/min)"] == flow]

        voltage_b1 = [c for c in df.columns if c.startswith("B1") and c.endswith("- V")]
        voltage_b2 = [c for c in df.columns if c.startswith("B2") and c.endswith("- V")]
        ppm_b1 = [c for c in df.columns if c.startswith("B1") and any(u in c for u in ["ppm", "ppb"])]
        ppm_b2 = [c for c in df.columns if c.startswith("B2") and any(u in c for u in ["ppm", "ppb"])]

        voltage_env = [c for c in df.columns if any(k in c.lower() for k in ["temp", "hum", "pres"]) and c.endswith("- V")]
        temperature_cols = [c for c in df.columns if c.endswith("°C")]
        humidity_cols = [c for c in df.columns if c.endswith("%") and "humidity" in c.lower()]
        pressure_cols = [c for c in df.columns if c.endswith("KPa")]

        # === B1 ===
        fig_b1 = make_subplots(specs=[[{"secondary_y": True}]])
        for v_col in voltage_b1:
            sensor_id = v_col.replace(" - V", "")
            fig_b1.add_trace(go.Scatter(x=df["Timestamp"], y=df[v_col], name=v_col, mode="lines",
                                        legendgroup=sensor_id), secondary_y=False)
            for g_col in [c for c in ppm_b1 if sensor_id in c]:
                fig_b1.add_trace(go.Scatter(x=df["Timestamp"], y=df[g_col], name=g_col, mode="lines+markers",
                                            legendgroup=sensor_id), secondary_y=True)
        fig_b1.update_yaxes(title_text="Voltage (V)", secondary_y=False, range=[0, 5])
        fig_b1.update_yaxes(title_text="ppm / ppb", secondary_y=True)
        fig_b1.update_layout(title="B1 Voltage + Gas", hovermode="x unified", height=500)

        # === B2 ===
        fig_b2 = make_subplots(specs=[[{"secondary_y": True}]])
        for v_col in voltage_b2:
            sensor_id = v_col.replace(" - V", "")
            fig_b2.add_trace(go.Scatter(x=df["Timestamp"], y=df[v_col], name=v_col, mode="lines",
                                        legendgroup=sensor_id), secondary_y=False)
            for g_col in [c for c in ppm_b2 if sensor_id in c]:
                fig_b2.add_trace(go.Scatter(x=df["Timestamp"], y=df[g_col], name=g_col, mode="lines+markers",
                                            legendgroup=sensor_id), secondary_y=True)
        fig_b2.update_yaxes(title_text="Voltage (V)", secondary_y=False, range=[0, 5])
        fig_b2.update_yaxes(title_text="ppm / ppb", secondary_y=True)
        fig_b2.update_layout(title="B2 Voltage + Gas", hovermode="x unified", height=500)

        # === Environmental ===
        fig_env = make_subplots(specs=[[{"secondary_y": True}]])
        fig_env.update_layout(title="Environmental Sensors", height=600)

        def add_traces(cols, axis_side, style="solid"):
            for col in cols:
                fig_env.add_trace(go.Scatter(
                    x=df["Timestamp"], y=df[col], name=col, mode="lines",
                    line=dict(dash=style)
                ), secondary_y=(axis_side == "right"))

        if "temp" in selected_sensors:
            add_traces([c for c in voltage_env if "temp" in c.lower()], axis_side="left")
            add_traces(temperature_cols, axis_side="right", style="dash")
        if "hum" in selected_sensors:
            add_traces([c for c in voltage_env if "hum" in c.lower()], axis_side="left")
            add_traces(humidity_cols, axis_side="right", style="dash")
        if "pres" in selected_sensors:
            add_traces([c for c in voltage_env if "pres" in c.lower()], axis_side="left")
            add_traces(pressure_cols, axis_side="right", style="dash")

        fig_env.update_xaxes(title_text="Timestamp")
        fig_env.update_yaxes(title_text="Sensor Voltage (V)", secondary_y=False)
        fig_env.update_yaxes(title_text="Native Unit", secondary_y=True, autorange='reversed')
        fig_env.update_layout(hovermode="x unified", legend=dict(orientation="h", x=0, y=-0.2))

        return fig_b1, fig_b2, fig_env
