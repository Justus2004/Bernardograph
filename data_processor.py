import csv
import os
from datetime import datetime
import struct
import logging
from config import OUTPUT_DIR

class DataProcessor:
    def __init__(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self.logger = logging.getLogger("SensorApp.DataProcessor")
        self.file = None
        self.csv_writer = None
        self.expected_chunks = 0
        self.received_chunks = 0
        self.current_filepath = None
        self.current_index = 1

    def start_session(self, seconds: int):
        self.expected_chunks = seconds * 10 if seconds > 0 else float('inf')
        self.received_chunks = 0
        self.current_index = 1
        
        dateistempel = datetime.now().strftime("%Y%m%d_%H%M%S")
        dateiname = os.path.join(OUTPUT_DIR, f"messung_{dateistempel}_d{seconds}s.csv")
        self.current_filepath = dateiname
        
        self.file = open(dateiname, mode='w', newline='')
        self.csv_writer = csv.writer(self.file, delimiter=';')
        self.csv_writer.writerow(["Index", "Druck_mbar", "ADC_Rohwert"])
        self.logger.info(f">>> Messung gestartet. Datei: {dateiname}")

    def process_chunk(self, data: bytes) -> tuple:
        if not self.file or len(data) != 200:
            return 0, False, []

        raw_values = struct.unpack('<100H', data)
        rows_to_write = []
        sum_mbar = 0
        mbar_chunk = [] 

        for raw_adc in raw_values:
            # Exakte Formel wie auf dem Arduino:
            # 1. ADC-Wert in Spannung umrechnen (14 Bit = 0 bis 16383)
            spannung = raw_adc * (5.0 / 16383.0)
            
            # 2. Spannung in Druck (mbar) umrechnen
            mbar = 100.0 - ((spannung / 4.717) * 100.0)

            # 3. Grenzbereich sauber abfangen
            if mbar < 0.0:
                mbar = 0.0
            elif mbar > 100.0:
                mbar = 100.0

            sum_mbar += mbar
            mbar_round = round(mbar, 2)
            rows_to_write.append([self.current_index, mbar_round, raw_adc])
            mbar_chunk.append(mbar_round)
            self.current_index += 1

        self.csv_writer.writerows(rows_to_write)
        self.file.flush()

        self.received_chunks += 1
        avg_mbar = sum_mbar / 100
        is_complete = self.received_chunks >= self.expected_chunks

        return avg_mbar, is_complete, mbar_chunk

    def close_session(self):
        if self.file:
            self.file.close()
            self.file = None
            self.logger.info(">>> Messung beendet und CSV sicher gespeichert.")
            return True
        return False