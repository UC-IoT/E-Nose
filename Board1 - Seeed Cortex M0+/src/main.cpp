#include <Arduino.h>
#include <Wire.h>

// Sensors' libraries
#include <Multichannel_Gas_GMXXX.h>
#include "sgp30.h"
#include "sensirion_common.h"
#include "seeed_bme680.h"
#include <SensirionI2cSfa3x.h>


// Define
#define IIC_ADDR  uint8_t(0x76) // BME688 I2C address

// Protocol
Seeed_BME680 bme688(IIC_ADDR); /* IIC PROTOCOL */
SensirionI2cSfa3x sensor;
GAS_GMXXX<TwoWire> gas;

// Sensors Setups
void MultichannelGasSensorSetup(){
  Serial.println("Initiating MutichannelGasSensor...");
  gas.begin(Wire, 0x08); // use the hardware I2C
}

void SGP30Setup(){
  Serial.println("Initiating SGP30...");
  s16 err;
  u16 scaled_ethanol_signal, scaled_h2_signal;
  while (sgp_probe() != STATUS_OK) {
        Serial.println("SGP failed");
        while (1);
    }
    /*Read H2 and Ethanol signal in the way of blocking*/
    err = sgp_measure_signals_blocking_read(&scaled_ethanol_signal,
                                            &scaled_h2_signal);
    if (err == STATUS_OK) {
        Serial.println("get ram signal!");
    } else {
        Serial.println("error reading signals");
    }
    err = sgp_iaq_init();
}

void BME688Setup(){
  Serial.println("Initiating BME688...");
  while (!bme688.init()) {
        Serial.println("BME688 init failed! Can't find device!");
        delay(10000);
    }
  Serial.println("BME688 init success!");
}

void FormaldehydeSetup(){
#ifdef NO_ERROR
#undef NO_ERROR
#endif
#define NO_ERROR 0



static char errorMessage[64];
static int16_t error;
  Serial.println("Initiating Formaldehyde...");
  while (!Serial) {
        delay(100);
    }
    Wire.begin();
    sensor.begin(Wire, SFA3X_I2C_ADDR_5D);

    error = sensor.deviceReset();
    if (error != NO_ERROR) {
        Serial.print("Error trying to execute deviceReset(): ");
        errorToString(error, errorMessage, sizeof errorMessage);
        Serial.println(errorMessage);
        return;
    }
    delay(1000);
    int8_t deviceMarking[32] = {0};
    error = sensor.getDeviceMarking(deviceMarking, 32);
    if (error != NO_ERROR) {
        Serial.print("Error trying to execute getDeviceMarking(): ");
        errorToString(error, errorMessage, sizeof errorMessage);
        Serial.println(errorMessage);
        return;
    }
    Serial.print("deviceMarking: ");
    Serial.print((const char*)deviceMarking);
    Serial.println();
    error = sensor.startContinuousMeasurement();
    if (error != NO_ERROR) {
        Serial.print("Error trying to execute startContinuousMeasurement(): ");
        errorToString(error, errorMessage, sizeof errorMessage);
        Serial.println(errorMessage);
        return;
    }
}



void MultichannelGasSensorRead(){
    uint8_t len = 0;
    uint8_t addr = 0;
    uint8_t i;
    uint32_t val = 0;
    Serial.println("Reading Multichannel Gas Sensor...");
    val = gas.getGM102B(); 
    Serial.println("GM102B (NO2): "); 
    Serial.print(val); 
    Serial.print(" ppm : ");
    Serial.print(gas.calcVol(val)); 
    Serial.print(" V");
    Serial.println();
    val = gas.getGM302B(); 
    Serial.println("GM302B (C2H5CH): "); 
    Serial.print(val); 
    Serial.print(" ppm : ");
    Serial.print(gas.calcVol(val)); 
    Serial.print(" V");
    Serial.println();
    val = gas.getGM502B(); 
    Serial.print("GM502B (VOC): "); 
    Serial.print(val); 
    Serial.print(" ppm : ");
    Serial.print(gas.calcVol(val)); 
    Serial.print("V");
    Serial.println();
    val = gas.getGM702B(); 
    Serial.print("GM702B (CO): "); 
    Serial.print(val); 
    Serial.print(" ppm : ");
    Serial.print(gas.calcVol(val)); 
    Serial.print("V");
    Serial.println();

}

void SGP30Read(){
    s16 err = 0;
    u16 tvoc_ppb, co2_eq_ppm;
    float voltage;
    Serial.println("Reading SGP30...");
    err = sgp_measure_iaq_blocking_read(&tvoc_ppb, &co2_eq_ppm);
    if (err == STATUS_OK) {
        Serial.print("tVOC: ");
        Serial.print(tvoc_ppb);
        Serial.print(" ppb : ");
        voltage = map(tvoc_ppb, 0, 60000, 0, 3300) / 1000.0;
        Serial.print(voltage);
        Serial.print(" V");
        Serial.println();

        Serial.print("CO2eq:");
        Serial.print(co2_eq_ppm);
        Serial.print("ppm : "); 
        voltage = map(co2_eq_ppm, 400, 60000, 0, 3300) / 1000.0;
        Serial.print(voltage);
        Serial.print(" V");
        Serial.println();
    } else {
        Serial.println("error reading IAQ values\n");
    }
}

