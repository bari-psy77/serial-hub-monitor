"""Toss 계열 QSS · 컬러 토큰 · 공통 프리미티브(Card / StatusPill / SegmentedTabs).

UI 문서 §0 참조. 색은 여기 한 곳에서만 관리한다.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

PALETTES = {
    # 지금까지의 밝은 화면
    "light": {
        "BG": "#F2F4F6", "CARD_BG": "#FFFFFF", "BORDER": "#E5E8EB",
        "TEXT": "#191F28", "TEXT_SUB": "#8B95A1",
        "PRIMARY": "#3182F6", "PRIMARY_DARK": "#1B64DA",
        "SUCCESS": "#00C471", "DANGER": "#F04452", "WARNING": "#FFB331",
        "CONSOLE_BG": "#FFFFFF", "CONSOLE_TEXT": "#191F28", "TX_TEXT": "#4E5968",
        "BANNER_BG": "#FFF4C2", "BANNER_TEXT": "#8A6D00",
        "HOVER_BG": "#F7F8F9", "DISABLED_BG": "#F2F4F6", "DISABLED_TEXT": "#B0B8C1",
        "SOFT_BG": "#E8F0FE", "SOFT_BORDER": "#C6D6F5",
        "SELECTION_BG": "#CFE3FF", "SELECTION_TEXT": "#191F28",
        "TINT_SUCCESS": "#E7F9F1", "TINT_WARNING": "#FFF6E5",
        "TINT_DANGER": "#FEECEE", "TINT_PRIMARY": "#E8F0FE", "TINT_NEUTRAL": "#F2F4F6",
    },
    # 어두운 화면 — 콘솔 본문까지 함께 바뀐다
    "dark": {
        "BG": "#16181D", "CARD_BG": "#1E2127", "BORDER": "#2C313A",
        "TEXT": "#E6E9EF", "TEXT_SUB": "#8B95A1",
        "PRIMARY": "#4C8DFF", "PRIMARY_DARK": "#2F6FE0",
        "SUCCESS": "#23D18B", "DANGER": "#F14C4C", "WARNING": "#F5C451",
        "CONSOLE_BG": "#14171C", "CONSOLE_TEXT": "#DCE1E8", "TX_TEXT": "#9AA4B2",
        "BANNER_BG": "#5C5326", "BANNER_TEXT": "#FFE9A3",
        "HOVER_BG": "#272B33", "DISABLED_BG": "#212429", "DISABLED_TEXT": "#5C6470",
        "SOFT_BG": "#22375C", "SOFT_BORDER": "#33507F",
        "SELECTION_BG": "#2C5480", "SELECTION_TEXT": "#FFFFFF",
        "TINT_SUCCESS": "#17372A", "TINT_WARNING": "#3B3115",
        "TINT_DANGER": "#3E1F22", "TINT_PRIMARY": "#22375C", "TINT_NEUTRAL": "#272B33",
    },
}
CURRENT = "light"

# 토큰의 초기값 = 라이트. set_theme() 이 globals() 를 갱신해 갈아끼운다 —
# 여기 이름을 명시해 두어야 정적 분석(ruff)이 이 이름들을 볼 수 있다.
BG = PALETTES["light"]["BG"]
CARD_BG = PALETTES["light"]["CARD_BG"]
BORDER = PALETTES["light"]["BORDER"]
TEXT = PALETTES["light"]["TEXT"]
TEXT_SUB = PALETTES["light"]["TEXT_SUB"]
PRIMARY = PALETTES["light"]["PRIMARY"]
PRIMARY_DARK = PALETTES["light"]["PRIMARY_DARK"]
SUCCESS = PALETTES["light"]["SUCCESS"]
DANGER = PALETTES["light"]["DANGER"]
WARNING = PALETTES["light"]["WARNING"]
CONSOLE_BG = PALETTES["light"]["CONSOLE_BG"]
CONSOLE_TEXT = PALETTES["light"]["CONSOLE_TEXT"]
TX_TEXT = PALETTES["light"]["TX_TEXT"]
BANNER_BG = PALETTES["light"]["BANNER_BG"]
BANNER_TEXT = PALETTES["light"]["BANNER_TEXT"]
HOVER_BG = PALETTES["light"]["HOVER_BG"]
DISABLED_BG = PALETTES["light"]["DISABLED_BG"]
DISABLED_TEXT = PALETTES["light"]["DISABLED_TEXT"]
SOFT_BG = PALETTES["light"]["SOFT_BG"]
SOFT_BORDER = PALETTES["light"]["SOFT_BORDER"]
SELECTION_BG = PALETTES["light"]["SELECTION_BG"]
SELECTION_TEXT = PALETTES["light"]["SELECTION_TEXT"]
TINT_SUCCESS = PALETTES["light"]["TINT_SUCCESS"]
TINT_WARNING = PALETTES["light"]["TINT_WARNING"]
TINT_DANGER = PALETTES["light"]["TINT_DANGER"]
TINT_PRIMARY = PALETTES["light"]["TINT_PRIMARY"]
TINT_NEUTRAL = PALETTES["light"]["TINT_NEUTRAL"]

UI_FONT = '"Pretendard", "Malgun Gothic", "Segoe UI", sans-serif'
MONO_FONT = '"Cascadia Mono", "Consolas", "D2Coding", monospace'

# ★색을 모듈 상수에 **값으로** 담으면 테마 교체가 먹지 않는다 (tr() 과 같은 함정) —
#   상태→토큰 이름만 두고, 실제 색은 쓸 때 찾는다.
STATE_TOKENS = {
    "connected": "SUCCESS",
    "reconnecting": "WARNING",
    "disconnected": "DANGER",
}
STATE_LABELS = {
    "connected": "Connected",
    "reconnecting": "Reconnecting",
    "disconnected": "Disconnected",
}

def build_qss() -> str:
    """현재 토큰으로 QSS 를 만든다 — 테마를 바꾸면 다시 부른다."""
    return f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: {UI_FONT};
    font-size: 13px;
}}
QFrame#card {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#card QLabel, QFrame#card QCheckBox {{ background: transparent; }}
QLabel#cardTitle {{ font-size: 14px; font-weight: 700; }}
QLabel#sectionLabel {{ color: {TEXT_SUB}; font-size: 11px; font-weight: 700; }}
QLabel#hint {{ color: {TEXT_SUB}; }}

QPushButton {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: {HOVER_BG}; }}
/* 포커스가 가면 버튼이 사라져 보이던 문제 — 테두리를 강조색으로 */
QPushButton:focus {{ border: 1px solid {PRIMARY}; }}
QPushButton:disabled {{ background: {DISABLED_BG}; color: {DISABLED_TEXT}; }}
QPushButton#primary {{
    background: {PRIMARY}; color: #FFFFFF; border: none; font-weight: 700;
    padding: 9px 18px;
}}
QPushButton#primary:hover {{ background: {PRIMARY_DARK}; }}
QPushButton#primary:disabled {{ background: {SOFT_BORDER}; color: {CARD_BG}; }}
QPushButton#danger {{ background: {DANGER}; color: #FFFFFF; border: none; font-weight: 700; }}
QPushButton#toolToggle {{
    padding: 3px 9px; border-radius: 7px; color: {TEXT_SUB};
}}
QPushButton#toolToggle:checked {{
    background: {SOFT_BG}; color: {PRIMARY}; border-color: {SOFT_BORDER}; font-weight: 700;
}}
QPushButton#segment {{
    border: none; background: transparent; color: {TEXT_SUB};
    padding: 8px 26px; border-radius: 9px; font-weight: 700;
}}
QPushButton#segment:checked {{ background: #E5E8EB; color: {TEXT}; }}

QLineEdit, QComboBox, QSpinBox {{
    background: {CARD_BG}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 6px 10px;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {PRIMARY}; }}
QLineEdit:disabled {{ background: {DISABLED_BG}; color: {DISABLED_TEXT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
/* 이름 버튼 — 값을 고르는 칸이므로 입력칸과 같은 모양으로 보인다.
   메뉴 표시는 텍스트 끝의 ▾ 하나로 충분하다 (Qt 기본 인디케이터는 모서리에 겹쳐 찍힌다). */
QToolButton#fieldButton {{
    background: {CARD_BG}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 6px 10px; text-align: left;
}}
QToolButton#fieldButton:hover {{ border-color: {PRIMARY}; }}
QToolButton#fieldButton::menu-indicator {{ image: none; width: 0; }}

QComboBox QAbstractItemView {{
    background: {CARD_BG}; border: 1px solid {BORDER};
    selection-background-color: {SELECTION_BG}; selection-color: {SELECTION_TEXT};
}}

/* 폰트는 QSS 로 지정하지 않는다 — QSS 폰트 룰이 있으면 repolish(레이아웃 전환 등)
   때마다 setFont() 로 준 줌 배율이 되돌려진다. 콘솔 폰트는 ConsolePane 이 코드로 건다. */
QPlainTextEdit, QTextEdit {{
    background: {CONSOLE_BG}; color: {CONSOLE_TEXT};
    border: 1px solid {BORDER}; border-radius: 10px;
    selection-background-color: {SELECTION_BG}; selection-color: {SELECTION_TEXT};
}}

QTableWidget {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background: {CARD_BG}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px; color: {TEXT_SUB}; font-weight: 700;
}}
QTableWidget::item:selected {{ background: {SELECTION_BG}; color: {SELECTION_TEXT}; }}

QSplitter::handle {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #D1D6DB; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #D1D6DB; border-radius: 5px; min-width: 30px; }}

QStatusBar {{ background: {BG}; color: {TEXT_SUB}; }}
QMenuBar {{ background: {BG}; }}
QMenuBar::item:selected {{ background: #E5E8EB; border-radius: 6px; }}
QMenu {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SELECTION_BG}; color: {SELECTION_TEXT}; }}
QCheckBox {{ spacing: 6px; }}
QToolTip {{ background: {TEXT}; color: #FFFFFF; border: none; padding: 6px 8px; }}"""


