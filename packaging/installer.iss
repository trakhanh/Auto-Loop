; Bộ cài KT Loop Station — biên dịch bằng Inno Setup 6 (packaging\build.py tự gọi và truyền các biến dưới đây).
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppDir
  #define AppDir "..\dist\KTLoopStation"
#endif
#ifndef StageDir
  #define StageDir "..\build\stage"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif
#define AppName "KT Loop Station"
#define AppExe "KTLoopStation.exe"

[Setup]
; AppId cố định: bản mới cài đè lên bản cũ thay vì cài thêm một bản nữa
AppId={{A25D804B-CA5F-4CAE-9B06-20BFA44FFC13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Khánh Trà
AppCopyright=By Khánh Trà
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} — bộ cài đặt
; cài cho riêng người dùng (không cần quyền quản trị); có thể chọn cài cho mọi tài khoản
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=KTLoopStation-Setup-{#AppVersion}
SetupIconFile=..\loopstation\ui\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardSizePercent=110
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "vi"; MessagesFile: "compiler:Default.isl,Vietnamese.isl"

[Types]
Name: "full"; Description: "Cài đầy đủ (kèm bộ mẫu test để tập dùng)"
Name: "compact"; Description: "Chỉ cài app"
Name: "custom"; Description: "Tự chọn"; Flags: iscustom

[Components]
Name: "main"; Description: "KT Loop Station (app + FFmpeg)"; Types: full compact custom; Flags: fixed
Name: "samples"; Description: "Bộ mẫu test: video, nhạc, tiếng nền, 2 dự án mẫu (~50 MB)"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng trên màn hình nền"; GroupDescription: "Biểu tượng:"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "{#StageDir}\Mau-Test\*"; DestDir: "{app}\Mau-Test"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: samples

[Dirs]
Name: "{app}\Mau-Test\Xuat"; Components: samples

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Ghép, loop video và nhạc"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; Comment: "Ghép, loop video và nhạc"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Mở {#AppName} ngay"; Flags: nowait postinstall skipifsilent
; cập nhật từ trong app (/SILENT /RELAUNCH=1): cài xong tự mở lại app
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: ShouldRelaunch

[UninstallDelete]
; chỉ xoá video thử xuất trong bộ mẫu; dự án, video đã xuất ở chỗ khác và dữ liệu app (%LOCALAPPDATA%\KTLoopStation)
; được giữ nguyên
Type: filesandordirs; Name: "{app}\Mau-Test\Xuat"

[Code]
function ShouldRelaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;
