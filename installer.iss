; Serial Hub 설치 프로그램 (Inno Setup 6)
;
;   빌드: python build_installer.py
;   또는: ISCC.exe installer.iss
;
; 입력은 build_exe.py 가 만든 dist\SerialHub\ 폴더다.
; 기본은 **사용자 단위 설치**라 관리자 권한이 필요 없다 — 사내 PC 에서 UAC 에
; 막히지 않는 것이 벤치 툴에는 더 중요하다. 설치 시작 시 "모든 사용자" 를 고를 수도 있다.

#define AppName "Serial Hub"
#define AppVersion "1.2.1"
#define AppPublisher "bari-psy77"
#define AppExe "SerialHub.exe"

[Setup]
; 업그레이드 시 같은 항목으로 인식되도록 고정 GUID
AppId={{7C4A1E52-9B3D-4E18-A6F1-2D5C8B0A7431}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\SerialHub
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=assets\serialhub.ico
OutputDir=dist
OutputBaseFilename=SerialHub_Setup_{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
DisableProgramGroupPage=no
DisableDirPage=no
ShowLanguageDialog=auto
; 사용자 단위 설치가 기본 — 시작 화면에서 "모든 사용자" 로 바꿀 수 있다
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
InfoBeforeFile=installer_info.txt

[Languages]
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ko.DesktopIcon=바탕 화면에 바로가기 만들기
ko.DemoIcon=데모 모드 바로가기도 만들기 (포트 없이 화면 확인)
ko.RunSelfcheck=설치 상태 점검 실행 (권장)
ko.LaunchApp={#AppName} 실행
ko.KeepData=설정과 프로파일을 남겨 두겠습니까?%n%n[예] 를 누르면 다음에 다시 설치할 때 그대로 쓸 수 있습니다.%n(모든 사용자용으로 설치했다면 다른 계정의 설정은 지워지지 않습니다)
ko.LogPageTitle=로그 저장 위치
ko.LogPageSubtitle=수집한 시리얼 로그를 어디에 저장할까요?
ko.LogPageDesc=포트에 연결하면 로그가 이 폴더 아래 날짜별(MMDD) 폴더에 자동 저장됩니다.%n나중에 프로그램의 [설정 > 로그 설정] 에서 언제든 바꿀 수 있습니다.
en.LogPageTitle=Log location
en.LogPageSubtitle=Where should captured serial logs be stored?
en.LogPageDesc=Logs are saved under this folder in per-date (MMDD) subfolders.%nYou can change it any time in Settings > Log.
en.DesktopIcon=Create a desktop shortcut
en.DemoIcon=Also create a demo-mode shortcut (no serial port needed)
en.RunSelfcheck=Run installation check (recommended)
en.LaunchApp=Launch {#AppName}
en.KeepData=Keep your settings and profiles?%n%n[Yes] lets a future install reuse them.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "demoicon"; Description: "{cm:DemoIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; build_exe.py 산출물 전체. 실행 중 생기는 파일(프로파일·로그)은 제외한다
Source: "dist\SerialHub\*"; DestDir: "{app}"; \
    Excludes: "profiles\*,*.log,selfcheck.txt,where.txt"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; DestName: "README.md"; Flags: ignoreversion
Source: "README.ko.md"; DestDir: "{app}"; DestName: "README.ko.md"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} (데모 모드)"; Filename: "{app}\{#AppExe}"; Parameters: "--demo"; Tasks: demoicon
Name: "{group}\설치 상태 점검"; Filename: "{app}\{#AppExe}"; Parameters: "--selfcheck"
Name: "{group}\사용 설명서"; Filename: "{app}\README.md"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{autodesktop}\{#AppName} (데모)"; Filename: "{app}\{#AppExe}"; Parameters: "--demo"; Tasks: demoicon

[InstallDelete]
; 업그레이드 설치 시 옛 버전의 _internal 을 통째로 비운다. 새 파일을 덮어쓰기만 하면
; 없어져야 할 옛 Qt/파이썬 모듈이 남아 로딩 충돌·불가해한 크래시를 만든다.
; (UninstallDelete 는 제거 시에만 돈다 — 업그레이드에는 관여하지 않는다)
Type: filesandordirs; Name: "{app}\_internal"

[Run]
; 사용자가 고른 로그 위치를 앱 설정에 기록한다 (이미 있는 프로파일은 건드리지 않는다).
; ★runasoriginaluser 필수 — 관리자 모드 설치에서는 [Run] 이 승격 계정으로 돌아
;   설정이 실제 사용자가 아니라 관리자 계정의 %LOCALAPPDATA% 에 기록된다.
Filename: "{app}\{#AppExe}"; Parameters: "--set-log-dir ""{code:GetLogDirArg}"""; \
    StatusMsg: "설정을 기록하는 중..."; Flags: runhidden waituntilterminated runasoriginaluser
Filename: "{app}\{#AppExe}"; Parameters: "--selfcheck"; Description: "{cm:RunSelfcheck}"; \
    Flags: postinstall skipifsilent nowait
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; \
    Flags: postinstall skipifsilent nowait unchecked

[UninstallDelete]
; 설치 시점에 없던 실행 산출물 + 파일을 지운 뒤 남는 빈 폴더 정리.
; 순서가 곧 처리 순서다 — 깊은 곳부터 적는다.
Type: files; Name: "{app}\selfcheck.txt"
Type: files; Name: "{app}\where.txt"
; _internal 은 전부 우리가 설치한 것이라 통째로 지워도 안전하다 (빈 하위 폴더가 남는 것 방지)
Type: filesandordirs; Name: "{app}\_internal"
; 수집한 로그는 시험 증적이라 지우지 않는다 — 비어 있을 때만 폴더를 치운다
Type: dirifempty; Name: "{app}\logs"
Type: dirifempty; Name: "{app}"

[Code]
var
  LogDirPage: TInputDirWizardPage;
  LogDirTouched: Boolean;

// 로그 위치 기본값 = 설치 위치 아래 logs.
// 특정 PC 의 개인 경로를 기본값으로 두지 않는다. 다만 관리자 모드로 Program Files
// 에 설치하면 일반 사용자 권한으로는 그 아래에 못 쓰므로 %LOCALAPPDATA% 로 잡는다.
function DefaultLogDir(): String;
begin
  // 관리자(모든 사용자) 모드에서는 {localappdata} 가 **승격 계정** 으로 전개돼
  // 실제 사용자와 다른 폴더를 가리킨다 — 사용자 무관한 공용 경로를 기본값으로 쓴다.
  if IsAdminInstallMode() then
    Result := ExpandConstant('{commonappdata}\SerialHub\logs')
  else
    Result := AddBackslash(WizardDirValue) + 'logs';
end;

// 업그레이드 설치라면 기존 설정의 로그 위치를 그대로 이어 쓴다 —
// 무심코 [다음] 을 눌러 사용자가 고른 D:\benchlogs 가 덮어써지면 안 된다.
function ExistingLogDir(): String;
var
  Lines: TArrayOfString;
  I, P: Integer;
  Text: String;
begin
  Result := '';
  if not LoadStringsFromFile(ExpandConstant('{localappdata}\SerialHub\settings.json'), Lines) then
    Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    P := Pos('"log_base_dir"', Lines[I]);
    if P > 0 then
    begin
      Text := Copy(Lines[I], P + 14, Length(Lines[I]));
      P := Pos(':', Text);
      if P > 0 then
      begin
        Text := Trim(Copy(Text, P + 1, Length(Text)));
        StringChangeEx(Text, '\\', '\', True);
        StringChangeEx(Text, '"', '', True);
        StringChangeEx(Text, ',', '', True);
        Result := Trim(Text);
      end;
      Exit;
    end;
  end;
end;


procedure LogDirEdited(Sender: TObject);
begin
  LogDirTouched := True;
end;

procedure InitializeWizard();
begin
  LogDirTouched := False;
  LogDirPage := CreateInputDirPage(wpSelectProgramGroup,
    ExpandConstant('{cm:LogPageTitle}'),
    ExpandConstant('{cm:LogPageSubtitle}'),
    ExpandConstant('{cm:LogPageDesc}'),
    False, '');
  LogDirPage.Add('');
  LogDirPage.Edits[0].OnChange := @LogDirEdited;
end;

// 설치 폴더는 이 페이지보다 앞에서 정해진다 — 사용자가 직접 고치기 전까지는
// 설치 위치를 따라가게 둔다 (설치 폴더를 바꾸면 로그 기본값도 같이 바뀐다)
procedure CurPageChanged(CurPageID: Integer);
var
  Existing: String;
begin
  if (LogDirPage <> nil) and (CurPageID = LogDirPage.ID) and (not LogDirTouched) then
  begin
    Existing := ExistingLogDir();          // 업그레이드면 기존 설정 우선
    if Existing <> '' then
      LogDirPage.Values[0] := Existing
    else
      LogDirPage.Values[0] := DefaultLogDir();
    LogDirTouched := False;
  end;
end;

function GetLogDir(Param: String): String;
begin
  if LogDirPage = nil then
    Result := DefaultLogDir()
  else
    Result := LogDirPage.Values[0];
end;

// 값이 `D:\` 처럼 백슬래시로 끝나면 `--set-log-dir "D:\"` 의 `\"` 가 escape 로 먹혀
// 앱에 `D:"` 가 전달된다. 루트가 아니면 후행 백슬래시를 떼고, 루트면 `.` 을 붙인다.
function GetLogDirArg(Param: String): String;
begin
  Result := GetLogDir('');
  if (Length(Result) > 0) and (Result[Length(Result)] = '\') then
  begin
    if Length(Result) <= 3 then
      Result := Result + '.'
    else
      Result := Copy(Result, 1, Length(Result) - 1);
  end;
end;

// 고른 폴더를 미리 만들어 둔다 — 못 만들면 그 자리에서 알려준다
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Target: String;
begin
  Result := True;
  if (LogDirPage <> nil) and (CurPageID = LogDirPage.ID) then
  begin
    Target := LogDirPage.Values[0];
    if Target = '' then
    begin
      SuppressibleMsgBox('로그를 저장할 폴더를 지정하세요.', mbError, MB_OK, IDOK);
      Result := False;
    end
    else if not ForceDirectories(Target) then
    begin
      SuppressibleMsgBox('이 폴더를 만들 수 없습니다:' #13#10 + Target + #13#10#13#10
                         + '다른 위치를 고르세요.', mbError, MB_OK, IDOK);
      Result := False;
    end;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine
          + '로그 저장 위치:' + NewLine + Space + GetLogDir('') + NewLine + NewLine
          + MemoGroupInfo + NewLine + NewLine + MemoTasksInfo;
end;

// 제거할 때 사용자 데이터(프로파일·설정)를 지울지 물어본다.
// 묻지 않고 지우면 벤치별 COM 매핑을 다시 만들어야 한다.
procedure WipeDataDir(DataDir: String);
begin
  DelTree(DataDir + '\profiles', True, True, True);
  DeleteFile(DataDir + '\settings.json');
  DeleteFile(DataDir + '\crash.log');
  DeleteFile(DataDir + '\selfcheck.txt');
  DeleteFile(DataDir + '\where.txt');
  RemoveDir(DataDir);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppData, Portable: String;
  HasData: Boolean;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // 설정은 %LOCALAPPDATA%\SerialHub 에 있고, portable.txt 를 둔 경우만 설치 폴더에 있다.
    // ★관리자 모드로 제거하면 {localappdata} 는 승격 계정 폴더라 실제 사용자 데이터에
    //   닿지 못한다 — 지우지 못할 뿐 파괴는 아니므로, 문구로 사실만 알린다.
    AppData := ExpandConstant('{localappdata}\SerialHub');
    Portable := ExpandConstant('{app}');
    HasData := DirExists(AppData + '\profiles') or FileExists(AppData + '\settings.json')
            or DirExists(Portable + '\profiles') or FileExists(Portable + '\settings.json');
    if HasData then
    begin
      // SuppressibleMsgBox 여야 무인 제거(/VERYSILENT /SUPPRESSMSGBOXES)가 멈추지 않는다.
      // 그냥 MsgBox 를 쓰면 대답할 사람이 없어 영원히 대기한다. 무인 시 기본값은
      // IDYES = "설정 남김" — 묻지 못했으면 지우지 않는 쪽이 안전하다.
      if SuppressibleMsgBox(ExpandConstant('{cm:KeepData}'), mbConfirmation,
                            MB_YESNO, IDYES) = IDNO then
      begin
        WipeDataDir(AppData);
        WipeDataDir(Portable);
      end;
    end;
    // 수집한 로그는 사용자가 고른 위치에 그대로 둔다 — 시험 증적이라 지우면 안 된다
  end;
end;
