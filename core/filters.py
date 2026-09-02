"""필터 / 하이라이트 / redact 룰. 설계문서 §5-4, §5-5, §5-8.

세 룰 모두 substring 이 기본이고 regex 는 옵트인이다 — 로그 검색에서 흔히 쓰는
`[ZCL]`, `!!` 같은 문자열이 regex 메타문자를 포함하기 때문.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from .logstore import LogLine

# 하이라이트 팔레트 — 검색 강조(주황)와 시각적으로 구분되도록 제한한다.
# ★키는 **프로파일 JSON 에 저장되는 식별자**다. 번역하면 안 된다 — 영어로 켠 PC 에서
#   저장한 프로파일을 한국어 PC 에서 열면 색을 못 찾는다. 화면에 보일 때만 tr() 를 거친다.
# ★색 **이름**은 프로파일 JSON 에 저장되는 식별자다 — 테마·언어와 무관하게 고정이고,
#   두 팔레트가 같은 키를 가져야 한다 (다른 PC·다른 테마에서 프로파일이 깨지지 않게).
HIGHLIGHT_PALETTES = {
    "light": {
        "빨강": "#FFD5D5", "주황": "#FFE2C2", "노랑": "#FFF4C2", "초록": "#D3F5E3",
        "파랑": "#D6E8FF", "보라": "#E6DBFF", "회색": "#E5E8EB",
    },
    "dark": {
        "빨강": "#5A2A2A", "주황": "#5E4426", "노랑": "#5C5326", "초록": "#245239",
        "파랑": "#22415E", "보라": "#42335E", "회색": "#3A3F44",
    },
}
SEARCH_PALETTE = {"light": "#FFC98A", "dark": "#7A5522"}
DEFAULT_HIGHLIGHT_COLOR = "노랑"
_CURRENT = "light"


def set_theme(name: str) -> None:
    global _CURRENT
    _CURRENT = name if name in HIGHLIGHT_PALETTES else "light"


def highlight_names() -> list[str]:
    """고를 수 있는 색 이름 — 순서까지 고정이다 (콤보 순서가 흔들리면 안 된다)."""
    return list(HIGHLIGHT_PALETTES["light"])


def highlight_hex(name: str) -> str:
    table = HIGHLIGHT_PALETTES[_CURRENT]
    return table.get(name, table[DEFAULT_HIGHLIGHT_COLOR])


def search_hex() -> str:
    return SEARCH_PALETTE[_CURRENT]


def compile_pattern(pattern: str, is_regex: bool, case_sensitive: bool) -> re.Pattern | None:
    """substring 은 escape 해서 regex 로 통일한다. 잘못된 regex 는 None (룰 무력화)."""
    if not pattern:
        return None
    body = pattern if is_regex else re.escape(pattern)
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        return re.compile(body, flags)
    except re.error:
        return None


@dataclass
class FilterRule:
    """필터드뷰 1개의 조건. ports 가 비면 전 포트."""

    pattern: str = ""
    is_regex: bool = False
    case_sensitive: bool = False
    ports: list[str] = field(default_factory=list)
    name: str = ""

    def compiled(self) -> re.Pattern | None:
        return compile_pattern(self.pattern, self.is_regex, self.case_sensitive)

    def match(self, line: LogLine, compiled: re.Pattern | None = None) -> bool:
        if self.ports and line.port not in self.ports:
            return False
        rx = compiled if compiled is not None else self.compiled()
        if rx is None:
            return not self.pattern  # 빈 필터 = 전부 통과, 깨진 regex = 전부 차단
        return rx.search(line.text) is not None

    def label(self) -> str:
        scope = ",".join(self.ports) if self.ports else "ALL"
        return self.name or f'"{self.pattern}" — {scope}'

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "is_regex": self.is_regex,
            "case_sensitive": self.case_sensitive,
            "ports": list(self.ports),
            "name": self.name,
        }

    @staticmethod
    def from_dict(data: dict) -> "FilterRule":
        return FilterRule(
            pattern=str(data.get("pattern", "")),
            is_regex=bool(data.get("is_regex", False)),
            case_sensitive=bool(data.get("case_sensitive", False)),
            ports=[str(p) for p in data.get("ports", [])],
            name=str(data.get("name", "")),
        )


@dataclass
class HighlightRule:
    pattern: str = ""
    color: str = DEFAULT_HIGHLIGHT_COLOR
    is_regex: bool = False
    case_sensitive: bool = False
    enabled: bool = True

    def compiled(self) -> re.Pattern | None:
        if not self.enabled:
            return None
        return compile_pattern(self.pattern, self.is_regex, self.case_sensitive)

    def qcolor_hex(self) -> str:
        return highlight_hex(self.color)

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "color": self.color,
            "is_regex": self.is_regex,
            "case_sensitive": self.case_sensitive,
            "enabled": self.enabled,
        }

    @staticmethod
    def from_dict(data: dict) -> "HighlightRule":
        return HighlightRule(
            pattern=str(data.get("pattern", "")),
            color=str(data.get("color", DEFAULT_HIGHLIGHT_COLOR)),
            is_regex=bool(data.get("is_regex", False)),
            case_sensitive=bool(data.get("case_sensitive", False)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class RedactRule:
    """regex 의 그룹 1이 있으면 그 그룹만, 없으면 매치 전체를 replacement 로 바꾼다.

    `is_regex=False` 면 리터럴로 취급한다 — 비밀번호에 `+`, `(` 같은 메타문자가 있으면
    regex 로는 매치에 실패해 평문이 그대로 기록되기 때문이다.
    """

    pattern: str = ""
    replacement: str = "<redacted>"
    enabled: bool = True
    is_regex: bool = True

    def compiled(self) -> re.Pattern | None:
        if not self.enabled or not self.pattern:
            return None
        return compile_pattern(self.pattern, self.is_regex, case_sensitive=True)

    def to_dict(self) -> dict:
        return {"pattern": self.pattern, "replacement": self.replacement,
                "enabled": self.enabled, "is_regex": self.is_regex}

    @staticmethod
    def from_dict(data: dict) -> "RedactRule":
        return RedactRule(
            pattern=str(data.get("pattern", "")),
            replacement=str(data.get("replacement", "<redacted>")),
            enabled=bool(data.get("enabled", True)),
            is_regex=bool(data.get("is_regex", True)),
        )


@dataclass
class TriggerRule:
    """밤샘 수집 중 '언제 몇 번 났는지' 를 세는 감시 패턴 (GAP-3).

    하이라이트가 '보이는 강조' 라면 트리거는 '집계' 다 — WDOG/MemManage 처럼
    새벽에 지나가면 놓치는 이벤트의 횟수·최근 시각을 상태줄에 남긴다.
    """

    pattern: str = ""
    is_regex: bool = False
    case_sensitive: bool = False
    ports: list[str] = field(default_factory=list)
    enabled: bool = True

    def compiled(self) -> re.Pattern | None:
        if not self.enabled:
            return None
        return compile_pattern(self.pattern, self.is_regex, self.case_sensitive)

    def to_dict(self) -> dict:
        return {"pattern": self.pattern, "is_regex": self.is_regex,
                "case_sensitive": self.case_sensitive, "ports": list(self.ports),
                "enabled": self.enabled}

    @staticmethod
    def from_dict(data: dict) -> "TriggerRule":
        return TriggerRule(
            pattern=str(data.get("pattern", "")),
            is_regex=bool(data.get("is_regex", False)),
            case_sensitive=bool(data.get("case_sensitive", False)),
            ports=[str(p) for p in data.get("ports", [])],
            enabled=bool(data.get("enabled", True)),
        )


class TriggerWatcher:
    """LogStore 를 자기 커서로 pull 하며 트리거 발생을 집계한다 (GUI tick 에서 호출)."""

    def __init__(self):
        self._rules: list[tuple[TriggerRule, re.Pattern]] = []
        self.counts: dict[str, int] = {}
        self.last_hit: dict[str, LogLine] = {}
        self._cursor = -1

    def set_rules(self, rules: list["TriggerRule"]) -> None:
        compiled = []
        for rule in rules:
            rx = rule.compiled()
            if rx is not None and rule.pattern:
                compiled.append((rule, rx))
        self._rules = compiled
        for rule, _rx in compiled:
            self.counts.setdefault(rule.pattern, 0)

    def reset(self, rewind: bool = False) -> None:
        """집계만 지운다. `rewind=True` 면 커서까지 되돌린다.

        칩 클릭(카운터 초기화)은 커서를 유지해야 이미 지나간 라인을 다시 세지 않고,
        store 가 통째로 바뀌는 프로파일 전환은 커서를 되돌려야 새 store 의 seq(1부터)를
        읽을 수 있다 — 안 그러면 집계가 조용히 죽는다.
        """
        self.counts = {}
        self.last_hit = {}
        if rewind:
            self._cursor = -1

    def scan(self, store) -> list[tuple[str, LogLine]]:
        """새 라인만 훑고, 이번에 새로 매치된 (패턴, 라인) 목록을 돌려준다."""
        if not self._rules:
            self._cursor = store.last_seq()
            return []
        lines = store.pull(self._cursor, limit=20_000)
        if not lines:
            return []
        self._cursor = lines[-1].seq
        hits: list[tuple[str, LogLine]] = []
        for line in lines:
            if line.is_tx:
                continue
            for rule, rx in self._rules:
                if rule.ports and line.port not in rule.ports:
                    continue
                if rx.search(line.text):
                    self.counts[rule.pattern] = self.counts.get(rule.pattern, 0) + 1
                    self.last_hit[rule.pattern] = line
                    hits.append((rule.pattern, line))
        return hits

    def total(self) -> int:
        return sum(self.counts.values())


DEFAULT_REDACT_RULES = [
    RedactRule(r"(?i)\bwifi\s+connect\s+\S+\s+(\S+)", "<PSK-redacted>"),
    RedactRule(r"(?i)\bnetworkkey\s+([0-9a-fA-F]{32})", "<networkkey-redacted>"),
    RedactRule(r"(?i)\bpskc\s+([0-9a-fA-F]{32})", "<pskc-redacted>"),
    # 키워드가 라인 경계 너머로 잘려도 값 자체의 '형태' 로 잡는 안전망.
    # Thread networkkey/PSKc(32 hex)와 Matter dataset TLV(64+ hex)가 대상 —
    # 이 길이의 연속 hex 는 실제 로그에서 비밀값 외엔 거의 나오지 않는다.
    RedactRule(r"\b([0-9a-fA-F]{32,})\b", "<hex-secret-redacted>"),
]

DEFAULT_HIGHLIGHT_RULES = [
    HighlightRule("Error", "주황"),
    HighlightRule("!!", "노랑"),
]


class Redactor:
    """reader 스레드에서 라인마다 호출된다 — 룰 갱신은 UI 스레드라 락이 필요하다."""

    def __init__(self, rules: list[RedactRule] | None = None):
        self._lock = threading.Lock()
        self._compiled: list[tuple[re.Pattern, str]] = []
        self._invalid: list[str] = []
        self.set_rules(rules or [])

    def set_rules(self, rules: list[RedactRule]) -> list[str]:
        """반환값 = 컴파일 실패해서 무력화된 룰 목록.

        마스킹 룰이 조용히 사라지면 평문이 그대로 기록된다. 호출자는 이 목록을
        반드시 사용자에게 보여야 한다 (fail-open 을 눈에 보이게 만든다).
        """
        compiled: list[tuple[re.Pattern, str]] = []
        invalid: list[str] = []
        for rule in rules:
            if not rule.enabled or not rule.pattern:
                continue
            pattern = rule.compiled()
            if pattern is None:
                invalid.append(rule.pattern)
                continue
            compiled.append((pattern, rule.replacement))
        with self._lock:
            self._compiled = compiled
            self._invalid = invalid
        return invalid

    def invalid_rules(self) -> list[str]:
        with self._lock:
            return list(self._invalid)

    def apply(self, text: str) -> str:
        with self._lock:
            compiled = self._compiled
        for rx, replacement in compiled:
            text = _sub_group_or_whole(rx, replacement, text)
        return text

    def has_rules(self) -> bool:
        with self._lock:
            return bool(self._compiled)


def _sub_group_or_whole(rx: re.Pattern, replacement: str, text: str) -> str:
    def _repl(match: re.Match) -> str:
        if match.re.groups >= 1 and match.group(1) is not None:
            start, end = match.span(1)
            whole_start = match.start()
            return match.group(0)[: start - whole_start] + replacement + match.group(0)[end - whole_start:]
        return replacement

    return rx.sub(_repl, text)
