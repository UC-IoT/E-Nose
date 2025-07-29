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
        Output("b1-raw-graph", "figure"),
        Output("b2-graph", "figure"),
        Output("b2-raw-graph", "figure"),
        Output("env-b1-graph", "figure"),
        Output("env-b2-graph", "figure"),
        Input("r-flow", "value"),
        State("r-stage", "value"),
        State("r-substance", "value"),
        Input("env-sensor-select", "value"),
    )
    def plot_all(flow, stage, sub, selected_sensors):
        empty_fig = go.Figure()
        if not all([stage, sub, flow]):
            return empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, empty_fig

        csv = os.path.join(stage, sub, f"{sub}_Readings.csv")
        if not os.path.isfile(csv):
            return empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, empty_fig

        try:
            df = pd.read_csv(csv, on_bad_lines='skip')
        except pd.errors.ParserError as e:
            print(f"Error reading CSV: {e}")
            return empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, empty_fig

        if 'Timestamp' not in df.columns or 'Flowrate (L/min)' not in df.columns:
            return empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, empty_fig

        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
        df = df[df["Flowrate (L/min)"] == flow]
        df = df.sort_values("Timestamp")

        voltage_b1 = [c for c in df.columns if c.startswith("B1") and c.endswith("- V")]
        voltage_b2 = [c for c in df.columns if c.startswith("B2") and c.endswith("- V")]
        ppm_b1 = [c for c in df.columns if c.startswith("B1") and any(u in c for u in ["ppm", "ppb"])]
        ppm_b2 = [c for c in df.columns if c.startswith("B2") and any(u in c for u in ["ppm", "ppb"])]

        raw_b1 = [c for c in df.columns if c.startswith("B1") and c.endswith("raw")]
        raw_b2 = [c for c in df.columns if c.startswith("B2") and c.endswith("raw")]

        temperature_cols = [c for c in df.columns if c.endswith("°C")]
        humidity_cols = [c for c in df.columns if c.endswith("%") and "humidity" in c.lower()]
        pressure_cols = [c for c in df.columns if c.endswith("KPa")]

        def create_fig(voltage_cols, ppm_cols, title):
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            for v_col in voltage_cols:
                sensor_id = v_col.replace(" - V", "")
                fig.add_trace(go.Scatter(x=df["Timestamp"], y=df[v_col], name=v_col, mode="lines+markers", line_shape="spline", legendgroup=sensor_id), secondary_y=False)
                for g_col in [c for c in ppm_cols if sensor_id in c]:
                    fig.add_trace(go.Scatter(x=df["Timestamp"], y=df[g_col], name=g_col, mode="lines+markers", line_shape="spline", legendgroup=sensor_id), secondary_y=True)
            fig.update_xaxes(title_text="Time")
            fig.update_yaxes(title_text="Voltage (V)", secondary_y=False, range=[0, 5])
            fig.update_yaxes(title_text="ppm / ppb", secondary_y=True)
            fig.update_layout(title=title, hovermode="x unified", height=500)
            return fig

        def create_env_fig(voltage_cols, title):
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            for col in voltage_cols:
                fig.add_trace(go.Scatter(x=df["Timestamp"], y=df[col], name=col, mode="lines+markers", line_shape="spline"), secondary_y=False)

            for sensor_type, cols in zip(["temp", "hum", "pres"], [temperature_cols, humidity_cols, pressure_cols]):
                if sensor_type in selected_sensors:
                    for col in cols:
                        fig.add_trace(go.Scatter(x=df["Timestamp"], y=df[col], name=col, mode="lines+markers", line_shape="spline", line=dict(dash="dash")), secondary_y=True)

            fig.update_xaxes(title_text="Time")
            fig.update_yaxes(title_text="Gas Sensor Voltage (V)", secondary_y=False, range=[0, 5])
            fig.update_yaxes(title_text="Unit", secondary_y=True)
            fig.update_layout(title=title, height=600, hovermode="x unified", legend=dict(orientation="h", x=0, y=-0.2))
            return fig

        def create_raw_fig(raw_cols, sensor_list, title):
            fig = go.Figure()
            for col in raw_cols:
                sensor_name = next((s for s in sensor_list if s in col), None)
                if sensor_name:
                    fig.add_trace(go.Scatter(
                        x=df["Timestamp"],
                        y=df[col],
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

        fig_b1 = create_fig(voltage_b1, ppm_b1, "B1 Voltage + Gas")
        fig_b1_raw = create_raw_fig(raw_b1, ["TGS2600", "TGS2602", "TGS2603", "MQ2"], "B1 Raw Data")
        fig_b2 = create_fig(voltage_b2, ppm_b2, "B2 Voltage + Gas")
        fig_b2_raw = create_raw_fig(raw_b2, ["TGS2610", "TGS2611", "TGS2612", "MQ9"], "B2 Raw Data")
        fig_env_b1 = create_env_fig(voltage_b1, "Environmental Sensors B1")
        fig_env_b2 = create_env_fig(voltage_b2, "Environmental Sensors B2")

        return fig_b1, fig_b1_raw, fig_b2, fig_b2_raw, fig_env_b1, fig_env_b2