void BME688Read(){
  if (bme688.read_sensor_data()) {
        Serial.println("Failed to perform reading :(");
        return;
    }
    Serial.println("Reading BME688...");
    Serial.print("temperature: ");
    Serial.print(bme688.sensor_result_value.temperature);
    Serial.print(" °C");
    Serial.print(" : ");
    float voltage = map(bme688.sensor_result_value.temperature, -40, 85, 0, 3300) / 1000.0;
    Serial.print(voltage);
    Serial.print(" V");
    Serial.println();

    Serial.print("pressure : ");
    Serial.print(bme688.sensor_result_value.pressure / 1000.0);
    Serial.print(" KPa");
    Serial.print(" : ");
    voltage = map(bme688.sensor_result_value.pressure, 30000, 110000, 0, 3300) / 1000.0;
    Serial.print(voltage);
    Serial.print(" V");
    Serial.println();

    Serial.print("humidity : ");
    Serial.print(bme688.sensor_result_value.humidity);
    Serial.print(" %");
    Serial.print(" : ");
    voltage = map(bme688.sensor_result_value.humidity, 0, 100, 0, 3300) / 1000.0;
    Serial.print(voltage);
    Serial.print("V");
    Serial.println();

    Serial.print("gas : ");
    Serial.print(bme688.sensor_result_value.gas / 1000.0);
    Serial.print(" Kohms");

    Serial.println();
}

void FormaldehydeRead(SensirionI2cSfa3x& sensor){
  static int16_t error;
  float hcho = 0.0;
    float humidity = 0.0;
    float temperature = 0.0;
    delay(500);
    error = sensor.readMeasuredValues(hcho, humidity, temperature);
    if (error != NO_ERROR) {
        Serial.print("Error trying to execute readMeasuredValues(): ");
        return;
    }
    Serial.println("Reading Formaldehyde...");
    Serial.print("hcho: ");
    Serial.print(hcho / 5.0);
    Serial.print(" ppb : ");
    float voltage = map(hcho, 0, 10000, 0, 3300) / 1000.0;
    Serial.print(voltage);
    Serial.print(" V");
    Serial.println();

    Serial.print("humidity: ");
    Serial.print(humidity / 100.0);
    Serial.print(" % : ");
    voltage = map(humidity, 0, 100, 0, 3300) / 1000.0;
    Serial.print(voltage);
    Serial.print(" V");
    Serial.println();

    Serial.print("temperature: ");
    Serial.print(temperature / 200.0);
    Serial.print(" °C : ");
    voltage = map(temperature, -20, 50, 0, 3300) / 1000.0;
    Serial.print(voltage);
    Serial.print(" V");
    Serial.println();
}

void TGS2600Read(){
  float sensor_volt;
    float sensorValue;

    sensorValue = analogRead(A0);
    sensor_volt = sensorValue/1024*5.0;

    Serial.print("TGS2600: ");
    Serial.print(sensor_volt);
    Serial.println(" V");
}

void TGS2602Read(){
  float sensor_volt;
    float sensorValue;

    sensorValue = analogRead(A1);
    sensor_volt = sensorValue/1024*5.0;

    Serial.print("TGS2602: ");
    Serial.print(sensor_volt);
    Serial.println(" V");
}

void TGS2603Read(){
  float sensor_volt;
    float sensorValue;

    sensorValue = analogRead(A2);
    sensor_volt = sensorValue/1024*5.0;

    Serial.print("TGS2603: ");
    Serial.print(sensor_volt);
    Serial.println(" V");
}

void MQ2Read(){
  float sensor_volt;
    float sensorValue;

    sensorValue = analogRead(A3);
    sensor_volt = sensorValue/1024*5.0;

    Serial.print("MQ2: ");
    Serial.print(sensor_volt);
    Serial.println("V");
}

void setup() {
  // put your setup code here, to run once:
  Serial.begin(9600);
  
  // Initiate MutichannelGasSensor
  delay(1000);
  gas.begin(Wire, 0x08); // use the hardware I2C

  // Initiate SGP30
  delay(1000);
  SGP30Setup();

  // Initiate BME688
  delay(1000);
  BME688Setup();

  // Initiate Formaldehyde
  delay(1000);
  FormaldehydeSetup();  

  Serial.println("All sensors initiated successfully!");
  Serial.println("Starting to read data...");
  delay(1000);

}

void loop() {
  // ANALOG 
  TGS2600Read();
  // delay(500);
  TGS2602Read();
  // delay(500);
  TGS2603Read();
  // delay(500);
  MQ2Read();
  // delay(500);

  // I2C
  MultichannelGasSensorRead();
  // delay(500);

  SGP30Read();
  // delay(500);

  BME688Read();
  // delay(500);

  FormaldehydeRead(sensor);

  delay(1000);
}

