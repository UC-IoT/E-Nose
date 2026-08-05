# E-Nose Dashboard

A configuration-driven Dash application for capturing, viewing and comparing sensor readings from B1, B2, B3, LB1 and LB2. Every capture is written to local CSV first and can also be uploaded to Firebase Realtime Database.

## Features

- Testing, Experiment, Deployment and Baseline capture types
- Automatic board enabling when a COM port is selected
- Live graphs grouped into collapsible board sections
- Background Firebase uploads with a durable retry queue
- Research page for overlaying a selected baseline with any saved session
- Board Manager for adding compatible serial boards without changing dashboard code
- Per-session folders and per-board CSV files

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- USB drivers for the connected boards
- Access to a Firebase Realtime Database if cloud upload is required

## Install and run

Open PowerShell in this folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

The dashboard opens at [http://127.0.0.1:8051](http://127.0.0.1:8051). Use `python app.py --no-browser` when you do not want it to open a browser automatically.

## Firebase configuration

The repository deliberately does not contain a live Firebase project URL, database secret or service-account key. Each installation must supply its own configuration.

For complete instructions for a new computer, see [FIREBASE_SETUP.md](FIREBASE_SETUP.md).

### Recommended local configuration

1. Copy `config/settings.example.json` to `config/settings.json`.
2. Replace `YOUR_PROJECT_ID` in the new file with the Firebase project ID.
3. Download a service-account JSON file from Firebase/Google Cloud and store it outside the repository.
4. Point the application to it before starting:

```powershell
$env:FIREBASE_CREDENTIALS_PATH = "C:\secure\path\serviceAccountKey.json"
python app.py
```

`config/settings.json` and all `serviceAccountKey.json` files are ignored by Git.

### Environment-variable configuration

The database address can instead be supplied for the current PowerShell window:

```powershell
$env:DATABASE_URL = "https://YOUR_PROJECT_ID-default-rtdb.firebaseio.com/"
$env:FIREBASE_CONSOLE_URL = "https://console.firebase.google.com/project/YOUR_PROJECT_ID/database/YOUR_PROJECT_ID-default-rtdb/data/"
$env:FIREBASE_CREDENTIALS_PATH = "C:\secure\path\serviceAccountKey.json"
python app.py
```

Environment variables override `config/settings.json`. Do not commit credentials, private keys or database secrets. Configure Firebase Realtime Database rules so unauthenticated public writes are not allowed. If Firebase is unavailable, capture still continues locally and pending records are saved for retry from the Firebase page.

## Finding COM ports on Windows

1. Connect the boards by USB.
2. Right-click the Windows Start button and open **Device Manager**.
3. Expand **Ports (COM & LPT)**.
4. Note the COM number shown for each board, such as `COM8`.
5. Close Arduino Serial Monitor, Waspmote IDE monitors and other programs using those ports. Only one program can open a COM port at a time.
6. In the dashboard, open Capture, press **Refresh COM ports**, and assign the ports. Selecting a port enables that board automatically.

## Capture workflow

1. Open Capture and select Testing, Experiment, Deployment or Baseline. This selection also determines the storage stage.
2. Enter the sample label, duration, interval and any other required capture details.
3. Refresh and assign the COM ports.
4. Press Start and keep the dashboard process running until capture finishes.
5. View current readings on Live or revisit completed data on Sessions.

Sessions are stored under:

```text
data/<capture-type>/<sample>/<session-id>/
  session.json
  <BOARD>_Readings.csv
  summary.json
  firebase_pending.jsonl   # present only when an upload needs retrying
```

The `data` directory is ignored by Git so captured research data is not accidentally published.

## Baselines and Research

Choose Baseline as the capture type to record a clean-air reference. On Research, select that baseline and any available session. Matching sensors are plotted together using elapsed time, with graphs grouped into expandable board sections.

## Adding a board

Open Board Manager and provide a unique board ID, display name, baud rate, Firebase ID and supported parser. `json_line` is the preferred protocol; each serial line should contain one JSON object:

```json
{"Sensor name":{"value":12.3,"unit":"ppm"}}
```

Metadata fields may begin with `_`, including `_timestamp_ms`, `_battery_percent` and `_battery_volts`. B3 currently uses `board3_auto`, which accepts both its human-readable sectioned report and the proposed JSON-line firmware in `firmware/board3`.

## Tests

Run the hardware-independent test suite with:

```powershell
python -m unittest discover -s tests -v
```

Physical serial capture and Firebase permissions should also be checked on the target computer before a live experiment.

## Safe contribution workflow

Create a branch, commit the application changes, push that branch, and open a pull request into `main`. Never commit local data or Firebase credentials, and do not force-push the shared `main` branch.
