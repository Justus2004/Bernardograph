#include <ArduinoBLE.h>

BLEService druckService("181A"); 
BLECharacteristic streamChar("2A6D", BLERead | BLENotify, 200); 
BLEStringCharacteristic cmdChar("2A6E", BLERead | BLENotify, 20);

void initBluetooth() {
  if (!BLE.begin()) {
    Serial.println("ERR: Bluetooth Start fehlgeschlagen!");
    while (1);
  }
  BLE.setLocalName("Drucksensor"); 
  BLE.setAdvertisedService(druckService);
  druckService.addCharacteristic(streamChar);
  druckService.addCharacteristic(cmdChar);
  BLE.addService(druckService);
  BLE.advertise();
  
  Serial.println("INFO: Bluetooth bereit.");
}

void sendStreamData(uint8_t* data, size_t length) {
  streamChar.writeValue(data, length);
}

void sendCommand(String cmd) {
  cmdChar.writeValue(cmd);
}

// Funktion für sauberes Logging an den PC
void sendLog(String level, String msg) {
  String logString = level + ":" + msg;
  cmdChar.writeValue(logString); 
  Serial.println(logString);     
}