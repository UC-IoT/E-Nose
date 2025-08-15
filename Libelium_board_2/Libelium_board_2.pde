#include <WaspSensorGas_Pro.h>

Gas CH4(SOCKET_1);
Gas SO2(SOCKET_3);
Gas NO2(SOCKET_2);
Gas H2S(SOCKET_4);

float concentration_SO2;
float concentration_NO2;
float concentration_H2S;
float concentration_CH4;
float temperature;
float humidity;
float pressure;

void setup()
{
    USB.println(F("Libelium Gas Sensors. 2 min sleep to heat sensors"));
    PWR.deepSleep("00:00:00:05", RTC_OFFSET, RTC_ALM1_MODE1, ALL_ON);
    SO2.ON();
    NO2.ON();
    H2S.ON();
    CH4.ON();
}

void loop()
{   
    concentration_SO2 = SO2.getConc();
    USB.println(F("***************************************"));
    USB.print(F("SO2: "));
    USB.print(concentration_SO2);
    USB.println(F(" ppm"));
    

    concentration_NO2 = NO2.getConc();
    USB.print(F("NO2: "));
    USB.print(concentration_NO2);
    USB.println(F(" ppm"));

    
    concentration_H2S = H2S.getConc();
    USB.print(F("H2S: "));
    USB.print(concentration_H2S);
    USB.println(F(" ppm"));

    
    concentration_CH4 = CH4.getConc();

    // Print CH4 concentration
    USB.print(F("CH4: "));
    USB.print(concentration_CH4);
    USB.println(F(" ppm"));
    

    // Read environmental variables
    temperature = H2S.getTemp();
    humidity = H2S.getHumidity();
    pressure = H2S.getPressure();


    // Call showSensorInfo() to display information about the all the sensors
    //CH4.showSensorInfo();  // No need to assign the return value to info_CH4
    //SO2.showSensorInfo();  // No need to assign the return value to info_CH4
    //NO2.showSensorInfo();  // No need to assign the return value to info_CH4
    //H2S.showSensorInfo();  // No need to assign the return value to info_CH4


    //USB.print(F("Temperature: "));
    //USB.print(temperature);
    //USB.println(F(" Celsius degrees"));
    //USB.print(F("RH: "));
    //USB.print(humidity);
    //USB.println(F(" %"));
    //USB.print(F("Pressure: "));
    //USB.print(pressure);
    //USB.println(F(" Pa"));

    delay(250);
}

