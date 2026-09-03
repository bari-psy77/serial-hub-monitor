#!/usr/bin/env python3
"""Serial Hub 셀프테스트 — 하드웨어 없이 core + UI 를 검증한다 (설계문서 §8).

  python selftest.py           # core 만
  python selftest.py --gui     # offscreen Qt 포함

가짜 시리얼 포트로 라인 조립 / 부분 라인 / 재접속 / 송신 / redact / probe 판정을 돌린다.
실기 검증(설계 §8 의 2~6)은 이 스크립트로 대체되지 않는다.
"""

from __future__ import annotations

import argparse
import io
import itertools
import re
import os
import shutil
import sys
import tempfile
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 콘솔이 cp949 여도 테스트는 돌아야 한다
    pass

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "serial_hub"

from .core import config as config_mod  # noqa: E402
from .core import portscan  # noqa: E402
from .core.config import PortConfig, Profile  # noqa: E402
from .core.filters import (DEFAULT_REDACT_RULES, FilterRule, HighlightRule,  # noqa: E402
                           RedactRule, Redactor)
from .core.logstore import (TS_ABSOLUTE, TS_OFF, TS_RELATIVE, LogStore,  # noqa: E402
                            format_for_merged_file, format_for_port_file, render_line)
from .core.port import PortReader  # noqa: E402
from .core.session import SerialHubSession  # noqa: E402

def pump(app) -> None:
    """processEvents() 는 DeferredDelete 를 처리하지 않는다 (app.exec() 안에서만 돈다).
    실기와 같은 파괴 시점을 재현하려고 여기서 직접 비운다."""
    from PySide6.QtCore import QEvent
    app.processEvents()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(f"{name} — {detail}")
        print(f"  [FAIL] {name} — {detail}")


class FakeSerial:
    """pyserial 대역. read() 는 큐에서 꺼내고, fail_after 를 넘기면 예외를 던진다."""

    def __init__(self, script: list[bytes] | None = None, fail_after: int | None = None):
        self.queue = list(script or [])
        self.written: list[bytes] = []
        self.closed = False
        self.reads = 0
        self.fail_after = fail_after
        self._lock = threading.Lock()

    def read(self, _size: int = 1) -> bytes:
        with self._lock:
            self.reads += 1
            if self.fail_after is not None and self.reads > self.fail_after:
                raise OSError("simulated read failure")
            if self.queue:
                return self.queue.pop(0)
        time.sleep(0.01)
        return b""

    def feed(self, data: bytes) -> None:
        with self._lock:
            self.queue.append(data)

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def wait_until(predicate, timeout: float = 3.0, interval: float = 0.02) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# --------------------------------------------------------------------- core

def test_logstore(tmp: str) -> None:
    print("\n== LogStore ==")
    store = LogStore(capacity_per_port=1_000)
    store.start_session(tmp, "unit", ["MLOG", "SHELL"])

    store.append("MLOG", "hello world")
    store.append("SHELL", "otcli state", is_tx=True)
    store.append("SHELL", "Done")

    lines = store.pull(-1)
    check("seq 는 전 포트 통합 단조 증가", [ln.seq for ln in lines] == [1, 2, 3], str(lines))
    check("포트 필터 pull", [ln.text for ln in store.pull(-1, ["SHELL"])] == ["otcli state", "Done"])
    check("after_seq pull", [ln.text for ln in store.pull(2)] == ["Done"])
    check("카운터", store.counters() == {"MLOG": 1, "SHELL": 2}, str(store.counters()))

    absolute = render_line(lines[0], TS_ABSOLUTE)
    relative = render_line(lines[0], TS_RELATIVE)
    off = render_line(lines[0], TS_OFF)
    check("타임스탬프 절대 렌더", absolute.endswith("hello world") and absolute.startswith("["), absolute)
    check("타임스탬프 상대 렌더", "+" in relative and relative.endswith("hello world"), relative)
    check("타임스탬프 끔", off == "hello world", off)
    check("병합 뷰 prefix", "[MLOG]" in render_line(lines[0], TS_ABSOLUTE, show_prefix=True))
    check("TX 는 >>> 로 표시", ">>> otcli state" in render_line(lines[1], TS_OFF))

    check("포트 파일 형식", format_for_port_file(lines[0]).startswith("[2"),
          format_for_port_file(lines[0]))
    check("병합 파일 형식은 기존 transcript 계열",
          "[MLOG] hello world" in format_for_merged_file(lines[0]),
          format_for_merged_file(lines[0]))

    store.stop_session()
    day = time.strftime("%m%d")
    mlog_path = os.path.join(tmp, day, "unit_mlog.log")
    all_path = os.path.join(tmp, day, "unit_all.log")
    check("포트별 파일 생성", os.path.exists(mlog_path), mlog_path)
    check("병합 파일 생성", os.path.exists(all_path), all_path)
    with open(all_path, "r", encoding="utf-8") as fh:
        merged = fh.read()
    check("병합 파일에 3줄 모두 기록", merged.count("\n") == 3, repr(merged))
    check("병합 파일에 TX 에코 기록", ">>> otcli state" in merged, repr(merged))

    # ring 상한
    store2 = LogStore(capacity_per_port=1_000)
    for i in range(2_500):
        store2.append("MLOG", f"line {i}")
    kept = store2.pull(-1, ["MLOG"])
    check("ring 상한 유지", len(kept) <= 1_000, f"{len(kept)} 줄 남음")
    check("ring 은 최신을 남긴다", kept[-1].text == "line 2499", kept[-1].text)
    check("총 카운터는 유실 없이 누적", store2.counters()["MLOG"] == 2_500)

    result = store2.pull_with_gap(-1, ["MLOG"], limit=100)
    check("pull limit 은 최신 쪽을 남긴다",
          len(result.lines) == 100 and result.lines[-1].text == "line 2499")
    check("생략된 개수를 알려준다 (조용한 유실 금지)", result.skipped > 0, str(result.skipped))

    # ring 이 이미 밀어낸 구간은 개수를 셀 수 없다 — "없었던 일"로 보이면 안 된다
    lagging = store2.pull_with_gap(5, ["MLOG"])
    check("ring 에서 밀려난 구간을 evicted 로 알린다", lagging.evicted, "evicted 미표시")
    fresh = store2.pull_with_gap(store2.last_seq() - 10, ["MLOG"])
    check("따라잡은 커서는 evicted 로 오인하지 않는다", not fresh.evicted)

    ordered = store2.pull(-1, ["MLOG"])
    check("seq 순서와 시각 순서가 어긋나지 않는다",
          all(a.t_wall <= b.t_wall for a, b in itertools.pairwise(ordered)))


def test_rollover(tmp: str) -> None:
    print("\n== 날짜 폴더 전환 ==")
    store = LogStore()
    store.start_session(tmp, "roll", ["MLOG"])
    store.append("MLOG", "before midnight")
    store.flush()                # 비동기 writer 를 확정시킨 뒤 날짜를 넘긴다
    store._session_day = "0101"  # 자정을 넘긴 상태를 흉내낸다
    store.append("MLOG", "after midnight")
    store.stop_session()
    today = time.strftime("%m%d")
    day_dir = os.path.join(tmp, today)
    check("자정 후 오늘 폴더로 다시 열림", os.path.exists(os.path.join(day_dir, "roll_mlog.log")))
    # 날짜가 바뀌면 세션명에 날짜를 붙인다 — 안 그러면 파일명의 HHMMSS 가 내용과 어긋난다
    rolled = os.path.join(day_dir, f"roll_{today}_mlog.log")
    check("전환 후 파일명에 새 날짜가 붙는다", os.path.exists(rolled), str(os.listdir(day_dir)))
    with open(rolled, "r", encoding="utf-8") as fh:
        body = fh.read()
    check("전환 후 라인이 새 파일에 기록", "after midnight" in body, repr(body))
    with open(os.path.join(day_dir, "roll_mlog.log"), "r", encoding="utf-8") as fh:
        check("전환 전 라인은 옛 파일에 남는다", "before midnight" in fh.read())


def test_concurrent_load(tmp: str) -> None:
    print("\n== 동시 적재 부하 (3 스레드) ==")
    store = LogStore(capacity_per_port=50_000)
    store.start_session(tmp, "load", ["MLOG", "SHELL", "UCLI"])
    per_thread = 5_000

    def writer(role: str) -> None:
        for i in range(per_thread):
            store.append(role, f"{role} line {i}")

    threads = [threading.Thread(target=writer, args=(role,))
               for role in ("MLOG", "SHELL", "UCLI")]
    start = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - start
    store.stop_session()

    counters = store.counters()
    check("스레드 3개가 넣은 라인이 하나도 안 빠졌다",
          all(counters[role] == per_thread for role in ("MLOG", "SHELL", "UCLI")), str(counters))

    lines = store.pull(-1)
    check("seq 는 경합 중에도 중복·역전이 없다",
          all(a.seq < b.seq for a, b in itertools.pairwise(lines)), "seq 순서 깨짐")
    check(f"15k 라인 적재 {elapsed:.2f}s", elapsed < 20.0, f"{elapsed:.2f}s")

    day = time.strftime("%m%d")
    with open(os.path.join(tmp, day, "load_all.log"), "r", encoding="utf-8") as fh:
        merged = fh.read().splitlines()
    check("병합 파일에 15,000줄 전부 기록",
          len(merged) == per_thread * 3, f"{len(merged)}줄")
    check("병합 파일에 라인이 섞여 깨진 곳 없음",
          all(line.startswith("[") and "] [" in line for line in merged[:2000]),
          next((line for line in merged[:2000] if not line.startswith("[")), ""))

    for role in ("MLOG", "SHELL", "UCLI"):
        path = os.path.join(tmp, day, f"load_{role.lower()}.log")
        with open(path, "r", encoding="utf-8") as fh:
            count = sum(1 for _ in fh)
        check(f"{role} 포트 파일에 {per_thread}줄", count == per_thread, f"{count}줄")


def test_rotation_and_marker(tmp: str) -> None:
    print("\n== 크기 회전 · 마커 · 세션 분절 ==")
    store = LogStore()
    store.max_file_bytes = 1_500  # 시험용으로 낮춘다 (기본 200MB)
    store.start_session(tmp, "rot", ["MLOG"])
    for i in range(60):
        store.append("MLOG", f"filler line {i} {'x' * 40}")
    store.marker("cycle 1 done")
    split_name = store.split_session()
    store.append("MLOG", "after split")
    store.stop_session()

    day = time.strftime("%m%d")
    day_dir = os.path.join(tmp, day)
    files = sorted(os.listdir(day_dir))
    check("크기 상한 도달 시 _pN 으로 자동 분절", any("rot_p" in f for f in files), str(files))
    check("마커가 _mark.log 로 남는다",
          any(f.endswith("_mark.log") for f in files), str(files))
    check("수동 분절 이름이 반환된다", split_name.startswith("rot_p"), split_name)
    with open(os.path.join(day_dir, f"{split_name}_mlog.log"), encoding="utf-8") as fh:
        check("분절 후 라인은 새 파일로 간다", "after split" in fh.read())
    total = 0
    for name in files:
        if name.startswith("rot") and name.endswith("_all.log"):
            with open(os.path.join(day_dir, name), encoding="utf-8") as fh:
                total += sum(1 for _ in fh)
    check("분절돼도 병합 라인 총합은 유실 없다 (60+마커+1)", total == 62, str(total))

    from .core.filters import TriggerRule, TriggerWatcher
    watcher = TriggerWatcher()
    watcher.set_rules([TriggerRule("WDOG"), TriggerRule("fault", ports=["MLOG"])])
    store2 = LogStore()
    store2.append("MLOG", "[SYS] WDOG1 reset")
    store2.append("SHELL", "hard fault here")   # ports=[MLOG] 라 안 잡혀야 함
    store2.append("MLOG", "MemManage fault")
    hits = watcher.scan(store2)
    check("트리거 매치 집계", watcher.counts.get("WDOG") == 1 and watcher.counts.get("fault") == 1,
          str(watcher.counts))
    check("포트 한정 트리거는 다른 포트를 무시", len(hits) == 2, str(hits))
    check("재스캔 시 같은 라인을 두 번 세지 않는다", watcher.scan(store2) == [])


