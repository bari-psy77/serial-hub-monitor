"""terminal — ConPTY 셸 세션(pywinpty) + VT 화면 상태(pyte). Qt 를 모른다.

설계문서 docs/superpowers/specs/2026-08-14-terminal-design.md.
UI 는 TerminalBuffer.generation 을 50ms tick 에서 비교해 바뀐 경우에만 다시 그린다 —
콘솔과 같은 pull 모델이라 firehose 출력에도 이벤트 큐가 넘치지 않는다.

pywinpty 는 Windows 전용이라 임포트를 가드한다 — 없는 환경(리눅스 CI, 미설치 소스
실행)에서는 TERMINAL_AVAILABLE=False 로 두고 UI 가 설치 안내를 보여준다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass

from .diag import diag

try:
    import pyte
    _PYTE_ERROR = ""
except Exception as exc:  # noqa: BLE001 - 의존성 부재는 기능 비활성으로 열화한다
    pyte = None
    _PYTE_ERROR = str(exc)

try:
    from winpty import PtyProcess
    _WINPTY_ERROR = ""
except Exception as exc:  # noqa: BLE001
    PtyProcess = None
    _WINPTY_ERROR = str(exc)

BUFFER_AVAILABLE = pyte is not None
TERMINAL_AVAILABLE = pyte is not None and PtyProcess is not None
TERMINAL_ERROR = _PYTE_ERROR or _WINPTY_ERROR

DEFAULT_SHELL = ["powershell.exe"]
DEFAULT_COLS = 120
DEFAULT_ROWS = 30


@dataclass(frozen=True, slots=True)
class Run:
    """같은 표시 속성이 이어지는 구간 — 문자 단위로 그리면 화면당 수천 번 칠하게 된다.

    cells = 이 run 이 차지하는 터미널 칸 수. 전각(한글 등) 문자는 글자 1개가 2칸이라
    len(text) 로 위치를 재면 화면이 어긋난다 — 렌더러는 반드시 cells 로 전진한다.
    """

    text: str
    fg: str = "default"
    bg: str = "default"
    bold: bool = False
    reverse: bool = False
    cells: int = 1


@dataclass(frozen=True, slots=True)
class Frame:
    rows: list          # list[list[Run]]
    cursor: tuple       # (x, y, visible)
    generation: int


class TerminalBuffer:
    """pyte HistoryScreen 래퍼. feed 는 reader 스레드, snapshot 은 GUI 스레드 — 락으로 보호."""

    def __init__(self, cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS,
                 history: int = 5000):
        if pyte is None:
            raise RuntimeError(f"pyte unavailable: {_PYTE_ERROR}")
        self.cols = cols
        self.rows = rows
        self._lock = threading.Lock()
        # ratio=0.1 → 한 페이지 = 화면의 1/10 (30행이면 3줄) — 휠 한 칸 단위에 맞춘다
        self._screen = pyte.HistoryScreen(cols, rows, history=history, ratio=0.1)
        self._stream = pyte.Stream(self._screen)
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def _scroll_bottom_locked(self) -> None:
        history = self._screen.history
        while history.position < history.size and history.bottom:
            self._screen.next_page()
            history = self._screen.history

    def feed(self, data: str) -> None:
        if not data:
            return
        with self._lock:
            # pyte 의 페이징은 buffer 자체를 돌려놓는다 — 스크롤백 상태로 feed 하면
            # 과거 화면 위에 출력이 섞인다. 새 출력이 오면 먼저 최신으로 복귀한다.
            self._scroll_bottom_locked()
            self._stream.feed(data)
            self._generation += 1

    def touch(self) -> None:
        """화면 내용 없이도 다시 그리게 한다 (프로세스 종료 배너 등 상태 변화용)."""
        with self._lock:
            self._generation += 1

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = max(2, int(cols)), max(2, int(rows))
        with self._lock:
            if (cols, rows) == (self.cols, self.rows):
                return
            self._screen.resize(rows, cols)
            self.cols, self.rows = cols, rows
            self._generation += 1

    def page_up(self) -> None:
        with self._lock:
            self._screen.prev_page()
            self._generation += 1

    def page_down(self) -> None:
        with self._lock:
            self._screen.next_page()
            self._generation += 1

    def scroll_to_bottom(self) -> None:
        """스크롤백을 접고 최신 화면으로 — 타이핑·재시작 등 상호작용 직전에 부른다."""
        with self._lock:
            self._scroll_bottom_locked()
            self._generation += 1

    def reset(self) -> None:
        """화면·히스토리를 완전히 비운다 — 재시작한 셸이 깨끗한 화면에서 시작하게."""
        with self._lock:
            self._screen.reset()
            self._screen.history.top.clear()
            self._screen.history.bottom.clear()
            self._screen.history = self._screen.history._replace(
                position=self._screen.history.size)
            self._generation += 1

    def text(self) -> str:
        """현재 보이는 화면 전체 (복사·테스트용)."""
        with self._lock:
            return "\n".join(row.rstrip() for row in self._screen.display)

    def snapshot(self) -> Frame:
        with self._lock:
            rows: list[list[Run]] = []
            buffer = self._screen.buffer
            for y in range(self.rows):
                line = buffer[y]
                runs: list[Run] = []
                run_chars: list[str] = []
                run_cells = 0
                attrs = None
                x = 0
                while x < self.cols:
                    ch = line[x]
                    if ch.data == "":
                        # 전각 문자의 연속 셀 (pyte 가 data='' 로 표시) — 앞 글자가
                        # 이미 2칸을 차지했다. 공백으로 바꾸면 글자 사이가 벌어진다.
                        x += 1
                        continue
                    cell_attrs = (ch.fg, ch.bg, bool(ch.bold), bool(ch.reverse))
                    if x + 1 < self.cols and line[x + 1].data == "":
                        # 전각은 독립 run — 렌더러가 2칸 자리에 glyph 하나를 그린다
                        if run_chars:
                            runs.append(Run("".join(run_chars), *attrs, cells=run_cells))
                            run_chars, run_cells = [], 0
                        runs.append(Run(ch.data, *cell_attrs, cells=2))
                        attrs = None
                        x += 2
                        continue
                    if attrs is None:
                        attrs = cell_attrs
                    if cell_attrs != attrs:
                        runs.append(Run("".join(run_chars), *attrs, cells=run_cells))
                        run_chars, run_cells = [], 0
                        attrs = cell_attrs
                    run_chars.append(ch.data or " ")
                    run_cells += 1
                    x += 1
                if run_chars:
                    runs.append(Run("".join(run_chars), *attrs, cells=run_cells))
                rows.append(runs)
            cursor = (self._screen.cursor.x, self._screen.cursor.y,
                      not self._screen.cursor.hidden)
            return Frame(rows, cursor, self._generation)


class TerminalSession:
    """pywinpty 프로세스 + reader 스레드. 화면 상태는 self.buffer 가 소유한다."""

    def __init__(self, argv: list[str] | None = None, cwd: str | None = None,
                 cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS, history: int = 5000):
        if not TERMINAL_AVAILABLE:
            raise RuntimeError(f"terminal unavailable: {TERMINAL_ERROR}")
        self.argv = list(argv or DEFAULT_SHELL)
        self.cwd = cwd or os.path.expanduser("~")
        self.buffer = TerminalBuffer(cols, rows, history)
        self._proc = None
        self._reader: threading.Thread | None = None
        self._waiter: threading.Thread | None = None
        self._alive = False
        self._exit_status: int | None = None
        self._start()

    # ------------------------------------------------------------------ 수명

    def _start(self) -> None:
        cmdline = subprocess.list2cmdline(self.argv)
        self._proc = PtyProcess.spawn(cmdline, cwd=self.cwd,
                                      dimensions=(self.buffer.rows, self.buffer.cols))
        self._alive = True
        self._exit_status = None
        self._reader = threading.Thread(target=self._read_loop, args=(self._proc,),
                                        name="terminal-reader", daemon=True)
        self._reader.start()
        # ★종료 감지는 read 파이프로 하지 않는다 — ConPTY 는 자식이 죽어도 read() 가
        #   블로킹된 채 안 풀릴 수 있다 (실측). wait() 전용 스레드가 확실한 신호다.
        self._waiter = threading.Thread(target=self._wait_loop, args=(self._proc,),
                                        name="terminal-waiter", daemon=True)
        self._waiter.start()
        diag.info("terminal", f"shell start {self.argv} cwd={self.cwd}")

    def _read_loop(self, proc) -> None:
        try:
            while True:
                chunk = proc.read(4096)   # blocking — close()/EOF 에 예외로 깨어난다
                if chunk:
                    self.buffer.feed(chunk)
        except Exception:  # noqa: BLE001 - EOF·핸들 닫힘 등 어떤 형태든 = 읽기 끝
            pass

    def _wait_loop(self, proc) -> None:
        try:
            status = proc.wait()
        except Exception:  # noqa: BLE001
            try:
                status = proc.exitstatus
            except Exception:  # noqa: BLE001
                status = None
        if proc is self._proc:
            self._exit_status = status
            self._alive = False
            self.buffer.touch()   # 내용 변화가 없어도 종료 배너를 그리게 한다
            diag.info("terminal", f"shell exit status={status}")

    @property
    def alive(self) -> bool:
        return self._alive and self._proc is not None and self._proc.isalive()

    @property
    def exit_status(self) -> int | None:
        return self._exit_status

    def close(self) -> None:
        proc, self._proc = self._proc, None
        self._alive = False
        if proc is not None:
            try:
                proc.terminate(force=True)
            except Exception:  # noqa: BLE001 - 이미 죽었으면 그만
                pass
            try:
                proc.close()   # 파이프 핸들을 닫아 블로킹된 read() 를 깨운다
            except Exception:  # noqa: BLE001
                pass
        for thread in (self._reader, self._waiter):
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
        self._reader = None
        self._waiter = None

    def restart(self) -> None:
        """같은 셸·같은 폴더로 새 프로세스 — 화면은 비우고 맨 위부터 다시 시작한다.

        이어 그리면 새 ConPTY 의 좌표와 옛 화면이 어긋나 프롬프트가 화면 한가운데에
        찍힌다 (실기 확인). 실제 터미널 재시작처럼 깨끗한 화면이 맞다.
        """
        self.close()
        self.buffer.reset()
        self._start()

    # ------------------------------------------------------------------ 입출력

    def write(self, text: str) -> None:
        proc = self._proc
        if proc is None or not self._alive:
            return
        try:
            proc.write(text)
        except Exception:  # noqa: BLE001 - 죽은 직후의 경쟁은 종료 처리에 맡긴다
            pass

    def resize(self, cols: int, rows: int) -> None:
        self.buffer.resize(cols, rows)
        proc = self._proc
        if proc is not None and self._alive:
            try:
                proc.setwinsize(self.buffer.rows, self.buffer.cols)
            except Exception:  # noqa: BLE001
                pass


def launch_admin_shell(cwd: str | None = None) -> bool:
    """외부 관리자(UAC 승격) PowerShell 창을 띄운다. 승격 셸은 임베드할 수 없다.

    반환값 = 실행 요청이 접수됐는가 (사용자가 UAC 를 거부하면 False).
    """
    if sys.platform != "win32":
        return False
    import ctypes
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "powershell.exe", "-NoExit",
            cwd or os.path.expanduser("~"), 1)
        ok = rc > 32
    except Exception:  # noqa: BLE001
        ok = False
    diag.info("terminal", f"admin shell launch -> {ok}")
    return ok
