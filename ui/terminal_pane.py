"""TerminalPane / TerminalDock — ConPTY 셸(core/terminal.py)을 그리는 위젯.

설계문서 docs/superpowers/specs/2026-08-14-terminal-design.md §3.2.
렌더링은 pull 모델이다 — MainWindow 의 50ms tick 이 pump() 를 부르고, 버퍼의
generation 이 바뀐 경우에만 스냅샷을 떠서 다시 그린다. 자체 타이머는 없다.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFontDatabase, QFontMetricsF, QKeySequence, QPainter)
from PySide6.QtWidgets import (QApplication, QDockWidget, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QVBoxLayout, QWidget)

from ..core import terminal as terminal_core
from ..core.i18n import tr

# 기본 팔레트 — VS Code 터미널 계열. pyte 는 색을 이름("red")이나 hex("cd3131")로 준다.
_DEFAULT_FG = QColor("#cccccc")
_DEFAULT_BG = QColor("#101418")
_ANSI_COLORS = {
    "black": "#000000", "red": "#cd3131", "green": "#0dbc79", "brown": "#e5e510",
    "blue": "#2472c8", "magenta": "#bc3fbc", "cyan": "#11a8cd", "white": "#e5e5e5",
    "brightblack": "#666666", "brightred": "#f14c4c", "brightgreen": "#23d18b",
    "brightbrown": "#f5f543", "brightblue": "#3b8eea", "brightmagenta": "#d670d6",
    "brightcyan": "#29b8db", "brightwhite": "#ffffff",
}

_KEY_SEQUENCES = {
    Qt.Key_Return: "\r", Qt.Key_Enter: "\r",
    Qt.Key_Backspace: "\x7f",
    Qt.Key_Tab: "\t",
    Qt.Key_Escape: "\x1b",
    Qt.Key_Up: "\x1b[A", Qt.Key_Down: "\x1b[B",
    Qt.Key_Right: "\x1b[C", Qt.Key_Left: "\x1b[D",
    Qt.Key_Home: "\x1b[H", Qt.Key_End: "\x1b[F",
    Qt.Key_Delete: "\x1b[3~", Qt.Key_Insert: "\x1b[2~",
}


def encode_key(event) -> str:
    """QKeyEvent → 셸로 보낼 VT 시퀀스. 모르는 키는 event.text() 그대로."""
    key = event.key()
    if event.modifiers() & Qt.ControlModifier and Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key - Qt.Key_A + 1)   # Ctrl+A..Z = 제어 바이트 (Ctrl+C → ^C)
    sequence = _KEY_SEQUENCES.get(key)
    if sequence is not None:
        return sequence
    return event.text()


def _qcolor(name, default: QColor) -> QColor:
    if not name or name == "default":
        return default
    mapped = _ANSI_COLORS.get(name)
    if mapped is not None:
        return QColor(mapped)
    color = QColor(f"#{name}") if len(name) == 6 else QColor(name)
    return color if color.isValid() else default


class TerminalPane(QWidget):
    """모노스페이스 그리드 렌더러 + 키보드/IME → pty 입력."""

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._generation = -1
        self._frame = session.buffer.snapshot()
        self._was_alive = True
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(10)
        self.setFont(font)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)   # 한글 IME 입력
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.setMinimumSize(240, 120)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 시그니처
        return QSize(900, 320)

    # ------------------------------------------------------------------ 갱신

    def _cell_size(self) -> tuple[float, float]:
        metrics = QFontMetricsF(self.font())
        return metrics.horizontalAdvance("M"), metrics.height()

    def pump(self) -> None:
        """tick 에서 부른다 — 화면이 실제로 바뀐 경우에만 스냅샷·리페인트."""
        generation = self.session.buffer.generation
        alive = self.session.alive
        if generation != self._generation or alive != self._was_alive:
            self._generation = generation
            self._was_alive = alive
            self._frame = self.session.buffer.snapshot()
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt 시그니처
        painter = QPainter(self)
        painter.fillRect(self.rect(), _DEFAULT_BG)
        painter.setFont(self.font())
        cell_w, cell_h = self._cell_size()
        ascent = QFontMetricsF(self.font()).ascent()
        bold_font = self.font()
        bold_font.setBold(True)
        for y, runs in enumerate(self._frame.rows):
            x = 0.0
            for run in runs:
                width = cell_w * len(run.text)
                fg = _qcolor(run.fg, _DEFAULT_FG)
                bg = _qcolor(run.bg, _DEFAULT_BG)
                if run.reverse:
                    fg, bg = bg, fg
                if bg != _DEFAULT_BG:
                    painter.fillRect(QRectF(x, y * cell_h, width, cell_h), bg)
                if run.text.strip():
                    painter.setFont(bold_font if run.bold else self.font())
                    painter.setPen(fg)
                    painter.drawText(QPointF(x, y * cell_h + ascent), run.text)
                x += width
        cursor_x, cursor_y, cursor_visible = self._frame.cursor
        if cursor_visible and self._was_alive and self.hasFocus():
            block = QColor(_DEFAULT_FG)
            block.setAlpha(170)
            painter.fillRect(QRectF(cursor_x * cell_w, cursor_y * cell_h, cell_w, cell_h),
                             block)
        if not self._was_alive:
            banner = tr('셸이 종료되었습니다 (코드 {0}) — [재시작] 을 눌러 주세요').format(
                self.session.exit_status)
            painter.fillRect(QRectF(0, 0, self.width(), cell_h + 6), QColor(0, 0, 0, 180))
            painter.setPen(QColor("#f14c4c"))
            painter.drawText(QPointF(6, ascent + 3), banner)
        painter.end()

    # ------------------------------------------------------------------ 입력

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        if event.matches(QKeySequence.Paste) or (
                event.key() == Qt.Key_Insert and event.modifiers() & Qt.ShiftModifier):
            self._paste()
            event.accept()
            return
        if event.key() == Qt.Key_PageUp:
            self.session.buffer.page_up()
            self.pump()
            event.accept()
            return
        if event.key() == Qt.Key_PageDown:
            self.session.buffer.page_down()
            self.pump()
            event.accept()
            return
        data = encode_key(event)
        if data:
            self.session.write(data)
            event.accept()
            return
        super().keyPressEvent(event)

    def inputMethodEvent(self, event) -> None:  # noqa: N802 - 한글 IME 확정 문자열 전송
        commit = event.commitString()
        if commit:
            self.session.write(commit)
        event.accept()

    def _paste(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self.session.write(text)

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(tr('화면 전체 복사'),
                       lambda: QApplication.clipboard().setText(self.session.buffer.text()))
        menu.addAction(tr('붙여넣기'), self._paste)
        menu.addSeparator()
        menu.addAction(tr('재시작'), self.session.restart)
        menu.exec(self.mapToGlobal(pos))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        cell_w, cell_h = self._cell_size()
        cols = max(20, int(self.width() / cell_w))
        rows = max(5, int(self.height() / cell_h))
        self.session.resize(cols, rows)
        super().resizeEvent(event)


class TerminalDock(QDockWidget):
    """터미널을 감싸는 도크 — 메인 창에 붙이거나 떼어내 독립 창으로 쓴다."""

    closed = Signal(object)

    def __init__(self, parent: QWidget | None = None, session_factory=None):
        super().__init__(tr('터미널 — PowerShell'), parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setObjectName(f"terminal_dock_{id(self):x}")
        self.session = None
        self.pane: TerminalPane | None = None

        body = QWidget(self)
        outer = QVBoxLayout(body)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.admin_button = QPushButton(tr('관리자 PowerShell (외부 창)'))
        self.admin_button.setToolTip(
            tr('UAC 승격 셸은 창 안에 넣을 수 없어 외부 창으로 띄웁니다'))
        self.restart_button = QPushButton(tr('재시작'))
        top.addWidget(self.admin_button)
        top.addWidget(self.restart_button)
        top.addStretch(1)
        outer.addLayout(top)

        error = ""
        if terminal_core.TERMINAL_AVAILABLE:
            factory = session_factory or terminal_core.TerminalSession
            try:
                self.session = factory()
            except Exception as exc:  # noqa: BLE001 - 셸 기동 실패도 안내로 열화
                error = str(exc)
        if self.session is not None:
            self.pane = TerminalPane(self.session, body)
            outer.addWidget(self.pane, 1)
            self.restart_button.clicked.connect(self.session.restart)
        else:
            hint = QLabel(tr('내장 터미널을 쓰려면 pywinpty 와 pyte 를 설치해 주세요 '
                             '(pip install pywinpty pyte).')
                          + f"\n{terminal_core.TERMINAL_ERROR or error}")
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            outer.addWidget(hint, 1)
            self.restart_button.setEnabled(False)
        self.admin_button.clicked.connect(lambda: terminal_core.launch_admin_shell())
        self.setWidget(body)

    def pump(self) -> None:
        if self.pane is not None:
            self.pane.pump()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        self.closed.emit(self)
        if self.session is not None:
            self.session.close()   # 도크를 닫으면 셸도 끝낸다 — 백그라운드 잔류 금지
        super().closeEvent(event)
