# Firebase Setup

This guide connects a new E-Nose dashboard installation to the shared Firebase Realtime Database. Complete it once on each computer.

## Before you start

You need:

- Access to the `project-enose` Firebase project.
- Python and the dashboard dependencies installed.
- A service-account key supplied securely by the Firebase administrator, if authenticated access is required.

Never commit, email or post a service-account key, private key or database secret.

## 1. Clone and install the dashboard

```powershell
git clone https://github.com/UC-IoT/E-Nose.git
cd E-Nose
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 2. Create the local Firebase settings

Copy the public template to the private local settings file:

```powershell
Copy-Item config\settings.example.json config\settings.json
notepad config\settings.json
```

Replace the file contents with:

```json
{
  "database_url": "https://project-enose-default-rtdb.firebaseio.com/",
  "firebase_console_url": "https://console.firebase.google.com/project/project-enose/database/project-enose-default-rtdb/data/"
}
```

Save and close Notepad. `config/settings.json` is ignored by Git and must remain uncommitted.

## 3. Configure authenticated access

Ask the Firebase administrator for approved access. On a controlled laboratory computer, store the supplied service-account JSON outside the repository, for example:

```text
C:\Users\YOUR_NAME\FirebaseKeys\project-enose-service-account.json
```

Set its location permanently for the current Windows user:

```powershell
[Environment]::SetEnvironmentVariable(
    "FIREBASE_CREDENTIALS_PATH",
    "C:\Users\YOUR_NAME\FirebaseKeys\project-enose-service-account.json",
    "User"
)
```

Close PowerShell and open a new PowerShell window after setting the variable.

Do not put the key in the repository. Do not rename it to `serviceAccountKey.json` inside the project folder. If a key is accidentally committed or shared, notify the Firebase administrator immediately so it can be revoked and replaced.

## 4. Run and verify

```powershell
cd C:\path\to\E-Nose
.\.venv\Scripts\Activate.ps1
python app.py
```

In the dashboard:

1. Open **Firebase**.
2. Click **Check Firebase connection**.
3. Confirm the connection says **Online and verified**.
4. If records were captured while offline, click **Retry pending records**.

## Troubleshooting

### `DATABASE_URL is not set`

Confirm `config/settings.json` exists and contains the database URL shown above. Make sure it is named `settings.json`, not `settings.json.txt`, and restart the Python dashboard.

### Credentials or permission error

Check the configured file exists:

```powershell
Test-Path $env:FIREBASE_CREDENTIALS_PATH
```

The result should be `True`. If it is `False` or the environment variable is empty, set the correct path again and open a new PowerShell window.

### Firebase is unavailable during capture

Keep capturing. The dashboard writes CSV data locally first and queues unsuccessful Firebase uploads. Restore the connection later and use **Retry pending records**.

## Security note

An administrator service-account key has broad privileges and is suitable only for controlled computers. For wider deployment, use individual Firebase Authentication accounts and restricted Realtime Database rules instead of distributing administrator credentials.
