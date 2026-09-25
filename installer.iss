#define AppName "Tori Download"
#define AppVersion "0.22.0"

[Setup]
AppId={{D497225E-182A-4706-97E8-52891D6E453F}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Tori Download
DefaultGroupName=Tori Download
PrivilegesRequired=lowest
OutputDir=release-dist
OutputBaseFilename=ToriDownload-Setup-v0.22
SetupIconFile=tori.ico
UninstallDisplayIcon={app}\ToriDownload.exe
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\ToriDownload.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "ToriDownload"; Flags: dontcreatekey uninsdeletevalue

[Icons]
Name: "{group}\Tori Download"; Filename: "{app}\ToriDownload.exe"
Name: "{group}\Extension folder"; Filename: "{app}\extension"
Name: "{autodesktop}\Tori Download"; Filename: "{app}\ToriDownload.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\ToriDownload.exe"; Description: "Launch Tori Download"; Flags: nowait postinstall skipifsilent
