"""Toss 계열 QSS · 컬러 토큰 · 공통 프리미티브(Card / StatusPill / SegmentedTabs).

UI 문서 §0 참조. 색은 여기 한 곳에서만 관리한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

BG = "#F2F4F6"
CARD_BG = "#FFFFFF"
BORDER = "#E5E8EB"
TEXT = "#191F28"
TEXT_SUB = "#8B95A1"
PRIMARY = "#3182F6"
PRIMARY_DARK = "#1B64DA"
SUCCESS = "#00C471"
DANGER = "#F04452"
WARNING = "#FFB331"
CONSOLE_BG = "#FFFFFF"
CONSOLE_TEXT = "#191F28"
TX_TEXT = "#4E5968"

UI_FONT = '"Pretendard", "Malgun Gothic", "Segoe UI", sans-serif'
MONO_FONT = '"Cascadia Mono", "Consolas", "D2Coding", monospace'

STATE_COLORS = {
    "connected": SUCCESS,
    "reconnecting": WARNING,
    "disconnected": DANGER,
}
STATE_LABELS = {
    "connected": "Connected",
    "reconnecting": "Reconnecting",
    "disconnected": "Disconnected",
}

QSS = f"""
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
QPushButton:hover {{ background: #F7F8F9; }}
QPushButton:disabled {{ background: #F2F4F6; color: #B0B8C1; }}
QPushButton#primary {{
    background: {PRIMARY}; color: #FFFFFF; border: none; font-weight: 700;
    padding: 9px 18px;
}}
QPushButton#primary:hover {{ background: {PRIMARY_DARK}; }}
QPushButton#primary:disabled {{ background: #C6D6F5; color: #FFFFFF; }}
QPushButton#danger {{ background: {DANGER}; color: #FFFFFF; border: none; font-weight: 700; }}
QPushButton#toolToggle {{
    padding: 3px 9px; border-radius: 7px; color: {TEXT_SUB};
}}
QPushButton#toolToggle:checked {{
    background: #E8F0FE; color: {PRIMARY}; border-color: #C6D6F5; font-weight: 700;
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
QLineEdit:disabled {{ background: #F2F4F6; color: #B0B8C1; }}
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
    background: {CARD_BG}; border: 1px solid {BORDER}; selection-background-color: #E8F0FE;
    selection-color: {TEXT};
}}

/* 폰트는 QSS 로 지정하지 않는다 — QSS 폰트 룰이 있으면 repolish(레이아웃 전환 등)
   때마다 setFont() 로 준 줌 배율이 되돌려진다. 콘솔 폰트는 ConsolePane 이 코드로 건다. */
QPlainTextEdit, QTextEdit {{
    background: {CONSOLE_BG}; color: {CONSOLE_TEXT};
    border: 1px solid {BORDER}; border-radius: 10px;
    selection-background-color: #CFE3FF; selection-color: {TEXT};
}}

QTableWidget {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background: {CARD_BG}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px; color: {TEXT_SUB}; font-weight: 700;
}}
QTableWidget::item:selected {{ background: #E8F0FE; color: {TEXT}; }}

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
QMenu::item:selected {{ background: #E8F0FE; }}
QCheckBox {{ spacing: 6px; }}
QToolTip {{ background: {TEXT}; color: #FFFFFF; border: none; padding: 6px 8px; }}
"""


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
        color = STATE_COLORS.get(state, DANGER)
        label = text or STATE_LABELS.get(state, state)
        self.setText(f"● {label}")
        self.setStyleSheet(
            f"QLabel {{ background: {_tint(color)}; color: {color}; "
            f"border-radius: 12px; padding: 4px 12px; font-weight: 700; }}")


def _tint(hex_color: str) -> str:
    """상태색의 옅은 배경 — 필 안쪽 채움용."""
    return {
        SUCCESS: "#E7F9F1",
        WARNING: "#FFF6E5",
        DANGER: "#FEECEE",
        PRIMARY: "#E8F0FE",
    }.get(hex_color, "#F2F4F6")


class SegmentedTabs(QWidget):
    """참조 화면(Operation/Configuration/...) 방식의 상단 세그먼트 탭."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        holder = QFrame(self)
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

    def set_index(self, index: int) -> None:
        button = self.group.button(index)
        if button is not None:
            button.setChecked(True)


def status_text(text: str, color: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"QLabel {{ color: {color}; background: transparent; }}")
    return label
