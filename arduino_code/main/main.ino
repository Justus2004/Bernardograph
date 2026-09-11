#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"
#include <ArduinoBLE.h>
#include "config.h"

ArduinoLEDMatrix matrix;

bool measuring = false;
bool continuousMode = false;
bool waitForButtonRelease = false;

unsigned long targetSeconds = 0;
unsigned long elapsedMilliseconds = 0;
float currentMbar = 0.0; 

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
  return val; 
}

void loop() {
  BLE.poll(); 

  // 1. Live-Druck berechnen (läuft immer)
  if (neuerWertBereit) {
    uint16_t adcDurchschnitt = aktuellerDurchschnitt;
    neuerWertBereit = false; 

    float spannung = adcDurchschnitt * (VCC_REF / ADC_MAX);
    currentMbar = SENSOR_MAX_MBAR - ((spannung / SENSOR_MAX_VOLTS) * SENSOR_MAX_MBAR);
    if (currentMbar < 0) currentMbar = 0;
  }

  // 2. Taster-Entprellung
  if (waitForButtonRelease && digitalRead(buttonPin) == HIGH) {
    delay(50);
    waitForButtonRelease = false;
  }

  // 3. Taster-Logik (Start & Stopp für ALLE Modi)
  if (!waitForButtonRelease && digitalRead(buttonPin) == LOW) {
    delay(50);
    if (digitalRead(buttonPin) == LOW) {
      
      if (!measuring) {
        // --- MESSUNG STARTEN ---
        targetSeconds = readShiftRegister();
        
        if (targetSeconds == 0) {
          continuousMode = true;
          sendLog("INFO", "Dauermessung gestartet (Beenden mit Taster)");
          sendCommand("START:0");
        } else {
          continuousMode = false;
          sendLog("INFO", "Zeit-Messung gestartet (" + String(targetSeconds) + "s)");
          sendCommand("START:" + String(targetSeconds));
        }

        bufferIndex = 0;
        activeBuffer = 0;
        bufferReady[0] = false;
        bufferReady[1] = false;
        errorBufferOverrun = false; 
        elapsedMilliseconds = 0;
        measuring = true; 
      } 
      else {
        // --- MESSUNG MANUELL ABBRECHEN ---
        measuring = false;
        sendCommand("END");
        if (continuousMode) {
          sendLog("INFO", "Dauermessung manuell beendet.");
        } else {
          sendLog("WARN", "Zeit-Messung vorzeitig durch Taster abgebrochen!");
        }
      }
      
      waitForButtonRelease = true; // Blockiert Mehrfach-Klicks
    }
  }

  // 4. Bluetooth Daten senden (nur wenn Messung aktiv)
  if (measuring) {
    if (errorBufferOverrun) {
      sendLog("ERR", "Buffer Overrun! Bluetooth zu langsam.");
      errorBufferOverrun = false; 
    }

    for (int i = 0; i < 2; i++) {
      if (bufferReady[i]) {
        sendStreamData((uint8_t*)buffers[i], CHUNK_SIZE * sizeof(uint16_t));
        bufferReady[i] = false;
        elapsedMilliseconds += (CHUNK_SIZE * 1000UL) / SAMPLE_RATE; 
      }
    }

    // Auto-Stopp für Zeit-Messungen
    if (!continuousMode && elapsedMilliseconds >= (targetSeconds * 1000UL)) {
      measuring = false;
      sendCommand("END");
      sendLog("INFO", "Messphase erfolgreich beendet.");
    }
  }

  // 5. Display-Update aufrufen
  updateDisplay();
}


// --- DISPLAY LOGIK ---
void updateDisplay() {
  static unsigned long lastDraw = 0;
  if (millis() - lastDraw < 50) return;
  lastDraw = millis();

  static bool blinkState = false;
  static unsigned long lastBlink = 0;
  if (millis() - lastBlink > 500) {
    blinkState = !blinkState;
    lastBlink = millis();
  }

  matrix.beginDraw();
  matrix.background(0, 0, 0);

  // --- 1. RAHMEN ZEICHNEN (Blinkend bei aktiver Messung) ---
  if (measuring && blinkState) {
    matrix.stroke(0xFFFFFFFF);
    matrix.line(0, 0, 11, 0);  // Oben
    matrix.line(11, 0, 11, 7); // Rechts
    matrix.line(11, 7, 0, 7);  // Unten
    matrix.line(0, 7, 0, 0);   // Links
  }

  matrix.stroke(0xFFFFFFFF);

  if (!measuring || continuousMode) {
    // MODUS: IDLE oder DAUERMESSUNG (Zeigt den Druck)
    if (currentMbar > 99.0) {
      // Grosses X
      matrix.line(0, 0, 11, 7);
      matrix.line(11, 0, 0, 7);
    } else {
      matrix.textFont(Font_4x6); // Kleinerer Font, damit er in den Rahmen passt
      // Wenn der Rahmen gezeichnet wird, Text leicht verschieben, damit er nicht überlappt
      int xOffset = measuring ? 2 : 1; 
      int yOffset = measuring ? 1 : 1;
      
      matrix.beginText(xOffset, yOffset, 0xFFFFFF);
      int val = (int)currentMbar;
      if (val < 10) matrix.print(" ");
      matrix.print(val);
      matrix.endText(NO_SCROLL);
    }
    
  } 
  else {
    // MODUS: ZEITMESSUNG (Zeigt den Countdown)
    long remaining = targetSeconds - (elapsedMilliseconds / 1000);
    if (remaining < 0) remaining = 0;

    matrix.textFont(Font_4x6); // Kleinerer Font
    int xOffset = measuring ? 2 : 1;
    int yOffset = measuring ? 1 : 1;

    matrix.beginText(xOffset, yOffset, 0xFFFFFF);
    
    if (remaining > 99) {
      matrix.print("99"); 
    } else {
      if (remaining < 10) matrix.print(" ");
      matrix.print(remaining);
    }
    
    matrix.endText(NO_SCROLL);
  }

  matrix.endDraw();
}