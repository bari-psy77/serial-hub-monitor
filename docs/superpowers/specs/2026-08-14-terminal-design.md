# 내장 터미널 (ConPTY) 설계

- 날짜: 2026-08-14
- 상태: 사용자 승인됨 (방식 = ConPTY 완전 터미널, 의존성 pywinpty + pyte 승인,
  기본 셸 = PowerShell, 시작 폴더 = 사용자 홈)
- 근거 요청: "PowerShell/터미널을 따로 열어야 하는 불편 — 기본 view 창에 같이,
  관리자 모드 오픈도"

## 1. 목적

메인 창 안에서 진짜 터미널(PowerShell)을 쓴다. ConPTY(pywinpty) + VT 에뮬레이터(pyte)
조합이므로 색·커서 이동·화면 지움·TUI 까지 실제 터미널과 같은 화면이 나온다.
관리자(UAC 승격) 셸은 임베드가 불가능하므로(승격 프로세스의 stdio 를 잡을 수 없다)
"관리자 PowerShell 열기" 는 외부 승격 창을 띄운다.

## 2. 확정 사항

| 항목 | 내용 |
|---|---|
| 의존성 | `pywinpty`(3.x, Windows 전용 — 환경 마커) + `pyte`(순수 파이썬) |
| 기본 셸 / 시작 폴더 | `powershell.exe`, 사용자 홈 |
| 배치 | 뷰어와 같은 하단 QDockWidget — 도킹 + 플로팅, 여러 개 가능 |
| 관리자 모드 | ShellExecuteW `runas` 로 외부 승격 PowerShell 창 |
| 미설치 폴백 | pywinpty/pyte 가 없으면 크래시 대신 설치 안내 문구 |

## 3. 구성요소

### 3.1 core/terminal.py (Qt 비의존)

- `TERMINAL_AVAILABLE: bool` / `TERMINAL_ERROR: str` — import 가드 결과.
- `TerminalBuffer(cols, rows, history=5000)` — pyte 래퍼. **플랫폼 무관, CI 테스트 대상.**
  - `feed(data: str)` — VT 스트림 해석 (락 보호)
  - `snapshot() -> Frame` — `Frame(rows: list[list[Run]], cursor: (x, y, visible),
    generation: int)`. `Run = (text, fg, bg, bold, reverse)` — 같은 속성 연속 구간을
    합쳐 그리기 비용을 줄인다. generation 은 feed 마다 증가 — UI 는 값이 같으면
    그리기를 건너뛴다 (50ms tick 원칙과 같은 pull 모델).
  - `resize(cols, rows)`, `page_up()/page_down()` (HistoryScreen 페이징),
    `text() -> str` (화면 전체 복사용)
- `TerminalSession(argv=None, cwd=None, cols=120, rows=30)` — pywinpty 구동.
  - reader 데몬 스레드가 `proc.read()` → `buffer.feed()`. EOF/예외 = 종료로 기록.
  - `write(text)`, `resize(cols, rows)`, `alive`, `exit_status`, `close()`,
    `restart()` — 같은 argv/cwd 로 새 프로세스.
  - argv 기본 `["powershell.exe"]`, cwd 기본 사용자 홈.
- `launch_admin_shell(cwd=None) -> bool` — `ShellExecuteW(None, "runas",
  "powershell.exe", "-NoExit", cwd, SW_SHOWNORMAL)`. 사용자가 UAC 를 거부하면 False.

### 3.2 ui/terminal_pane.py

