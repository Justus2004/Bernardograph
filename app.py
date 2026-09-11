import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import queue
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from data_processor import DataProcessor
from bluetooth_handler import BluetoothHandler

class SensorDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Drucksensor Dashboard & Analyse")
        self.root.geometry("1400x800")
        
        self.msg_queue = queue.Queue()
        self.processor = DataProcessor()
        self.ble_handler = BluetoothHandler(self.msg_queue, self.processor)
        
        self.raw_df = None       
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
        self.log("Bereit. Klicke auf 'Bluetooth Start' oder 'CSV laden'.\nTipp: Halte 'x' oder 'y' beim Scrollen für gezielten Zoom!")

    def setup_ui(self):
        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(main_paned)
        main_paned.add(left_frame, minsize=800)
        
        top_frame = tk.Frame(left_frame, pady=10)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10)
        
        self.btn_connect = tk.Button(top_frame, text="Bluetooth Start", command=self.start_connection, bg="#0078D7", fg="white", font=("Arial", 10, "bold"))
        self.btn_connect.pack(side=tk.LEFT, padx=5)
        
        self.btn_load = tk.Button(top_frame, text="CSV laden", command=self.load_csv, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
        self.btn_load.pack(side=tk.LEFT, padx=5)
        
        self.btn_reset = tk.Button(top_frame, text="Reset Ansicht", command=self.reset_view, bg="#607D8B", fg="white", font=("Arial", 10, "bold"))
        self.btn_reset.pack(side=tk.LEFT, padx=5)
        
        self.lbl_status = tk.Label(top_frame, text="🔴 Getrennt", font=("Arial", 10, "bold"), fg="#D32F2F")
        self.lbl_status.pack(side=tk.LEFT, padx=15)
        
        self.lbl_countdown = tk.Label(top_frame, text="", font=("Arial", 10, "bold"), fg="#FFA500")
        self.lbl_countdown.pack(side=tk.LEFT, padx=15)
        
        self.fig, self.ax = plt.subplots(figsize=(10, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=left_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.canvas.mpl_connect('scroll_event', self.on_zoom)
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('button_release_event', self.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        
        self.canvas.mpl_connect('key_press_event', self.on_key_press)
        self.canvas.mpl_connect('key_release_event', self.on_key_release)
        
        self.log_text = scrolledtext.ScrolledText(left_frame, height=6, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.log_text.pack(side=tk.BOTTOM, padx=10, pady=5, fill=tk.X)

        right_frame = tk.Frame(main_paned, width=350, bg="#f0f0f0", padx=10, pady=10)
        main_paned.add(right_frame, minsize=300)
        
        lbl_title = tk.Label(right_frame, text="Analyse Werkzeuge", font=("Arial", 14, "bold"), bg="#f0f0f0")
        lbl_title.pack(pady=(0, 15))

        lf_smooth = tk.LabelFrame(right_frame, text="1. Signal-Glättung", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_smooth.pack(fill=tk.X, pady=5)
        self.smooth_var = tk.IntVar(value=1)
        tk.Scale(lf_smooth, from_=1, to=100, orient=tk.HORIZONTAL, variable=self.smooth_var, command=lambda _: self.update_plot(), bg="#f0f0f0", label="Fenstergröße (Werte)").pack(fill=tk.X)

        lf_peaks = tk.LabelFrame(right_frame, text="2. Automatische Peaks", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_peaks.pack(fill=tk.X, pady=5)
        self.chk_peaks_var = tk.BooleanVar(value=True)
        tk.Checkbutton(lf_peaks, text="Min/Max Marker anzeigen", variable=self.chk_peaks_var, command=self.update_plot, bg="#f0f0f0").pack(anchor="w")

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

        lf_export = tk.LabelFrame(right_frame, text="5. Exportieren", bg="#f0f0f0", font=("Arial", 10, "bold"), pady=5, padx=5)
        lf_export.pack(fill=tk.X, pady=5)
        tk.Button(lf_export, text="Aktuelle Ansicht als PNG", command=self.export_png, width=25).pack(pady=2)
        tk.Button(lf_export, text="Markierten Bereich als CSV", command=self.export_csv, width=25).pack(pady=2)

    def reset_view(self):
        if self.raw_df is None and not self.is_measuring: return
        self.ax.set_xlim(left=0, right=self.raw_df['Sekunden'].iloc[-1] if self.raw_df is not None else self.countdown)
        self.ax.set_ylim(bottom=0, top=105)
        self.canvas.draw_idle()

    def log(self, msg):
        self.msg_queue.put(("LOG", msg))

    def process_queue(self):
        while not self.msg_queue.empty():
            msg_type, data = self.msg_queue.get()
            if msg_type == "LOG":
                self.log_text.insert(tk.END, data + "\n")
                self.log_text.see(tk.END)
            elif msg_type == "STATUS":
                text, color = data
                self.lbl_status.config(text=text, fg=color)
            elif msg_type == "START_MEASURE":
                self.start_live_plot(data)
            elif msg_type == "LIVE_DATA":
                self.update_live_plot(data)
            elif msg_type == "END_MEASURE":
                self.stop_live_plot()
                self.plot_data(data)
        self.root.after(100, self.process_queue)

    def start_connection(self):
        self.btn_connect.config(state=tk.DISABLED, text="Bluetooth aktiv")
        self.ble_handler.start()

    def start_live_plot(self, seconds):
        self.is_measuring = True
        self.countdown = seconds
        self.live_x = []
        self.live_y = []
        self.live_index = 0
        self.ax.clear()
        
        if seconds == 0:
            self.lbl_countdown.config(text="⏳ Dauermessung läuft...", fg="#FFA500")
            self.ax.set_title("Live-Dauermessung (Stoppen am Arduino)")
            self.ax.set_xlim(0, 10) # Startet mit 10 Sekunden Fenster, das später mitwandert
        else:
            self.lbl_countdown.config(text=f"⏳ {self.countdown} s verbleiben", fg="#FFA500")
            self.ax.set_title(f"Live-Messung läuft... (Ziel: {seconds} s)")
            self.ax.set_xlim(0, seconds)
            
        self.ax.set_xlabel("Zeit (Sekunden seit Start)")
        self.ax.set_ylabel("Druck (mbar)")
        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.ax.set_ylim(0, 105)
        
        self.live_line, = self.ax.plot([], [], color='#D32F2F', linewidth=1.5)
        self.canvas.draw_idle()
        if seconds > 0:
            self.update_countdown()

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
        
        # Dauermessung: X-Achse dynamisch mitscrollen, wenn Rand erreicht wird
        if self.countdown == 0 and self.live_x[-1] > self.ax.get_xlim()[1]:
            current_max = self.ax.get_xlim()[1]
            self.ax.set_xlim(current_max - 5, current_max + 5)
        
        self.live_line.set_data(self.live_x, self.live_y)
        self.canvas.draw_idle()
    def stop_live_plot(self):
        self.is_measuring = False
        self.lbl_countdown.config(text="✅ Messung beendet", fg="#4CAF50")

    def load_csv(self):
        if self.is_measuring:
            messagebox.showwarning("Achtung", "Bitte warte, bis die laufende Messung abgeschlossen ist.")
            return
            
        filepath = filedialog.askopenfilename(title="Messdaten auswählen", filetypes=[("CSV Dateien", "*.csv")])
        if filepath:
            self.current_filepath = filepath
            self.plot_data(filepath)

    def plot_data(self, filepath):
        try:
            self.log(f"INFO: Lade finale Daten zur Analyse...")
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
                    df['Sekunden'] = (df['Zeit_Objekt'] - df['Zeit_Objekt'].iloc[0]).dt.total_seconds()
                else:
                    df['Sekunden'] = (df['Zeitstempel'].astype(float) - 1) / 1000.0

            self.raw_df = df
            self.clear_slice()
            self.clear_threshold()
            self.smooth_var.set(1)
            self.update_plot()
            
        except Exception as e:
            self.log(f"ERR: Fehler beim Laden: {e}")
            messagebox.showerror("Ladefehler", f"Fehler: {e}")

    def update_plot(self):
        if self.raw_df is None or self.is_measuring: return
        
        df = self.raw_df.copy()
        window = self.smooth_var.get()
        if window > 1:
            df['Druck_mbar'] = df['Druck_mbar'].rolling(window=window, min_periods=1, center=True).mean()

        self.ax.clear()
        self.ax.plot(df['Sekunden'], df['Druck_mbar'], color='#D32F2F', linewidth=1.5)
        
        if self.chk_peaks_var.get():
            idx_max, idx_min = df['Druck_mbar'].idxmax(), df['Druck_mbar'].idxmin()
            self.ax.plot(df.loc[idx_max, 'Sekunden'], df.loc[idx_max, 'Druck_mbar'], marker='o', color='blue')
            self.ax.annotate(f"MAX: {df.loc[idx_max, 'Druck_mbar']:.1f}", (df.loc[idx_max, 'Sekunden'], df.loc[idx_max, 'Druck_mbar']), xytext=(0,10), textcoords="offset points", ha='center', color='blue')
            self.ax.plot(df.loc[idx_min, 'Sekunden'], df.loc[idx_min, 'Druck_mbar'], marker='o', color='green')
            self.ax.annotate(f"MIN: {df.loc[idx_min, 'Druck_mbar']:.1f}", (df.loc[idx_min, 'Sekunden'], df.loc[idx_min, 'Druck_mbar']), xytext=(0,-15), textcoords="offset points", ha='center', color='green')

        if self.slice_start is not None and self.slice_end is not None:
            self.ax.axvspan(self.slice_start, self.slice_end, color='blue', alpha=0.15)
            self.ax.axvline(self.slice_start, color='blue', linestyle='--')
            self.ax.axvline(self.slice_end, color='blue', linestyle='--')

        if self.threshold_val is not None:
            cross_df = df[df['Druck_mbar'] >= self.threshold_val]
            if not cross_df.empty:
                ct, cv = cross_df.iloc[0]['Sekunden'], cross_df.iloc[0]['Druck_mbar']
                self.ax.axhline(self.threshold_val, color='orange', linestyle='--')
                self.ax.plot(ct, cv, marker='x', color='black', markersize=8)
                self.ax.annotate(f"{ct:.3f}s", (ct, cv), xytext=(10,-10), textcoords="offset points", color='black')
                self.lbl_thresh_res.config(text=f"Schwelle erreicht:\nZeit: {ct:.3f} s\nWert: {cv:.2f} mbar")
            else:
                self.lbl_thresh_res.config(text="Schwelle nicht erreicht.")

        filename = "Live-Daten" if not self.current_filepath else self.current_filepath.split('/')[-1].split('\\')[-1]
        self.ax.set_title(f"Messung: {filename} | Dauer: {df['Sekunden'].iloc[-1]:.2f} s")
        self.ax.set_xlabel("Zeit (Sekunden)")
        self.ax.set_ylabel("Druck (mbar)")
        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.ax.set_xlim(left=0)
        self.ax.set_ylim(bottom=0, top=105)
        
        self.annot = self.ax.annotate("", xy=(0,0), xytext=(15,15), textcoords="offset points", bbox=dict(boxstyle="round,pad=0.3", fc="#ffffe0", alpha=0.9), arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0"))
        self.annot.set_visible(False)
        self.canvas.draw_idle()

    def analyze_slice(self):
        if self.raw_df is None or self.is_measuring: return
        try:
            s_start = float(self.ent_start.get().replace(',', '.'))
            s_end = float(self.ent_end.get().replace(',', '.'))
            if s_start >= s_end: return messagebox.showwarning("Eingabe", "Start muss kleiner als Ende sein.")
                
            self.slice_start, self.slice_end = s_start, s_end
            df = self.raw_df.copy()
            if self.smooth_var.get() > 1: df['Druck_mbar'] = df['Druck_mbar'].rolling(window=self.smooth_var.get(), center=True).mean()
                
            sliced = df[(df['Sekunden'] >= s_start) & (df['Sekunden'] <= s_end)]
            if not sliced.empty:
                tdiff = sliced.iloc[-1]['Sekunden'] - sliced.iloc[0]['Sekunden']
                rate = (sliced.iloc[-1]['Druck_mbar'] - sliced.iloc[0]['Druck_mbar']) / tdiff if tdiff > 0 else 0
                self.lbl_stats.config(text=f"Schnitt: {sliced['Druck_mbar'].mean():.2f} mbar\nMin: {sliced['Druck_mbar'].min():.2f} mbar\nMax: {sliced['Druck_mbar'].max():.2f} mbar\nσ: ±{sliced['Druck_mbar'].std():.2f} mbar\nRate: {rate:.2f} mbar/s")
            self.update_plot()
        except ValueError:
            messagebox.showerror("Fehler", "Bitte gültige Zahlen eingeben.")

    def clear_slice(self):
        self.slice_start = self.slice_end = None
        self.ent_start.delete(0, tk.END)
        self.ent_end.delete(0, tk.END)
        self.lbl_stats.config(text="Kein Bereich gewählt.")
        self.update_plot()

    def find_threshold(self):
        if self.raw_df is None or self.is_measuring: return
        try:
            self.threshold_val = float(self.ent_thresh.get().replace(',', '.'))
            self.update_plot()
        except ValueError:
            messagebox.showerror("Fehler", "Gültige Zahl einfügen.")

    def clear_threshold(self):
        self.threshold_val = None
        self.ent_thresh.delete(0, tk.END)
        self.lbl_thresh_res.config(text="")
        self.update_plot()

    def export_png(self):
        if self.raw_df is None or self.is_measuring: return
        fp = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")])
        if fp: self.fig.savefig(fp, dpi=300, bbox_inches='tight'); self.log(f"Graph gespeichert: {fp}")

    def export_csv(self):
        if self.raw_df is None or self.slice_start is None or self.is_measuring: return
        fp = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV File", "*.csv")])
        if fp:
            self.raw_df[(self.raw_df['Sekunden'] >= self.slice_start) & (self.raw_df['Sekunden'] <= self.slice_end)].to_csv(fp, sep=';', index=False)
            self.log(f"CSV exportiert: {fp}")

    def on_key_press(self, event):
        self.current_key = event.key.lower() if event.key else None

    def on_key_release(self, event):
        self.current_key = None

    def on_zoom(self, event):
        if event.inaxes != self.ax or self.is_measuring: return
        
        scale = 1/1.2 if event.button == 'up' else 1.2
        
        scale_x = scale if self.current_key == 'x' else (scale if self.current_key not in ['x', 'y'] else 1.0)
        scale_y = scale if self.current_key == 'y' else (scale if self.current_key not in ['x', 'y'] else 1.0)
        
        xd, yd = event.xdata, event.ydata
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        
        nxw = (xl[1]-xl[0]) * scale_x
        nyh = (yl[1]-yl[0]) * scale_y
        
        # --- NEU: Zoom-Limit für X-Achse (Nicht tiefer als 0.01 Sekunden / 10 Datenpunkte) ---
        if nxw < 0.01: 
            nxw = 0.01
        
        # X-Achse berechnen
        if scale_x != 1.0 or nxw == 0.01:
            nxmin = xd - nxw * (1 - (xl[1]-xd)/(xl[1]-xl[0]))
            nxmax = nxmin + nxw
        else:
            nxmin, nxmax = xl[0], xl[1]
            
        # Y-Achse berechnen
        if scale_y != 1.0:
            nymin = yd - nyh * (1 - (yl[1]-yd)/(yl[1]-yl[0]))
            nymax = nymin + nyh
        else:
            nymin, nymax = yl[0], yl[1]
        
        # Constraints anwenden
        if nxmin < 0:
            nxmax -= nxmin
            nxmin = 0
            
        if nymin < 0:
            nymax -= nymin
            nymin = 0
        if nymax > 120:
            nymin -= (nymax - 120)
            nymax = 120
            if nymin < 0: nymin = 0
                
        self.ax.set_xlim([nxmin, nxmax])
        self.ax.set_ylim([nymin, nymax])
        self.canvas.draw_idle()

    def on_press(self, event):
        self.canvas.get_tk_widget().focus_set()
        
        if event.button in [1, 3] and event.inaxes == self.ax and not self.is_measuring:
            self.press = (event.x, event.y, self.ax.get_xlim(), self.ax.get_ylim())
            self.canvas.get_tk_widget().config(cursor="fleur")

    def on_release(self, event):
        self.press = None
        self.canvas.get_tk_widget().config(cursor="arrow")
        if not self.is_measuring: self.canvas.draw_idle()

    def on_motion(self, event):
        if event.inaxes != self.ax or self.is_measuring:
            if self.annot and self.annot.get_visible(): 
                self.annot.set_visible(False)
                self.canvas.draw_idle()
            return

        if self.press:
            if self.annot and self.annot.get_visible(): 
                self.annot.set_visible(False)
            x0, y0, xl, yl = self.press
            dx, dy = (event.x-x0)*(xl[1]-xl[0])/self.ax.bbox.width, (event.y-y0)*(yl[1]-yl[0])/self.ax.bbox.height
            
            nxmin, nxmax = xl[0]-dx, xl[1]-dx
            nymin, nymax = yl[0]-dy, yl[1]-dy
            
            if nxmin < 0:
                nxmax -= nxmin
                nxmin = 0
                
            if nymin < 0:
                nymax -= nymin
                nymin = 0
            if nymax > 120:
                nymin -= (nymax - 120)
                nymax = 120
                if nymin < 0: nymin = 0
                    
            self.ax.set_xlim(nxmin, nxmax)
            self.ax.set_ylim(nymin, nymax)
            self.canvas.draw_idle()
            return
        
        if self.raw_df is not None and event.xdata and self.annot:
            df = self.raw_df.copy()
            if self.smooth_var.get() > 1: df['Druck_mbar'] = df['Druck_mbar'].rolling(window=self.smooth_var.get(), center=True).mean()
            row = df.loc[(df['Sekunden'] - event.xdata).abs().idxmin()]
            if abs(row['Sekunden'] - event.xdata) < ((self.ax.get_xlim()[1] - self.ax.get_xlim()[0]) * 0.05):
                self.annot.xy = (row['Sekunden'], row['Druck_mbar'])
                self.annot.set_text(f"{row['Sekunden']:.3f} s\n{row['Druck_mbar']:.2f} mbar")
                self.annot.set_visible(True)
            else: self.annot.set_visible(False)
            self.canvas.draw_idle()

if __name__ == "__main__":
    root = tk.Tk()
    app = SensorDashboard(root)
    root.mainloop()