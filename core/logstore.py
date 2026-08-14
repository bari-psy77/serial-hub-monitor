"""LogStore — 전 포트 라인 보관(ring) + 무중단 파일 기록.

설계문서 §3.1 / §6 참조. Qt 를 모르는 순수 파이썬 계층이다.

파일 기록은 append() 를 호출한 reader 스레드에서 즉시 수행하고 flush 한다.
GUI 가 멈추거나 강제 종료돼도 로그는 남는다 (FR-7 의 본질).
"""

from __future__ import annotations

import heapq
import os
import re
import threading
import time
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass

from . import ansi
from .diag import diag
from .i18n import tr

# ESC 시퀀스(CSI/OSC/단독 Fe) + BEL. 펌웨어가 컬러 코드를 섞어 보내면 화면·파일·grep
# 전부에서 쓰레기가 되므로 저장 전에 벗긴다 (프로파일 strip_ansi 로 끌 수 있다).
def strip_ansi(text: str) -> str:
    """색 코드를 버리고 본문만 — 색을 살리려면 LogStore 가 ansi.parse 를 쓴다."""
    return ansi.strip(text)


# NUL 을 비롯한 C0 제어문자. 하나만 섞여도 편집기·뷰어가 파일 전체를 '바이너리' 로
# 판단해 열기를 거부한다 (실제로 겪은 문제) — 눈에 보이는 형태로 바꿔 텍스트를 지킨다.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_controls(text: str) -> str:
    """제어문자를 `<00>` 같은 표기로 바꾼다. 흔적은 남기되 파일은 텍스트로 유지한다."""
    if not _CONTROL_RE.search(text):
        return text
    return _CONTROL_RE.sub(lambda m: f"<{ord(m.group()):02X}>", text)

TS_ABSOLUTE = "absolute"
TS_RELATIVE = "relative"
TS_OFF = "off"
TS_MODES = (TS_ABSOLUTE, TS_RELATIVE, TS_OFF)

TX_MARK = ">>> "
MARKER_PORT = "MARK"  # 사용자/브리지가 주입하는 구분 마커 전용 가상 포트
MERGED_KEY = "_MERGED"  # 병합 파일의 이름 지정 키 (포트가 아니다)
DEFAULT_MAX_FILE_BYTES = 200 * 1024 * 1024  # firehose 밤샘 수집 시 단일 파일 폭주 방지
SYNC_INTERVAL_S = 2.0   # 이 주기로 디스크에 내려 다른 도구가 바로 읽을 수 있게 한다


def _safe_name(name: str) -> str:
    """파일명으로 쓸 수 있게 정리 — 사용자가 아무거나 넣어도 저장이 실패하면 안 된다."""
    cleaned = "".join(ch for ch in name.strip() if ch.isalnum() or ch in "-_. ").strip()
    return cleaned.replace(" ", "_")[:48]


@dataclass(frozen=True, slots=True)
class LogLine:
    """캡처 시각을 라인에 고정해 둔다 — 타임스탬프 표시 모드를 나중에 바꿔도 과거 라인의 시각이 정확하다."""

    seq: int
    t_wall: float
    t_mono: float
    port: str
    text: str
    is_tx: bool = False
    # 펌웨어가 넣은 색 구간 ((start, end, fg, bg, bold), ...) — text 기준 offset.
    # 파일·검색·필터는 text 만 보고, 콘솔만 이걸 입힌다 (core/ansi.py 참조)
    spans: tuple = ()


@dataclass(frozen=True, slots=True)
class PullResult:
    lines: list[LogLine]
    skipped: int = 0        # limit 으로 잘라낸 개수 (정확히 앎)
    evicted: bool = False   # ring 에서 이미 밀려난 구간이 있음 (개수는 알 수 없음)


def _seq_of(line: LogLine) -> int:
    return line.seq


def stamp_clock(t_wall: float) -> str:
    """`01:19:12.165` — 시:분:초.밀리초."""
    ms = int(t_wall * 1000) % 1000
    return f"{time.strftime('%H:%M:%S', time.localtime(t_wall))}.{ms:03d}"


def stamp_date_clock(t_wall: float) -> str:
    """`2026-08-02 01:19:12.165` — 기존 Tera Term / VS Code 저장 로그와 같은 형식."""
    ms = int(t_wall * 1000) % 1000
    return f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t_wall))}.{ms:03d}"


