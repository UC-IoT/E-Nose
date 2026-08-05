# Board3 firmware variant

This `main.cpp` replaces the human-oriented serial report with one JSON object per sample. Copy it into the existing Board3 PlatformIO project's `src/main.cpp` only after inspecting it and confirming the connected sensor set.

Example output:

```json
{"Raw AQ Value":{"value":312,"unit":"raw"},"NH3":{"value":1.2,"unit":"ppm"},"CO2":{"value":451,"unit":"ppm"}}
```

The V2 board registry configures B3 to use `board3_auto` at 9600 baud. This accepts both the currently flashed sectioned report and this proposed JSON-line format, so the dashboard continues working before and after a firmware upgrade.

The DFRobot H2 sensor remains excluded because it is commented out in the supplied firmware and therefore has not been treated as an active, validated sensor. It should be integrated only after the I2C address and physical readings are confirmed.
