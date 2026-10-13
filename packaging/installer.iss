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
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "assoc"; Description: "Open .l7n projects with LEVEL7 Nesting"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assocgrafis"; Description: "Open GRAFIS MDL / SCB files with LEVEL7 Nesting (double-click / Enter; several files = several sessions)"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; an update replaces the whole runtime: no stale Qt / Python DLLs or plugins from the previous build
Type: filesandordirs; Name: "{app}\_internal"

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

; GRAFIS files: LEVEL7 always appears under "Open with"; with the task it becomes the program for MDL / SCB
Root: HKA; Subkey: "Software\Classes\LEVEL7.Grafis"; ValueType: string; ValueName: ""; ValueData: "GRAFIS file (LEVEL7 Nesting)"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\LEVEL7.Grafis\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\LEVEL7Nesting.exe,0"
Root: HKA; Subkey: "Software\Classes\LEVEL7.Grafis\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\LEVEL7Nesting.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.mdl\OpenWithProgids"; ValueType: string; ValueName: "LEVEL7.Grafis"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.scb\OpenWithProgids"; ValueType: string; ValueName: "LEVEL7.Grafis"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.dxf\OpenWithProgids"; ValueType: string; ValueName: "LEVEL7.Grafis"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\LEVEL7Nesting.exe\SupportedTypes"; ValueType: string; ValueName: ".mdl"; ValueData: ""; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\LEVEL7Nesting.exe\SupportedTypes"; ValueType: string; ValueName: ".scb"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\LEVEL7Nesting.exe\SupportedTypes"; ValueType: string; ValueName: ".dxf"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\LEVEL7Nesting.exe\SupportedTypes"; ValueType: string; ValueName: ".l7n"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.mdl"; ValueType: string; ValueName: ""; ValueData: "LEVEL7.Grafis"; Tasks: assocgrafis; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.scb"; ValueType: string; ValueName: ""; ValueData: "LEVEL7.Grafis"; Tasks: assocgrafis; Flags: uninsdeletevalue

[Run]
Filename: "{app}\LEVEL7Nesting.exe"; Description: "{cm:LaunchProgram,LEVEL7 Nesting}"; Flags: nowait postinstall skipifsilent
; online update (started by the app with /SILENT /LAUNCH=1): start LEVEL7 again as the normal user
Filename: "{app}\LEVEL7Nesting.exe"; Flags: nowait runasoriginaluser; Check: LaunchAfterUpdate

[Code]
function LaunchAfterUpdate: Boolean;
begin
  Result := ExpandConstant('{param:LAUNCH|0}') = '1';
end;
