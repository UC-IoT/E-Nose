import pandas as pd
from datetime import datetime, timedelta
import serial
import time
import msvcrt
import os
import re

# === User Inputs for Board and Serial Port ===
while True:
    board_input = input("Enter the board number (e.g., 1 for B1): ").strip()
    if board_input in ["1", "2"]:
        board_number = f"B{board_input}"
        break
    else:
        print("Invalid input. Please enter 1 or 2.")
while True:
    try:
        port_number = int(input("Enter the COM port number (e.g., 3 for COM3): ").strip())
        if port_number > 0:
            serial_port = f"COM{port_number}"
            break
        else:
            print("Please enter a valid COM port number greater than 0.")
    except ValueError:
        print("Invalid input. Please enter a numeric value.")

baud_rate = 9600

# === Folder and Substance Inputs ===
# === Folder and Substance Inputs with validation ===
valid_stages = ["Testing", "Experiment", "Deployment"]
while True:
    folder_name = input("Enter the folder name (Experiment, Deployment, Testing): ").strip().title()
    if folder_name in valid_stages:
        break
    else:
        print("Invalid input. Please enter either 'Testing', 'Experiment' or 'Deployment'.")

substance = input("Enter the substance being tested: ").strip().title()
prefix_map = {"Testing": "T", "Experiment": "E", "Deployment": "D"}
folder_prefix = prefix_map[folder_name]
full_folder_path = os.path.join(folder_name, substance)
os.makedirs(full_folder_path, exist_ok=True)
print(f"Folder created or found: {full_folder_path}")

# === Determine session serial number ===
existing_files = os.listdir(full_folder_path)
substance_lower = f"{folder_prefix}{substance}".lower()
matching_files = [f for f in existing_files if f.lower().startswith(substance_lower)]
session_count = len(matching_files) + 1
session_serial = f"{session_count:04d}"

# === Session ID and timestamp ===
timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
session_id = f"{board_number}{folder_prefix}{substance}{session_serial}_{timestamp}"

# === Flowrate Input ===
while True:
    try:
        flow_rate = float(input("Enter the Flowrate of the pump (1 - 5 L/min): ").strip())
        if 1 <= flow_rate <= 5:
            break
        else:
            print("Please enter a flowrate between 1 and 5.")
    except ValueError:
        print("Invalid input. Please enter a numeric value.")

# === Duration & Interval Inputs ===
while True:
    try:
        duration_minutes = float(input("Enter duration of capture (in minutes): ").strip())
        if duration_minutes > 0:
            break
        else:
            print("Please enter a positive duration.")
    except ValueError:
        print("Invalid input. Please enter a numeric value.")

while True:
    try:
        interval = float(input("Enter interval between readings (in seconds): ").strip())
        if interval > 0:
            break
        else:
            print("Interval must be greater than 0.")
    except ValueError:
        print("Invalid input. Please enter a numeric value.")

start_time = datetime.now()
end_time = start_time + timedelta(minutes=duration_minutes)

print(f"\nStarting data capture for {duration_minutes} minutes every {interval} seconds...")
print("Press 'x' at any time to cancel.\n")

# === CSV Output File ===
filename = os.path.join(full_folder_path, f"{session_id}.csv")

# === Start Serial Communication ===
ser = serial.Serial(serial_port, baud_rate, timeout=2)
time.sleep(2)

data_sets = []
capturing = False
current_data = {}
current_group = ""

# === Helper to clean strings ===
def clean_text(text):
    return re.sub(r'[^\x00-\x7F°]', '', text)

def extract_numeric(val):
    return re.sub(r"[^\d\.]+", "", val)

