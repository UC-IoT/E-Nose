#include <Arduino.h>
#include <Wire.h>

// Sensors' libraries
#include <SensirionI2CSgp41.h>
#include "bme68xLibrary.h"

// Protocol
SensirionI2CSgp41 sgp41;

#define NEW_GAS_MEAS (BME68X_GASM_VALID_MSK | BME68X_HEAT_STAB_MSK | BME68X_NEW_DATA_MSK)
#define MEAS_DUR 140

#ifndef PIN_CS
#define PIN_CS SS
#endif
Bme68x bme;

void BME680Setup()
{
  Serial.println("Initiating BME680...");
  SPI.begin();
  while (!Serial)
		delay(10);

	/* initializes the sensor based on SPI library */
	bme.begin(PIN_CS, SPI);

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
	uint16_t sharedHeatrDur = MEAS_DUR - (bme.getMeasDur(BME68X_PARALLEL_MODE) / 1000);

	bme.setHeaterProf(tempProf, mulProf, sharedHeatrDur, 10);
	bme.setOpMode(BME68X_PARALLEL_MODE);

	Serial.println("TimeStamp(ms), Temperature(deg C), Pressure(Pa), Humidity(%), Gas resistance(ohm), Status, Gas index");

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
  float sensorValue;

  sensorValue = analogRead(A0);
  Serial.print("TGS2610: ");
  Serial.print(sensorValue);

}

void TGS2611Read()
{
  float sensorValue;

  sensorValue = analogRead(A1);

  Serial.print("TGS2611: ");
  Serial.print(sensorValue);
}

void TGS2612Read()
{
  float sensorValue;

  sensorValue = analogRead(A2);

  Serial.print("TGS2612: ");
  Serial.print(sensorValue);
}

void MQ9_bRead()
{
  float sensorValue;

  sensorValue = analogRead(A1);

  Serial.print("MQ9_b: ");
  Serial.print(sensorValue);
}

void BME680Read()
{
  bme68xData data;
	uint8_t nFieldsLeft = 0;

	/* data being fetched for every 140ms */
	delay(MEAS_DUR);

	if (bme.fetchData())
	{
		do
		{
			nFieldsLeft = bme.getData(data);
			if (data.status == NEW_GAS_MEAS)
			{
				Serial.print(String(millis()) + ", ");
				Serial.print(String(data.temperature) + ", ");
				Serial.print(String(data.pressure) + ", ");
				Serial.print(String(data.humidity) + ", ");
				Serial.print(String(data.gas_resistance) + ", ");
				Serial.print(String(data.status, HEX) + ", ");
				Serial.println(data.gas_index);
			}
		} while (nFieldsLeft);
	}
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
