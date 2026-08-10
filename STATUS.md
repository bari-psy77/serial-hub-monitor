# 프로젝트 현황 (기준일: 2026-08-11)

> 이 저장소에는 그동안 STATUS.md가 없었다. 형제 프로젝트들과 형식을 맞춘 첫 스냅샷이다.

## 개요

**Serial Hub (v1.3.0)** — VS Code Serial Monitor + Tera Term + MobaXterm를 한 창으로 대체하는 윈도우 데스크톱 시리얼 모니터(PySide6 + pyserial). 최대 3개 콘솔(User CLI / Matter log / Matter shell)을 동시에 띄우고, 필터드뷰·ANSI 색상·수동 시작 로깅·PSK/networkkey 마스킹·트리거(WDOG/HardFault)·프로파일·localhost 자동화 브리지를 제공한다. PyInstaller + Inno Setup으로 설치본을 만든다.

## 현재까지 진행 사항

- **테스트 실측(2026-08-11)**: `python selftest.py` → **153 passed, 0 failed**. `python selftest.py --gui` → **197 passed, 0 failed**. 합계 350건 전부 통과.
- **CI 도입(신규 `532075b`)**: `.github/workflows/ci.yml` — `main` push / `main` 대상 PR에서 ubuntu-latest(잡 상한 15분), Python 3.12(pip 캐시). **selftest의 두 절반을 모두 돌린다**(`python selftest.py`, `python selftest.py --gui`). 헤드리스 처리는 xvfb가 아니라 **잡 전체에 `QT_QPA_PLATFORM=offscreen`** — core 구간도 `ui.main_window`(PySide6 QtWidgets)를 임포트하기 때문이다. PySide6 휠이 링크하는 시스템 라이브러리(`libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1`)를 apt로 먼저 깐다. cron 스케줄은 없다(프라이빗 레포 무료 분 예산).
  - **체크아웃 경로 주의**: `selftest.py`가 `__package__ = "serial_hub"`로 상대 임포트를 하므로 **체크아웃 폴더 이름이 곧 패키지 이름**이다. 원격 이름이 `serial-hub-monitor`라 CI는 `path: serial_hub`로 명시해 체크아웃한다. 새로 클론하는 사람도 반드시 `serial_hub`로 받아야 한다.
- **구조**: `core/`(Qt 비의존 — `logstore.py` 링버퍼·파일 기록·회전·자정 롤오버, `port.py` 수신 스레드·재접속·probe, `portscan.py` COM 열거·점유자 추정·역할 판별, `config.py`, `filters.py`, `session.py`, `bridge.py` localhost JSON-Lines 서버(기본 3341), `ansi.py`, `diag.py`, `i18n.py`, `i18n_en.py`) · `ui/`(PySide6 — `main_window.py` 외 12모듈) · 진입점 `app.py`/`launcher.py` · 외부 스크립트용 `hub_client.py`.
- **i18n 완료(`99e0fa2`)**: 한국어/영어 2종, 영어가 **기본 표시 언어**. 번역표는 `core/i18n_en.py` 한 파일(약 330항목)이고, 한국어 원문이 곧 키라서 번역 누락 시 빈 문자열이 아니라 한국어로 열화된다. **커버리지가 테스트로 강제된다** — `selftest.py`가 `ui/`·`core/`·루트의 모든 `.py`를 AST로 훑어 `tr("…")` 리터럴을 수집한 뒤 누락 0건을 단언하고, 추가로 `{0}`/`{1}` 자리표시자 일치, **모듈 최상위 `tr()` 금지**(임포트 시점에 언어가 굳는 것 방지), 하이라이트 색 이름은 프로파일 JSON에 저장되므로 한국어 식별자 고정, 알 수 없는 언어 코드는 `en` 폴백까지 검사한다.
- **양국어 문서(`6a8c028`·`eb390ff`)**: `README.md` / `README.ko.md`, F1 도움말이 언어 설정을 따라간다. 구현 방식이 깔끔하다 — 가이드 **파일명 자체가 번역 키**라(`SerialHub_사용설명서.html` → `SerialHub_UserGuide_en.html`) `open_help`에 분기가 없다.
- **1.3.0 릴리스 준비(`9429d8b`)**: `__init__.py`의 `__version__`과 `installer.iss`의 `AppVersion`이 모두 `1.3.0`. 설치본에 README 2종을 함께 넣고, 빌드 시 가이드 HTML 2종을 `docs/`로 동봉한다.
- **빌드·설치 툴체인**: `build_exe.py`(PyInstaller, 기본 폴더형 — onefile은 기동 ~10초/112MB 압축해제라 비권장, 미사용 PySide6 모듈 약 25개 제외, `--zip` 포터블 아카이브) · `build_installer.py`(Inno Setup 6 `ISCC.exe` 구동, exe 없으면 자동 빌드) · `installer.iss`(고정 AppId, `PrivilegesRequired=lowest` 기본 사용자별 설치, x64, Windows 10+, 한국어·영어 `[Languages]`, 로그 위치 지정 마법사 페이지, 구 `_internal` 정리, 제거 시 설정 보존 여부 질문).
- **소스 내 TODO/FIXME/XXX/HACK/NotImplemented 마커 0건**. 대신 "왜 이렇게 했는지"를 설명하는 주석이 촘촘하다.

## 미완성 / 필요 사항

- **실제 시리얼 장비로 검증한 적이 없다 — 이 프로젝트의 가장 큰 공백.** 테스트의 모든 시리얼 I/O는 가짜다(`selftest.py`의 `FakeSerial`, `uitest.py`의 가상 3콘솔 DUT). 진단 로그 `app.log`(2026-08-10~08-11)에 남은 포트는 **COM97·COM98·COM99뿐**이고 전부 존재하지 않는 포트다. 즉 아래는 전부 **구현 완료·실기 미검증**이다:
  - 물리 어댑터에서의 실제 open/read/write(보율 처리, `timeout=0.05` 수신 루프, 실펌웨어 타이밍에서의 부분 라인 조립)
  - **케이블 분리·장비 리부트 시 자동 재접속** — 지금까지 발동시킨 것은 합성 `OSError`뿐이고, 실제 USB-시리얼 분리는 윈도우에서 다른 예외 형태로 온다
  - **역할 판별 probe**(`core/portscan.py`) — 실 SDK의 미지원 명령 응답 서명 매칭에 기능 전체가 걸려 있는데, 지금은 테스트가 스스로 써 넣은 문자열로만 확인됐다. 코드 주석도 SDK 업그레이드로 문자열이 바뀔 수 있음을 인정한다
  - **포트 점유자 진단** — Tera Term/VS Code가 COM을 잡고 있는 실제 상황에서 미검증(휴리스틱이며 `handle.exe`가 없는 환경)
  - **포트가 실제로 있는 PC에서의 COM 열거** — `app.py --selfcheck`가 존재하는 이유가 `list_ports()`의 예외 삼킴인데, 그 명령이 한 번도 실행된 적이 없다
  - 실기 명령 송신·에코 왕복, NUL/제어바이트 처리와 실펌웨어 출력의 ANSI 렌더링
  - **빌드된 exe·설치본의 클린 PC 설치 테스트**(`dist/`는 gitignore라 이 노트북 밖에 존재하지 않는다)
- **검증 기준 문서가 저장소에 없다**: `__init__.py`가 설계문서 `plans/serial-monitor/20260802-serial-monitor-design.md`를 가리키고 README·selftest가 "설계 §8의 2~6은 이 스크립트로 대체되지 않는다"고 적지만, **`plans/` 디렉터리 자체가 없다**. 즉 "실기로 무엇을 확인해야 하는지"의 정본 목록을 지금 복원할 수 없다.
- **사용설명서 HTML이 v1.2.1인 채로 1.3.0 설치본에 들어갔다**: `docs/SerialHub_UserGuide_en.html`·`docs/SerialHub_사용설명서.html` 모두 표기가 `v1.2.1`(생성 2026-08-10 10:11)인데 그 뒤 1.3.0으로 올렸다. 재생성(`python make_docs.py`)은 **실제 윈도우 디스플레이가 필요하다**(offscreen에서는 글자가 두부로 깨져 `QT_QPA_PLATFORM=windows`를 강제한다).
- **`uitest.py`는 CI 밖**: 리눅스 offscreen 통과 여부가 확인되지 않아 의도적으로 제외했다(ci.yml 주석). 가상 3콘솔 시나리오 134개 검사가 CI 회귀 감지에서 빠져 있다.
- **윈도우 전용 경로가 CI에서 전혀 안 돈다**: CI는 ubuntu뿐이라 `%LOCALAPPDATA%` 해소, 포터블 모드 폴백, `list_ports_windows`, 파일 열기 경로가 미커버.
- **코드 서명 없음**: `SerialHub.spec`의 `codesign_identity=None`, `installer.iss`에 `SignTool` 지시자 없음. 서명 없는 34MB 설치본은 SmartScreen 경고를 맞는다.
- **배포 경로가 없다**: 워크플로는 `ci.yml` 하나뿐이고 릴리스 워크플로가 없다. `dist/`는 gitignore라 **README가 안내하는 `dist/SerialHub_Setup_1.3.0.exe` 경로는 저장소를 클론한 사람에게 존재하지 않는다.**
- **설치본의 시작 메뉴 항목이 한국어 고정**: `[Languages]`/`[CustomMessages]`는 양국어인데 `[Icons]`는 `설치 상태 점검`·`사용 설명서`·`(데모 모드)`가 하드코딩돼 있다(앱 기본 언어는 이제 영어). 게다가 `사용 설명서` 항목이 F1이 여는 HTML 가이드가 아니라 `{app}\README.md`(원본 마크다운)를 가리킨다.
- **`SerialHub.spec`에 절대 경로가 박혀 있다**(`C:\project\serial_hub\…`, `pathex=['C:\\project']`) — 다른 위치에 클론하면 깨진다. `build_exe.py`가 spec을 재생성하므로 커밋 유지 여부를 정해야 한다.
- **CHANGELOG가 없다**: 1.3.0에서 무엇이 바뀌었는지는 커밋 제목에만 남아 있다.
- **의존성 미고정**: `requirements.txt`는 `PySide6>=6.6`, `pyserial>=3.5` 두 줄뿐이고 락파일·dev 의존성이 없다. 빌드 도구(`pyinstaller`, Inno Setup)는 README에 문장으로만 있다.
- **알려진 기능 한계(문서화됨, 설계상 수용)**: redact는 저장 라인 단위라 **비밀값이 라인 경계에 걸치면 마스킹되지 않는다**(연결 직후 첫 부분 라인, 개행 없는 프롬프트 부분 플러시). 줄 버퍼링은 "즉시 기록" 원칙을 깨므로 감수하고, 로그를 외부로 첨부하기 전 `wifi connect` 주변을 훑어보라고 안내한다. 언어 변경은 재시작 후 적용. 영어판 가이드는 한국어 UI 스크린샷을 공유한다.

