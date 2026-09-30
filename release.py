import os
import re
import subprocess

def run_git(command):
    print(f"> {command}")
    subprocess.run(command, shell=True, check=True)

print("=== Automatischer Release-Manager ===")

# 1. Aktuelle Version aus config.py lesen
config_path = "config.py"
try:
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Sucht nach dem Muster "X.Y.Z"
    match = re.search(r'APP_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', content)
    if not match:
        raise ValueError("Konnte Versionsnummer (z.B. 1.0.8) in config.py nicht finden.")
    
    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
except Exception as e:
    print(f"[Fehler] {e}")
    exit()

print(f"Aktuelle Version: {major}.{minor}.{patch}")
print("Welches Update möchtest du veröffentlichen?")
print(f" [1] Patch (Bugfix)         -> {major}.{minor}.{patch+1}")
print(f" [2] Minor (Neue Funktion)  -> {major}.{minor+1}.0")
print(f" [3] Major (Großes Update)  -> {major+1}.0.0")
print(f" [4] Manuell eingeben")

choice = input("Auswahl (1-4): ").strip()

if choice == '1': new_version = f"{major}.{minor}.{patch+1}"
elif choice == '2': new_version = f"{major}.{minor+1}.0"
elif choice == '3': new_version = f"{major+1}.0.0"
elif choice == '4': new_version = input("Neue Versionsnummer (z.B. 2.5.0): ").strip().lstrip('v')
else:
    print("Abbruch: Ungültige Auswahl.")
    exit()

message = input("Was ist neu? (Commit-Nachricht): ").strip()
if not new_version or not message:
    print("Abbruch: Version und Nachricht dürfen nicht leer sein!")
    exit()

# 2. config.py aktualisieren
new_content = re.sub(r'APP_VERSION\s*=\s*".*?"', f'APP_VERSION = "{new_version}"', content)
with open(config_path, "w", encoding="utf-8") as f:
    f.write(new_content)
print(f"\n[OK] config.py wurde auf {new_version} aktualisiert.")

# 3. Git-Befehle
print("\nStarte Git-Upload...")
try:
    run_git("git add .")
    run_git(f'git commit -m "{message}"')
    run_git(f"git tag v{new_version}")
    run_git("git push origin main")
    run_git(f"git push origin v{new_version}")
    
    print(f"\n✅ Erfolgreich! Version v{new_version} wurde hochgeladen.")
except subprocess.CalledProcessError:
    print("\n❌ Fehler beim Ausführen der Git-Befehle.")