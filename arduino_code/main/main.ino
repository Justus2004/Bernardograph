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
    pinMode(shiftPins[i], INPUT_PULLUP);
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

  // --- NEU: Heartbeat alle 2 Sekunden senden ---
  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat > 2000) {
    sendCommand("HB");
    lastHeartbeat = millis();
  }  

  // 1. Live-Druck berechnen (läuft immer)
  if (neuerWertBereit) {
    uint16_t adcDurchschnitt = aktuellerDurchschnitt;
    neuerWertBereit = false; 

    float spannung = adcDurchschnitt * (VCC_REF / ADC_MAX);
    currentMbar = SENSOR_MAX_MBAR - ((spannung / SENSOR_MAX_VOLTS) * SENSOR_MAX_MBAR);
    if (currentMbar < 0) currentMbar = 0;
    
    Serial.print("Gemessene Spannung: ");
    Serial.print(spannung, 4); // Die "4" bestimmt die Anzahl der Nachkommastellen
    Serial.println(" V");
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
  
  // --- FIX: Buffer explizit mit Schwarz überschreiben ---
  matrix.background(0, 0, 0);
  matrix.stroke(0);           // Stiftfarbe auf Schwarz setzen
  matrix.fill(0);             // Füllfarbe auf Schwarz setzen
  matrix.rect(0, 0, 12, 8);   // Komplettes Display schwarz übermalen
  // ------------------------------------------------------

  // --- 1. RAHMEN ZEICHNEN (Blinkend bei aktiver Messung) ---
  if (measuring && blinkState) {
    matrix.stroke(0xFFFFFFFF);
    matrix.line(0, 0, 11, 0);  // Oben
    matrix.line(11, 0, 11, 7); // Rechts
    matrix.line(0, 7, 11, 7);  // Unten 
    matrix.line(0, 0, 0, 7);   // Links 
  }

  matrix.stroke(0xFFFFFFFF); 
  
  // MODUS: IMMER DRUCK ANZEIGEN (Countdown entfernt)
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

  matrix.endDraw();
}