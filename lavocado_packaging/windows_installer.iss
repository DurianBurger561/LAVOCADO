; Inno Setup script for the LAVOCADO Windows installer.
; Built in CI with:  ISCC.exe /DAppVersion=1.2.3 lavocado_packaging\windows_installer.iss
; Expects the PyInstaller output in dist\LAVOCADO (relative to the repository root).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{E0991B06-1654-41D3-8BED-A3426D57822F}
AppName=LAVOCADO
AppVersion={#AppVersion}
AppVerName=LAVOCADO {#AppVersion}
AppPublisher=LAVOCADO
AppPublisherURL=https://durianburger561.github.io/LAVOCADO/
AppSupportURL=https://github.com/DurianBurger561/LAVOCADO
; Per-user install: no administrator prompt.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\LAVOCADO
DefaultGroupName=LAVOCADO
DisableProgramGroupPage=yes
DisableDirPage=auto
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=icons\lavocado.ico
UninstallDisplayIcon={app}\LAVOCADO.exe
UninstallDisplayName=LAVOCADO
OutputDir=..\dist-installer
OutputBaseFilename=LAVOCADO-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ShowLanguageDialog=auto
LanguageDetectionMethod=uilanguage

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseTraditional.isl")
Name: "chinesetraditional"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\LAVOCADO\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LAVOCADO"; Filename: "{app}\LAVOCADO.exe"
Name: "{autodesktop}\LAVOCADO"; Filename: "{app}\LAVOCADO.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LAVOCADO.exe"; Description: "{cm:LaunchProgram,LAVOCADO}"; Flags: nowait postinstall skipifsilent
