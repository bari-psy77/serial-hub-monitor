# 로그 뷰어 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 과거 로그 파일을 열어 검색·필터·하이라이트로 분석하는 뷰어 (도킹 + 독립 창).

**Architecture:** Qt 비의존 파서/읽기 전용 스토어(`core/logfile.py`)가 파일을
`LogLine` 목록으로 복원하고, `ConsolePane` 이 요구하는 최소 인터페이스
(`pull_with_gap`/`last_seq`)만 구현해 기존 콘솔·필터 UI 를 그대로 재사용한다.
UI 는 `QDockWidget` 로 감싸 메인 창 도킹과 독립 창(플로팅)을 동시에 얻는다.

**Tech Stack:** Python 3.12, PySide6, 기존 selftest/uitest 하네스 (pytest 아님).

**Spec:** `docs/superpowers/specs/2026-08-14-log-viewer-design.md`

## Global Constraints

- 테스트는 `selftest.py`(check() 하네스) / `uitest.py` 에 추가한다 — pytest 없음.
- 사용자 문구는 전부 `tr('한국어 원문')` + `core/i18n_en.py` 등록. f-string 금지,
  `tr('… {0}').format(x)`. 모듈 최상위 `tr()` 금지.
- ruff: `--select E,F,W,B,ARG --line-length 110` 통과 (전각 문자는 2칸).
- 검증 3종 세트: `python selftest.py --gui` / `python uitest.py` / ruff.
- 파일은 읽고 즉시 닫는다(잠그지 않는다). 인코딩 utf-8 `errors="replace"`.
- 커밋은 태스크 단위 메시지를 준비하되, 실제 커밋 시점은 소유자 확인 후 일괄 수행한다.

---

### Task 1: core/logfile.py — 파서 + LogFileStore

**Files:**
- Create: `core/logfile.py`
- Test: `selftest.py` (새 함수 `test_logfile_viewer(tmp)` + `main()` 등록)

**Interfaces:**
- Produces:
  - `parse_log_file(path: str) -> ParsedLog` — `ParsedLog.fmt` ∈ `"port"|"merged"|"plain"`,
    `ParsedLog.entries: list[ParsedEntry]` (`t_wall: float, source: str, text: str, is_tx: bool`),
    `ParsedLog.path: str`
  - `LogFileStore()` — `add_files(paths: list[str]) -> list[tuple[str, str]]`(실패 (경로, 사유)),
    `sources() -> list[str]`, `labels() -> dict[str, str]`(소스 → 표시명),
    `pull(after_seq, ports=None, limit=None) -> list[LogLine]`,
    `pull_with_gap(after_seq, ports=None, limit=None) -> PullResult`,
    `last_seq() -> int`, `counters() -> dict[str, int]`, `total_lines() -> int`
  - `LARGE_WARN_BYTES = 200 * 1024 * 1024`
- Consumes: `core/logstore.py` 의 `LogLine`, `PullResult`, `TX_MARK`

**규칙 (스펙 §3.1):**
- 파일 형식은 파일 단위 — 앞쪽 비어 있지 않은 50줄 중 먼저 매치되는 형식.
  형식이 정해진 뒤 안 맞는 줄은 그 줄만 plain(버리지 않는다).
- 병합 형식 `[HH:MM:SS +  123.4s] [PORT] 본문` → 출처 = PORT, t_wall = 파일 mtime 의
  날짜 + 시각. 포트 형식 `[YYYY-MM-DD HH:MM:SS.mmm] 본문` → t_wall 완전 복원,
  출처 = 파일명 stem. plain → t_wall = mtime, 출처 = 파일명 stem.
- `>>> ` 접두어 = is_tx (접두어는 본문에서 뗀다 — render_line 이 다시 붙인다).
- 스토어: add_files 마다 전체를 t_wall 기준 안정 정렬(동률은 파일 내 순서) 후 seq 1..N
  재부여, t_mono = t_wall - 최소 t_wall. 파일 출처 키가 겹치면 `이름(2)` 식 부여
  (병합 파일의 포트 키는 의도적으로 공유 — 두 세션의 MLOG 는 하나의 소스로 합친다).

