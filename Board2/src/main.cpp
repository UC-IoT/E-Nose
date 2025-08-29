#include <Arduino.h>
#include <Wire.h>
#include <SoftwareSerial.h>

// Sensors' libraries
#include <SensirionI2CSgp41.h>
#include "bme68xLibrary.h"
#include "SensirionGasIndexAlgorithm.h" // Add this line to include the algorithm header

SensirionI2CSgp41 sgp41;

#define NEW_GAS_MEAS (BME68X_GASM_VALID_MSK | BME68X_HEAT_STAB_MSK | BME68X_NEW_DATA_MSK)
#define BME68X_I2C_ADDR  0x76

// Define MEAS_DUR in milliseconds (adjust as needed for your application)
#define MEAS_DUR 100


Bme68x bme;

// Declare VOC and NOx algorithm parameter structures
GasIndexAlgorithmParams vocParams;
GasIndexAlgorithmParams noxParams;

// Declare and initialize conditioning_s for SGP41 conditioning phase
int conditioning_s = 10; // Set to desired number of seconds for conditioning

// Create SoftwareSerial on D2 (TX), D3 (RX)
SoftwareSerial co2Serial(2, 3);
 
const byte cmd_get_sensor[] = {
    0xFF, 0x01, 0x86,
    0x00, 0x00, 0x00,
    0x00, 0x00, 0x79
};
 
int readCO2();
bool sendCommandAndReadResponse(byte* response);

void BME680Setup()
{
  Serial.println("Initiating BME680...");
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
	uint16_t sharedHeatrDur = MEAS_DUR - (bme.getMeasDur(BME68X_PARALLEL_MODE) / 1000);

	bme.setHeaterProf(tempProf, mulProf, sharedHeatrDur, 10);
	bme.setOpMode(BME68X_PARALLEL_MODE);

	//Serial.println("TimeStamp(ms), Temperature(deg C), Pressure(Pa), Humidity(%), Gas resistance(ohm), Status, Gas index");

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

void CO2Setup()
{
  Serial.println("Initiating CO2 sensor...");
  co2Serial.begin(9600);
  Serial.println("CO2 sensor ready.");
}

void TGS2610Read()
{
  float sensorValue;

  sensorValue = analogRead(A0);
  Serial.print("TGS2610: ");
  Serial.println(sensorValue);

}

void TGS2611Read()
{
  float sensorValue;

  sensorValue = analogRead(A1);

  Serial.print("TGS2611: ");
  Serial.println(sensorValue);
}

void TGS2612Read()
{
  float sensorValue;

  sensorValue = analogRead(A2);

  Serial.print("TGS2612: ");
  Serial.println(sensorValue);
}

void MQ9_bRead()
{
  float sensorValue;

  sensorValue = analogRead(A3);

  Serial.print("MQ9_b: ");
  Serial.println(sensorValue);
}

void BME680Read()
{
  Serial.println("Reading BME680...");
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
    Serial.println(srawVoc);
    Serial.print("NOx Raw: ");
    Serial.println(srawNox);
    Serial.print("VOC Index: ");
    Serial.println(vocIndex);
    Serial.print("NOx Index: ");
    Serial.println(noxIndex);
  }
}

void CO2Read()
{
    Serial.println("Reading CO2...");
    int co2ppm = readCO2();
    if (co2ppm > 0) {
        Serial.print("CO2 Concentration: ");
        Serial.print(co2ppm);
        Serial.println(" ppm");
    } else {
        Serial.println("Sensor read failed.");
    }
}

int readCO2() {
    byte response[9];
    if (sendCommandAndReadResponse(response)) {
        // Check header
        if (response[0] != 0xFF || response[1] != 0x86)
            return -1;
 
        // Validate checksum
        byte checksum = 0xFF - (response[1] + response[2] + response[3] +
                                response[4] + response[5] + response[6] + response[7]) + 1;
        if (response[8] != checksum)
            return -2;
 
        // Extract CO2 value
        int ppm = response[2] * 256 + response[3];
        return ppm;
    }
    return -3;
}
 
bool sendCommandAndReadResponse(byte* response) {
    // Clear any stale data
    while (co2Serial.available()) co2Serial.read();
 
    // Send command
    for (byte b : cmd_get_sensor) {
        co2Serial.write(b);
    }
 
    // Wait for response (max 100ms)
    unsigned long start = millis();
    int i = 0;
    while (i < 9 && millis() - start < 300) {
        if (co2Serial.available()) {
            response[i++] = co2Serial.read();
        }
    }
    return i == 9;
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

  // Initiate CO2 sensor
  delay(1000);
  CO2Setup();

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
  CO2Read();
  Serial.println();
  Serial.println();
  delay(1000);
}
