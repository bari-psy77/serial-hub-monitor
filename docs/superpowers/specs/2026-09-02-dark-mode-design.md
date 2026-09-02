# 다크모드 설계

- 날짜: 2026-09-02
- 상태: 사용자 승인됨 (아래 §2 결정 사항, 성능 측정 확인 후 진행 승인)
- 근거 요청: 사내 공유 후 접수된 요청 4건 중 1건 — "다크모드 변경 가능하게"

## 1. 목적

화면 테마를 **라이트 / 다크**로 고르고 **즉시** 전환한다. 색은 UI 껍데기뿐 아니라
**로그 본문(펌웨어 ANSI 색·하이라이트)과 터미널까지** 함께 바뀌어야 실제로 어두운
환경에서 읽을 수 있다.

## 2. 확정 사항 (사용자 결정)

| 항목 | 결정 |
|---|---|
| 선택지 | **라이트 / 다크 2택**, 기본값 = 라이트 (지금 모습) |
| 전환 시점 | **즉시 적용** (언어는 재시작 필요 — 그 차이를 UI 에 표시) |
| ANSI·하이라이트 색 | **다크 전용 값을 따로 정의** (자동 밝기 반전 아님) |
| 내장 터미널 | **테마를 따라간다** (라이트에서는 밝은 터미널) |
| 저장 위치 | `settings.json` — 언어와 같은 자리(사람 설정, 프로파일 아님) |

## 3. 측정 근거 (2026-09-02, 이 벤치)

설계 A안(색을 저장하지 않고 그릴 때 결정)이 화면 속도를 해치지 않는지 먼저 쟀다.

| 항목 | 값 |
|---|---|
| span 당 색 해석 — 현재(hex 문자열 파싱) | 0.744 µs |
| span 당 색 해석 — 제안(SGR 코드 → 캐시된 QColor) | **0.091 µs** |
| firehose 1,500 line/s 에서 tick 1회 (75줄) | 10 ms (예산 50 ms) |
| 테마 전환 시 재하이라이트 (pane 1개, 20,001 블록) | 189 ms |
| 같은 조건 `reload()` 전체 | 409 ms |

→ **평상시 렌더링은 오히려 빨라진다.** 비용은 전환하는 순간뿐이고, pane 5~6개 기준
약 1초의 일회성 지연이다(명시적 조작 + 대기 커서로 완화).

(참고: `CLAUDE.md` 는 rehighlight 를 "pane 당 0.5~1.2초"로 적고 있으나, 이번 실측은
20,001 블록에서 189 ms 였다. 옛 측정이거나 더 큰 버퍼 기준으로 보인다.)

## 4. 핵심 결정 — 색을 저장하지 않는다

`ansi.parse()` 는 지금 SGR 코드를 **hex 문자열로 바꿔** `LogLine.spans` 에 넣고, 그
값이 수신 시점에 ring 에 박힌다. 그래서 테마를 바꿔도 **이미 받은 로그는 옛 색 그대로**
남아 화면이 반반으로 섞인다.

→ **spans 에 SGR 코드를 담고, 색은 그릴 때 팔레트에서 찾는다.** store 는 의미를,
뷰는 표현을 갖는다는 기존 구조 원칙과 같고, 스크롤백 전체가 즉시 새 팔레트로 칠해진다.

**계약 변경**: `parse()` 반환의 `(start, end, fg, bg, bold)` 에서 `fg`/`bg` 가
**hex 문자열 → int 코드**가 된다.

- 표준 전경 `30..37`, 밝은 전경 `90..97`, 배경 `40..47`·`100..107` 은 SGR 값 그대로
- 256색은 `X256_BASE + n` (`X256_BASE = 1000`) 으로 인코딩한다
- 색 없음 = `0`

## 5. 구성요소

### 5.1 `ui/theme.py`

```python
PALETTES: dict[str, dict[str, str]]   # "light" / "dark", 키는 기존 토큰 이름 그대로
CURRENT: str                          # 현재 테마 이름
def theme_names() -> list[str]
def set_theme(name: str) -> str       # 토큰 갱신 + QSS 재생성, 반환 = 실제 적용된 이름
def apply_theme(app) -> None          # 기존 함수 — set_theme 이후에 호출한다
```

- 토큰(`BG`·`TEXT`·`PRIMARY`…)은 **모듈 전역**으로 유지하고 `set_theme()` 이 값을
  갈아끼운다. UI 9개 모듈이 전부 `from . import theme` 로 **모듈 참조**를 쓰므로
  (`theme.BG`) 값 교체가 그대로 따라온다 — 조사해서 확인했다.
- 알 수 없는 이름은 `light` 로 폴백한다.

### 5.2 `core/ansi.py` (Qt 비의존 유지)

```python
def set_theme(name: str) -> None
def fg_hex(code: int) -> str      # 0 이면 "" (기본색)
def bg_hex(code: int) -> str
X256_BASE = 1000
```

- `_FG`/`_BG` 를 테마별 2벌로 두고, 다크용은 VS Code 다크 계열 값을 직접 적는다.
- `parse()` 는 코드만 담는다 (§4).

### 5.3 `core/filters.py`

```python
def set_theme(name: str) -> None
def highlight_names() -> list[str]        # 프로파일 식별자 — 테마와 무관하게 고정
def highlight_hex(name: str) -> str
def search_hex() -> str
```

- ★하이라이트 색 **이름은 프로파일 JSON 에 저장되는 식별자**다. 두 팔레트가 같은 키를
  가져야 하고, 테마를 바꿔도 프로파일이 깨지면 안 된다 (테스트로 강제).
- 지금 값으로 임포트하는 두 곳(`ui/console_pane.py`, `ui/rules_page.py`)을 함수
  호출로 바꾼다 — 값 임포트는 런타임 교체가 먹지 않는다.

