; Inno Setup 6 script for DTF Manager. Built by build.ps1 (it passes /DAppVersion=<version>).
; Manual build:  ISCC.exe /DAppVersion=1.0.0 installer.iss   (needs dist\DTFManager from PyInstaller)

; ---- editable constants ------------------------------------------------------------------
#define MyAppName "DTF Manager"
#define MyAppPublisher "DTF Manager"
#define MyAppExeName "DTFManager.exe"
#define MyAppMutex "DTFManager-AppMutex"
; ------------------------------------------------------------------------------------------

#ifndef AppVersion
  #error Informe a versao: ISCC.exe /DAppVersion=1.0.0 installer.iss (o build.ps1 faz isso)
#endif

[Setup]
; FIXED GUID: identifies this app for upgrades and uninstall. NEVER change it.
AppId={{C4111349-E156-43E9-BD99-978D3DB85F41}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#AppVersion}
; Per-user install: no administrator prompt. {autopf} becomes %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
OutputDir=installer_output
OutputBaseFilename=DTFManager-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; The running app holds this mutex (dtf_manager/core/app_mutex.py): the installer notices it,
; closes the app (Restart Manager) and, when it can, restarts it.
AppMutex={#MyAppMutex}
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Whole PyInstaller one-folder output.
Source: "dist\DTFManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Normal install: checkbox on the last page.
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
; Silent install (automatic update): reopens the app by itself.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: WizardSilent

; User data is NOT touched on uninstall or update: there is no [UninstallDelete] on purpose.
; The app keeps its data outside the install folder: %LOCALAPPDATA%\DTF Manager\DTF Manager
; (database, license, history, link memory), QSettings in the registry (HKCU\Software\DTF Manager)
; and the license credentials in the Windows Credential Manager.