def test_review_regressions(tmp: str) -> None:
    """2026-08-03 리뷰 지적에 대한 수정의 회귀 가드."""
    print("\n== 리뷰 수정 회귀 가드 ==")

    # LOCK-SCOPE-IO: 디스크가 늦어도 append/pull 이 막히면 안 된다
    store = LogStore()
    store.start_session(tmp, "lockscope", ["MLOG"])
    original_write = type(store)._service
    slow = {"n": 0}

    class SlowWriter:
        def write(self, _text):
            slow["n"] += 1
            time.sleep(0.4)

        def close(self):
            pass
        error = None
        bytes_written = 0

    with store._service_lock:
        store._writers["MLOG"] = SlowWriter()
        store._merged = SlowWriter()
    store.append("MLOG", "trigger slow write")
    time.sleep(0.15)                       # writer 스레드가 느린 write 중
    started = time.monotonic()
    store.append("MLOG", "must not block")
    store.pull(-1, ["MLOG"])
    blocked = time.monotonic() - started
    check(f"느린 디스크가 수신/조회를 막지 않는다 ({blocked * 1000:.0f}ms)", blocked < 0.2,
          f"{blocked:.2f}s 블록")
    with store._service_lock:
        store._writers.clear()
        store._merged = None
    store.stop_session()
    assert original_write is type(store)._service

    # PROBE-FALLBACK: 토큰 에코가 있으면 서명 미매치를 MLOG 로 확정하지 않는다
    token = portscan.DEFAULT_PROBE_TOKEN
    verdict, _ = portscan.classify_probe_text(f"> {token}\r\nUnknown command: {token}\r\n", token)
    check("모르는 응답 문구는 판정 보류", verdict == portscan.VERDICT_UNKNOWN, verdict)

    # ANSI: 색은 본문에서 떼되 버리지 않고 span 으로 보관한다
    from .core import ansi as ansi_mod
    from .core.logstore import strip_ansi
    check("콜론형 SGR 제거", strip_ansi("\x1b[38:5:196mRED\x1b[0m") == "RED")
    check("private prefix CSI 제거", strip_ansi("\x1b[?25lX") == "X")
    check("라인 말미의 잘린 CSI 제거", strip_ansi("text\x1b[3") == "text")
    check("정상 텍스트는 안 건드린다", strip_ansi("normal [ZCL] 1;2 text") == "normal [ZCL] 1;2 text")

    clean, spans = ansi_mod.parse("\x1b[32mGREEN\x1b[0m plain \x1b[1;31mBOLDRED\x1b[0m")
    check("색을 뗀 본문", clean == "GREEN plain BOLDRED", clean)
    check("색 구간 2개", len(spans) == 2, str(spans))
    check("첫 구간이 GREEN 을 정확히 덮는다",
          spans[0][0] == 0 and spans[0][1] == 5 and spans[0][2], str(spans[0]))
    check("두 번째 구간은 굵게 + 빨강",
          spans[1][4] is True and spans[1][2].lower() != spans[0][2].lower(), str(spans[1]))
    check("색이 없으면 span 도 없다", ansi_mod.parse("plain") == ("plain", ()))
    check("256색 SGR 파싱", ansi_mod.parse("\x1b[38;5;196mX\x1b[0m")[1][0][2].startswith("#"))

    # 색을 저장하지 않는다 — 토큰만 담고 팔레트는 그릴 때 본다 (테마 전환용 계약)
    check("표준색은 SGR 코드 토큰으로 담긴다",
          ansi_mod.parse("\x1b[32mGREEN\x1b[0m")[1][0][2] == "32",
          str(ansi_mod.parse("\x1b[32mGREEN\x1b[0m")[1][0]))
    check("트루컬러는 리터럴 hex 로 담긴다",
          ansi_mod.parse("\x1b[38;2;10;20;30mX\x1b[0m")[1][0][2] == "#0A141E",
          str(ansi_mod.parse("\x1b[38;2;10;20;30mX\x1b[0m")[1][0]))
    check("xterm256 의 표준 16색은 코드로 환산된다 (테마를 따라가야 하므로)",
          ansi_mod.parse("\x1b[38;5;2mX\x1b[0m")[1][0][2] == "32",
          str(ansi_mod.parse("\x1b[38;5;2mX\x1b[0m")[1][0]))
    check("xterm256 컬러큐브는 리터럴",
          ansi_mod.parse("\x1b[38;5;196mX\x1b[0m")[1][0][2].startswith("#"))

    light_green = ansi_mod.resolve("32")
    ansi_mod.set_theme("dark")
    check("테마를 바꾸면 같은 토큰이 다른 색이 된다",
          ansi_mod.resolve("32") != light_green and ansi_mod.resolve("32").startswith("#"),
          f"{light_green} -> {ansi_mod.resolve('32')}")
    check("배경 토큰도 테마를 따른다",
          ansi_mod.resolve("41", background=True).startswith("#"))
    check("리터럴은 테마와 무관하게 그대로", ansi_mod.resolve("#0A141E") == "#0A141E")
    check("기본색 토큰은 빈 문자열", ansi_mod.resolve("") == "")
    check("두 팔레트의 코드 집합이 같다",
          set(ansi_mod.PALETTES["light"]["fg"]) == set(ansi_mod.PALETTES["dark"]["fg"])
          and set(ansi_mod.PALETTES["light"]["bg"]) == set(ansi_mod.PALETTES["dark"]["bg"]))
    ansi_mod.set_theme("없는테마")
    check("모르는 테마는 light 폴백", ansi_mod.resolve("32") == light_green)

    store_ansi = LogStore()
    line = store_ansi.append("MLOG", "\x1b[33mWARN\x1b[0m tail")
    check("적재 시 본문에 이스케이프가 없다", "\x1b" not in line.text and line.text == "WARN tail")
    check("적재 시 색 구간이 보존된다", len(line.spans) == 1 and line.spans[0][:2] == (0, 4),
          str(line.spans))
    redacting = LogStore()
    redacting.set_redactor(Redactor(DEFAULT_REDACT_RULES))
    masked_line = redacting.append("SHELL", "\x1b[32mwifi connect AP hunter2pass\x1b[0m")
    check("마스킹된 줄은 색 구간을 버린다 (offset 어긋남 방지)",
          masked_line.spans == () and "hunter2pass" not in masked_line.text, str(masked_line))

    # 형태 기반 redact — 키워드가 라인 경계로 잘려도 값 자체로 잡는다
    redactor = Redactor(DEFAULT_REDACT_RULES)
    masked = redactor.apply("2233445566778899aabbccddeeff00112233445566778899aabbccddeeff")
    check("키워드 없이도 긴 hex 는 마스킹된다", "aabbccddeeff" not in masked, masked)
    check("짧은 hex(주소 등)는 안 건드린다",
          redactor.apply("pc=0x08010000 len=1234") == "pc=0x08010000 len=1234")

    # transform 파이프라인이 확장을 지우지 않는다
    store2 = LogStore()
    store2.add_transform(lambda text: text.replace("AAA", "BBB"))
    store2.set_ansi_strip(True)
    check("set_ansi_strip 이 커스텀 변환을 지우지 않는다",
          store2.append("MLOG", "\x1b[31mAAA\x1b[0m").text == "BBB")

    # usable_sizes 가 bool 을 int 로 통과시키면 패널 폭이 0 이 된다
    from .ui.main_window import usable_sizes
    check("bool 은 분할 크기로 인정하지 않는다", usable_sizes([True, False], 2) is None)

    # TriggerWatcher.reset(rewind) — store 교체 시 커서까지 되돌려야 집계가 산다
    from .core.filters import TriggerRule, TriggerWatcher
    watcher = TriggerWatcher()
    watcher.set_rules([TriggerRule("WDOG")])
    old_store = LogStore()
    for i in range(50):
        old_store.append("MLOG", f"line {i}")
    old_store.append("MLOG", "WDOG1 reset")
    watcher.scan(old_store)
    new_store = LogStore()
    new_store.append("MLOG", "WDOG1 reset in new session")
    watcher.reset()
    check("커서 유지 reset 은 옛 커서를 지키느라 새 store 를 못 본다", watcher.scan(new_store) == [])
    watcher.reset(rewind=True)
    check("rewind reset 이면 새 store 의 트리거를 잡는다", len(watcher.scan(new_store)) == 1)


def test_log_features(tmp: str) -> None:
    print("\n== 로그 기능 (제어문자·멈춤·파일명) ==")
    from .core.logstore import MERGED_KEY, sanitize_controls

    # 실제로 겪은 문제: NUL 한 개 때문에 편집기가 파일 전체를 바이너리로 판정해 안 열린다
    check("NUL 을 눈에 보이는 표기로 바꾼다", sanitize_controls("a\x00b") == "a<00>b")
    check("다른 C0 제어문자도 처리", sanitize_controls("x\x01\x1fy") == "x<01><1F>y")
    check("탭은 살린다", sanitize_controls("a\tb") == "a\tb")
    check("한글·일반 문자는 그대로", sanitize_controls("정상 [ZCL] 텍스트") == "정상 [ZCL] 텍스트")

    store = LogStore()
    store.start_session(tmp, "ctrl", ["MLOG"])
    store.append("MLOG", "before\x00after")
    store.flush()
    store.stop_session()
    day_dir = os.path.join(tmp, time.strftime("%m%d"))
    with open(os.path.join(day_dir, "ctrl_mlog.log"), "rb") as fh:
        raw = fh.read()
    check("로그 파일에 NUL 바이트가 없다 (편집기가 열 수 있다)", b"\x00" not in raw, str(raw[:60]))
    check("제어문자 흔적은 남는다", b"<00>" in raw, str(raw[:60]))

    # 기록 멈춤 — 화면·ring 은 계속, 파일만 멈춘다
    store2 = LogStore()
    store2.start_session(tmp, "pause", ["MLOG"])
    store2.append("MLOG", "recorded 1")
    store2.flush()
    store2.set_paused(True)
    for i in range(5):
        store2.append("MLOG", f"while paused {i}")
    check("멈춘 동안에도 ring 에는 쌓인다",
          sum(1 for ln in store2.pull(-1, ["MLOG"]) if "while paused" in ln.text) == 5)
    dropped = store2.set_paused(False)
    check("멈춘 동안 미기록 줄 수를 알려준다", dropped == 5, str(dropped))
    store2.append("MLOG", "recorded 2")
    store2.flush()
    store2.stop_session()
    with open(os.path.join(day_dir, "pause_mlog.log"), encoding="utf-8") as fh:
        body = fh.read()
    check("멈춤 전후는 파일에 있다", "recorded 1" in body and "recorded 2" in body)
    check("멈춘 구간은 파일에 없다", "while paused" not in body)
    check("멈춤/재개가 그 포트 파일에도 표시된다 (공백 오해 방지)",
          ("일시정지" in body or "paused" in body)
          and ("재개" in body or "resumed" in body), body[-200:])

    # 포트별 파일명 + 세션 접두어 옵션
    store3 = LogStore()
    store3.set_file_naming({"MLOG": "matter", "SHELL": "ht", MERGED_KEY: "merged"},
                           include_session=False)
    store3.start_session(tmp, "named", ["MLOG", "SHELL"])
    store3.append("MLOG", "x")
    store3.append("SHELL", "y")
    store3.flush()
    files = set(os.listdir(day_dir))
    check("포트별 지정 이름으로 저장된다", {"matter.log", "ht.log"} <= files, str(sorted(files)))
    check("병합 파일명도 지정된다", "merged.log" in files, str(sorted(files)))
    check("세션 접두어를 끄면 이름만 쓴다", not any(f.startswith("named_") for f in files))
    check("파일 경로/크기 조회", store3.file_paths().get("MLOG", "").endswith("matter.log")
          and store3.file_sizes().get("MLOG", 0) > 0)
    store3.stop_session()

    # 트래픽 없는 포트는 파일을 만들지 않는다 (0바이트 파일이 쌓이던 문제)
    store5 = LogStore()
    store5.start_session(tmp, "lazyfile", ["MLOG", "SHELL", "UCLI"])
    day_files = os.listdir(day_dir)
    check("세션을 열어도 빈 파일을 미리 만들지 않는다",
          not any(f.startswith("lazyfile") for f in day_files),
          str([f for f in day_files if f.startswith('lazyfile')]))
    store5.append("MLOG", "only mlog")
    store5.flush()
    made = sorted(f for f in os.listdir(day_dir) if f.startswith("lazyfile"))
    check("트래픽이 온 포트만 파일이 생긴다",
          made == ["lazyfile_all.log", "lazyfile_mlog.log"], str(made))
    check("생긴 파일은 0바이트가 아니다",
          all(os.path.getsize(os.path.join(day_dir, f)) > 0 for f in made))
    check("flush 는 디스크까지 내린다 (다른 도구가 바로 읽는다)",
          os.path.getsize(os.path.join(day_dir, "lazyfile_mlog.log")) > 0)
    store5.stop_session()

    store4 = LogStore()
    store4.set_file_naming({"MLOG": "bad/name*?"}, include_session=True)
    store4.start_session(tmp, "safe", ["MLOG"])
    store4.append("MLOG", "z")
    store4.flush()
    check("파일명에 못 쓰는 문자는 걸러낸다",
          any(f.startswith("safe_badname") for f in os.listdir(day_dir)),
          str([f for f in os.listdir(day_dir) if f.startswith("safe")]))
    store4.stop_session()


def test_log_dir_options(tmp: str) -> None:
    print("\n== 저장 위치 옵션 — 날짜 폴더 · 사전 경로 · 덮어쓰기 ==")
    from .core.logstore import MERGED_KEY

    # 날짜(MMDD) 하위 폴더를 끄면 save location 에 바로 저장한다
    flat = os.path.join(tmp, "flatdir")
    store = LogStore()
    store.set_use_date_folder(False)
    store.start_session(flat, "direct", ["MLOG"])
    store.append("MLOG", "no date folder")
    store.flush()
    store.stop_session()
    check("날짜 폴더 없이 지정 폴더에 바로 저장된다",
          os.path.exists(os.path.join(flat, "direct_mlog.log")),
          str(os.listdir(flat)) if os.path.exists(flat) else "폴더 없음")
    check("MMDD 하위 폴더를 만들지 않는다",
          not os.path.exists(os.path.join(flat, time.strftime("%m%d"))))

    # plan_paths — 기록을 시작하면 만들어질 경로를 미리 계산한다 (덮어쓰기 확인용)
    store2 = LogStore()
    store2.set_use_date_folder(False)
    store2.set_file_naming({"MLOG": "matter", MERGED_KEY: "merged"}, include_session=False)
    plandir = os.path.join(tmp, "plandir")
    plan = store2.plan_paths(plandir, "sess", ["MLOG"])
    check("plan_paths 가 포트·병합 파일 경로를 준다",
          plan.get("MLOG") == os.path.join(plandir, "matter.log")
          and plan.get(MERGED_KEY) == os.path.join(plandir, "merged.log"), str(plan))
    check("plan_paths 는 폴더·파일을 만들지 않는다", not os.path.exists(plandir))
    store2.start_session(plandir, "sess", ["MLOG"])
    store2.append("MLOG", "planned")
    store2.flush()
    store2.stop_session()
    check("plan 경로 그대로 실제 파일이 생긴다",
          os.path.exists(plan["MLOG"]) and os.path.exists(plan[MERGED_KEY]),
          str(os.listdir(plandir)) if os.path.exists(plandir) else "폴더 없음")

    # 날짜 폴더를 켠 상태(기본값)의 plan 도 실제 생성 규칙과 일치해야 한다
    store2b = LogStore()
    plan_dated = store2b.plan_paths(plandir, "dated", ["MLOG"])
    check("날짜 폴더 사용 시 plan 에도 MMDD 가 들어간다",
          plan_dated["MLOG"] == os.path.join(plandir, time.strftime("%m%d"), "dated_mlog.log"),
          str(plan_dated))

    # 덮어쓰기 — 기존 파일을 지우고 처음부터 새로 쓴다
    over = os.path.join(tmp, "overdir")
    os.makedirs(over, exist_ok=True)
    fixed = os.path.join(over, "fixed.log")
    with open(fixed, "w", encoding="utf-8") as fh:
        fh.write("old contents\n")
    store3 = LogStore()
    store3.set_use_date_folder(False)
    store3.set_file_naming({"MLOG": "fixed", MERGED_KEY: "fixedall"}, include_session=False)
    store3.start_session(over, "s1", ["MLOG"], overwrite=True)
    check("덮어쓰기는 시작 시점에 기존 파일을 지운다 (트래픽이 없어도)",
          not os.path.exists(fixed))
    store3.append("MLOG", "fresh line")
    store3.flush()
    store3.stop_session()
    with open(fixed, encoding="utf-8") as fh:
        body = fh.read()
    check("덮어쓴 파일에는 새 내용만 남는다",
          "old contents" not in body and "fresh line" in body, repr(body))

    # 기본은 이어쓰기 — 기존 증적을 조용히 지우지 않는다
    store4 = LogStore()
    store4.set_use_date_folder(False)
    store4.set_file_naming({"MLOG": "fixed", MERGED_KEY: "fixedall"}, include_session=False)
    store4.start_session(over, "s2", ["MLOG"])
    store4.append("MLOG", "appended line")
    store4.flush()
    store4.stop_session()
    with open(fixed, encoding="utf-8") as fh:
        body = fh.read()
    check("기본 동작은 이어쓰기 — 기존 내용이 보존된다",
          "fresh line" in body and "appended line" in body, repr(body))


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


