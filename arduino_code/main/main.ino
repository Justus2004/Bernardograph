#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"
#include <ArduinoBLE.h>
#include "config.h"

ArduinoLEDMatrix matrix;

bool measuring = false;
unsigned long targetSeconds = 0;
unsigned long elapsedMilliseconds = 0;

void initTimer();
void initBluetooth();
void sendStreamData(uint8_t* data, size_t length);
void sendCommand(String cmd);
void sendLog(String level, String msg); 

void setup() {
  Serial.begin(115200);
  analogReadResolution(14); 
  matrix.begin(); 

  pinMode(buttonPin, INPUT_PULLUP);
  for (int i = 0; i < 8; i++) {
    pinMode(shiftPins[i], INPUT);
  }

  initBluetooth();
  initTimer(); 
}

unsigned long readShiftRegister() {
  unsigned long val = 0;
  for (int i = 0; i < 8; i++) {
    if (digitalRead(shiftPins[i]) == HIGH) {
      val |= (1 << i);
    }
  }
  return (val == 0) ? 10 : val;
}

void loop() {
  BLE.poll(); 

  if (!measuring) {
    matrix.beginDraw();
    matrix.background(0, 0, 0);
    matrix.stroke(0xFFFFFFFF);
    matrix.point(6, 4); 
    matrix.endDraw();

    if (digitalRead(buttonPin) == LOW) {
      delay(50);
      if (digitalRead(buttonPin) == LOW) {
        targetSeconds = readShiftRegister();
        
        sendLog("INFO", "Messphase gestartet (" + String(targetSeconds) + "s)");
        sendCommand("START:" + String(targetSeconds));

        bufferIndex = 0;
        activeBuffer = 0;
        bufferReady[0] = false;
        bufferReady[1] = false;
        errorBufferOverrun = false; 
        elapsedMilliseconds = 0;

        measuring = true; 
        delay(500); 
      }
    }
    return;
  }

  if (errorBufferOverrun) {
    sendLog("ERR", "Buffer Overrun! Bluetooth zu langsam, Daten gingen verloren.");
    errorBufferOverrun = false; 
  }

  for (int i = 0; i < 2; i++) {
    if (bufferReady[i]) {
      sendStreamData((uint8_t*)buffers[i], CHUNK_SIZE * sizeof(uint16_t));
      bufferReady[i] = false;
      elapsedMilliseconds += (CHUNK_SIZE * 1000UL) / SAMPLE_RATE; 
    }
  }

  if (elapsedMilliseconds >= (targetSeconds * 1000UL)) {
    measuring = false;
    sendCommand("END");
    sendLog("INFO", "Messphase erfolgreich beendet.");
    
    matrix.beginDraw();
    matrix.background(0, 0, 0);
    matrix.stroke(0xFFFFFFFF);
    matrix.rect(2, 2, 8, 4);
    matrix.endDraw();
    delay(2000);
  }

  if (neuerWertBereit) {
    uint16_t adcDurchschnitt = aktuellerDurchschnitt;
    neuerWertBereit = false; 

    float spannung = adcDurchschnitt * (VCC_REF / ADC_MAX);
    float mbar = SENSOR_MAX_MBAR - ((spannung / SENSOR_MAX_VOLTS) * SENSOR_MAX_MBAR);
    
    // Limits für das Display
    if (mbar < 0) mbar = 0;
    if (mbar > SENSOR_MAX_MBAR) mbar = SENSOR_MAX_MBAR;

    int displayValue = (int)mbar;
    matrix.beginDraw();
    matrix.background(0, 0, 0); 
    matrix.stroke(0xFFFFFFFF); 

    if (displayValue >= SENSOR_MAX_MBAR) {
      matrix.rect(0, 0, 12, 8);
      matrix.point(5, 2);
    } else {
      matrix.textFont(Font_5x7);
      matrix.beginText(1, 1, 0xFFFFFF); 
      if (displayValue < 10) matrix.print(" ");
      matrix.print(displayValue);
      matrix.endText(NO_SCROLL); 
    }
    matrix.endDraw();
  }
}