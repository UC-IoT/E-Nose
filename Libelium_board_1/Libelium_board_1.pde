

#include <WaspSensorGas_Pro.h>

/*
 * Define object for sensor: gas_PRO_sensor
 * Input to choose board socket. 
 * Waspmote OEM. Possibilities for this sensor:
 *   - SOCKET_1 
 * P&S! Possibilities for this sensor:
 *  - SOCKET_A
 *  - SOCKET_B
 *  - SOCKET_C
 *  - SOCKET_F
 */

WaspSensorGas_Pro_h Lib;

Gas NO(SOCKET_3);
Gas CO(SOCKET_5);
Gas NO2(SOCKET_4);
Gas NH3(SOCKET_1);
Gas O2(SOCKET_4);


float concentration_NO;  // Stores the concentration level in ppm
float concentration_CO;  // Stores the concentration level in ppm
float concentration_NO2;  // Stores the concentration level in ppm
float concentration_NH3;  // Stores the concentration level in ppm
float concentration_O2;  // Stores the concentration level in ppm

float temperature;  // Stores the temperature in ºC
float humidity;   // Stores the realitve humidity in %RH
float pressure;   // Stores the pressure in Pa

void setup()
{
    USB.println(F("Libelium Gas Sensors. 2 min sleep to heat sensors"));
    PWR.deepSleep("00:00:02:00", RTC_OFFSET, RTC_ALM1_MODE1, ALL_ON);
    Lib.setBaudrate(9600);

    NO.ON();
    CO.ON();
    NH3.ON();
    NO2.ON();
    O2.ON();
} 


void loop()
{      
    concentration_NO = NO.getConc();

    USB.println(F("***************************************"));

    USB.print(F("NO: "));
    USB.print(concentration_NO);
    USB.println(F(" ppm"));
  
    concentration_CO = CO.getConc();

    USB.print(F("CO: "));
    USB.print(concentration_CO);
    USB.println(F(" ppm"));
   
    concentration_NO2 = NO2.getConc();

    USB.print(F("NO2: "));
    USB.print(concentration_NO2);
    USB.println(F(" ppm"));
 
    concentration_NH3 = NH3.getConc();

    USB.print(F("NH3: "));
    USB.print(concentration_NH3);
    USB.println(F(" ppm"));

    concentration_O2 = O2.getConc();

    USB.print(F("O2: "));
    USB.print(concentration_O2);
    USB.println(F(" ppm"));
    
    // Read enviromental variables
    temperature = O2.getTemp();
   
    //USB.print(F("Temperature: "));
    //USB.print(temperature);
    //USB.println(F(" Celsius degrees"));
  
}