## 차단 요소 (사용자 조치 필요)

1. **실제 시리얼 장비 + 그 장비가 물린 윈도우 PC** — 위 "실기 미검증" 항목 전부가 여기서만 닫힌다. 소유자만 접근 가능한 자원이고, 이것 없이는 재접속·probe·점유자 진단이 실제로 동작하는지 아무도 모른다. **현재 최우선 차단 요소다.**
2. **설계문서 `plans/serial-monitor/20260802-serial-monitor-design.md` 제공(또는 §8 2~6 항목 재작성)** — 코드·README가 이 문서를 실기 검증 기준으로 지목하는데 저장소에 없다. 무엇을 검증해야 완료인지 정의가 없으면 1번을 수행해도 "끝났다"고 말할 근거가 없다.
3. **배포 방식 결정** — GitHub Releases + 릴리스 워크플로를 만들 것인지, 아니면 계속 사내 공유 폴더로 직접 전달할 것인지. 지금은 README가 존재하지 않는 경로를 안내하는 상태라 어느 쪽이든 결정이 필요하다.
4. **코드 서명 인증서 구매 여부** — 구매하면 `installer.iss`에 `SignTool`, spec에 서명 설정을 넣는다. 사지 않는다면 "SmartScreen 경고는 정상"이라는 안내를 배포 문서에 명시해야 한다. 비용이 걸린 판단이라 소유자 결정 사항.
5. **가이드 HTML 재생성 실행(윈도우 데스크톱 세션 필요)** — `python make_docs.py`는 실제 디스플레이를 요구해 CI나 원격 세션에서 대신 돌려줄 수 없다. 1.3.0 설치본이 v1.2.1 문서를 담고 나가는 것을 막으려면 소유자가 직접 한 번 실행해야 한다.

## 다음 개발 우선순위

1. **실기 검증 세션 (반나절~1일 — 차단 요소 1·2 필요)**: 장비를 물린 PC에서 `app.py --selfcheck` → COM 열거 확인 → 3콘솔 연결 → 명령 송신·에코 → **케이블 분리 후 재접속** → 다른 프로그램이 포트를 잡은 상태에서 점유자 진단 → 실펌웨어 응답으로 probe 역할 판별 대조. 발견되는 차이를 `core/port.py`·`core/portscan.py`에 반영하고 회귀 테스트로 고정. **다른 모든 항목보다 우선한다** — 현재 350개 테스트는 이 프로그램이 가짜 장비와 잘 지낸다는 것만 증명한다.
2. **가이드 재생성 + 1.3.1 재빌드 (1시간 — 차단 요소 5)**: `python make_docs.py`로 v1.3.x 표기 가이드 생성 → `build_exe.py` → `build_installer.py`. 1번에서 코드 수정이 나오면 그 뒤에 묶어서 하는 편이 낫다.
3. **설치본 마감 손질 (2~3시간, 차단 없음)**: `[Icons]` 항목을 `[CustomMessages]`로 옮겨 양국어화, `사용 설명서` 아이콘을 README.md가 아니라 F1이 여는 HTML 가이드로 변경, `SerialHub.spec`의 절대 경로 문제 정리(커밋 제거 또는 상대 경로화).
4. **배포 경로 확립 (반나절 — 차단 요소 3·4)**: 결정에 따라 태그 푸시 시 exe/설치본을 굽고 Releases에 올리는 워크플로 추가(윈도우 러너 필요), README의 `dist/` 안내를 실제 다운로드 경로로 교체.
5. **CI 커버리지 확장 (반나절, 차단 없음)**: `uitest.py`를 offscreen에서 한 번 돌려보고 통과하면 CI에 추가, 윈도우 러너 잡을 붙여 `%LOCALAPPDATA%`·포터블 폴백·`list_ports_windows` 경로를 처음으로 CI에서 덮는다.
6. **정비 (틈틈이)**: CHANGELOG 신설(1.3.0 소급 기록), `requirements.txt` 버전 고정 + 빌드 의존성 명시, redact 라인 경계 한계에 대한 완화책(연결 직후 첫 부분 라인만 한시 버퍼링 등) 검토.
