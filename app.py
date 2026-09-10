import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, ttk
import threading
import asyncio
import queue
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import os
import csv
from datetime import datetime
import struct
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError

from config import DEVICE_NAME, STREAM_UUID, CMD_UUID, OUTPUT_DIR

class DataProcessor:
    def __init__(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self.file = None
        self.csv_writer = None
        self.expected_chunks = 0
        self.received_chunks = 0
        self.current_filepath = None
        self.current_index = 1

    def start_session(self, seconds: int):
        self.expected_chunks = seconds * 10
        self.received_chunks = 0
        self.current_index = 1
        
        dateistempel = datetime.now().strftime("%Y%m%d_%H%M%S")
        dateiname = os.path.join(OUTPUT_DIR, f"messung_{dateistempel}_d{seconds}s.csv")
        self.current_filepath = dateiname
        
        self.file = open(dateiname, mode='w', newline='')
        self.csv_writer = csv.writer(self.file, delimiter=';')
        self.csv_writer.writerow(["Index", "Druck_mbar", "ADC_Rohwert"])
        
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
            rows_to_write.append([self.current_index, round(mbar, 2), raw_adc])
            self.current_index += 1

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


class SensorDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Drucksensor Dashboard & Analyse")
        self.root.geometry("1400x800")
        
        self.msg_queue = queue.Queue()
        self.processor = DataProcessor()
        self.is_connecting = False
        
        # Daten-States
        self.raw_df = None       
        self.current_filepath = None
        self.press = None
        self.annot = None
        
        # Analyse-States
        self.slice_start = None
        self.slice_end = None
        self.threshold_val = None
        
        self.setup_ui()
        self.root.after(100, self.process_queue)
        self.log("Bereit. Klicke auf 'Bluetooth Start' oder 'CSV laden'.")

    def setup_ui(self):
        # Haupt-Container
        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # --- LINKER BEREICH: Graph & Logs ---
        left_frame = tk.Frame(main_paned)
        main_paned.add(left_frame, minsize=800)
        
        # Top Bar (Buttons & Status)
        top_frame = tk.Frame(left_frame, pady=10)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10)
        
        self.btn_connect = tk.Button(top_frame, text="Bluetooth Start", command=self.start_connection, bg="#0078D7", fg="white", font=("Arial", 10, "bold"))
        self.btn_connect.pack(side=tk.LEFT, padx=5)
        
        self.btn_load = tk.Button(top_frame, text="CSV laden", command=self.load_csv, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
        self.btn_load.pack(side=tk.LEFT, padx=5)
        
        self.lbl_status = tk.Label(top_frame, text="🔴 Getrennt", font=("Arial", 10, "bold"), fg="#D32F2F")
        self.lbl_status.pack(side=tk.LEFT, padx=15)
        
        # Graph
        self.fig, self.ax = plt.subplots(figsize=(10, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=left_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.canvas.mpl_connect('scroll_event', self.on_zoom)
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('button_release_event', self.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        
        # Log
        self.log_text = scrolledtext.ScrolledText(left_frame, height=6, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.log_text.pack(side=tk.BOTTOM, padx=10, pady=5, fill=tk.X)

        # --- RECHTER BEREICH: Analyse Panel ---
        right_frame = tk.Frame(main_paned, width=350, bg="#f0f0f0", padx=10, pady=10)
        main_paned.add(right_frame, minsize=300)
        
        lbl_title = tk.Label(right_frame, text="Analyse Werkzeuge", font=("Arial", 14, "bold"), bg="#f0f0f0")
        lbl_title.pack(pady=(0, 15))

        # 1. Glättung (Moving Average)
        lf_smooth = tk.LabelFrame(right_frame, text="1. Signal-Glättung", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_smooth.pack(fill=tk.X, pady=5)
        self.smooth_var = tk.IntVar(value=1)
        self.slider_smooth = tk.Scale(lf_smooth, from_=1, to=100, orient=tk.HORIZONTAL, variable=self.smooth_var, command=lambda _: self.update_plot(), bg="#f0f0f0", label="Fenstergröße (Werte)")
        self.slider_smooth.pack(fill=tk.X)

        # 2. Peaks (Min/Max)
        lf_peaks = tk.LabelFrame(right_frame, text="2. Automatische Peaks", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_peaks.pack(fill=tk.X, pady=5)
        self.chk_peaks_var = tk.BooleanVar(value=True)
        tk.Checkbutton(lf_peaks, text="Min/Max Marker anzeigen", variable=self.chk_peaks_var, command=self.update_plot, bg="#f0f0f0").pack(anchor="w")

        # 3. Zeitraum-Analyse
        lf_time = tk.LabelFrame(right_frame, text="3. Zeitraum-Analyse", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_time.pack(fill=tk.X, pady=5)
        
        frame_time_inputs = tk.Frame(lf_time, bg="#f0f0f0")
        frame_time_inputs.pack(fill=tk.X)
        tk.Label(frame_time_inputs, text="Von (s):", bg="#f0f0f0").grid(row=0, column=0, padx=2)
        self.ent_start = tk.Entry(frame_time_inputs, width=8)
        self.ent_start.grid(row=0, column=1, padx=2)
        tk.Label(frame_time_inputs, text="Bis (s):", bg="#f0f0f0").grid(row=0, column=2, padx=2)
        self.ent_end = tk.Entry(frame_time_inputs, width=8)
        self.ent_end.grid(row=0, column=3, padx=2)
        tk.Button(frame_time_inputs, text="Prüfen", command=self.analyze_slice).grid(row=0, column=4, padx=5)
        tk.Button(frame_time_inputs, text="X", command=self.clear_slice, fg="red").grid(row=0, column=5)
        
        self.lbl_stats = tk.Label(lf_time, text="Kein Bereich gewählt.", justify=tk.LEFT, bg="#f0f0f0", font=("Consolas", 9))
        self.lbl_stats.pack(anchor="w", pady=5)

        # 4. Schwellenwert (Threshold Trigger)
        lf_thresh = tk.LabelFrame(right_frame, text="4. Schwellenwert finden", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_thresh.pack(fill=tk.X, pady=5)
        frame_thresh_inputs = tk.Frame(lf_thresh, bg="#f0f0f0")
        frame_thresh_inputs.pack(fill=tk.X)
        tk.Label(frame_thresh_inputs, text="Ziel (mbar):", bg="#f0f0f0").pack(side=tk.LEFT, padx=2)
        self.ent_thresh = tk.Entry(frame_thresh_inputs, width=8)
        self.ent_thresh.pack(side=tk.LEFT, padx=2)
        tk.Button(frame_thresh_inputs, text="Suchen", command=self.find_threshold).pack(side=tk.LEFT, padx=5)
        tk.Button(frame_thresh_inputs, text="X", command=self.clear_threshold, fg="red").pack(side=tk.LEFT)
        
        self.lbl_thresh_res = tk.Label(lf_thresh, text="", bg="#f0f0f0", font=("Consolas", 9))
        self.lbl_thresh_res.pack(anchor="w", pady=5)

        # 5. Export
        lf_export = tk.LabelFrame(right_frame, text="5. Exportieren", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_export.pack(fill=tk.X, pady=5)
        tk.Button(lf_export, text="Aktuelle Ansicht als PNG", command=self.export_png, width=25).pack(pady=2)
        tk.Button(lf_export, text="Markierten Bereich als CSV", command=self.export_csv, width=25).pack(pady=2)

    # --- ZENTRALE PLOT-LOGIK (Wendet alle Analysen an) ---
    def update_plot(self):
        if self.raw_df is None: return
        
        # 1. Daten kopieren und Glättung anwenden
        df = self.raw_df.copy()
        window = self.smooth_var.get()
        if window > 1:
            df['Druck_mbar'] = df['Druck_mbar'].rolling(window=window, min_periods=1, center=True).mean()

        self.ax.clear()
        
        # 2. Hauptlinie zeichnen
        self.ax.plot(df['Sekunden'], df['Druck_mbar'], color='#D32F2F', linewidth=1.5)
        
        # 3. Min/Max Peaks anzeigen
        if self.chk_peaks_var.get():
            idx_max = df['Druck_mbar'].idxmax()
            idx_min = df['Druck_mbar'].idxmin()
            
            x_max, y_max = df.loc[idx_max, 'Sekunden'], df.loc[idx_max, 'Druck_mbar']
            x_min, y_min = df.loc[idx_min, 'Sekunden'], df.loc[idx_min, 'Druck_mbar']
            
            self.ax.plot(x_max, y_max, marker='o', color='blue', markersize=6)
            self.ax.annotate(f"MAX: {y_max:.1f}", (x_max, y_max), xytext=(0,10), textcoords="offset points", ha='center', color='blue', fontsize=8)
            
            self.ax.plot(x_min, y_min, marker='o', color='green', markersize=6)
            self.ax.annotate(f"MIN: {y_min:.1f}", (x_min, y_min), xytext=(0,-15), textcoords="offset points", ha='center', color='green', fontsize=8)

        # 4. Zeitraum-Analyse (Shading & Bereich markieren)
        if self.slice_start is not None and self.slice_end is not None:
            self.ax.axvspan(self.slice_start, self.slice_end, color='blue', alpha=0.15)
            self.ax.axvline(self.slice_start, color='blue', linestyle='--', linewidth=1)
            self.ax.axvline(self.slice_end, color='blue', linestyle='--', linewidth=1)

        # 5. Schwellenwert markieren
        if self.threshold_val is not None:
            cross_df = df[df['Druck_mbar'] >= self.threshold_val]
            if not cross_df.empty:
                cross_time = cross_df.iloc[0]['Sekunden']
                cross_val = cross_df.iloc[0]['Druck_mbar']
                
                self.ax.axhline(self.threshold_val, color='orange', linestyle='--', linewidth=1.5)
                self.ax.plot(cross_time, cross_val, marker='x', color='black', markersize=8, markeredgewidth=2)
                self.ax.annotate(f"Erreicht bei {cross_time:.3f}s", (cross_time, cross_val), xytext=(10,-10), textcoords="offset points", color='black')
                self.lbl_thresh_res.config(text=f"Schwelle überschritten:\nZeitpunkt: {cross_time:.3f} s\nExakter Wert: {cross_val:.2f} mbar")
            else:
                self.lbl_thresh_res.config(text="Schwelle wurde nie erreicht!")

        # Formatierung & 1. Quadrant
        filename = "Live-Daten" if not self.current_filepath else self.current_filepath.split('/')[-1].split('\\')[-1]
        self.ax.set_title(f"Messung: {filename} | Dauer: {df['Sekunden'].iloc[-1]:.2f} s")
        self.ax.set_xlabel("Zeit (Sekunden seit Start)")
        self.ax.set_ylabel("Druck (mbar)")
        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.ax.set_xlim(left=0)
        self.ax.set_ylim(bottom=0, top=105)
        
        # Tooltip Reset
        self.annot = self.ax.annotate("", xy=(0,0), xytext=(15,15), textcoords="offset points",
                                      bbox=dict(boxstyle="round,pad=0.3", fc="#ffffe0", ec="#aaaaaa", alpha=0.9),
                                      arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0"))
        self.annot.set_visible(False)
        
        self.canvas.draw_idle()

    # --- ANALYSE FUNKTIONEN (Rechtes Panel) ---
    def analyze_slice(self):
        if self.raw_df is None: return
        try:
            s_start = float(self.ent_start.get().replace(',', '.'))
            s_end = float(self.ent_end.get().replace(',', '.'))
            
            if s_start >= s_end:
                messagebox.showwarning("Eingabe", "Start muss kleiner als Ende sein.")
                return
                
            self.slice_start = s_start
            self.slice_end = s_end
            
            # Berechnen basierend auf geglätteten Daten!
            window = self.smooth_var.get()
            df = self.raw_df.copy()
            if window > 1:
                df['Druck_mbar'] = df['Druck_mbar'].rolling(window=window, min_periods=1, center=True).mean()
                
            mask = (df['Sekunden'] >= s_start) & (df['Sekunden'] <= s_end)
            sliced = df.loc[mask]
            
            if sliced.empty:
                self.lbl_stats.config(text="Keine Daten im Bereich.")
            else:
                avg = sliced['Druck_mbar'].mean()
                vmin = sliced['Druck_mbar'].min()
                vmax = sliced['Druck_mbar'].max()
                std = sliced['Druck_mbar'].std()
                
                start_val = sliced.iloc[0]['Druck_mbar']
                end_val = sliced.iloc[-1]['Druck_mbar']
                time_diff = sliced.iloc[-1]['Sekunden'] - sliced.iloc[0]['Sekunden']
                rate = (end_val - start_val) / time_diff if time_diff > 0 else 0
                
                stats_text = (f"Durchschnitt:  {avg:.2f} mbar\n"
                              f"Minimum:       {vmin:.2f} mbar\n"
                              f"Maximum:       {vmax:.2f} mbar\n"
                              f"Schwankung(σ): ±{std:.2f} mbar\n"
                              f"Steigung/Rate: {rate:.2f} mbar/s")
                self.lbl_stats.config(text=stats_text)
                
            self.update_plot()
        except ValueError:
            messagebox.showerror("Fehler", "Bitte gültige Zahlen für den Zeitraum eingeben.")

    def clear_slice(self):
        self.slice_start = None
        self.slice_end = None
        self.ent_start.delete(0, tk.END)
        self.ent_end.delete(0, tk.END)
        self.lbl_stats.config(text="Kein Bereich gewählt.")
        self.update_plot()

    def find_threshold(self):
        if self.raw_df is None: return
        try:
            val = float(self.ent_thresh.get().replace(',', '.'))
            self.threshold_val = val
            self.update_plot()
        except ValueError:
            messagebox.showerror("Fehler", "Bitte eine gültige Zahl für den Schwellenwert eingeben.")

    def clear_threshold(self):
        self.threshold_val = None
        self.ent_thresh.delete(0, tk.END)
        self.lbl_thresh_res.config(text="")
        self.update_plot()

    def export_png(self):
        if self.raw_df is None: return
        filepath = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")])
        if filepath:
            self.fig.savefig(filepath, dpi=300, bbox_inches='tight')
            self.log(f"INFO: Graph als Bild gespeichert unter {filepath}")

    def export_csv(self):
        if self.raw_df is None or self.slice_start is None or self.slice_end is None:
            messagebox.showinfo("Info", "Bitte zuerst einen Zeitraum analysieren (Start/Bis), um diesen zu exportieren.")
            return
            
        filepath = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV File", "*.csv")])
        if filepath:
            df = self.raw_df.copy()
            mask = (df['Sekunden'] >= self.slice_start) & (df['Sekunden'] <= self.slice_end)
            sliced = df.loc[mask]
            sliced.to_csv(filepath, sep=';', index=False)
            self.log(f"INFO: Bereich als CSV gespeichert unter {filepath}")

    # --- CSV LADEN ---
    def load_csv(self):
        filepath = filedialog.askopenfilename(
            title="Messdaten auswählen",
            filetypes=[("CSV Dateien", "*.csv")]
        )
        if filepath:
            self.current_filepath = filepath
            self.plot_data(filepath)

    def plot_data(self, filepath):
        try:
            self.log(f"INFO: Lade Daten...")
            df = pd.read_csv(filepath, sep=';')
            
            if 'Index' in df.columns:
                df['Sekunden'] = (df['Index'] - 1) / 1000.0
            else:
                erster_wert = str(df['Zeitstempel'].iloc[0])
                if ':' in erster_wert:
                    try:
                        df['Zeit_Objekt'] = pd.to_datetime(df['Zeitstempel'], format='%Y-%m-%d %H:%M:%S.%f')
                    except ValueError:
                        df['Zeit_Objekt'] = pd.to_datetime(df['Zeitstempel'], format='%H:%M:%S.%f')
                    startzeit = df['Zeit_Objekt'].iloc[0]
                    df['Sekunden'] = (df['Zeit_Objekt'] - startzeit).dt.total_seconds()
                else:
                    df['Sekunden'] = (df['Zeitstempel'].astype(float) - 1) / 1000.0

            # Rohdaten für spätere Analysen/Glättungen speichern
            self.raw_df = df
            
            # Alle alten Analyse-Markierungen zurücksetzen
            self.clear_slice()
            self.clear_threshold()
            self.smooth_var.set(1)
            
            # Initialer Plot-Aufruf
            self.update_plot()
            
        except Exception as e:
            self.log(f"ERR: Fehler beim Laden der Datei: {e}")
            messagebox.showerror("Ladefehler", f"Die Datei konnte nicht verarbeitet werden.\nFehler: {e}")

    # --- MAUS-INTERAKTIONEN (Zoom, Pan, Hover im 1. Quadranten) ---
    def on_zoom(self, event):
        if event.inaxes != self.ax: return
        base_scale = 1.2
        if event.button == 'up':
            scale_factor = 1 / base_scale
        elif event.button == 'down':
            scale_factor = base_scale
        else:
            return
            
        xdata, ydata = event.xdata, event.ydata
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
        
        new_width = (xlim[1] - xlim[0]) * scale_factor
        new_height = (ylim[1] - ylim[0]) * scale_factor
        
        new_xmin = xdata - new_width * (1 - (xlim[1] - xdata) / (xlim[1] - xlim[0]))
        new_xmax = xdata + new_width * ((xlim[1] - xdata) / (xlim[1] - xlim[0]))
        new_ymin = ydata - new_height * (1 - (ylim[1] - ydata) / (ylim[1] - ylim[0]))
        new_ymax = ydata + new_height * ((ylim[1] - ydata) / (ylim[1] - ylim[0]))

        if new_xmin < 0: new_xmin = 0
        if new_ymin < 0: new_ymin = 0
        
        self.ax.set_xlim([new_xmin, new_xmax])
        self.ax.set_ylim([new_ymin, new_ymax])
        self.canvas.draw_idle()

    def on_press(self, event):
        if event.button in [1, 3] and event.inaxes == self.ax:
            self.press = (event.x, event.y, self.ax.get_xlim(), self.ax.get_ylim())
            self.canvas.get_tk_widget().config(cursor="fleur")

    def on_release(self, event):
        self.press = None
        self.canvas.get_tk_widget().config(cursor="arrow")
        self.canvas.draw_idle()

    def on_motion(self, event):
        if event.inaxes != self.ax:
            if self.annot and self.annot.get_visible():
                self.annot.set_visible(False)
                self.canvas.draw_idle()
            return

        if self.press is not None:
            if self.annot and self.annot.get_visible():
                self.annot.set_visible(False)
            x0, y0, xlim, ylim = self.press
            dx_data = (event.x - x0) * (xlim[1] - xlim[0]) / self.ax.bbox.width
            dy_data = (event.y - y0) * (ylim[1] - ylim[0]) / self.ax.bbox.height
            
            new_xmin = xlim[0] - dx_data
            new_xmax = xlim[1] - dx_data
            new_ymin = ylim[0] - dy_data
            new_ymax = ylim[1] - dy_data

            if new_xmin < 0:
                new_xmax -= new_xmin
                new_xmin = 0
            if new_ymin < 0:
                new_ymax -= new_ymin
                new_ymin = 0

            self.ax.set_xlim(new_xmin, new_xmax)
            self.ax.set_ylim(new_ymin, new_ymax)
            self.canvas.draw_idle()
            return
        
        if self.raw_df is not None and event.xdata is not None and self.annot:
            # Für den Tooltip nutzen wir immer die geglätteten Daten, die gerade angezeigt werden
            window = self.smooth_var.get()
            df = self.raw_df.copy()
            if window > 1:
                df['Druck_mbar'] = df['Druck_mbar'].rolling(window=window, min_periods=1, center=True).mean()
                
            idx = (df['Sekunden'] - event.xdata).abs().idxmin()
            row = df.loc[idx]
            closest_x = row['Sekunden']
            closest_y = row['Druck_mbar']
            
            x_range = self.ax.get_xlim()[1] - self.ax.get_xlim()[0]
            if abs(closest_x - event.xdata) < (x_range * 0.05):
                self.annot.xy = (closest_x, closest_y)
                self.annot.set_text(f"{closest_x:.3f} s\n{closest_y:.2f} mbar")
                self.annot.set_visible(True)
            else:
                self.annot.set_visible(False)
            self.canvas.draw_idle()

    # --- GUI & BLUETOOTH QUEUE LOGIK ---
    def log(self, msg):
        self.msg_queue.put(("LOG", msg))

    def process_queue(self):
        while not self.msg_queue.empty():
            msg_type, data = self.msg_queue.get()
            if msg_type == "LOG":
                self.log_text.insert(tk.END, data + "\n")
                self.log_text.see(tk.END)
            elif msg_type == "PLOT":
                self.current_filepath = data
                self.plot_data(data)
            elif msg_type == "STATUS":
                text, color = data
                self.lbl_status.config(text=text, fg=color)
        self.root.after(100, self.process_queue)

    def start_connection(self):
        if self.is_connecting: return
        self.is_connecting = True
        self.btn_connect.config(state=tk.DISABLED, text="Bluetooth aktiv")
        threading.Thread(target=self.run_ble_loop, daemon=True).start()

    def run_ble_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.ble_task())

    async def ble_task(self):
        self.log("INFO: Automatischer Verbindungsmodus gestartet.")
        
        while True:
            self.msg_queue.put(("STATUS", ("🟡 Suche...", "#FFA500")))
            try:
                devices = await BleakScanner.discover(timeout=5.0)
            except BleakError as e:
                self.log(f"ERR: Bluetooth-Adapter Fehler: {e}")
                self.msg_queue.put(("STATUS", ("🔴 Adapter-Fehler", "#D32F2F")))
                await asyncio.sleep(5)
                continue
            except Exception as e:
                self.log(f"ERR: Scan-Fehler: {e}")
                await asyncio.sleep(5)
                continue

            target = next((d for d in devices if d.name == DEVICE_NAME), None)

            if not target:
                self.msg_queue.put(("STATUS", ("🔴 Nicht gefunden", "#D32F2F")))
                await asyncio.sleep(3)
                continue

            self.log(f"Gefunden: {target.address}. Verbinde...")
            self.msg_queue.put(("STATUS", ("🟡 Verbinde...", "#FFA500")))
            
            def on_disconnect(client):
                self.log("WARN: Verbindung abgebrochen. Versuche Neustart...")
                self.msg_queue.put(("STATUS", ("🔴 Getrennt", "#D32F2F")))
                if self.processor.file:
                    self.processor.close_session()

            try:
                async with BleakClient(target, disconnected_callback=on_disconnect) as client:
                    self.log("🟢 Verbunden! Warte auf Tasterdruck...")
                    self.msg_queue.put(("STATUS", ("🟢 Verbunden", "#4CAF50")))

                    def handle_cmd(sender, data):
                        msg = data.decode('utf-8').strip()
                        if msg.startswith("INFO:") or msg.startswith("WARN:") or msg.startswith("ERR:"):
                            self.log(f"Arduino: {msg}")
                        elif msg.startswith("START:"):
                            sec = int(msg.split(":")[1])
                            self.processor.start_session(sec)
                        elif msg == "END":
                            self.processor.close_session()
                            if self.processor.current_filepath:
                                self.msg_queue.put(("PLOT", self.processor.current_filepath))

                    def handle_stream(sender, data):
                        avg, complete = self.processor.process_chunk(data)
                        if complete:
                            self.processor.close_session()
                            if self.processor.current_filepath:
                                self.msg_queue.put(("PLOT", self.processor.current_filepath))

                    await client.start_notify(CMD_UUID, handle_cmd)
                    await client.start_notify(STREAM_UUID, handle_stream)

                    while client.is_connected:
                        await asyncio.sleep(1)
                        
            except BleakError as e:
                self.log(f"ERR: Bluetooth-Verbindungsfehler: {e}")
                self.msg_queue.put(("STATUS", ("🔴 Fehler", "#D32F2F")))
                await asyncio.sleep(3)
            except Exception as e:
                self.log(f"ERR: Unerwarteter Fehler: {e}")
                self.msg_queue.put(("STATUS", ("🔴 Fehler", "#D32F2F")))
                await asyncio.sleep(3)

if __name__ == "__main__":
    root = tk.Tk()
    app = SensorDashboard(root)
    root.mainloop()