def test_terminal_core() -> None:
    print("\n== 터미널 버퍼 (pyte 래퍼 — 플랫폼 무관) ==")
    from .core.terminal import BUFFER_AVAILABLE, TERMINAL_ERROR, TerminalBuffer

    if not BUFFER_AVAILABLE:
        print(f"  [SKIP] pyte 미설치 — {TERMINAL_ERROR}")
        return

    buf = TerminalBuffer(20, 5, history=100)
    gen0 = buf.generation
    buf.feed("plain \x1b[31mred\x1b[0m tail")
    check("feed 로 generation 이 증가한다", buf.generation > gen0)
    frame = buf.snapshot()
    check("스냅샷 행 수 = rows", len(frame.rows) == 5, str(len(frame.rows)))
    runs = frame.rows[0]
    texts = [run.text for run in runs]
    check("같은 속성 구간이 run 으로 합쳐진다", "".join(texts).startswith("plain red tail"),
          str(texts))
    red = next((run for run in runs if run.text == "red"), None)
    check("SGR 색이 run 에 남는다", red is not None and red.fg == "red",
          str([(run.text, run.fg) for run in runs]))
    plain = next((run for run in runs if "plain" in run.text), None)
    check("색 없는 구간은 기본 전경", plain is not None and plain.fg == "default", str(plain))

    buf.feed("\r\n\x1b[1mbold\x1b[0m")
    frame = buf.snapshot()
    bold = next((run for run in frame.rows[1] if run.text == "bold"), None)
    check("굵게 속성", bold is not None and bold.bold, str(frame.rows[1]))
    check("커서 위치", frame.cursor == (4, 1, True), str(frame.cursor))

    buf.feed("\x1b[2J\x1b[H")   # 화면 지움 + 홈
    frame = buf.snapshot()
    check("화면 지움이 반영된다", all(not run.text.strip() for row in frame.rows for run in row),
          str(frame.rows[0]))

    buf.resize(10, 3)
    frame = buf.snapshot()
    check("resize 반영", len(frame.rows) == 3 and buf.cols == 10)

    # 전각(한글) — pyte 는 뒤 칸에 data='' 연속 셀을 둔다. 이를 공백으로 바꾸면
    # 화면에서 글자마다 틈이 생긴다 (실기 보고: "용 어 가  cmdlet…")
    wide = TerminalBuffer(20, 3)
    wide.feed("가나 ab다")
    row = wide.snapshot().rows[0]
    joined = "".join(run.text for run in row)
    check("전각 연속 셀이 가짜 공백이 되지 않는다",
          joined.startswith("가나 ab다"), repr(joined))
    check("run 의 cells 합 = 화면 폭 (칸 단위 위치 계산)",
          sum(run.cells for run in row) == 20,
          str([(run.text, run.cells) for run in row]))
    check("전각 문자 run 은 2칸을 차지한다",
          row[0].text == "가" and row[0].cells == 2, str(row[0]))
    narrow = next((run for run in row if "ab" in run.text), None)
    check("반각 run 의 cells = 글자 수",
          narrow is not None and narrow.cells == len(narrow.text), str(narrow))

    # 스크롤백 — 행보다 많은 줄을 흘리면 히스토리로 밀리고 페이징으로 돌아온다
    buf2 = TerminalBuffer(10, 3, history=100)
    for i in range(8):
        buf2.feed(f"line{i}\r\n")
    check("현재 화면에는 마지막 줄들만", "line7" in buf2.text() and "line0" not in buf2.text(),
          buf2.text())
    for _ in range(3):
        buf2.page_up()   # ratio 0.1 — 3행 화면이면 한 번에 1줄 (휠 한 칸 단위)
    check("page_up 으로 히스토리가 보인다", "line4" in buf2.text() and "line7" not in buf2.text(),
          buf2.text())
    for _ in range(3):
        buf2.page_down()
    check("page_down 으로 현재 화면 복귀", "line7" in buf2.text(), buf2.text())

    # 스크롤백 중 새 출력 — pyte 는 페이징이 buffer 자체를 돌려놓기 때문에, 그대로
    # feed 하면 과거 화면 위에 출력이 섞인다. feed 가 먼저 최신으로 복귀해야 한다.
    buf2.page_up()
    buf2.feed("line8\r\n")
    check("스크롤백 중 출력이 오면 최신 화면으로 복귀해 이어 쓴다",
          "line8" in buf2.text(), buf2.text())
    buf2.page_up()
    buf2.scroll_to_bottom()
    check("scroll_to_bottom 으로 즉시 최신 화면", "line8" in buf2.text(), buf2.text())

    # 스크롤 위치 — 오른쪽 스크롤바가 어디쯤인지 그리는 근거
    value, maximum = buf2.scroll_state()
    check("맨 아래에서는 value == maximum", value == maximum and maximum > 0,
          f"{value}/{maximum}")
    buf2.page_up()
    up_value, up_max = buf2.scroll_state()
    check("스크롤백으로 올라가면 value 가 준다", up_value < value and up_max == maximum,
          f"{up_value}/{up_max}")
    buf2.scroll_to(maximum)
    check("scroll_to(maximum) 은 맨 아래", buf2.scroll_state()[0] == maximum,
          str(buf2.scroll_state()))
    buf2.scroll_to(0)
    check("scroll_to(0) 은 맨 위", buf2.scroll_state()[0] == 0, str(buf2.scroll_state()))

    # reset — 재시작한 셸이 화면 중간에 그려지던 실기 문제. 새 셸 = 깨끗한 화면.
    gen_before = buf2.generation
    buf2.reset()
    check("reset 후 화면이 비고 generation 이 오른다",
          buf2.text().strip() == "" and buf2.generation > gen_before, repr(buf2.text()))
    buf2.feed("fresh\r\n")
    check("reset 후 출력은 맨 윗줄부터", buf2.text().splitlines()[0].strip() == "fresh",
          repr(buf2.text()))
    buf2.page_up()
    check("reset 은 히스토리도 비운다 (과거 line 이 안 나온다)",
          "line" not in buf2.text(), buf2.text())


def test_terminal_pty() -> None:
    print("\n== 터미널 세션 (ConPTY — Windows 에서만) ==")
    from .core import terminal as terminal_mod

    if not terminal_mod.TERMINAL_AVAILABLE or sys.platform != "win32":
        print(f"  [SKIP] pywinpty/pyte 미가용 — {terminal_mod.TERMINAL_ERROR or 'non-windows'}")
        return

    session = terminal_mod.TerminalSession(["cmd.exe"], cols=100, rows=24)
    check("세션이 살아 있다", wait_until(lambda: session.alive, timeout=10.0))
    session.write("echo serialhub-pty-check\r")
    check("echo 왕복이 화면 버퍼에 도착한다",
          wait_until(lambda: "serialhub-pty-check" in session.buffer.text(), timeout=10.0),
          session.buffer.text()[-200:])
    session.resize(80, 20)
    check("resize 반영", session.buffer.cols == 80 and session.buffer.rows == 20)
    session.write("exit\r")
    check("종료를 감지한다", wait_until(lambda: not session.alive, timeout=10.0))
    check("종료 코드가 남는다", wait_until(lambda: session.exit_status is not None, timeout=5.0),
          str(session.exit_status))
    session.close()
    check("close 후 reader 스레드 종료",
          session._reader is None or not session._reader.is_alive())

    # close() 는 살아 있는 세션도 확실히 끝낸다 (도크 닫기 = 프로세스 종료)
    session2 = terminal_mod.TerminalSession(["cmd.exe"], cols=80, rows=20)
    wait_until(lambda: session2.alive, timeout=10.0)
    session2.close()
    check("close 가 살아 있는 프로세스를 끝낸다",
          wait_until(lambda: not session2.alive, timeout=5.0))


def test_release_tooling(tmp: str) -> None:
    print("\n== 릴리스 배포 도구 (산출물 선택) ==")
    from .publish_release import ReleaseError, find_artifacts, repo_slug

    # 원격이 SSH 별칭(git@github-bari:...)이어도 gh 가 저장소를 알아야 한다
    check("SSH 별칭 원격에서 owner/repo 를 뽑는다",
          repo_slug("git@github-bari:bari-psy77/serial-hub-monitor.git")
          == "bari-psy77/serial-hub-monitor")
    check("표준 SSH 원격도 같다",
          repo_slug("git@github.com:owner/repo.git") == "owner/repo")
    check("HTTPS 원격도 같다",
          repo_slug("https://github.com/owner/repo.git") == "owner/repo")
    check("알 수 없는 형식은 빈 문자열", repo_slug("file:///tmp/x") == "")

    dist = os.path.join(tmp, "reldist")
    os.makedirs(dist, exist_ok=True)

    try:
        find_artifacts(dist, "1.4.0")
        check("산출물이 없으면 알려준다", False, "예외가 안 났다")
    except ReleaseError as exc:
        check("산출물이 없으면 알려준다", "Setup" in str(exc), str(exc))

    setup = os.path.join(dist, "SerialHub_Setup_1.4.0.exe")
    old_zip = os.path.join(dist, "SerialHub_20260814.zip")
    new_zip = os.path.join(dist, "SerialHub_20260901.zip")
    for path in (setup, old_zip, new_zip):
        with open(path, "wb") as fh:
            fh.write(b"x" * 16)
    os.utime(old_zip, (time.time() - 600, time.time() - 600))

    found = find_artifacts(dist, "1.4.0")
    check("이 버전의 설치본을 고른다", found.installer == setup, found.installer)
    check("포터블 zip 은 가장 최신 것만 고른다", found.portable == new_zip, found.portable)
    check("배포 대상은 두 개뿐", len(found.paths()) == 2, str(found.paths()))

    # 버전이 다른 설치본만 있으면 오해 없이 실패해야 한다 (옛 파일을 올리는 사고 방지)
    os.remove(setup)
    with open(os.path.join(dist, "SerialHub_Setup_1.3.0.exe"), "wb") as fh:
        fh.write(b"x")
    try:
        find_artifacts(dist, "1.4.0")
        check("버전이 다르면 올리지 않는다", False, "예외가 안 났다")
    except ReleaseError as exc:
        check("버전이 다르면 올리지 않는다", "1.4.0" in str(exc), str(exc))


    # 403 은 거의 항상 토큰 권한 문제다 — 사용자가 무엇을 고칠지 알 수 있어야 한다
    from .publish_release import describe_args, permission_hint
    hint = permission_hint(
        "HTTP 403: Resource not accessible by personal access token")
    check("403 이면 토큰 권한 안내를 붙인다",
          "Contents" in hint and "Read and write" in hint, hint)
    check("다른 오류에는 권한 안내를 붙이지 않는다",
          permission_hint("HTTP 404: Not Found") == "")
    summary = describe_args(["release", "create", "v1.4.0",
                             r"C:\dist\SerialHub_Setup_1.4.0.exe",
                             "--notes", "아주 긴 릴리스 노트 " * 40])
    check("에러 메시지에 릴리스 노트 본문을 쏟지 않는다",
          "<생략>" in summary and len(summary) < 120, summary)
    check("경로는 파일명만 남긴다",
          "SerialHub_Setup_1.4.0.exe" in summary and "C:" not in summary, summary)


    # 릴리스 노트는 CHANGELOG 의 해당 버전 절을 그대로 쓴다
    from .publish_release import read_version, release_notes
    from . import __version__ as pkg_version

    notes = release_notes(pkg_version)
    check("릴리스 노트가 이 버전 절을 담는다",
          notes.startswith(f"## {pkg_version}"), notes[:60])
    check("릴리스 노트에 받는 파일 안내가 붙는다",
          "SerialHub_Setup_" in notes and "--selfcheck" in notes, notes[-200:])
    check("publish_release 가 읽는 버전이 패키지 버전과 같다",
          read_version() == pkg_version, f"{read_version()} vs {pkg_version}")

    # ★CHANGELOG 맨 위 절이 곧 이번 릴리스다 — 버전이 어긋나면 엉뚱한 노트가 올라간다
    changelog = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "CHANGELOG.md"), encoding="utf-8").read()
    heads = re.findall(r"^## (\S+)\s+—\s+(\S+)", changelog, re.M)
    check("CHANGELOG 최상단 버전이 현재 버전과 같다",
          bool(heads) and heads[0][0] == pkg_version,
          str(heads[:2]))
    check("CHANGELOG 최상단 항목에 날짜가 적혀 있다",
          bool(heads) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", heads[0][1]),
          str(heads[:1]))