def apply_titlebar(widget) -> None:
    """창 제목표시줄도 테마를 따라간다 (Windows 11).

    Qt 는 제목표시줄을 그리지 않는다 — OS 가 그린다. DWM 속성으로 다크를 알려주지 않으면
    본문만 어둡고 위쪽만 하얗게 남는다 (실사용 신고).
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if CURRENT == "dark" else 0)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (구버전 빌드는 19)
        for attribute in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:  # noqa: BLE001 - 장식이 안 바뀔 뿐, 앱은 계속 돈다
        pass


def state_color(state: str) -> str:
    """상태 필 색 — 현재 팔레트에서 찾는다."""
    return globals().get(STATE_TOKENS.get(state, "DANGER"), DANGER)


def theme_names() -> list[str]:
    return ["light", "dark"]


def set_theme(name: str) -> str:
    """팔레트를 갈아끼우고 QSS 를 다시 만든다.

    UI 모듈은 전부 `from . import theme` 로 **모듈 참조**를 쓰므로(theme.BG)
    여기서 전역을 바꾸면 그대로 따라온다. 값으로 임포트하면 안 되는 이유다.
    """
    global CURRENT, QSS
    CURRENT = name if name in PALETTES else "light"
    globals().update(PALETTES[CURRENT])
    QSS = build_qss()
    return CURRENT


QSS = ""
set_theme(CURRENT)        # 임포트 시 라이트로 한 번 채운다 (app.py 가 다시 정한다)


def apply_theme(app) -> None:
    app.setStyleSheet(QSS)


class Card(QFrame):
    """§0 흰색 라운드 카드. title 을 주면 상단에 제목 라벨을 붙인다."""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)
        self.title_label: QLabel | None = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("cardTitle")
            self._layout.addWidget(self.title_label)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


class StatusPill(QLabel):
    """`● Connected` 형태의 상태 필 (UI 문서 §0 / §7)."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._current: tuple[str, str] | None = None
        self.set_state("disconnected", text)

    def set_state(self, state: str, text: str = "") -> None:
        # 50ms 마다 호출된다 — 값이 같으면 setStyleSheet 를 건너뛴다 (repolish 비용)
        if self._current == (state, text):
            return
        self._current = (state, text)
        color = state_color(state)
        label = text or STATE_LABELS.get(state, state)
        self.setText(f"● {label}")
        self.setStyleSheet(
            f"QLabel {{ background: {pill_tint(color)}; color: {color}; "
            f"border-radius: 12px; padding: 4px 12px; font-weight: 700; }}")