- [ ] **Step 1: 실패하는 테스트 작성** — `selftest.py` 에 추가:

```python
def test_logfile_viewer(tmp: str) -> None:
    print("\n== 로그 파일 불러오기 (파서·읽기 전용 스토어) ==")
    from .core.logfile import LogFileStore, parse_log_file

    vdir = os.path.join(tmp, "viewer")
    os.makedirs(vdir, exist_ok=True)
    port_path = os.path.join(vdir, "bench_mlog.log")
    with open(port_path, "w", encoding="utf-8") as fh:
        fh.write("[2026-08-02 01:19:12.165] boot banner\n"
                 "[2026-08-02 01:19:12.700] >>> otcli state\n"
                 "banner without timestamp\n")
    merged_path = os.path.join(vdir, "bench_all.log")
    with open(merged_path, "w", encoding="utf-8") as fh:
        fh.write("[01:19:12 +   0.1s] [MLOG] boot banner\n"
                 "[01:19:13 +   1.1s] [SHELL] Done\n"
                 "[01:19:14 +   2.1s] [MARK] ### cycle 1\n")
    plain_path = os.path.join(vdir, "notes.txt")
    with open(plain_path, "w", encoding="utf-8") as fh:
        fh.write("first plain line\nsecond plain line\n")

    parsed = parse_log_file(port_path)
    check("포트 파일 형식 인식", parsed.fmt == "port", parsed.fmt)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(parsed.entries[0].t_wall))
    check("포트 파일 t_wall 복원", stamp == "2026-08-02 01:19:12", stamp)
    check("밀리초 복원", abs(parsed.entries[0].t_wall % 1 - 0.165) < 0.01)
    check("TX 라인 인식 + >>> 는 본문에서 뗀다",
          parsed.entries[1].is_tx and parsed.entries[1].text == "otcli state")
    check("형식 밖의 줄은 plain 으로 살린다",
          parsed.entries[2].text == "banner without timestamp")

    merged = parse_log_file(merged_path)
    check("병합 파일 형식 인식", merged.fmt == "merged", merged.fmt)
    check("병합 라인 출처 복원", [e.source for e in merged.entries] == ["MLOG", "SHELL", "MARK"])
    check("plain 형식 열화", parse_log_file(plain_path).fmt == "plain")

    store = LogFileStore()
    errors = store.add_files([port_path, merged_path, plain_path,
                              os.path.join(vdir, "missing.log")])
    check("실패 파일은 예외가 아니라 보고 목록", len(errors) == 1 and "missing" in errors[0][0],
          str(errors))
    check("소스 키 — 파일 stem + 병합 포트",
          set(store.sources()) == {"bench_mlog", "MLOG", "SHELL", "MARK", "notes"},
          str(store.sources()))
    lines = store.pull(-1)
    check("전 소스 합산 라인 수", len(lines) == 8, str(len(lines)))
    check("seq 는 1..N 단조", [ln.seq for ln in lines] == list(range(1, 9)))
    check("t_wall 오름차순 정렬",
          all(a.t_wall <= b.t_wall for a, b in itertools.pairwise(lines)))
    check("소스 필터 pull", [ln.text for ln in store.pull(-1, ["SHELL"])] == ["Done"])
    result = store.pull_with_gap(-1, ["bench_mlog"], limit=2)
    check("limit 은 최신 쪽을 남기고 생략 개수를 알린다",
          len(result.lines) == 2 and result.skipped == 1, str(result))
    check("counters", store.counters()["bench_mlog"] == 3, str(store.counters()))

    # 같은 stem 을 한 번 더 추가하면 (2) 로 구분된다
    dup_dir = os.path.join(vdir, "dup")
    os.makedirs(dup_dir, exist_ok=True)
    dup_path = os.path.join(dup_dir, "bench_mlog.log")
    with open(dup_path, "w", encoding="utf-8") as fh:
        fh.write("[2026-08-03 09:00:00.000] second bench\n")
    store.add_files([dup_path])
    check("겹치는 파일 소스는 (2) 로 구분", "bench_mlog(2)" in store.sources(),
          str(store.sources()))
    check("추가 후에도 seq 1..N 재부여",
          [ln.seq for ln in store.pull(-1)] == list(range(1, 10)))
```

