#ifndef MyAppVersion
  #define MyAppVersion "0.8.0"
#endif

[Setup]
AppId={{7E2F1C2A-9C3B-4A5E-9B7D-2C6F1A8E4D10}
AppName=MPC XPJ Builder
AppVersion={#MyAppVersion}
AppPublisher=Cursednik
AppPublisherURL=https://github.com/cursednik/mpc-xpj-builder
AppSupportURL=https://github.com/cursednik/mpc-xpj-builder/issues
DefaultDirName={autopf}\MPC XPJ Builder
DefaultGroupName=MPC XPJ Builder
OutputDir=..\dist
OutputBaseFilename=mpc-xpj-builder-v{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\mpc-xpj-builder-gui.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\mpc-xpj-builder.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\mpc-xpj-builder-gui.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\HARDWARE_TEST.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\MPC XPJ Builder GUI"; Filename: "{app}\mpc-xpj-builder-gui.exe"
Name: "{group}\MPC XPJ Builder CLI"; Filename: "{app}\mpc-xpj-builder.exe"
Name: "{group}\Uninstall MPC XPJ Builder"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MPC XPJ Builder"; Filename: "{app}\mpc-xpj-builder-gui.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\mpc-xpj-builder-gui.exe"; Description: "Launch MPC XPJ Builder"; Flags: nowait postinstall skipifsilent
