import os
import pandas as pd
import plotly.graph_objects as go
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

voltage_columns = [col for col in df.columns if col.endswith("(V)")]
for col in voltage_columns:
    df[col] = df[col].astype(str).str.replace(" V", "", regex=False)
    df[col] = pd.to_numeric(df[col], errors='coerce')

if 'Flowrate (L/min)' not in df.columns:
    print("Flowrate column not found.")
    exit()

unique_flowrates = sorted(df['Flowrate (L/min)'].dropna().unique())

# === Create Plotly Figure ===
fig = go.Figure()
trace_lookup = []

def clean_legend_name(col_name):
    name = col_name.replace(" (V)", "")
    match = re.match(r"(.*? - .*?) \((.*?)\)$", name)
    if match:
        base, gas = match.groups()
        return f"{base} ({gas})"
    return name

for flow in unique_flowrates:
    sub_df = df[df['Flowrate (L/min)'] == flow]
    for col in voltage_columns:
        legend_name = clean_legend_name(col)
        fig.add_trace(go.Scatter(
            x=sub_df['Timestamp'],
            y=sub_df[col],
            mode='lines+markers',
            name=legend_name,
            visible=(flow == unique_flowrates[0])
        ))
        trace_lookup.append(flow)

# === Build visibility for each flowrate ===
def build_visibility(selected_flow):
    return [f == selected_flow for f in trace_lookup]

# === Dropdown Buttons for Flowrate Filtering ===
dropdown_buttons = []
for flow in unique_flowrates:
    visibility = build_visibility(flow)
    dropdown_buttons.append(dict(
        label=f"{flow} L/min",
        method="update",
        args=[{"visible": visibility},
              {"title": f"{stage_input} - {substance_input} | Voltage Readings at {flow} L/min"}]
    ))

# === Final Layout ===
fig.update_layout(
    title=f"{stage_input} - {substance_input} | Voltage Readings at {unique_flowrates[0]} L/min",
    xaxis_title="Time",
    yaxis=dict(title="Voltage (V)", range=[0, 5]),
    updatemenus=[dict(
        active=0,
        buttons=dropdown_buttons,
        x=0.1,
        y=1.15,
        xanchor='left',
        yanchor='top'
    )],
    height=700
)

fig.show()
