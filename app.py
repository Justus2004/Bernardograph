import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, ttk
import queue
import pandas as pd
import matplotlib.pyplot as plt
import os
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.widgets import SpanSelector

from config import APP_VERSION
from data_processor import DataProcessor
from bluetooth_handler import BluetoothHandler
from updater import AppUpdater
from plot_events import PlotEventManager

class SensorDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Drucksensor Dashboard & Analyse")
        self.root.geometry("1450x850")
        
        self.msg_queue = queue.Queue()
        self.processor = DataProcessor()
        self.ble_handler = BluetoothHandler(self.msg_queue, self.processor)
        
        # --- Modulare Helfer initialisieren ---
        self.updater = AppUpdater(self.root, self.log)
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
        self.log("Bereit. Starte automatische Bluetooth-Verbindung...\nTipp: Halte 'x' oder 'y' beim Scrollen für gezielten Zoom!")
        
        self.root.after(500, self.start_connection)
        self.root.after(2000, self.updater.check_for_updates) 
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        print("Beende Programm hart...")
        try:
            if self.is_measuring and self.processor: self.processor.close_session()
        except: pass 
        self.root.destroy()
        os._exit(0) 

    def setup_ui(self):
        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(main_paned)
        main_paned.add(left_frame, minsize=800)
        
        top_frame = tk.Frame(left_frame, pady=10)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10)
        
        self.btn_connect = tk.Button(top_frame, text="Bluetooth Start", command=self.start_connection, bg="#0078D7", fg="white", font=("Arial", 10, "bold"))
        self.btn_connect.pack(side=tk.LEFT, padx=5)

        self.btn_update = tk.Button(top_frame, text=f"v{APP_VERSION} (Update Info)", command=lambda: self.updater.check_for_updates(manual=True), bg="#9C27B0", fg="white", font=("Arial", 10, "bold"))
        self.btn_update.pack(side=tk.RIGHT, padx=5)
        
        self.btn_load = tk.Button(top_frame, text="CSV laden (Neu)", command=lambda: self.load_csv(append=False), bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
        self.btn_load.pack(side=tk.LEFT, padx=5)

        self.btn_add = tk.Button(top_frame, text="+ CSV hinzufügen", command=lambda: self.load_csv(append=True), bg="#8BC34A", fg="white", font=("Arial", 10, "bold"))
        self.btn_add.pack(side=tk.LEFT, padx=5)
        
        self.btn_reset = tk.Button(top_frame, text="Reset Ansicht", command=self.reset_view, bg="#607D8B", fg="white", font=("Arial", 10, "bold"))
        self.btn_reset.pack(side=tk.LEFT, padx=5)
        
        tk.Label(top_frame, text="Y-Max:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=(15, 2))
        self.ent_ymax = tk.Entry(top_frame, width=5, font=("Arial", 10))
        self.ent_ymax.insert(0, "105")
        self.ent_ymax.pack(side=tk.LEFT, padx=2)
        self.ent_ymax.bind("<Return>", lambda _: self.update_plot())
        
        self.lbl_status = tk.Label(top_frame, text="🔴 Getrennt", font=("Arial", 10, "bold"), fg="#D32F2F")
        self.lbl_status.pack(side=tk.LEFT, padx=15)
        
        self.lbl_countdown = tk.Label(top_frame, text="", font=("Arial", 10, "bold"), fg="#FFA500")
        self.lbl_countdown.pack(side=tk.LEFT, padx=15)
        
        self.fig, self.ax = plt.subplots(figsize=(10, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=left_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.span = SpanSelector(self.ax, self.on_span_select, 'horizontal', useblit=True, props=dict(alpha=0.15, facecolor='blue'), interactive=True)
        
        # --- Events an die externe Plot-Klasse übergeben ---
        self.canvas.mpl_connect('scroll_event', self.plot_events.on_zoom)
        self.canvas.mpl_connect('button_press_event', self.plot_events.on_press)
        self.canvas.mpl_connect('button_release_event', self.plot_events.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.plot_events.on_motion)
        self.canvas.mpl_connect('key_press_event', self.plot_events.on_key_press)
        self.canvas.mpl_connect('key_release_event', self.plot_events.on_key_release)
        
        self.log_text = scrolledtext.ScrolledText(left_frame, height=6, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.log_text.pack(side=tk.BOTTOM, padx=10, pady=5, fill=tk.X)

        right_frame = tk.Frame(main_paned, width=380, bg="#f0f0f0", padx=10, pady=10)
        main_paned.add(right_frame, minsize=350)
        
        lbl_title = tk.Label(right_frame, text="Analyse Werkzeuge", font=("Arial", 14, "bold"), bg="#f0f0f0")
        lbl_title.pack(pady=(0, 10))

        lf_smooth = tk.LabelFrame(right_frame, text="1. Signal-Glättung", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_smooth.pack(fill=tk.X, pady=5)
        self.smooth_var = tk.IntVar(value=1)
        tk.Scale(lf_smooth, from_=1, to=100, orient=tk.HORIZONTAL, variable=self.smooth_var, command=lambda _: self.update_plot(), bg="#f0f0f0", label="Fenstergröße (Werte)").pack(fill=tk.X)

        lf_peaks = tk.LabelFrame(right_frame, text="2. Automatische Peaks", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_peaks.pack(fill=tk.X, pady=5)
        self.chk_peaks_var = tk.BooleanVar(value=True)
        tk.Checkbutton(lf_peaks, text="Min/Max Marker anzeigen", variable=self.chk_peaks_var, command=self.update_plot, bg="#f0f0f0").pack(anchor="w")

        lf_time = tk.LabelFrame(right_frame, text="3. Zeitraum-Analyse (Maus ziehen!)", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_time.pack(fill=tk.X, pady=5)
        frame_time_inputs = tk.Frame(lf_time, bg="#f0f0f0")
        frame_time_inputs.pack(fill=tk.X)
        tk.Label(frame_time_inputs, text="Von:", bg="#f0f0f0").grid(row=0, column=0, padx=2)
        self.ent_start = tk.Entry(frame_time_inputs, width=6)
        self.ent_start.grid(row=0, column=1, padx=2)
        tk.Label(frame_time_inputs, text="Bis:", bg="#f0f0f0").grid(row=0, column=2, padx=2)
        self.ent_end = tk.Entry(frame_time_inputs, width=6)
        self.ent_end.grid(row=0, column=3, padx=2)
        tk.Button(frame_time_inputs, text="Prüfen", command=self.analyze_slice).grid(row=0, column=4, padx=5)
        tk.Button(frame_time_inputs, text="X", command=self.clear_slice, fg="red").grid(row=0, column=5)
        self.lbl_stats = tk.Label(lf_time, text="Kein Bereich gewählt.", justify=tk.LEFT, bg="#f0f0f0", font=("Consolas", 9))
        self.lbl_stats.pack(anchor="w", pady=5)

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
        
        lf_export = tk.LabelFrame(right_frame, text="5. Dokumentation & Export", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_export.pack(fill=tk.X, pady=5)
        tk.Label(lf_export, text="Notizen / Bemerkungen (wird in CSV gespeichert):", bg="#f0f0f0").pack(anchor="w")
        self.text_notes = tk.Text(lf_export, height=3, width=30, font=("Arial", 9))
        self.text_notes.pack(fill=tk.X, pady=2)
        
        # --- NEU: Button für reinen Notiz-Export ---
        tk.Button(lf_export, text="Notizen separat als Text speichern", command=self.export_notes, width=25).pack(pady=2)
        
        tk.Button(lf_export, text="Aktuelle Ansicht als PNG", command=self.export_png, width=25).pack(pady=2)
        tk.Button(lf_export, text="Markierten Bereich als CSV", command=self.export_csv, width=25).pack(pady=2)

    def on_span_select(self, xmin, xmax):
        self.ent_start.delete(0, tk.END)
        self.ent_start.insert(0, f"{xmin:.3f}")
        self.ent_end.delete(0, tk.END)
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

    def log(self, msg): self.msg_queue.put(("LOG", msg))

    def process_queue(self):
        while not self.msg_queue.empty():
            msg_type, data = self.msg_queue.get()
            if msg_type == "LOG":
                self.log_text.insert(tk.END, data + "\n")
                self.log_text.see(tk.END)
            elif msg_type == "STATUS":
                self.lbl_status.config(text=data[0], fg=data[1])
            elif msg_type == "START_MEASURE":
                self.start_live_plot(data)
            elif msg_type == "LIVE_DATA":
                self.update_live_plot(data)
            elif msg_type == "END_MEASURE":
                self.stop_live_plot()
                self.load_csv(append=False, direct_path=data)
        self.root.after(100, self.process_queue)

    def start_connection(self):
        self.btn_connect.config(state=tk.DISABLED, text="Bluetooth aktiv")
        self.ble_handler.start()

    def start_live_plot(self, seconds):
        self.is_measuring = True
        self.countdown = seconds
        self.live_x, self.live_y, self.live_index = [], [], 0
        self.datasets = [] 
        self.ax.clear()
        
        try: ymax = float(self.ent_ymax.get().replace(',', '.'))
        except: ymax = 105
        
        if seconds == 0:
            self.lbl_countdown.config(text="⏳ Dauermessung läuft...", fg="#FFA500")
            self.ax.set_title("Live-Dauermessung (Stoppen am Arduino)")
            self.ax.set_xlim(0, 10) 
        else:
            self.lbl_countdown.config(text=f"⏳ {self.countdown} s verbleiben", fg="#FFA500")
            self.ax.set_title(f"Live-Messung läuft... (Ziel: {seconds} s)")
            self.ax.set_xlim(0, seconds)
            
        self.ax.set_xlabel("Zeit (Sekunden seit Start)")
        self.ax.set_ylabel("Druck (mbar)")
        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.ax.set_ylim(0, ymax)
        
        self.live_line, = self.ax.plot([], [], color='#D32F2F', linewidth=1.5)
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
        
        if self.countdown == 0 and self.live_x[-1] > self.ax.get_xlim()[1]:
            current_max = self.ax.get_xlim()[1]
            self.ax.set_xlim(current_max - 5, current_max + 5)
        
        self.live_line.set_data(self.live_x, self.live_y)
        self.canvas.draw_idle()

    def stop_live_plot(self):
        self.is_measuring = False
        self.lbl_countdown.config(text="✅ Messung beendet", fg="#4CAF50")

    def load_csv(self, append=False, direct_path=None):
        if self.is_measuring: return messagebox.showwarning("Achtung", "Bitte warte, bis die laufende Messung abgeschlossen ist.")
        filepath = direct_path or filedialog.askopenfilename(title="Messdaten auswählen", filetypes=[("CSV Dateien", "*.csv")])
        if filepath:
            if not append: 
                self.datasets = [] 
                # --- NEU: Radikaler Reset aller UI-Eingaben ---
                self.text_notes.delete("1.0", tk.END)
                self.ent_ymax.delete(0, tk.END)
                self.ent_ymax.insert(0, "105")
                self.clear_slice()
                self.clear_threshold()
                self.smooth_var.set(1)
                
            self.current_filepath = filepath
            try:
                self.log(f"INFO: Lade Daten: {os.path.basename(filepath)}")
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
                self.reset_view() # Zwingt den Graphen sofort in die korrekte Y-Max Ansicht
            except Exception as e:
                self.log(f"ERR: Fehler beim Laden: {e}")
                messagebox.showerror("Ladefehler", f"Fehler: {e}")
                
    def update_plot(self):
        if not self.datasets or self.is_measuring: return
        window = self.smooth_var.get()
        self.ax.clear()
        
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
                    self.ax.plot(ct, cv, marker='x', color='black', markersize=8)
                    self.lbl_thresh_res.config(text=f"Schwelle erreicht:\nZeit: {ct:.3f} s\nWert: {cv:.2f} mbar")

        if len(self.datasets) > 1: self.ax.legend(loc="upper right", fontsize=8)
        if self.slice_start is not None and self.slice_end is not None:
            self.ax.axvspan(self.slice_start, self.slice_end, color='blue', alpha=0.15)
            self.ax.axvline(self.slice_start, color='blue', linestyle='--')
            self.ax.axvline(self.slice_end, color='blue', linestyle='--')
        if self.threshold_val is not None: self.ax.axhline(self.threshold_val, color='orange', linestyle='--')

        title_str = "Live-Daten" if not self.current_filepath else f"{len(self.datasets)} Messungen geladen"
        self.ax.set_title(title_str)
        self.ax.set_xlabel("Zeit (Sekunden)")
        self.ax.set_ylabel("Druck (mbar)")
        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.ax.set_xlim(left=0, right=max_time)
        self.ax.set_ylim(bottom=0, top=ymax)
        
        self.annot = self.ax.annotate("", xy=(0,0), xytext=(15,15), textcoords="offset points", bbox=dict(boxstyle="round,pad=0.3", fc="#ffffe0", alpha=0.9), arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0"))
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
        self.ent_start.delete(0, tk.END)
        self.ent_end.delete(0, tk.END)
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
        self.ent_thresh.delete(0, tk.END)
        self.lbl_thresh_res.config(text="")
        self.update_plot()
        
    def export_png(self):
            if not self.datasets or self.is_measuring: return
            fp = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")])
            if fp: self.fig.savefig(fp, dpi=300, bbox_inches='tight'); self.log(f"Graph gespeichert: {fp}")

    def export_notes(self):
        note = self.text_notes.get("1.0", tk.END).strip()
        if not note: 
            return messagebox.showwarning("Fehler", "Das Notizfeld ist leer.")
            
        fp = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Textdatei", "*.txt")])
        if fp:
            with open(fp, 'w', encoding='utf-8') as f:
                f.write(note)
            self.log(f"Notizen gespeichert: {fp}")
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
            
            # 1. Die Sekunden auf 0 zurücksetzen
            start_time = df_export['Sekunden'].iloc[0]
            df_export['Sekunden'] = df_export['Sekunden'] - start_time
            
            # 2. NEU: Den Index sauber ab 1 neu durchnummerieren
            if 'Index' in df_export.columns:
                df_export['Index'] = range(1, len(df_export) + 1)
            
            note = self.text_notes.get("1.0", tk.END).strip()
            
            with open(fp, 'w', encoding='utf-8', newline='') as f:
                if note:
                    for line in note.split('\n'): 
                        f.write(f"# {line}\n")
                df_export.to_csv(f, sep=';', index=False)
                
            self.log(f"CSV erfolgreich exportiert: {fp}")
            messagebox.showinfo("Export", "Die CSV-Datei wurde gespeichert!\nZeit startet bei 0s, Index beginnt bei 1.")
            
        except Exception as e: 
            self.log(f"ERR: Export fehlgeschlagen: {e}")
            messagebox.showerror("Export-Fehler", f"Konnte CSV nicht speichern:\n{e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = SensorDashboard(root)
    root.mainloop()