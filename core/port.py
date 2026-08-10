"""PortReader — 포트 1개의 수신 스레드 · 자동 재접속 · 송신.

`scripts/run_srp_suite.py` 의 검증된 Port 클래스(2초 간격 재오픈, `!!` 배너,
LF 분리 + CR 제거)를 승격한 것이다. Qt 를 모른다 — UI 는 state 를 폴링한다.
"""

from __future__ import annotations

import threading
import time

from . import portscan
from .diag import diag
from .logstore import LogStore
from .i18n import tr

STATE_DISCONNECTED = "disconnected"
STATE_CONNECTED = "connected"
STATE_RECONNECTING = "reconnecting"

PARTIAL_MARK = " <partial>"
_PARTIAL_IDLE = 0.25  # 개행 없는 프롬프트(`> `)를 이 시간 뒤 한 줄로 흘려보낸다
# 부분 flush 로 잘라 보낸 직전 조각. 다음 조각이 붙어 완성되면 합친 문자열에 redact 를
# 다시 걸어, 비밀값이 라인 경계로 쪼개져 마스킹을 빠져나가는 경로를 막는다.
_REJOIN_WINDOW = 2.0


class PortReader:
    def __init__(self, role: str, com: str, baud: int, store: LogStore,
                 reconnect_interval: float = 2.0):
        self.role = role
        self.com = com
        self.baud = baud
        self.store = store
        self.reconnect_interval = reconnect_interval

        self.state = STATE_DISCONNECTED
        self.last_error: str = ""
        self.connected_at: float = 0.0

        self._ser = None
        self._partial_tail = ""   # 부분 flush 한 직전 조각 (경계 걸친 비밀값 재판정용)
        self._partial_at = 0.0
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ 수명

    def start(self) -> tuple[bool, str]:
        """최초 연결은 동기 시도한다 — 실패 사유(점유 등)를 사용자에게 바로 보여주기 위함.

        연결된 뒤의 끊김만 자동 재접속 루프로 처리한다 (설계 §7).
        """
        if self._thread is not None and self._thread.is_alive():
            return True, ""
        self.store.register_port(self.role)
        self._stop.clear()
        try:
            self._ser = portscan.open_serial(self.com, self.baud, timeout=0.05)
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self.state = STATE_DISCONNECTED
            diag.warn("port", f"{self.role} open 실패 {self.com}@{self.baud}: {exc}")
            return False, self.last_error

        self.last_error = ""
        self.state = STATE_CONNECTED
        diag.info("port", f"{self.role} open {self.com}@{self.baud}")
        self.connected_at = time.time()
        self._thread = threading.Thread(target=self._run, name=f"reader-{self.role}", daemon=True)
        self._thread.start()
        return True, ""

    def stop(self, join_timeout: float = 2.0) -> bool:
        """반환값 False = 스레드가 시간 안에 안 죽었다.

        그 경우 `_thread` 를 비우면 안 된다 — 죽지 않은 스레드가 재접속 루프에서
        새 핸들을 잡아 COM 을 영구 점유하는데, 호출자는 같은 role 에 reader 를
        하나 더 띄워 라인이 두 번 들어오게 된다.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                self.last_error = tr('수신 스레드가 종료되지 않음 — 포트를 계속 점유할 수 있습니다')
                diag.error("port", f"{self.role} stop 실패 — reader 스레드 미종료 ({self.com})")
                self._close_serial()
                return False
        self._thread = None
        self._close_serial()
        self.state = STATE_DISCONNECTED
        return True

    def _close_serial(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ 수신

    def _run(self) -> None:
        pending = b""
        last_data = time.monotonic()
        while not self._stop.is_set():
            ser = self._ser
            if ser is None:
                self._reconnect()
                pending = b""
                continue
            try:
                data = ser.read(4096)
            except Exception as exc:  # noqa: BLE001
                if pending:
                    # 끊기기 직전에 받은 마지막 줄을 버리지 않는다 — 크래시 직전 로그가 그 줄이다
                    self.store.append(
                        self.role, pending.rstrip(b"\r").decode("utf-8", "replace") + PARTIAL_MARK)
                    pending = b""
                if self._stop.is_set():
                    return  # stop() 이 핸들을 닫아서 난 예외 — 재접속 배너를 남기지 않는다
                self.store.append(self.role, f"!! read error ({str(exc)[:60]}) — reopening")
                diag.warn("port", f"{self.role} read error ({exc}) — 재접속 루프 진입")
                self.last_error = str(exc)
                self._close_serial()
                self.state = STATE_RECONNECTING
                pending = b""
                self._reconnect()
                continue

            if data:
                pending += data
                last_data = time.monotonic()
                while b"\n" in pending:
                    raw, pending = pending.split(b"\n", 1)
                    self._emit(raw.rstrip(b"\r").decode("utf-8", "replace"))
            elif pending and (time.monotonic() - last_data) >= _PARTIAL_IDLE:
                # 개행이 안 오는 프롬프트도 화면에 보여야 CLI 로 쓸 수 있다
                text = pending.rstrip(b"\r").decode("utf-8", "replace")
                pending = b""
                self._partial_tail = text
                self._partial_at = time.monotonic()
                self.store.append(self.role, text + PARTIAL_MARK)

    def _emit(self, text: str) -> None:
        """직전에 부분 flush 한 조각이 있으면 합쳐서 redact 를 다시 판정한다.

        비밀값이 라인 경계로 쪼개지면 어떤 룰도 매치하지 못해 평문이 남는다.
        합친 문자열이 마스킹되면(=경계에 비밀값이 걸쳐 있었다) 뒷조각을 그대로 쓰지 않고
        마스킹된 꼬리만 기록한다. 앞조각은 이미 파일에 갔으므로 완벽히 되돌릴 수는 없지만,
        값의 나머지 절반이 평문으로 남는 것은 막는다.
        """
        tail = self._partial_tail
        if tail and (time.monotonic() - self._partial_at) <= _REJOIN_WINDOW:
            self._partial_tail = ""
            joined = tail + text
            redactor = getattr(self.store, "_redactor", None)
            if redactor is not None:
                masked = redactor.apply(joined)
                if masked != joined:
                    self.store.append(self.role, tr('!! (앞 조각과 합쳐 재판정: 비밀값 마스킹)'))
                    self.store.append(self.role, masked[len(tail):] if len(masked) > len(tail)
                                      else masked)
                    return
        self._partial_tail = ""
        self.store.append(self.role, text)

    def _reconnect(self) -> None:
        """연결이 살아 있다가 끊긴 경우에만 돈다. stop() 이 걸리면 즉시 빠진다."""
        self.state = STATE_RECONNECTING
        while not self._stop.is_set():
            if self._stop.wait(self.reconnect_interval):
                return
            try:
                handle = portscan.open_serial(self.com, self.baud, timeout=0.05)
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                continue
            if self._stop.is_set():
                # 여는 사이에 stop() 이 걸렸다 — 핸들을 넘기면 포트를 계속 물고 있게 된다
                try:
                    handle.close()
                except Exception:  # noqa: BLE001
                    pass
                return
            self._ser = handle
            self.store.append(self.role, "!! reopened")
            diag.info("port", f"{self.role} reopened {self.com}")
            self.last_error = ""
            self.state = STATE_CONNECTED
            self.connected_at = time.time()
            return

    # ------------------------------------------------------------------ 송신

    def send(self, text: str, echo: bool = True) -> tuple[bool, str]:
        """시리얼에는 원문을, 로그에는 redact 적용본을 남긴다 (LogStore.append 가 적용)."""
        ser = self._ser
        if ser is None or self.state != STATE_CONNECTED:
            return False, tr('{0} 미연결 — 전송하지 않음').format(self.role)
        try:
            with self._write_lock:
                ser.write(text.encode("utf-8", "replace") + b"\r\n")
                ser.flush()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            return False, str(exc)
        if echo:
            self.store.append(self.role, text, is_tx=True)
        return True, ""

    # ------------------------------------------------------------------ probe

    def probe(self, token: str = portscan.DEFAULT_PROBE_TOKEN,
              patterns: dict[str, str] | None = None,
              passive_seconds: float = 2.0,
              response_timeout: float = 2.5) -> portscan.ProbeResult:
        """이미 연결된 포트를 대상으로 한 probe — 열려 있는 reader 를 통해 주고받는다.

        무해 토큰만 보내므로 오배정된 포트에서도 부수 효과가 없다 (설계 §5-7).
        백그라운드 스레드에서 호출할 것 (sleep 을 포함한다).
        """
        result = portscan.ProbeResult(com=self.com)
        if self.state != STATE_CONNECTED:
            result.detail = tr('{0} 미연결 — probe 불가').format(self.role)
            result.error = "not connected"
            return result

        seq0 = self.store.last_seq()
        time.sleep(passive_seconds)
        result.passive_lines = len(self.store.pull(seq0, [self.role]))

        seq1 = self.store.last_seq()
        ok, err = self.send(token)
        if not ok:
            result.detail = tr('probe 전송 실패: {0}').format(err[:70])
            result.error = err
            return result

        deadline = time.monotonic() + response_timeout
        text = ""
        while time.monotonic() < deadline:
            lines = [ln for ln in self.store.pull(seq1, [self.role]) if not ln.is_tx]
            text = "\n".join(ln.text for ln in lines)
            verdict, evidence = portscan.classify_probe_text(text, token, patterns)
            if verdict != portscan.VERDICT_UNKNOWN:
                result.verdict = verdict
                result.ok = True
                result.detail = tr('{0} 판정 — 응답 `{1}`').format(verdict, evidence)
                result.tail = text[-400:]
                diag.info("probe", f"{self.role}({self.com}) -> {verdict} (`{evidence}`)")
                return result
            time.sleep(0.05)
        diag.info("probe", f"{self.role}({self.com}) -> "
                           f"{'MLOG' if result.passive_lines else '미확정'} "
                           f"passive={result.passive_lines}")

        result.tail = text[-400:]
        if token in text:
            # 에코가 있으면 입력 콘솔이다 — 서명 미매치를 MLOG 로 확정하지 않는다
            result.detail = (tr('미확정 — 명령을 되찍었는데(입력 콘솔) 알려진 서명이 아닙니다. 프로파일의 '
                                'probe 패턴을 확인하세요'))
        elif result.passive_lines > 0:
            # 토큰 전송 전의 자발 트래픽만 로그 포트의 근거가 된다 (portscan.probe_port 와 동일 규칙)
            result.verdict = portscan.ROLE_MLOG
            result.ok = True
            result.detail = (tr('{0} 판정 — 명령 응답 없음, 자발 트래픽 {1}줄')
                .format(portscan.ROLE_MLOG, result.passive_lines))
        else:
            result.detail = (tr('미확정 — 알려진 응답 서명이 없습니다. 서명이 바뀌었을 수 있으니 프로파일의 '
                                'probe 패턴을 확인하세요'))
        return result