`main()` 에 `test_logfile_viewer(tmp)` 를 `test_log_dir_options(tmp)` 다음 줄로 등록.

- [ ] **Step 2: 실패 확인** — `python selftest.py` → `ModuleNotFoundError`/`ImportError`
  (core.logfile 없음) 로 RED 확인.

- [ ] **Step 3: 최소 구현** — `core/logfile.py`:

```python
"""logfile — 과거 로그 파일을 LogLine 으로 복원하는 파서 + 읽기 전용 스토어."""
from __future__ import annotations

import os
import re
import time
from bisect import bisect_right
from dataclasses import dataclass

from .diag import diag
from .logstore import LogLine, PullResult, TX_MARK

FMT_PORT = "port"
FMT_MERGED = "merged"
FMT_PLAIN = "plain"
LARGE_WARN_BYTES = 200 * 1024 * 1024
_SNIFF_LINES = 50

_PORT_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})\.(\d{3})\] (.*)$")
_MERGED_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2}) \+\s*([0-9.]+)s\] \[([^\]]+)\] (.*)$")

@dataclass(frozen=True, slots=True)
class ParsedEntry:
    t_wall: float
    source: str
    text: str
    is_tx: bool

@dataclass(frozen=True, slots=True)
class ParsedLog:
    fmt: str
    entries: list  # list[ParsedEntry]
    path: str
```

파서: stem = `os.path.splitext(os.path.basename(path))[0]`, mtime 은 `os.path.getmtime`.
형식 판별은 앞쪽 비어 있지 않은 50줄에서 `_PORT_RE`/`_MERGED_RE` 매치를 찾는다.
본문이 `TX_MARK` 로 시작하면 `is_tx=True` + 접두어 제거. t_wall 복원은 `time.mktime` +
밀리초. 스토어는 `add_files` 에서 파싱 실패를 `(path, str(exc))` 로 모으고, 성공분을
누적 리스트에 붙인 뒤 `sorted(..., key=t_wall, 안정 정렬)` → `LogLine(seq=i+1, …)` 재구성.
`pull_with_gap` 은 seq 정렬 리스트에서 `bisect_right` + ports 필터 + limit 꼬리 유지
(`skipped` 계산, `evicted=False`).

- [ ] **Step 4: 통과 확인** — `python selftest.py` → 새 체크 전부 PASS, 기존 무회귀.

- [ ] **Step 5: 커밋 준비** — `feat(viewer): parse past log files into a read-only store`

---

### Task 2: ui/log_viewer.py — 뷰어 위젯 + 도크

**Files:**
- Create: `ui/log_viewer.py`
- Modify: `core/i18n_en.py` (새 문구), `selftest.py` `test_gui` (GUI 체크)

**Interfaces:**
- Consumes: Task 1 의 `LogFileStore`/`parse_log_file`/`LARGE_WARN_BYTES`,
  `ConsolePane(title, store, ports, ts_mode=…, hide_empty=…, max_blocks=…)`
  (`show_prefix`/`extra_filter`/`state_pill`/`set_highlight_rules` — filter_view.py 참조)
- Produces:
  - `LogViewerWidget(profile, paths, parent=None)` — `.store`, `.pane`, `.edit`(필터),
    `.case_box`, `.regex_box`, `.source_boxes: dict[str, QCheckBox]`,
    `.add_button`, `.save_button`, `.error_label`, `.add_files(paths)`, `.save_to_file()`
  - `LogViewerDock(profile, paths, parent)` — QDockWidget, `.viewer` = LogViewerWidget,
    `closed = Signal(object)`, 닫으면 WA_DeleteOnClose
  - `confirm_large(parent, total_bytes) -> bool` — 모듈 함수 (테스트가 패치)

**동작:**
- 상단 바: 필터 QLineEdit + Aa + `.*` + 소스 체크박스들 + [파일 추가] + [결과 저장],
  아래 `ConsolePane(tr('로그 뷰어'), store, sources, …, max_blocks=50_000)`,
  `show_prefix=True`, `state_pill.hide()`, 프로파일 하이라이트 룰 적용.
