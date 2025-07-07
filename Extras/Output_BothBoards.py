import pandas as pd
from datetime import datetime, timedelta
import serial
import threading
import time
import msvcrt
import os
import re

# === Helper to clean strings ===
def clean_text(text):
    return re.sub(r'[^\x00-\x7F°]', '', text)

def extract_numeric(val):
    return re.sub(r"[^\d\.]+", "", val)

# === User Inputs ===
while True:
    board_mode = input("Do you want to test (1) one board or (2) both boards? Enter 1 or 2: ").strip()
    if board_mode in ["1", "2"]:
        break
    else:
        print("Invalid input. Please enter 1 or 2.")

boards = []
if board_mode == "1":
    while True:
        board_input = input("Enter the board number (1 or 2): ").strip()
        if board_input in ["1", "2"]:
            board_number = f"B{board_input}"
            break
        else:
            print("Invalid input. Please enter 1 or 2.")
    while True:
        try:
            port_number = int(input(f"Enter the COM port number for {board_number}: ").strip())
            if port_number > 0:
                serial_port = f"COM{port_number}"
                boards.append( (board_number, serial_port) )
                break
            else:
                print("Please enter a valid COM port number greater than 0.")
        except ValueError:
            print("Invalid input. Please enter a numeric value.")

else:  # board_mode == "2"
    for i in [1,2]:
        while True:
            try:
                port_number = int(input(f"Enter the COM port number for Board B{i}: ").strip())
                if port_number > 0:
                    boards.append( (f"B{i}", f"COM{port_number}") )
                    break
                else:
                    print("Please enter a valid COM port number greater than 0.")
            except ValueError:
                print("Invalid input. Please enter a numeric value.")

baud_rate = 9600

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
base_file_match = f"{''.join([b[0] for b in boards])}{folder_prefix}{substance}".lower()
matching_files = [f for f in existing_files if f.lower().startswith(base_file_match)]
session_count = len(matching_files) + 1
session_serial = f"{session_count:04d}"

# === Session ID ===
timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
session_id = f"{''.join([b[0] for b in boards])}{folder_prefix}{substance}{session_serial}_{timestamp}"

# === Flowrate, Duration, Interval ===
while True:
    try:
        flow_rate = float(input("Enter the Flowrate of the pump (1 - 5 L/min): ").strip())
        if 1 <= flow_rate <= 5:
            break
        else:
            print("Please enter a flowrate between 1 and 5.")
    except ValueError:
        print("Invalid input. Please enter a numeric value.")

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

# === Data capture ===
start_time = datetime.now()
end_time = start_time + timedelta(minutes=duration_minutes)

# === CSV filename ===
filename = os.path.join(full_folder_path, f"{session_id}.csv")
cumulative_filename = os.path.join(full_folder_path, f"{substance}_Readings.csv")

# === Data collection function ===
def collect_data(board_label, port, data_list):
    try:
        ser = serial.Serial(port, baud_rate, timeout=2)
        time.sleep(2)
        current_data = {}
        current_group = ""
        capturing = False
        while datetime.now() < end_time:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            line = clean_text(line)
            if line == "New Data":
                if current_data:
                    current_data["Timestamp"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                    current_data["Flowrate (L/min)"] = flow_rate
                    data_list.append(current_data)
                    current_data = {}
                capturing = True
                current_group = "General"
                continue
            if not capturing:
                continue
            if line.startswith("Reading "):
                current_group = line.replace("Reading", "").replace("...", "").strip()
                continue
            parts = [p.strip() for p in line.replace(":", ": ").split(":", maxsplit=2)]
            if len(parts) == 3:
                key, val1, val2 = parts
                key = clean_text(key)
                if any(unit in val1 for unit in ["ppm", "ppb", "%", "°C", "KPa", "Kohms"]):
                    unit = re.findall(r"(ppm|ppb|%|°C|KPa|Kohms)", val1)
                    if unit:
                        unit_str = unit[0]
                        name_base = f"{board_label} - {current_group} - {key}"
                        current_data[f"{name_base} ({unit_str})"] = val1
                        current_data[f"{name_base} (V)"] = extract_numeric(val2)
                else:
                    current_data[f"{board_label} - {current_group} - {key}"] = f"{val1} : {val2}"
            elif len(parts) == 2:
                key, val = parts
                key_clean = clean_text(key)
                val_clean = clean_text(val)
                if val_clean.endswith("V"):
                    try:
                        numeric_val = float(val_clean.replace("V", "").strip())
                        current_data[f"{board_label} - {current_group} - {key_clean} (V)"] = numeric_val
                    except ValueError:
                        current_data[f"{board_label} - {current_group} - {key_clean}"] = val_clean
                else:
                    current_data[f"{board_label} - {current_group} - {key_clean}"] = val_clean
        ser.close()
    except Exception as e:
        print(f"\nError on {board_label}: {e}")

# === Start threads for each board ===
board_data_lists = []
threads = []
for board_label, port in boards:
    data_list = []
    t = threading.Thread(target=collect_data, args=(board_label, port, data_list))
    t.start()
    board_data_lists.append(data_list)
    threads.append(t)

print(f"\nCapturing data for {duration_minutes} min every {interval} sec on {' & '.join([b[0] for b in boards])}.\nPress 'x' anytime to stop.\n")

# === Main time loop ===
try:
    while datetime.now() < end_time:
        if msvcrt.kbhit() and msvcrt.getwch().lower() == 'x':
            print("\nCapture cancelled by user.")
            break
        time.sleep(interval)
except KeyboardInterrupt:
    print("\nInterrupted by user.")

# === Wait for threads ===
for t in threads:
    t.join()

# === Merge data into unified table ===
combined_records = []
max_len = max(len(dl) for dl in board_data_lists)
for i in range(max_len):
    record = {}
    for data_list in board_data_lists:
        if i < len(data_list):
            record.update(data_list[i])
    combined_records.append(record)

# === Export to CSV ===
if combined_records:
    df = pd.DataFrame(combined_records)
    cols = ['Timestamp', 'Flowrate (L/min)'] + [c for c in df.columns if c not in ['Timestamp', 'Flowrate (L/min)']]
    df = df[cols]
    df.columns = [clean_text(c).replace("Â", "").strip() for c in df.columns]
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"\nSession file saved: {filename}")

    if os.path.exists(cumulative_filename):
        df.to_csv(cumulative_filename, mode='a', index=False, header=False, encoding="utf-8-sig")
        print(f"Appended to cumulative: {cumulative_filename}")
    else:
        df.to_csv(cumulative_filename, index=False, encoding="utf-8-sig")
        print(f"Cumulative created: {cumulative_filename}")
else:
    print("\nNo data captured. CSV not created.")

# === Session summary ===
if input("\nSave summary? (y/n): ").strip().lower() == 'y':
    now = datetime.now()
    duration_string = f"{int(duration_minutes)} minutes"
    freq_string = f"every {int(interval)} sec"
    boards_tested = " & ".join([b[0] for b in boards])
    notes = input("Enter any notes (optional): ").strip()
    summary_text = f"""
Date:        {now.strftime("%d-%m-%Y")}
Time:        {now.strftime("%H:%M:%S")}
Boards:      {boards_tested}
Substance:   {substance}
Flowrate:    {flow_rate} L/min
Duration:    {duration_string}
Frequency:   {freq_string}
Notes:       {notes if notes else '(No notes entered)'}
""".strip()
    summary_file = os.path.join(full_folder_path, f"{session_id}.txt")
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(summary_text)
    print(f"\nSummary saved: {summary_file}")
else:
    print("Summary not saved.")
