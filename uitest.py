#!/usr/bin/env python3
"""UI 시나리오 자동검증 — 실제 장비 없이 가상 DUT 로 GUI 전체 흐름을 돌린다.

  python uitest.py

selftest.py 가 단위 검증이라면, 이 파일은 **사용자 시나리오** 검증이다:
실제 MainWindow(offscreen) + 실제 QTimer 이벤트 루프 + 가상 3콘솔(장비 동작 모사)로
"설정 > 연결에서 포트 고르고 → 전체 Probe → 연결 → 명령 → 필터 → 재부팅 → 부하"
를 끝까지 밟는다. 가상 DUT 의 응답 문자열은 실제 펌웨어 디스패처
(MainLoopDefault.cpp / user_cli.c)와 같은 형식이다.
"""

from __future__ import annotations

import itertools
import os
import sys
import tempfile
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "serial_hub"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from .core import config as config_mod  # noqa: E402
from .core import diag as diag_mod  # noqa: E402
from .core import portscan  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(f"{name} — {detail}")
        print(f"  [FAIL] {name} — {detail}")


# ------------------------------------------------------------------ 가상 DUT

VCOM_MLOG, VCOM_SHELL, VCOM_UCLI = "VCOM1", "VCOM2", "VCOM3"


class VirtualConsole:
    """pyserial 호환 최소 인터페이스. VirtualDut 가 큐에 응답을 밀어넣는다."""

    def __init__(self, dut: "VirtualDut", com: str):
        self.dut = dut
        self.com = com
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.killed = False
        self.pending_line = b""

    def feed(self, data: bytes) -> None:
        with self.lock:
            self.buf += data

    def read(self, size: int = 1) -> bytes:
        if self.killed:
            raise OSError("virtual port lost")
        with self.lock:
            out = bytes(self.buf[:size])
            del self.buf[:len(out)]
        if not out:
            time.sleep(0.005)
        return out

    def write(self, data: bytes) -> int:
        if self.killed:
            raise OSError("virtual port lost")
        self.pending_line += data
        while b"\n" in self.pending_line:
            line, self.pending_line = self.pending_line.split(b"\n", 1)
            self.dut.handle(self.com, line.rstrip(b"\r").decode("utf-8", "replace"), self)
        return len(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        with self.lock:
            self.buf.clear()

    def close(self) -> None:
        self.dut.on_close(self.com, self)


class VirtualDut:
    """3콘솔 모사 — 응답 형식은 실제 디스패처와 동일하게 맞춘다."""

    def __init__(self):
        self.live: dict[str, VirtualConsole] = {}
        self.down: set[str] = set()
        self.mlog_rate = 30           # line/s
        self.mlog_count = 0
        self.shell_cmds: list[str] = []
        self.ucli_cmds: list[str] = []
        self._stop = threading.Event()
        self.paused = threading.Event()   # 방출/수신 카운트를 같은 시점에 스냅샷하기 위함
        self._emitter = threading.Thread(target=self._emit_loop, name="vdut-mlog", daemon=True)
        self._emitter.start()

    # ------------------------------------------------ pyserial 대체 진입점

    def open(self, com: str, _baud: int, timeout: float = 0.05):  # noqa: ARG002
        if com not in (VCOM_MLOG, VCOM_SHELL, VCOM_UCLI):
            raise OSError(f"could not open port {com!r}")
        if com in self.down:
            raise OSError(f"port {com!r} unavailable (device down)")
        console = VirtualConsole(self, com)
        old = self.live.get(com)
        if old is not None:
            old.killed = True
        self.live[com] = console
        if com == VCOM_UCLI and getattr(self, "_boot_pending", False):
            self._boot_pending = False
            console.feed(b"\r\n-- BOOT -- my_thermostat v0.9.99\r\ninit_control_env ok\r\n")
        return console

    def list_ports(self):
        return [portscan.PortInfo(VCOM_MLOG, "Virtual MLOG UART"),
                portscan.PortInfo(VCOM_SHELL, "Virtual Matter shell"),
                portscan.PortInfo(VCOM_UCLI, "Virtual User CLI")]

    def on_close(self, com: str, console: VirtualConsole) -> None:
        if self.live.get(com) is console:
            self.live.pop(com, None)

    # ------------------------------------------------ 콘솔 동작

    def _emit_loop(self) -> None:
        seq = 0
        while not self._stop.is_set():
            console = self.live.get(VCOM_MLOG)
            if self.paused.is_set():
                time.sleep(0.01)
                continue
            if console is not None and not console.killed:
                seq += 1
                self.mlog_count += 1
                if seq % 7 == 0:
                    line = f"\x1b[32m[DIS]\x1b[0m mDNS advertise #{seq}\r\n"  # ANSI 컬러 모사
                elif seq % 11 == 0:
                    line = "\r\n"  # 빈 라인 다발 모사
                else:
                    line = f"[ZCL] CASE metric {seq}\r\n"
                console.feed(line.encode())
            time.sleep(max(0.001, 1.0 / self.mlog_rate))

    def handle(self, com: str, line: str, console: VirtualConsole) -> None:
        if com == VCOM_MLOG:
            return  # 로그 전용 — RX 디스패처 없음 (user_cli/shell 과 달리 무반응)
        if com == VCOM_SHELL:
            self.shell_cmds.append(line)
            console.feed(f"> {line}\r\n".encode())  # 명령 에코
            cmd = line.split()[0] if line.split() else ""
            if cmd == "otcli":
                console.feed(b"leader\r\nDone\r\n")
            elif cmd == "wifi":
                console.feed(b"Done\r\n")
            else:
                # MainLoopDefault.cpp:189 형식
                console.feed(f"Error {line}: 2f (Invalid argument)\r\n".encode())
            return
        if com == VCOM_UCLI:
            self.ucli_cmds.append(line)
            console.feed(f"{line}\r\n".encode())
            cmd = line.split()[0] if line.split() else ""
            if cmd == "help":
                console.feed(b"- help : Help\r\n- reboot : reboot system\r\n")
            elif cmd == "heap":
                console.feed(b"free heap: 123456\r\n")
            elif cmd == "reboot":
                threading.Thread(target=self._do_reboot, daemon=True).start()
            else:
                console.feed(b"\r\nInvalid command\r\n")  # user_cli.c:527 형식

    def _do_reboot(self) -> None:
        time.sleep(0.1)
        self.down.add(VCOM_UCLI)
        console = self.live.get(VCOM_UCLI)
        if console is not None:
            console.killed = True
        time.sleep(1.0)
        self._boot_pending = True
        self.down.discard(VCOM_UCLI)

    def stop(self) -> None:
        self._stop.set()


# ------------------------------------------------------------------ 러너

def _free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def send_key(app, widget, key, text: str = "") -> None:
    """실제 키 입력 경로로 보낸다 — 슬롯을 직접 부르면 단축키·포커스 라우팅 버그를 못 잡는다."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    if widget is None:
        raise AssertionError("키를 보낼 위젯이 없다 (offscreen 에서 focusWidget() 은 None 일 수 있다)")
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, key, Qt_NoModifier(), text))
    app.processEvents()


def Qt_NoModifier():  # noqa: N802 - Qt 임포트를 함수 안에 가두기 위한 얇은 헬퍼
    from PySide6.QtCore import Qt
    return Qt.NoModifier


def spin(app, seconds: float) -> None:
    """실제 QTimer(tick 50ms)가 돌도록 이벤트 루프를 밟는다.

    ★processEvents() 는 DeferredDelete 를 처리하지 않는다 — app.exec() 안에서만 돈다.
    그래서 여기서 직접 비워준다. 안 그러면 deleteLater() 한 위젯이 테스트에서만
    살아남아, 실기에서 "이미 삭제된 C++ 객체" 로 죽는 버그를 잡지 못한다.
    """
    from PySide6.QtCore import QEvent
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.01)


def wait_for(app, predicate, timeout: float = 6.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def select_port(card, com: str) -> None:
    index = card.port_combo.findData(com)
    assert index >= 0, f"{com} not in combo"
    card.port_combo.setCurrentIndex(index)


def main() -> int:  # noqa: PLR0915
    tmp = tempfile.mkdtemp(prefix="serialhub_uitest_")
    config_mod.DATA_DIR = os.path.join(tmp, "data")
    config_mod.PROFILE_DIR = os.path.join(tmp, "profiles")
    config_mod.SETTINGS_PATH = os.path.join(tmp, "settings.json")
    diag_mod.diag.reconfigure()  # DATA_DIR 재지정 후 옛 핸들러를 닫고 다시 연다
    # 이 스위트의 단언 문구는 한국어 UI 기준이다. 기본 표시 언어가 영어가 되면서(1.3.0)
    # 설정이 빈 tmp 에서는 영어로 떠 전부 어긋난다 — 명시적으로 한국어를 지정한다.
    from .core.i18n import set_language
    set_language("ko")

    dut = VirtualDut()
    original_open, original_list = portscan.open_serial, portscan.list_ports
    portscan.open_serial = dut.open
    portscan.list_ports = dut.list_ports

    from PySide6.QtWidgets import QApplication, QWidget

    from .core.config import Profile
    from .core.filters import FilterRule
    from .ui import theme
    from .ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)

    slot_errors: list[str] = []
    original_hook = sys.excepthook

    def record(exc_type, exc, tb):
        slot_errors.append(f"{exc_type.__name__}: {exc}")
        original_hook(exc_type, exc, tb)

    sys.excepthook = record

    profile = Profile()
    profile.name = "__uitest__"
    profile.log_base_dir = os.path.join(tmp, "logs")
    # 벤치 PC 에서 실기 Serial Hub 가 떠 있으면 3341 이 겹친다 — 테스트 명령이 실제 DUT 로
    # 가는 사고를 막기 위해 임시 포트를 쓴다 (0 = OS 가 골라줌, start() 후 실제 포트 조회)
    profile.bridge_port = _free_port()
    window = MainWindow(profile)
    window.show()
    spin(app, 0.3)

    try:
        # ---------------------------------------------------------- S1 포트 열거
        print("\n== S1. 설정 > 연결 — 가상 포트 열거·선택 ==")
        page = window.connection_page
        for card in page.cards.values():
            card.refresh_ports()
        check("가상 포트 3개가 드롭다운에 뜬다",
              all(card.port_combo.findData(VCOM_MLOG) >= 0 for card in page.cards.values()))

        # 일부러 MLOG↔SHELL 을 바꿔 놓는다 (벤치 COM 스왑 상황 재현)
        select_port(page.cards["MLOG"], VCOM_SHELL)
        select_port(page.cards["SHELL"], VCOM_MLOG)
        select_port(page.cards["UCLI"], VCOM_UCLI)
        check("드롭다운 선택이 프로파일에 반영된다",
              profile.port("MLOG").com == VCOM_SHELL and profile.port("SHELL").com == VCOM_MLOG)

        # ---------------------------------------------------------- S2 전체 Probe
        print("\n== S2. 전체 Probe — 스왑 감지·매핑 제안·적용 ==")
        page.probe_all_button.click()
        done = wait_for(app, lambda: not any(c.probing for c in page.cards.values()), timeout=12.0)
        check("probe 3건이 끝난다", done)
        # 설정 창을 띄우지 않은 상태라 isVisible() 은 False 다 — 제안 내용 자체를 본다
        check("스왑을 감지해 매핑 제안이 뜬다",
              wait_for(app, lambda: bool(page._suggested), timeout=2.0),
              page.suggestion.text())
        page.apply_suggestion_button.click()
        spin(app, 0.2)
        check("제안 적용으로 매핑이 바로잡힌다",
              profile.port("MLOG").com == VCOM_MLOG and profile.port("SHELL").com == VCOM_SHELL,
              str([(p.role, p.com) for p in profile.ports]))
        check("probe 는 실명령을 보내지 않았다 (무해 토큰만)",
              all(cmd.startswith("serialhub_probe") for cmd in dut.shell_cmds) and
              all(cmd.startswith("serialhub_probe") for cmd in dut.ucli_cmds),
              f"shell={dut.shell_cmds[:3]} ucli={dut.ucli_cmds[:3]}")

        # ---------------------------------------------------------- S3 전체 연결
        print("\n== S3. 전체 연결 — 수신·기록 시작 ==")
        page.connect_all_button.click()
        check("3포트 전부 연결된다",
              wait_for(app, lambda: all(window.session.is_connected(r)
                                        for r in ("MLOG", "SHELL", "UCLI"))))
        check("연결 성공 시 상태줄에 결과가 뜬다", bool(window.status_left.text()))
        # ★기록은 자동으로 시작하지 않는다 — [로그 시작] 을 눌러야 파일이 생긴다
        check("연결만으로는 기록이 시작되지 않는다", not window.session.store.recording)
        check("연결 직후 REC 표시는 '기록 안 함'", "기록 안 함" in window.rec_button.text(),
              window.rec_button.text())
        check("기록 전에는 멈춤 버튼이 비활성", not window.pause_button.isEnabled())
        check("로그 시작 버튼 문구", "로그 시작" in window.log_button.text(),
              window.log_button.text())
        started = window.start_logging(ask=False)   # 확인 창은 GUI 테스트에서 건너뛴다
        check("[로그 시작] 으로 기록이 시작된다", started and window.session.store.recording)
        check("기록 중에는 버튼이 '로그 중지' 로 바뀐다", "로그 중지" in window.log_button.text(),
              window.log_button.text())
        for reader in window.session.readers.values():
            reader.reconnect_interval = 0.2  # 시험 시간 단축
        check("MLOG 수신이 콘솔에 흐른다",
              wait_for(app, lambda: "CASE metric" in window.panes["MLOG"].view.toPlainText()))

        # ---------------------------------------------------------- S4 ANSI/빈줄
        print("\n== S4. ANSI 컬러 제거·빈 라인 숨김 ==")
        check("ANSI 이스케이프가 화면에 없다",
              wait_for(app, lambda: "mDNS advertise" in window.panes["MLOG"].view.toPlainText())
              and "\x1b" not in window.panes["MLOG"].view.toPlainText())

        # 펌웨어가 넣은 색이 실제로 화면에 칠해져야 한다 (지우는 게 아니라 살린다)
        def colored_block_count() -> int:
            document = window.panes["MLOG"].view.document()
            found = 0
            block = document.begin()
            while block.isValid():
                if "mDNS advertise" in block.text():
                    for fragment_format in block.layout().formats():
                        color = fragment_format.format.foreground().color()
                        if color.isValid() and color.name().lower() not in ("#000000", "#191f28"):
                            found += 1
                            break
                block = block.next()
            return found

        check("펌웨어 색이 화면에 칠해진다", wait_for(app, lambda: colored_block_count() > 0),
              "색 입힌 블록 0개")
        window.ansi_action.setChecked(False)
        window.toggle_ansi_color()
        spin(app, 0.3)
        check("색 표시를 끄면 본문만 남는다", colored_block_count() == 0,
              f"{colored_block_count()}개 남음")
        window.ansi_action.setChecked(True)
        window.toggle_ansi_color()
        spin(app, 0.3)
        check("다시 켜면 색이 복원된다", colored_block_count() > 0)
        # 기본값은 날짜 하위 폴더 없이 base 에 바로 저장한다 (log_use_date_folder=False)
        mlog_file = os.path.join(profile.log_base_dir,
                                 f"{window.session.session_name}_mlog.log")
        check("ANSI 이스케이프가 파일에도 없다",
              os.path.exists(mlog_file) and "\x1b" not in open(mlog_file, encoding="utf-8").read(),
              mlog_file)

        # ---------------------------------------------------------- S5 명령 전송
        print("\n== S5. 명령 패널 — 전송·응답·히스토리·오지정 힌트 ==")
        panel = window.command_panel
        panel.select_role("SHELL")
        panel.edit.setText("otcli state")
        panel.send_current()
        check("SHELL 응답(Done)이 콘솔에 온다",
              wait_for(app, lambda: "Done" in window.panes["SHELL"].view.toPlainText()))
        check("TX 에코가 >>> 로 표시된다", ">>> otcli state" in window.panes["SHELL"].view.toPlainText())
        check("히스토리에 쌓인다", panel.history.get("SHELL") == ["otcli state"])

        panel.select_role("UCLI")
        panel.edit.setText("otcli state")   # UCLI 가 모르는 명령 = 오지정 상황
        panel.send_current()
        check("오지정 힌트가 뜬다 (`Invalid command` 감지)",
              wait_for(app, lambda: "대상 포트" in panel.hint.text(), timeout=4.0),
              panel.hint.text())

        # redact — 시리얼로는 원문, 화면·파일·히스토리는 마스킹
        panel.select_role("SHELL")
        panel.edit.setText("wifi connect NTGR_F699 hunter2pass")
        panel.send_current()
        check("장비에는 PSK 원문이 간다",
              wait_for(app, lambda: any("hunter2pass" in c for c in dut.shell_cmds)))
        spin(app, 0.3)
        shell_text = window.panes["SHELL"].view.toPlainText()
        check("화면에는 PSK 가 마스킹된다", "hunter2pass" not in shell_text
              and "<PSK-redacted>" in shell_text, shell_text[-200:])

        # ---------------------------------------------------------- S6 필터드뷰
        print("\n== S6. 필터드뷰 — 소급·라이브·파일 저장 ==")
        window.open_filter_view(FilterRule(pattern="mDNS", ports=["MLOG"]))
        view = window.filter_views[-1]
        spin(app, 0.6)
        text = view.pane.view.toPlainText()
        check("필터 매치만 보인다", "mDNS advertise" in text and "CASE metric" not in text,
              text[:150])
        out_path = os.path.join(tmp, "filtered_out.log")
        from PySide6.QtWidgets import QFileDialog
        original_dialog = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(lambda *_a, **_k: (out_path, ""))
        try:
            view.save_button.click()
        finally:
            QFileDialog.getSaveFileName = original_dialog
        check("필터 결과가 파일로 저장된다",
              os.path.exists(out_path) and "mDNS advertise" in open(out_path, encoding="utf-8").read())
        view.close()
        spin(app, 0.2)

        # ---------------------------------------------------------- S6b 마커·분절·트리거·브리지
        print("\n== S6b. 마커 / 세션 분절 / 트리거 / 자동화 브리지 ==")
        window.insert_marker("T1 cycle start")
        window._apply_layout("merged")   # 병합 뷰를 실제로 띄워 텍스트를 단정한다
        spin(app, 0.4)
        check("마커가 병합 뷰에 보인다",
              "### T1 cycle start" in window.merged_pane.view.toPlainText(),
              window.merged_pane.view.toPlainText()[-200:])
        window._apply_layout("split")
        spin(app, 0.2)

        first_session = window.session.store.session_name
        window.split_log_session()
        spin(app, 0.3)
        split_session = window.session.store.session_name
        check("세션 분절로 파일 이름이 바뀐다", split_session != first_session,
              f"{first_session} -> {split_session}")
        check("분절 후에도 수신이 계속된다",
              wait_for(app, lambda: os.path.exists(
                  os.path.join(profile.log_base_dir, f"{split_session}_mlog.log"))))

        # 트리거: MLOG 에 WDOG 이벤트 주입
        base_total = window.trigger_watcher.total()
        console = dut.live.get(VCOM_MLOG)
        console.feed(b"[SYS] WDOG1 reset detected\r\n")
        console.feed(b"[SYS] MemManage fault at 0x08010000\r\n")
        check("트리거가 집계된다 (WDOG+MemManage)",
              wait_for(app, lambda: window.trigger_watcher.total() >= base_total + 2),
              str(window.trigger_watcher.counts))
        check("트리거 칩이 갱신된다",
              wait_for(app, lambda: window.trigger_chip.text() != "⚡ 0"),
              window.trigger_chip.text())

        # 브리지: 외부 스크립트 입장에서 명령·마커·상태
        from .hub_client import HubClient
        check("브리지가 기동돼 있다", window.bridge.running, window.bridge.error)
        with HubClient(port=window.bridge.port) as hub:
            status = hub.status()
            check("브리지 status 에 연결 상태가 나온다",
                  status["roles"].get("SHELL") == "connected", str(status["roles"]))
            reply = hub.command("SHELL", "otcli state")
            check("브리지 경유 명령이 응답을 받는다 (COM 점유 공유)",
                  any("Done" in ln for ln in reply), str(reply))
            hub.marker("bridge marker test")
            spin(app, 0.2)
            check("브리지 마커가 store 에 들어간다",
                  any("bridge marker test" in ln.text
                      for ln in window.session.store.pull(-1, ["MARK"])))
            window._apply_layout("merged")
            spin(app, 0.4)
            check("자동화(브리지) 마커도 병합 뷰에 보인다",
                  "bridge marker test" in window.merged_pane.view.toPlainText(),
                  window.merged_pane.view.toPlainText()[-200:])
            window._apply_layout("split")
            spin(app, 0.2)

        # ---------------------------------------------------------- S6c 창 분리 / 버퍼 지우기 / 레이아웃
        print("\n== S6c. 창 분리 · 버퍼 지우기 · 레이아웃 전환 ==")
        mlog_pane = window.panes["MLOG"]
        window.pop_out_pane(mlog_pane)
        spin(app, 0.4)
        check("콘솔이 별도 창으로 분리된다",
              "MLOG" in window.popped and window.popped["MLOG"].pane is mlog_pane)
        check("분리된 pane 은 본창 컨테이너에 없다",
              mlog_pane.parent() is not window.console_holder
              and mlog_pane.parent() is not None, str(mlog_pane.parent()))
        before_lines = mlog_pane.view.blockCount()
        spin(app, 0.8)
        check("분리 창에서도 수신이 계속된다", mlog_pane.view.blockCount() > before_lines,
              f"{before_lines} -> {mlog_pane.view.blockCount()}")
        check("본창은 남은 콘솔로 재배치된다",
              window.panes["SHELL"].isVisible() and window.panes["UCLI"].isVisible())

        for mode in ("columns", "tabs", "merged", "split"):
            window._apply_layout(mode)
            spin(app, 0.2)
            check(f"분리 중 레이아웃 {mode} 전환에도 분리 창이 pane 을 유지한다",
                  window.popped["MLOG"].pane is mlog_pane and mlog_pane.isVisible())

        window.popped["MLOG"].close()
        spin(app, 0.4)
        check("창을 닫으면 원래 자리로 복귀한다",
              not window.popped and mlog_pane.isVisible()
              and mlog_pane.parent() is not None)
        window.tick()
        spin(app, 0.3)
        check("복귀 후에도 수신이 이어진다", "CASE metric" in mlog_pane.view.toPlainText())

        # 하단(명령 패널)이 레이아웃 전환 후에도 화면 안에 남아야 한다
        window.resize(1280, 800)
        spin(app, 0.3)
        for mode in ("tabs", "columns", "split"):
            window._apply_layout(mode)
            spin(app, 0.25)
            panel_bottom = (window.command_panel.mapTo(window, window.command_panel.rect()
                                                       .bottomLeft()).y())
            check(f"레이아웃 {mode} 후 명령 패널이 창 안에 보인다",
                  window.command_panel.isVisible() and 0 < panel_bottom <= window.height() + 2,
                  f"bottom={panel_bottom} height={window.height()}")

        # ★탭·병합은 splitter 를 만들지 않는다 — 이전 레이아웃의 죽은 splitter 를 그대로
        # 들고 있으면 다음 전환에서 RuntimeError 로 창이 멈춘다. 전 조합을 밟는다.
        modes = ("split", "columns", "tabs", "merged")
        layout_error = ""
        for first in modes:
            for second in modes:
                try:
                    window._apply_layout(first)
                    spin(app, 0.12)      # deleteLater 가 실제로 실행되게 이벤트 루프를 돌린다
                    window._apply_layout(second)
                    spin(app, 0.12)
                    window.tick()
                except RuntimeError as exc:
                    layout_error = f"{first} -> {second}: {exc}"
                    break
            if layout_error:
                break
        check("레이아웃을 어떤 순서로 바꿔도 죽은 splitter 를 만지지 않는다",
              not layout_error, layout_error)

        # 분할 비율은 탭·병합을 거쳐도 살아남아야 한다
        window._apply_layout("split")
        spin(app, 0.2)
        window._splitters[0][1].setSizes([700, 300])
        spin(app, 0.2)
        window._apply_layout("tabs")
        spin(app, 0.2)
        window._apply_layout("split")
        spin(app, 0.3)
        restored = window._splitters[0][1].sizes()
        check("탭을 거쳐도 분할 비율이 복원된다",
              len(restored) == 2 and restored[0] > restored[1], str(restored))

        # 버퍼 지우기 — 화면·ring 은 비고 파일은 남는다
        merged_before = os.path.join(profile.log_base_dir,
                                     f"{window.session.store.session_name}_all.log")
        window.session.store.flush()
        size_before = os.path.getsize(merged_before) if os.path.exists(merged_before) else 0
        dut.paused.set()          # 비운 직후 상태를 보려면 유입을 멈춰야 한다
        spin(app, 0.3)
        window.clear_all_buffers()
        spin(app, 0.2)
        check("버퍼 비우기로 화면이 비워진다",
              window.panes["MLOG"].view.toPlainText().strip() == "",
              window.panes["MLOG"].view.toPlainText()[:80])
        check("버퍼 비우기로 ring 도 비워진다",
              len(window.session.store.pull(-1, ["MLOG"])) <= 1,
              str(len(window.session.store.pull(-1, ["MLOG"]))))
        window.session.store.flush()
        size_after = os.path.getsize(merged_before) if os.path.exists(merged_before) else 0
        check("버퍼를 비워도 로그 파일은 그대로다", size_after >= size_before > 0,
              f"{size_before} -> {size_after}")
        dut.paused.clear()
        check("버퍼 비운 뒤에도 수신이 재개된다",
              wait_for(app, lambda: "CASE metric" in window.panes["MLOG"].view.toPlainText(),
                       timeout=5.0))

        # ---------------------------------------------------------- S6d 규칙 페이지 레이아웃
        print("\n== S6d. 설정 > 규칙 — 카드 겹침 없음 (전체화면 포함) ==")
        rules = window.rules_page
        for size in ((1000, 700), (1920, 1080), (900, 500)):
            window.resize(*size)
            spin(app, 0.3)
            tables = [rules.highlight_table, rules.redact_table,
                      rules.trigger_table, rules.filter_table]
            clipped = [t.objectName() or str(i) for i, t in enumerate(tables)
                       if t.height() < t.horizontalHeader().height() + 8]
            check(f"{size[0]}x{size[1]}: 표가 찌그러지지 않는다", not clipped, str(clipped))
            # 카드끼리 겹치면 앞 카드의 아래끝이 다음 카드 위끝보다 아래에 온다
            cards = [w for w in rules.findChildren(QWidget)
                     if w.objectName() == "card" and w.isVisible()]
            geos = sorted(((c.mapTo(rules, c.rect().topLeft()).y(),
                            c.mapTo(rules, c.rect().bottomLeft()).y()) for c in cards))
            overlap = [(a, b) for (_, a), (b, _) in itertools.pairwise(geos) if a > b + 1]
            check(f"{size[0]}x{size[1]}: 카드가 서로 겹치지 않는다", not overlap, str(overlap[:2]))
        # 룰을 늘려도 행이 잘리지 않는다
        rows_before = rules.trigger_table.rowCount()
        for _ in range(6):
            rules._add_trigger()
        spin(app, 0.3)
        needed = (rules.trigger_table.horizontalHeader().height()
                  + rules.trigger_table.rowCount()
                  * rules.trigger_table.verticalHeader().defaultSectionSize())
        check("룰을 늘리면 표 높이가 따라 커진다 (행 잘림 없음)",
              rules.trigger_table.height() >= min(needed, 300),
              f"h={rules.trigger_table.height()} rows={rules.trigger_table.rowCount()}")
        del profile.trigger_rules[rows_before:]
        rules.reload()
        spin(app, 0.2)

        # ---------------------------------------------------------- S6e 기록 멈춤/재개
        print("\n== S6e. 기록 멈춤 / 재개 / 로그 파일 열기 ==")
        store = window.session.store
        window.toggle_recording_pause()
        spin(app, 0.5)
        check("기록 멈춤 상태가 된다", store.paused)
        check("REC 표시가 멈춤으로 바뀐다", "기록멈춤" in window.rec_button.text(),
              window.rec_button.text())
        store.flush()
        paused_path = store.file_paths()["MLOG"]
        size_at_pause = os.path.getsize(paused_path)
        before_lines = window.panes["MLOG"].view.blockCount()
        spin(app, 1.2)
        check("멈춰도 화면 수신은 계속된다",
              window.panes["MLOG"].view.blockCount() > before_lines)
        store.flush()
        check("멈춘 동안 파일은 커지지 않는다",
              os.path.getsize(paused_path) == size_at_pause,
              f"{size_at_pause} -> {os.path.getsize(paused_path)}")
        window.toggle_recording_pause()
        spin(app, 0.8)
        store.flush()
        check("재개하면 파일이 다시 커진다", os.path.getsize(paused_path) > size_at_pause)
        with open(paused_path, encoding="utf-8", errors="replace") as fh:
            paused_body = fh.read()
        check("멈춤/재개 배너가 포트 파일에 남는다",
              "일시정지" in paused_body and "재개" in paused_body, paused_body[-160:])

        window._rebuild_log_menu()
        actions = [a.text() for a in window.log_menu.actions()]
        check("로그 파일 목록이 크기와 함께 뜬다",
              any("mlog" in a and "KB" in a for a in actions), str(actions))

        # 사용자 시나리오: 멈춤 → 저장 위치 변경 → 재개 → 새 위치에 쌓여야 한다
        print("\n== S6f. 기록 중 로그 위치·이름 변경 ==")
        page = window.connection_page
        window.toggle_recording_pause()          # 멈춤
        spin(app, 0.3)
        new_dir = os.path.join(tmp, "moved_logs")
        log_page = window.log_page                # 로그 설정은 설정 창의 로그 페이지로 옮겼다
        log_page.dir_edit.setText(new_dir)
        log_page.commit()                          # OK 를 누른 것과 같다
        window.retarget_logs()
        spin(app, 0.3)
        check("변경 즉시 REC 경로가 새 위치를 가리킨다",
              new_dir.replace("/", os.sep) in (store.log_dir or ""), str(store.log_dir))
        window.toggle_recording_pause()          # 재개
        check("재개 후 새 위치에 파일이 쌓인다",
              wait_for(app, lambda: os.path.exists(
                  os.path.join(new_dir, os.path.basename(store.file_paths()["MLOG"])))
                  and os.path.getsize(store.file_paths()["MLOG"]) > 0, timeout=6.0),
              str(store.file_paths().get("MLOG")))
        check("옛 위치 파일은 그대로 남는다", os.path.exists(paused_path))

        # 접두어를 바꾸면 파일 이름도 따라간다 + 미리보기가 갱신된다
        log_page.prefix_edit.setText("bench")
        spin(app, 0.2)
        check("접두어 변경이 미리보기에 반영된다", "bench_" in log_page.preview.text(),
              log_page.preview.text())
        log_page.commit()
        window.retarget_logs()
        spin(app, 0.5)
        check("접두어 변경 후 새 파일명으로 기록한다",
              os.path.basename(store.file_paths()["MLOG"]).startswith("bench_"),
              os.path.basename(store.file_paths()["MLOG"]))
        check("새 접두어 파일에도 실제로 쌓인다",
              wait_for(app, lambda: os.path.getsize(store.file_paths()["MLOG"]) > 0, timeout=6.0))

        # 포트별 로그명 지정도 기록 중 반영 (설정 > 로그 페이지에서 OK)
        log_page.port_edits["MLOG"].setText("matter")
        log_page.commit()
        window.retarget_logs()
        spin(app, 0.4)
        check("포트별 로그명이 기록 중에도 반영된다",
              os.path.basename(store.file_paths()["MLOG"]).endswith("_matter.log"),
              os.path.basename(store.file_paths()["MLOG"]))

        # ---------------------------------------------------------- S6g 새 UI 구조
        print("\n== S6g. 탭 제거 · 설정 모달 · 이름 변경 · 히스토리 ==")
        check("메인에 탭 위젯이 없다", not hasattr(window, "tabs"))
        check("액션 바 버튼이 있다 (연결/설정/규칙/로그/프로파일)",
              any("연결" in b.text() for b in window.findChildren(type(window.rec_button))))
        settings = window.settings()
        check("설정 창에 5개 페이지 (연결/규칙/로그/프로파일/일반)", settings.stack.count() == 5,
              str(settings.stack.count()))
        check("일반 페이지에 언어 선택이 있다", settings.general_page.combo.count() >= 2)
        settings.go_to(settings.PAGE_RULES)
        check("규칙 페이지로 이동", settings.stack.currentIndex() == settings.PAGE_RULES)
        check("규칙은 서브트리로 나뉜다", len(settings.rules_page._tree_items) == 4)
        settings.rules_page.show_page(2)
        check("트리 선택이 페이지를 바꾼다", settings.rules_page.pages.currentIndex() == 2)

        # 명령 대상에 전 포트가 뜬다 (장비마다 입력 콘솔이 다르다)
        targets = [window.command_panel.target.itemData(i)
                   for i in range(window.command_panel.target.count())]
        check("명령 대상에 MLOG 도 포함된다", "MLOG" in targets, str(targets))
        window.command_panel.select_role("MLOG")
        ok, _err = window.session.send("MLOG", "ping")
        check("MLOG 로도 명령을 보낼 수 있다", ok)

        # 포트 이름 바꾸기 → 콘솔 제목·프로파일 반영
        card = settings.connection_page.cards["MLOG"]
        card._set_label("MATTER-LOG")
        window.tick()
        spin(app, 0.2)
        check("포트 이름이 프로파일에 저장된다", profile.port("MLOG").label == "MATTER-LOG")
        check("콘솔 제목이 새 이름을 쓴다", window.panes["MLOG"].title == "MATTER-LOG",
              window.panes["MLOG"].title)
        index = window.command_panel.target.findData("MLOG")
        check("명령 대상 표시도 새 이름을 쓴다",
              window.command_panel.target.itemText(index) == "MATTER-LOG",
              window.command_panel.target.itemText(index))
        check("이름을 바꿔도 전송 대상은 role 그대로다",
              window.command_panel.current_role() == "MLOG",
              window.command_panel.current_role())
        card._set_label("")
        window.tick()
        check("이름을 비우면 COM 번호를 쓴다", window.panes["MLOG"].title == VCOM_MLOG,
              window.panes["MLOG"].title)

        # 로그 설정은 OK 전까지 반영되지 않는다 (빈 파일 방지)
        before_dir = profile.log_base_dir
        log_page.dir_edit.setText(os.path.join(tmp, "not_applied"))
        spin(app, 0.2)
        check("로그 설정은 입력만으로 반영되지 않는다", profile.log_base_dir == before_dir)
        log_page.revert()
        check("취소하면 입력이 되돌아간다", log_page.dir_edit.text() == before_dir)

        # 검색·명령 히스토리 드롭다운 — ★슬롯 직접 호출이 아니라 실제 키 이벤트로 검증한다
        from PySide6.QtCore import Qt as _Qt
        dut.paused.set()          # 매치 개수가 흔들리지 않게 유입을 멈춘다
        spin(app, 0.3)
        pane = window.panes["MLOG"]
        pane.focus_search()
        pane.search.edit.setText("CASE")
        pane._run_search()
        spin(app, 0.3)
        first = pane._match_index
        total = len(pane._matches)
        # ★키는 실제 포커스 위젯으로 보낸다. focus_search() 는 lineEdit 이 아니라 콤보에
        # 포커스를 주고, QComboBox 는 키를 lineEdit->event() 로 넘겨 **이벤트 필터를
        # 건너뛴다** — lineEdit 에 직접 보내면 이 경로의 버그가 안 잡힌다.
        # offscreen 에서는 창이 활성화되지 않아 focusWidget() 이 None 일 수 있다 —
        # 전달 경로 두 가지(콤보 / lineEdit)를 위젯을 직접 지정해 각각 확인한다.
        focused = app.focusWidget()
        if focused is not None:
            check("Ctrl+F 포커스는 콤보 자체다 (필터가 아니라 keyPressEvent 경로)",
                  focused is pane.search.edit, str(type(focused).__name__))
        search_focus = pane.search.edit
        send_key(app, search_focus, _Qt.Key_Return, "\r")
        spin(app, 0.15)
        second = pane._match_index
        send_key(app, search_focus, _Qt.Key_Return, "\r")
        spin(app, 0.15)
        third = pane._match_index
        check("검색창에서 Enter 로 다음 매치로 간다", total > 3 and second != first,
              f"total={total} {first}->{second}")
        check("Enter 한 번에 한 칸씩만 이동한다 (중복 발생 없음)",
              total > 3 and (second - first) % total == 1 and (third - second) % total == 1,
              f"{first}->{second}->{third} (total={total})")
        # 마우스로 눌러 편집 중(=lineEdit 포커스)인 경로도 같이 확인
        pane.search.edit.lineEdit().setFocus()
        spin(app, 0.1)
        fourth_before = pane._match_index
        send_key(app, pane.search.edit.lineEdit(), _Qt.Key_Return, "\r")
        spin(app, 0.15)
        check("lineEdit 에 포커스가 있어도 Enter 가 한 칸 이동한다",
              total > 3 and (pane._match_index - fourth_before) % total == 1,
              f"{fourth_before}->{pane._match_index}")
        check("검색어가 프로파일에 남는다", "CASE" in profile.search_history.get("console", []))
        check("검색 드롭다운에 최근 검색어가 뜬다",
              pane.search.edit.count() > 0 and pane.search.edit.itemText(0) == "CASE")
        pane.close_search()

        # 명령 히스토리 — ↑/↓ 로 지난 명령이 실제로 올라와야 한다
        window.command_panel.select_role("SHELL")
        spin(app, 0.15)
        edit = window.command_panel.edit
        sent = list(profile.command_history.get("SHELL", []))
        check("명령 드롭다운에 히스토리가 뜬다", edit.count() > 0, str(edit.count()))
        edit.setText("")
        window.command_panel._history_pos.pop("SHELL", None)
        window.command_panel.focus_input()     # ★Ctrl+` 와 같은 경로 (포커스 = 콤보)
        spin(app, 0.1)
        focused = app.focusWidget()
        if focused is not None:
            check("Ctrl+` 포커스도 콤보 자체다", focused is edit, str(type(focused).__name__))
        cmd_focus = edit                       # 콤보로 직접 보낸다 (= 실기 전달 경로)
        edit.setText("")
        send_key(app, cmd_focus, _Qt.Key_Up)
        check("↑ 로 마지막 명령이 올라온다", bool(sent) and edit.text() == sent[-1],
              f"{edit.text()!r} vs {sent[-1:]!r}")
        if len(sent) > 1:
            send_key(app, cmd_focus, _Qt.Key_Up)
            check("↑ 를 더 누르면 그 앞 명령", edit.text() == sent[-2],
                  f"{edit.text()!r} vs {sent[-2]!r}")
            send_key(app, cmd_focus, _Qt.Key_Down)
            check("↓ 로 다시 최근 명령", edit.text() == sent[-1],
                  f"{edit.text()!r} vs {sent[-1]!r}")

        # 명령 전송도 Enter 로 — 콤보 포커스 / lineEdit 포커스 양쪽 다
        before_tx = len(dut.shell_cmds)
        edit.setText("otcli state")
        send_key(app, cmd_focus, _Qt.Key_Return, "\r")
        spin(app, 0.5)
        check("콤보에 포커스가 있어도 Enter 로 명령이 나간다",
              len(dut.shell_cmds) == before_tx + 1,
              f"{before_tx} -> {len(dut.shell_cmds)}")
        before_tx = len(dut.shell_cmds)
        edit.lineEdit().setFocus()
        spin(app, 0.1)
        edit.setText("wifi status")
        send_key(app, edit.lineEdit(), _Qt.Key_Return, "\r")
        spin(app, 0.5)
        check("lineEdit 에 포커스가 있어도 Enter 로 명령이 나간다",
              len(dut.shell_cmds) == before_tx + 1,
              f"{before_tx} -> {len(dut.shell_cmds)}")
        edit.setText("")
        dut.paused.clear()

        # Enter 로 자동 스크롤 복귀 — 본문에 포커스가 있을 때만
        pane.lock_button.setChecked(True)
        check("스크롤 잠금 상태", pane.scroll_lock)
        send_key(app, pane.view, _Qt.Key_Return, "\r")
        check("Enter 로 자동 스크롤이 풀린다", not pane.scroll_lock)

        # ------------------------------------------------- S6h 콘솔 수 (1/2/3 UART 모델)
        print("\n== S6h. 콘솔 수 — UART 1개·2개 모델 ==")
        conn = settings.connection_page
        log_page_ports = settings.log_page

        conn._set_count(1)                       # UART 1개짜리 모델
        window.tick()
        spin(app, 0.3)
        check("1개로 줄이면 활성 포트가 하나다", profile.active_roles() == ["MLOG"],
              str(profile.active_roles()))
        check("안 쓰는 콘솔은 화면에서 빠진다",
              not window.panes["SHELL"].isVisible() and not window.panes["UCLI"].isVisible())
        check("쓰는 콘솔은 그대로 보인다", window.panes["MLOG"].isVisible())
        check("안 쓰는 포트의 상태 필도 숨는다",
              not window.pills["SHELL"].isVisible() and window.pills["MLOG"].isVisible())
        targets = [window.command_panel.target.itemData(i)
                   for i in range(window.command_panel.target.count())]
        check("명령 대상도 쓰는 포트만", targets == ["MLOG"], str(targets))
        check("안 쓰는 포트는 연결이 끊긴다", not window.session.is_connected("SHELL"))
        check("로그 설정에서도 안 쓰는 파일명 칸이 숨는다",
              not log_page_ports.port_edits["SHELL"].isVisible())
        check("1개 모드에서도 tick 이 예외 없이 돈다", window.tick() is None)

        conn._set_count(2)                       # UART 2개짜리 모델
        window.tick()
        spin(app, 0.3)
        check("2개로 늘리면 두 개가 활성", profile.active_roles() == ["MLOG", "SHELL"],
              str(profile.active_roles()))
        check("다시 켠 콘솔이 화면에 돌아온다", window.panes["SHELL"].isVisible())
        check("세 번째 콘솔은 여전히 숨김", not window.panes["UCLI"].isVisible())
        check("다시 켜도 이전 스크롤백이 남아 있다",
              "CASE metric" in window.panes["MLOG"].view.toPlainText())

        # 개별 체크박스로도 (앞에서부터가 아닌 조합)
        conn.cards["SHELL"].use_box.setChecked(False)
        conn.cards["UCLI"].use_box.setChecked(True)
        window.tick()
        spin(app, 0.3)
        check("체크박스로 임의 조합도 된다", profile.active_roles() == ["MLOG", "UCLI"],
              str(profile.active_roles()))
        conn.cards["MLOG"].use_box.setChecked(False)
        conn.cards["UCLI"].use_box.setChecked(False)
        window.tick()
        check("전부 끄면 하나는 남는다", len(profile.active_roles()) >= 1,
              str(profile.active_roles()))

        conn._set_count(3)                       # 원래대로 (뒤 시나리오가 3콘솔을 쓴다)
        window.tick()
        spin(app, 0.4)
        check("3개로 되돌리면 전부 복귀", profile.active_roles() == ["MLOG", "SHELL", "UCLI"],
              str(profile.active_roles()))
        # 껐던 포트는 연결도 끊겼다 — 뒤 시나리오를 위해 되살린다 (실기에서도 [전체 연결])
        for role in ("MLOG", "SHELL", "UCLI"):
            if not window.session.is_connected(role):
                window.session.connect(role)
        check("다시 켠 뒤 [전체 연결] 로 수신이 이어진다",
              wait_for(app, lambda: all(window.session.is_connected(r)
                                        for r in ("MLOG", "SHELL", "UCLI")), timeout=8.0))
        spin(app, 0.6)

        # ---------------------------------------------------------- S7 재부팅 생존
        print("\n== S7. UCLI reboot — 단절·자동 재접속·부팅 배너 캡처 ==")
        panel.select_role("UCLI")
        panel.edit.setText("reboot")
        panel.send_current()
        check("단절이 배너로 보인다",
              wait_for(app, lambda: "read error" in window.panes["UCLI"].view.toPlainText(),
                       timeout=6.0))
        check("자동 재접속된다",
              wait_for(app, lambda: "!! reopened" in window.panes["UCLI"].view.toPlainText(),
                       timeout=8.0))
        check("부팅 배너 첫 줄부터 캡처된다",
              wait_for(app, lambda: "-- BOOT --" in window.panes["UCLI"].view.toPlainText(),
                       timeout=4.0))
        check("재접속 후 상태 필이 Connected 로 돌아온다",
              wait_for(app, lambda: window.session.is_connected("UCLI")))

        # ---------------------------------------------------------- S8 firehose
        print("\n== S8. firehose 부하 — UI 생존·파일 무손실 ==")
        # 전송 중인 라인이 스냅샷 경계에 걸리지 않도록 멈춘 상태에서 양쪽을 잰다
        dut.paused.set()
        spin(app, 0.4)
        before = dut.mlog_count
        before_count = window.session.store.counters().get("MLOG", 0)
        window.session.store.flush()
        mlog_file = window.session.store.file_paths()["MLOG"]
        file_lines_before = (sum(1 for _ in open(mlog_file, encoding="utf-8", errors="replace"))
                             if os.path.exists(mlog_file) else 0)
        dut.paused.clear()
        dut.mlog_rate = 1500
        started = time.monotonic()
        ticks = 0

        def count_tick():
            nonlocal ticks
            ticks += 1
        window.timer.timeout.connect(count_tick)
        spin(app, 3.0)
        dut.paused.set()          # 방출을 멈춘 뒤에 세야 두 카운트의 시점이 같다
        spin(app, 0.2)
        dut.mlog_rate = 20
        elapsed = time.monotonic() - started
        emitted = dut.mlog_count - before
        check(f"부하 중에도 tick 이 돈다 ({ticks}회/{elapsed:.1f}s)", ticks >= 30, str(ticks))
        # 가상 콘솔은 무손실이므로 슬랙을 두지 않는다 — 큐가 완전히 빌 때까지 기다린 뒤 등호 비교
        wait_for(app, lambda: not dut.live[VCOM_MLOG].buf, timeout=10.0)
        spin(app, 1.0)
        counters = window.session.store.counters()
        received = counters.get("MLOG", 0) - before_count
        check(f"수신 라인 = 방출 라인 (방출 {emitted}, 수신 {received})",
              received == emitted, f"차이 {emitted - received}")
        window.session.store.flush()
        # 세션 도중 파일을 갈아끼웠을 수 있으니 누적이 아니라 이 구간의 증분으로 본다
        if os.path.exists(mlog_file):
            with open(mlog_file, encoding="utf-8", errors="replace") as fh:
                file_lines_after = sum(1 for _ in fh)
            written = file_lines_after - file_lines_before
            check(f"파일에 기록된 줄이 수신량 이상 (증분 {written})",
                  written >= received, f"파일 증분 {written} < 수신 {received}")
        dut.paused.clear()

        # ------------------------------------------------- S8b 덮어쓰기 확인 · 날짜 폴더
        print("\n== S8b. 같은 이름 파일 존재 시 — 덮어쓰기/이어쓰기/취소 ==")
        from PySide6.QtWidgets import QDialog
        from .ui.log_start_dialog import LogStartDialog

        window.stop_logging()
        spin(app, 0.3)
        over_dir = os.path.join(tmp, "overwrite_check")
        log_page.dir_edit.setText(over_dir)
        log_page.include_box.setChecked(False)       # 고정 파일명 = 충돌이 가장 잘 나는 설정
        log_page.date_folder_box.setChecked(False)
        log_page.port_edits["MLOG"].setText("fixed")
        log_page.commit()
        os.makedirs(over_dir, exist_ok=True)
        fixed_path = os.path.join(over_dir, "fixed.log")
        with open(fixed_path, "w", encoding="utf-8") as fh:
            fh.write("OLD LINE\n")

        original_start_exec = LogStartDialog.exec
        LogStartDialog.exec = lambda _self: QDialog.Accepted   # 시작 확인 창은 자동 통과
        asked: list[list[str]] = []

        def choose(answer: str):
            def _choose(existing: list[str]) -> str:
                asked.append(list(existing))
                return answer
            return _choose

        try:
            window._ask_overwrite = choose("cancel")
            started = window.start_logging()
            check("[취소] 를 고르면 기록을 시작하지 않는다", not started and not store.recording)
            check("모달에 기존 파일 목록이 전달된다",
                  bool(asked) and any(p.endswith("fixed.log") for p in asked[-1]), str(asked))

            window._ask_overwrite = choose("append")
            started = window.start_logging()
            check("[이어쓰기] 를 고르면 기록이 시작된다", started and store.recording)
            store.append("MLOG", "appended by uitest")
            store.flush()
            with open(fixed_path, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            check("이어쓰기는 기존 내용을 보존한다",
                  "OLD LINE" in body and "appended by uitest" in body, body[:120])
            window.stop_logging()

            window._ask_overwrite = choose("overwrite")
            started = window.start_logging()
            check("[덮어쓰기] 를 고르면 기록이 시작된다", started and store.recording)
            store.append("MLOG", "fresh by uitest")
            store.flush()
            with open(fixed_path, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            check("덮어쓴 파일에는 옛 내용이 없다",
                  "OLD LINE" not in body and "fresh by uitest" in body, body[:120])
            window.stop_logging()

            def never_ask(_existing: list[str]) -> str:
                raise AssertionError("ask=False 경로에서 덮어쓰기 모달이 호출됐다")

            window._ask_overwrite = never_ask
            started = window.start_logging(ask=False)   # 자동화/브리지 경로는 조용히 이어쓴다
            check("ask=False 는 모달 없이 이어쓴다", started and store.recording)
            store.append("MLOG", "auto append")
            store.flush()
            with open(fixed_path, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            check("ask=False 도 기존 내용을 보존한다",
                  "fresh by uitest" in body and "auto append" in body, body[:160])
        finally:
            LogStartDialog.exec = original_start_exec
            if "_ask_overwrite" in window.__dict__:
                del window._ask_overwrite            # 인스턴스 속성을 걷어 원래 메서드로 복귀

        # 날짜 폴더 옵션을 켜면 (기록 중 retarget 포함) MMDD 아래로 들어간다
        log_page.date_folder_box.setChecked(True)
        log_page.commit()
        window.retarget_logs()
        spin(app, 0.3)
        day = time.strftime("%m%d")
        check("날짜 폴더를 켜면 MMDD 아래에 기록한다",
              os.path.normpath(store.log_dir or "") == os.path.normpath(os.path.join(over_dir, day)),
              str(store.log_dir))
        store.append("MLOG", "dated line")
        store.flush()
        check("날짜 폴더에 파일이 실제로 생긴다",
              os.path.exists(os.path.join(over_dir, day, "fixed.log")),
              str(os.listdir(over_dir)))

        # ------------------------------------------------- S8c 로그 뷰어 (과거 파일 분석)
        print("\n== S8c. 로그 뷰어 — 기록한 파일 다시 열기 ==")
        store.flush()
        dock = window.open_log_viewer([fixed_path])
        spin(app, 0.4)
        check("뷰어 도크가 열린다", dock is not None and dock in window.viewer_docks)
        vtext = dock.viewer.pane.view.toPlainText()
        check("기록했던 내용이 뷰어에 보인다", "fresh by uitest" in vtext, vtext[:200])
        dock.viewer.edit.setText("auto append")
        dock.viewer._refresh_timer.stop()
        dock.viewer._refresh_pane()
        spin(app, 0.2)
        vtext = dock.viewer.pane.view.toPlainText()
        check("뷰어 필터가 동작한다",
              "auto append" in vtext and "fresh by uitest" not in vtext, vtext[:200])
        dock.setFloating(True)
        check("도크는 떼어내 독립 창이 된다 (플로팅)", dock.isFloating())
        dock.close()
        spin(app, 0.3)
        check("도크를 닫으면 목록에서 빠진다", dock not in window.viewer_docks)

        # ------------------------------------------------- S8d 내장 터미널 (ConPTY)
        print("\n== S8d. 내장 터미널 — ConPTY PowerShell ==")
        from .core.terminal import TERMINAL_AVAILABLE
        if not TERMINAL_AVAILABLE:
            print("  [SKIP] pywinpty/pyte 미설치 — 터미널 시나리오 생략")
        else:
            tdock = window.open_terminal()
            check("터미널 도크가 열린다", tdock is not None and tdock in window.terminal_docks)
            tsession = tdock.pane.session
            check("셸이 기동한다", wait_for(app, lambda: tsession.alive, timeout=20.0))
            spin(app, 1.5)   # PowerShell 프롬프트가 뜰 시간
            for ch in "echo serialhub-term-check":
                key = ord(ch.upper()) if ch.isalnum() else _Qt.Key_Minus if ch == "-" else _Qt.Key_Space
                send_key(app, tdock.pane, key, ch)
            send_key(app, tdock.pane, _Qt.Key_Return, "\r")
            check("타이핑이 셸을 왕복해 화면 버퍼에 온다",
                  wait_for(app, lambda: "serialhub-term-check" in tsession.buffer.text(),
                           timeout=20.0),
                  tsession.buffer.text()[-300:])
            tdock.close()
            spin(app, 0.4)
            check("터미널 도크를 닫으면 목록에서 빠진다", tdock not in window.terminal_docks)
            check("도크를 닫으면 셸 프로세스도 끝난다",
                  wait_for(app, lambda: not tsession.alive, timeout=8.0))

        # ---------------------------------------------------------- S9 종료·파일 검증
        print("\n== S9. 종료 — 로그 파일·진단 로그 ==")
        # 경로를 재구성하지 말고 store 가 실제로 쓰고 있는 경로를 쓴다
        # (S6f 에서 위치·이름을 바꿨으므로 프로파일 값으로 조립하면 어긋난다)
        from .core.logstore import MERGED_KEY
        window.session.store.flush()
        merged = window.session.store.file_paths().get(MERGED_KEY, "")
        window.close()
        spin(app, 0.3)
        check("병합 로그가 남는다", os.path.exists(merged), merged)
        # 위치를 옮긴 뒤의 파일은 새 폴더에, 그 전 기록은 옛 폴더에 있어야 한다.
        # 두 폴더를 통틀어 내용이 보존됐는지 확인한다.
        all_bodies = ""
        for root, _dirs, files in os.walk(tmp):
            for name in files:
                if name.endswith("_all.log"):
                    with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                        all_bodies += fh.read()
        check("병합 로그에 TX 에코가 있다", ">>> otcli state" in all_bodies)
        check("병합 로그에도 PSK 원문이 없다", "hunter2pass" not in all_bodies)
        check("병합 로그에 부팅 배너가 있다", "-- BOOT --" in all_bodies)
        check("병합 로그에 브리지 마커가 있다", "bridge marker test" in all_bodies)
        check("분절 전 파일도 그대로 남아 있다",
              any(f.startswith(first_session) for _r, _d, fs in os.walk(tmp) for f in fs),
              first_session)
        check("분절 전 파일에 수동 마커가 있다", "T1 cycle start" in all_bodies)
        app_log = os.path.join(config_mod.DATA_DIR, "app.log")
        check("진단 로그(app.log)가 남는다", os.path.exists(app_log), app_log)
        if os.path.exists(app_log):
            diag_body = open(app_log, encoding="utf-8", errors="replace").read()
            check("진단 로그에 연결/재접속/probe 흔적이 있다",
                  "connect_all" in diag_body and "reopened" in diag_body and "probe" in diag_body,
                  diag_body[-300:])

        check("Qt 슬롯에서 삼켜진 예외 없음", not slot_errors, "; ".join(slot_errors[:3]))
    finally:
        sys.excepthook = original_hook
        dut.stop()
        portscan.open_serial = original_open
        portscan.list_ports = original_list
        diag_mod.diag.reconfigure()  # 임시 폴더 핸들을 놓아줘야 지울 수 있다
        if not FAILED:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)  # 실패 시엔 조사용으로 남긴다

    print(f"\n=== {len(PASSED)} passed, {len(FAILED)} failed ===")
    for failure in FAILED:
        print(f"  FAIL: {failure}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
