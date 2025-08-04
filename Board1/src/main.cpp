#include <Arduino.h>
#include <Wire.h>
#include <bsec2.h>

// Sensors' libraries
#include <Multichannel_Gas_GMXXX.h>
#include "sgp30.h"
#include "sensirion_common.h"
#include <SensirionI2cSfa3x.h>
#include "bme68xLibrary.h"

// Define
#define IIC_ADDR uint8_t(0x76) // BME688 I2C address
#define NEW_GAS_MEAS (BME68X_GASM_VALID_MSK | BME68X_HEAT_STAB_MSK | BME68X_NEW_DATA_MSK)
#define BME68X_I2C_ADDR 0x76

#ifndef PIN_CS
#define PIN_CS SS
#endif
Bme68x bme;

#define PANIC_LED LED_BUILTIN
#define ERROR_DUR 1000
#define SAMPLE_RATE BSEC_SAMPLE_RATE_LP

Bsec2 envSensor;

// Function prototypes
void checkBsecStatus(Bsec2 &bsec);
void newDataCallback(bme68xData data, bsecOutputs outputs, Bsec2 bsec);
void errLeds(void);

SensirionI2cSfa3x sensor; // Formaldehyde sensor
GAS_GMXXX<TwoWire> gas;   // Multichannel gas sensor

// -------------------- Sensor Setup Functions --------------------

void MultichannelGasSensorSetup()
{
    Serial.println("Initiating MutichannelGasSensor...");
    gas.begin(Wire, 0x08);
}

void SGP30Setup()
{
    Serial.println("Initiating SGP30...");
    s16 err;
    u16 scaled_ethanol_signal, scaled_h2_signal;

    int attempts = 0;
    while (sgp_probe() != STATUS_OK && attempts < 5)
    {
        Serial.println("SGP30 probe failed, retrying...");
        delay(500);
        attempts++;
    }

    if (attempts >= 5)
    {
        Serial.println("SGP30 initialization failed.");
        return;
    }

    err = sgp_measure_signals_blocking_read(&scaled_ethanol_signal, &scaled_h2_signal);
    if (err == STATUS_OK)
    {
        Serial.println("SGP30: got raw signals.");
    }
    else
    {
        Serial.println("SGP30: error reading signals.");
    }

    sgp_iaq_init();
}

void BME688Setup()
{
    pinMode(PANIC_LED, OUTPUT);

    if (!envSensor.begin(BME68X_I2C_ADDR_LOW, Wire))
    {
        checkBsecStatus(envSensor);
    }

    if (SAMPLE_RATE == BSEC_SAMPLE_RATE_ULP)
    {
        envSensor.setTemperatureOffset(TEMP_OFFSET_ULP);
    }
    else if (SAMPLE_RATE == BSEC_SAMPLE_RATE_LP)
    {
        envSensor.setTemperatureOffset(TEMP_OFFSET_LP);
    }

    bsecSensor sensorList[] = {
        BSEC_OUTPUT_IAQ,
        BSEC_OUTPUT_RAW_TEMPERATURE,
        BSEC_OUTPUT_RAW_PRESSURE,
        BSEC_OUTPUT_RAW_HUMIDITY,
        BSEC_OUTPUT_RAW_GAS,
        BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_TEMPERATURE,
        BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_HUMIDITY,
        BSEC_OUTPUT_STATIC_IAQ,
        BSEC_OUTPUT_CO2_EQUIVALENT,
        BSEC_OUTPUT_BREATH_VOC_EQUIVALENT,
        BSEC_OUTPUT_GAS_PERCENTAGE,
        BSEC_OUTPUT_COMPENSATED_GAS,
        BSEC_OUTPUT_RUN_IN_STATUS,
        BSEC_OUTPUT_STABILIZATION_STATUS};

    if (!envSensor.updateSubscription(sensorList, ARRAY_LEN(sensorList), SAMPLE_RATE))
    {
        checkBsecStatus(envSensor);
    }

    // Attach callback (signature must match exactly)
    envSensor.attachCallback(newDataCallback);

    Serial.print("BSEC library version ");
    Serial.print(envSensor.version.major);
    Serial.print(".");
    Serial.print(envSensor.version.minor);
    Serial.print(".");
    Serial.print(envSensor.version.major_bugfix);
    Serial.print(".");
    Serial.println(envSensor.version.minor_bugfix);
}

