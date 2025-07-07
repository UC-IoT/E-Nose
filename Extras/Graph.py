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

# === Main Dashboard Layout ===
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

# === PPM Graph Layout ===
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

# === Dropdown Callbacks ===
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

# === Main Graph with Twin Axis ===
@app.callback(Output('sensor-graph', 'figure'), Input('flowrate-dropdown', 'value'),
              State('stage-dropdown', 'value'), State('substance-dropdown', 'value'))
def update_voltage_graph(flow, stage, substance):
    if not all([flow, stage, substance]):
        return go.Figure()
    path = os.path.join(stage, substance, f"{substance}_Readings.csv")
    if not os.path.exists(path):
        return go.Figure()

    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors='coerce')
    sub_df = df[df['Flowrate (L/min)'] == flow].copy()

    volt_cols = [c for c in df.columns if c.endswith("(V)") and not any(k in c for k in ["Temperature", "Humidity", "Pressure", "BME688"])]
    ppm_cols = [c for c in df.columns if re.search(r"\((ppm|ppb)\)", c)]

    # Clean voltage
    for col in volt_cols:
        sub_df[col] = pd.to_numeric(sub_df[col].astype(str).str.replace(" V", "", regex=False), errors='coerce')

    # Clean ppm
    for col in ppm_cols:
        sub_df[col] = pd.to_numeric(sub_df[col].astype(str).str.extract(r"([\d\.]+)")[0], errors='coerce').round(2)

    fig = make_subplots(
    rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.07,
    row_heights=[0.45, 0.2, 0.2, 0.15],
    subplot_titles=[
        f"{stage} - {substance} | Voltage + PPM @ {flow} L/min",
        "Temperature", "Humidity", "Pressure"
    ],
    specs=[
        [{"secondary_y": True}],
        [{}],
        [{}],
        [{}]
    ]
)

    def clean_label(c):
        c = c.replace(" (V)", "")
        m = re.match(r"(.*? - .*?) \((.*?)\)$", c)
        return f"{m[1]} ({m[2]})" if m else c

    # Voltage
    for col in volt_cols:
        fig.add_trace(go.Scatter(
            x=sub_df["Timestamp"], y=sub_df[col],
            mode="lines+markers", name=clean_label(col),
            line=dict(shape='linear', dash='solid'),
            hovertemplate="%{y:.2f} V<br>%{x|%Y-%m-%d %H:%M:%S}"
        ), row=1, col=1, secondary_y=False)

    # PPM
    for col in ppm_cols:
        fig.add_trace(go.Scatter(
            x=sub_df["Timestamp"], y=sub_df[col],
            mode="lines+markers", name=col,
            line=dict(shape='linear', dash='dash'),
            hovertemplate="%{y:.2f}<br>%{x|%Y-%m-%d %H:%M:%S}"
        ), row=1, col=1, secondary_y=True)

    # BME always shown, but non-toggleable (legendgroup disabled)
    bme_map = {
        "BME688 - temperature (°C)": (2, "Temperature (°C)"),
        "BME688 - humidity (%)": (3, "Humidity (%)"),
        "BME688 - pressure (KPa)": (4, "Pressure (kPa)")
    }
    for name, (r, label) in bme_map.items():
        if name in df.columns:
            fig.add_trace(go.Scatter(
                x=df['Timestamp'], y=df[name],
                mode="lines", name=label, line=dict(shape='spline'),
                hovertemplate="%{y:.2f}<br>%{x|%Y-%m-%d %H:%M:%S}",
                showlegend=False
            ), row=r, col=1)

    # Axis ranges
    if sub_df["Timestamp"].notnull().any():
        x_min, x_max = sub_df["Timestamp"].min(), sub_df["Timestamp"].max()
        fig.update_xaxes(range=[x_min, x_max])

    # Estimate dtick for ~10 ticks
    if ppm_cols:
        combined_ppm = pd.concat([sub_df[col].dropna() for col in ppm_cols])
        ppm_dtick = (combined_ppm.max() - combined_ppm.min()) / 10 if not combined_ppm.empty else None
    else:
        ppm_dtick = None

    fig.update_yaxes(title_text="Voltage (V)", range=[0, 5], row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Concentration (ppm/ppb)", dtick=ppm_dtick, row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="°C", row=2, col=1)
    fig.update_yaxes(title_text="%", row=3, col=1)
    fig.update_yaxes(title_text="kPa", row=4, col=1)

    # Explicitly show time on all
    fig.update_xaxes(title_text="Time", row=1, col=1)
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_xaxes(title_text="Time", row=3, col=1)
    fig.update_xaxes(title_text="Time", row=4, col=1)

    fig.update_layout(height=1000)
    return fig

# === Simple PPM Page ===
@app.callback(Output('ppm-graph-only', 'figure'), Input('flowrate-dropdown', 'value'),
              State('stage-dropdown', 'value'), State('substance-dropdown', 'value'))
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
        fig.add_trace(go.Scatter(
            x=sub_df["Timestamp"], y=sub_df[col],
            mode="lines+markers", name=col,
            hovertemplate="%{y:.2f}<br>%{x|%Y-%m-%d %H:%M:%S}"
        ))

    if sub_df["Timestamp"].notnull().any():
        x_min, x_max = sub_df["Timestamp"].min(), sub_df["Timestamp"].max()
        fig.update_xaxes(range=[x_min, x_max])

    fig.update_layout(title=f"{stage} - {substance} | PPM/PPB @ {flow} L/min",
                      xaxis_title="Time", yaxis_title="Concentration (ppm/ppb)", height=700)
    return fig

if __name__ == "__main__":
    os.environ["DASH_DEBUG_MODE"] = "False"
    app.run(debug=True)