def test_selfcheck() -> None:
    print("\n== --selfcheck (빌드 점검) ==")
    from .app import selfcheck, terminal_status

    ok, lines = selfcheck()
    body = "\n".join(lines)
    check("소스 실행 환경에서는 통과한다", ok, body)
    check("pyserial 항목이 있다", "pyserial" in body, body)
    check("PySide6 항목이 있다", "PySide6" in body, body)
    # 내장 터미널 의존성(pywinpty/pyte)은 임포트 가드 뒤에 있어 번들에서 빠져도
    # 화면상으론 "설치해 주세요" 안내로만 보인다 — 빌드 점검이 잡아야 한다
    check("내장 터미널 항목이 있다 (번들 누락을 여기서 잡는다)",
          "terminal" in body.lower() or "터미널" in body, body)

    # ★Windows 전용 기능이라 리눅스 CI 에서는 '없음' 이 정상이다 — 그걸로 빌드를
    #   실패시키면 CI 가 늘 빨갛다 (실제로 이 검사를 넣고 한 번 깨뜨렸다)
    ok_win, line_win = terminal_status("win32", available=True, error="")
    check("Windows + 가용 = 통과", ok_win and "OK" in line_win, line_win)
    ok_missing, line_missing = terminal_status("win32", available=False, error="no module")
    check("Windows 에서 빠져 있으면 실패로 잡는다",
          not ok_missing and "FAIL" in line_missing, line_missing)
    ok_linux, line_linux = terminal_status("linux", available=False, error="no module")
    check("다른 플랫폼에서는 실패시키지 않는다 (CI)", ok_linux, line_linux)
    check("다른 플랫폼에서는 확인하지 않았다고 알린다", "FAIL" not in line_linux, line_linux)


def test_redact() -> None:
    print("\n== redact ==")
    redactor = Redactor([
        RedactRule(r"(?i)\bwifi\s+connect\s+\S+\s+(\S+)", "<PSK-redacted>"),
        RedactRule(r"secret-\d+", "<gone>"),
    ])
    masked = redactor.apply("wifi connect NTGR_F699 hunter2pass")
    check("그룹1만 치환", masked == "wifi connect NTGR_F699 <PSK-redacted>", masked)
    check("SSID 는 남는다", "NTGR_F699" in masked, masked)
    whole = redactor.apply("token secret-12345 end")
    check("그룹 없으면 매치 전체 치환", whole == "token <gone> end", whole)
    check("깨진 regex 는 무시", Redactor([RedactRule("(unclosed", "x")]).apply("(unclosed") == "(unclosed")

    store = LogStore()
    store.set_redactor(redactor)
    line = store.append("SHELL", "wifi connect AP hunter2pass", is_tx=True)
    check("ring 에 원문이 남지 않는다", "hunter2pass" not in line.text, line.text)

    literal = Redactor([RedactRule("pass+word(1)", "<lit>", is_regex=False)])
    check("리터럴 모드는 메타문자를 그대로 찾는다",
          literal.apply("token pass+word(1) end") == "token <lit> end",
          literal.apply("token pass+word(1) end"))
    regex_mode = Redactor([RedactRule("pass+word(1)", "<lit>", is_regex=True)])
    check("regex 모드로는 같은 문자열이 안 잡힌다 (리터럴 모드가 필요한 이유)",
          "pass+word(1)" in regex_mode.apply("token pass+word(1) end"))

    reporter = Redactor()
    invalid = reporter.set_rules([RedactRule("(unclosed", "x"), RedactRule("ok", "y")])
    check("깨진 redact 룰을 조용히 버리지 않고 보고한다", invalid == ["(unclosed"], str(invalid))
    check("멀쩡한 룰은 살아 있다", reporter.apply("ok") == "y")


def test_filters() -> None:
    print("\n== 필터 ==")
    store = LogStore()
    store.append("MLOG", "CASE session established")
    store.append("SHELL", "no match here")
    store.append("MLOG", "case insensitive")
    lines = store.pull(-1)

    rule = FilterRule(pattern="CASE")
    hits = [ln.text for ln in lines if rule.match(ln)]
    check("substring 은 기본 대소문자 무시", len(hits) == 2, str(hits))

    rule_cs = FilterRule(pattern="CASE", case_sensitive=True)
    check("대소문자 구분", len([ln for ln in lines if rule_cs.match(ln)]) == 1)

    rule_port = FilterRule(pattern="", ports=["SHELL"])
    check("포트 한정", [ln.text for ln in lines if rule_port.match(ln)] == ["no match here"])

    meta = FilterRule(pattern="[ZCL]")
    store.append("MLOG", "[ZCL] attribute")
    check("substring 은 regex 메타를 escape",
          any(meta.match(ln) for ln in store.pull(-1)), "[ZCL] 매치 실패")

    broken = FilterRule(pattern="(unclosed", is_regex=True)
    check("깨진 regex 는 전부 차단", not any(broken.match(ln) for ln in store.pull(-1)))
    check("하이라이트 룰 색 매핑", HighlightRule("x", "주황").qcolor_hex().startswith("#"))


    # 하이라이트 색은 테마를 따라가되, **이름은 프로파일에 저장되는 식별자**라 고정이다
    from .core import filters as filters_mod
    light_names = filters_mod.highlight_names()
    light_red = filters_mod.highlight_hex("빨강")
    light_search = filters_mod.search_hex()
    filters_mod.set_theme("dark")
    check("하이라이트 이름은 테마와 무관하게 같다 (프로파일 호환)",
          filters_mod.highlight_names() == light_names, str(filters_mod.highlight_names()))
    check("다크에서는 색 값이 달라진다",
          filters_mod.highlight_hex("빨강") != light_red,
          f"{light_red} -> {filters_mod.highlight_hex('빨강')}")
    check("검색 하이라이트도 테마를 따른다",
          filters_mod.search_hex() != light_search and filters_mod.search_hex().startswith("#"))
    check("모르는 이름은 기본색으로 폴백",
          filters_mod.highlight_hex("없는색")
          == filters_mod.highlight_hex(filters_mod.DEFAULT_HIGHLIGHT_COLOR))
    check("룰의 색도 테마를 따라간다",
          HighlightRule("X", "빨강").qcolor_hex() == filters_mod.highlight_hex("빨강"))
    filters_mod.set_theme("light")
    check("되돌리면 원래 색", filters_mod.highlight_hex("빨강") == light_red)

def test_probe_classification() -> None:
    print("\n== probe 판정 ==")
    token = portscan.DEFAULT_PROBE_TOKEN

    shell_out = f"> {token}\r\nError {token}: 2f (Invalid argument)\r\n"
    verdict, evidence = portscan.classify_probe_text(shell_out, token)
    check("Matter shell 서명 → SHELL", verdict == portscan.ROLE_SHELL, f"{verdict} / {evidence}")

    ucli_out = f"{token}\r\n\r\nInvalid command\r\n"
    verdict, _ = portscan.classify_probe_text(ucli_out, token)
    check("user_cli 서명 → UCLI", verdict == portscan.ROLE_UCLI, verdict)

    noise = "[ZCL] some log line\r\n[DIS] another\r\n"
    verdict, _ = portscan.classify_probe_text(noise, token)
    check("로그만 흐르면 미확정", verdict == portscan.VERDICT_UNKNOWN, verdict)

    stale = f"Invalid command\r\n{token}\r\nError {token}: 2f (Invalid argument)\r\n"
    verdict, _ = portscan.classify_probe_text(stale, token)
    check("에코 앞의 잔여 출력은 무시 (echo-anchor)", verdict == portscan.ROLE_SHELL, verdict)

    # 에코가 없으면 토큰을 품지 않은 서명은 인정하지 않는다 (fail-closed)
    noecho_noise = "[ZCL] boot\r\nInvalid command found in payload\r\n[DIS] mDNS\r\n"
    verdict, _ = portscan.classify_probe_text(noecho_noise, token)
    check("에코 없이 흘러온 문자열만으로는 UCLI 로 단정하지 않는다",
          verdict == portscan.VERDICT_UNKNOWN, verdict)
    noecho_anchored = f"Error {token}: 2f (Invalid argument)\r\n"
    verdict, _ = portscan.classify_probe_text(noecho_anchored, token)
    check("에코가 없어도 토큰을 품은 서명은 인정한다", verdict == portscan.ROLE_SHELL, verdict)

    check("COM10+ 는 \\\\.\\ 접두어", portscan.port_name("COM11") == "\\\\.\\COM11",
          portscan.port_name("COM11"))
    check("COM9 이하는 그대로", portscan.port_name("COM4") == "COM4")


def test_port_reader() -> None:
    print("\n== PortReader (가짜 시리얼) ==")
    store = LogStore()
    fake = FakeSerial([b"first line\r\n", b"second ", b"line\r\n"])
    created: list[FakeSerial] = [fake]

    def fake_open(_com, _baud, timeout=0.05):  # noqa: ARG001
        return created[-1]

    original = portscan.open_serial
    portscan.open_serial = fake_open
    try:
        reader = PortReader("MLOG", "COM99", 115200, store)
        ok, err = reader.start()
        check("가짜 포트 open", ok, err)
        check("라인 조립 (CRLF 분리)",
              wait_until(lambda: [ln.text for ln in store.pull(-1, ["MLOG"])] ==
                         ["first line", "second line"]),
              str([ln.text for ln in store.pull(-1, ['MLOG'])]))

        seq = store.last_seq()
        fake.feed(b"> ")  # 개행 없는 프롬프트
        check("개행 없는 프롬프트도 표시된다",
              wait_until(lambda: any("<partial>" in ln.text
                                     for ln in store.pull(seq, ["MLOG"])), timeout=2.0))

        ok, err = reader.send("otcli state")
        check("송신 성공", ok, err)
        check("시리얼로 CRLF 종단 전송", fake.written and fake.written[-1] == b"otcli state\r\n",
              str(fake.written))
        check("TX 에코가 ring 에 남는다",
              any(ln.is_tx and ln.text == "otcli state" for ln in store.pull(-1, ["MLOG"])))

        # 읽기 실패 → 재접속 배너 → 새 핸들로 복구
        seq = store.last_seq()
        replacement = FakeSerial([b"after reopen\r\n"])
        created.append(replacement)
        fake.fail_after = 0
        reader.reconnect_interval = 0.1
        check("read error 배너",
              wait_until(lambda: any("read error" in ln.text
                                     for ln in store.pull(seq, ["MLOG"])), timeout=3.0))
        check("자동 재접속 후 reopened 배너",
              wait_until(lambda: any("reopened" in ln.text
                                     for ln in store.pull(seq, ["MLOG"])), timeout=3.0))
        check("재접속 후 수신 재개",
              wait_until(lambda: any("after reopen" in ln.text
                                     for ln in store.pull(seq, ["MLOG"])), timeout=3.0))
        # 끊기기 직전의 부분 라인을 버리지 않는다
        seq = store.last_seq()
        broken = FakeSerial()
        created.append(broken)
        broken.feed(b"last words before death")
        time.sleep(0.05)
        broken.fail_after = broken.reads + 1
        reader._ser = broken
        check("끊기기 직전 부분 라인이 살아남는다",
              wait_until(lambda: any("last words before death" in ln.text
                                     for ln in store.pull(seq, ["MLOG"])), timeout=3.0),
              str([ln.text for ln in store.pull(seq, ["MLOG"])][:4]))

        seq = store.last_seq()
        check("정상 stop 은 True 를 돌려준다", reader.stop() is True)
        check("stop 후 스레드 종료", not reader.is_running)
        check("정상 해제는 read error 배너를 남기지 않는다",
              not any("read error" in ln.text for ln in store.pull(seq, ["MLOG"])),
              str([ln.text for ln in store.pull(seq, ["MLOG"])]))
    finally:
        portscan.open_serial = original


def test_port_reader_probe() -> None:
    print("\n== PortReader.probe (라이브 경로) ==")
    store = LogStore()
    fake = FakeSerial()
    original = portscan.open_serial
    portscan.open_serial = lambda _c, _b, timeout=0.05: fake  # noqa: ARG005
    try:
        reader = PortReader("SHELL", "COM98", 115200, store)
        reader.start()
        token = portscan.DEFAULT_PROBE_TOKEN

        def answer() -> None:
            time.sleep(0.4)
            fake.feed(f"Error {token}: 2f (Invalid argument)\r\n".encode())

        threading.Thread(target=answer, daemon=True).start()
        result = reader.probe(token, passive_seconds=0.1, response_timeout=2.0)
        check("라이브 probe 가 SHELL 판정", result.verdict == portscan.ROLE_SHELL, result.detail)
        check("probe 는 토큰 1줄만 보낸다",
              fake.written == [token.encode() + b"\r\n"], str(fake.written))
        reader.stop()
    finally:
        portscan.open_serial = original


