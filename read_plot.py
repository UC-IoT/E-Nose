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
                            {"label": "Temperature (°C)", "value": "temp"},
                            {"label": "Humidity (%)", "value": "hum"},
                            {"label": "Pressure (KPa)", "value": "pres"},
                        ],
                        value=["temp"],  # Start with only temp selected
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

        # Columns
        voltage_b1 = [c for c in df.columns if c.startswith("B1") and c.endswith("- V")]
        voltage_b2 = [c for c in df.columns if c.startswith("B2") and c.endswith("- V")]
        ppm_b1 = [c for c in df.columns if c.startswith("B1") and any(u in c for u in ["ppm", "ppb"])]
        ppm_b2 = [c for c in df.columns if c.startswith("B2") and any(u in c for u in ["ppm", "ppb"])]
        temperature_cols = [c for c in df.columns if c.endswith("°C")]
        humidity_cols = [c for c in df.columns if c.endswith("%") and "humidity" in c.lower()]
        pressure_cols = [c for c in df.columns if c.endswith("KPa")]

        # === 1. B1 Graph ===
        fig_b1 = make_subplots(specs=[[{"secondary_y": True}]])
        for col in voltage_b1:
            fig_b1.add_trace(go.Scatter(x=df["Timestamp"], y=df[col], name=col, mode="lines"), secondary_y=False)
        for col in ppm_b1:
            fig_b1.add_trace(go.Scatter(x=df["Timestamp"], y=df[col], name=col, mode="lines+markers"), secondary_y=True)
        fig_b1.update_yaxes(title_text="Voltage (V)", secondary_y=False)
        fig_b1.update_yaxes(title_text="ppm / ppb", secondary_y=True)
        fig_b1.update_layout(title="B1 Voltage + Gas", hovermode="x unified", height=500)

        # === 2. B2 Graph ===
        fig_b2 = make_subplots(specs=[[{"secondary_y": True}]])
        for col in voltage_b2:
            fig_b2.add_trace(go.Scatter(x=df["Timestamp"], y=df[col], name=col, mode="lines"), secondary_y=False)
        for col in ppm_b2:
            fig_b2.add_trace(go.Scatter(x=df["Timestamp"], y=df[col], name=col, mode="lines+markers"), secondary_y=True)
        fig_b2.update_yaxes(title_text="Voltage (V)", secondary_y=False)
        fig_b2.update_yaxes(title_text="ppm / ppb", secondary_y=True)
        fig_b2.update_layout(title="B2 Voltage + Gas", hovermode="x unified", height=500)

        # === 3. Environmental Graph with Smart Axis Assignment ===
        fig_env = make_subplots(specs=[[{"secondary_y": True}]])
        fig_env.update_layout(title="Environmental Sensors", height=600)

        left_used = False
        right_used = False

        def plot_sensor_group(cols, name, prefer_axis="left"):
            nonlocal left_used, right_used
            if not cols:
                return
            use_right = False

            if prefer_axis == "left" and not left_used:
                use_right = False
                left_used = True
            elif prefer_axis == "right" and not right_used:
                use_right = True
                right_used = True
            elif not left_used:
                use_right = False
                left_used = True
            else:
                use_right = True
                right_used = True

            line_style = "dash" if use_right else "solid"
            for col in cols:
                fig_env.add_trace(
                    go.Scatter(
                        x=df["Timestamp"],
                        y=df[col],
                        name=col,
                        mode="lines",
                        line=dict(dash=line_style)
                    ),
                    secondary_y=use_right
                )

            # Y-axis title
            if use_right:
                fig_env.update_yaxes(title_text=name, secondary_y=True)
            else:
                fig_env.update_yaxes(title_text=name, secondary_y=False)

        # Plot based on what user selects
        if "temp" in selected_sensors:
            plot_sensor_group(temperature_cols, "Temperature (°C)", prefer_axis="left")
        if "hum" in selected_sensors:
            plot_sensor_group(humidity_cols, "Humidity (%)", prefer_axis="right")
        if "pres" in selected_sensors:
            plot_sensor_group(pressure_cols, "Pressure (KPa)", prefer_axis="right")

        fig_env.update_xaxes(title_text="Timestamp")
        fig_env.update_layout(
            hovermode="x unified",
            legend=dict(orientation="h", x=0, y=-0.2)
        )

        return fig_b1, fig_b2, fig_env
