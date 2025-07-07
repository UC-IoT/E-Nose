#read_plot.py
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
            html.H3("Plot historical data", style={"textAlign": "center", "marginTop": "25px"}),

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
                    dcc.Graph(id="r-graph"),
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
        df = pd.read_csv(csv)
        return [{"label": f"{f} L/min", "value": f} for f in sorted(df["Flowrate (L/min)"].dropna().unique())]

    @app.callback(
        Output("r-graph", "figure"),
        Input("r-flow", "value"),
        State("r-stage", "value"),
        State("r-substance", "value")
    )
    def plot(flow, stage, sub):
        if not all([stage, sub, flow]):
            return go.Figure()

        csv = os.path.join(stage, sub, f"{sub}_Readings.csv")
        if not os.path.isfile(csv):
            return go.Figure()

        df = pd.read_csv(csv)
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
        df = df[df["Flowrate (L/min)"] == flow]

        voltage_b1 = [c for c in df.columns if c.startswith("B1") and c.endswith("- V") and not any(u in c for u in ["°C", "%", "KPa", "ppm", "ppb", "KOhms"])]
        voltage_b2 = [c for c in df.columns if c.startswith("B2") and c.endswith("- V") and not any(u in c for u in ["°C", "%", "KPa", "ppm", "ppb", "KOhms"])]
        ppm_b1 = [c for c in df.columns if c.startswith("B1") and any(u in c for u in ["ppm", "ppb"])]
        ppm_b2 = [c for c in df.columns if c.startswith("B2") and any(u in c for u in ["ppm", "ppb"])]
        temperature_cols = [c for c in df.columns if c.endswith("°C")]
        humidity_cols = [c for c in df.columns if c.endswith("%") and "humidity" in c.lower()]
        pressure_cols = [c for c in df.columns if c.endswith("KPa")]

        fig = make_subplots(
            rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.07,
            row_heights=[0.25, 0.25, 0.15, 0.1, 0.1, 0.1],
            subplot_titles=[
                "<b>Board B1 — Voltage (V)</b>",
                "<b>Board B2 — Voltage (V)</b>",
                "<b>Gas Sensors (ppm / ppb) [B1 & B2]</b>",
                "<b>Temperature (°C)</b>",
                "<b>Humidity (%)</b>",
                "<b>Pressure (KPa)</b>"
            ]
        )

        def add_traces(cols, row):
            for col in cols:
                fig.add_trace(go.Scatter(x=df["Timestamp"], y=df[col], name=col, mode="lines"), row=row, col=1)

        add_traces(voltage_b1, 1)
        add_traces(voltage_b2, 2)
        add_traces(ppm_b1 + ppm_b2, 3)
        add_traces(temperature_cols, 4)
        add_traces(humidity_cols, 5)
        add_traces(pressure_cols, 6)

        for i in range(1, 7):
            fig.update_xaxes(title_text="", row=i, col=1, showticklabels=True)

        fig.update_yaxes(title_text="Voltage (V)", row=1, col=1, range=[0, 5])
        fig.update_yaxes(title_text="Voltage (V)", row=2, col=1, range=[0, 5])
        fig.update_yaxes(title_text="ppm / ppb", row=3, col=1)
        fig.update_yaxes(title_text="°C", row=4, col=1)
        fig.update_yaxes(title_text="%", row=5, col=1)
        fig.update_yaxes(title_text="KPa", row=6, col=1)

        fig.update_layout(
            height=1700,
            legend=dict(orientation="h", x=0, y=-0.25, title=None),
            margin=dict(t=60, b=120),
            hovermode="x unified"
        )

        return fig