void FormaldehydeSetup()
{
#ifdef NO_ERROR
#undef NO_ERROR
#endif
#define NO_ERROR 0

    static char errorMessage[64];
    static int16_t error;

    Serial.println("Initiating Formaldehyde...");
    sensor.begin(Wire, SFA3X_I2C_ADDR_5D);

    error = sensor.deviceReset();
    if (error != NO_ERROR)
    {
        Serial.print("Error deviceReset(): ");
        errorToString(error, errorMessage, sizeof errorMessage);
        Serial.println(errorMessage);
        return;
    }

    delay(1000);

    int8_t deviceMarking[32] = {0};
    error = sensor.getDeviceMarking(deviceMarking, 32);
    if (error != NO_ERROR)
    {
        Serial.print("Error getDeviceMarking(): ");
        errorToString(error, errorMessage, sizeof errorMessage);
        Serial.println(errorMessage);
        return;
    }

    Serial.print("deviceMarking: ");
    Serial.println((const char *)deviceMarking);

    error = sensor.startContinuousMeasurement();
    if (error != NO_ERROR)
    {
        Serial.print("Error startContinuousMeasurement(): ");
        errorToString(error, errorMessage, sizeof errorMessage);
        Serial.println(errorMessage);
        return;
    }
}

// -------------------- Sensor Reading Functions --------------------

void MultichannelGasSensorRead()
{
    Serial.println("Reading Multichannel Gas Sensor...");
    uint32_t val;

    val = gas.getGM102B();
    Serial.print("GM102B (NO2):    ");
    Serial.print(val);
    Serial.println(" ppm");

    val = gas.getGM302B();
    Serial.print("GM302B (C2H5CH): ");
    Serial.print(val);
    Serial.println(" ppm");

    val = gas.getGM502B();
    Serial.print("GM502B (VOC):    ");
    Serial.print(val);
    Serial.println(" ppm");

    val = gas.getGM702B();
    Serial.print("GM702B (CO):     ");
    Serial.print(val);
    Serial.println(" ppm");
}

void SGP30Read()
{
    s16 err = 0;
    u16 tvoc_ppb, co2_eq_ppm;

    Serial.println("Reading SGP30...");
    err = sgp_measure_iaq_blocking_read(&tvoc_ppb, &co2_eq_ppm);
    if (err == STATUS_OK)
    {
        Serial.print("tVOC:  ");
        Serial.print(tvoc_ppb);
        Serial.println(" ppb");

        Serial.print("CO2eq: ");
        Serial.print(co2_eq_ppm);
        Serial.println(" ppm");
    }
    else
    {
        Serial.println("SGP30: error reading IAQ values");
    }
}

void BME688Read()
{
    if (!envSensor.run())
    {
        checkBsecStatus(envSensor);
    }
}

void FormaldehydeRead(SensirionI2cSfa3x &sensor)
{
    static int16_t error;
    float hcho = 0.0, humidity = 0.0, temperature = 0.0;

    delay(500);
    error = sensor.readMeasuredValues(hcho, humidity, temperature);
    if (error != NO_ERROR)
    {
        Serial.println("Error reading Formaldehyde values");
        return;
    }

    Serial.println("Reading Formaldehyde...");
    Serial.print("hcho:        ");
    Serial.print(hcho);
    Serial.println(" ppb");

    Serial.print("humidity:    ");
    Serial.print(humidity);
    Serial.println(" %");

    Serial.print("temperature: ");
    Serial.print(temperature);
    Serial.println(" °C");
}

void TGS2600Read()
{
    Serial.print("TGS2600: ");
    Serial.println(analogRead(A0));
}

void TGS2602Read()
{
    Serial.print("TGS2602: ");
    Serial.println(analogRead(A1));
}

void TGS2603Read()
{
    Serial.print("TGS2603: ");
    Serial.println(analogRead(A2));
}

void MQ2Read()
{
    Serial.print("MQ2:     ");
    Serial.println(analogRead(A3));
}

// -------------------- BME688 Callbacks and Helpers --------------------

volatile bool bmeDataReady = false;

