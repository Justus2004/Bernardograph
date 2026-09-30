import tkinter as tk
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from tkinter.scrolledtext import ScrolledText
from tkinter import messagebox, filedialog
import queue
import pandas as pd
import matplotlib.pyplot as plt
import os
import logging
from logging.handlers import RotatingFileHandler
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.widgets import SpanSelector

from config import APP_VERSION, MAX_LIVE_POINTS
from data_processor import DataProcessor
from bluetooth_handler import BluetoothHandler
from updater import AppUpdater
from plot_events import PlotEventManager

# Custom Logging Handler, um Logs in die UI zu pushen
class QueueLoggingHandler(logging.Handler):
    def __init__(self, msg_queue):
        super().__init__()
        self.msg_queue = msg_queue
        
    def emit(self, record):
        self.msg_queue.put(("LOG", self.format(record)))


class SensorDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Drucksensor Dashboard & Analyse")
        self.root.geometry("1450x850")
        
        self.msg_queue = queue.Queue()
        self.setup_logging()
        
        self.processor = DataProcessor()
        self.ble_handler = BluetoothHandler(self.msg_queue, self.processor)
        self.updater = AppUpdater(self.root)
        self.plot_events = PlotEventManager(self)
        
        self.datasets = [] 
        self.colors = ['#D32F2F', '#1976D2', '#388E3C', '#FBC02D', '#8E24AA', '#E64A19', '#0097A7']
        
        self.current_filepath = None
        self.press = None
        self.annot = None
        self.current_key = None 
        
        self.is_measuring = False
        self.countdown = 0
        self.live_x = []
        self.live_y = []
        self.live_index = 0
        self.live_line = None
        
        self.slice_start = None
        self.slice_end = None
        self.threshold_val = None
        
        self.setup_ui()
        self.root.after(100, self.process_queue)
        self.logger.info("Bereit. Starte automatische Bluetooth-Verbindung...\nTipp: Halte 'x' oder 'y' beim Scrollen für gezielten Zoom!")
        
        self.root.after(500, self.start_connection)
        self.root.after(2000, self.updater.check_for_updates) 
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_logging(self):
        self.logger = logging.getLogger("SensorApp")
        self.logger.setLevel(logging.DEBUG)
        
        # 1. Speichern in Datei
        fh = RotatingFileHandler("app.log", maxBytes=1024*1024, backupCount=3)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
        self.logger.addHandler(fh)
        
        # 2. Ausgeben im UI-Fenster
        qh = QueueLoggingHandler(self.msg_queue)
        qh.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        qh.setLevel(logging.INFO) # Nur Info, Warnings, Errors in der UI
        self.logger.addHandler(qh)

    def on_closing(self):
        print("Beende Programm hart...")
        try:
            if self.is_measuring and self.processor: self.processor.close_session()
        except: pass 
        self.root.destroy()
        os._exit(0) 

    def setup_ui(self):
        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=BOTH, expand=True)

        left_frame = tb.Frame(main_paned)
        main_paned.add(left_frame, minsize=800)
        
        top_frame = tb.Frame(left_frame, padding=10)
        top_frame.pack(side=TOP, fill=X)
        
        self.btn_connect = tb.Button(top_frame, text="Bluetooth Start", command=self.start_connection, bootstyle=PRIMARY)
        self.btn_connect.pack(side=LEFT, padx=5)

        self.btn_update = tb.Button(top_frame, text=f"v{APP_VERSION} (Update)", command=lambda: self.updater.check_for_updates(manual=True), bootstyle=INFO)
        self.btn_update.pack(side=RIGHT, padx=5)
        
        self.btn_load = tb.Button(top_frame, text="CSV laden", command=lambda: self.load_csv(append=False), bootstyle=SUCCESS)
        self.btn_load.pack(side=LEFT, padx=5)

        self.btn_add = tb.Button(top_frame, text="+ CSV hinzufügen", command=lambda: self.load_csv(append=True), bootstyle=(SUCCESS, OUTLINE))
        self.btn_add.pack(side=LEFT, padx=5)
        
        self.btn_reset = tb.Button(top_frame, text="Reset Ansicht", command=self.reset_view, bootstyle=SECONDARY)
        self.btn_reset.pack(side=LEFT, padx=5)
        
        # Einstellungs-Button für Kalibrierung
        self.btn_settings = tb.Button(top_frame, text="⚙️ Einstellungen", command=self.open_settings, bootstyle=WARNING)
        self.btn_settings.pack(side=LEFT, padx=5)
        
        tb.Label(top_frame, text="Y-Max:", font=("Arial", 10, "bold")).pack(side=LEFT, padx=(15, 2))
        self.ent_ymax = tb.Entry(top_frame, width=5)
        self.ent_ymax.insert(0, "105")
        self.ent_ymax.pack(side=LEFT, padx=2)
        self.ent_ymax.bind("<Return>", lambda _: self.update_plot())
        
        self.lbl_status = tb.Label(top_frame, text="🔴 Getrennt", font=("Arial", 10, "bold"), bootstyle=DANGER)
        self.lbl_status.pack(side=LEFT, padx=15)
        
        self.lbl_countdown = tb.Label(top_frame, text="", font=("Arial", 10, "bold"), bootstyle=WARNING)
        self.lbl_countdown.pack(side=LEFT, padx=15)
        
        # Matplotlib Figure
        self.fig, self.ax = plt.subplots(figsize=(10, 4))
        self.fig.patch.set_facecolor('#222222') # Darkmode anpassung
        self.ax.set_facecolor('#333333')
        self.ax.tick_params(colors='white')
        self.ax.xaxis.label.set_color('white')
        self.ax.yaxis.label.set_color('white')
        self.ax.title.set_color('white')
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=left_frame)
        self.canvas.get_tk_widget().pack(side=TOP, fill=BOTH, expand=True)
        
        self.span = SpanSelector(self.ax, self.on_span_select, 'horizontal', useblit=True, props=dict(alpha=0.25, facecolor='cyan'), interactive=True)
        
        # Events an die externe Plot-Klasse übergeben
        self.canvas.mpl_connect('scroll_event', self.plot_events.on_zoom)
        self.canvas.mpl_connect('button_press_event', self.plot_events.on_press)
        self.canvas.mpl_connect('button_release_event', self.plot_events.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.plot_events.on_motion)
        self.canvas.mpl_connect('key_press_event', self.plot_events.on_key_press)
        self.canvas.mpl_connect('key_release_event', self.plot_events.on_key_release)
        
        self.log_text = ScrolledText(left_frame, height=6, bg="#222222", fg="white", font=("Consolas", 10), insertbackground="white")
        self.log_text.pack(side=BOTTOM, padx=10, pady=5, fill=X)

        right_frame = tb.Frame(main_paned, padding=10)
        main_paned.add(right_frame, minsize=350)
        
        tb.Label(right_frame, text="Analyse Werkzeuge", font=("Arial", 14, "bold")).pack(pady=(0, 10))

        lf_smooth = tb.LabelFrame(right_frame, text="1. Signal-Glättung", padding=10)
        lf_smooth.pack(fill=X, pady=5)
        self.smooth_var = tb.IntVar(value=1)
        tb.Scale(lf_smooth, from_=1, to=100, orient=HORIZONTAL, variable=self.smooth_var, command=lambda _: self.update_plot()).pack(fill=X)

        lf_peaks = tb.LabelFrame(right_frame, text="2. Automatische Peaks", padding=10)
        lf_peaks.pack(fill=X, pady=5)
        self.chk_peaks_var = tb.BooleanVar(value=True)
        tb.Checkbutton(lf_peaks, text="Min/Max Marker anzeigen", variable=self.chk_peaks_var, command=self.update_plot, bootstyle="round-toggle").pack(anchor="w")

        lf_time = tb.LabelFrame(right_frame, text="3. Zeitraum-Analyse (Maus ziehen!)", padding=10)
        lf_time.pack(fill=X, pady=5)
        frame_time_inputs = tb.Frame(lf_time)
        frame_time_inputs.pack(fill=X)
        tb.Label(frame_time_inputs, text="Von:").grid(row=0, column=0, padx=2)
        self.ent_start = tb.Entry(frame_time_inputs, width=6)
        self.ent_start.grid(row=0, column=1, padx=2)
        tb.Label(frame_time_inputs, text="Bis:").grid(row=0, column=2, padx=2)
        self.ent_end = tb.Entry(frame_time_inputs, width=6)
        self.ent_end.grid(row=0, column=3, padx=2)
        tb.Button(frame_time_inputs, text="Prüfen", command=self.analyze_slice, bootstyle=INFO).grid(row=0, column=4, padx=5)
        tb.Button(frame_time_inputs, text="X", command=self.clear_slice, bootstyle=DANGER).grid(row=0, column=5)
        self.lbl_stats = tb.Label(lf_time, text="Kein Bereich gewählt.", justify=LEFT, font=("Consolas", 9))
        self.lbl_stats.pack(anchor="w", pady=5)

        lf_thresh = tb.LabelFrame(right_frame, text="4. Schwellenwert finden", padding=10)
        lf_thresh.pack(fill=X, pady=5)
        frame_thresh_inputs = tb.Frame(lf_thresh)
        frame_thresh_inputs.pack(fill=X)
        tb.Label(frame_thresh_inputs, text="Ziel (mbar):").pack(side=LEFT, padx=2)
        self.ent_thresh = tb.Entry(frame_thresh_inputs, width=8)
        self.ent_thresh.pack(side=LEFT, padx=2)
        tb.Button(frame_thresh_inputs, text="Suchen", command=self.find_threshold, bootstyle=INFO).pack(side=LEFT, padx=5)
        tb.Button(frame_thresh_inputs, text="X", command=self.clear_threshold, bootstyle=DANGER).pack(side=LEFT)
        self.lbl_thresh_res = tb.Label(lf_thresh, text="", font=("Consolas", 9))
        self.lbl_thresh_res.pack(anchor="w", pady=5)
        
        lf_export = tb.LabelFrame(right_frame, text="5. Dokumentation & Export", padding=10)
        lf_export.pack(fill=X, pady=5)
        tb.Label(lf_export, text="Notizen / Bemerkungen:").pack(anchor="w")
        self.text_notes = tb.Text(lf_export, height=3, width=30, font=("Arial", 9))
        self.text_notes.pack(fill=X, pady=2)
        
        tb.Button(lf_export, text="Notizen separat speichern", command=self.export_notes, bootstyle=(PRIMARY, OUTLINE)).pack(fill=X, pady=2)
        tb.Button(lf_export, text="Aktuelle Ansicht als PNG", command=self.export_png, bootstyle=(PRIMARY, OUTLINE)).pack(fill=X, pady=2)
        tb.Button(lf_export, text="Markierten Bereich als CSV", command=self.export_csv, bootstyle=(PRIMARY, OUTLINE)).pack(fill=X, pady=2)

    def open_settings(self):
        top = tb.Toplevel(self.root)
        top.title("Kalibrierung")
        top.geometry("300x250")
        
        tb.Label(top, text="ADC Auflösung:").pack(pady=(10, 2))
        ent_adc = tb.Entry(top)
        ent_adc.insert(0, str(self.processor.adc_res))
        ent_adc.pack()
        
        tb.Label(top, text="Referenzspannung (V):").pack(pady=(10, 2))
        ent_ref = tb.Entry(top)
        ent_ref.insert(0, str(self.processor.ref_volt))
        ent_ref.pack()
        
        tb.Label(top, text="Spannungsteiler:").pack(pady=(10, 2))
        ent_div = tb.Entry(top)
        ent_div.insert(0, str(self.processor.volt_div))
        ent_div.pack()
        
        def save():
            try:
                self.processor.adc_res = float(ent_adc.get())
                self.processor.ref_volt = float(ent_ref.get())
                self.processor.volt_div = float(ent_div.get())
                self.logger.info("Kalibrierung erfolgreich aktualisiert.")
                top.destroy()
            except ValueError:
                messagebox.showerror("Fehler", "Bitte gültige Zahlen eingeben.")
                
        tb.Button(top, text="Speichern", command=save, bootstyle=SUCCESS).pack(pady=20)

    # --- Restliche Methoden bleiben von der Logik her identisch, nur kleine Anpassungen beim Logging ---
    
    def on_span_select(self, xmin, xmax):
        self.ent_start.delete(0, tb.END)
        self.ent_start.insert(0, f"{xmin:.3f}")
        self.ent_end.delete(0, tb.END)
        self.ent_end.insert(0, f"{xmax:.3f}")
        self.analyze_slice()

    def reset_view(self):
        if not self.datasets and not self.is_measuring: return
        try: ymax = float(self.ent_ymax.get().replace(',', '.'))
        except: ymax = 105
        max_time = self.countdown
        if self.datasets: max_time = max([df['Sekunden'].iloc[-1] for _, df in self.datasets])
        self.ax.set_xlim(left=0, right=max_time)
        self.ax.set_ylim(bottom=0, top=ymax)
        self.canvas.draw_idle()

    def process_queue(self):
        while not self.msg_queue.empty():
            msg_type, data = self.msg_queue.get()
            if msg_type == "LOG":
                self.log_text.insert(tb.END, data + "\n")
                self.log_text.see(tb.END)
            elif msg_type == "STATUS":
                self.lbl_status.config(text=data[0], bootstyle=data[1])
            elif msg_type == "START_MEASURE":
                self.start_live_plot(data)
            elif msg_type == "LIVE_DATA":
                self.update_live_plot(data)
            elif msg_type == "END_MEASURE":
                self.stop_live_plot()
                self.load_csv(append=False, direct_path=data)
        self.root.after(100, self.process_queue)

    def start_connection(self):
        self.btn_connect.config(state=DISABLED, text="Bluetooth aktiv")
        self.ble_handler.start()

    def start_live_plot(self, seconds):
        self.is_measuring = True
        self.countdown = seconds
        self.live_x, self.live_y, self.live_index = [], [], 0
        self.datasets = [] 
        self.ax.clear()
        self.ax.grid(True, linestyle='--', alpha=0.3)
        
        try: ymax = float(self.ent_ymax.get().replace(',', '.'))
        except: ymax = 105
        
        if seconds == 0:
            self.lbl_countdown.config(text="⏳ Dauermessung läuft...", bootstyle=WARNING)
            self.ax.set_title("Live-Dauermessung (Stoppen am Arduino)", color="white")
            self.ax.set_xlim(0, 10) 
        else:
            self.lbl_countdown.config(text=f"⏳ {self.countdown} s verbleiben", bootstyle=WARNING)
            self.ax.set_title(f"Live-Messung läuft... (Ziel: {seconds} s)", color="white")
            self.ax.set_xlim(0, seconds)
            
        self.ax.set_xlabel("Zeit (Sekunden seit Start)")
        self.ax.set_ylabel("Druck (mbar)")
        self.ax.set_ylim(0, ymax)
        
        self.live_line, = self.ax.plot([], [], color='#00d2ff', linewidth=1.5)
        self.canvas.draw_idle()
        if seconds > 0: self.update_countdown()

    def update_countdown(self):
        if self.is_measuring and self.countdown > 0:
            self.countdown -= 1
            self.lbl_countdown.config(text=f"⏳ {self.countdown} s verbleiben")
            self.root.after(1000, self.update_countdown)

    def update_live_plot(self, mbar_chunk):
        if not self.is_measuring: return
        new_x = [(self.live_index + i) / 1000.0 for i in range(len(mbar_chunk))]
        self.live_x.extend(new_x)
        self.live_y.extend(mbar_chunk)
        self.live_index += len(mbar_chunk)
        
        # --- NEU: Rollierendes Fenster bei zu vielen Datenpunkten ---
        if len(self.live_x) > MAX_LIVE_POINTS:
            self.live_x = self.live_x[-MAX_LIVE_POINTS:]
            self.live_y = self.live_y[-MAX_LIVE_POINTS:]
            window_width = self.live_x[-1] - self.live_x[0]
            self.ax.set_xlim(self.live_x[0], self.live_x[-1] + (window_width * 0.05))
        elif self.countdown == 0 and self.live_x[-1] > self.ax.get_xlim()[1]:
            current_max = self.ax.get_xlim()[1]
            self.ax.set_xlim(current_max - 5, current_max + 5)
        
        self.live_line.set_data(self.live_x, self.live_y)
        self.canvas.draw_idle()

    def stop_live_plot(self):
        self.is_measuring = False
        self.lbl_countdown.config(text="✅ Messung beendet", bootstyle=SUCCESS)

    def load_csv(self, append=False, direct_path=None):
        if self.is_measuring: return messagebox.showwarning("Achtung", "Bitte warte, bis die laufende Messung abgeschlossen ist.")
        filepath = direct_path or filedialog.askopenfilename(title="Messdaten auswählen", filetypes=[("CSV Dateien", "*.csv")])
        if filepath:
            if not append: 
                self.datasets = [] 
                self.text_notes.delete("1.0", tb.END)
                self.ent_ymax.delete(0, tb.END)
                self.ent_ymax.insert(0, "105")
                self.clear_slice()
                self.clear_threshold()
                self.smooth_var.set(1)
                
            self.current_filepath = filepath
            try:
                self.logger.info(f"Lade Daten: {os.path.basename(filepath)}")
                with open(filepath, 'r') as f:
                    skip = sum(1 for line in f if line.startswith('#'))
                        
                df = pd.read_csv(filepath, sep=';', skiprows=skip)
                if 'Index' in df.columns:
                    df['Sekunden'] = (df['Index'] - 1) / 1000.0
                elif 'Sekunden' not in df.columns:
                    erster_wert = str(df['Zeitstempel'].iloc[0])
                    if ':' in erster_wert:
                        try: df['Zeit_Objekt'] = pd.to_datetime(df['Zeitstempel'], format='%Y-%m-%d %H:%M:%S.%f')
                        except ValueError: df['Zeit_Objekt'] = pd.to_datetime(df['Zeitstempel'], format='%H:%M:%S.%f')
                        df['Sekunden'] = (df['Zeit_Objekt'] - df['Zeit_Objekt'].iloc[0]).dt.total_seconds()
                    else: df['Sekunden'] = (df['Zeitstempel'].astype(float) - 1) / 1000.0

                self.datasets.append((os.path.basename(filepath), df))
                self.update_plot()
                self.reset_view()
            except Exception as e:
                self.logger.error(f"Fehler beim Laden: {e}")
                messagebox.showerror("Ladefehler", f"Fehler: {e}")
                
    def update_plot(self):
        if not self.datasets or self.is_measuring: return
        window = self.smooth_var.get()
        self.ax.clear()
        self.ax.grid(True, linestyle='--', alpha=0.3)
        
        try: ymax = float(self.ent_ymax.get().replace(',', '.'))
        except: ymax = 105

        max_time = 0
        for idx, (name, raw_df) in enumerate(self.datasets):
            df = raw_df.copy()
            color = self.colors[idx % len(self.colors)]
            if window > 1: df['Druck_mbar'] = df['Druck_mbar'].rolling(window=window, min_periods=1, center=True).mean()

            self.ax.plot(df['Sekunden'], df['Druck_mbar'], color=color, linewidth=1.5, label=name)
            if df['Sekunden'].iloc[-1] > max_time: max_time = df['Sekunden'].iloc[-1]
            
            if self.chk_peaks_var.get():
                idx_max, idx_min = df['Druck_mbar'].idxmax(), df['Druck_mbar'].idxmin()
                self.ax.plot(df.loc[idx_max, 'Sekunden'], df.loc[idx_max, 'Druck_mbar'], marker='o', color=color)
                self.ax.plot(df.loc[idx_min, 'Sekunden'], df.loc[idx_min, 'Druck_mbar'], marker='x', color=color)

            if self.threshold_val is not None:
                cross_df = df[df['Druck_mbar'] >= self.threshold_val]
                if not cross_df.empty:
                    ct, cv = cross_df.iloc[0]['Sekunden'], cross_df.iloc[0]['Druck_mbar']
                    self.ax.plot(ct, cv, marker='x', color='white', markersize=8)
                    self.lbl_thresh_res.config(text=f"Schwelle erreicht:\nZeit: {ct:.3f} s\nWert: {cv:.2f} mbar")

        if len(self.datasets) > 1:
            legend = self.ax.legend(loc="upper right", fontsize=8)
            plt.setp(legend.get_texts(), color='black') # Legend text color fix
            
        if self.slice_start is not None and self.slice_end is not None:
            self.ax.axvspan(self.slice_start, self.slice_end, color='cyan', alpha=0.15)
            self.ax.axvline(self.slice_start, color='cyan', linestyle='--')
            self.ax.axvline(self.slice_end, color='cyan', linestyle='--')
        if self.threshold_val is not None: self.ax.axhline(self.threshold_val, color='orange', linestyle='--')

        title_str = "Live-Daten" if not self.current_filepath else f"{len(self.datasets)} Messungen geladen"
        self.ax.set_title(title_str, color='white')
        self.ax.set_xlabel("Zeit (Sekunden)")
        self.ax.set_ylabel("Druck (mbar)")
        self.ax.set_xlim(left=0, right=max_time)
        self.ax.set_ylim(bottom=0, top=ymax)
        
        self.annot = self.ax.annotate("", xy=(0,0), xytext=(15,15), textcoords="offset points", bbox=dict(boxstyle="round,pad=0.3", fc="#222222", ec="white", alpha=0.9), arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0", color="white"))
        self.annot.get_bbox_patch().set_alpha(0.9)
        self.annot.set_color("white")
        self.annot.set_visible(False)
        self.canvas.draw_idle()

    def analyze_slice(self):
        if not self.datasets or self.is_measuring: return
        try:
            s_start = float(self.ent_start.get().replace(',', '.'))
            s_end = float(self.ent_end.get().replace(',', '.'))
            if s_start >= s_end: return messagebox.showwarning("Eingabe", "Start muss kleiner als Ende sein.")
                
            self.slice_start, self.slice_end = s_start, s_end
            _, raw_df = self.datasets[-1] 
            df = raw_df.copy()
            if self.smooth_var.get() > 1: df['Druck_mbar'] = df['Druck_mbar'].rolling(window=self.smooth_var.get(), center=True).mean()
                
            sliced = df[(df['Sekunden'] >= s_start) & (df['Sekunden'] <= s_end)]
            if not sliced.empty:
                tdiff = sliced.iloc[-1]['Sekunden'] - sliced.iloc[0]['Sekunden']
                rate = (sliced.iloc[-1]['Druck_mbar'] - sliced.iloc[0]['Druck_mbar']) / tdiff if tdiff > 0 else 0
                self.lbl_stats.config(text=f"Schnitt: {sliced['Druck_mbar'].mean():.2f} mbar\nMin: {sliced['Druck_mbar'].min():.2f} mbar\nMax: {sliced['Druck_mbar'].max():.2f} mbar\nσ: ±{sliced['Druck_mbar'].std():.2f} mbar\nRate: {rate:.2f} mbar/s")
            self.update_plot()
        except ValueError: messagebox.showerror("Fehler", "Bitte gültige Zahlen eingeben.")

    def clear_slice(self):
        self.slice_start = self.slice_end = None
        self.ent_start.delete(0, tb.END)
        self.ent_end.delete(0, tb.END)
        self.lbl_stats.config(text="Kein Bereich gewählt.")
        self.update_plot()

    def find_threshold(self):
        if not self.datasets or self.is_measuring: return
        try:
            self.threshold_val = float(self.ent_thresh.get().replace(',', '.'))
            self.update_plot()
        except ValueError: messagebox.showerror("Fehler", "Gültige Zahl einfügen.")

    def clear_threshold(self):
        self.threshold_val = None
        self.ent_thresh.delete(0, tb.END)
        self.lbl_thresh_res.config(text="")
        self.update_plot()

    def export_png(self):
            if not self.datasets or self.is_measuring: return
            fp = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")])
            if fp: self.fig.savefig(fp, dpi=300, bbox_inches='tight', facecolor=self.fig.get_facecolor()); self.logger.info(f"Graph gespeichert: {fp}")

    def export_notes(self):
        note = self.text_notes.get("1.0", tb.END).strip()
        if not note: 
            return messagebox.showwarning("Fehler", "Das Notizfeld ist leer.")
            
        fp = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Textdatei", "*.txt")])
        if fp:
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(note)
            self.logger.info(f"Notizen gespeichert: {fp}")
            messagebox.showinfo("Erfolg", "Notizen wurden als Textdatei gespeichert.")

    def export_csv(self):
        if not self.datasets: 
            return messagebox.showwarning("Fehler", "Es ist keine Messung geladen.")
        if self.slice_start is None or self.slice_end is None: 
            return messagebox.showwarning("Fehler", "Bitte markiere zuerst einen Bereich im Graphen (Maus ziehen).")
        if self.is_measuring: 
            return messagebox.showwarning("Fehler", "Bitte warte, bis die laufende Messung beendet ist.")

        fp = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV File", "*.csv")])
        if not fp: 
            return 
            
        try:
            _, df = self.datasets[-1] 
            df_export = df[(df['Sekunden'] >= self.slice_start) & (df['Sekunden'] <= self.slice_end)].copy()
            
            if df_export.empty: 
                return messagebox.showwarning("Fehler", "Der markierte Bereich enthält keine Daten!")
            
            start_time = df_export['Sekunden'].iloc[0]
            df_export['Sekunden'] = df_export['Sekunden'] - start_time
            
            if 'Index' in df_export.columns:
                df_export['Index'] = range(1, len(df_export) + 1)
            
            note = self.text_notes.get("1.0", tb.END).strip()
            
            with open(fp, 'w', encoding='utf-8', newline='') as f:
                if note:
                    for line in note.split('\n'): 
                        f.write(f"# {line}\n")
                df_export.to_csv(f, sep=';', index=False)
                
            self.logger.info(f"CSV erfolgreich exportiert: {fp}")
            messagebox.showinfo("Export", "Die CSV-Datei wurde gespeichert!\nZeit startet bei 0s, Index beginnt bei 1.")
            
        except Exception as e: 
            self.logger.error(f"Export fehlgeschlagen: {e}")
            messagebox.showerror("Export-Fehler", f"Konnte CSV nicht speichern:\n{e}")

if __name__ == "__main__":
    try:
        import ttkbootstrap as tb
        # Modernes dunkles Theme anwenden (Alternativen: 'superhero', 'cyborg', 'cosmo')
        root = tb.Window(themename="darkly")
        app = SensorDashboard(root)
        root.mainloop()
    except Exception as e:
        import traceback
        import webbrowser
        import tkinter as tk
        from tkinter import messagebox
        import os
        
        emergency_root = tk.Tk()
        emergency_root.withdraw() 
        
        error_msg = str(e)
        ans = messagebox.askyesno(
            "Kritischer Absturz", 
            f"Das Programm ist leider beim Start abgestürzt:\n\n{error_msg}\n\nMöchtest du die GitHub-Seite öffnen, um das neueste Notfall-Update manuell herunterzuladen?"
        )
        
        if ans:
            webbrowser.open("https://github.com/Justus2004/Bernardograph/releases/latest")
        os._exit(1)