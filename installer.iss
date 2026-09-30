[Setup]
AppName=Drucksensor Dashboard
AppVersion={#MyAppVersion}
AppPublisher=DeinName
DefaultDirName={autopf}\DrucksensorDashboard
DefaultGroupName=Drucksensor Dashboard
OutputDir=Output
OutputBaseFilename=Drucksensor_Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest

[Files]
Source: "dist\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Drucksensor Dashboard"; Filename: "{app}\app.exe"
Name: "{autodesktop}\Drucksensor Dashboard"; Filename: "{app}\app.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked