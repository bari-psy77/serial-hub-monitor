# 프로젝트 현황 (기준일: 2026-09-01)

## 개요

**Serial Hub (v1.4.0)** — VS Code Serial Monitor + Tera Term + MobaXterm를 한 창으로 대체하는 윈도우 데스크톱 시리얼 모니터(PySide6 + pyserial). 최대 3개 콘솔(User CLI / Matter log / Matter shell)을 동시에 띄우고, 필터드뷰·ANSI 색상·수동 시작 로깅·PSK/networkkey 마스킹·트리거(WDOG/HardFault)·프로파일·localhost 자동화 브리지를 제공한다. 1.4.0에서 **지난 로그 파일 뷰어**와 **내장 ConPTY 터미널**이 추가됐다. PyInstaller + Inno Setup으로 설치본을 만들고, **GitHub 릴리스로 배포한다** (설치본 + 포터블 zip, 항상 최신 하나만).

## 현재까지 진행 사항

- **테스트 실측(2026-09-01)**: `python selftest.py` → **237 passed**, `python selftest.py --gui` → **324 passed**, `python uitest.py` → **166 passed**. 합계 490건 전부 통과(`--gui` 는 core 를 포함하므로 324+166 로 센다). `ruff check . --select E,F,W,B,ARG --line-length 110` 클린.
- **배포 완료(2026-09-01)**: GitHub 릴리스 **`v1.4.0`** 에 설치본(`SerialHub_Setup_1.4.0.exe`, 35MB)과 포터블 zip(`SerialHub_20260901.zip`, 49MB)을 올렸다. `publish_release.py` 가 이 버전 설치본 + 가장 최신 zip 을 골라 올리고 **옛 릴리스는 지운다**(최신 하나만 유지). 산출물은 저장소에 넣지 않는다(`dist/` 는 gitignore). 인증은 GitHub CLI 또는 `GH_TOKEN` 1회용 토큰이고, 올리기 전에 **어느 계정으로 올리는지 출력**한다 — 이 벤치는 다른 회사 계정도 함께 쓰기 때문이다. README 2종의 다운로드 안내도 릴리스 페이지로 바꿨다.
- **1.4.0 신기능** (자세한 내역은 `CHANGELOG.md`):
  - **로그 저장 위치 옵션** — 날짜별(MMDD) 하위 폴더는 이제 선택이고 **기본은 로그 폴더에 바로 저장**. `LogStore.set_use_date_folder()` + 프로파일 `log_use_date_folder`.
  - **덮어쓰기 확인** — 기록 시작 전 `plan_paths()`로 생성될 경로를 미리 계산해 같은 이름이 있으면 덮어쓰기/이어쓰기/취소를 묻는다. 자동화(`ask=False`) 경로는 종전대로 조용히 이어쓴다.
  - **로그 뷰어**(`core/logfile.py` + `ui/log_viewer.py`) — 포트별/병합/plain 3형식을 파싱해 타임스탬프·출처·TX를 복원하고, `ConsolePane`이 쓰는 `pull_with_gap`/`last_seq` 계약만 구현한 읽기 전용 스토어로 기존 콘솔·필터 UI를 그대로 재사용한다. 여러 파일 시간순 병합, 소스별 체크박스, 결과 저장.
  - **내장 터미널**(`core/terminal.py` + `ui/terminal_pane.py`) — pywinpty(ConPTY) + pyte. 50ms tick에서 `generation` 비교로만 다시 그리는 pull 모델, 휠·스크롤바 스크롤백, 재시작 시 화면 리셋, 관리자 셸은 외부 승격 창.
  - **도크 정책** — 뷰어·터미널은 하단에서 **탭으로 묶이고**, 닫으면 `removeDockWidget`으로 공간을 즉시 반환한다.
- **실기 검증**: 터미널·뷰어·도크 동작을 **실제 디스플레이에서 스크린샷으로 확인**했다. 전각(한글) 정렬, PSReadLine 토큰 색, 배경색 블록, 휠 스크롤백, 재시작 후 깨끗한 화면, 탭 묶기, 닫은 뒤 레이아웃 복구, **Tab 자동완성**(`Get-Ch`→`Get-ChildItem`), **⛶ 최대화/복원**까지 눈으로 대조.
- **실기 신고로 잡은 것(2026-09-01)**: 터미널 **Tab 자동완성**이 Qt 의 포커스 이동에 먹히던 문제(`focusNextPrevChild` 차단), 떼어낸 도크를 키울 방법이 없던 문제(**툴바 ⛶ 버튼** — 창 장식에 네이티브 최대화 버튼을 다는 방식은 **실제 클릭 시 도크가 파괴돼** 폐기했다), 설치 프로그램의 데모 모드 항목 제거. 각각 실기에서 재현한 뒤 고쳤다.
- **빌드·설치 실측(2026-08-14)**: `build_exe.py --zip` → `dist/SerialHub/SerialHub.exe`(123MB) + 포터블 zip(49MB), `build_installer.py` → `dist/SerialHub_Setup_1.4.0.exe`(35MB). **빌드된 exe의 `--selfcheck`가 `=> usable`** — 이 PC의 실제 COM 4개(COM4·COM5·COM7·COM9)를 열거했고, 새로 추가한 **내장 터미널 항목도 `[OK]`**(프리즈된 번들 안에서 ConPTY 프로세스를 실제로 띄워 확인). 무인 설치→제거 사이클을 **영어·한국어 각각** 돌려 잔존물 0을 확인했다.
- **selfcheck 보강** — pywinpty/pyte는 임포트 가드 뒤에 있어 번들에서 빠져도 "설치해 주세요" 안내로만 보인다. 그 조용한 누락을 `--selfcheck`가 잡도록 항목을 추가했다(selftest가 항목 존재를 강제).
- **설치본 마감** — 시작 메뉴 항목을 `[CustomMessages]`로 옮겨 **양국어화**했고, `사용 설명서` 바로가기가 원본 마크다운이 아니라 **F1이 여는 HTML 가이드**를 가리키도록 고쳤다(가이드는 파일명이 곧 번역 키다).
- **문서** — `python make_docs.py`를 실제 디스플레이에서 돌려 **한/영 가이드를 v1.4.0으로 재생성**(각 815KB, 스크린샷 9장 내장). 로그 뷰어·내장 터미널 절이 새로 들어갔다. **`CHANGELOG.md` 신설**(1.4.0 + 1.3.0 소급).
- **구조**: `core/`(Qt 비의존 — `logstore.py`, `logfile.py`, `terminal.py`, `port.py`, `portscan.py`, `config.py`, `filters.py`, `session.py`, `bridge.py`, `ansi.py`, `diag.py`, `i18n.py`, `i18n_en.py`) · `ui/`(PySide6 — `main_window.py` 외 14모듈) · 진입점 `app.py`/`launcher.py` · 외부 스크립트용 `hub_client.py`.
- **i18n**: 한국어 원문이 곧 키이고 영어표는 `core/i18n_en.py` 한 곳. 누락·자리표시자 불일치·모듈 최상위 `tr()`·색 이름 고정을 selftest가 자동 검사한다. 기본 표시 언어는 영어.
- **소스 내 TODO/FIXME/XXX/HACK/NotImplemented 마커 0건.**

## 미완성 / 필요 사항

- **실제 시리얼 장비로 통신을 검증한 적이 없다 — 여전히 가장 큰 공백.** 이번 세션에서 `--selfcheck`로 **COM 포트가 실제로 열거된다는 것까지는 확인**했지만(COM4·COM5·COM7·COM9), 그 포트로 실제 데이터를 주고받은 적은 없다. 아래는 구현 완료·실기 미검증이다:
  - 물리 어댑터에서의 open/read/write(보율 처리, `timeout=0.05` 수신 루프, 실펌웨어 타이밍에서의 부분 라인 조립)
  - **케이블 분리·장비 리부트 시 자동 재접속** — 지금까지 발동시킨 것은 합성 `OSError`뿐이다
  - **역할 판별 probe** — 실 SDK의 미지원 명령 응답 서명 매칭에 걸려 있는데, 지금은 테스트가 스스로 써 넣은 문자열로만 확인됐다
  - **포트 점유자 진단** — Tera Term/VS Code가 COM을 잡고 있는 실제 상황에서 미검증
  - 실기 명령 송신·에코 왕복, NUL/제어바이트 처리와 실펌웨어 출력의 ANSI 렌더링
