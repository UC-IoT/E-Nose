#include <Arduino.h>
#include <Wire.h>

// Sensors' libraries
#include <Multichannel_Gas_GMXXX.h>
#include "sgp30.h"
#include "sensirion_common.h"
#include <SensirionI2cSfa3x.h>
#include "bme68xLibrary.h"


// Define
#define IIC_ADDR  uint8_t(0x76) // BME688 I2C address
#define NEW_GAS_MEAS (BME68X_GASM_VALID_MSK | BME68X_HEAT_STAB_MSK | BME68X_NEW_DATA_MSK)
#define BME68X_I2C_ADDR  0x76

#ifndef PIN_CS
#define PIN_CS SS
#endif
Bme68x bme;

// Protocol
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

void BME688Setup()
{
  Serial.println("Initiating BME688...");
  Wire.begin();
  while (!Serial)
		delay(10);

	/* initializes the sensor based on I2C library */
	bme.begin(BME68X_I2C_ADDR, Wire);

	if(bme.checkStatus())
	{
		if (bme.checkStatus() == BME68X_ERROR)
		{
			Serial.println("Sensor error:" + bme.statusString());
			return;
		}
		else if (bme.checkStatus() == BME68X_WARNING)
		{
			Serial.println("Sensor Warning:" + bme.statusString());
		}
	}
	
	/* Set the default configuration for temperature, pressure and humidity */
	bme.setTPH();

	/* Heater temperature in degree Celsius */
	uint16_t tempProf[10] = { 320, 100, 100, 100, 200, 200, 200, 320, 320,
			320 };
	/* Multiplier to the shared heater duration */
	uint16_t mulProf[10] = { 5, 2, 10, 30, 5, 5, 5, 5, 5, 5 };
	/* Shared heating duration in milliseconds */
	uint16_t sharedHeatrDur = 140 - (bme.getMeasDur(BME68X_PARALLEL_MODE) / 1000);

	bme.setHeaterProf(tempProf, mulProf, sharedHeatrDur, 10);
	bme.setOpMode(BME68X_PARALLEL_MODE);

	//Serial.println("TimeStamp(ms), Temperature(deg C), Pressure(Pa), Humidity(%), Gas resistance(ohm), Status, Gas index");

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


// Sensors Readings
void MultichannelGasSensorRead(){
    uint8_t len = 0;
    uint8_t addr = 0;
    uint8_t i;
    uint32_t val = 0;
    Serial.println("Reading Multichannel Gas Sensor...");
    val = gas.getGM102B(); 
    Serial.print("GM102B (NO2): "); 
    Serial.print(val); 
    Serial.print(" ppm");
    Serial.println();
    val = gas.getGM302B(); 
    Serial.print("GM302B (C2H5CH): "); 
    Serial.print(val); 
    Serial.print(" ppm");
    Serial.println();
    val = gas.getGM502B(); 
    Serial.print("GM502B (VOC): "); 
    Serial.print(val); 
    Serial.print(" ppm");
    Serial.println();
    val = gas.getGM702B(); 
    Serial.print("GM702B (CO): "); 
    Serial.print(val); 
    Serial.print(" ppm");
    
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
        Serial.print(" ppb");
        Serial.println();

        Serial.print("CO2eq:");
        Serial.print(co2_eq_ppm);
        Serial.print("ppm"); 
        Serial.println();
    } else {
        Serial.println("error reading IAQ values\n");
    }
}

void BME688Read()
{
  Serial.println("Reading BME688...");
  bme68xData data;
	uint8_t nFieldsLeft = 0;

	if (bme.fetchData())
	{
			nFieldsLeft = bme.getData(data);
		
				//Serial.println(String(millis()) + " ms");
        Serial.print("Temperature: ");
				Serial.println(String(data.temperature) + " °C ");
        Serial.print("Pressure: ");
				Serial.println(String(data.pressure) + " Pa ");
        Serial.print("Humidity: ");
				Serial.println(String(data.humidity) + " % ");
        Serial.print("Gas Resistance: ");
				Serial.println(String(data.gas_resistance) + " ohm ");
				//Serial.println(String(data.status, HEX));
        Serial.print("Gas Index: ");
				Serial.println(data.gas_index);
			}

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
    Serial.print(hcho);
    Serial.print(" ppb");
    Serial.println();

    Serial.print("humidity: ");
    Serial.print(humidity);
    Serial.print(" %");
    Serial.println();

    Serial.print("temperature: ");
    Serial.print(temperature);
    Serial.print(" °C");
    Serial.println();
}

void TGS2600Read(){
  float sensorValue;

  sensorValue = analogRead(A0);
  Serial.print("TGS2600: ");
  Serial.println(sensorValue);
}

void TGS2602Read(){
  float sensorValue;

  sensorValue = analogRead(A1);
  Serial.print("TGS2602: ");
  Serial.println(sensorValue);
}

void TGS2603Read(){
    float sensorValue;
    sensorValue = analogRead(A2);

    Serial.print("TGS2603: ");
    Serial.println(sensorValue);
}

void MQ2Read(){
    float sensorValue;

    sensorValue = analogRead(A3);
    Serial.print("MQ2: ");
    Serial.println(sensorValue);
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
  Serial.println("New Data");
  // ANALOG 
  TGS2600Read();
  TGS2602Read();
  TGS2603Read();
  MQ2Read();

  // I2C
  MultichannelGasSensorRead();
  SGP30Read();
  BME688Read();
  FormaldehydeRead(sensor);

  Serial.println();
  Serial.println();
  delay(250);
}

