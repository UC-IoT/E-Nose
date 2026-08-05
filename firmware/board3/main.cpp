#include <Arduino.h>
#include <Wire.h>
#include "Air_Quality_Sensor.h"
#include "MutichannelGasSensor.h"
#include "SCD30.h"
#include <SensirionI2CSen5x.h>

// eNose V2 Board3 firmware output
// One compact JSON object is emitted per sample. Human-readable setup messages
// are allowed because the V2 json_line parser ignores non-JSON serial lines.

#define SERIAL_BAUD 9600
#define AQ_SENSOR_PIN A0
#define MULTICHANNEL_ADDR 0x04
#define LOOP_DELAY_MS 3000
#define GAS_MAX_VALID_PPM 1000000.0f

AirQualitySensor aqSensor(AQ_SENSOR_PIN);
SensirionI2CSen5x sen5x;
extern MutichannelGasSensor gas;
extern SCD30 scd30;

static bool firstField = true;

void beginJson() {
    Serial.print("{");
    firstField = true;
}

void endJson() {
    Serial.println("}");
}

void printNumberField(const char* name, float value, const char* unit) {
    if (isnan(value) || isinf(value) || value < -1000000.0f || value > 1000000.0f) return;
    if (!firstField) Serial.print(",");
    firstField = false;
    Serial.print("\""); Serial.print(name); Serial.print("\":{\"value\":");
    Serial.print(value, 3);
    Serial.print(",\"unit\":\""); Serial.print(unit); Serial.print("\"}");
}

void printGasField(const char* name, float value) {
    if (value >= 0 && value < GAS_MAX_VALID_PPM) {
        printNumberField(name, value, "ppm");
    }
}

void setup() {
    Serial.begin(SERIAL_BAUD);
    while (!Serial) {}
    Wire.begin();
    Wire.setClock(100000);

    Serial.println("Board3: initialising sensors");
    Serial.println(aqSensor.init() ? "Board3: air-quality sensor ready" : "Board3: air-quality sensor error");

    gas.begin(MULTICHANNEL_ADDR);
    gas.powerOn();
    Serial.println("Board3: multichannel gas sensor ready");

    scd30.initialize();
    scd30.setTemperatureOffset(250);
    Serial.println("Board3: SCD30 ready");

    sen5x.begin(Wire);
    uint16_t error = sen5x.deviceReset();
    if (error) {
        Serial.println("Board3: SEN55 reset failed");
    } else {
        sen5x.startMeasurement();
        Serial.println("Board3: SEN55 ready");
    }
}

void loop() {
    int qualityStatus = aqSensor.slope();
    int rawAQ = aqSensor.getValue();

    float nh3 = gas.measure_NH3();
    float co = gas.measure_CO();
    float no2 = gas.measure_NO2();
    float ethanol = gas.measure_C2H5OH();

    float co2 = NAN;
    float scdTemperature = NAN;
    float scdHumidity = NAN;
    if (scd30.isAvailable()) {
        float result[3] = {0, 0, 0};
        scd30.getCarbonDioxideConcentration(result);
        co2 = result[0];
        scdTemperature = result[1];
        scdHumidity = result[2];
    }

    float pm1p0 = NAN, pm2p5 = NAN, pm4p0 = NAN, pm10p0 = NAN;
    float vocIndex = NAN, noxIndex = NAN, senTemperature = NAN, senHumidity = NAN;
    uint16_t senError = sen5x.readMeasuredValues(
        pm1p0, pm2p5, pm4p0, pm10p0,
        senHumidity, senTemperature, vocIndex, noxIndex
    );

    beginJson();
    printNumberField("Raw AQ Value", (float)rawAQ, "raw");
    printNumberField("AQ Status", (float)qualityStatus, "code");
    printGasField("NH3", nh3);
    printGasField("CO", co);
    printGasField("NO2", no2);
    printGasField("Ethanol", ethanol);
    printNumberField("CO2", co2, "ppm");
    printNumberField("SCD30 Temperature", scdTemperature, "C");
    printNumberField("SCD30 Humidity", scdHumidity, "%");
    if (!senError) {
        printNumberField("PM1.0", pm1p0, "ug/m3");
        printNumberField("PM2.5", pm2p5, "ug/m3");
        printNumberField("PM4.0", pm4p0, "ug/m3");
        printNumberField("PM10", pm10p0, "ug/m3");
        printNumberField("VOC Index", vocIndex, "index");
        printNumberField("NOx Index", noxIndex, "index");
        printNumberField("SEN55 Temperature", senTemperature, "C");
        printNumberField("SEN55 Humidity", senHumidity, "%");
    }
    endJson();

    delay(LOOP_DELAY_MS);
}