def pill_tint(hex_color: str) -> str:
    """상태색의 옅은 배경 — 필 안쪽 채움. 다크에서는 어두운 톤을 쓴다."""
    return {
        SUCCESS: TINT_SUCCESS,
        WARNING: TINT_WARNING,
        DANGER: TINT_DANGER,
        PRIMARY: TINT_PRIMARY,
    }.get(hex_color, TINT_NEUTRAL)


class SegmentedTabs(QWidget):
    """참조 화면(Operation/Configuration/...) 방식의 상단 세그먼트 탭."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        holder = QFrame(self)
        self._holder = holder
        holder.setStyleSheet(f"QFrame {{ background: {CARD_BG}; border: 1px solid {BORDER};"
                             " border-radius: 12px; }")
        row = QHBoxLayout(holder)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(4)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for index, label in enumerate(labels):
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            if index == 0:
                button.setChecked(True)
            self.group.addButton(button, index)
            row.addWidget(button)
        self.group.idClicked.connect(self.changed.emit)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        outer.addWidget(holder)
        outer.addStretch(1)


    def refresh_theme(self) -> None:
        """생성 때 한 번만 바른 배경을 다시 바른다 (QSS 로 덮이지 않는다)."""
        self._holder.setStyleSheet(f"QFrame {{ background: {CARD_BG}; border: 1px solid {BORDER};"
                             " border-radius: 12px; }")

    def set_index(self, index: int) -> None:
        button = self.group.button(index)
        if button is not None:
            button.setChecked(True)


def status_text(text: str, color: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"QLabel {{ color: {color}; background: transparent; }}")
    return label
