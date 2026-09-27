#pragma once

const int sensorPin = A0; 
const int buttonPin = 13;   // NEU: Taster auf Digital Pin 13
const int shiftPins[8] = {2, 3, 4, 5, 6, 7, 8, 9}; // NEU: Schalter Pins 2 bis 9

#define CHUNK_SIZE 100 

const float VCC_REF = 5.0;              
const float ADC_MAX = 16383.0;          
const float SENSOR_MAX_VOLTS = 4.717;    
const float SENSOR_MAX_MBAR = 100.0;    
const int SAMPLE_RATE = 1000;           

extern volatile uint16_t buffers[2][CHUNK_SIZE];
extern volatile uint8_t activeBuffer;   
extern volatile int bufferIndex;
extern volatile bool bufferReady[2];

extern volatile bool neuerWertBereit;
extern volatile uint16_t aktuellerDurchschnitt;
extern volatile bool errorBufferOverrun;