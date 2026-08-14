"""logfile — 과거 로그 파일을 LogLine 으로 복원하는 파서 + 읽기 전용 스토어.

설계문서 docs/superpowers/specs/2026-08-14-log-viewer-design.md §3.1.
Qt 를 모르는 순수 파이썬 계층이다. 뷰어는 이 스토어를 ConsolePane 에 그대로 물린다 —
ConsolePane 이 쓰는 것은 pull_with_gap()/last_seq() 뿐이라 라이브 LogStore 와 호환된다.

기록 시 이미 redact 를 거친 파일이므로 여기서는 재마스킹하지 않는다.
파일은 읽고 즉시 닫는다 — 다른 도구(기록 중인 앱 포함)를 잠그면 안 된다.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from .logstore import TX_MARK, LogLine, PullResult

FMT_PORT = "port"        # [2026-08-02 01:19:12.165] 본문   (포트별 파일)
FMT_MERGED = "merged"    # [01:19:12 +   0.1s] [MLOG] 본문  (병합 파일)
FMT_PLAIN = "plain"      # 그 외 — 원문 그대로 (빈 화면 금지, 열화 수용)
LARGE_WARN_BYTES = 200 * 1024 * 1024   # 이 합계를 넘으면 로드 전에 확인을 받는다
_SNIFF_LINES = 50        # 형식 판별에 보는 앞쪽 비어 있지 않은 줄 수

_PORT_RE = re.compile(r"^\[(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\.(\d{3})\] (.*)$")
_MERGED_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2}) \+\s*([0-9.]+)s\] \[([^\]]+)\] (.*)$")


@dataclass(frozen=True, slots=True)
class ParsedEntry:
    t_wall: float
    source: str
    text: str
    is_tx: bool


@dataclass(frozen=True, slots=True)
class ParsedLog:
    fmt: str
    entries: list        # list[ParsedEntry]
    path: str


def _split_tx(body: str) -> tuple[str, bool]:
    """`>>> ` 접두어는 본문에서 뗀다 — render_line 이 표시할 때 다시 붙인다."""
    if body.startswith(TX_MARK):
        return body[len(TX_MARK):], True
    return body, False


def _sniff(lines: list[str]) -> str:
    """파일 형식은 파일 단위로 정한다 — 앞쪽 비어 있지 않은 50줄 중 먼저 매치되는 형식."""
    seen = 0
    for line in lines:
        if not line.strip():
            continue
        if _PORT_RE.match(line):
            return FMT_PORT
        if _MERGED_RE.match(line):
            return FMT_MERGED
        seen += 1
        if seen >= _SNIFF_LINES:
            break
    return FMT_PLAIN


def parse_log_file(path: str) -> ParsedLog:
    """한 파일을 ParsedEntry 목록으로. 형식 판별 실패는 오류가 아니라 plain 열화다."""
    stem = os.path.splitext(os.path.basename(path))[0]
    mtime = os.path.getmtime(path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read().splitlines()
    fmt = _sniff(raw)
    day = time.localtime(mtime)   # 병합 형식은 날짜가 없다 — 파일 수정일로 보정 (표시는 시각만)
    entries: list[ParsedEntry] = []
    last_t = mtime
    for line in raw:
        t_wall, source, body = None, stem, line
        if fmt == FMT_PORT:
            match = _PORT_RE.match(line)
            if match:
                year, month, mday, hour, minute, sec, ms, body = match.groups()
                t_wall = time.mktime((int(year), int(month), int(mday), int(hour),
                                      int(minute), int(sec), 0, 0, -1)) + int(ms) / 1000.0
        elif fmt == FMT_MERGED:
            match = _MERGED_RE.match(line)
            if match:
                hour, minute, sec, _elapsed, source, body = match.groups()
                t_wall = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, int(hour),
                                      int(minute), int(sec), 0, 0, -1))
        if t_wall is None:
            # 형식이 정해진 파일 안의 배너/깨진 줄 — 그 줄만 plain 으로 받아들인다.
            # 시각은 직전 줄을 따라가 정렬 위치가 흐트러지지 않게 한다.
            t_wall, source = last_t, stem
        last_t = t_wall
        text, is_tx = _split_tx(body)
        entries.append(ParsedEntry(t_wall, source, text, is_tx))
    return ParsedLog(fmt, entries, path)


class LogFileStore:
    """읽기 전용 스토어 — 파일에서 복원한 라인을 시간순으로 합쳐 seq 를 부여한다.

    add_files() 뒤에는 seq 가 전부 다시 매겨지므로, UI 는 커서를 버리고 reload() 한다.
    """

    def __init__(self):
        self._entries: list[ParsedEntry] = []
        self._lines: list[LogLine] = []
        self._sources: list[str] = []      # 등록 순서 유지
        self._formats: list[str] = []
        self._paths: list[str] = []

    # ------------------------------------------------------------------ 적재

    def _unique_key(self, stem: str) -> str:
        if stem not in self._sources:
            return stem
        n = 2
        while f"{stem}({n})" in self._sources:
            n += 1
        return f"{stem}({n})"

    def _register(self, source: str) -> None:
        if source not in self._sources:
            self._sources.append(source)

    def add_files(self, paths: list[str]) -> list[tuple[str, str]]:
        """파일들을 파싱해 합친다. 반환값 = 실패한 (경로, 사유) 목록 — 예외를 던지지 않는다."""
        errors: list[tuple[str, str]] = []
        for path in paths:
            try:
                parsed = parse_log_file(path)
            except OSError as exc:
                errors.append((path, str(exc)))
                continue
            if parsed.fmt == FMT_MERGED:
                # 병합 파일의 포트 키는 의도적으로 공유한다 — 두 세션의 MLOG 는 한 소스다
                for entry in parsed.entries:
                    self._register(entry.source)
                    self._entries.append(entry)
            else:
                key = self._unique_key(os.path.splitext(os.path.basename(path))[0])
                self._register(key)   # 빈 파일도 소스는 등록한다 (0줄로 표시)
                for entry in parsed.entries:
                    self._entries.append(ParsedEntry(entry.t_wall, key, entry.text, entry.is_tx))
            self._formats.append(parsed.fmt)
            self._paths.append(path)
        self._rebuild()
        return errors

    def _rebuild(self) -> None:
        ordered = sorted(self._entries, key=lambda e: e.t_wall)   # 안정 정렬 — 동률은 추가 순서
        t0 = ordered[0].t_wall if ordered else 0.0
        self._lines = [LogLine(i + 1, e.t_wall, e.t_wall - t0, e.source, e.text, e.is_tx, ())
                       for i, e in enumerate(ordered)]

    # ------------------------------------------------------------------ 조회

    def sources(self) -> list[str]:
        return list(self._sources)

    def labels(self) -> dict[str, str]:
        return {source: source for source in self._sources}

    def paths(self) -> list[str]:
        return list(self._paths)

    def all_plain(self) -> bool:
        """전부 형식 미상(plain)이면 True — 뷰어가 타임스탬프 표시를 끄는 기준."""
        return bool(self._formats) and all(fmt == FMT_PLAIN for fmt in self._formats)

    def total_lines(self) -> int:
        return len(self._lines)

    def last_seq(self) -> int:
        return len(self._lines)

    def counters(self) -> dict[str, int]:
        counts = {source: 0 for source in self._sources}
        for line in self._lines:
            counts[line.port] = counts.get(line.port, 0) + 1
        return counts

    def pull(self, after_seq: int, ports: list[str] | None = None,
             limit: int | None = None) -> list[LogLine]:
        return self.pull_with_gap(after_seq, ports, limit).lines

    def pull_with_gap(self, after_seq: int, ports: list[str] | None = None,
                      limit: int | None = None) -> PullResult:
        """seq == 리스트 index+1 이므로 after_seq 가 곧 시작 index 다."""
        start = max(0, after_seq)
        chunk = self._lines[start:]
        if ports is not None:
            wanted = set(ports)
            chunk = [line for line in chunk if line.port in wanted]
        skipped = 0
        if limit is not None and len(chunk) > limit:
            skipped = len(chunk) - limit
            chunk = chunk[-limit:]
        return PullResult(chunk, skipped, False)
