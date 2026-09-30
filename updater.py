import tkinter as tk
from tkinter import messagebox
import requests
import threading
import tempfile
import subprocess
import os
import logging
from config import APP_VERSION, GITHUB_REPO

class AppUpdater:
    def __init__(self, root, app_callback):
        self.root = root
        self.logger = logging.getLogger("SensorApp.Updater")
        self.app_callback = app_callback
        self.latest_version = None
        self.download_url = None
        self.downloaded_version = None
        self.exe_path = os.path.join(tempfile.gettempdir(), "Drucksensor_Update.exe")
        self.is_downloading = False

    def check_for_updates(self, manual=False):
        def check():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                response = requests.get(url, timeout=3).json()
                latest_version = response.get("tag_name", "").replace("v", "")
                
                if latest_version and latest_version > APP_VERSION:
                    download_url = next((asset["browser_download_url"] for asset in response.get("assets", []) if asset["name"].endswith(".exe")), None)
                    if download_url:
                        self.latest_version = latest_version
                        self.download_url = download_url
                        
                        # Prüfen, ob wir genau dieses (oder ein neueres) Update schon geladen haben
                        if self.downloaded_version == latest_version and os.path.exists(self.exe_path):
                            self.root.after(0, lambda: self.app_callback("READY", latest_version))
                        else:
                            self.root.after(0, lambda: self.app_callback("AVAILABLE", latest_version))
                    elif manual:
                        messagebox.showinfo("Fehler", "Keine Setup-Datei auf GitHub gefunden.")
                elif manual:
                    messagebox.showinfo("Aktuell", "Du hast bereits die neueste Version!")
            except Exception as e:
                if manual: messagebox.showerror("Fehler", f"Konnte nicht nach Updates suchen: {e}")
        
        threading.Thread(target=check, daemon=True).start()

    def start_download(self):
        if self.is_downloading or not self.download_url: return
        self.is_downloading = True
        self.app_callback("DOWNLOADING", 0)
        
        def download_task():
            try:
                r = requests.get(self.download_url, stream=True)
                total_length = r.headers.get('content-length')
                
                with open(self.exe_path, 'wb') as f:
                    if total_length is None:
                        f.write(r.content)
                        self.root.after(0, lambda: self.app_callback("DOWNLOADING", 100))
                    else:
                        dl = 0
                        total_length = int(total_length)
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                dl += len(chunk)
                                f.write(chunk)
                                progress = int(100 * dl / total_length)
                                self.root.after(0, lambda p=progress: self.app_callback("DOWNLOADING", p))
                
                self.downloaded_version = self.latest_version
                self.is_downloading = False
                self.root.after(0, lambda: self.app_callback("READY", self.latest_version))
                
            except Exception as e:
                self.logger.error(f"Download fehlgeschlagen: {e}")
                self.is_downloading = False
                self.root.after(0, lambda: self.app_callback("ERROR", str(e)))

        threading.Thread(target=download_task, daemon=True).start()

    def install_update(self):
        if os.path.exists(self.exe_path):
            subprocess.Popen([self.exe_path, '/SILENT', '/SP-'])
            os._exit(0)