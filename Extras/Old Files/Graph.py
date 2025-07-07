import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re

# === Get user input for stage and substance ===
stage_input = input("Enter the project stage (Testing, Experiment, Deployment): ").strip().title()
while stage_input not in ["Testing", "Experiment", "Deployment"]:
    stage_input = input("Invalid stage. Please enter Testing, Experiment, or Deployment: ").strip().title()

substance_input = input("Enter the substance being tested: ").strip().title()

# === Construct file path ===
folder_path = os.path.join(stage_input, substance_input)
file_name = f"{substance_input}_Readings.csv"
file_path = os.path.join(folder_path, file_name)

if not os.path.exists(file_path):
    print(f"File not found: {file_path}")
    exit()

# === Load CSV ===
df = pd.read_csv(file_path)
df.columns = [col.strip() for col in df.columns]

# === Preprocess ===
if "Timestamp" in df.columns:
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors='coerce')

if 'Flowrate (L/min)' not in df.columns:
    print("Flowrate column not found.")
    exit()

# === Identify column groups ===
voltage_columns = [col for col in df.columns if col.endswith("(V)")]
sensor_keywords = ["Temperature", "Pressure", "Humidity"]
voltage_columns = [col for col in voltage_columns if not any(k in col for k in sensor_keywords) and "BME688" not in col]

for col in voltage_columns:
    df[col] = df[col].astype(str).str.replace(" V", "", regex=False)
    df[col] = pd.to_numeric(df[col], errors='coerce')

bme_columns = {
    "BME688 - temperature (°C)": (2, "Temperature (°C)"),
    "BME688 - humidity (%)": (3, "Humidity (%)"),
    "BME688 - pressure (KPa)": (4, "Pressure (kPa)")
}

unique_flowrates = sorted(df['Flowrate (L/min)'].dropna().unique())

# === Create Subplots ===
fig = make_subplots(
    rows=4, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.07,  # More space between rows
    row_heights=[0.45, 0.2, 0.2, 0.15],  # Make Row 1 larger
    subplot_titles=[
        f"{stage_input} - {substance_input} | Voltage Readings",
        "Temperature (°C)",
        "Humidity (%)",
        "Pressure (kPa)"
    ]
)


trace_lookup = []

def clean_legend_name(col_name):
    col_name = col_name.replace(" (V)", "")
    match = re.match(r"(.*? - .*?) \((.*?)\)$", col_name)
    if match:
        base, gas = match.groups()
        return f"{base} ({gas})"
    return col_name

# === Row 1: Voltage Traces ===
for flow in unique_flowrates:
    sub_df = df[df['Flowrate (L/min)'] == flow]
    for col in voltage_columns:
        legend_name = clean_legend_name(col)
        fig.add_trace(go.Scatter(
            x=sub_df['Timestamp'],
            y=sub_df[col],
            mode='lines+markers',
            name=f"{legend_name}",
            visible=(flow == unique_flowrates[0])
        ), row=1, col=1)
        trace_lookup.append(flow)

# === Rows 2–4: BME688 Sensor Data ===
for col_name, (row_idx, label) in bme_columns.items():
    if col_name in df.columns:
        fig.add_trace(go.Scatter(
            x=df['Timestamp'],
            y=df[col_name],
            mode='lines',
            name=label,
            line=dict(shape='spline'),
            showlegend=True
        ), row=row_idx, col=1)

# === Visibility function ===
def build_visibility(selected_flow):
    vis = [f == selected_flow for f in trace_lookup]
    vis += [True] * len(bme_columns)  # Always show BME traces
    return vis

# === Time ranges per flowrate ===
flow_time_ranges = {}
for flow in unique_flowrates:
    sub_df = df[df['Flowrate (L/min)'] == flow]
    flow_time_ranges[flow] = [sub_df['Timestamp'].min(), sub_df['Timestamp'].max()]

# === Dropdown Buttons ===
dropdown_buttons = []
for flow in unique_flowrates:
    time_range = flow_time_ranges[flow]
    visibility = build_visibility(flow)
    dropdown_buttons.append(dict(
        label=f"{flow} L/min",
        method="update",
        args=[
            {"visible": visibility},
            {
                "title": f"{stage_input} - {substance_input} | Voltage Readings at {flow} L/min",
                "xaxis.range": [time_range[0], time_range[1]],
                "xaxis2.range": [time_range[0], time_range[1]],
                "xaxis3.range": [time_range[0], time_range[1]],
                "xaxis4.range": [time_range[0], time_range[1]]
            }
        ]
    ))

# === Layout ===
fig.update_layout(
    title=f"{stage_input} - {substance_input} | Voltage Readings at {unique_flowrates[0]} L/min",
    height=1000,
    xaxis_title="Time",
    yaxis=dict(
        title=dict(text="Voltage (V)", font=dict(color="blue")),
        range=[0, 5]
    ),
    updatemenus=[dict(
        active=0,
        buttons=dropdown_buttons,
        x=0.1,
        y=1.2,
        xanchor='left',
        yanchor='top'
    )]
)

fig.update_yaxes(title_text="Voltage (V)", row=1, col=1)
fig.update_yaxes(title_text="°C", row=2, col=1)
fig.update_yaxes(title_text="%", row=3, col=1)
fig.update_yaxes(title_text="kPa", row=4, col=1)

fig.show()

