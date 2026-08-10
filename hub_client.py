#!/usr/bin/env python3
"""Serial Hub 브리지 클라이언트 — 외부 자동화 스크립트용.

hub 가 COM 을 쥐고 있는 동안에도 이걸로 명령을 보내고 응답을 받는다.
run_*.py / otcli_dut.py 류를 이관할 때 pyserial 대신 이 클래스를 쓰면 된다.

  from serial_hub.hub_client import HubClient
  hub = HubClient()                      # 127.0.0.1:3341
  print(hub.status()["roles"])
  reply = hub.command("SHELL", "otcli state")   # 응답 라인들
  hub.marker("### T1 cycle 3 start")

CLI 로도 쓸 수 있다:
  python hub_client.py status
  python hub_client.py send SHELL "otcli state"
  python hub_client.py marker "### T1 start"
  python hub_client.py tail MLOG          # Ctrl+C 로 종료
"""

from __future__ import annotations

import json
import socket
import sys
import time
from .core.i18n import tr

DEFAULT_ADDR = ("127.0.0.1", 3341)


class HubClient:
    def __init__(self, host: str = DEFAULT_ADDR[0], port: int = DEFAULT_ADDR[1],
                 timeout: float = 12.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._file = self._sock.makefile("rwb")

    def close(self) -> None:
        try:
            self._file.close()
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "HubClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def request(self, payload: dict) -> dict:
        self._file.write(json.dumps(payload, ensure_ascii=False).encode() + b"\n")
        self._file.flush()
        raw = self._file.readline()
        if not raw:
            raise ConnectionError("hub closed connection")
        response = json.loads(raw.decode("utf-8", "replace"))
        if not response.get("ok"):
            raise RuntimeError(f"hub error: {response.get('err')}")
        return response

    # ------------------------------------------------------------------ 고수준

    def status(self) -> dict:
        return self.request({"op": "status"})

    def send(self, role: str, text: str) -> int:
        return int(self.request({"op": "send", "role": role, "text": text})["seq"])

    def pull(self, role: str | None = None, after: int = -1, max_lines: int = 500,
             wait_ms: int = 0) -> tuple[int, list[dict]]:
        payload: dict = {"op": "pull", "after": after, "max": max_lines, "wait_ms": wait_ms}
        if role:
            payload["role"] = role
        response = self.request(payload)
        return int(response["last"]), list(response["lines"])

    def marker(self, text: str) -> None:
        self.request({"op": "marker", "text": text})

    def command(self, role: str, text: str, timeout: float = 5.0,
                done_tokens: tuple[str, ...] = ("Done", "Error", "Invalid command")) -> list[str]:
        """명령 1개를 보내고 종결 토큰이 올 때까지의 응답 라인을 모아 돌려준다.

        otcli_dut.py 의 echo-anchor 방식 — send 가 돌려준 seq 이후만 본다.
        """
        seq = self.send(role, text)
        deadline = time.monotonic() + timeout
        collected: list[str] = []
        cursor = seq
        while time.monotonic() < deadline:
            cursor, lines = self.pull(role, after=cursor, wait_ms=500)
            for entry in lines:
                if entry["tx"]:
                    continue
                collected.append(entry["text"])
                if any(tok in entry["text"] for tok in done_tokens):
                    return collected
        return collected


def _cli() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    op = args[0]
    with HubClient() as hub:
        if op == "status":
            print(json.dumps(hub.status(), ensure_ascii=False, indent=2))
        elif op == "send" and len(args) >= 3:
            for line in hub.command(args[1], " ".join(args[2:])):
                print(line)
        elif op == "marker" and len(args) >= 2:
            hub.marker(" ".join(args[1:]))
            print("ok")
        elif op == "tail":
            role = args[1] if len(args) > 1 else None
            cursor = hub.status()["seq"]
            print(tr('-- tail {0} (Ctrl+C 종료) --').format(role or 'ALL'))
            try:
                while True:
                    cursor, lines = hub.pull(role, after=cursor, wait_ms=2000)
                    for entry in lines:
                        mark = ">>> " if entry["tx"] else ""
                        print(f"[{entry['port']}] {mark}{entry['text']}")
            except KeyboardInterrupt:
                pass
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
