# Serial Hub — CLAUDE.md

**포트 통합 시리얼 모니터** (PySide6 + pyserial, Python 3.12, Windows). VS Code Serial
Monitor + Tera Term + MobaXterm 를 한 창으로 대체한다. v1.6.0, 원 개발 위치는
`c:\ht\scripts\serial_hub` (2026-08 여기로 이관, git 이력은 `8f07a9b` v1.2.1 import 부터).

현황·미검증 목록의 정본은 `STATUS.md`, 사용자 문서는 `README.md`(영)/`README.ko.md`(한).
이 파일은 **작업할 때 지켜야 할 규칙과, 실제 버그로 배운 함정**만 담는다.

## 자주 쓰는 명령

```bash
# 실행 (소스)
python app.py                 # 마지막 프로파일로 기동
python app.py --demo          # 포트 없이 화면 확인 (합성 로그)
python app.py --selfcheck     # 빌드/환경 점검 (COM 열거·Qt·쓰기 경로)

# 검증 — 수정 후 반드시 셋 다
python selftest.py --gui      # 단위 + offscreen GUI (~403)
python uitest.py              # 가상 3콘솔 사용자 시나리오 (~179)
python -m ruff check . --select E,F,W,B,ARG --line-length 110

# 문서·빌드 (부모 폴더에서 -m 으로 돌려도 된다: cd C:\project && python -m serial_hub.build_exe)
python make_docs.py           # 사용설명서 HTML 재생성 — ★실제 디스플레이 필요 (아래 함정 참조)
python build_exe.py --zip     # PyInstaller 폴더형 + 포터블 zip → dist/
python build_installer.py     # Inno Setup 설치본 → dist/
```

★ **폴더 이름이 곧 패키지 이름이다.** `selftest.py` 등이 `__package__ = "serial_hub"` 로
상대 임포트를 하므로, 클론/체크아웃 폴더명은 반드시 `serial_hub` 여야 한다
(CI 도 `path: serial_hub` 로 명시 체크아웃).

## 아키텍처 (지켜야 할 경계)

- **`core/` 는 Qt 를 모른다.** 순수 Python + pyserial. UI 는 `ui/` 가 50ms QTimer 1개로
  core 상태를 pull 한다 — 라인마다 시그널을 쏘면 firehose 에서 이벤트 큐가 포화된다.
- **파일 I/O 는 ring `_lock` 밖에서** (`logstore.py` 의 `_service_lock`). 느린 디스크가
  수신 스레드를 막으면 COM RX 가 넘친다.
- **PyInstaller 진입점은 `launcher.py`** (절대 임포트). `app.py` 를 직접 얼리면 상대
  임포트를 정적 분석 못 해 패키지가 번들에서 빠진다 — 그걸 잡는 게 `--selfcheck` 다.
- 브리지(`core/bridge.py`, 127.0.0.1:3341)는 `allow_reuse_address` 를 켜면 안 된다 —
  Windows 의 SO_REUSEADDR 는 이중 bind 를 허용해 남의 인스턴스로 명령이 샐 수 있다.

## 제품 동작 원칙 (사용자와 합의된 것 — 바꾸지 말 것)

- **probe 는 실명령을 보내지 않는다.** 어느 콘솔에도 없는 무해 토큰 1개를 보내고
  unknown-command 응답 서명으로 역할 판정 (`Error <cmd>:` = Matter shell,
  `Invalid command` = user_cli). 에코가 없으면 fail-closed. 오배정된 COM 에서
  `swtimer ... set` 같은 실명령이 실행되는 사고를 막기 위한 것이다.
- **명령 대상은 활성 포트 전부.** 장비마다 입력 받는 콘솔이 다르므로 로그 전용으로
  보이는 포트도 막지 않는다. 오지정은 unknown-command 힌트가 잡는다.
- **기록은 수동 시작.** 연결해도 파일이 안 생긴다. [⏺ Start log] → 저장 위치·파일명
  확인 모달(**누를 때마다** 뜬다) → 시작. 테스트/자동화는 `start_logging(ask=False)`.
- **로그 파일은 첫 줄이 올 때 lazy 생성 + 2초마다 fsync.** 미리 만들면 0바이트 파일이
  쌓이고, sync 없으면 다른 편집기에서 빈 파일로 보인다.
- **로그 설정은 [OK] 를 눌러야 적용** (`log_page.py` 의 commit/revert). 입력 즉시
  반영하면 글자 칠 때마다 빈 파일이 생긴다.
