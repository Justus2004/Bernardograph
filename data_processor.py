import csv
import os
from datetime import datetime, timedelta
import struct
from config import OUTPUT_DIR

class DataProcessor:
    def __init__(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self.file = None
        self.csv_writer = None
        self.expected_chunks = 0
        self.received_chunks = 0
        self.next_time = None
        self.current_filepath = None

    def start_session(self, seconds: int):
        self.expected_chunks = seconds * 10
        self.received_chunks = 0
        
        dateistempel = datetime.now().strftime("%Y%m%d_%H%M%S")
        dateiname = os.path.join(OUTPUT_DIR, f"messung_{dateistempel}_d{seconds}s.csv")
        self.current_filepath = dateiname
        
        self.file = open(dateiname, mode='w', newline='')
        self.csv_writer = csv.writer(self.file, delimiter=';')
        self.csv_writer.writerow(["Zeitstempel", "Druck_mbar", "ADC_Rohwert"])
        self.next_time = datetime.now()
        
        print(f"\n>>> Messung gestartet ({seconds} Sekunden). Datei: {dateiname}")

    def process_chunk(self, data: bytes) -> tuple:
        if not self.file or len(data) != 200:
            return 0, False

        raw_values = struct.unpack('<100H', data)
        rows_to_write = []
        sum_mbar = 0

        for raw_adc in raw_values:
            spannung = raw_adc * (5.0 / 16383.0)
            mbar = 100.0 - ((spannung / 4.78) * 100.0)
            if mbar < 0: mbar = 0.0
            if mbar > 100: mbar = 100.0

            sum_mbar += mbar
            # Korrigierter Zeitstempel mit Datum (verhindert Rollover Fehler um Mitternacht)
            time_str = self.next_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            rows_to_write.append([time_str, round(mbar, 2), raw_adc])
            self.next_time += timedelta(milliseconds=1)

        self.csv_writer.writerows(rows_to_write)
        self.file.flush()

        self.received_chunks += 1
        avg_mbar = sum_mbar / 100
        is_complete = self.received_chunks >= self.expected_chunks

        return avg_mbar, is_complete

    def close_session(self):
        if self.file:
            self.file.close()
            self.file = None
        print("\n>>> Messung beendet und CSV sicher gespeichert.")