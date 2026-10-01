[Setup]
AppName=Bernardograph
AppVersion={#MyAppVersion}
AppPublisher=DeinName
DefaultDirName={autopf}\Bernardograph
DefaultGroupName=Bernardograph
OutputDir=Output
OutputBaseFilename=Bernardograph_Setup
; Hier weisen wir Inno Setup an, auch für die Setup.exe dein Icon zu nutzen:
SetupIconFile=icon.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest

[Files]
Source: "dist\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Wir kopieren das Icon mit in den Installationsordner, damit Windows-Shortcuts es finden:
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Bernardograph"; Filename: "{app}\app.exe"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\Bernardograph"; Filename: "{app}\app.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\app.exe"; Flags: nowait

[UninstallDelete]
Type: filesandordirs; Name: "{app}"