def test_profile(tmp: str) -> None:
    print("\n== 프로파일 ==")
    original_dir = config_mod.PROFILE_DIR
    original_settings = config_mod.SETTINGS_PATH  # 실제 설정 파일을 건드리면 안 된다
    config_mod.PROFILE_DIR = os.path.join(tmp, "profiles")
    config_mod.SETTINGS_PATH = os.path.join(tmp, "settings.json")
    try:
        profile = Profile()
        profile.name = "unit-bench"
        profile.ports = [PortConfig("MLOG", "COM4"), PortConfig("SHELL", "COM5"),
                         PortConfig("UCLI", "COM8")]
        profile.saved_filters = [FilterRule(pattern="CASE", name="case")]
        profile.command_history = {"SHELL": ["otcli state"]}
        ok, path = profile.save()
        check("프로파일 저장", ok, path)

        loaded, warning = Profile.load("unit-bench")
        check("프로파일 왕복", not warning and loaded.port("SHELL").com == "COM5",
              f"{warning} / {loaded.to_dict()}")
        check("필터 왕복", loaded.saved_filters[0].pattern == "CASE")
        check("히스토리 왕복", loaded.command_history.get("SHELL") == ["otcli state"])
        check("COM 기본값은 비어 있다 (FR-9 하드코딩 금지)",
              all(p.com == "" for p in Profile().ports))

        # 로그 기본 위치: 설치 시 고른 값 > 기존 벤치 경로 > Windows 문서 폴더
        config_mod.save_settings({"log_base_dir": r"D:\chosen\by\installer"})
        check("설치 시 지정한 로그 위치가 새 프로파일 기본값이 된다",
              Profile().log_base_dir == r"D:\chosen\by\installer", Profile().log_base_dir)
        config_mod.save_settings({})
        fallback = config_mod.default_log_base()
        check("지정이 없으면 데이터 폴더 아래 logs 를 쓴다 (개인 경로 하드코딩 금지)",
              fallback == os.path.join(config_mod.DATA_DIR, "logs"), fallback)
        # 하드코딩이 아니라 "설치 위치를 따라간다" 는 것을 확인 — DATA_DIR 을 옮기면 같이 옮겨야 한다
        moved_dir = os.path.join(tmp, "elsewhere")
        original_data = config_mod.DATA_DIR
        config_mod.DATA_DIR = moved_dir
        try:
            check("설치 위치가 바뀌면 로그 기본값도 따라간다",
                  config_mod.default_log_base() == os.path.join(moved_dir, "logs"),
                  config_mod.default_log_base())
        finally:
            config_mod.DATA_DIR = original_data
        check("기존 프로파일의 로그 위치는 설치값이 덮어쓰지 않는다",
              Profile.from_dict({"log_base_dir": r"E:\kept"}).log_base_dir == r"E:\kept")

        # 날짜(MMDD) 하위 폴더는 옵션이다 — 기본은 save location 에 바로 저장 (사용자 합의)
        check("날짜 하위 폴더 저장은 기본 꺼짐", Profile().log_use_date_folder is False)
        check("날짜 폴더 설정 왕복",
              Profile.from_dict({"log_use_date_folder": True}).log_use_date_folder is True
              and Profile.from_dict({}).log_use_date_folder is False)

        # 화면 언어: 설정이 없으면 영어가 기본, settings.json 에 적어둔 값은 그대로 존중
        config_mod.save_settings({})
        check("언어 미지정이면 기본값은 영어", config_mod.language() == "en", config_mod.language())
        config_mod.save_settings({})
        check("테마 기본값은 light", config_mod.theme() == "light", config_mod.theme())
        config_mod.set_theme_setting("dark")
        check("테마가 settings.json 에 남는다 (종료 후 다시 켜도 유지)",
              config_mod.theme() == "dark", config_mod.theme())
        config_mod.save_settings({"theme": "없는테마"})
        check("모르는 테마 값은 light 로 폴백", config_mod.theme() == "light")
        config_mod.save_settings({})
        config_mod.save_settings({"language": "ko"})
        check("settings.json 에 명시한 언어는 기본값과 무관하게 유지된다",
              config_mod.language() == "ko", config_mod.language())
        config_mod.save_settings({})

        broken = Profile.path_for("broken")
        os.makedirs(config_mod.PROFILE_DIR, exist_ok=True)
        with open(broken, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        recovered, warning = Profile.load("broken")
        check("깨진 프로파일도 기동은 된다", recovered.roles() == ["MLOG", "SHELL", "UCLI"])
        check("깨진 프로파일 경고 + .bak 보존",
              bool(warning) and os.path.exists(broken + ".bak"), warning)

        # 프로파일 JSON 은 벤치 간 복사·공유용이다. 로그에서 지운 비밀값이 여기 남으면 안 된다
        secret = Profile()
        secret.name = "unit-secret"
        secret.set_redactor(Redactor(DEFAULT_REDACT_RULES))
        secret.command_history = {"SHELL": ["wifi connect NTGR hunter2pass"]}
        secret.scratchpad = "dataset networkkey 00112233445566778899aabbccddeeff\notcli state"
        secret.save()
        with open(Profile.path_for("unit-secret"), "r", encoding="utf-8") as fh:
            raw = fh.read()
        check("프로파일에 명령 히스토리의 PSK 가 평문으로 안 남는다", "hunter2pass" not in raw)
        check("프로파일에 스크래치패드의 networkkey 가 평문으로 안 남는다",
              "00112233445566778899aabbccddeeff" not in raw)
        check("마스킹해도 명령 형태는 남아 재사용 가능", "wifi connect NTGR" in raw)
    finally:
        config_mod.PROFILE_DIR = original_dir
        config_mod.SETTINGS_PATH = original_settings


def test_session(tmp: str) -> None:
    print("\n== SerialHubSession ==")
    profile = Profile()
    profile.log_base_dir = tmp
    profile.ports = [PortConfig("MLOG", "COM97"), PortConfig("SHELL", ""), PortConfig("UCLI", "")]
    session = SerialHubSession(profile)
    fake = FakeSerial([b"boot\r\n"])
    original = portscan.open_serial
    portscan.open_serial = lambda _c, _b, timeout=0.05: fake  # noqa: ARG005
    try:
        name = session.start_recording()
        check("세션명 자동 생성", name.startswith(profile.session_prefix), name)
        planned = session.plan_recording(name)
        actual = session.store.file_paths()
        check("plan_recording 이 실제 기록 경로와 일치한다",
              planned.get("MLOG") == actual.get("MLOG"), f"{planned} vs {actual}")
        check("프로파일 기본값은 날짜 폴더 없이 base 에 바로 기록한다",
              os.path.dirname(actual.get("MLOG", "")) == tmp, str(actual))
        results = session.connect_all()
        check("COM 미지정 포트는 건너뛴다", len(results) == 1, str(results))
        check("연결 상태 조회", wait_until(lambda: session.is_connected("MLOG")))
        check("미연결 포트 전송은 거부", session.send("SHELL", "x")[0] is False)
        session.shutdown()
        check("shutdown 후 전부 해제", not session.any_connected())
    finally:
        portscan.open_serial = original


# ---------------------------------------------------------------------- GUI

def test_gui(tmp: str) -> None:
    print("\n== GUI (offscreen) ==")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QComboBox

    from .core import ansi as ansi_mod
    from .core import filters as filters_mod
    from .core.filters import FilterRule as FR
    from .core.filters import TriggerRule
    from .ui import theme
    from .ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)

    # 창을 닫으면 프로파일이 저장된다 — 실제 profiles/ 를 더럽히지 않도록 임시 폴더로 돌린다
    original_profile_dir = config_mod.PROFILE_DIR
    original_settings = config_mod.SETTINGS_PATH
    config_mod.PROFILE_DIR = os.path.join(tmp, "gui-profiles")
    config_mod.SETTINGS_PATH = os.path.join(tmp, "gui-settings.json")

    # Qt 슬롯 안에서 난 예외는 조용히 삼켜진다 — 잡아서 실패로 만든다
    slot_errors: list[str] = []
    original_hook = sys.excepthook

    def _record(exc_type, exc, tb):
        slot_errors.append(f"{exc_type.__name__}: {exc}")
        original_hook(exc_type, exc, tb)  # 기록만 하고 삼키면 테스트 자체의 예외도 안 보인다

    sys.excepthook = _record

    profile = Profile()
    profile.name = "__selftest__"
    profile.log_base_dir = tmp
    profile.highlight_rules = [HighlightRule("CASE", "빨강")]
    window = MainWindow(profile)
    window.show()

    store = window.session.store
    for i in range(500):
        store.append("MLOG", f"[ZCL] CASE line {i}")
    store.append("SHELL", "otcli state", is_tx=True)
    store.append("UCLI", "")
    window.tick()
    pump(app)

    mlog_pane = window.panes["MLOG"]
    check("콘솔에 수신 라인 반영", "CASE line 499" in mlog_pane.view.toPlainText())
    check("빈 라인 숨김 기본 on", window.panes["UCLI"].view.toPlainText().strip() == "",
          repr(window.panes["UCLI"].view.toPlainText()))
    window.panes["UCLI"].empty_button.setChecked(False)
    pump(app)
    check("빈 라인 숨김 해제하면 보인다",
          window.panes["UCLI"].view.toPlainText() != "", "빈 줄이 여전히 숨겨짐")

    before = mlog_pane.view.toPlainText().splitlines()[0]
    mlog_pane.cycle_ts_mode()
    after = mlog_pane.view.toPlainText().splitlines()[0]
    check("타임스탬프 토글이 과거 라인까지 다시 그린다", before != after, f"{before} / {after}")

    mlog_pane.focus_search()
    mlog_pane.search.edit.setText("CASE line 4")
    mlog_pane.step_match(1)  # 디바운스를 건너뛰고 즉시 검색
    pump(app)
    check("검색 매치 카운트", mlog_pane.search.count_label.text() not in ("0/0", ""),
          mlog_pane.search.count_label.text())

    from PySide6.QtWidgets import QDockWidget as _QDockWidget
    window.open_filter_view(FR(pattern="line 12", ports=["MLOG"]))
    view = window.filter_views[-1]
    pump(app)
    check("필터드뷰는 하단 도크로 뜬다 (독립 창이 아니라)",
          isinstance(view, _QDockWidget) and not view.isFloating()
          and window.dockWidgetArea(view) == Qt.BottomDockWidgetArea,
          f"floating={view.isFloating()}")
    check("필터드뷰에도 최대화 버튼이 있다", hasattr(view, "maximize_button"))
    view.setFloating(True)
    pump(app)
    check("떼어내 독립 창으로도 쓸 수 있다", view.isFloating() and view.isVisible())
    view.setFloating(False)
    pump(app)
    view.pump()
    pump(app)
    text = view.pane.view.toPlainText()
    check("필터드뷰 소급 채움", "line 12" in text, text[:120])
    check("필터드뷰는 매치만 표시", "line 300" not in text)
    check("필터드뷰는 prefix 를 붙인다", "[MLOG]" in text, text[:120])
    view.close()
    check("필터드뷰 닫으면 목록에서 빠진다", view not in window.filter_views)

    window.command_panel.edit.setText("wifi connect AP hunter2pass")
    pump(app)
    check("입력 중 redact 미리보기", "hunter2pass" not in window.command_panel.hint.text(),
          window.command_panel.hint.text())

    # 로그 저장 옵션 — 날짜 폴더 체크박스도 [확인](commit) 을 거쳐야 반영된다
    from .ui.log_page import LogPage
    lp_profile = Profile()
    lp_profile.log_base_dir = tmp
    log_page = LogPage(lp_profile)
    check("날짜 폴더 체크박스 기본값은 프로파일(꺼짐)을 따른다",
          not log_page.date_folder_box.isChecked())
    hint_off = log_page.dir_hint.text()
    log_page.date_folder_box.setChecked(True)
    hint_on = log_page.dir_hint.text()
    check("체크 상태에 따라 저장 위치 안내문이 바뀐다", hint_off != hint_on and bool(hint_on),
          f"{hint_off!r} / {hint_on!r}")
    check("입력만으로는 프로파일에 반영되지 않는다", lp_profile.log_use_date_folder is False)
    log_page.commit()
    check("commit 하면 날짜 폴더 설정이 프로파일에 반영된다",
          lp_profile.log_use_date_folder is True)
    log_page.date_folder_box.setChecked(False)
    log_page.revert()
    check("revert 하면 프로파일 값으로 되돌아간다", log_page.date_folder_box.isChecked())

    # 테마 전환 — QSS 재적용만으로 덮이지 않는 것들이 핵심이다
    from .ui import theme as theme_mod
    window.change_font(0)
    window.change_font(4)                     # 12 -> 16 으로 키워 둔다
    zoomed = profile.console_font_size
    light_console_bg = theme_mod.CONSOLE_BG
    light_pill = theme_mod.state_color("connected")

    window.apply_theme_change("dark")
    pump(app)
    check("테마가 다크로 바뀐다", theme_mod.CURRENT == "dark", theme_mod.CURRENT)
    check("콘솔 배경 토큰이 어두워진다", theme_mod.CONSOLE_BG != light_console_bg,
          f"{light_console_bg} -> {theme_mod.CONSOLE_BG}")
    check("상태 색도 새 팔레트를 쓴다", theme_mod.state_color("connected") != light_pill)
    check("★전환해도 글자 크기가 유지된다 (repolish 가 setFont 를 되돌린다)",
          mlog_pane.font_size() == zoomed, f"{mlog_pane.font_size()} vs {zoomed}")
    check("로그 본문 색도 다크 팔레트를 쓴다",
          ansi_mod.resolve("32") == ansi_mod.PALETTES["dark"]["fg"][32],
          ansi_mod.resolve("32"))
    check("하이라이트 색도 다크로 바뀐다",
          filters_mod.highlight_hex("빨강") == filters_mod.HIGHLIGHT_PALETTES["dark"]["빨강"])
    rules_combo = None
    for child in window.settings().rules_page.findChildren(QComboBox):
        if child.currentData() in filters_mod.highlight_names():
            rules_combo = child
            break
    check("규칙 페이지의 색 미리보기도 다크를 따른다 (실사용 신고)",
          rules_combo is not None
          and filters_mod.highlight_hex(rules_combo.currentData()) in rules_combo.styleSheet(),
          rules_combo.styleSheet()[:60] if rules_combo else "(콤보 없음)")
    # ★도크 제목줄의 X·분리 아이콘은 스타일이 주는 어두운 비트맵이라 QSS 로 색을
    #   못 바꾼다 — 다크에서 묻혀 안 보였다 (실사용 신고). 팔레트 색으로 직접 그린다
    icon = theme_mod.dock_button_icon("close", "#FF3B30")
    icon_image = icon.pixmap(14, 14).toImage()
    check("도크 버튼 아이콘을 지정한 색으로 그린다",
          not icon.isNull() and any(
              icon_image.pixelColor(x, y).alpha() > 200
              and icon_image.pixelColor(x, y).red() > 200
              and icon_image.pixelColor(x, y).green() < 90
              for x in range(icon_image.width()) for y in range(icon_image.height())))
    check("분리 버튼 아이콘도 그린다",
          not theme_mod.dock_button_icon("float", "#FF3B30").isNull())
    window.open_filter_view(FR(pattern="line 12", ports=["MLOG"]))
    pump(app)
    dock_close = theme_mod.dock_button(window.filter_views[-1], "close")
    dock_image = (dock_close.icon().pixmap(14, 14).toImage()
                  if dock_close is not None else None)
    dark_text = QColor(theme_mod.TEXT)
    check("도크 X 버튼이 다크 글자색으로 다시 칠해진다 (하단 도킹 시 안 보이던 문제)",
          dock_image is not None and any(
              dock_image.pixelColor(x, y).alpha() > 200
              and abs(dock_image.pixelColor(x, y).red() - dark_text.red()) < 40
              and abs(dock_image.pixelColor(x, y).blue() - dark_text.blue()) < 40
              for x in range(dock_image.width()) for y in range(dock_image.height())),
          "(버튼 없음)" if dock_close is None else "아이콘 색 불일치")
    window.filter_views[-1].close()      # 뒤 테스트가 도크 잔여를 검사한다
    pump(app)

    # ★50ms 캐시(값이 같으면 setStyleSheet 생략) 때문에 옛 테마 색이 굳는 자리들
    store.set_paused(True)
    window.tick()
    window.apply_theme_change("light")
    window.apply_theme_change("dark")
    window.tick()
    check("기록 멈춤 버튼 색도 테마를 따라온다",
          theme_mod.WARNING in window.rec_button.styleSheet(),
          window.rec_button.styleSheet()[:70])
    store.set_paused(False)
    # 실제 트리거가 잡힌 상태를 만든다 (칩이 경고색으로 칠해지는 조건)
    window.trigger_watcher.set_rules([TriggerRule(pattern="CASE")])
    store.append("MLOG", "[ZCL] CASE session established")
    window.tick()
    window.apply_theme_change("light")
    window.apply_theme_change("dark")
    window.tick()
    window._rec_shown = ("굳은 값", "paused")
    window._trigger_shown = 999
    window.apply_theme_change("light")
    window.apply_theme_change("dark")
    check("테마 전환이 tick 캐시를 비운다 (안 비우면 옛 색이 굳는다)",
          window._rec_shown != ("굳은 값", "paused") and window._trigger_shown != 999,
          f"{window._rec_shown} / {window._trigger_shown}")
    check("트리거 칩 색도 테마를 따라온다",
          theme_mod.WARNING in window.trigger_chip.styleSheet(),
          window.trigger_chip.styleSheet()[:70])
    window.trigger_watcher.set_rules([])
    window.trigger_watcher.reset()
    card = window.settings().connection_page.cards["MLOG"]
    card.set_status("연결 실패", theme_mod.DANGER)
    light_danger = theme_mod.PALETTES["light"]["DANGER"]
    window.apply_theme_change("light")
    card.set_status("연결 실패", light_danger)
    window.apply_theme_change("dark")
    check("연결 카드의 상태 문구 색도 테마를 따라온다",
          theme_mod.DANGER in card.status.styleSheet(),
          card.status.styleSheet()[:70])

    pill = window.pills["MLOG"]
    check("테마를 바꾸면 상태 필도 새 팔레트로 다시 칠해진다 (라이트에서 어두운 필이 남던 문제)",
          theme_mod.pill_tint(theme_mod.state_color(pill.state())) in pill.styleSheet(),
          pill.styleSheet()[:80])
    check("설정에 저장된다 (종료 후 다시 켜도 다크)", config_mod.theme() == "dark",
          config_mod.theme())
    check("전환 후에도 tick 이 예외 없이 돈다", window.tick() is None)

    window.apply_theme_change("light")
    pump(app)
    check("되돌리면 원래 색", theme_mod.CONSOLE_BG == light_console_bg)
    check("되돌려도 글자 크기는 그대로", mlog_pane.font_size() == zoomed)
    window.change_font(0)

    # 설정 > 일반의 테마 콤보 — 고르면 즉시 적용된다
    general = window.settings().general_page
    check("일반 페이지에 테마 콤보가 있다", hasattr(general, "theme_combo"))
    check("테마 콤보는 라이트·다크 2개", general.theme_combo.count() == 2,
          str(general.theme_combo.count()))
    check("콤보의 itemData 는 저장 키다 (표시명이 아니라)",
          [general.theme_combo.itemData(i) for i in range(2)] == ["light", "dark"],
          str([general.theme_combo.itemData(i) for i in range(2)]))
    # 앞선 검사에서 테마가 어느 쪽이든 상관없게 — 콤보는 현재 설정으로 만들어진다
    general.theme_combo.setCurrentIndex(general.theme_combo.findData("light"))
    pump(app)
    general.theme_combo.setCurrentIndex(general.theme_combo.findData("dark"))
    pump(app)
    check("콤보를 바꾸면 즉시 적용된다 (언어와 달리 재시작 불필요)",
          theme_mod.CURRENT == "dark", theme_mod.CURRENT)
    general.theme_combo.setCurrentIndex(general.theme_combo.findData("light"))
    pump(app)
    check("되돌리면 라이트", theme_mod.CURRENT == "light")

    # 상태 필 옆 연결 토글 버튼 — 필 본체 클릭은 포커스 이동 그대로
    check("포트마다 연결 토글 버튼이 있다",
          set(window.port_toggles) == set(profile.roles()),
          str(list(window.port_toggles)))
    window.port_toggles['MLOG'].click()
    pump(app)
    check("COM 미지정이면 연결하지 않고 안내한다",
          not window.session.is_connected('MLOG') and bool(window.status_left.text()),
          window.status_left.text())

    # Ctrl+휠 폰트 확대/축소 — 전 콘솔 공통 (Ctrl+/- 와 같은 경로)
    from PySide6.QtCore import QPoint as _QPoint, QPointF as _QPointF
    from PySide6.QtGui import QWheelEvent as _QWheelEvent

    def _wheel_on(widget, delta: int, mods):
        app.sendEvent(widget, _QWheelEvent(
            _QPointF(10, 10), _QPointF(10, 10), _QPoint(0, 0), _QPoint(0, delta),
            Qt.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False))
        pump(app)

    before = profile.console_font_size
    _wheel_on(mlog_pane.view, 120, Qt.KeyboardModifier.ControlModifier)
    check("Ctrl+휠 위로 = 글자 커진다",
          profile.console_font_size == before + 1,
          f"{before} -> {profile.console_font_size}")
    check("콘솔에 실제로 반영된다",
          mlog_pane.font_size() == profile.console_font_size,
          f"{mlog_pane.font_size()} vs {profile.console_font_size}")
    check("다른 콘솔도 같이 바뀐다 (전체 공통)",
          window.panes['SHELL'].font_size() == profile.console_font_size)
    _wheel_on(mlog_pane.view, -120, Qt.KeyboardModifier.ControlModifier)
    check("Ctrl+휠 아래로 = 글자 작아진다", profile.console_font_size == before,
          str(profile.console_font_size))
    # ★실제 마우스는 본문(view)이 아니라 그 안의 viewport 에 닿는다. 거기서 우리 확대가
    #   안 걸리면 Qt 내장 확대가 그 콘솔 하나만 키운다 — "휠이 메인만 동작" 신고의 정체
    before_vp = profile.console_font_size
    _wheel_on(mlog_pane.view.viewport(), 120, Qt.KeyboardModifier.ControlModifier)
    check("viewport 에서도 Ctrl+휠이 전 콘솔 공통으로 먹는다",
          profile.console_font_size == before_vp + 1,
          f"{before_vp} -> {profile.console_font_size}")
    check("다른 콘솔도 같이 커진다 (Qt 내장 확대가 아니라 우리 경로)",
          window.panes["SHELL"].font_size() == profile.console_font_size)
    _wheel_on(mlog_pane.view.viewport(), -120, Qt.KeyboardModifier.ControlModifier)

    before_bar = profile.console_font_size
    _wheel_on(mlog_pane.view.verticalScrollBar(), 120, Qt.KeyboardModifier.ControlModifier)
    check("스크롤바 위에서도 Ctrl+휠이 먹는다 (실사용 신고 — 안 먹던 자리)",
          profile.console_font_size == before_bar + 1,
          f"{before_bar} -> {profile.console_font_size}")
    _wheel_on(mlog_pane.view.verticalScrollBar(), -120, Qt.KeyboardModifier.ControlModifier)

    # ★"창이 생기고 처음 휠이 안 된다" (실사용 신고) — 갓 만든 창에서 커서가
    #   본문 위에 있으리라는 보장이 없다. 콘솔 창 안이면 **어디에 떨어져도** 먹어야 한다
    window.open_filter_view(FR(pattern="line 12", ports=["MLOG"]))
    pump(app)
    fresh = window.filter_views[-1]
    # ★창을 붙이고 보이는 순간 QSS polish 가 폰트를 덮는다 — 새 창만 딴 크기로 뜬다
    check("갓 만든 창의 글자 크기가 나머지와 같다",
          fresh.pane.font_size() == profile.console_font_size,
          f"{fresh.pane.font_size()} vs {profile.console_font_size}")
    before_new = profile.console_font_size
    _wheel_on(fresh.edit, 120, Qt.KeyboardModifier.ControlModifier)
    check("갓 만든 필터드뷰는 입력칸 위에서도 Ctrl+휠이 먹는다",
          profile.console_font_size == before_new + 1,
          f"{before_new} -> {profile.console_font_size}")
    check("그 새 창의 콘솔에도 반영된다",
          fresh.pane.font_size() == profile.console_font_size,
          f"{fresh.pane.font_size()} vs {profile.console_font_size}")
    _wheel_on(fresh.pane.title_label, -120, Qt.KeyboardModifier.ControlModifier)
    check("제목줄 쪽에서도 먹는다", profile.console_font_size == before_new,
          str(profile.console_font_size))
    fresh.close()
    pump(app)

    _wheel_on(mlog_pane.view, 120, Qt.KeyboardModifier.NoModifier)
    check("Ctrl 없이는 폰트가 안 바뀐다 (평소 스크롤)",
          profile.console_font_size == before, str(profile.console_font_size))

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
    viewer._refresh_timer.stop()
    viewer._refresh_pane()
    pump(app)
    text = viewer.pane.view.toPlainText()
    check("필터가 매치만 남긴다", "beta line" in text and "alpha line" not in text, text[:200])
    viewer.edit.setText("")
    viewer.source_boxes["SHELL"].setChecked(False)
    viewer._refresh_timer.stop()
    viewer._refresh_pane()
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

    # 내장 터미널 — 스텁 세션(에코 루프백)으로 렌더·키 경로 검증 (실제 pty 불필요 = CI 안전)
    from .core.terminal import BUFFER_AVAILABLE
    if not BUFFER_AVAILABLE:
        print("  [SKIP] pyte 미설치 — 터미널 GUI 검사 생략")
    else:
        from PySide6.QtCore import QEvent as _QEvent
        from PySide6.QtGui import QKeyEvent as _QKeyEvent

        from .core.terminal import TerminalBuffer
        from .ui import terminal_pane as term_mod

        class _EchoSession:
            def __init__(self):
                self.buffer = TerminalBuffer(40, 10, history=200)
                self.written: list[str] = []
                self.alive = True
                self.exit_status = None

            def write(self, text: str) -> None:
                self.written.append(text)
                self.buffer.feed(text)

            def resize(self, cols: int, rows: int) -> None:
                self.buffer.resize(cols, rows)

            def close(self) -> None:
                self.alive = False

            def restart(self) -> None:
                self.alive = True

        stub = _EchoSession()
        term = term_mod.TerminalPane(stub)
        term.show()          # 숨긴 위젯은 resizeEvent 가 show 때까지 유예된다
        term.resize(640, 320)
        pump(app)
        stub.buffer.feed("PS C:\\bench> hello-term")
        gen_before = term._generation
        term.pump()
        pump(app)
        check("pump 가 새 generation 을 반영한다", term._generation != gen_before)
        check("화면 텍스트가 버퍼에 있다", "hello-term" in stub.buffer.text())

        def _press(key, text="", mods=Qt.KeyboardModifier.NoModifier):
            app.sendEvent(term, _QKeyEvent(_QEvent.Type.KeyPress, key, mods, text))

        _press(Qt.Key_A, "a")
        check("일반 문자가 세션으로 간다", stub.written[-1] == "a", str(stub.written[-3:]))
        _press(Qt.Key_Return, "\r")
        check("Enter 는 CR 로 간다", stub.written[-1] == "\r", repr(stub.written[-1]))
        _press(Qt.Key_Up)
        check("화살표는 VT 시퀀스로 간다", stub.written[-1] == "\x1b[A", repr(stub.written[-1]))
        _press(Qt.Key_C, "\x03", Qt.KeyboardModifier.ControlModifier)
        check("Ctrl+C 는 제어 바이트로 간다", stub.written[-1] == "\x03", repr(stub.written[-1]))
        # ★Tab 은 Qt 가 keyPressEvent 앞에서 포커스 이동으로 가로챈다 — 셸 자동완성이
        #   안 먹던 실기 문제. **형제 위젯이 포커스를 받을 수 있을 때만** 재현되므로
        #   실제 도크와 같은 구성(버튼 + 터미널)에서 확인한다.
        from PySide6.QtWidgets import QPushButton as _QPushButton
        from PySide6.QtWidgets import QVBoxLayout as _QVBoxLayout
        from PySide6.QtWidgets import QWidget as _QWidget
        holder = _QWidget()
        holder_layout = _QVBoxLayout(holder)
        holder_layout.addWidget(_QPushButton("Restart"))
        tab_stub = _EchoSession()
        tab_pane = term_mod.TerminalPane(tab_stub, holder)
        holder_layout.addWidget(tab_pane)
        holder.show()
        tab_pane.setFocus()
        pump(app)
        app.sendEvent(tab_pane, _QKeyEvent(_QEvent.Type.KeyPress, Qt.Key_Tab,
                                           Qt.KeyboardModifier.NoModifier, "\t"))
        pump(app)
        check("Tab 이 포커스 이동에 먹히지 않고 셸로 간다 (자동완성)",
              tab_stub.written == ["\t"], str(tab_stub.written))
        app.sendEvent(tab_pane, _QKeyEvent(_QEvent.Type.KeyPress, Qt.Key_Backtab,
                                           Qt.KeyboardModifier.ShiftModifier, ""))
        pump(app)
        check("Shift+Tab 은 역방향 완성 시퀀스로 간다",
              tab_stub.written[-1] == "\x1b[Z", repr(tab_stub.written[-1]))
        holder.close()
        holder.deleteLater()
        pump(app)
        check("리사이즈가 세션 크기를 바꾼다", stub.buffer.cols > 40, str(stub.buffer.cols))
        frame = stub.buffer.snapshot()
        check("스냅샷 커서가 프레임에 있다", len(frame.cursor) == 3)

        # 휠 스크롤 — 위로 굴리면 스크롤백, 타이핑(에코 유입)하면 최신으로 복귀
        from PySide6.QtCore import QPoint, QPointF as _QPointF
        from PySide6.QtGui import QWheelEvent as _QWheelEvent

        stub.buffer.resize(40, 5)
        for i in range(30):
            stub.buffer.feed(f"scrollline{i}\r\n")
        term.pump()
        pump(app)

        def _wheel(delta_y: int) -> None:
            app.sendEvent(term, _QWheelEvent(
                _QPointF(10, 10), _QPointF(10, 10), QPoint(0, 0), QPoint(0, delta_y),
                Qt.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False))

        for _ in range(6):
            _wheel(120)
        check("휠 위로 = 스크롤백 (최신 줄이 화면에서 사라진다)",
              "scrollline29" not in stub.buffer.text(), stub.buffer.text())
        _press(Qt.Key_A, "a")
        check("타이핑하면 최신 화면으로 복귀한다",
              "scrollline29" in stub.buffer.text(), stub.buffer.text())
        for _ in range(4):
            _wheel(120)
        for _ in range(8):
            _wheel(-120)
        check("휠 아래로 = 최신 방향 복귀", "scrollline29" in stub.buffer.text(),
              stub.buffer.text())

        # 오른쪽 세로 스크롤바 — 위치 표시 + 드래그로 이동
        bar = term.scrollbar
        check("터미널에 세로 스크롤바가 있다", bar is not None and bar.isVisible())
        check("맨 아래에서는 스크롤바가 끝에 있다", bar.value() == bar.maximum(),
              f"{bar.value()}/{bar.maximum()}")
        for _ in range(5):
            _wheel(120)
        term.pump()
        pump(app)
        check("휠로 올리면 스크롤바 값도 따라 준다", bar.value() < bar.maximum(),
              f"{bar.value()}/{bar.maximum()}")
        bar.setValue(bar.maximum())
        pump(app)
        check("스크롤바를 끝으로 옮기면 최신 화면으로 간다",
              "scrollline29" in stub.buffer.text(), stub.buffer.text())
        bar.setValue(0)
        pump(app)
        check("스크롤바를 맨 위로 옮기면 과거가 보인다",
              "scrollline29" not in stub.buffer.text(), stub.buffer.text())
        # 터미널은 격자 렌더러라 콘솔과 폰트 체계가 다르다 — 별도 공통값으로 확대
        term.show()
        # 스텁 pane 은 도크가 아니라 테스트가 만든 것이라 배선이 없다 — 슬롯을 직접
        # 잇고 동작을 본다. 실제 도크가 이 슬롯에 연결하는지는 uitest 가 검증한다.
        term.zoom_requested.connect(window.change_terminal_font)
        pump(app)
        term_before = profile.terminal_font_size
        app.sendEvent(term.screen, _QWheelEvent(
            _QPointF(10, 10), _QPointF(10, 10), _QPoint(0, 0), _QPoint(0, 120),
            Qt.NoButton, Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase, False))
        pump(app)
        check("터미널도 Ctrl+휠로 커진다",
              profile.terminal_font_size == term_before + 1,
              f"{term_before} -> {profile.terminal_font_size}")
        # 도크에 붙은 pane 이 아니라 스텁이라 슬롯이 닿지 않는다 — 적용 함수는 직접 본다
        term.set_font_size(profile.terminal_font_size)
        check("터미널 폰트 적용 함수가 실제로 반영한다",
              term.font_size() == profile.terminal_font_size,
              f"{term.font_size()} vs {profile.terminal_font_size}")
        check("콘솔 폰트는 터미널 확대에 영향받지 않는다",
              profile.console_font_size == before, str(profile.console_font_size))

        term.deleteLater()
        pump(app)

        # 액션 바 터미널 버튼 — 메뉴를 뒤지지 않고 바로 연다 (아이콘은 언어 무관)
        check("액션 바에 터미널 버튼이 있다",
              hasattr(window, "terminal_button")
              and window.terminal_button.text().startswith("🖥"),
              getattr(getattr(window, "terminal_button", None), "text", lambda: "없음")())
        window.terminal_button.click()
        pump(app)
        check("터미널 버튼이 도크를 연다", len(window.terminal_docks) == 1,
              str(len(window.terminal_docks)))
        first_dock = window.terminal_docks[0]
        check("도크는 떠 있지 않고 하단에 도킹된다",
              not first_dock.isFloating()
              and window.dockWidgetArea(first_dock) == Qt.BottomDockWidgetArea,
              f"floating={first_dock.isFloating()} area={window.dockWidgetArea(first_dock)}")

        # 두 번째부터는 옆으로 늘어놓지 않고 탭으로 묶는다 (실기 보고: 옆에 나란히 생김)
        window.terminal_button.click()
        pump(app)
        second_dock = window.terminal_docks[1]
        check("두 번째 도크는 첫 도크와 탭으로 묶인다",
              second_dock in window.tabifiedDockWidgets(first_dock),
              str(window.tabifiedDockWidgets(first_dock)))
        check("두 번째 도크도 떠 있지 않다", not second_dock.isFloating())
        check("도크 이름이 서로 다르다 (배치 기억이 꼬이지 않게)",
              first_dock.objectName() != second_dock.objectName(),
              f"{first_dock.objectName()} vs {second_dock.objectName()}")

        # 새 창의 글자 크기 — 붙여서 보인 뒤에 걸어야 QSS polish 에 안 덮인다
        check("갓 만든 터미널 글자 크기가 설정값과 같다",
              second_dock.pane.font_size() == profile.terminal_font_size,
              f"{second_dock.pane.font_size()} vs {profile.terminal_font_size}")
        term_before = profile.terminal_font_size
        _wheel_on(second_dock, 120, Qt.KeyboardModifier.ControlModifier)
        check("터미널 도크는 본문 밖에서도 Ctrl+휠이 먹는다",
              profile.terminal_font_size == term_before + 1,
              f"{term_before} -> {profile.terminal_font_size}")
        _wheel_on(second_dock, -120, Qt.KeyboardModifier.ControlModifier)

        # 창을 키우는 길 — ★네이티브 프레임에 최대화 버튼을 붙이면(창 플래그 교체)
        # 실제 버튼 클릭 때 Qt 가 도크를 파괴한다 (실기 재현). 우리 버튼으로 처리한다.
        check("도크 툴바에 최대화 버튼이 있다", hasattr(second_dock, "maximize_button"))
        second_dock.maximize_button.click()
        pump(app)
        check("최대화 버튼이 떼어내서 최대화한다",
              second_dock.isFloating()
              and bool(second_dock.windowState() & Qt.WindowMaximized),
              f"float={second_dock.isFloating()} state={second_dock.windowState()}")
        check("최대화해도 도크가 살아 있다 (파괴되지 않는다)",
              second_dock in window.terminal_docks and second_dock.isVisible())
        second_dock.maximize_button.click()
        pump(app)
        check("다시 누르면 원래 크기로 돌아온다",
              not (second_dock.windowState() & Qt.WindowMaximized))
        check("창 플래그를 교체하지 않는다 (도크 파괴 원인)",
              not (second_dock.windowFlags() & Qt.WindowMaximizeButtonHint),
              str(second_dock.windowFlags()))
        second_dock.setFloating(False)
        pump(app)

        from PySide6.QtWidgets import QDockWidget as _QDockWidget
        for dock in list(window.terminal_docks):
            dock.close()
        pump(app)

        # 창이 최소화됐거나 아직 안 보이는 상태여도 탭 묶기는 같아야 한다
        # (isVisible 로 기존 도크를 세면 이 경우 조용히 옆으로 붙는다)
        window.hide()
        pump(app)
        hidden_first = window.open_terminal()
        hidden_second = window.open_terminal()
        pump(app)
        check("창이 안 보이는 상태에서도 두 번째 도크가 탭으로 묶인다",
              hidden_second in window.tabifiedDockWidgets(hidden_first),
              str(window.tabifiedDockWidgets(hidden_first)))
        for dock in list(window.terminal_docks):
            dock.close()
        pump(app)
        check("터미널 도크 닫으면 목록에서 빠진다", not window.terminal_docks)
        check("닫은 도크는 창에서 완전히 제거된다 (빈 영역이 남지 않게)",
              not [d for d in window.findChildren(_QDockWidget)],
              str([d.objectName() for d in window.findChildren(_QDockWidget)]))

    for mode in ("columns", "tabs", "merged", "split"):
        window._apply_layout(mode)
        pump(app)
        stray = [name for name, pane in list(window.panes.items()) + [("merged", window.merged_pane)]
                 if pane.parent() is None and pane.isVisible()]
        check(f"레이아웃 {mode}: 부모 없는 pane 이 창으로 뜨지 않는다", not stray, str(stray))
    check("레이아웃 4종 전환", window.layout_mode == "split")

    window._apply_layout("merged")
    window.tick()
    pump(app)
    check("병합 뷰는 3포트를 한 화면에",
          all(f"[{role}]" in window.merged_pane.view.toPlainText()
              for role in ("MLOG", "SHELL")),
          window.merged_pane.view.toPlainText()[:200])

    # 병합 모드에서는 컨테이너가 merged_pane 자체다 — 전환하며 지우면 pane 이 파괴된다
    window._apply_layout("columns")
    pump(app)
    window._apply_layout("merged")
    pump(app)
    window._apply_layout("split")
    pump(app)
    try:
        window.merged_pane.view.blockCount()
        window.tick()
        pump(app)
        merged_alive = True
    except RuntimeError as exc:
        merged_alive = False
        print("      ", exc)
    check("병합↔분할 왕복 후에도 pane 이 살아 있다 (deleteLater 오폭 방지)", merged_alive)

    # 부하: 20k 라인을 pump 하며 UI 시간 측정
    start = time.monotonic()
    for i in range(20_000):
        store.append("MLOG", f"[DIS] mDNS burst {i}")
    window.tick()
    pump(app)
    elapsed = time.monotonic() - start
    check(f"20k 라인 적재+렌더 {elapsed:.2f}s", elapsed < 12.0, f"{elapsed:.2f}s")
    check("블록 상한이 메모리를 묶는다",
          mlog_pane.view.blockCount() <= mlog_pane.view.maximumBlockCount() + 1,
          str(mlog_pane.view.blockCount()))

    # 같은 키가 창 컨텍스트에 두 번 걸리면 Qt 가 ambiguous 로 판단해 양쪽 다 발화하지 않는다.
    # 패널마다 있는 Ctrl+F / F3 / Esc 는 WidgetWithChildrenShortcut 이라 중복이 아니다.
    from PySide6.QtGui import QAction, QShortcut
    window_contexts = (Qt.WindowShortcut, Qt.ApplicationShortcut)
    registered: list[str] = []
    for action in window.findChildren(QAction):
        if action.shortcutContext() in window_contexts:
            registered += [seq.toString() for seq in action.shortcuts() if not seq.isEmpty()]
    for shortcut in window.findChildren(QShortcut):
        if shortcut.context() in window_contexts and not shortcut.key().isEmpty():
            registered.append(shortcut.key().toString())
    duplicates = sorted({key for key in registered if registered.count(key) > 1})
    check("창 컨텍스트 단축키 중복 등록 없음 (ambiguous 방지)", not duplicates, str(duplicates))
    pane_scoped = [s for s in mlog_pane.findChildren(QShortcut)
                   if s.context() == Qt.WidgetWithChildrenShortcut]
    check("패널 단축키는 위젯 컨텍스트로 격리돼 있다", len(pane_scoped) >= 3, str(len(pane_scoped)))

    before_views = len(window.filter_views)
    for action in window.filter_menu.actions():
        if action.shortcut().toString() == "Ctrl+K":
            action.trigger()
    check("Ctrl+K 액션이 필터드뷰를 연다", len(window.filter_views) == before_views + 1)
    window.filter_views[-1].close()

    window._rebuild_filter_menu()
    window._rebuild_filter_menu()
    ctrl_k_actions = [a for a in window.findChildren(QAction) if a.shortcut().toString() == "Ctrl+K"]
    check("메뉴 재구성이 Ctrl+K 액션을 누적시키지 않는다", len(ctrl_k_actions) == 1,
          f"{len(ctrl_k_actions)}개 남음")

    # 분할 비율·창 지오메트리는 프로파일에 남아야 한다 (UI 문서 §1 약속)
    from .ui.main_window import usable_sizes
    window._apply_layout("split")
    pump(app)
    window._capture_layout()
    stored = window.profile.layout.get("splitters", {})
    check("분할 비율이 프로파일에 담긴다",
          isinstance(stored.get("split_main"), list) and len(stored["split_main"]) == 2
          and all(isinstance(v, int) for v in stored["split_main"]), str(stored))
    check("창 지오메트리가 프로파일에 담긴다", bool(window.profile.layout.get("geometry")))
    check("복원 검증: 정상 값은 그대로 쓴다", usable_sizes([800, 400], 2) == [800, 400])
    check("복원 검증: 칸 수가 다르면 버린다", usable_sizes([800, 400, 200], 2) is None)
    check("복원 검증: 합이 0이면 버린다 (패널이 폭 0 으로 사라짐)", usable_sizes([0, 0], 2) is None)
    check("복원 검증: 손상된 값은 버린다", usable_sizes(["a", 1], 2) is None)

    # 실제 pane 은 최소폭이 커서 offscreen 좁은 창에서는 비율이 안 보인다 —
    # 저장값을 splitter 에 적용하는 경로 자체를 직접 검증한다
    from PySide6.QtWidgets import QLabel, QSplitter
    probe_splitter = QSplitter(Qt.Horizontal)
    probe_splitter.addWidget(QLabel("a"))
    probe_splitter.addWidget(QLabel("b"))
    window.profile.layout["splitters"]["probe_key"] = [1000, 500]
    window._restore_sizes(probe_splitter, "probe_key", [1, 1])
    left, right = probe_splitter.sizes()
    check("저장된 분할 비율이 splitter 에 적용된다 (좌 > 우)", left > right, f"{left}:{right}")
    window.profile.layout["splitters"]["probe_key"] = [0, 0]
    window._restore_sizes(probe_splitter, "probe_key", [700, 300])
    left, right = probe_splitter.sizes()
    check("손상된 저장값이면 기본 비율로 떨어진다", left > right, f"{left}:{right}")

    # probe 결과가 현재 매핑과 다르면 매핑을 제안한다 (자동 적용은 하지 않는다)
    page = window.connection_page
    coms = {"MLOG": "COM4", "SHELL": "COM5", "UCLI": "COM8"}
    for role, verdict in (("MLOG", "SHELL"), ("SHELL", "MLOG"), ("UCLI", "UCLI")):
        page.cards[role].last_verdict = verdict
        page.cards[role].last_probed_com = coms[role]  # 판정과 probe 한 COM 은 짝이어야 한다
        page.profile.port(role).com = coms[role]
    page._suggested = {}
    page._update_suggestion()
    check("역할이 뒤바뀐 probe 결과에 매핑 제안을 띄운다",
          page._suggested.get("SHELL") == "COM4" and page._suggested.get("MLOG") == "COM5",
          str(page._suggested))
    page._apply_suggestion()
    check("제안 적용이 프로파일 COM 을 바꾼다",
          page.profile.port("SHELL").com == "COM4", str(page.profile.port("SHELL").com))

    # probe 하지 않은 COM 은 제안에 섞이면 안 된다 (probe 중 콤보를 바꾼 상황)
    page._suggested = {}
    page.cards["MLOG"].last_probed_com = ""   # 콤보 변경으로 무효화된 상태
    page._update_suggestion()
    check("probe 한 적 없는 COM 은 제안하지 않는다", not page._suggested, str(page._suggested))

    # 규칙 페이지를 한 번 건드렸다고 다른 룰 속성이 조용히 초기화되면 안 된다
    window.profile.highlight_rules = [HighlightRule("CASE", "빨강", is_regex=False,
                                                    case_sensitive=True)]
    window.profile.saved_filters = [FR(pattern="Err", case_sensitive=True, name="f1")]
    window.rules_page.reload(window.profile)
    window.rules_page._collect()
    check("규칙 페이지 편집이 하이라이트 대소문자 설정을 지우지 않는다",
          window.profile.highlight_rules[0].case_sensitive)
    check("규칙 페이지 편집이 저장된 필터의 대소문자 설정을 지우지 않는다",
          window.profile.saved_filters[0].case_sensitive)
    window.profile.redact_rules = [RedactRule("lit+eral", "<x>", is_regex=False)]
    window.rules_page.reload(window.profile)
    window.rules_page._collect()
    check("규칙 페이지 편집이 redact 리터럴 모드를 지우지 않는다",
          window.profile.redact_rules[0].is_regex is False)

    # 연결 중 포트 콤보만 바꿔도 화면이 "새 COM 을 Connected" 라고 거짓말하면 안 된다
    window.profile.port("MLOG").com = "COM999"
    window.tick()
    pump(app)
    check("미연결 상태에서는 프로파일 COM 을 그대로 보여준다",
          "COM999" in window.pills["MLOG"].text(), window.pills["MLOG"].text())

    # 프로파일 저장 → 전환: 옛 store 를 붙들고 있는 위젯이 남으면 안 된다
    window.save_profile_as("__selftest_b__")
    check("프로파일 저장 후 목록에 뜬다",
          any("__selftest_b__" in window.profile_page.list.item(i).text()
              for i in range(window.profile_page.list.count())))
    old_store = window.session.store
    window.open_filter_view(FR(pattern="line", ports=["MLOG"]))
    window.load_profile("__selftest__")
    pump(app)
    check("프로파일 전환 시 옛 store 를 쓰는 필터드뷰가 안 남는다", not window.filter_views)
    check("전환 후 pane 이 새 store 를 본다",
          all(pane.store is window.session.store for pane in window.panes.values()),
          "pane.store 갱신 누락")
    check("전환 후 명령 패널도 새 store/session",
          window.command_panel.store is window.session.store and old_store is not window.session.store)
    tick_error = ""
    try:
        window.tick()
        pump(app)
    except Exception as exc:  # noqa: BLE001 - 예외를 FAIL 로 만들어야 의미가 있다
        tick_error = f"{type(exc).__name__}: {exc}"
    check("전환 후에도 tick 이 예외 없이 돈다", not tick_error, tick_error)

    window.close()
    pump(app)
    sys.excepthook = original_hook
    config_mod.PROFILE_DIR = original_profile_dir
    config_mod.SETTINGS_PATH = original_settings
    check("Qt 슬롯에서 삼켜진 예외 없음", not slot_errors, "; ".join(slot_errors[:3]))