void newDataCallback(bme68xData data, bsecOutputs outputs, Bsec2 bsec)
{
    if (!outputs.nOutputs)
        return;

    Serial.println("\n==== BME688 BSEC2 Sensor Data ====");

    for (uint8_t i = 0; i < outputs.nOutputs; i++)
    {
        const bsecData output = outputs.output[i];
        switch (output.sensor_id)
        {
        case BSEC_OUTPUT_RAW_TEMPERATURE:
            Serial.print("Raw Temperature:            ");
            Serial.print(output.signal, 2);
            Serial.println(" °C");
            break;
        case BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_TEMPERATURE:
            Serial.print("Compensated Temperature:    ");
            Serial.print(output.signal, 2);
            Serial.println(" °C");
            break;
        case BSEC_OUTPUT_RAW_HUMIDITY:
            Serial.print("Raw Humidity:               ");
            Serial.print(output.signal, 2);
            Serial.println(" %");
            break;
        case BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_HUMIDITY:
            Serial.print("Compensated Humidity:       ");
            Serial.print(output.signal, 2);
            Serial.println(" %");
            break;
        case BSEC_OUTPUT_RAW_PRESSURE:
            Serial.print("Pressure:                   ");
            Serial.print(output.signal / 100.0, 2);
            Serial.println(" hPa");
            break;
        case BSEC_OUTPUT_RAW_GAS:
            Serial.print("Raw Gas Resistance:         ");
            Serial.print(output.signal / 1000.0, 2);
            Serial.println(" kΩ");
            break;
        case BSEC_OUTPUT_COMPENSATED_GAS:
            Serial.print("Compensated Gas Resistance: ");
            Serial.print(output.signal / 1000.0, 2);
            Serial.println(" kΩ");
            break;
        case BSEC_OUTPUT_IAQ:
            Serial.print("IAQ Index:                  ");
            Serial.print(output.signal, 2);
            Serial.print(" (Accuracy: ");
            Serial.print(output.accuracy);
            Serial.println(")");
            break;
        case BSEC_OUTPUT_STATIC_IAQ:
            Serial.print("Static IAQ:                 ");
            Serial.println(output.signal, 2);
            break;
        case BSEC_OUTPUT_CO2_EQUIVALENT:
            Serial.print("CO₂ Equivalent:             ");
            Serial.print(output.signal, 2);
            Serial.println(" ppm");
            break;
        case BSEC_OUTPUT_BREATH_VOC_EQUIVALENT:
            Serial.print("bVOC Equivalent:            ");
            Serial.print(output.signal, 2);
            Serial.println(" ppm");
            break;
        case BSEC_OUTPUT_GAS_PERCENTAGE:
            Serial.print("Gas Percentage:             ");
            Serial.print(output.signal, 2);
            Serial.println(" %");
            break;
        case BSEC_OUTPUT_RUN_IN_STATUS:
            Serial.print("Run-In Status: ");
            Serial.println(output.signal > 0 ? "Complete" : "In Progress");
            break;
        case BSEC_OUTPUT_STABILIZATION_STATUS:
            Serial.print("Stabilization Status: ");
            Serial.println(output.signal > 0 ? "Stable" : "Stabilizing");
            break;
        default:
            break;
        }
    }

    // Signal that it's time to read all other sensors in sync
    bmeDataReady = true;
}

void checkBsecStatus(Bsec2 &bsec)
{
    if (bsec.status < BSEC_OK)
    {
        Serial.println("BSEC error code : " + String(bsec.status));
        errLeds();
    }
    else if (bsec.status > BSEC_OK)
    {
        Serial.println("BSEC warning code : " + String(bsec.status));
    }

    if (bsec.sensor.status < BME68X_OK)
    {
        Serial.println("BME68X error code : " + String(bsec.sensor.status));
        errLeds();
    }
    else if (bsec.sensor.status > BME68X_OK)
    {
        Serial.println("BME68X warning code : " + String(bsec.sensor.status));
    }
}

void errLeds(void)
{
    while (1)
    {
        digitalWrite(PANIC_LED, HIGH);
        delay(ERROR_DUR);
        digitalWrite(PANIC_LED, LOW);
        delay(ERROR_DUR);
    }
}

// -------------------- Arduino Setup and Loop --------------------

void setup()
{
    Serial.begin(115200);
    delay(100);
    Wire.begin();

    delay(500);
    MultichannelGasSensorSetup();

    delay(500);
    SGP30Setup();

    delay(500);
    BME688Setup();

    delay(500);
    FormaldehydeSetup();

    Serial.println("All sensors initiated successfully!");
    Serial.println("Starting to read data...");
}

void loop()
{
    // Run BME688; when ready, callback sets bmeDataReady
    envSensor.run();

    if (bmeDataReady)
    {
        bmeDataReady = false;

        Serial.println("New Data (synchronized)");

        // Analog sensors
        TGS2600Read();
        TGS2602Read();
        TGS2603Read();
        MQ2Read();

        // I2C sensors
        MultichannelGasSensorRead();
        SGP30Read();
        FormaldehydeRead(sensor);

        Serial.println();
        Serial.println();
    }
}
