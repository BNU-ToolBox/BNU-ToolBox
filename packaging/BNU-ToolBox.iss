#ifndef AppVersion
  #define AppVersion "0.0.1"
#endif
#ifndef StageDir
  #define StageDir "..\build\stage"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installer"
#endif

#define AppName "BNU-ToolBox"
#define AppPublisher "BNU-ToolBox"
#define AppExeName "BNU-ToolBox.exe"
#define AppIcon "..\app\web\assets\bnu-toolbox.ico"

[Setup]
AppId={{A41E5143-9BC8-4DF7-9825-49FC671B48A5}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir={#OutputDir}
OutputBaseFilename=BNU-ToolBox-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
UninstallDisplayIcon={app}\app\web\assets\bnu-toolbox.ico
SetupIconFile={#AppIcon}
LicenseFile={#StageDir}\LICENSE
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式:"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BNU-ToolBox"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app\web\assets\bnu-toolbox.ico"
Name: "{group}\卸载 BNU-ToolBox"; Filename: "{uninstallexe}"; IconFilename: "{app}\app\web\assets\bnu-toolbox.ico"
Name: "{autodesktop}\BNU-ToolBox"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app\web\assets\bnu-toolbox.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\main.py"""; WorkingDir: "{app}"; Description: "启动 BNU-ToolBox"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\plugins\campus-network-auth\autostart.py"" --uninstall"; WorkingDir: "{app}"; RunOnceId: "RemoveCampusNetworkAutostart"; Flags: runhidden

[Code]
function EdgeInstalled(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf32}\Microsoft\Edge\Application\msedge.exe')) or
    FileExists(ExpandConstant('{pf}\Microsoft\Edge\Application\msedge.exe')) or
    FileExists(ExpandConstant('{localappdata}\Microsoft\Edge\Application\msedge.exe'));
end;

function InitializeSetup(): Boolean;
begin
  Result := EdgeInstalled();
  if not Result then
    MsgBox('BNU-ToolBox 需要 Microsoft Edge。请先安装或修复 Windows 11 自带的 Edge。', mbError, MB_OK);
end;
