#include <Arduino.h>
#include <Wire.h>

// Sensors' libraries
#include "seeed_bme680.h"
#include <SensirionI2CSgp41.h>

// Protocol
#define IIC_ADDR  uint8_t(0x76)
Seeed_BME680 bme680(IIC_ADDR);
SensirionI2CSgp41 sgp41;

void BME680Setup(){
  Serial.println("Initiating BME680...");
  while (!bme680.init()) {
        Serial.println("BME680 init failed! Can't find device!");
        delay(10000);
    }
  Serial.println("BME680 init success!");
}

void SGP41Setup(){
  Serial.println("Initiating SGP41...");
  while (!Serial) {
        delay(100);
    }

    Wire.begin();

    uint16_t error;
    char errorMessage[256];

    sgp41.begin(Wire);

    uint8_t serialNumberSize = 3;
    uint16_t serialNumber[serialNumberSize];

    error = sgp41.getSerialNumber(serialNumber);

    if (error) {
        Serial.print("Error trying to execute getSerialNumber(): ");
        errorToString(error, errorMessage, 256);
        Serial.println(errorMessage);
    } else {
        Serial.print("SerialNumber:");
        Serial.print("0x");
        for (size_t i = 0; i < serialNumberSize; i++) {
            uint16_t value = serialNumber[i];
            Serial.print(value < 4096 ? "0" : "");
            Serial.print(value < 256 ? "0" : "");
            Serial.print(value < 16 ? "0" : "");
            Serial.print(value, HEX);
        }
        Serial.println();
    }

    uint16_t testResult;
    error = sgp41.executeSelfTest(testResult);
    if (error) {
        Serial.print("Error trying to execute executeSelfTest(): ");
        errorToString(error, errorMessage, 256);
        Serial.println(errorMessage);
    } else if (testResult != 0xD400) {
        Serial.print("executeSelfTest failed with error: ");
        Serial.println(testResult);
    }
}


void TGS2610Read(){
  float sensor_volt;
    float sensorValue;

    sensorValue = analogRead(A0);
    sensor_volt = sensorValue/1024*5.0;

    Serial.print("TGS2610: ");
    Serial.print(sensor_volt);
    Serial.println(" V");
}

void TGS2611Read(){
  float sensor_volt;
    float sensorValue;

    sensorValue = analogRead(A1);
    sensor_volt = sensorValue/1024*5.0;

    Serial.print("TGS2611: ");
    Serial.print(sensor_volt);
    Serial.println("V");
}

void TGS2612Read(){
  float sensor_volt;
    float sensorValue;

    sensorValue = analogRead(A2);
    sensor_volt = sensorValue/1024*5.0;

    Serial.print("TGS2612 = ");
    Serial.print(sensor_volt);
    Serial.println("V");
}

void MQ9_bRead(){

  float sensor_volt;
    float sensorValue;

    sensorValue = analogRead(A1);
    sensor_volt = sensorValue/1024*5.0;

    Serial.print("MQ9_b: ");
    Serial.print(sensor_volt);
    Serial.println(" V");
}

void BME680Read(){
  if (bme680.read_sensor_data()) {
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

    Serial.println();
}

void SGP41Read(){
  Serial.println("Reading SGP41...");
  uint16_t conditioning_s = 10;

  uint16_t error;
    char errorMessage[256];
    uint16_t defaultRh = 0x8000;
    uint16_t defaultT = 0x6666;
    uint16_t srawVoc = 0;
    uint16_t srawNox = 0;

    delay(1000);

    if (conditioning_s > 0) {
        // During NOx conditioning (10s) SRAW NOx will remain 0
        error = sgp41.executeConditioning(defaultRh, defaultT, srawVoc);
        conditioning_s--;
    } else {
        // Read Measurement
        error = sgp41.measureRawSignals(defaultRh, defaultT, srawVoc, srawNox);
    }

    if (error) {
        Serial.print("Error trying to execute measureRawSignals(): ");
        errorToString(error, errorMessage, 256);
        Serial.println(errorMessage);
    } else {
        Serial.print("SRAW_VOC:");
        Serial.print(srawVoc);
        Serial.println();
        Serial.print("SRAW_NOx:");
        Serial.print(srawNox);
    }
}

void setup() {
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

void loop() {

  TGS2610Read();
  TGS2611Read();
  TGS2612Read();
  MQ9_bRead();
  BME680Read();
  SGP41Read();
  delay(1000);

}