- 필터 로직·디바운스(250ms)·저장은 `filter_view.py` 의 `_match`/`_refresh_pane`/
  `save_to_file` 와 같은 방식 (extra_filter + reload).
- 전 파일이 plain 이면 pane.ts_mode = "off", 아니면 profile.ts_mode.
- `add_files`: `confirm_large(self, 합계 바이트)` False 면 중단. 추가 후 소스 체크박스
  재구성 + `pane.reload()`. 실패 목록은 `error_label` 에 존댓말로 표시.
- 새 문구(예: '로그 뷰어', '파일 추가', '결과 저장', '읽지 못한 파일: {0}',
  '파일이 큽니다 ({0} MB). 전부 불러올까요?', '로그 파일 열기(뷰어)')는 전부
  `i18n_en.py` 에 영어 등록.

- [ ] **Step 1: 실패하는 테스트 작성** — `selftest.py` `test_gui` 의 LogPage 블록 다음에:

```python
    # 로그 뷰어 — 과거 파일을 열어 검색·필터 (스펙 2026-08-14)
    from .ui import log_viewer as log_viewer_mod
    vdir = os.path.join(tmp, "gui-viewer")
    os.makedirs(vdir, exist_ok=True)
    vport = os.path.join(vdir, "old_mlog.log")
    with open(vport, "w", encoding="utf-8") as fh:
        fh.write("[2026-08-02 01:00:00.000] alpha line\n"
                 "[2026-08-02 01:00:01.000] beta line\n")
    vmerged = os.path.join(vdir, "old_all.log")
    with open(vmerged, "w", encoding="utf-8") as fh:
        fh.write("[01:00:00 +   0.0s] [SHELL] gamma line\n")
    viewer = log_viewer_mod.LogViewerWidget(profile, [vport, vmerged])
    pump(app)
    text = viewer.pane.view.toPlainText()
    check("뷰어가 두 파일을 병합해 보여준다", "alpha line" in text and "gamma line" in text,
          text[:200])
    check("뷰어는 출처 prefix 를 붙인다", "[old_mlog]" in text and "[SHELL]" in text,
          text[:200])
    viewer.edit.setText("beta")
    viewer._refresh_timer.stop(); viewer._refresh_pane()
    pump(app)
    text = viewer.pane.view.toPlainText()
    check("필터가 매치만 남긴다", "beta line" in text and "alpha line" not in text, text[:200])
    viewer.edit.setText("")
    viewer.source_boxes["SHELL"].setChecked(False)
    viewer._refresh_timer.stop(); viewer._refresh_pane()
    pump(app)
    check("소스 체크박스로 파일을 뺀다",
          "gamma line" not in viewer.pane.view.toPlainText())
    out_path = os.path.join(tmp, "viewer_out.log")
    from PySide6.QtWidgets import QFileDialog as _QFD
    original_get = _QFD.getSaveFileName
    _QFD.getSaveFileName = staticmethod(lambda *_a, **_k: (out_path, ""))
    try:
        viewer.save_to_file()
    finally:
        _QFD.getSaveFileName = original_get
    check("뷰어 결과 저장", os.path.exists(out_path)
          and "alpha line" in open(out_path, encoding="utf-8").read())
    # 대용량 확인이 거부되면 파일을 추가하지 않는다
    original_confirm = log_viewer_mod.confirm_large
    log_viewer_mod.confirm_large = lambda _parent, _total: False
    try:
        before_sources = list(viewer.store.sources())
        viewer.add_files([vport])
    finally:
        log_viewer_mod.confirm_large = original_confirm
    check("대용량 확인 거부 시 추가하지 않는다",
          list(viewer.store.sources()) == before_sources)
    viewer.deleteLater()
    pump(app)
```

- [ ] **Step 2: 실패 확인** — `python selftest.py --gui` → `ImportError: ui.log_viewer` RED.

