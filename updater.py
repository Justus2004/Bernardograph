import tkinter as tk
from tkinter import messagebox, ttk
import requests
import threading
import tempfile
import subprocess
import os
from config import APP_VERSION, GITHUB_REPO

class AppUpdater:
    def __init__(self, root, log_callback):
        self.root = root
        self.log = log_callback

    def check_for_updates(self, manual=False):
        def check():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                response = requests.get(url, timeout=3).json()
                latest_version = response.get("tag_name", "").replace("v", "")
                
                if latest_version and latest_version > APP_VERSION:
                    download_url = next((asset["browser_download_url"] for asset in response.get("assets", []) if asset["name"].endswith(".exe")), None)
                    if download_url:
                        ans = messagebox.askyesno("Update verfügbar!", f"Version {latest_version} ist verfügbar.\n\nSoll das Update jetzt heruntergeladen und automatisch installiert werden?")
                        if ans: self.install_update(download_url)
                    elif manual: messagebox.showinfo("Fehler", "Keine Setup-Datei im Release gefunden.")
                elif manual: messagebox.showinfo("Aktuell", "Du hast bereits die neueste Version!")
            except Exception as e:
                if manual: messagebox.showerror("Fehler", f"Konnte nicht nach Updates suchen: {e}")
        threading.Thread(target=check, daemon=True).start()

    def install_update(self, download_url):
        prog_win = tk.Toplevel(self.root)
        prog_win.title("Update wird heruntergeladen")
        prog_win.geometry("400x150")
        prog_win.attributes("-topmost", True)
        
        tk.Label(prog_win, text="Bitte warten, lade neue Version...", font=("Arial", 11)).pack(pady=15)
        progress = ttk.Progressbar(prog_win, orient=tk.HORIZONTAL, length=300, mode='determinate')
        progress.pack(pady=5)
        lbl_percent = tk.Label(prog_win, text="0 %", font=("Arial", 10, "bold"))
        lbl_percent.pack()

        def download_and_run():
            try:
                self.log("INFO: Lade Update herunter...")
                temp_exe = os.path.join(tempfile.gettempdir(), "Drucksensor_Update.exe")
                r = requests.get(download_url, stream=True)
                total_size = int(r.headers.get('content-length', 0))
                downloaded = 0
                
                with open(temp_exe, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = int((downloaded / total_size) * 100)
                                self.root.after(0, lambda p=percent: progress.config(value=p))
                                self.root.after(0, lambda p=percent: lbl_percent.config(text=f"{p} %"))
                
                self.log("INFO: Download fertig. Starte Installation...")
                self.root.after(0, prog_win.destroy)
                subprocess.Popen([temp_exe, '/SILENT', '/SP-'])
                os._exit(0)
            except Exception as e:
                self.root.after(0, prog_win.destroy)
                self.root.after(0, lambda: messagebox.showerror("Update-Fehler", f"Fehler beim Herunterladen: {e}"))
                
        threading.Thread(target=download_and_run, daemon=True).start()