- **검증 기준 문서가 저장소에 없다**: `__init__.py`가 가리키는 `plans/serial-monitor/20260802-serial-monitor-design.md`가 없어, "실기로 무엇을 확인해야 완료인지"의 정본 목록을 복원할 수 없다.
- **`uitest.py`는 CI 밖**: 리눅스 offscreen 통과 여부가 미확인이라 의도적으로 제외돼 있다. 162건이 CI 회귀 감지에서 빠져 있다. 게다가 터미널 시나리오(S8d)는 **Windows 전용**이라 리눅스 CI에 넣어도 건너뛴다.
- **윈도우 전용 경로가 CI에서 전혀 안 돈다**: CI는 ubuntu뿐이라 `%LOCALAPPDATA%` 해소, 포터블 폴백, `list_ports_windows`, **pywinpty(ConPTY) 전 경로**가 미커버.
- **코드 서명 없음**: 서명 없는 35MB 설치본은 SmartScreen 경고를 맞는다.
- **릴리스 자동화는 없다(수동 배포)**: `publish_release.py` 는 **로컬에서 구운 산출물**을 올린다. 태그 푸시로 CI가 굽는 워크플로는 없다 — 윈도우 러너가 필요하고 프라이빗 레포 무료 분 예산이 걸려 있어 보류했다. 즉 **배포 전에 빌드를 잊으면 안 된다**(스크립트가 버전 불일치는 막아 준다).
- **`SerialHub.spec`에 절대 경로가 박혀 있다**(`C:\project\serial_hub\…`) — 다른 위치에 클론하면 깨진다. `build_exe.py`가 spec을 재생성하므로 커밋 유지 여부를 정해야 한다.
- **의존성 하한만 지정**: `requirements.txt`는 `PySide6>=6.6`, `pyserial>=3.5`, `pyte>=0.8`, `pywinpty>=2.0;win32` 네 줄이고 락파일·dev 의존성이 없다.
- **알려진 기능 한계(설계상 수용)**: redact는 저장 라인 단위라 비밀값이 라인 경계에 걸치면 마스킹되지 않는다. 언어 변경은 재시작 후 적용. 영어판 가이드는 한국어 UI 스크린샷을 공유한다. 터미널은 마우스 텍스트 선택을 지원하지 않는다(화면 전체 복사만).

## 차단 요소 (사용자 조치 필요)

1. **실제 시리얼 장비 + 그 장비가 물린 윈도우 PC** — 위 "실기 미검증" 항목 전부가 여기서만 닫힌다. **현재 최우선 차단 요소다.** (COM 포트 4개가 이 PC에 붙어 있는 것은 확인됐으니, 장비만 연결하면 바로 진행 가능하다.)
2. **설계문서 `plans/serial-monitor/20260802-serial-monitor-design.md` 제공(또는 §8 2~6 항목 재작성)** — 무엇을 검증해야 "완료"인지 정의가 없다.
3. **코드 서명 인증서 구매 여부** — 사지 않는다면 "SmartScreen 경고는 정상"이라는 안내를 배포 문서에 명시해야 한다. (배포 방식은 **GitHub 릴리스로 결정·시행됨** — 2026-09-01.)

## 다음 개발 우선순위

1. **실기 검증 세션 (반나절~1일 — 차단 요소 1·2 필요)**: 장비를 물린 상태에서 3콘솔 연결 → 명령 송신·에코 → **케이블 분리 후 재접속** → 다른 프로그램이 포트를 잡은 상태에서 점유자 진단 → 실펌웨어 응답으로 probe 역할 판별 대조. 발견되는 차이를 `core/port.py`·`core/portscan.py`에 반영하고 회귀 테스트로 고정. **다른 모든 항목보다 우선한다.**
2. **릴리스 자동화 (반나절, 선택)**: 지금은 로컬 빌드 → `publish_release.py` 수동 실행이다. 태그 푸시로 윈도우 러너가 굽고 올리게 하려면 무료 분 예산을 먼저 확인해야 한다.
3. **CI 커버리지 확장 (반나절)**: `uitest.py`를 offscreen에서 돌려보고 통과하면 CI에 추가(터미널 시나리오는 자동 skip), 윈도우 러너 잡을 붙여 `%LOCALAPPDATA%`·포터블 폴백·`list_ports_windows`·pywinpty 경로를 처음으로 CI에서 덮는다.
4. **정비 (틈틈이)**: `SerialHub.spec` 절대 경로 정리, `requirements.txt` 버전 고정 + 빌드 의존성 명시, redact 라인 경계 한계 완화책 검토, 터미널 마우스 선택·복사.