def test_theme() -> None:
    print("\n== 테마 팔레트 (라이트/다크) ==")
    from .ui import theme as theme_mod

    original = theme_mod.CURRENT
    try:
        check("테마는 라이트/다크 2택", theme_mod.theme_names() == ["light", "dark"],
              str(theme_mod.theme_names()))
        theme_mod.set_theme("light")
        light_bg, light_text = theme_mod.BG, theme_mod.CONSOLE_TEXT
        theme_mod.set_theme("dark")
        check("다크로 바꾸면 배경 토큰이 바뀐다",
              theme_mod.BG != light_bg and theme_mod.CURRENT == "dark",
              f"{light_bg} -> {theme_mod.BG}")
        check("콘솔 본문 색도 함께 바뀐다", theme_mod.CONSOLE_TEXT != light_text)
        check("QSS 가 새 토큰으로 다시 만들어진다", theme_mod.BG in theme_mod.build_qss(),
              theme_mod.build_qss()[:80])
        check("두 팔레트의 토큰 이름이 같다",
              set(theme_mod.PALETTES["light"]) == set(theme_mod.PALETTES["dark"]),
              str(set(theme_mod.PALETTES["light"]) ^ set(theme_mod.PALETTES["dark"])))
        check("배너 색도 토큰으로 있다 (콘솔이 하드코딩하던 것)",
              "BANNER_BG" in theme_mod.PALETTES["light"])
        # ★QSS 에 밝은 색을 박아두면 다크에서 글씨가 안 보인다 (실사용 신고)
        theme_mod.set_theme("dark")
        dark_qss = theme_mod.build_qss()
        # ★색 하나만 박혀 있어도 다크에서 흰 덩어리가 된다 (메뉴 hover 실사용 신고).
        #   목록을 늘려가며 잡지 말고 "다크 QSS 의 모든 색은 다크 팔레트 값" 으로 잠근다.
        allowed = set(theme_mod.PALETTES["dark"].values()) | {"#FFFFFF"}
        leftovers = sorted({c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}", dark_qss)}
                           - {c.upper() for c in allowed})
        check("다크 QSS 의 색이 전부 다크 팔레트 값이다", not leftovers, str(leftovers))
        check("선택 색이 테마를 따른다",
              theme_mod.PALETTES["light"]["SELECTION_BG"]
              != theme_mod.PALETTES["dark"]["SELECTION_BG"])
        check("버튼 포커스 테두리 규칙이 있다 (포커스가 가면 안 보이던 문제)",
              "QPushButton:focus" in dark_qss)
        # ★상태 필 글씨가 배경 틴트에 묻혀 안 읽혔다 (실사용 신고 — 라이트·다크 둘 다).
        #   눈대중 대신 WCAG 대비비로 잠근다.
        for name in ("light", "dark"):
            theme_mod.set_theme(name)
            for state in ("connected", "reconnecting", "disconnected"):
                ratio = theme_mod.contrast_ratio(theme_mod.pill_text(state),
                                                 theme_mod.pill_tint(theme_mod.state_color(state)))
                check(f"{name} 상태 필 글씨 대비가 4.5 이상 ({state})", ratio >= 4.5, f"{ratio:.2f}")
            tip = theme_mod.contrast_ratio(theme_mod.TOOLTIP_TEXT, theme_mod.TOOLTIP_BG)
            check(f"{name} 툴팁 대비가 4.5 이상", tip >= 4.5, f"{tip:.2f}")
        theme_mod.set_theme("dark")
        # 인라인으로 발라 둔 옛 팔레트 색을 지금 테마의 같은 자리 색으로 옮긴다
        check("retone 이 라이트 색을 다크 같은 자리로 옮긴다",
              theme_mod.retone(theme_mod.PALETTES["light"]["WARNING"])
              == theme_mod.PALETTES["dark"]["WARNING"])
        check("팔레트에 없는 색은 그대로 둔다", theme_mod.retone("#123456") == "#123456")

        # 안 쓰는 포트 카드도 팔레트를 따라야 한다 — 다크에서 흰 카드가 떴다
        from .ui import connection_page as conn_mod
        check("비활성 카드 색이 하드코딩이 아니다",
              "#F7F8FA" not in io.open(conn_mod.__file__, encoding="utf-8").read())

        # ★기동 경로 회귀 가드 — app.py 는 theme.set_theme() 하나만 부른다.
        #   여기서 로그·하이라이트 팔레트가 같이 안 바뀌면 **다크로 켰을 때** 밝은
        #   하이라이트 위에 밝은 글자가 얹혀 글씨가 안 보인다 (실사용 신고)
        from .core import ansi as ansi_check
        from .core import filters as filters_check
        check("theme.set_theme 이 로그 색 팔레트까지 바꾼다",
              ansi_check.resolve("32") == ansi_check.PALETTES["dark"]["fg"][32],
              ansi_check.resolve("32"))
        check("theme.set_theme 이 하이라이트 팔레트까지 바꾼다",
              filters_check.highlight_hex("빨강")
              == filters_check.HIGHLIGHT_PALETTES["dark"]["빨강"],
              filters_check.highlight_hex("빨강"))
        theme_mod.set_theme("light")
        check("되돌릴 때도 세 팔레트가 함께 간다",
              ansi_check.resolve("32") == ansi_check.PALETTES["light"]["fg"][32]
              and filters_check.highlight_hex("빨강")
              == filters_check.HIGHLIGHT_PALETTES["light"]["빨강"])
        theme_mod.set_theme("dark")
        check("상태 필 배경도 테마를 따른다",
              theme_mod.pill_tint(theme_mod.SUCCESS)
              != theme_mod.PALETTES["light"]["TINT_SUCCESS"],
              theme_mod.pill_tint(theme_mod.SUCCESS))

        theme_mod.set_theme("없는테마")
        check("모르는 이름은 light 폴백",
              theme_mod.CURRENT == "light" and theme_mod.BG == light_bg)
    finally:
        theme_mod.set_theme(original)


