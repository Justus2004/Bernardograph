import csv
import os
from datetime import datetime
import struct
import logging
import json
from config import OUTPUT_DIR

class DataProcessor:
    def __init__(self):
        self.logger = logging.getLogger("SensorApp.DataProcessor")
        self.file = None
        self.csv_writer = None
        self.expected_chunks = 0
        self.received_chunks = 0
        self.current_filepath = None
        self.current_index = 1
        self.settings_file = "settings.json"  # <--- NEU

    def get_save_directory(self):
        """Liest den Speicherort aus, oder fällt auf den Standard zurück."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                    custom_dir = data.get("save_dir", "")
                    
                    # Prüfen, ob der Ordner existiert (falls z.B. ein Stick abgezogen wurde)
                    if custom_dir and os.path.isdir(custom_dir):
                        return custom_dir
            except Exception as e:
                self.logger.warning(f"Fehler beim Lesen der Speichereinstellungen: {e}")
                
        # FALLBACK: Wenn nichts eingestellt ist oder der Ordner fehlt
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        return OUTPUT_DIR

    def start_session(self, seconds: int):
        self.expected_chunks = seconds * 10 if seconds > 0 else float('inf')
        self.received_chunks = 0
        self.current_index = 1
        
        # Dynamischen Speicherort ermitteln
        save_dir = self.get_save_directory()
        
        dateistempel = datetime.now().strftime("%Y%m%d_%H%M%S")
        dateiname = os.path.join(save_dir, f"messung_{dateistempel}_d{seconds}s.csv")
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
            spannung = raw_adc * (5.0 / 16383.0)
            mbar = 100.0 - ((spannung / 4.717) * 100.0)

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