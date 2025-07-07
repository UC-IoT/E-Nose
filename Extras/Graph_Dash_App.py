from dash import Dash, dcc, html, Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import os
import re

BASE_DIR = "."

app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "eNose Dashboard"

# === Helper Functions ===
def get_stage_options():
    return [d for d in os.listdir(BASE_DIR) if os.path.isdir(os.path.join(BASE_DIR, d)) and d in ["Testing", "Experiment", "Deployment"]]

def get_substance_options(stage):
    stage_path = os.path.join(BASE_DIR, stage)
    if not os.path.exists(stage_path):
        return []
    return [d for d in os.listdir(stage_path) if os.path.isdir(os.path.join(stage_path, d))]

# === Shared Layout Controls ===
def shared_controls():
    return html.Div([
        html.Div([
            html.Label("Select Project Stage:"),
            dcc.Dropdown(id='stage-dropdown', options=[{'label': s, 'value': s} for s in get_stage_options()], placeholder="Select Stage"),
        ], style={'maxWidth': '400px', 'margin': 'auto', 'marginBottom': '20px'}),

        html.Div([
            html.Label("Select Substance:"),
            dcc.Dropdown(id='substance-dropdown', placeholder="Select Substance"),
        ], style={'maxWidth': '400px', 'margin': 'auto', 'marginBottom': '20px'}),

        html.Div([
            html.Label("Select Flowrate:"),
            dcc.Dropdown(id='flowrate-dropdown', placeholder="Select Flowrate"),
        ], style={'maxWidth': '400px', 'margin': 'auto', 'marginBottom': '40px'})
    ])

# === Main Dashboard Layout (Voltage + controls) ===
def main_dashboard_layout():
    return html.Div([
        html.H2("eNose Sensor Dashboard - Main", style={'textAlign': 'center', 'marginBottom': '30px'}),
        shared_controls(),
        dcc.Graph(id='sensor-graph'),
        html.Div([
            html.A("Go to PPM/PPB Graph Page", href="/ppm", target="_blank", rel="noopener noreferrer",
                   style={"cursor": "pointer", "color": "#007bff", "textDecoration": "underline"})
        ], style={'textAlign': 'center', 'marginTop': '30px'})
    ])

# === PPM Graph Layout (uses shared controls) ===
def ppm_graph_layout():
    return html.Div([
        html.H2("eNose Sensor Dashboard - PPM/PPB Graph", style={'textAlign': 'center', 'marginBottom': '30px'}),
        shared_controls(),
        dcc.Graph(id='ppm-graph-only'),
        html.Div([
            html.A("Back to Main Dashboard", href="/", target="_blank", rel="noopener noreferrer",
                   style={"cursor": "pointer", "color": "#007bff", "textDecoration": "underline"})
        ], style={'textAlign': 'center', 'marginTop': '30px'})
    ])

# === App Layout with URL Routing ===
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='page-content')
])

@app.callback(Output('page-content', 'children'), Input('url', 'pathname'))
def display_page(pathname):
    if pathname == '/ppm':
        return ppm_graph_layout()
    return main_dashboard_layout()

# === Callbacks for shared dropdowns ===
@app.callback(Output('substance-dropdown', 'options'), Input('stage-dropdown', 'value'))
def update_substance_dropdown(stage):
    if not stage:
        return []
    return [{'label': s, 'value': s} for s in get_substance_options(stage)]

@app.callback(Output('flowrate-dropdown', 'options'), Input('stage-dropdown', 'value'), Input('substance-dropdown', 'value'))
def update_flowrate_dropdown(stage, substance):
    if not stage or not substance:
        return []
    path = os.path.join(stage, substance, f"{substance}_Readings.csv")
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path)
    if 'Flowrate (L/min)' not in df.columns:
        return []
    return [{'label': f"{f} L/min", 'value': f} for f in sorted(df['Flowrate (L/min)'].dropna().unique())]

@app.callback(Output('sensor-graph', 'figure'), Input('flowrate-dropdown', 'value'), State('stage-dropdown', 'value'), State('substance-dropdown', 'value'))
def update_voltage_graph(flow, stage, substance):
    if not all([flow, stage, substance]):
        return go.Figure()
    path = os.path.join(stage, substance, f"{substance}_Readings.csv")
    if not os.path.exists(path):
        return go.Figure()

    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors='coerce')

    volt_cols = [c for c in df.columns if c.endswith("(V)") and not any(k in c for k in ["Temperature", "Humidity", "Pressure", "BME688"])]
    for col in volt_cols:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(" V", "", regex=False), errors='coerce')

    bme_map = {
        "BME688 - temperature (°C)": (2, "Temperature (°C)"),
        "BME688 - humidity (%)": (3, "Humidity (%)"),
        "BME688 - pressure (KPa)": (4, "Pressure (kPa)")
    }

    sub_df = df[df['Flowrate (L/min)'] == flow]
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.07, row_heights=[0.45, 0.2, 0.2, 0.15],
                        subplot_titles=[f"{stage} - {substance} | Voltage @ {flow} L/min", "Temperature", "Humidity", "Pressure"])

    def clean_label(c):
        c = c.replace(" (V)", "")
        m = re.match(r"(.*? - .*?) \((.*?)\)$", c)
        return f"{m[1]} ({m[2]})" if m else c

    for col in volt_cols:
        fig.add_trace(go.Scatter(x=sub_df["Timestamp"], y=sub_df[col], mode="lines+markers", name=clean_label(col)), row=1, col=1)

    for name, (r, label) in bme_map.items():
        if name in df.columns:
            fig.add_trace(go.Scatter(x=df['Timestamp'], y=df[name], mode="lines", name=label, line=dict(shape='spline')), row=r, col=1)

    fig.update_layout(height=1000, xaxis_title="Time")
    fig.update_yaxes(title_text="Voltage (V)", row=1, col=1, range=[0, 5])
    fig.update_yaxes(title_text="°C", row=2, col=1)
    fig.update_yaxes(title_text="%", row=3, col=1)
    fig.update_yaxes(title_text="kPa", row=4, col=1)
    return fig

@app.callback(Output('ppm-graph-only', 'figure'), Input('flowrate-dropdown', 'value'), State('stage-dropdown', 'value'), State('substance-dropdown', 'value'))
def update_ppm_graph(flow, stage, substance):
    if not all([flow, stage, substance]):
        return go.Figure()
    path = os.path.join(stage, substance, f"{substance}_Readings.csv")
    if not os.path.exists(path):
        return go.Figure()

    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors='coerce')
    sub_df = df[df['Flowrate (L/min)'] == flow]
    ppm_cols = [c for c in df.columns if re.search(r"\((ppm|ppb)\)", c)]

    fig = go.Figure()
    for col in ppm_cols:
        fig.add_trace(go.Scatter(x=sub_df["Timestamp"], y=sub_df[col], mode="lines+markers", name=col))

    fig.update_layout(title=f"{stage} - {substance} | PPM/PPB @ {flow} L/min", xaxis_title="Time", yaxis_title="Concentration (ppm/ppb)", height=700)
    return fig

if __name__ == "__main__":
    os.environ["DASH_DEBUG_MODE"] = "False"
    app.run(debug=True)
