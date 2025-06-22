import pandas as pd
from datetime import datetime
import serial
import time
import msvcrt  

# === Serial Configuration ===
serial_port = "COM3"  
baud_rate = 9600

# === User Input ===
num_data = int(input("Enter the number of data sets to capture: "))
interval = float(input("Enter interval between readings (in seconds): "))

# === CSV Output File ===
timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
filename = f"eNose_Readings_{timestamp}.csv"

# === Start Serial Communication ===
ser = serial.Serial(serial_port, baud_rate, timeout=2)
time.sleep(2)

print(f"\nStarting data capture for {num_data} sets every {interval} seconds...")
print("Press 'x' at any time to cancel.\n")

data_sets = []
data_count = 0
capturing = False
current_data = {}
current_group = ""

try:
    while data_count < num_data:

        if msvcrt.kbhit():
            key = msvcrt.getwch()
            if key.lower() == 'x':
                print("\nData capture cancelled by user.")
                break

        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        if line == "New Data":
            if current_data:
                current_data["Timestamp"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                data_sets.append(current_data)
                print(f"Captured ({data_count + 1}/{num_data}):", current_data)
                data_count += 1
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

        parts = [p.strip() for p in line.split(":", maxsplit=2)]

        if len(parts) == 3:
            key, val1, val2 = parts
            if any(unit in val1 for unit in ["ppm", "ppb", "%", "°C", "KPa", "Kohms"]):
                name_base = f"{current_group} - {key}"
                unit = val1.split()[-1]
                current_data[f"{name_base} ({unit})"] = val1
                current_data[f"{name_base} (V)"] = val2
            else:
                current_data[f"{current_group} - {key}"] = f"{val1} : {val2}"

        elif len(parts) == 2:
            key, val = parts
            current_data[f"{current_group} - {key}"] = val

except Exception as e:
    print(f"\nError occurred: {e}")

finally:
    ser.close()
    print("Serial connection closed.")

# === Export to CSV ===
if data_sets:
    df = pd.DataFrame(data_sets)
    cols = ['Timestamp'] + [col for col in df.columns if col != 'Timestamp']
    df = df[cols]
    df.to_csv(filename, index=False)
    print(f"\nCSV file saved with {len(data_sets)} readings: {filename}")
else:
    print("\nNo data captured. CSV file was not created.")