- [ ] **Step 3: 최소 구현** — `ui/log_viewer.py` 를 위 Interfaces/동작대로 작성.
  `confirm_large` 는 `total_bytes <= LARGE_WARN_BYTES` 면 즉시 True, 넘으면
  QMessageBox 질문(진행/취소). `LogViewerWidget.add_files` 는 호출 전에
  `log_viewer` 모듈의 `confirm_large` 를 통해서만 묻는다 (테스트 패치 지점).

- [ ] **Step 4: 통과 확인** — `python selftest.py --gui` 전부 PASS (i18n 검사 포함).

- [ ] **Step 5: 커밋 준비** — `feat(viewer): filterable log viewer widget with source toggles`

---

### Task 3: MainWindow 연결 — 메뉴·도크 관리 + uitest

**Files:**
- Modify: `ui/main_window.py` (파일 메뉴 액션, `open_log_viewer`, `viewer_docks` 관리),
  `core/i18n_en.py`(신규 문구), `uitest.py` (S8c 시나리오)

**Interfaces:**
- Consumes: Task 2 의 `LogViewerDock`, `confirm_large`
- Produces: `MainWindow.open_log_viewer(paths: list[str] | None = None) -> LogViewerDock | None`
  (paths=None 이면 QFileDialog.getOpenFileNames 다중 선택), `MainWindow.viewer_docks: list`

**동작:**
- 파일 메뉴(로그 메뉴 구성부 근처)에 `tr('로그 파일 열기(뷰어)…')` 액션 추가 →
  `open_log_viewer()`.
- `open_log_viewer`: 파일 미선택 시 None. `confirm_large` 거부 시 None.
  `LogViewerDock(self.profile, paths, self)` → `addDockWidget(Qt.BottomDockWidgetArea, dock)`
  → `viewer_docks.append`, `dock.closed.connect(제거)`. 도크는 정적 뷰라 tick 에 안 묶는다.

- [ ] **Step 1: 실패하는 테스트 작성** — `uitest.py` S8b 날짜 폴더 검사 뒤에:

```python
        # ------------------------------------------------- S8c 로그 뷰어 (과거 파일 분석)
        print("\n== S8c. 로그 뷰어 — 기록한 파일 다시 열기 ==")
        store.flush()
        dock = window.open_log_viewer([fixed_path])
        spin(app, 0.4)
        check("뷰어 도크가 열린다", dock is not None and dock in window.viewer_docks)
        vtext = dock.viewer.pane.view.toPlainText()
        check("기록했던 내용이 뷰어에 보인다", "fresh by uitest" in vtext, vtext[:200])
        dock.viewer.edit.setText("auto append")
        dock.viewer._refresh_timer.stop(); dock.viewer._refresh_pane()
        spin(app, 0.2)
        vtext = dock.viewer.pane.view.toPlainText()
        check("뷰어 필터가 동작한다",
              "auto append" in vtext and "fresh by uitest" not in vtext, vtext[:200])
        check("도크는 떼어내 독립 창이 된다 (플로팅)",
              (dock.setFloating(True) or dock.isFloating()))
        dock.close()
        spin(app, 0.3)
        check("도크를 닫으면 목록에서 빠진다", dock not in window.viewer_docks)
```

- [ ] **Step 2: 실패 확인** — `python uitest.py` → `AttributeError: open_log_viewer` RED.

- [ ] **Step 3: 최소 구현** — `ui/main_window.py` 에 액션·`open_log_viewer`·정리 로직.

- [ ] **Step 4: 통과 확인** — `python uitest.py` / `python selftest.py --gui` / ruff 전부 PASS.

- [ ] **Step 5: 커밋 준비** — `feat(viewer): open past logs from the file menu as dock windows`

---

## Self-Review 체크

- 스펙 §3.1 파서/스토어 → Task 1, §3.2 위젯/도크·대용량 경고 → Task 2,
  §3.3 메뉴·도크 관리 → Task 3, §5 테스트 3층 → 각 태스크 Step 1. 공백 없음.
- plain 전용 ts_mode off 는 Task 2 동작 절에 명시 (GUI 체크는 병합 파일 포함이라 생략).
- 시그니처 일치: `add_files`/`sources`/`confirm_large`/`open_log_viewer` 전 태스크 동일.
