#pragma once

const int sensorPin = A0; 
const int buttonPin = 2;   
const int shiftPins[8] = {3, 4, 5, 6, 7, 8, 9, 10};

#define CHUNK_SIZE 100 

// --- KONSTANTEN ---
const float VCC_REF = 5.0;              // Referenzspannung des ADC
const float ADC_MAX = 16383.0;          // Maximalwert für 14-Bit Auflösung
const float SENSOR_MAX_VOLTS = 4.78;    // Sensorspannung bei 0 mbar (bzw. Vollausschlag)
const float SENSOR_MAX_MBAR = 100.0;    // Maximaler Druck
const int SAMPLE_RATE = 1000;           // Messungen pro Sekunde

// --- GLOBALE VARIABLEN ---
extern volatile uint16_t buffers[2][CHUNK_SIZE];
extern volatile uint8_t activeBuffer;   
extern volatile int bufferIndex;
extern volatile bool bufferReady[2];

extern volatile bool neuerWertBereit;
extern volatile uint16_t aktuellerDurchschnitt;
extern volatile bool errorBufferOverrun;