def render_prefix_len(line: LogLine, ts_mode: str = TS_ABSOLUTE,
                      show_prefix: bool = False) -> int:
    """render_line 이 본문 앞에 붙인 글자 수 — 색 구간 offset 보정에 쓴다."""
    length = 0
    if ts_mode == TS_ABSOLUTE:
        length += len(f"[{stamp_clock(line.t_wall)}]") + 1
    elif ts_mode == TS_RELATIVE:
        length += len(f"[+{line.t_mono:8.1f}s]") + 1
    if show_prefix:
        length += len(f"[{line.port}]") + 1
    if line.is_tx:
        length += len(TX_MARK)
    return length


def render_line(line: LogLine, ts_mode: str = TS_ABSOLUTE, show_prefix: bool = False) -> str:
    """화면 표시용 1줄. 병합 뷰 / 필터드뷰는 show_prefix=True 로 출처를 남긴다."""
    parts = []
    if ts_mode == TS_ABSOLUTE:
        parts.append(f"[{stamp_clock(line.t_wall)}]")
    elif ts_mode == TS_RELATIVE:
        parts.append(f"[+{line.t_mono:8.1f}s]")
    if show_prefix:
        parts.append(f"[{line.port}]")
    if line.is_tx:
        parts.append(TX_MARK + line.text)
    else:
        parts.append(line.text)
    return " ".join(parts)


def format_for_port_file(line: LogLine) -> str:
    """포트별 파일 — 기존 `log\\0801\\matter.log` 계열 형식."""
    body = (TX_MARK + line.text) if line.is_tx else line.text
    return f"[{stamp_date_clock(line.t_wall)}] {body}"


def format_for_merged_file(line: LogLine) -> str:
    """병합 파일 — 기존 run_*.py transcript 계열 형식 (분석 문서 grep 호환)."""
    body = (TX_MARK + line.text) if line.is_tx else line.text
    clock = time.strftime("%H:%M:%S", time.localtime(line.t_wall))
    return f"[{clock} +{line.t_mono:7.1f}s] [{line.port}] {body}"


class _Writer:
    """append-only 무버퍼 파일 핸들.

    ★파일은 **첫 줄이 올 때** 만든다. 미리 만들면 트래픽 없는 포트마다 0바이트 파일이
    남고, 설정을 건드릴 때마다 빈 파일이 쌓인다. 기록 실패는 예외를 삼키고 상태로만 남긴다.
    """

    def __init__(self, path: str):
        self.path = path
        self.error: str | None = None
        self.bytes_written = 0
        self._fh = None
        self._unsynced = 0

    @property
    def created(self) -> bool:
        return self._fh is not None

    def _open(self) -> bool:
        if self._fh is not None:
            return True
        if self.error:
            return False   # 한 번 실패한 경로를 매 줄 재시도하지 않는다
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._fh = open(self.path, "ab", buffering=0)
            return True
        except Exception as exc:  # noqa: BLE001 - 기록 실패로 수신을 멈추지 않는다
            self.error = str(exc)
            diag.error("logstore", f"파일 열기 실패 {self.path}: {exc}")
            return False

    def write(self, text: str) -> None:
        if not self._open():
            return
        try:
            payload = text.encode("utf-8", "replace") + b"\r\n"
            self._fh.write(payload)
            self.bytes_written += len(payload)
            self._unsynced += len(payload)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            diag.error("logstore", f"파일 기록 실패 {self.path}: {exc}")
            self.close()

    def sync(self) -> None:
        """OS 캐시를 디스크로 내린다 — 다른 도구가 지금 열어도 내용이 보이게."""
        if self._fh is None or not self._unsynced:
            return
        try:
            os.fsync(self._fh.fileno())
            self._unsynced = 0
        except Exception:  # noqa: BLE001 - sync 실패로 수신을 멈추지 않는다
            pass

    def close(self) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                fh.flush()
                os.fsync(fh.fileno())
            except Exception:  # noqa: BLE001
                pass
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass


