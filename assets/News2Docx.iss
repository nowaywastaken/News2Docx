#define MyAppName "News2Docx"
#ifndef MyAppVersion
#define MyAppVersion "2.1.0"
#endif
#define MyURL "https://github.com/nowaywastaken/News2Docx"

[Setup]
AppId={{CDA5E01C-6B4A-4D01-9AE9-3F11D7C7E7E1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisherURL={#MyURL}

DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer\output
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

DisableDirPage=no
WizardStyle=modern

; 安装程序图标
SetupIconFile=APP.ICO

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "News2Docx.exe"; DestDir: "{app}"; DestName: "News2Docx.exe"; Flags: ignoreversion
Source: "APP.ICO"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{userdocs}\{#MyAppName}"; Flags: uninsalwaysuninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\News2Docx.exe"; WorkingDir: "{userdocs}\{#MyAppName}"; IconFilename: "{app}\APP.ICO"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\News2Docx.exe"; WorkingDir: "{userdocs}\{#MyAppName}"; Tasks: desktopicon; IconFilename: "{app}\APP.ICO"

[Tasks]
Name: "desktopicon"; Description: "在桌面创建快捷方式"; GroupDescription: "其他选项:"; Flags: unchecked

[Run]
Filename: "{app}\News2Docx.exe"; Description: "运行 News2Docx"; Flags: nowait postinstall skipifsilent