- `TerminalPane(QWidget)` — 모노스페이스 그리드 렌더러.
  - `paintEvent`: Frame 의 run 단위로 배경/전경을 칠한다. pyte 색 이름·256색 인덱스를
    QColor 로 매핑(기본 전경/배경은 테마 색). 커서는 블록으로 반전.
  - `pump()`: session.buffer.generation 이 바뀌었을 때만 `update()` — MainWindow 의
    50ms tick 이 부른다 (자체 타이머 없음).
  - `keyPressEvent`: 문자·Enter(`\r`)·Backspace(`\x7f`)·Tab·화살표/Home/End/
    Delete(`\x1b[…`)·Ctrl+문자(제어 바이트) → `session.write()`.
    `키 → 시퀀스` 변환은 순수 함수 `encode_key(key, text, modifiers) -> str` 로 분리해
    단위 테스트한다. Ctrl+V / Shift+Insert = 붙여넣기(클립보드 텍스트 전송).
    PageUp/PageDown = 스크롤백 페이징.
  - `inputMethodEvent`: 한글 등 IME 확정 문자열을 전송.
  - `resizeEvent`: 폰트 메트릭으로 cols/rows 계산 → `session.resize`.
  - 컨텍스트 메뉴: 화면 전체 복사 / 붙여넣기 / 재시작.
  - 프로세스가 죽으면 마지막 화면 위에 종료 코드 배너 + [재시작] 안내.
- `TerminalDock(QDockWidget)` — 상단 줄([관리자 PowerShell] [재시작]) + TerminalPane.
  닫으면 세션 종료 + WA_DeleteOnClose, `closed` 시그널 (뷰어 도크와 같은 관리 패턴).
  pywinpty/pyte 미설치면 pane 대신 설치 안내 라벨.

### 3.3 MainWindow

- 보기 메뉴: `터미널 열기` → `open_terminal()` (TerminalDock 생성, 하단 도킹,
  `terminal_docks` 리스트), `관리자 PowerShell 열기 (외부 창)` → `launch_admin_shell`.
- `tick()` 이 `terminal_docks` 의 pane.pump() 를 함께 돈다.
- 종료(closeEvent) 시 열려 있는 터미널 세션을 모두 close.

### 3.4 패키징

- `requirements.txt`: `pyte>=0.8`, `pywinpty>=2.0; sys_platform == "win32"`
  (리눅스 CI 가 깨지면 안 된다).
- `build_exe.py`: hiddenimports 에 `winpty`·`pyte` 추가 (PyInstaller 정적 분석 보강).

## 4. 동작 규칙

- 터미널은 시리얼 경로와 완전히 무관하다 — redact·LogStore 를 거치지 않는다
  (셸 화면은 로그 파일에 기록하지 않는다).
- 도크를 닫으면 셸 프로세스는 종료한다 (백그라운드 잔류 금지).
- 앱 종료 시에도 모두 종료. terminate 실패는 diag 에만 남긴다.
- 사용자 문구는 존댓말 + `tr()`.

## 5. 테스트 계획

- **selftest (플랫폼 무관)**: TerminalBuffer — SGR 색/굵게 run 병합, 커서 이동·화면
  지움 반영, generation 증가, resize, 스크롤백 페이징, `encode_key` 매핑
  (Enter/화살표/Ctrl+C/일반 문자).
- **selftest (Windows + pywinpty 있을 때만)**: TerminalSession 으로 `cmd /c echo` 왕복,
  종료 감지(exit_status), close 후 스레드 종료. 미설치/타 플랫폼이면 건너뛰고
  그 사실을 출력한다.
- **selftest --gui**: 스텁 세션(에코 루프백)으로 TerminalPane 렌더·키 전달·pump 검증.
  실제 pty 없이 돌므로 CI 안전.
- **uitest (Windows)**: 터미널 도크 열기 → `echo` 명령 타이핑 → 화면에 출력 확인 →
  도크 닫기 → 프로세스 종료 확인.
- i18n 신규 문구는 기존 selftest 가 자동 강제.

## 6. 범위 제외 (YAGNI)

- 마우스 텍스트 선택·부분 복사 (v1 은 화면 전체 복사)
- 셸 종류 설정 UI (기본 PowerShell 고정 — 요구 시 후속)
- 터미널 화면의 파일 로깅
- 관리자 셸 임베드 (UAC 경계상 불가)
