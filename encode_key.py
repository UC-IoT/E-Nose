import base64
from pathlib import Path

# Path to your JSON file
key_path = Path(r"C:\Users\savin\Documents\workplace\E-Nose\serviceAccountKey.json")

# Read and encode
with open(key_path, "rb") as f:
    encoded = base64.b64encode(f.read()).decode("utf-8")

# Save to encoded.txt
out_path = key_path.parent / "encoded.txt"
with open(out_path, "w") as out:
    out.write(encoded)

print(f"[✓] Encoded key saved to {out_path}")
print("Copy this string into your .env as FIREBASE_CREDENTIALS_BASE64=")
5