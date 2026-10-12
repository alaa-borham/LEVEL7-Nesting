; Inno Setup 6 script for LEVEL7 Nesting (x64). Build after PyInstaller:
;   iscc /DAppVersion=0.1.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6B8E8F4E-6F0C-4C2B-9D8E-7A1E5C3B7A10}
AppName=LEVEL7 Nesting
AppVersion={#AppVersion}
AppPublisher=LEVEL7
DefaultDirName={autopf}\LEVEL7 Nesting
DefaultGroupName=LEVEL7 Nesting
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=LEVEL7Nesting-{#AppVersion}-Setup
SetupIconFile=..\level7\resources\level7.ico
UninstallDisplayIcon={app}\LEVEL7Nesting.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "assoc"; Description: "Open .l7n projects with LEVEL7 Nesting"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\LEVEL7Nesting\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LEVEL7 Nesting"; Filename: "{app}\LEVEL7Nesting.exe"
Name: "{group}\{cm:UninstallProgram,LEVEL7 Nesting}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LEVEL7 Nesting"; Filename: "{app}\LEVEL7Nesting.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.l7n"; ValueType: string; ValueName: ""; ValueData: "LEVEL7.Project"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\LEVEL7.Project"; ValueType: string; ValueName: ""; ValueData: "LEVEL7 Nesting project"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\LEVEL7.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\LEVEL7Nesting.exe,0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\LEVEL7.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\LEVEL7Nesting.exe"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\LEVEL7Nesting.exe"; Description: "{cm:LaunchProgram,LEVEL7 Nesting}"; Flags: nowait postinstall skipifsilent
