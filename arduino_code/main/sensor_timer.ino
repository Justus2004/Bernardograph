#include "FspTimer.h"
#include "config.h"

FspTimer messTimer;

volatile uint16_t buffers[2][CHUNK_SIZE];
volatile uint8_t activeBuffer = 0;
volatile int bufferIndex = 0;
volatile bool bufferReady[2] = {false, false};

volatile uint32_t messungsSumme = 0;   
volatile int messungsZaehler = 0;      
volatile uint16_t aktuellerDurchschnitt = 0;
volatile bool neuerWertBereit = false; 
volatile bool errorBufferOverrun = false; 

extern bool measuring;

void timerInterrupt(timer_callback_args_t *p_args) {
  if (!measuring) return;

  uint16_t messwert = analogRead(sensorPin); 
  
  messungsSumme += messwert; 
  messungsZaehler++;
  
  if (messungsZaehler >= SAMPLE_RATE) {
    aktuellerDurchschnitt = messungsSumme / SAMPLE_RATE; 
    messungsSumme = 0;
    messungsZaehler = 0;
    neuerWertBereit = true; 
  }

  buffers[activeBuffer][bufferIndex] = messwert;
  bufferIndex++;
  
  if (bufferIndex >= CHUNK_SIZE) {
    if (bufferReady[1 - activeBuffer]) {
      errorBufferOverrun = true; // PC kommt mit dem Auslesen nicht hinterher
    }
    
    bufferReady[activeBuffer] = true; 
    activeBuffer = 1 - activeBuffer;  
    bufferIndex = 0;                  
  }
}

void initTimer() {
  uint8_t timerType = GPT_TIMER; 
  int8_t channel = FspTimer::get_available_timer(timerType);
  if (channel < 0) {
    timerType = AGT_TIMER;
    channel = FspTimer::get_available_timer(timerType);
  }
  messTimer.begin(TIMER_MODE_PERIODIC, timerType, channel, (float)SAMPLE_RATE, 50.0f, timerInterrupt);
  messTimer.setup_overflow_irq();
  messTimer.open();
  messTimer.start();
}