class LogStore:
    """포트별 ring + 파일 기록. 모든 공개 메서드는 스레드 안전하다."""

    def __init__(self, capacity_per_port: int = 200_000):
        self.capacity_per_port = max(1_000, int(capacity_per_port))
        self._lock = threading.RLock()
        self._seq = 0
        self._t0_wall = time.time()
        self._t0_mono = time.monotonic()
        self._lines: dict[str, list[LogLine]] = {}
        self._counts: dict[str, int] = {}
        self._evicted: dict[str, int] = {}
        self._redactor = None
        # 라인 변환 파이프라인 — append 시 redact 보다 먼저 순서대로 적용된다.
        # 새 변환(타임존 정규화, 커스텀 마스킹 등)은 여기 끼우면 화면·ring·파일에 일괄 반영된다.
        # sanitize_controls 는 끌 수 없다 — 제어문자 하나로 로그 파일 전체가 안 열린다
        self._transforms: list = [sanitize_controls]
        # 세션 상태
        self._base_dir: str | None = None
        self._session: str | None = None
        self._session_base: str | None = None
        self._session_day: str | None = None
        self._part = 1
        self.max_file_bytes = DEFAULT_MAX_FILE_BYTES
        self._writers: dict[str, _Writer] = {}
        self._merged: _Writer | None = None
        self._recording = False
        self._paused = False
        self._paused_dropped = 0
        self._names: dict[str, str] = {}     # 포트 -> 파일명 조각 (비면 역할명 소문자)
        self._include_session = True
        self._use_date_folder = True         # 끄면 base_dir 에 바로 쓴다 (MMDD 하위 폴더 없음)
        # 파일 I/O 전용 스레드 — 디스크가 한 번 늦으면 reader 3개가 같이 멈추고
        # COM RX 버퍼가 넘쳐 수신이 유실된다. 큐 순서 = seq 순서 (락 안에서 넣는다).
        # ★실제 write() 는 _lock 밖에서 한다 — _service_lock 이 소비자(writer 스레드 /
        # split / stop)를 직렬화해 파일 내 순서를 지킨다.
        self._queue: deque = deque()
        self._queue_cv = threading.Condition(threading.Lock())
        self._service_lock = threading.Lock()
        self._writer_stop = threading.Event()
        self._writer_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ 설정

    def set_redactor(self, redactor) -> None:
        """redact 적용 지점을 여기 한 곳으로 모은다 — 원문이 ring 이나 파일에 남을 경로가 없다."""
        with self._lock:
            self._redactor = redactor

    def set_ansi_strip(self, enabled: bool) -> None:
        """strip_ansi 만 넣고 뺀다 — add_transform() 으로 등록한 확장을 지우면 안 된다."""
        with self._lock:
            others = [t for t in self._transforms if t is not strip_ansi]
            self._transforms = [strip_ansi, *others] if enabled else others

    def add_transform(self, fn) -> None:
        """확장 포인트 — str -> str 변환을 파이프라인 끝(단, redact 앞)에 추가한다."""
        with self._lock:
            self._transforms = [*self._transforms, fn]

    def register_port(self, port: str) -> None:
        with self._lock:
            self._lines.setdefault(port, [])
            self._counts.setdefault(port, 0)

    # ------------------------------------------------------------------ 세션

    def start_session(self, base_dir: str, session: str, ports: list[str],
                      overwrite: bool = False) -> None:
        """포트별 파일 + 병합 파일을 연다. 이미 열려 있으면 닫고 새로 연다.

        overwrite=True 면 같은 이름의 기존 파일을 시작 시점에 지운다 — 사용자가
        덮어쓰기를 명시적으로 골랐을 때만 쓴다 (기본은 이어쓰기).
        """
        self.stop_session()
        with self._service_lock:
            # 파일 쪽 상태(_writers/_session/_part/_session_day/_base_dir)는 _service_lock 소유다
            self._base_dir = base_dir
            self._session = session
            self._session_base = session
            self._part = 1
            self._session_day = time.strftime("%m%d")
            self._open_writers(ports)
            if overwrite:
                self._remove_existing_targets()
        with self._lock:
            for port in ports:
                self.register_port(port)
            self._recording = True
        # stop Event 는 스레드마다 새로 만든다 — join 타임아웃으로 좀비가 남아도
        # 자기 Event(이미 set)로 종료를 계속 시도하고, 새 세션 스레드와 얽히지 않는다.
        stop_event = threading.Event()
        self._writer_stop = stop_event
        self._writer_thread = threading.Thread(target=self._writer_loop, args=(stop_event,),
                                               name="logwriter", daemon=True)
        self._writer_thread.start()
        diag.info("logstore", f"session start `{session}` dir={self._day_dir()} ports={ports}")

    def stop_session(self) -> None:
        """큐를 비우고 파일을 닫는다 — 종료 시 마지막 라인이 사라지지 않게."""
        thread = self._writer_thread
        stop_event = self._writer_stop
        if thread is not None and thread.is_alive():
            stop_event.set()
            with self._queue_cv:
                self._queue_cv.notify_all()
            thread.join(timeout=3.0)
            if thread.is_alive():
                # 좀비는 자기 Event 로 계속 종료를 시도한다. 여기서 clear 하면
                # 영영 안 죽으므로 절대 되돌리지 않는다.
                diag.warn("logstore", "writer 스레드가 3초 안에 안 끝났다 — 자기 종료에 맡긴다")
        self._writer_thread = None
        with self._lock:
            was_recording = self._recording
            self._recording = False
        self._service()          # 남은 큐를 파일로 (락 밖)
        with self._service_lock:
            self._close_writers()
        if was_recording:
            diag.info("logstore", f"session stop, counters={self.counters()}")

    def _writer_loop(self, stop_event: threading.Event) -> None:
        last_sync = time.monotonic()
        while True:
            with self._queue_cv:
                while not self._queue and not stop_event.is_set():
                    self._queue_cv.wait(0.2)
                stopping = stop_event.is_set() and not self._queue
            if stopping:
                self._sync_all()
                return
            self._service()
            # 주기적으로 디스크에 내린다 — 안 하면 다른 도구가 파일을 열었을 때
            # 크기가 0 이거나 내용이 비어 보인다
            if time.monotonic() - last_sync >= SYNC_INTERVAL_S:
                self._sync_all()
                last_sync = time.monotonic()

    def _sync_all(self) -> None:
        with self._service_lock:
            for writer in self._writers.values():
                writer.sync()
            if self._merged is not None:
                self._merged.sync()

    def _service(self) -> None:
        """큐를 비워 파일에 쓴다. **self._lock 을 잡지 않는다** —
        디스크가 늦어도 reader 의 append 와 GUI 의 pull 이 멈추면 안 되기 때문.
        소비자 직렬화는 _service_lock 이 맡고, 큐가 FIFO 라 파일 내 순서는 seq 순서다.
        """
        with self._service_lock:
            while True:
                with self._queue_cv:
                    if not self._queue:
                        return
                    line = self._queue.popleft()
                self._rollover_if_needed()
                writer = self._writers.get(line.port)
                if writer is None and self._base_dir is not None:
                    # 세션 시작 뒤에 생긴 포트도 자기 파일을 갖는다 (조용히 누락되면 안 된다)
                    writer = self._new_writer(line.port)
                    self._writers[line.port] = writer
                if writer is not None:
                    writer.write(format_for_port_file(line))
                if self._merged is not None:
                    self._merged.write(format_for_merged_file(line))

    def _day_dir(self) -> str:
        if self._base_dir is None:
            raise RuntimeError(tr('세션이 시작되지 않았습니다 — start_session() 이 먼저입니다'))
        if not self._use_date_folder:
            return self._base_dir
        return os.path.join(self._base_dir, self._session_day or time.strftime("%m%d"))

    def set_file_naming(self, names: dict[str, str], include_session: bool = True) -> None:
        """포트별 파일명 조각과 세션 접두어 사용 여부. 다음 세션/분절부터 적용된다."""
        with self._service_lock:
            self._names = {k: _safe_name(v) for k, v in names.items() if v}
            self._include_session = include_session

    def set_use_date_folder(self, enabled: bool) -> None:
        """날짜(MMDD) 하위 폴더 사용 여부. 다음 세션/분절부터 적용된다."""
        with self._service_lock:
            self._use_date_folder = bool(enabled)

    def _named(self, session: str | None, piece: str) -> str:
        return f"{session}_{piece}.log" if self._include_session else f"{piece}.log"

    def file_name_for(self, port: str) -> str:
        return self._named(self._session, self._names.get(port) or port.lower())

    def plan_paths(self, base_dir: str, session: str, ports: list[str]) -> dict[str, str]:
        """start_session 이 만들게 될 파일 경로를 미리 계산한다 — 파일·폴더는 만들지 않는다.

        기록 시작 전 "같은 이름의 파일이 이미 있나" 검사(덮어쓰기 확인)에 쓴다.
        """
        with self._service_lock:
            day_dir = (os.path.join(base_dir, time.strftime("%m%d"))
                       if self._use_date_folder else base_dir)
            paths = {port: os.path.join(day_dir, self._named(session, self._names.get(port) or port.lower()))
                     for port in ports}
            merged = self._names.get(MERGED_KEY) or "all"
            paths[MERGED_KEY] = os.path.join(day_dir, self._named(session, merged))
            return paths

    def _new_writer(self, port: str) -> _Writer:
        return _Writer(os.path.join(self._day_dir(), self.file_name_for(port)))

    def _open_writers(self, ports: list[str]) -> None:
        for port in ports:
            self._writers[port] = self._new_writer(port)
        merged = self._names.get(MERGED_KEY) or "all"
        self._merged = _Writer(os.path.join(self._day_dir(), self._named(self._session, merged)))

    def file_paths(self) -> dict[str, str]:
        """현재 기록 중인 파일 경로 (UI 에서 '열기' 에 쓴다)."""
        with self._service_lock:
            paths = {port: writer.path for port, writer in self._writers.items()}
            if self._merged is not None:
                paths[MERGED_KEY] = self._merged.path
            return paths

    def file_sizes(self) -> dict[str, int]:
        with self._service_lock:
            sizes = {port: writer.bytes_written for port, writer in self._writers.items()}
            if self._merged is not None:
                sizes[MERGED_KEY] = self._merged.bytes_written
            return sizes

    def _remove_existing_targets(self) -> None:
        """덮어쓰기 시작 — 대상 경로의 기존 파일을 지운다 (writer 는 lazy 라 첫 줄에 새로 만든다).

        트래픽이 안 와도 옛 내용이 남아 "덮어썼는데 예전 로그가 보인다" 는 혼동이 없어야
        하므로, 첫 줄을 기다리지 않고 시작 시점에 지운다. 호출자가 _service_lock 소유.
        """
        targets = [writer.path for writer in self._writers.values()]
        if self._merged is not None:
            targets.append(self._merged.path)
        for path in targets:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                # 다른 도구가 물고 있으면 못 지운다 — 이어쓰기로 열리게 두고 기록은 계속한다
                diag.error("logstore", f"덮어쓰기용 기존 파일 삭제 실패 {path}: {exc}")

    def _close_writers(self) -> None:
        for writer in self._writers.values():
            writer.close()
        self._writers.clear()
        if self._merged is not None:
            self._merged.close()
            self._merged = None

    def _rollover_if_needed(self) -> None:
        """자정(날짜 폴더 전환) 또는 파일 크기 상한 도달 시 파일을 갈아끼운다 — 수신은 안 멈춘다.

        호출자가 `_service_lock` 을 들고 있어야 한다 (파일 쪽 상태 소유 락).
        """
        if self._base_dir is None:
            return
        today = time.strftime("%m%d")
        if today != self._session_day:
            ports = list(self._writers.keys())
            self._close_writers()
            self._session_day = today
            # 날짜가 바뀌면 세션명의 시각(HHMMSS)이 파일 내용과 어긋난다 — 새 이름을 붙인다
            self._session_base = f"{self._session_base}_{today}"
            self._part = 1
            self._session = self._session_base
            self._open_writers(ports)
            diag.info("logstore", f"자정 폴더 전환 -> {self._day_dir()} (`{self._session}`)")
            return
        if self.max_file_bytes and self._merged is not None \
                and self._merged.bytes_written >= self.max_file_bytes:
            ports = list(self._writers.keys())
            self._close_writers()
            self._part += 1
            self._session = f"{self._session_base}_p{self._part}"
            self._open_writers(ports)
            diag.info("logstore", f"크기 상한 도달 — 파일 분절 -> `{self._session}`")

    def flush(self) -> None:
        """큐에 남은 라인을 지금 파일에 쓰고 디스크까지 내린다.

        기록은 writer 스레드가 비동기로 하므로, 로그 파일을 바로 열어보거나 티켓에
        첨부하기 직전에 호출하면 마지막 몇 줄까지 확실히 반영된다.
        """
        self._service()
        self._sync_all()

    def relocate(self, base_dir: str, session: str | None = None) -> str:
        """기록 중에 저장 위치·파일명을 바꾼다 — 지금부터 새 파일에 쓴다.

        이미 쓴 파일은 옛 위치에 그대로 둔다 (옮기면 그 사이 다른 도구가 열고 있을 수 있고,
        무엇보다 이미 만들어진 증적을 앱이 움직이면 안 된다). 반환값 = 새 폴더 경로.
        """
        if not self.recording:
            return ""
        self._service()          # 옛 파일로 갈 것은 옛 파일에 (락 밖)
        with self._service_lock:
            ports = [p for p in self._writers]
            self._close_writers()
            self._base_dir = base_dir
            self._session_day = time.strftime("%m%d")
            if session:
                self._session_base = session
                self._session = session
                self._part = 1
            self._open_writers(ports)
            diag.info("logstore", f"기록 위치 변경 -> {self._day_dir()} (`{self._session}`)")
            return self._day_dir()

    def split_session(self, new_name: str | None = None) -> str:
        """연결을 유지한 채 지금부터의 로그를 새 파일로 받는다 (티켓용 작은 파일 첨부).

        코어는 원래 무중단 재오픈이 가능했고, 이 메서드는 그 진입점이다 (GAP-4).
        """
        if not self.recording:
            return ""
        self._service()  # 지금까지의 큐를 옛 파일로 (락 밖)
        with self._service_lock:
            if self._base_dir is None:
                return ""
            ports = [p for p in self._writers if p != MARKER_PORT] or [MARKER_PORT]
            self._close_writers()
            if new_name:
                self._session_base = new_name
                self._part = 1
                self._session = new_name
            else:
                self._part += 1
                self._session = f"{self._session_base}_p{self._part}"
            self._open_writers(ports)
            diag.info("logstore", f"수동 세션 분절 -> `{self._session}`")
            return self._session

    # ------------------------------------------------------------------ 마커

    def marker(self, text: str) -> LogLine:
        """`### ` 구분 마커 — 병합 뷰/병합 파일에서 재현 시점을 표시한다 (GAP-1).

        기존 관행(run_srp_suite 의 `### CYCLE …`, TTL 의 `[STRESS]` 앵커) 계승.
        """
        self.register_port(MARKER_PORT)
        body = text if text.startswith("#") else f"### {text}"
        return self.append(MARKER_PORT, body)

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_paused(self, paused: bool) -> int:
        """기록 일시 정지 / 재개. 반환값 = 정지 구간 동안 파일에 안 남은 줄 수.

        수신·화면·ring 은 계속 돈다 — 파일 기록만 멈춘다. 재개해도 멈춘 동안의 줄은
        파일에 들어가지 않으므로, 그 사실을 로그에 배너로 남긴다 (나중에 "왜 비었지" 방지).
        """
        with self._lock:
            if self._paused == paused:
                return self._paused_dropped
        if paused:
            # 배너를 먼저 기록해야 파일에 남는다 (정지 후에 쓰면 그 배너도 버려진다)
            self._banner_all(tr('!! 기록 일시정지 — 여기부터 재개 표시까지는 파일에 없습니다'))
            self.flush()
            with self._lock:
                self._paused = True
                self._paused_dropped = 0
            diag.info("logstore", "기록 일시정지")
            return 0
        with self._lock:
            self._paused = False
            dropped = self._paused_dropped
        self._banner_all(tr('!! 기록 재개 — 정지 중 {0:,}줄은 이 파일에 없습니다').format(dropped))
        diag.info("logstore", f"기록 재개 — 정지 중 {dropped}줄 미기록")
        return dropped

    def _banner_all(self, text: str) -> None:
        """모든 포트 파일에 같은 배너를 남긴다.

        MARK 파일에만 쓰면 `_shell.log` 만 열어본 사람은 왜 시간이 비는지 알 수 없다.
        """
        with self._lock:
            ports = [p for p in self._lines if p != MARKER_PORT]
        for port in ports or [MARKER_PORT]:
            self.append(port, text)
        self.marker(text.lstrip("! ").strip())

    @property
    def session_name(self) -> str:
        with self._service_lock:
            return self._session or ""

    @property
    def log_dir(self) -> str | None:
        with self._service_lock:
            return self._day_dir() if self._base_dir is not None else None

    def write_error(self) -> str | None:
        with self._service_lock:
            for writer in self._writers.values():
                if writer.error:
                    return f"{os.path.basename(writer.path)}: {writer.error}"
            if self._merged is not None and self._merged.error:
                return f"{os.path.basename(self._merged.path)}: {self._merged.error}"
            return None

    # ------------------------------------------------------------------ 적재

    def append(self, port: str, text: str, is_tx: bool = False) -> LogLine:
        with self._lock:
            # 색은 여기서 본문과 분리한다 — 파일·grep 은 깨끗하게, 화면은 색을 살린다
            spans: tuple = ()
            if "\x1b" in text or "\x07" in text:
                text, spans = ansi.parse(text)
            for transform in self._transforms:
                try:
                    text = transform(text)
                except Exception:  # noqa: BLE001 - 변환 하나가 깨져도 수신은 계속돼야 한다
                    diag.exception("logstore", f"transform 실패: {getattr(transform, '__name__', '?')}")
            if self._redactor is not None:
                masked = self._redactor.apply(text)
                if masked != text:
                    spans = ()   # 길이가 바뀌면 색 offset 이 어긋난다 — 본문이 우선
                    text = masked
            # 시각은 seq 와 같은 락 구간에서 찍는다 — 아니면 병합 파일에서 시각이
            # seq 역순으로 보이는 구간이 생긴다
            self._seq += 1
            line = LogLine(self._seq, time.time(), time.monotonic() - self._t0_mono,
                           port, text, is_tx, spans)

            arr = self._lines.setdefault(port, [])
            arr.append(line)
            self._counts[port] = self._counts.get(port, 0) + 1
            if len(arr) > self.capacity_per_port:
                trimmed = max(1, self.capacity_per_port // 10)
                del arr[:trimmed]
                self._evicted[port] = self._evicted.get(port, 0) + trimmed

            if self._recording and not self._paused:
                with self._queue_cv:
                    self._queue.append(line)
                    self._queue_cv.notify()
            elif self._recording:
                self._paused_dropped += 1   # 정지 중 — 화면엔 남지만 파일엔 안 간다
            return line

    # ------------------------------------------------------------------ 조회

    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def counters(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def pull(self, after_seq: int, ports: list[str] | None = None,
             limit: int | None = None) -> list[LogLine]:
        """after_seq 초과 라인을 seq 오름차순으로 반환. limit 은 뒤에서부터 자른다."""
        return self.pull_with_gap(after_seq, ports, limit).lines

    def pull_with_gap(self, after_seq: int, ports: list[str] | None = None,
                      limit: int | None = None) -> "PullResult":
        """뷰가 밀린 구간이 조용히 사라지지 않도록, 못 준 게 있으면 같이 알려준다.

        - `skipped` : limit 때문에 잘라낸 개수 (정확)
        - `evicted` : ring 이 이미 밀어낸 구간이 있어 개수조차 알 수 없는 경우
        """
        with self._lock:
            keys = list(self._lines.keys()) if ports is None else [p for p in ports if p in self._lines]
            chunks: list[list[LogLine]] = []
            available = 0
            evicted = False
            for port in keys:
                arr = self._lines[port]
                if after_seq >= 0 and arr and self._evicted.get(port, 0) and after_seq < arr[0].seq - 1:
                    # 커서가 ring 에 남은 가장 오래된 라인보다 뒤처졌다 = 이미 밀려난 구간이 있다
                    evicted = True
                start = bisect_right(arr, after_seq, key=_seq_of)
                if start >= len(arr):
                    continue
                available += len(arr) - start
                if limit is not None and len(arr) - start > limit:
                    start = len(arr) - limit
                chunks.append(arr[start:])
            if not chunks:
                return PullResult([], 0, evicted)
            out = chunks[0] if len(chunks) == 1 else list(heapq.merge(*chunks, key=_seq_of))
            if limit is not None and len(out) > limit:
                out = out[-limit:]
            return PullResult(out, max(0, available - len(out)), evicted)

    def clear_buffer(self, ports: list[str] | None = None) -> int:
        """메모리 ring 을 비운다. **파일은 건드리지 않는다** (이미 기록된 증적은 보존).

        긴 세션에서 화면·검색을 정리하고 메모리를 되찾기 위한 것. 반환값은 버린 라인 수.
        """
        with self._lock:
            keys = list(self._lines.keys()) if ports is None else [p for p in ports
                                                                   if p in self._lines]
            dropped = 0
            for port in keys:
                dropped += len(self._lines[port])
                self._evicted[port] = self._evicted.get(port, 0) + len(self._lines[port])
                self._lines[port] = []
        diag.info("logstore", f"버퍼 비움 ports={keys or 'ALL'} dropped={dropped}")
        return dropped

    def tail(self, ports: list[str] | None = None, limit: int = 5_000) -> list[LogLine]:
        """ring 소급 채움용 — 가장 최근 limit 개."""
        return self.pull(-1, ports, limit)
