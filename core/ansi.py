"""ANSI SGR 파서 — 색을 '지우지' 않고 '떼어내서' 보관한다.

펌웨어가 `\x1b[32m` 같은 컬러 코드를 섞어 보내면 두 요구가 충돌한다:
  - 로그 파일과 grep 은 이스케이프가 없어야 한다 (Jira 첨부·분석 스크립트)
  - 화면은 펌웨어가 의도한 색으로 보여야 한다 (에러/경고 구분)

그래서 적재 시점에 **본문(clean)과 색 구간(spans)을 분리**한다. 파일·필터·redact 는
clean 만 보고, 콘솔만 spans 를 입힌다. 색이 없으면 spans 는 비어서 비용이 0 이다.
"""

from __future__ import annotations

import re

SGR_RE = re.compile(r"\x1b\[([0-9;:]*)m")
# SGR 이 아닌 나머지 제어 시퀀스(커서 이동·화면 지우기 등)와 BEL — 본문에서 제거만 한다
OTHER_ESC_RE = re.compile(r"\x1b\[[0-9;:<=>?]*[ -/]*[@-ln-~]"
                          r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]|\x07")
TRUNC_ESC_RE = re.compile(r"\x1b\[?[0-9;:<=>?]*$")

# 흰 배경에서 읽히도록 조정한 8색 + 밝은 8색 (터미널 기본값을 그대로 쓰면 노랑이 안 보인다)
_FG = {
    30: "#3B4045", 31: "#C0392B", 32: "#1E8449", 33: "#B7791F",
    34: "#1F5FA9", 35: "#8E44AD", 36: "#0E7490", 37: "#5B6770",
    90: "#6B7280", 91: "#E74C3C", 92: "#27AE60", 93: "#D68910",
    94: "#3498DB", 95: "#A569BD", 96: "#17A2B8", 97: "#2C3034",
}
_BG = {
    40: "#3B4045", 41: "#FADBD8", 42: "#D5F5E3", 43: "#FCF3CF",
    44: "#D6EAF8", 45: "#EBDEF0", 46: "#D1F2F6", 47: "#EEF1F4",
    100: "#D5D8DC", 101: "#FADBD8", 102: "#D5F5E3", 103: "#FCF3CF",
    104: "#D6EAF8", 105: "#EBDEF0", 106: "#D1F2F6", 107: "#F8F9F9",
}


def _xterm256(index: int) -> str:
    """256색 팔레트 → hex."""
    if index < 16:
        table = list(_FG.values())[:8] + list(_FG.values())[8:16]
        return table[index] if index < len(table) else "#000000"
    if index < 232:
        index -= 16
        levels = (0, 95, 135, 175, 215, 255)
        return "#{:02X}{:02X}{:02X}".format(
            levels[index // 36], levels[(index // 6) % 6], levels[index % 6])
    gray = 8 + (index - 232) * 10
    return f"#{gray:02X}{gray:02X}{gray:02X}"


def _apply_params(params: list[int], state: tuple[str, str, bool]) -> tuple[str, str, bool]:
    fg, bg, bold = state
    index = 0
    while index < len(params):
        code = params[index]
        if code == 0:
            fg, bg, bold = "", "", False
        elif code == 1:
            bold = True
        elif code == 22:
            bold = False
        elif code == 39:
            fg = ""
        elif code == 49:
            bg = ""
        elif code in _FG:
            fg = _FG[code]
        elif code in _BG:
            bg = _BG[code]
        elif code in (38, 48):
            target_fg = code == 38
            if index + 1 < len(params) and params[index + 1] == 5 and index + 2 < len(params):
                color = _xterm256(params[index + 2])
                index += 2
            elif index + 1 < len(params) and params[index + 1] == 2 and index + 4 < len(params):
                color = "#{:02X}{:02X}{:02X}".format(*(min(255, max(0, v))
                                                       for v in params[index + 2:index + 5]))
                index += 4
            else:
                index += 1
                continue
            if target_fg:
                fg = color
            else:
                bg = color
        index += 1
    return fg, bg, bold


def parse(text: str) -> tuple[str, tuple[tuple[int, int, str, str, bool], ...]]:
    """(색 코드를 뺀 본문, ((start, end, fg, bg, bold), ...)).

    offset 은 반환된 본문 기준이다. 이스케이프가 없으면 원문을 그대로 돌려준다.
    """
    if "\x1b" not in text and "\x07" not in text:
        return text, ()

    out: list[str] = []
    spans: list[tuple[int, int, str, str, bool]] = []
    state = ("", "", False)
    span_start = 0
    position = 0
    length = 0

    while position < len(text):
        match = SGR_RE.search(text, position)
        if match is None:
            break
        chunk = text[position:match.start()]
        if chunk:
            out.append(chunk)
            length += len(chunk)
        if state != ("", "", False) and length > span_start:
            spans.append((span_start, length, state[0], state[1], state[2]))
        raw = match.group(1)
        params = [int(p) for p in re.split(r"[;:]", raw) if p.isdigit()] or [0]
        state = _apply_params(params, state)
        span_start = length
        position = match.end()

    if position < len(text):
        chunk = text[position:]
        out.append(chunk)
        length += len(chunk)
    if state != ("", "", False) and length > span_start:
        spans.append((span_start, length, state[0], state[1], state[2]))

    clean = "".join(out)
    # SGR 외의 제어 시퀀스가 남아 있으면 본문에서 지운다. 길이가 바뀌면 offset 이
    # 어긋나므로 그때는 색을 포기한다 (본문 정확도가 우선).
    stripped = TRUNC_ESC_RE.sub("", OTHER_ESC_RE.sub("", clean))
    if stripped != clean:
        return stripped, ()
    return clean, tuple(spans)


def strip(text: str) -> str:
    """색을 버리고 본문만 (파일 기록·검색용)."""
    return parse(text)[0]
