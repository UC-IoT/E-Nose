#include <Arduino.h>
#include <Wire.h>

// Sensors' libraries
#include "seeed_bme680.h"
#include <SensirionI2CSgp41.h>

// Protocol
#define IIC_ADDR uint8_t(0x76)
Seeed_BME680 bme680(IIC_ADDR);
SensirionI2CSgp41 sgp41;

void BME680Setup()
{
  Serial.println("Initiating BME680...");
  while (!bme680.init())
  {
    Serial.println("BME680 init failed! Can't find device!");
    delay(10000);
  }
  Serial.println("BME680 init success!");
}

void SGP41Setup()
{
  Serial.println("Initiating SGP41...");
  while (!Serial)
    delay(100);

  Wire.begin();
  sgp41.begin(Wire);

  char errorMessage[256];
  uint16_t error;

  // Print serial number
  uint16_t serialNumber[3];
  error = sgp41.getSerialNumber(serialNumber);
  if (error)
  {
    errorToString(error, errorMessage, 256);
    Serial.print("Serial number error: ");
    Serial.println(errorMessage);
  }
  else
  {
    Serial.print("Sensor Serial Number: 0x");
    for (size_t i = 0; i < 3; i++)
    {
      Serial.printf("%04X", serialNumber[i]);
    }
    Serial.println();
  }

  // Run self-test
  uint16_t testResult;
  error = sgp41.executeSelfTest(testResult);
  if (error || testResult != 0xD400)
  {
    errorToString(error, errorMessage, 256);
    Serial.print("Self-test failed: ");
    Serial.println(errorMessage);
    while (true)
      delay(1000); // Halt execution
  }
  Serial.println("SGP41 self-test passed.");

  // Initialize VOC and NOx index algorithms
  GasIndexAlgorithm_init(&vocParams, GasIndexAlgorithm_ALGORITHM_TYPE_VOC);
  GasIndexAlgorithm_init(&noxParams, GasIndexAlgorithm_ALGORITHM_TYPE_NOX);
  Serial.println("Gas index algorithms initialized.");
}

void TGS2610Read()
{
  float sensor_volt;
  float sensorValue;

  sensorValue = analogRead(A0);
  sensor_volt = sensorValue / 1024 * 5.0;

  Serial.print("TGS2610: ");
  Serial.print(sensor_volt);
  Serial.println(" V");
}

void TGS2611Read()
{
  float sensor_volt;
  float sensorValue;

  sensorValue = analogRead(A1);
  sensor_volt = sensorValue / 1024 * 5.0;

  Serial.print("TGS2611: ");
  Serial.print(sensor_volt);
  Serial.println("V");
}

void TGS2612Read()
{
  float sensor_volt;
  float sensorValue;

  sensorValue = analogRead(A2);
  sensor_volt = sensorValue / 1024 * 5.0;

  Serial.print("TGS2612 = ");
  Serial.print(sensor_volt);
  Serial.println("V");
}

void MQ9_bRead()
{

  float sensor_volt;
  float sensorValue;

  sensorValue = analogRead(A1);
  sensor_volt = sensorValue / 1024 * 5.0;

  Serial.print("MQ9_b: ");
  Serial.print(sensor_volt);
  Serial.println(" V");
}

void BME680Read()
{
  if (bme680.read_sensor_data())
  {
    Serial.println("Failed to perform reading :(");
    return;
  }
  Serial.println("Reading BME680...");
  Serial.print("temperature: ");
  Serial.print(bme680.sensor_result_value.temperature);
  Serial.print(" °C : ");
  float voltage = map(bme680.sensor_result_value.temperature, -40, 85, 0, 3300) / 1000.0;
  Serial.print(voltage);
  Serial.println(" V");

  Serial.print("pressure: ");
  Serial.print(bme680.sensor_result_value.pressure / 1000.0);
  Serial.print(" KPa : ");
  voltage = map(bme680.sensor_result_value.pressure, 30000, 110000, 0, 3300) / 1000.0;
  Serial.print(voltage);
  Serial.println(" V");

  Serial.print("humidity: ");
  Serial.print(bme680.sensor_result_value.humidity);
  Serial.print(" % :");
  voltage = map(bme680.sensor_result_value.humidity, 0, 100, 0, 3300) / 1000.0;
  Serial.print(voltage);
  Serial.println(" V");

  Serial.print("gas: ");
  Serial.print(bme680.sensor_result_value.gas / 1000.0);
  Serial.print(" Kohms : ");
  voltage = 0;
  Serial.print(voltage);
  Serial.println(" V");
}

void SGP41Read()
{
  Serial.println("Reading SGP41...");
  uint16_t error;
  char errorMessage[256];

  // Default RH and T (50% RH, 25°C) in fixed-point format
  uint16_t defaultRh = 0x8000;
  uint16_t defaultT = 0x6666;

  uint16_t srawVoc = 0, srawNox = 0;
  int32_t vocIndex = 0, noxIndex = 0;

  if (conditioning_s > 0)
  {
    Serial.print("Conditioning NOx... seconds left: ");
    Serial.println(conditioning_s);

    error = sgp41.executeConditioning(defaultRh, defaultT, srawVoc);
    srawNox = 0;
    conditioning_s--;
  }
  else
  {
    error = sgp41.measureRawSignals(defaultRh, defaultT, srawVoc, srawNox);
  }

  if (error)
  {
    errorToString(error, errorMessage, 256);
    Serial.print("Measurement error: ");
    Serial.println(errorMessage);
  }
  else
  {
    // Always process VOC and NOx
    GasIndexAlgorithm_process(&vocParams, srawVoc, &vocIndex);
    GasIndexAlgorithm_process(&noxParams, srawNox, &noxIndex);

    // Output
    Serial.print("VOC Raw: ");
    Serial.print(srawVoc);
    Serial.print(" | NOx Raw: ");
    Serial.print(srawNox);
    Serial.print(" ==>> VOC Index: ");
    Serial.print(vocIndex);
    Serial.print(" | NOx Index: ");
    Serial.println(noxIndex);
  }
}

void setup()
{
  // put your setup code here, to run once:
  Serial.begin(9600);

  // Initiate MutichannelGasSensor
  delay(1000);
  BME680Setup();

  // Initiate SGP30
  delay(1000);
  SGP41Setup();

  Serial.println("All sensors initiated successfully!");
  Serial.println("Starting to read data...");
  delay(1000);
}

void loop()
{
  Serial.println("New Data");
  TGS2610Read();
  TGS2611Read();
  TGS2612Read();
  MQ9_bRead();
  BME680Read();
  SGP41Read();
  Serial.println();
  Serial.println();
  delay(1000);
}