try:
    while datetime.now() < end_time:
        if msvcrt.kbhit():
            key = msvcrt.getwch()
            if key.lower() == 'x':
                print("\nData capture cancelled by user.")
                break

        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        line = clean_text(line)

        if line == "New Data":
            if current_data:
                current_data["Timestamp"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                current_data["Flowrate (L/min)"] = flow_rate
                data_sets.append(current_data)
                print(f"Captured ({len(data_sets)}):", current_data)
                current_data = {}
                time.sleep(interval)
            capturing = True
            current_group = "General"
            continue

        if not capturing:
            continue

        if line.startswith("Reading "):
            current_group = line.replace("Reading", "").replace("...", "").strip()
            continue

        fixed_line = line.replace(":", ": ").replace("  ", " ").strip()
        parts = [p.strip() for p in fixed_line.split(":", maxsplit=2)]

        if len(parts) == 3:
            key, val1, val2 = parts
            val1, val2 = clean_text(val1), clean_text(val2)
            key = clean_text(key)

            if any(unit in val1 for unit in ["ppm", "ppb", "%", "°C", "KPa", "Kohms"]):
                unit = re.findall(r"(ppm|ppb|%|°C|KPa|Kohms)", val1)
                if unit:
                    unit_str = unit[0]
                    name_base = f"{current_group} - {key}"
                    val1_with_unit = val1 if unit_str in val1 else f"{val1} {unit_str}"
                    current_data[f"{name_base} ({unit_str})"] = val1_with_unit
                    current_data[f"{name_base} (V)"] = extract_numeric(val2)
            else:
                current_data[f"{current_group} - {key}"] = f"{val1} : {val2}"

        elif len(parts) == 2:
            key, val = parts
            key_clean = clean_text(key)
            val_clean = clean_text(val)

            if val_clean.endswith("V"):
                try:
                    numeric_val = float(val_clean.replace("V", "").strip())
                    current_data[f"{current_group} - {key_clean} (V)"] = numeric_val
                except ValueError:
                    current_data[f"{current_group} - {key_clean}"] = val_clean
            else:
                current_data[f"{current_group} - {key_clean}"] = val_clean

except Exception as e:
    print(f"\nError occurred: {e}")

finally:
    ser.close()
    print("Serial connection closed.")

# === Export to CSV ===
if data_sets:
    df = pd.DataFrame(data_sets)
    cols = ['Timestamp', 'Flowrate (L/min)'] + [col for col in df.columns if col not in ['Timestamp', 'Flowrate (L/min)']]
    df = df[cols]
    df.columns = [clean_text(c).replace("Â", "").strip() for c in df.columns]

    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"\nCSV file saved with {len(data_sets)} readings: {filename}")

    cumulative_filename = os.path.join(full_folder_path, f"{substance}_Readings.csv")
    if os.path.exists(cumulative_filename):
        df.to_csv(cumulative_filename, mode='a', index=False, header=False, encoding="utf-8-sig")
        print(f"Appended data to cumulative file: {cumulative_filename}")
    else:
        df.to_csv(cumulative_filename, index=False, encoding="utf-8-sig")
        print(f"Cumulative file created: {cumulative_filename}")
else:
    print("\nNo data captured. CSV file was not created.")

# === Session Summary ===
save_summary = input("\nDo you want to save a summary for this session? (y/n): ").strip().lower()

if save_summary == 'y':
    date_str = datetime.now().strftime("%d-%m-%Y")
    time_str = datetime.now().strftime("%H:%M:%S")
    total_duration = round(duration_minutes * 60)
    minutes, seconds = divmod(total_duration, 60)
    duration_string = f"{minutes} minutes" if seconds == 0 else f"{minutes} minutes and {seconds} seconds" if minutes > 0 else f"{seconds} seconds"

    frequency_string = f"every {int(interval)} seconds" if interval != 1 else "every second"

    print("\nEnter any notes for this session (optional). Press Enter if none:")
    user_notes = input("> ").strip()

    board_num_only = board_number[-1] 
    summary_lines = [
        f"Date:        {date_str}",
        f"Time:        {time_str}",
        f"Board Number: {board_num_only}",
        f"Substance:   {substance}",
        f"Flowrate:    {flow_rate} L/min",
        f"Duration:    {duration_string}",
        f"Frequency:   {frequency_string}",
        "",
        "Notes:"
    ]

    summary_lines.append(user_notes if user_notes else "(No notes entered)")

    summary_text = "\n".join(summary_lines)
    summary_file = os.path.join(full_folder_path, f"{session_id}.txt")

    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(summary_text)

    print(f"\nSummary saved to: {summary_file}")
else:
    print("Summary not saved.")
