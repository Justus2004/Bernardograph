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
    def __init__(self, root):
        self.root = root
        self.logger = logging.getLogger("SensorApp.Updater")

    def check_for_updates(self, manual=False):
        def check():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                response = requests.get(url, timeout=3).json()
                latest_version = response.get("tag_name", "").replace("v", "")
                
                if latest_version and latest_version > APP_VERSION:
                    download_url = next((asset["browser_download_url"] for asset in response.get("assets", []) if asset["name"].endswith(".exe")), None)
                    if download_url:
                        self.logger.info(f"Update v{latest_version} gefunden. Lade lautlos im Hintergrund...")
                        self.download_silently(download_url, latest_version)
                    elif manual: 
                        messagebox.showinfo("Fehler", "Keine Setup-Datei gefunden.")
                elif manual: 
                    messagebox.showinfo("Aktuell", "Du hast bereits die neueste Version!")
            except Exception as e:
                if manual: messagebox.showerror("Fehler", f"Konnte nicht nach Updates suchen: {e}")
        
        threading.Thread(target=check, daemon=True).start()

    def download_silently(self, download_url, version):
        try:
            temp_exe = os.path.join(tempfile.gettempdir(), "Drucksensor_Update.exe")
            r = requests.get(download_url, stream=True)
            
            with open(temp_exe, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk: f.write(chunk)
            
            self.logger.info("Hintergrund-Download abgeschlossen. Warte auf Bestätigung.")
            self.root.after(0, lambda: self.prompt_install(version, temp_exe))
            
        except Exception as e:
            self.logger.error(f"Hintergrund-Download fehlgeschlagen: {e}")

    def prompt_install(self, version, exe_path):
        ans = messagebox.askyesno("Update bereit!", f"Version {version} wurde im Hintergrund fertig heruntergeladen.\n\nMöchtest du die App jetzt kurz neustarten (dauert ca. 3 Sekunden)?")
        if ans:
            subprocess.Popen([exe_path, '/SILENT', '/SP-'])
            os._exit(0)
        else:
            self.logger.info("Update-Installation übersprungen. Heruntergeladene Datei wird gelöscht.")
            try:
                if os.path.exists(exe_path):
                    os.remove(exe_path)
            except Exception as e:
                self.logger.error(f"Konnte temporäre Update-Datei nicht löschen: {e}")