def test_i18n() -> None:
    """번역 누락 검사 — 새 문구를 넣고 영어 표를 안 채우면 여기서 걸린다."""
    print("\n== i18n (한국어/영어) ==")
    import ast
    from .core import i18n
    root = os.path.dirname(os.path.abspath(__file__))
    keys = set()
    for folder in ("ui", "core", "."):
        base = os.path.join(root, folder)
        for name in os.listdir(base):
            if not name.endswith(".py"):
                continue
            try:
                tree = ast.parse(open(os.path.join(base, name), encoding="utf-8").read())
            except Exception:  # noqa: BLE001
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "tr" and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    keys.add(node.args[0].value)
    check("번역 대상 문구를 찾았다", len(keys) > 200, str(len(keys)))
    missing = i18n.missing_keys(keys)
    check("영어 번역 누락 없음", not missing, f"{len(missing)}개: " + "; ".join(missing[:3]))

    # 자리표시자({0}, {1:,})가 번역에서 사라지면 format() 이 터진다
    import re
    broken = []
    for key, value in i18n.EN.items():
        want = set(re.findall(r"\{(\d+)", key))
        got = set(re.findall(r"\{(\d+)", value))
        if want != got:
            broken.append(key[:40])
    check("번역문의 자리표시자가 원문과 같다", not broken, "; ".join(broken[:3]))

    # ★모듈 최상위 상수에서 tr() 를 부르면 임포트 시점 언어로 굳는다 (언어 설정이 그 뒤다)
    frozen = []
    for folder in ("ui", "core", "."):
        base = os.path.join(root, folder)
        for name in os.listdir(base):
            if not name.endswith(".py"):
                continue
            try:
                tree = ast.parse(open(os.path.join(base, name), encoding="utf-8").read())
            except Exception:  # noqa: BLE001
                continue
            for stmt in tree.body:
                if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    continue
                for node in ast.walk(stmt):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == "tr"):
                        frozen.append(f"{folder}/{name}")
                        break
    check("모듈 최상위 상수에 tr() 가 없다 (임포트 시점에 굳는다)", not frozen,
          "; ".join(sorted(set(frozen))))

    # 색 이름은 프로파일에 저장되는 식별자다 — 번역되면 저장한 색을 못 찾는다
    from .core.filters import DEFAULT_HIGHLIGHT_COLOR, highlight_names
    i18n.set_language("en")
    check("색 팔레트 키는 언어와 무관하게 고정",
          "노랑" in highlight_names() and DEFAULT_HIGHLIGHT_COLOR == "노랑",
          str(highlight_names()[:3]))

    check("영어로 바꾸면 영어가 나온다", i18n.tr("확인") == "OK", i18n.tr("확인"))
    check("표에 없는 문구는 원문 유지", i18n.tr("존재하지 않는 문구") == "존재하지 않는 문구")
    i18n.set_language("ko")
    check("한국어로 되돌리면 원문", i18n.tr("확인") == "확인")
    check("기본 언어는 영어다", i18n.DEFAULT_LANGUAGE == "en", i18n.DEFAULT_LANGUAGE)
    check("모르는 언어 코드는 기본값(en)", i18n.set_language("zz") == "en")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true", help="offscreen Qt 테스트 포함")
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="serialhub_selftest_")
    try:
        test_logstore(tmp)
        test_rollover(tmp)
        test_rotation_and_marker(tmp)
        test_review_regressions(tmp)
        test_log_features(tmp)
        test_log_dir_options(tmp)
        test_logfile_viewer(tmp)
        test_terminal_core()
        test_terminal_pty()
        test_selfcheck()
        test_release_tooling(tmp)
        test_concurrent_load(tmp)
        test_redact()
        test_filters()
        test_probe_classification()
        test_port_reader()
        test_port_reader_probe()
        test_profile(tmp)
        test_session(tmp)
        test_i18n()
        test_theme()
        if args.gui:
            test_gui(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== {len(PASSED)} passed, {len(FAILED)} failed ===")
    for failure in FAILED:
        print(f"  FAIL: {failure}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
