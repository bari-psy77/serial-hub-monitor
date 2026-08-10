"""프로파일(JSON) 직렬화. 설계문서 §5-6.

QSettings 가 아니라 JSON 파일인 이유: 벤치마다 COM 매핑이 다르므로 프로파일을
파일로 복사·공유할 수 있어야 한다. COM 번호는 코드에 넣지 않는다 (FR-9).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field

from .filters import (DEFAULT_HIGHLIGHT_RULES, DEFAULT_REDACT_RULES, FilterRule,
                      HighlightRule, RedactRule, TriggerRule)
from .logstore import TS_ABSOLUTE, TS_MODES
from .portscan import DEFAULT_BAUD, DEFAULT_PROBE_PATTERNS, DEFAULT_PROBE_TOKEN, DEFAULT_ROLES
from .i18n import tr

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".wtest", delete=True):
            return True
    except Exception:  # noqa: BLE001
        return False


APP_FOLDER_NAME = "SerialHub"
PORTABLE_MARKER = "portable.txt"


def _local_app_data() -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), APP_FOLDER_NAME)


def _data_dir() -> str:
    """프로파일·설정을 둘 곳.

    설치해서 쓰는 경우 Windows 관례대로 `%LOCALAPPDATA%\\SerialHub` 를 쓴다 — 설치
    폴더(Program Files 등)는 쓰기가 막혀 있을 수 있고, 사용자 설정을 프로그램 폴더에
    두는 것도 관례가 아니다. exe 옆에 `portable.txt` 를 만들어 두면 그 폴더에 저장해
    USB·zip 으로 통째로 들고 다닐 수 있다. 소스로 돌릴 때는 패키지 폴더를 쓴다.
    """
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.exists(os.path.join(exe_dir, PORTABLE_MARKER)) and _writable(exe_dir):
            return exe_dir
        candidates = [_local_app_data(), exe_dir]
    else:
        candidates = [PACKAGE_DIR]
    for base in candidates:
        if _writable(base):
            return base
    return tempfile.gettempdir()


DATA_DIR = _data_dir()
PROFILE_DIR = os.path.join(DATA_DIR, "profiles")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

DEFAULT_PROFILE_NAME = "default"


def default_log_base() -> str:
    """로그 기본 위치.

    설치할 때 사용자가 고른 값이 있으면 그것, 없으면 이 프로그램의 데이터 폴더 아래
    `logs`. 특정 PC 의 개인 경로를 기본값으로 박아두지 않는다 — 남의 PC 에서는
    존재하지도 않는 경로이고, 벤치마다 두는 자리가 다르다.
    """
    configured = load_settings().get("log_base_dir")
    if isinstance(configured, str) and configured.strip():
        return configured
    return os.path.join(DATA_DIR, "logs")


@dataclass
class PortConfig:
    role: str
    com: str = ""
    baud: int = DEFAULT_BAUD
    enabled: bool = True
    log_name: str = ""   # 로그 파일명 조각. 비우면 역할명 소문자 (mlog/shell/ucli)
    label: str = ""      # 화면에 보일 이름. 비우면 COM 번호를 그대로 쓴다

    def display(self) -> str:
        """콘솔 제목·상태 필·prefix 에 쓰는 이름 — 지정 안 하면 COM 번호."""
        return self.label.strip() or self.com or self.role

    def to_dict(self) -> dict:
        return {"role": self.role, "com": self.com, "baud": self.baud,
                "enabled": self.enabled, "log_name": self.log_name, "label": self.label}

    @staticmethod
    def from_dict(data: dict) -> "PortConfig":
        return PortConfig(
            role=str(data.get("role", "PORT")),
            com=str(data.get("com", "")),
            baud=int(data.get("baud", DEFAULT_BAUD)),
            enabled=bool(data.get("enabled", True)),
            log_name=str(data.get("log_name", "")),
            label=str(data.get("label", "")),
        )


@dataclass
class Profile:
    name: str = DEFAULT_PROFILE_NAME
    ports: list[PortConfig] = field(default_factory=lambda: [PortConfig(r) for r in DEFAULT_ROLES])
    log_base_dir: str = field(default_factory=lambda: default_log_base())
    session_prefix: str = "serialhub"
    log_include_session: bool = True   # 파일명에 `<접두어>_HHMMSS_` 를 붙일지
    merged_log_name: str = "all"       # 병합 파일 이름 조각
    max_log_mb: int = 200              # 병합 파일 크기 상한 (0 = 안 나눔)
    search_history: dict[str, list[str]] = field(default_factory=dict)
    capacity_per_port: int = 200_000
    ts_mode: str = TS_ABSOLUTE
    hide_empty: bool = True
    strip_ansi: bool = True     # 본문에서 색 코드 제거 (파일·grep 은 항상 깨끗하다)
    ansi_color: bool = True     # 펌웨어가 보낸 색을 화면에 살릴지
    console_font_size: int = 12
    word_wrap: bool = False
    highlight_rules: list[HighlightRule] = field(
        default_factory=lambda: [HighlightRule(**r.to_dict()) for r in DEFAULT_HIGHLIGHT_RULES])
    redact_rules: list[RedactRule] = field(
        default_factory=lambda: [RedactRule(**r.to_dict()) for r in DEFAULT_REDACT_RULES])
    saved_filters: list[FilterRule] = field(default_factory=list)
    trigger_rules: list[TriggerRule] = field(default_factory=lambda: [
        TriggerRule("WDOG"), TriggerRule("MemManage"), TriggerRule("HardFault")])
    bridge_port: int = 3341  # 0 = 자동화 브리지 끔
    probe_token: str = DEFAULT_PROBE_TOKEN
    probe_patterns: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PROBE_PATTERNS))
    command_history: dict[str, list[str]] = field(default_factory=dict)
    scratchpad: str = ""
    layout: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ 조회

    def port(self, role: str) -> PortConfig | None:
        for entry in self.ports:
            if entry.role == role:
                return entry
        return None

    def roles(self) -> list[str]:
        """설정에 존재하는 전 슬롯. 화면에 실제로 띄우는 건 active_roles() 다."""
        return [p.role for p in self.ports]

    def active_roles(self) -> list[str]:
        """이 모델에서 **실제로 쓰는** 포트.

        UART 가 1개뿐인 모델도 있고 2개인 모델도 있다 — 안 쓰는 콘솔까지 늘 3개를
        띄우면 화면만 좁아진다. 슬롯은 그대로 두고(설정을 잃지 않게) 표시만 끈다.
        """
        active = [p.role for p in self.ports if p.enabled]
        return active or self.roles()[:1]   # 전부 끄는 건 허용하지 않는다

    def set_active_count(self, count: int) -> None:
        """앞에서부터 count 개만 사용 — "포트 수" 빠른 선택용."""
        count = max(1, min(count, len(self.ports)))
        for index, entry in enumerate(self.ports):
            entry.enabled = index < count

    def enabled_ports(self) -> list[PortConfig]:
        return [p for p in self.ports if p.enabled and p.com]

    # ------------------------------------------------------------------ 직렬화

    def set_redactor(self, redactor) -> None:
        """프로파일 JSON 에 비밀값이 평문으로 들어가지 않게 하는 마지막 관문.

        명령 히스토리와 스크래치패드는 사용자가 `wifi connect <ssid> <psk>` 를 그대로
        타이핑하는 자리다. 로그에서는 마스킹하면서 "벤치 간 복사·공유용" 파일에
        평문으로 남기면 마스킹을 한 의미가 없다.
        """
        self._redactor = redactor

    def _mask(self, text: str) -> str:
        redactor = getattr(self, "_redactor", None)
        return redactor.apply(text) if redactor is not None else text

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ports": [p.to_dict() for p in self.ports],
            "log_base_dir": self.log_base_dir,
            "session_prefix": self.session_prefix,
            "log_include_session": self.log_include_session,
            "merged_log_name": self.merged_log_name,
            "max_log_mb": self.max_log_mb,
            "search_history": {k: list(v)[-30:] for k, v in self.search_history.items()},
            "capacity_per_port": self.capacity_per_port,
            "ts_mode": self.ts_mode,
            "hide_empty": self.hide_empty,
            "strip_ansi": self.strip_ansi,
            "ansi_color": self.ansi_color,
            "console_font_size": self.console_font_size,
            "word_wrap": self.word_wrap,
            "highlight_rules": [r.to_dict() for r in self.highlight_rules],
            "redact_rules": [r.to_dict() for r in self.redact_rules],
            "saved_filters": [f.to_dict() for f in self.saved_filters],
            "trigger_rules": [t.to_dict() for t in self.trigger_rules],
            "bridge_port": self.bridge_port,
            "probe_token": self.probe_token,
            "probe_patterns": dict(self.probe_patterns),
            "command_history": {k: [self._mask(x) for x in list(v)[-100:]]
                                for k, v in self.command_history.items()},
            "scratchpad": self._mask(self.scratchpad),
            "layout": dict(self.layout),
        }

    @staticmethod
    def from_dict(data: dict) -> "Profile":
        profile = Profile()
        profile.name = str(data.get("name", DEFAULT_PROFILE_NAME))
        ports = [PortConfig.from_dict(p) for p in data.get("ports", []) if isinstance(p, dict)]
        if ports:
            profile.ports = ports
        profile.log_base_dir = str(data.get("log_base_dir") or default_log_base())
        profile.session_prefix = str(data.get("session_prefix", "serialhub"))
        profile.log_include_session = bool(data.get("log_include_session", True))
        profile.merged_log_name = str(data.get("merged_log_name", "all")) or "all"
        profile.max_log_mb = max(0, min(4096, int(data.get("max_log_mb", 200))))
        history = data.get("search_history")
        if isinstance(history, dict):
            profile.search_history = {str(k): [str(x) for x in v]
                                      for k, v in history.items() if isinstance(v, list)}
        profile.capacity_per_port = int(data.get("capacity_per_port", 200_000))
        ts_mode = str(data.get("ts_mode", TS_ABSOLUTE))
        profile.ts_mode = ts_mode if ts_mode in TS_MODES else TS_ABSOLUTE
        profile.hide_empty = bool(data.get("hide_empty", True))
        profile.strip_ansi = bool(data.get("strip_ansi", True))
        profile.ansi_color = bool(data.get("ansi_color", True))
        profile.console_font_size = max(7, min(28, int(data.get("console_font_size", 12))))
        profile.word_wrap = bool(data.get("word_wrap", False))
        if "highlight_rules" in data:
            profile.highlight_rules = [HighlightRule.from_dict(r)
                                       for r in data["highlight_rules"] if isinstance(r, dict)]
        if "redact_rules" in data:
            profile.redact_rules = [RedactRule.from_dict(r)
                                    for r in data["redact_rules"] if isinstance(r, dict)]
        profile.saved_filters = [FilterRule.from_dict(f)
                                 for f in data.get("saved_filters", []) if isinstance(f, dict)]
        if "trigger_rules" in data:
            profile.trigger_rules = [TriggerRule.from_dict(t)
                                     for t in data["trigger_rules"] if isinstance(t, dict)]
        profile.bridge_port = max(0, min(65535, int(data.get("bridge_port", 3341))))
        profile.probe_token = str(data.get("probe_token", DEFAULT_PROBE_TOKEN))
        patterns = data.get("probe_patterns")
        if isinstance(patterns, dict) and patterns:
            profile.probe_patterns = {str(k): str(v) for k, v in patterns.items()}
        history = data.get("command_history")
        if isinstance(history, dict):
            profile.command_history = {str(k): [str(x) for x in v]
                                       for k, v in history.items() if isinstance(v, list)}
        profile.scratchpad = str(data.get("scratchpad", ""))
        layout = data.get("layout")
        profile.layout = dict(layout) if isinstance(layout, dict) else {}
        return profile

    # ------------------------------------------------------------------ 파일

    @staticmethod
    def path_for(name: str) -> str:
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_. ").strip() or DEFAULT_PROFILE_NAME
        return os.path.join(PROFILE_DIR, f"{safe}.json")

    @staticmethod
    def load(name: str) -> tuple["Profile", str]:
        """(profile, warning). 파싱 실패해도 기동은 시킨다 — 깨진 파일은 .bak 로 보존 (설계 §7)."""
        path = Profile.path_for(name)
        if not os.path.exists(path):
            profile = Profile()
            profile.name = name
            return profile, ""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            profile = Profile.from_dict(data)
            profile.name = name
            return profile, ""
        except Exception as exc:  # noqa: BLE001
            backup = path + ".bak"
            try:
                shutil.copyfile(path, backup)
            except Exception:  # noqa: BLE001
                backup = tr('(백업 실패)')
            profile = Profile()
            profile.name = name
            return profile, (tr('프로파일 `{0}` 파싱 실패 ({1}) — 기본값으로 기동, 원본 보존: {2}')
                .format(name, str(exc)[:60], backup))

    def save(self) -> tuple[bool, str]:
        path = Profile.path_for(self.name)
        tmp = path + ".tmp"
        try:
            os.makedirs(PROFILE_DIR, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True, path
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


def list_profiles() -> list[str]:
    try:
        names = [os.path.splitext(f)[0] for f in os.listdir(PROFILE_DIR) if f.endswith(".json")]
    except FileNotFoundError:
        names = []
    if DEFAULT_PROFILE_NAME not in names:
        names.append(DEFAULT_PROFILE_NAME)
    return sorted(names)


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_settings(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except Exception:  # noqa: BLE001
        pass


def language() -> str:
    """화면 언어 — 프로파일이 아니라 **사람** 설정이라 settings.json 에 둔다."""
    return str(load_settings().get("language", "ko"))


def set_language(lang: str) -> None:
    data = load_settings()
    data["language"] = lang
    save_settings(data)


def last_profile_name() -> str:
    return str(load_settings().get("last_profile", DEFAULT_PROFILE_NAME))


def remember_profile(name: str) -> None:
    data = load_settings()
    data["last_profile"] = name
    save_settings(data)


def set_default_log_base(path: str) -> str:
    """설치 프로그램이 사용자가 고른 로그 위치를 남기는 통로.

    이미 만들어 둔 프로파일은 건드리지 않는다 — 새로 만들어지는 프로파일의 기본값만 바뀐다.
    """
    data = load_settings()
    data["log_base_dir"] = path
    save_settings(data)
    return SETTINGS_PATH
