"""COM 열거 · 점유 진단 · 역할 probe. 설계문서 §5-7, §5-9, §7.

probe 는 **실제 명령을 보내지 않는다**. 어느 콘솔에도 없는 무해 토큰 1개를 보내고
각 콘솔 디스패처의 unknown-command 응답 서명으로 역할을 판별한다. probe 시점엔
어느 COM 이 어느 콘솔인지 모르므로, 실명령을 쓰면 오배정된 포트에서 그 콘솔의
진짜 명령(UCLI `swtimer ... set` 등)이 실행될 수 있다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports as _list_ports

from .diag import diag
from .i18n import tr

ROLE_MLOG = "MLOG"
ROLE_SHELL = "SHELL"
ROLE_UCLI = "UCLI"
DEFAULT_ROLES = (ROLE_MLOG, ROLE_SHELL, ROLE_UCLI)
COMMANDABLE_ROLES = (ROLE_SHELL, ROLE_UCLI)

DEFAULT_BAUD = 115200
BAUD_CHOICES = (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)

# 어느 콘솔의 명령 테이블에도 없는 토큰. 바꿔도 되지만 실제 명령의 접두사가 되면 안 된다.
DEFAULT_PROBE_TOKEN = "serialhub_probe_7f3a"

# 응답 서명 — SDK 업그레이드로 문자열이 바뀔 수 있어 프로파일에서 덮어쓸 수 있게 둔다.
#   SHELL: MainLoopDefault.cpp:189  `Error <cmd>: <CHIP_ERROR_FORMAT>`
#   UCLI : user_cli.c:527           `Invalid command`
# `{token}` 은 실제로 보낸 명령/토큰으로 치환된다 — 로그 본문의 다른 "Error" 줄과 섞이지 않게 한다.
DEFAULT_PROBE_PATTERNS = {
    ROLE_SHELL: r"Error\s+{token}",
    ROLE_UCLI: r"Invalid command",
}
TOKEN_PLACEHOLDER = "{token}"

VERDICT_UNKNOWN = "UNKNOWN"

# 커맨드라인에 포트명이 안 잡히는 GUI 터미널들 — 점유 후보로 함께 보여준다.
TERMINAL_PROCESS_NAMES = (
    "ttermpro.exe", "MobaXterm.exe", "putty.exe", "TeraTerm.exe",
    "python.exe", "pythonw.exe", "Code.exe", "serialmonitor.exe", "plink.exe",
)


def port_name(com: str) -> str:
    """COM10 이상은 `\\\\.\\COM11` 형태여야 열린다 (scripts/serport.py:30-31 과 동일)."""
    return ("\\\\.\\" + com) if (com.upper().startswith("COM") and len(com) > 4) else com


def open_serial(com: str, baud: int, timeout: float = 0.05) -> serial.Serial:
    """기존 스크립트(serport.py)와 동일한 개방 파라미터 — 흐름제어 없음, 8N1."""
    return serial.Serial(port_name(com), baud, timeout=timeout, rtscts=False, dsrdtr=False)


@dataclass
class PortInfo:
    device: str
    description: str = ""
    hwid: str = ""

    def label(self) -> str:
        return f"{self.device}  —  {self.description}" if self.description else self.device


def list_ports() -> list[PortInfo]:
    out: list[PortInfo] = []
    try:
        for info in _list_ports.comports():
            out.append(PortInfo(info.device, info.description or "", info.hwid or ""))
    except Exception:  # noqa: BLE001 - 열거 실패는 빈 목록으로 처리
        return []
    out.sort(key=lambda p: (len(p.device), p.device))
    return out


def is_free(com: str, baud: int = DEFAULT_BAUD) -> tuple[bool, str]:
    """(열 수 있나, 상세). cleanup_ports.py probe_port 와 같은 판정."""
    try:
        ser = open_serial(com, baud, timeout=0.1)
        ser.close()
        return True, "free"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def who_holds(com: str) -> list[str]:
    """점유 후보 프로세스 (휴리스틱).

    handle.exe 가 없는 환경이라 "이 PID 가 이 핸들을 쥐고 있다"를 단정할 수 없다.
    커맨드라인에 포트명이 있거나, 알려진 터미널 프로세스인 것을 후보로 나열한다.
    """
    ps_cmd = [
        "powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine "
        "| ConvertTo-Json -Compress",
    ]
    try:
        out = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=20,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001
        return []
    raw = (out.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, dict):
        data = [data]

    # 단어 경계로 봐야 COM5 가 COM55 나 `C:\SOMECOM5\` 를 잡지 않는다
    target_rx = re.compile(rf"\b{re.escape(com)}\b", re.IGNORECASE)
    self_pid = os.getpid()
    hits: list[str] = []
    for entry in data:
        name = str(entry.get("Name") or "")
        cmdline = str(entry.get("CommandLine") or "")
        pid = entry.get("ProcessId")
        if pid == self_pid:
            continue  # 우리 자신은 후보가 아니다
        if target_rx.search(cmdline):
            hits.append(f"{name} (PID {pid})")
        elif name in TERMINAL_PROCESS_NAMES and name not in ("python.exe", "pythonw.exe"):
            hits.append(f"{name} (PID {pid})?")
    # 확정 후보(포트명 일치)를 앞으로
    hits.sort(key=lambda s: s.endswith("?"))
    return hits[:6]


# ----------------------------------------------------------------- probe

@dataclass
class ProbeResult:
    verdict: str = VERDICT_UNKNOWN
    detail: str = ""
    ok: bool = False
    passive_lines: int = 0
    tail: str = ""
    error: str = ""
    com: str = ""   # 실제로 probe 한 COM — 판정과 짝지어야 매핑 제안이 틀리지 않는다


def expand_pattern(pattern: str, token: str) -> str:
    return pattern.replace(TOKEN_PLACEHOLDER, re.escape(token))


def compile_probe_patterns(patterns: dict[str, str], token: str) -> list[tuple[str, re.Pattern]]:
    compiled: list[tuple[str, re.Pattern]] = []
    for role, pattern in patterns.items():
        if not pattern:
            continue
        try:
            compiled.append((role, re.compile(expand_pattern(pattern, token), re.IGNORECASE)))
        except re.error:
            continue
    return compiled


def anchor_after_echo(text: str, token: str) -> str:
    """토큰이 처음 나온 **줄의 시작**부터를 응답 구간으로 본다 (otcli_dut.py echo-anchor 변형).

    토큰 자체를 건너뛰면 안 된다 — 디바이스가 `Error <cmd>: ...` 처럼 명령을 되찍는 경우
    증거가 토큰 뒤가 아니라 같은 줄 앞쪽에 있기 때문이다. 줄 머리로 잡으면 에코가 있든
    없든 응답 줄 전체가 구간에 들어오고, 에코 앞의 잔여 출력은 그대로 배제된다.
    """
    index = text.find(token)
    if index < 0:
        return text
    return text[text.rfind("\n", 0, index) + 1:]


def classify_probe_text(text: str, token: str,
                        patterns: dict[str, str] | None = None) -> tuple[str, str]:
    """에코를 못 찾으면 **토큰을 품은 서명만** 인정한다 (fail-closed).

    에코가 없으면 판정 창이 수신 텍스트 전체로 열리는데, 초당 수백 줄이 흐르는 로그
    포트에서 `Invalid command` 같은 문자열이 우연히 한 번만 섞여도 UCLI 로 오판한다.
    """
    patterns = patterns or DEFAULT_PROBE_PATTERNS
    anchored = token in text
    window = anchor_after_echo(text, token)
    for role, rx in compile_probe_patterns(patterns, token):
        if not anchored and TOKEN_PLACEHOLDER not in patterns.get(role, ""):
            continue
        match = rx.search(window)
        if match:
            return role, match.group(0).strip()[:80]
    return VERDICT_UNKNOWN, ""


def probe_port(com: str, baud: int = DEFAULT_BAUD, token: str = DEFAULT_PROBE_TOKEN,
               patterns: dict[str, str] | None = None,
               passive_seconds: float = 2.0, response_timeout: float = 2.5) -> ProbeResult:
    """포트를 직접 열어 역할 판별. 이미 우리 reader 가 잡고 있으면 쓸 수 없다
    (그 경우 PortReader.probe 경로를 쓴다)."""
    result = ProbeResult(com=com)
    try:
        ser = open_serial(com, baud, timeout=0.05)
    except Exception as exc:  # noqa: BLE001
        result.error = str(exc)
        result.detail = tr('열기 실패: {0}').format(str(exc)[:70])
        return result

    try:
        # 1) 수동 관찰 — 자발 트래픽이 있으면 로그 콘솔 후보
        passive = _read_for(ser, passive_seconds)
        result.passive_lines = passive.count("\n")

        # 2) 무해 토큰 1개 전송
        try:
            ser.reset_input_buffer()
        except Exception:  # noqa: BLE001
            pass
        ser.write(token.encode() + b"\r\n")
        ser.flush()

        # 3) 응답 서명 탐색
        answer = _read_for(ser, response_timeout)
        result.tail = answer[-400:]
        verdict, evidence = classify_probe_text(answer, token, patterns)
        diag.info("probe", f"probe_port {com} -> {verdict} passive={result.passive_lines} "
                           f"evidence=`{evidence}`")
        if verdict != VERDICT_UNKNOWN:
            result.verdict = verdict
            result.ok = True
            result.detail = tr('{0} 판정 — 응답 `{1}`').format(verdict, evidence)
        elif token in answer:
            # 토큰을 되찍었다 = 입력을 받는 콘솔이라는 적극적 증거. 서명만 못 알아본
            # 것이므로 MLOG 로 확정하면 안 된다 (SDK 문구 변경 시 SHELL 을 MLOG 로 오판).
            result.detail = (tr('미확정 — 명령을 되찍었는데(입력 콘솔) 알려진 서명이 아닙니다. SDK 응답 '
                                '문구가 바뀌었을 수 있으니 프로파일의 probe 패턴을 확인하세요'))
        elif result.passive_lines > 0:
            # 우리가 보내기 **전에** 스스로 뱉은 트래픽이 있어야 로그 포트로 본다.
            # 토큰 전송 뒤의 출력은 그 명령에 대한 응답일 수 있어 근거가 못 된다.
            result.verdict = ROLE_MLOG
            result.ok = True
            result.detail = tr('{0} 판정 — 명령 응답 없음, 자발 트래픽 {1}줄').format(
                ROLE_MLOG, result.passive_lines)
        else:
            result.detail = (tr('미확정 — 알려진 응답 서명이 없습니다. 서명이 바뀌었을 수 있으니 '
                                'Rules/프로파일의 probe 패턴을 확인하세요'))
        return result
    except Exception as exc:  # noqa: BLE001
        result.error = str(exc)
        result.detail = tr('probe 실패: {0}').format(str(exc)[:70])
        return result
    finally:
        try:
            ser.close()
        except Exception:  # noqa: BLE001
            pass


def _read_for(ser: serial.Serial, seconds: float) -> str:
    end = time.monotonic() + seconds
    chunks: list[bytes] = []
    while time.monotonic() < end:
        try:
            data = ser.read(4096)
        except Exception:  # noqa: BLE001
            break
        if data:
            chunks.append(data)
        else:
            time.sleep(0.02)
    return b"".join(chunks).decode("utf-8", "replace")


class BackgroundTask:
    """GUI 스레드를 막지 않고 probe / who_holds 를 돌리기 위한 최소 래퍼.

    UI 는 이미 50ms QTimer 를 돌리므로 완료 여부를 폴링한다 — 크로스 스레드 시그널이 필요 없다.
    """

    def __init__(self, fn, *args, **kwargs):
        self._result = None
        self._error: str | None = None
        self._done = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(fn, args, kwargs), daemon=True)
        self._thread.start()

    def _run(self, fn, args, kwargs) -> None:
        try:
            self._result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
        finally:
            self._done.set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def result(self):
        return self._result

    @property
    def error(self) -> str | None:
        return self._error