- **NUL 등 제어문자는 `<00>` 로 치환해 기록** — 한 바이트만 섞여도 편집기가 파일 전체를
  바이너리로 보고 열기를 거부한다.
- **redact 는 화면·로그파일·프로파일 JSON 공통, 시리얼 wire 만 원문.** 프로파일은 벤치 간
  복사물이라 command_history·scratchpad 도 저장 시 마스킹.
- **콘솔 수 가변 (1~3 UART 모델).** `Profile.active_roles()` 기준으로 화면·상태필·명령
  대상·로그·카운터에서 뺀다. 패널/필 위젯은 **파괴하지 않고 숨기기만** 한다 — 다시 켤 때
  스크롤백이 살아야 하고, 도중에 위젯을 지우면 tick() 이 죽은 객체를 만진다.
- **포트 표시 이름 rename**: 콤보·목록은 `itemData` = role(내부 식별자) 고정,
  `itemText` = 표시명. 이름을 바꿔도 전송 대상·저장 키가 흔들리면 안 된다.
- 사용자 문구는 **존댓말**. 카피라이트는 `psy-bari`.

## i18n 규칙 (v1.2.x~1.3.0 에서 실제 버그로 확립)

- 사용자에게 보이는 문자열은 전부 `tr('한국어 원문')` — **한국어 문장이 곧 키**,
  영어표는 `core/i18n_en.py` 한 곳. 없는 키는 한국어로 열화(빈 화면 방지).
  기본 표시 언어는 **영어** (`DEFAULT_LANGUAGE = "en"`, v1.3.0 에서 변경됨).
- 인자는 f-string 금지 — `tr('… {0} …').format(x)` (f-string 은 값이 박혀 키가 안 된다).
- ★**모듈 최상위 상수에서 `tr()` 금지.** 임포트 시점에 굳는데 언어 설정은 그 뒤다
  (LAYOUT_LABELS 사례 — 함수 `layout_labels()` 로 바꿈). `app.py` 는 UI 모듈 임포트
  **전에** `set_language()` 를 부른다.
- ★**저장되는 식별자는 번역 금지.** `HIGHLIGHT_COLORS` 키는 프로파일 JSON 에 들어가는
  식별자다 — 표시할 때만 `tr(name)`, `itemData` 는 원본. 언어 다른 PC 간 프로파일
  복사가 깨진다.
- 위 두 규칙 + 번역 누락 + `{0}` 자리표시자 불일치는 **selftest 가 자동 검사**한다.
  문구를 추가하면 `i18n_en.py` 도 같이 채울 것.
- 도움말 HTML 은 **파일명이 번역 키다** (`SerialHub_사용설명서.html` ↔
  `SerialHub_UserGuide_en.html`) — `open_help` 에 언어 분기가 없다.

## Qt 함정 (전부 실기 크래시/오동작으로 배운 것)

- **`processEvents()` 는 DeferredDelete 를 처리하지 않는다** (`app.exec()` 안에서만).
  offscreen 테스트에서 `deleteLater()` 한 위젯이 계속 살아 있어, 실기에서만
  "Internal C++ object already deleted" 로 죽는 버그를 못 잡는다. 그래서 selftest 의
  `pump()` / uitest 의 `spin()` 이 `sendPostedEvents(None, DeferredDelete)` 를 같이
  부른다. 실사례 = `_apply_layout` 이 탭·병합 모드에서 `_splitters` 를 안 비워 죽은
  QSplitter 재사용 → 레이아웃 전환 크래시 (v1.0.1).
