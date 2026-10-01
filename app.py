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
import math
from logging.handlers import RotatingFileHandler
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.widgets import SpanSelector

from config import APP_VERSION, MAX_LIVE_POINTS
from data_processor import DataProcessor
from bluetooth_handler import BluetoothHandler
from updater import AppUpdater
from plot_events import PlotEventManager

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
        self.root.minsize(900, 600)
        
        # App maximiert im Vollbild starten
        try:
            self.root.state('zoomed')
        except tk.TclError:
            try: self.root.attributes('-zoomed', True)
            except: pass
        
        self.msg_queue = queue.Queue()
        self.setup_logging()
        
        self.processor = DataProcessor()
        self.ble_handler = BluetoothHandler(self.msg_queue, self.processor)
        
        self.blink_id = None
        self.blink_state = False
        self.updater = AppUpdater(self.root, self.update_callback)
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
        self.apply_theme_colors()
        self.root.after(100, self.process_queue)
        self.logger.info("Bereit. Starte automatische Bluetooth-Verbindung...\nTipp: Halte 'x' oder 'y' beim Scrollen für gezielten Zoom!")
        
        self.root.after(500, self.start_connection)
        self.root.after(2000, self.updater.check_for_updates) 
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_logging(self):
        self.logger = logging.getLogger("SensorApp")
        self.logger.setLevel(logging.DEBUG)
        
        fh = RotatingFileHandler("app.log", maxBytes=1024*1024, backupCount=3)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
        self.logger.addHandler(fh)
        
        qh = QueueLoggingHandler(self.msg_queue)
        qh.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        qh.setLevel(logging.INFO)
        self.logger.addHandler(qh)

    def update_callback(self, state, data):
        if state == "AVAILABLE":
            ans = messagebox.askyesno("Update gefunden!", f"Eine neue Version (v{data}) ist verfügbar!\n\nMöchtest du das Update jetzt herunterladen?")
            if ans:
                self.updater.start_download()
        elif state == "DOWNLOADING":
            self.stop_blinking()
            self.btn_version.config(text=f"DL: {data}%", bootstyle=INFO)
        elif state == "READY":
            self.btn_version.config(text=f"Install v{data}", bootstyle=SUCCESS)
            ans = messagebox.askyesno("Download abgeschlossen", f"Update v{data} ist bereit!\n\nJetzt installieren und die App neustarten?")
            if ans:
                self.updater.install_update()
            else:
                self.start_blinking()
        elif state == "ERROR":
            self.stop_blinking()
            self.btn_version.config(text=f"v{APP_VERSION}", bootstyle=SECONDARY)
            messagebox.showerror("Update Fehler", f"Download fehlgeschlagen:\n{data}")

    def start_blinking(self, step=0, direction=1):
        if self.blink_id and step == 0:
            self.root.after_cancel(self.blink_id)
            
        if not hasattr(self, 'custom_style'):
            self.custom_style = tb.Style()
        
        # Farbverlauf von dunklem zu leuchtendem Grün
        greens = ["#1b4f26", "#236b33", "#2a8740", "#32a34d", "#39bf5a", "#45d468", "#59e379"]
        
        if step >= len(greens) - 1:
            direction = -1
        elif step <= 0:
            direction = 1
            
        current_color = greens[step]
        # Custom Style anwenden (überschreibt temporär das Standard-Theme)
        self.custom_style.configure("Pulsing.TButton", background=current_color, bordercolor=current_color, foreground="white")
        self.btn_version.config(style="Pulsing.TButton")
        
        self.blink_id = self.root.after(120, lambda: self.start_blinking(step + direction, direction))

    def stop_blinking(self):
        if self.blink_id:
            self.root.after_cancel(self.blink_id)
            self.blink_id = None
        # Style zurücksetzen und originalen Bootstyle wiederherstellen
        self.btn_version.config(style="TButton", bootstyle=SECONDARY)

    def handle_version_click(self):
        # Wenn geklickt wird und ein fertiges Update wartet -> Installieren
        if self.updater.downloaded_version == self.updater.latest_version and self.updater.latest_version:
            ans = messagebox.askyesno("Update bereit", f"Update v{self.updater.latest_version} ist bereits heruntergeladen.\nJetzt installieren?")
            if ans:
                self.updater.install_update()
        else:
            self.updater.check_for_updates(manual=True)

    def on_closing(self):
        print("Beende Programm...")
        try:
            if self.is_measuring and self.processor: self.processor.close_session()
        except: pass 
        self.root.destroy()
        os._exit(0) 

    def setup_ui(self):
        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=4)
        main_paned.pack(fill=BOTH, expand=True)

        left_frame = tb.Frame(main_paned)
        
        left_frame.rowconfigure(0, weight=0) 
        left_frame.rowconfigure(1, weight=1) 
        left_frame.rowconfigure(2, weight=0) 
        left_frame.columnconfigure(0, weight=1)
        
        main_paned.add(left_frame, stretch="always")

        # 1. BAR OBEN
        top_frame = tb.Frame(left_frame, padding=5)
        top_frame.grid(row=0, column=0, sticky="ew")
        
        self.btn_version = tb.Button(top_frame, text=f"v{APP_VERSION}", bootstyle=SECONDARY, command=self.handle_version_click)
        self.btn_version.pack(side=LEFT, padx=10)

        self.btn_load = tb.Button(top_frame, text="CSV laden", command=lambda: self.load_csv(append=False), bootstyle=SUCCESS)
        self.btn_load.pack(side=LEFT, padx=3)

        self.btn_add = tb.Button(top_frame, text="+ CSV hinzufügen", command=lambda: self.load_csv(append=True), bootstyle=(SUCCESS, OUTLINE))
        self.btn_add.pack(side=LEFT, padx=3)
        
        self.btn_reset = tb.Button(top_frame, text="Reset Ansicht", command=self.reset_view, bootstyle=SECONDARY)
        self.btn_reset.pack(side=LEFT, padx=3)
        
        self.lbl_status = tb.Label(top_frame, text="🔴 Getrennt", font=("Arial", 10, "bold"), bootstyle=DANGER)
        self.lbl_status.pack(side=LEFT, padx=10)
        
        self.lbl_countdown = tb.Label(top_frame, text="", font=("Arial", 10, "bold"), bootstyle=WARNING)
        self.lbl_countdown.pack(side=LEFT, padx=10)

        # 2. DIAGRAMM MITTE
        plot_frame = tb.Frame(left_frame)
        plot_frame.grid(row=1, column=0, sticky="nsew")
        
        self.fig, self.ax = plt.subplots()
        self.fig.subplots_adjust(left=0.08, right=0.97, top=0.93, bottom=0.12)
        
        self.ax.set_title("Messdaten & Live-Analyse")
        self.ax.set_xlabel("Zeit (Sekunden)")
        self.ax.set_ylabel("Druck (mbar)")
        
        self.ax.set_xlim(0, 10)
        self.ax.set_ylim(0, 105)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=BOTH, expand=True)
        
        self.span = SpanSelector(self.ax, self.on_span_select, 'horizontal', useblit=True, props=dict(alpha=0.25, facecolor='cyan'), interactive=False)

        self.canvas.mpl_connect('scroll_event', self.plot_events.on_zoom)
        self.canvas.mpl_connect('button_press_event', self.plot_events.on_press)
        self.canvas.mpl_connect('button_release_event', self.plot_events.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.plot_events.on_motion)
        self.canvas.mpl_connect('key_press_event', self.plot_events.on_key_press)
        self.canvas.mpl_connect('key_release_event', self.plot_events.on_key_release)
        
        # 3. LOGBUCH UNTEN
        log_frame = tb.Frame(left_frame)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        
        self.log_text = ScrolledText(log_frame, height=6, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)

        # RECHTE SEITE (Tools)
        right_frame = tb.Frame(main_paned, padding=10)
        main_paned.add(right_frame, stretch="never")
        
        tb.Label(right_frame, text="Analyse Werkzeuge", font=("Arial", 14, "bold")).pack(pady=(0, 10))

        # ACHSEN-SKALIERUNG
        lf_axis = tb.LabelFrame(right_frame, text="Achsen Skalierung (Max)", padding=8)
        lf_axis.pack(fill=X, pady=4)
        frame_axis_inputs = tb.Frame(lf_axis)
        frame_axis_inputs.pack(fill=X)
        
        tb.Label(frame_axis_inputs, text="X (s):").grid(row=0, column=0, padx=2)
        self.ent_xmax = tb.Entry(frame_axis_inputs, width=6)
        self.ent_xmax.insert(0, "Auto")
        self.ent_xmax.grid(row=0, column=1, padx=2)
        self.ent_xmax.bind("<Return>", lambda _: self.update_plot(preserve_limits=False))

        tb.Label(frame_axis_inputs, text="Y (mbar):").grid(row=0, column=2, padx=2)
        self.ent_ymax = tb.Entry(frame_axis_inputs, width=6)
        self.ent_ymax.insert(0, "105")
        self.ent_ymax.grid(row=0, column=3, padx=2)
        self.ent_ymax.bind("<Return>", lambda _: self.update_plot(preserve_limits=False))

        tb.Button(frame_axis_inputs, text="OK", command=lambda: self.update_plot(preserve_limits=False), bootstyle=INFO).grid(row=0, column=4, padx=5)

        # 1. Signal-Glättung
        lf_smooth = tb.LabelFrame(right_frame, text="1. Signal-Glättung", padding=8)
        lf_smooth.pack(fill=X, pady=4)
        
        frame_smooth_top = tb.Frame(lf_smooth)
        frame_smooth_top.pack(fill=X)
        tb.Label(frame_smooth_top, text="Fenstergröße:").pack(side=LEFT)
        self.lbl_smooth_val = tb.Label(frame_smooth_top, text="1 Werte", font=("Arial", 9, "bold"))
        self.lbl_smooth_val.pack(side=RIGHT)
        
        self.smooth_var = tb.IntVar(value=1)
        tb.Scale(lf_smooth, from_=1, to=100, orient=HORIZONTAL, variable=self.smooth_var, command=self.on_smooth_change).pack(fill=X, pady=(2,0))

        # 2. Peaks
        lf_peaks = tb.LabelFrame(right_frame, text="2. Automatische Peaks", padding=8)
        lf_peaks.pack(fill=X, pady=4)
        self.chk_peaks_var = tb.BooleanVar(value=True)
        tb.Checkbutton(lf_peaks, text="Min/Max Marker anzeigen", variable=self.chk_peaks_var, command=self.update_plot, bootstyle="round-toggle").pack(anchor="w")

        # 3. Zeitraum
        lf_time = tb.LabelFrame(right_frame, text="3. Zeitraum-Analyse (Maus ziehen!)", padding=8)
        lf_time.pack(fill=X, pady=4)
        frame_time_inputs = tb.Frame(lf_time)
        frame_time_inputs.pack(fill=X)
        tb.Label(frame_time_inputs, text="Von:").grid(row=0, column=0, padx=2)
        self.ent_start = tb.Entry(frame_time_inputs, width=6)
        self.ent_start.grid(row=0, column=1, padx=2)
        tb.Label(frame_time_inputs, text="Bis:").grid(row=0, column=2, padx=2)
        self.ent_end = tb.Entry(frame_time_inputs, width=6)
        self.ent_end.grid(row=0, column=3, padx=2)
        tb.Button(frame_time_inputs, text="Prüfen", command=self.analyze_slice, bootstyle=INFO).grid(row=0, column=4, padx=2)
        tb.Button(frame_time_inputs, text="X", command=self.clear_slice, bootstyle=DANGER).grid(row=0, column=5)
        
        self.default_stats = "Schnitt: -- mbar\nMin: -- mbar\nMax: -- mbar\nσ: ±-- mbar\nRate: -- mbar/s"
        self.lbl_stats = tb.Label(lf_time, text=self.default_stats, justify=LEFT, font=("Consolas", 8))
        self.lbl_stats.pack(anchor="w", pady=2)

        # 4. Schwelle
        lf_thresh = tb.LabelFrame(right_frame, text="4. Schwellenwert finden", padding=8)
        lf_thresh.pack(fill=X, pady=4)
        frame_thresh_inputs = tb.Frame(lf_thresh)
        frame_thresh_inputs.pack(fill=X)
        tb.Label(frame_thresh_inputs, text="Ziel (mbar):").pack(side=LEFT, padx=2)
        self.ent_thresh = tb.Entry(frame_thresh_inputs, width=8)
        self.ent_thresh.pack(side=LEFT, padx=2)
        tb.Button(frame_thresh_inputs, text="Suchen", command=self.find_threshold, bootstyle=INFO).pack(side=LEFT, padx=2)
        tb.Button(frame_thresh_inputs, text="X", command=self.clear_threshold, bootstyle=DANGER).pack(side=LEFT)
        self.lbl_thresh_res = tb.Label(lf_thresh, text="", font=("Consolas", 8))
        self.lbl_thresh_res.pack(anchor="w", pady=2)
        
        # 5. Export
        lf_export = tb.LabelFrame(right_frame, text="5. Dokumentation & Export", padding=8)
        lf_export.pack(fill=X, pady=4)
        tb.Label(lf_export, text="Notizen / Bemerkungen:").pack(anchor="w")
        self.text_notes = tb.Text(lf_export, height=2, width=30, font=("Arial", 9))
        self.text_notes.pack(fill=X, pady=2)
        
        tb.Button(lf_export, text="Notizen speichern", command=self.export_notes, bootstyle=(PRIMARY, OUTLINE)).pack(fill=X, pady=1)
        tb.Button(lf_export, text="Ansicht als PNG", command=self.export_png, bootstyle=(PRIMARY, OUTLINE)).pack(fill=X, pady=1)
        tb.Button(lf_export, text="Bereich als CSV", command=self.export_csv, bootstyle=(PRIMARY, OUTLINE)).pack(fill=X, pady=1)

    def on_smooth_change(self, _):
        val = self.smooth_var.get()
        self.lbl_smooth_val.config(text=f"{val} Werte")
        self.update_plot()

    def apply_theme_colors(self):
        self.fig.patch.set_facecolor('#ffffff')
        self.ax.set_facecolor('#f8f9fa')
        self.ax.tick_params(colors='black')
        self.ax.xaxis.label.set_color('black')
        self.ax.yaxis.label.set_color('black')
        self.ax.title.set_color('black')
        
        self.log_text.config(
            bg="#f0f0f0",
            fg="black",
            insertbackground="black"
        )
        self.canvas.draw_idle()

    def on_span_select(self, xmin, xmax):
        if len(self.datasets) > 1:
            messagebox.showwarning("Achtung", "Die Zeitraum-Analyse ist nur bei einem einzelnen Datensatz möglich.")
            return

        # Ignoriere einfache Klicks (ohne Ziehen)
        if xmin == xmax:
            self.clear_slice()
            return

        # Automatisch umdrehen, falls von rechts nach links gezogen wurde
        if xmin > xmax:
            xmin, xmax = xmax, xmin
            
        self.ent_start.delete(0, tk.END)
        self.ent_start.insert(0, f"{xmin:.3f}")
        self.ent_end.delete(0, tk.END)
        self.ent_end.insert(0, f"{xmax:.3f}")
        self.analyze_slice()

    def reset_view(self):
        if not self.datasets and not self.is_measuring: return
        self.ent_xmax.delete(0, tk.END)
        self.ent_xmax.insert(0, "Auto")
        self.ent_ymax.delete(0, tk.END)
        self.ent_ymax.insert(0, "105")
        self.update_plot(preserve_limits=False)

    def process_queue(self):
        while not self.msg_queue.empty():
            msg_type, data = self.msg_queue.get()
            if msg_type == "LOG":
                self.log_text.insert(tk.END, data + "\n")
                self.log_text.see(tk.END)
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
        self.ble_handler.start()

    def start_live_plot(self, seconds):
        self.is_measuring = True
        self.countdown = seconds
        self.live_x, self.live_y, self.live_index = [], [], 0
        self.datasets = [] 
        self.ax.clear()
        self.apply_theme_colors()
        self.ax.grid(True, linestyle='--', alpha=0.3)
        
        try: ymax = float(self.ent_ymax.get().replace(',', '.'))
        except: ymax = 105
        
        self.ax.set_title("Messdaten & Live-Analyse", color='black')
        
        if seconds == 0:
            self.lbl_countdown.config(text="⏳ Dauermessung läuft...", bootstyle=WARNING)
            self.ax.set_xlim(0, 10) 
        else:
            self.lbl_countdown.config(text=f"⏳ {self.countdown} s verbleiben", bootstyle=WARNING)
            self.ax.set_xlim(0, seconds)
            
        self.ax.set_xlabel("Zeit (Sekunden seit Start)")
        self.ax.set_ylabel("Druck (mbar)")
        self.ax.set_ylim(0, ymax)
        
        line_color = '#0078D7'
        self.live_line, = self.ax.plot([], [], color=line_color, linewidth=1.5)
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
                self.text_notes.delete("1.0", tk.END)
                self.ent_ymax.delete(0, tk.END)
                self.ent_ymax.insert(0, "105")
                self.ent_xmax.delete(0, tk.END)
                self.ent_xmax.insert(0, "Auto")
                self.clear_slice()
                self.clear_threshold()
                self.smooth_var.set(1)
                self.lbl_smooth_val.config(text="1 Werte")
            else:
                self.clear_slice()
                
            self.current_filepath = filepath
            try:
                self.logger.info(f"Lade Daten: {os.path.basename(filepath)}")
                
                # CSV einlesen und nach Notizen suchen
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    
                notes_lines = []
                for line in lines:
                    if line.startswith('#'):
                        clean_line = line.lstrip('#').strip()
                        # Meta-Tags für Achsen abfangen
                        if clean_line.startswith('XMAX:'):
                            val = clean_line.split('XMAX:')[1].strip()
                            self.ent_xmax.delete(0, tk.END)
                            self.ent_xmax.insert(0, val)
                        elif clean_line.startswith('YMAX:'):
                            val = clean_line.split('YMAX:')[1].strip()
                            self.ent_ymax.delete(0, tk.END)
                            self.ent_ymax.insert(0, val)
                        else:
                            # Echte Notizen behalten (entfernt führendes Leerzeichen falls vorhanden)
                            notes_lines.append(clean_line[1:] if clean_line.startswith(' ') else clean_line)
                
                # Nur die echten Notizen anzeigen
                if not append and notes_lines:
                    self.text_notes.insert(tk.END, '\n'.join(notes_lines))
                    
                skip = len([line for line in lines if line.startswith('#')])
                        
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
                self.update_plot(preserve_limits=False)
            except Exception as e:
                self.logger.error(f"Fehler beim Laden: {e}")
                messagebox.showerror("Ladefehler", f"Fehler: {e}")
                
    def update_plot(self, preserve_limits=True):
        if not self.datasets or self.is_measuring: return
        
        # 1. Aktuellen Zoom speichern
        old_xlim = self.ax.get_xlim() if preserve_limits else None
        old_ylim = self.ax.get_ylim() if preserve_limits else None

        window = self.smooth_var.get()
        self.ax.clear()
        self.apply_theme_colors()
        self.ax.grid(True, linestyle='--', alpha=0.3)
        
        text_color = 'black'
        bbox_bg = '#ffffff'

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
                
                max_x, max_y = df.loc[idx_max, 'Sekunden'], df.loc[idx_max, 'Druck_mbar']
                min_x, min_y = df.loc[idx_min, 'Sekunden'], df.loc[idx_min, 'Druck_mbar']
                
                self.ax.plot(max_x, max_y, marker='o', markersize=8, markerfacecolor='#FFD700', markeredgecolor='#D32F2F', markeredgewidth=1.5, zorder=5)
                self.ax.annotate(f"MAX: {max_y:.1f} mbar\n({max_x:.2f} s)", xy=(max_x, max_y), xytext=(0, 12), textcoords="offset points", ha='center', fontsize=8, fontweight='bold', color=text_color, bbox=dict(boxstyle="round,pad=0.2", fc=bbox_bg, ec='#FFD700', alpha=0.85))
                
                self.ax.plot(min_x, min_y, marker='D', markersize=7, markerfacecolor='#00FFFF', markeredgecolor='black', markeredgewidth=1.2, zorder=5)
                self.ax.annotate(f"MIN: {min_y:.1f} mbar\n({min_x:.2f} s)", xy=(min_x, min_y), xytext=(0, -22), textcoords="offset points", ha='center', fontsize=8, fontweight='bold', color=text_color, bbox=dict(boxstyle="round,pad=0.2", fc=bbox_bg, ec='#00FFFF', alpha=0.85))

            if self.threshold_val is not None:
                cross_df = df[df['Druck_mbar'] >= self.threshold_val]
                if not cross_df.empty:
                    ct, cv = cross_df.iloc[0]['Sekunden'], cross_df.iloc[0]['Druck_mbar']
                    self.ax.plot(ct, cv, marker='X', color='#FF9800', markersize=10, zorder=6)
                    self.lbl_thresh_res.config(text=f"Schwelle erreicht:\nZeit: {ct:.3f} s\nWert: {cv:.2f} mbar")

        try:
            xmax_str = self.ent_xmax.get().strip().replace(',', '.')
            if xmax_str.lower() in ["auto", ""]: 
                xmax = math.ceil(max_time) if max_time > 0 else 10
                self.ent_xmax.delete(0, tk.END)
                self.ent_xmax.insert(0, str(xmax))
            else: 
                xmax = float(xmax_str)
        except:
            xmax = math.ceil(max_time) if max_time > 0 else 10
            self.ent_xmax.delete(0, tk.END)
            self.ent_xmax.insert(0, str(xmax))

        if len(self.datasets) >= 1:
            legend = self.ax.legend(loc="upper right", fontsize=8)
            plt.setp(legend.get_texts(), color=text_color)
            
        if self.slice_start is not None and self.slice_end is not None:
            span_color = '#0078D7'
            self.ax.axvspan(self.slice_start, self.slice_end, color=span_color, alpha=0.18)
            self.ax.axvline(self.slice_start, color=span_color, linestyle='--')
            self.ax.axvline(self.slice_end, color=span_color, linestyle='--')
        if self.threshold_val is not None: self.ax.axhline(self.threshold_val, color='#FF9800', linestyle='--', linewidth=1.5)

        self.ax.set_title("Messdaten & Live-Analyse", color=text_color)
        self.ax.set_xlabel("Zeit (Sekunden)")
        self.ax.set_ylabel("Druck (mbar)")
        
        # 2. Achsen wiederherstellen (oder neue setzen, falls gewünscht)
        if preserve_limits and old_xlim and old_ylim and old_xlim != (0.0, 1.0):
            self.ax.set_xlim(old_xlim)
            self.ax.set_ylim(old_ylim)
        else:
            self.ax.set_xlim(left=0, right=xmax)
            self.ax.set_ylim(bottom=0, top=ymax)
        
        self.annot = self.ax.annotate("", xy=(0,0), xytext=(15,15), textcoords="offset points", bbox=dict(boxstyle="round,pad=0.3", fc=bbox_bg, ec=text_color, alpha=0.9), arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0", color=text_color))
        self.annot.get_bbox_patch().set_alpha(0.9)
        self.annot.set_color(text_color)
        self.annot.set_visible(False)
        self.canvas.draw_idle()

    def analyze_slice(self):
        if not self.datasets or self.is_measuring: return
        if len(self.datasets) > 1: return
        try:
            s_start = float(self.ent_start.get().replace(',', '.'))
            s_end = float(self.ent_end.get().replace(',', '.'))
            
            # Bei exakt gleichen Werten Analyse abbrechen
            if s_start == s_end: 
                self.clear_slice()
                return
                
            # Wenn Start größer als Ende, Zahlen einfach tauschen statt Fehler zu werfen
            if s_start > s_end:
                s_start, s_end = s_end, s_start
                self.ent_start.delete(0, tk.END)
                self.ent_start.insert(0, f"{s_start:.3f}")
                self.ent_end.delete(0, tk.END)
                self.ent_end.insert(0, f"{s_end:.3f}")
                
            self.slice_start, self.slice_end = s_start, s_end
            _, raw_df = self.datasets[-1] 
            df = raw_df.copy()
            if self.smooth_var.get() > 1: df['Druck_mbar'] = df['Druck_mbar'].rolling(window=self.smooth_var.get(), center=True).mean()
                
            sliced = df[(df['Sekunden'] >= s_start) & (df['Sekunden'] <= s_end)]
            if not sliced.empty:
                tdiff = sliced.iloc[-1]['Sekunden'] - sliced.iloc[0]['Sekunden']
                rate = (sliced.iloc[-1]['Druck_mbar'] - sliced.iloc[0]['Druck_mbar']) / tdiff if tdiff > 0 else 0
                self.lbl_stats.config(text=f"Schnitt: {sliced['Druck_mbar'].mean():.2f} mbar\nMin: {sliced['Druck_mbar'].min():.2f} mbar\nMax: {sliced['Druck_mbar'].max():.2f} mbar\nσ: ±{sliced['Druck_mbar'].std():.2f} mbar\nRate: {rate:.2f} mbar/s")
            
            # Wichtig: preserve_limits=True nutzen, damit man nach dem Markieren im Zoom bleibt
            self.update_plot(preserve_limits=True)
        except ValueError: 
            messagebox.showerror("Fehler", "Bitte gültige Zahlen eingeben.")

    def clear_slice(self):
        self.slice_start = self.slice_end = None
        self.ent_start.delete(0, tk.END)
        self.ent_end.delete(0, tk.END)
        self.lbl_stats.config(text=self.default_stats)
        
        if hasattr(self, 'span') and self.span:
            self.span.extents = (0, 0)
            try: self.span.set_visible(False)
            except: pass
            
        self.update_plot()

    def find_threshold(self):
        if not self.datasets or self.is_measuring: return
        try:
            self.threshold_val = float(self.ent_thresh.get().replace(',', '.'))
            self.update_plot()
        except ValueError: messagebox.showerror("Fehler", "Gültige Zahl einfügen.")

    def clear_threshold(self):
        self.threshold_val = None
        self.ent_thresh.delete(0, tk.END)
        self.lbl_thresh_res.config(text="")
        self.update_plot()

    def export_png(self):
            if not self.datasets or self.is_measuring: return
            fp = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")])
            if fp: self.fig.savefig(fp, dpi=300, bbox_inches='tight', facecolor=self.fig.get_facecolor()); self.logger.info(f"Graph gespeichert: {fp}")

    def export_notes(self):
        if not self.current_filepath or not os.path.exists(self.current_filepath):
            return messagebox.showwarning("Fehler", "Es ist keine Messung geladen, zu der Notizen gespeichert werden könnten.")
            
        note = self.text_notes.get("1.0", tk.END).strip()
        
        try:
            # 1. Alte Datei komplett einlesen
            with open(self.current_filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 2. Alte Notizen (alles mit # am Anfang) entfernen, um nur die reinen Daten zu behalten
            data_lines = [line for line in lines if not line.startswith('#')]
            
            # 3. Datei neu schreiben: Meta-Daten, Notizen, dann Rohdaten
            with open(self.current_filepath, 'w', encoding='utf-8') as f:
                # Achsenwerte speichern
                f.write(f"# XMAX:{self.ent_xmax.get().strip()}\n")
                f.write(f"# YMAX:{self.ent_ymax.get().strip()}\n")
                
                # Sichtbare Notizen speichern
                if note:
                    for line in note.split('\n'):
                        f.write(f"# {line}\n")
                f.writelines(data_lines)
                
            self.logger.info(f"Notizen in CSV aktualisiert: {self.current_filepath}")
            messagebox.showinfo("Erfolg", f"Notizen wurden direkt in der CSV-Datei gespeichert!\n({os.path.basename(self.current_filepath)})")
            
        except Exception as e:
            self.logger.error(f"Fehler beim Speichern der Notizen in die CSV: {e}")
            messagebox.showerror("Fehler", f"Konnte Notizen nicht in CSV speichern:\n{e}")

    def export_csv(self):
        if not self.datasets: 
            return messagebox.showwarning("Fehler", "Es ist keine Messung geladen.")
        if len(self.datasets) > 1: 
            return messagebox.showwarning("Fehler", "CSV Export der Analyse ist nur für einen einzelnen Datensatz möglich.")
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
            
            note = self.text_notes.get("1.0", tk.END).strip()
            
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
        root = tb.Window(themename="flatly")
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