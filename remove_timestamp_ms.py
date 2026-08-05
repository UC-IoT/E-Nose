from __future__ import annotations

import csv
import os
import sys
from pathlib import Path


def remove_timestamp_ms(root: Path) -> tuple[int, int, list[Path]]:
    scanned = changed = 0
    locked: list[Path] = []
    for path in sorted(root.rglob("*.csv")):
        scanned += 1
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "Timestamp_ms" not in reader.fieldnames:
                continue
            fields = [field for field in reader.fieldnames if field != "Timestamp_ms"]
            rows = list(reader)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        try:
            os.replace(temporary, path)
            changed += 1
        except PermissionError:
            locked.append(path)
            temporary.unlink(missing_ok=True)
    return scanned, changed, locked


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "data"
    scanned, changed, locked = remove_timestamp_ms(target)
    print(f"Scanned {scanned} CSV files; removed Timestamp_ms from {changed} files.")
    for path in locked:
        print(f"LOCKED: {path}")
    raise SystemExit(1 if locked else 0)
