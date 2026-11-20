#ifndef Payload
  #error Set Payload to the extracted release folder
#endif
#ifndef Output
  #error Set Output to the release output folder
#endif
[Setup]
AppId={{33221639-CE2D-468D-ACC6-250D1DA16165}
AppName=Next MC Launcher
AppVersion=0.1.0-beta.2
AppPublisher=Next MC contributors (unofficial)
AppPublisherURL=https://github.com/A5yncX/next-mc-launcher
DefaultDirName={localappdata}\Programs\Next MC Launcher
DefaultGroupName=Next MC Launcher
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Output}
OutputBaseFilename=NextMC-Setup-Windows-x64
Compression=lzma2/fast
SolidCompression=yes
SetupIconFile=..\assets\next-mc.ico
UninstallFilesDir={app}\NextMC
UninstallDisplayIcon={app}\next-mc-launcher.exe
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Next MC Launcher"; Filename: "{app}\next-mc-launcher.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Next MC Launcher"; Filename: "{app}\next-mc-launcher.exe"; WorkingDir: "{app}"; Tasks: desktopicon