### 5.4 `ui/console_pane.py`

- 하이라이터가 span 의 코드를 `ansi.fg_hex()` 로 풀고 **QColor 를 코드별로 캐시**한다.
- 배너 색 하드코딩(`#FFF4C2`/`#8A6D00`)을 테마 토큰으로 옮긴다.
- `refresh_theme()` — 포맷·QColor 캐시를 비우고, **폰트 크기를 다시 적용한 뒤**,
  하이라이트 룰을 재설정해 다시 칠한다.

### 5.5 `ui/terminal_pane.py`

- `_DEFAULT_FG`/`_DEFAULT_BG`/`_ANSI_COLORS` 를 테마별 2벌로. 라이트용 셀 색표를
  새로 정의한다(밝은 배경 + 어두운 글자).
- `refresh_theme()` — 팔레트 교체 후 `screen.update()`.

### 5.6 `ui/general_page.py`

- 언어 아래에 **테마 콤보**(라이트/다크). 언어는 "재시작 후 적용", 테마는 "즉시 적용"
  이라고 각각 라벨에 적는다.

### 5.7 기동 시 적용 — `app.py`

언어와 같은 자리에서 **UI 모듈을 임포트하기 전에** 테마를 정한다:

```python
set_language(config_mod.language())
theme.set_theme(config_mod.theme())      # ← 추가
```

★모듈 최상위 상수에서 색을 굳히는 코드가 생기면 이 순서로도 못 잡는다 —
`tr()` 과 같은 규칙(임포트 시점에 굳히지 않기)을 색에도 적용한다.

### 5.8 `core/config.py`

```python
def theme() -> str                    # settings.json, 기본 "light"
def set_theme_setting(name: str) -> str
```

### 5.9 `ui/main_window.py`

```python
def apply_theme_change(self, name: str) -> None
```

**전환 절차 — QSS 재적용만으로는 부족하다:**

1. `theme.set_theme()` · `ansi.set_theme()` · `filters.set_theme()`
2. `theme.apply_theme(app)` (QSS 재적용)
3. **인라인 스타일 재적용** — `setStyleSheet` 를 코드에서 직접 부르는 곳은 조사 결과
   7개 모듈이다(`theme`·`main_window`·`connection_page`·`command_panel`·`rules_page`·
   `general_page`·`settings_dialog`). 이 중 **생성 시 한 번만 바르는 것**(Card 배경,
   settings 창 배경)이 문제이고, tick 에서 매번 바르는 것(상태 필·REC 버튼)은 다음
   tick 에 저절로 맞는다. 전자는 위젯에 `refresh_theme()` 를 두고 MainWindow 가 순회한다
4. ★**콘솔·터미널 폰트 크기 재적용** — QSS repolish 가 `setFont()` 를 되돌린다
   (`CLAUDE.md` 에 적힌 함정. Ctrl+휠로 키워 둔 크기가 전환 때 12pt 로 돌아가면 안 된다)
5. 모든 pane `refresh_theme()` (콘솔 3 + 병합 + 필터드뷰 + 로그 뷰어)
6. 터미널 도크 `refresh_theme()`
7. `config.set_theme_setting(name)` 로 저장
8. 전환 중에는 대기 커서(`Qt.WaitCursor`)를 표시한다 — 약 1초가 걸린다

## 6. 테스트 계획

- **core (플랫폼 무관)**
  - `ansi`: 테마 교체 후 `fg_hex()` 가 다크 값을 돌려준다 / 코드→hex 매핑이 두 테마에서
    같은 키 집합을 갖는다 / 알 수 없는 테마는 light 폴백 / 256색 인코딩 왕복
  - `ansi.parse()`: spans 가 **코드**를 담는다(계약 변경 회귀 가드), 기존 offset·bold 유지
  - `filters`: 하이라이트 **이름 집합이 테마와 무관하게 동일**(프로파일 호환), 색 값은 다름
  - `config`: settings.json 왕복, 기본값 light, 잘못된 값 폴백
- **selftest --gui**
  - 전환 후 **콘솔 폰트 크기가 유지된다** ★ (repolish 함정 회귀 가드)
  - 전환 후 QSS 배경이 실제로 바뀐다 / 되돌리면 원복된다
  - 하이라이트·ANSI 포맷이 새 팔레트로 다시 칠해진다 (블록 포맷 색 비교)
  - 전환 후 `tick()` 이 예외 없이 돈다
- **uitest**: 수신 중 전환 → 스크롤백 유지, 예외 없음, 기록 계속
- **실기**: 라이트/다크 각 스크린샷 1장 (콘솔 색·터미널·필터드뷰 포함)

## 7. 범위 밖 (YAGNI)

- 시스템 테마 자동 추적 (2택으로 결정)
- 사용자 커스텀 팔레트 / 테마별 하이라이트 이름 추가
- 로그 파일·문서(HTML 가이드)의 색 — 파일은 언제나 평문이고 가이드는 별도 문서다

## 8. 위험과 완화

| 위험 | 완화 |
|---|---|
| span 계약 변경이 기존 테스트·저장 라인을 깬다 | 계약 회귀 테스트를 먼저 쓰고, `logstore`·`console_pane`·selftest 4건을 같은 커밋에서 함께 고친다 |
| 전환 시 폰트 크기가 리셋된다 | 절차 4단계로 명시 + GUI 테스트로 고정 |
| 하이라이트 색 이름이 테마별로 갈리면 프로파일이 깨진다 | 두 팔레트의 키 집합 동일성을 테스트로 강제 |
| 전환 순간 약 1초 멈춤 | 명시적 조작에만 발생 + 대기 커서. 측정값(§3)을 근거로 수용 |
