; Inno Setup script for News2Docx — minimal-privilege, production-safe packaging
; 安全要点：
; - 用户级安装（PrivilegesRequired=lowest），默认安装到 {localappdata}\News2Docx，可写且无需管理员权限。
; - 严格排除敏感/无关文件（config.yml、日志、运行产物、缓存、虚拟环境、测试缓存等）。
; - 固定工作目录为安装目录；本程序默认仅输出到控制台，不写入本地日志文件。
; - 启用安装包完整性校验（AppIntegrityCheck=yes）。
; - 未包含 Python 运行时；图标指向 index.py，依赖目标机已安装并关联 .py（或后续改为捆绑解释器）。

#define MyAppName "News2Docx"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "News2Docx"
#define MyAppURL "https://github.com/nowaywastaken/News2Docx"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\News2Docx
DefaultGroupName={#MyAppName}
OutputDir=installer\output
OutputBaseFilename=News2Docx_Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
AppId={{E0D2E2E0-5A8D-47B1-9C38-NEWS2DOCX-0001}
DisableDirPage=no
DisableProgramGroupPage=no
UsePreviousAppDir=no
ArchitecturesInstallIn64BitMode=x64
SetupLogging=yes
AppIntegrityCheck=yes

[Files]
; 源码目录为脚本上级目录
Source: "..\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
    Excludes: \
        ".git*;.github*;installer\\output*;*.pyc;__pycache__*;.pytest_cache*;.ruff_cache*;.DS_Store;" \
        ".venv*;env*;venv*;goal.md;.env;log.txt;logs*;runs*;.n2d_cache*;config.yml;config.toml"

[Icons]
; 开始菜单图标（工作目录固定为安装目录）
Name: "{group}\News2Docx"; Filename: "{app}\index.py"; WorkingDir: "{app}"; Comment: "Run News2Docx"
; 桌面图标（用户级）
Name: "{userdesktop}\News2Docx"; Filename: "{app}\index.py"; WorkingDir: "{app}"; Comment: "Run News2Docx"

[Run]
; 初次安装完成后不自动运行，避免在无人值守环境中启动进程。
; 若需要自动启动，可解注释：
; Filename: "{app}\\index.py"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; 卸载时保留用户数据（runs、.n2d_cache 等）；程序在任务完成后会自动清理单次 run 产物。
; 如需清理可在 UI/CLI 提供清理入口。

[Tasks]
; 如需可选桌面图标，可在此定义任务并与 Icons 关联；此处保持最简，始终创建用户桌面图标。

; 可选：签名（需在开发机配置证书）。默认不启用，避免在无证书环境下构建失败。
; 使用方法：编译时定义 SIGN（/D SIGN），启用如下签名工具。
; #ifdef SIGN
; SignTool=msig
; #endif
; [SignTool]
; Name: "msig"; Command: "signtool sign /fd SHA256 /a /tr http://timestamp.digicert.com /td SHA256 $f"
