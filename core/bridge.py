"""로컬 자동화 브리지 — hub 가 COM 을 쥔 채 외부 스크립트에 문을 열어준다 (GAP-2).

COM 은 단일 점유라 hub 실행 중엔 serport.py / sercmd.py / run_*.py / otcli_dut.py 가
전부 막힌다. 이 브리지는 127.0.0.1 전용 TCP 로 그 통로를 대신한다 — 외부 스크립트는
포트를 직접 열지 않고 hub 를 거쳐 명령을 보내고 응답 라인을 당겨간다.

프로토콜: JSON Lines (요청 1줄 → 응답 1줄, UTF-8)
  {"op":"status"}                                → {"ok":true,"roles":{...},"session":..,"seq":..}
  {"op":"send","role":"SHELL","text":"otcli state"} → {"ok":true,"seq":123}
  {"op":"pull","role":"SHELL","after":123,"max":500,"wait_ms":2000}
      → {"ok":true,"last":140,"lines":[{"seq":..,"t":..,"port":..,"text":..,"tx":..}]}
      (role 생략 = 전 포트. wait_ms 동안 새 라인을 기다렸다가 반환 — 폴링 낭비 제거)
  {"op":"marker","text":"### T1 start"}          → {"ok":true}

클라이언트 헬퍼: hub_client.py
"""

from __future__ import annotations

import json
import socket
import socketserver
import threading
import time

from .diag import diag

DEFAULT_BRIDGE_PORT = 3341  # otcli-bridge(3340) 이웃 — 사내 관례 유지
MAX_PULL = 2_000
MAX_WAIT_MS = 10_000
MAX_LINE_BYTES = 64 * 1024


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server: BridgeServer = self.server  # type: ignore[assignment]
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        diag.info("bridge", f"client 접속 {peer}")
        try:
            while True:
                raw = self.rfile.readline(MAX_LINE_BYTES)
                if not raw:
                    return
                try:
                    request = json.loads(raw.decode("utf-8", "replace"))
                    response = server.dispatch(request)
                except Exception as exc:  # noqa: BLE001 - 요청 하나가 깨져도 연결은 유지
                    response = {"ok": False, "err": f"bad request: {str(exc)[:80]}"}
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")
        except (ConnectionError, OSError):
            pass
        finally:
            diag.info("bridge", f"client 종료 {peer}")


class _ExclusiveTCPServer(socketserver.ThreadingTCPServer):
    """포트를 독점 점유한다 — 이미 떠 있는 인스턴스가 있으면 bind 가 실패해야 한다."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:  # Windows 전용 — 다른 프로세스의 재바인드를 막는다
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            except OSError:
                pass
        super().server_bind()


class BridgeServer:
    """세션당 1개. 127.0.0.1 에만 바인드한다 — 외부 노출 금지."""

    def __init__(self, session, port: int = DEFAULT_BRIDGE_PORT):
        self.session = session
        self.port = port
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self.error: str = ""

    # ------------------------------------------------------------------ 수명

    def start(self) -> bool:
        if self._server is not None:
            return True
        try:
            # ★allow_reuse_address(SO_REUSEADDR)를 켜면 Windows 에서는 **이미 listen 중인
            # 포트에도 bind 가 성공**한다. 그러면 두 번째 hub 의 자동화 명령이 남의 세션
            # (다른 DUT)으로 흘러간다. 점유 충돌은 반드시 OSError 로 받아야 한다.
            server = _ExclusiveTCPServer(("127.0.0.1", self.port), _Handler)
            server.daemon_threads = True
            server.dispatch = self.dispatch  # type: ignore[attr-defined]
        except OSError as exc:
            # 다른 hub 인스턴스가 이미 물고 있는 경우 — 죽지 말고 알리기만 한다
            self.error = str(exc)
            diag.warn("bridge", f"포트 {self.port} 바인드 실패: {exc}")
            return False
        self._server = server
        self.port = server.server_address[1]  # port=0 이면 실제 배정된 포트로 갱신
        self._thread = threading.Thread(target=server.serve_forever, name="bridge",
                                        daemon=True)
        self._thread.start()
        self.error = ""
        diag.info("bridge", f"listening 127.0.0.1:{self.port}")
        return True

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:  # noqa: BLE001
                pass
            diag.info("bridge", "stopped")

    @property
    def running(self) -> bool:
        return self._server is not None

    # ------------------------------------------------------------------ 처리

    def dispatch(self, request: dict) -> dict:
        op = str(request.get("op", ""))
        if op == "status":
            return self._op_status()
        if op == "send":
            return self._op_send(request)
        if op == "pull":
            return self._op_pull(request)
        if op == "marker":
            text = str(request.get("text", "")).strip()
            if not text:
                return {"ok": False, "err": "text required"}
            line = self.session.store.marker(text)
            return {"ok": True, "seq": line.seq}
        return {"ok": False, "err": f"unknown op {op!r}"}

    def _op_status(self) -> dict:
        session = self.session
        return {
            "ok": True,
            "roles": {r: session.state_of(r) for r in session.profile.roles()},
            "session": session.store.session_name,
            "recording": session.store.recording,
            "seq": session.store.last_seq(),
            "counters": session.store.counters(),
        }

    def _op_send(self, request: dict) -> dict:
        role = str(request.get("role", ""))
        text = str(request.get("text", ""))
        if not role or not text:
            return {"ok": False, "err": "role/text required"}
        ok, err = self.session.send(role, text)
        if not ok:
            return {"ok": False, "err": err}
        return {"ok": True, "seq": self.session.store.last_seq()}

    def _op_pull(self, request: dict) -> dict:
        store = self.session.store
        role = request.get("role")
        ports = [str(role)] if role else None
        after = int(request.get("after", -1))
        limit = min(MAX_PULL, int(request.get("max", 500)))
        wait_ms = min(MAX_WAIT_MS, int(request.get("wait_ms", 0)))

        deadline = time.monotonic() + wait_ms / 1000.0
        lines = store.pull(after, ports, limit=limit)
        while not lines and time.monotonic() < deadline:
            time.sleep(0.03)
            lines = store.pull(after, ports, limit=limit)
        return {
            "ok": True,
            "last": lines[-1].seq if lines else after,
            "lines": [{"seq": ln.seq, "t": round(ln.t_wall, 3), "port": ln.port,
                       "text": ln.text, "tx": ln.is_tx} for ln in lines],
        }