- **편집 가능한 QComboBox 는 키 전달 경로가 두 갈래다.**
  ① 마우스로 눌러 편집 = lineEdit 포커스 → 이벤트 필터를 탄다. 단 QLineEdit 이 Return
  을 ignore() 해 콤보가 되돌려주므로 `returnPressed` 가 2번 난다 → 필터에서 소비.
  ② `setFocus()` (Ctrl+F/Ctrl+`) = **콤보 자신** 포커스 → `lineEdit->event()` 직접
  호출이라 **이벤트 필터를 안 탄다** → `keyPressEvent` 오버라이드 필수 (v1.0.3).
- **Enter 를 QShortcut 으로 잡지 말 것** — 포커스 위젯보다 먼저 먹어 검색창
  returnPressed 가 사라진다. 콘솔 본문의 Enter(스크롤 해제)는 `view` 이벤트 필터로.
- **QSS 에 폰트 룰 금지** — repolish(레이아웃 전환 등)마다 `setFont()` 줌이 초기화된다.
  콘솔 폰트는 `ConsolePane.set_font_size()` 코드로만. 다만 전역 `QWidget{font-size}` 는
  남아 있어, **새로 만든 pane 은 도크를 붙여 show() 한 뒤에** 폰트를 걸어야 한다 —
  먼저 걸면 첫 polish 가 13px 로 덮어 새 창만 다른 크기로 뜬다 (v1.6.0 실사용 신고).
- **Ctrl+휠 확대는 위젯마다 달지 말 것.** 실제 마우스는 `view` 가 아니라 `viewport()` 에
  닿고, 스크롤바·입력칸·제목줄도 저마다 다른 위젯이라 창이 늘 때마다 구멍이 난다.
  `ui/wheel_zoom.py` 필터를 QApplication 에 걸어 **어느 pane 안이냐**로만 판정한다.
- **도크 제목줄의 X·분리 아이콘은 QSS 로 색을 못 바꾼다** (`titlebar-close-icon` 은 이미지
  교체 전용, `url(none)` 은 아이콘을 지운다). `theme.dock_button_icon()` 으로 팔레트 색을
  직접 그려 넣고, 스타일이 바뀌면 Qt 가 되돌리므로 테마 전환 뒤 다시 칠한다.
- 상태필/REC 버튼처럼 50ms 마다 갱신되는 것은 값이 같으면 `setStyleSheet` 를 건너뛴다
  (repolish 비용).

## 테스트 작성 규칙

- 키 입력 검증은 슬롯 직접 호출 금지 — `send_key()` 로 **실제 QKeyEvent** 를,
  그것도 lineEdit 을 찍지 말고 **실제 포커스 위젯**(콤보)으로 보낼 것. QComboBox ②경로
  버그는 lineEdit 에 보내면 재현되지 않는다.
- 가상 DUT(`uitest.py` VirtualDut)의 응답 문자열은 실펌웨어 디스패처
  (`MainLoopDefault.cpp:189` / `user_cli.c:527`) 형식과 동일하게 유지할 것 — probe
  판정이 이 서명에 걸려 있다.
- 수정을 되돌려 **테스트가 실패하는 것까지 확인**하고 복구하는 것이 이 저장소의 관례다.
- `Date.now` 류 주의사항은 없고, offscreen 에서 `app.focusWidget()` 은 None 일 수 있다
  — 위젯을 직접 지정해 두 경로를 각각 검증한다.

## 빌드·릴리스 체크리스트

1. 버전은 **두 곳**: `__init__.py` `__version__` + `installer.iss` `AppVersion`
   (README 의 설치본 파일명도). 문서 푸터는 `make_docs.py` 가 `__version__` 을 읽는다.
2. `python make_docs.py` — ★**offscreen 불가, 실제 Windows 디스플레이 필요**
   (offscreen 은 폰트가 없어 캡처가 전부 두부 글자가 된다. `QT_QPA_PLATFORM=windows` 강제).
3. `build_exe.py --zip` → `build_installer.py`. 산출물은 `dist/` (gitignore).
4. 빌드된 exe 로 `--selfcheck` (exit 0 확인). 설치/제거 사이클도 무인으로 확인:
   `Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=...` → `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES`.
5. ★**실행 중인 SerialHub.exe 가 있으면 설치가 초기화 단계에서 막힌다.** 또 방금
   실행했던 exe 를 곧바로 무인 제거하면 이미지 락으로 일부 파일이 남는다(Inno 가
   재부팅으로 미룸) — 실행 안 한 상태의 install→uninstall 은 깨끗하다.
6. Inno 대화상자는 `SuppressibleMsgBox` 만 사용 (`MsgBox` 는 `/SUPPRESSMSGBOXES` 로
   억제되지 않아 무인 제거가 영원히 대기한다). 관리자 설치 후 실행은 `runasoriginaluser`.

## 기타 함정

- **ruff E501 은 동아시아 전각 문자를 2칸으로 센다** — `len()` 과 다르다. 한글 긴 문자열을
  접을 때는 `unicodedata.east_asian_width` 기준으로 폭을 재야 한다.
- `diag.*()` 로그와 프로파일 키·`setObjectName`·QSS 는 번역 대상이 아니다.
- 진단은 `%LOCALAPPDATA%\SerialHub\app.log`(1MB×3 회전) + `crash.log`. 문제 보고를 받으면
  "도움말 → 진단 폴더 열기" 로 두 파일을 받는 것이 사후 분석 경로다.
- 원 개발 벤치의 대응 메모리는 `~/.claude/projects/c--ht/memory/project_serial_hub_tool.md`
  (이 저장소 밖, c:\ht 워크스페이스 세션용).
