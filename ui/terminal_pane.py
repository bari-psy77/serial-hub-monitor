"""TerminalPane / TerminalDock — ConPTY 셸(core/terminal.py)을 그리는 위젯.

설계문서 docs/superpowers/specs/2026-08-14-terminal-design.md §3.2.
렌더링은 pull 모델이다 — MainWindow 의 50ms tick 이 pump() 를 부르고, 버퍼의
generation 이 바뀐 경우에만 스냅샷을 떠서 다시 그린다. 자체 타이머는 없다.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter
from PySide6.QtWidgets import (QApplication, QDockWidget, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QScrollBar, QVBoxLayout, QWidget)

from ..core import terminal as terminal_core
from ..core.i18n import tr
from . import theme
from .dock_common import make_maximize_button

# 기본 팔레트 — VS Code 터미널 계열. pyte 는 색을 이름("red")이나 hex("cd3131")로 준다.
# 터미널도 테마를 따라간다 (사용자 결정). 라이트는 밝은 배경 + 어두운 글자.
TERMINAL_PALETTES = {
    "dark": {"fg": "#cccccc", "bg": "#101418"},
    "light": {"fg": "#1F2328", "bg": "#FBFCFD"},
}
_DEFAULT_FG = QColor("#cccccc")
_DEFAULT_BG = QColor("#101418")
_ANSI_LIGHT = {
    "black": "#1F2328", "red": "#B22222", "green": "#137333", "brown": "#8A6D00",
    "blue": "#1A5FB4", "magenta": "#8E44AD", "cyan": "#0E7490", "white": "#5B6770",
    "brightblack": "#6B7280", "brightred": "#D93025", "brightgreen": "#188038",
    "brightbrown": "#B7791F", "brightblue": "#1967D2", "brightmagenta": "#A142F4",
    "brightcyan": "#12869A", "brightwhite": "#202124",
}
_ANSI_DARK = {
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
    Qt.Key_Backtab: "\x1b[Z",   # Shift+Tab — 셸의 역방향 자동완성
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


def terminal_palette(theme_name: str) -> dict:
    """터미널 셀 색표 — 테마를 따라간다."""
    name = theme_name if theme_name in TERMINAL_PALETTES else "dark"
    base = TERMINAL_PALETTES[name]
    return {"fg": QColor(base["fg"]), "bg": QColor(base["bg"]),
            "ansi": _ANSI_LIGHT if name == "light" else _ANSI_DARK}


def _qcolor(name, default: QColor, table: dict | None = None) -> QColor:
    if not name or name == "default":
        return default
    mapped = (table or _ANSI_DARK).get(name)
    if mapped is not None:
        return QColor(mapped)
    color = QColor(f"#{name}") if len(name) == 6 else QColor(name)
    return color if color.isValid() else default


class TerminalScreen(QWidget):
    """실제 글자를 그리는 격자 — 스크롤바와 나란히 놓기 위해 TerminalPane 이 감싼다."""

    def __init__(self, owner: "TerminalPane"):
        super().__init__(owner)
        self._owner = owner
        self.setFocusPolicy(Qt.NoFocus)      # 키 입력은 TerminalPane 이 받는다

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        self._owner.paint_screen(self, event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - 휠은 화면 위젯이 먼저 받는다
        self._owner.wheelEvent(event)


class TerminalPane(QWidget):
    """모노스페이스 그리드 렌더러 + 키보드/IME → pty 입력 + 세로 스크롤바."""

    zoom_requested = Signal(int)      # Ctrl+휠 — 소유자가 터미널 공통으로 적용한다

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._generation = -1
        self._frame = session.buffer.snapshot()
        self._was_alive = True
        # ★위젯 폰트(self.font())를 쓰면 안 된다 — 테마 QSS(font-family: UI_FONT)가
        #   polish 때 프로포셔널 폰트로 덮어써 격자 계산이 전부 어긋난다 (실기 확인).
        #   터미널 폰트는 멤버로 고정하고 메트릭·페인트에 직접 쓴다.
        self.palette_colors = terminal_palette(theme.CURRENT)
        self._term_font = QFont()
        self._term_font.setFamilies(["Cascadia Mono", "Consolas", "D2Coding"])
        self._term_font.setStyleHint(QFont.Monospace)
        self._term_font.setPointSize(10)
        self._bold_font = QFont(self._term_font)
        self._bold_font.setBold(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)   # 한글 IME 입력
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.setMinimumSize(240, 120)

        self.screen = TerminalScreen(self)
        self.scrollbar = QScrollBar(Qt.Vertical, self)
        self.scrollbar.setObjectName("terminalScroll")
        self.scrollbar.setRange(0, 0)
        self.scrollbar.valueChanged.connect(self._on_scrollbar)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.screen, 1)
        layout.addWidget(self.scrollbar)
        self._syncing_scrollbar = False
        self._sync_scrollbar()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 시그니처
        return QSize(900, 320)

    # ------------------------------------------------------------------ 스크롤

    def _sync_scrollbar(self) -> None:
        """버퍼의 스크롤 위치를 스크롤바에 반영 — 되돌아오는 valueChanged 는 무시한다."""
        value, maximum = self.session.buffer.scroll_state()
        self._syncing_scrollbar = True
        try:
            self.scrollbar.setRange(0, maximum)
            self.scrollbar.setPageStep(max(1, self.session.buffer.rows))
            self.scrollbar.setValue(value)
        finally:
            self._syncing_scrollbar = False

    def _on_scrollbar(self, value: int) -> None:
        if self._syncing_scrollbar:
            return
        self.session.buffer.scroll_to(value)
        self.pump()

    # ------------------------------------------------------------------ 갱신

    def _cell_size(self) -> tuple[float, float]:
        metrics = QFontMetricsF(self._term_font)
        return metrics.horizontalAdvance("M"), metrics.height()

    def pump(self) -> None:
        """tick 에서 부른다 — 화면이 실제로 바뀐 경우에만 스냅샷·리페인트."""
        generation = self.session.buffer.generation
        alive = self.session.alive
        if generation != self._generation or alive != self._was_alive:
            self._generation = generation
            self._was_alive = alive
            self._frame = self.session.buffer.snapshot()
            self._sync_scrollbar()
            self.screen.update()

    def paint_screen(self, target: QWidget, _event) -> None:
        """TerminalScreen 이 위임하는 실제 그리기 — 좌표계는 격자 원점(0,0)이다."""
        painter = QPainter(target)
        default_fg = self.palette_colors["fg"]
        default_bg = self.palette_colors["bg"]
        ansi_table = self.palette_colors["ansi"]
        painter.fillRect(target.rect(), default_bg)
        painter.setFont(self._term_font)
        cell_w, cell_h = self._cell_size()
        ascent = QFontMetricsF(self._term_font).ascent()
        bold_font = self._bold_font
        for y, runs in enumerate(self._frame.rows):
            x = 0.0
            for run in runs:
                # ★len(text) 가 아니라 cells 로 전진한다 — 전각(한글)은 글자 1개 = 2칸
                width = cell_w * run.cells
                fg = _qcolor(run.fg, default_fg, ansi_table)
                bg = _qcolor(run.bg, default_bg, ansi_table)
                if run.reverse:
                    fg, bg = bg, fg
                if bg != default_bg:
                    painter.fillRect(QRectF(x, y * cell_h, width, cell_h), bg)
                if run.text.strip():
                    painter.setFont(bold_font if run.bold else self._term_font)
                    painter.setPen(fg)
                    # ★글자를 격자 칸 위치에 하나씩 놓는다. 문자열째로 그리면 폰트의
                    #   실제 advance 와 cell_w 의 오차가 누적돼 run 경계(색 바뀌는
                    #   지점)마다 틈이 생긴다 (실기 스크린샷으로 확인).
                    baseline = y * cell_h + ascent
                    if run.cells == 2 and len(run.text) == 1:
                        painter.drawText(QPointF(x, baseline), run.text)   # 전각 1글자
                    else:
                        for index, ch in enumerate(run.text):
                            if ch != " ":
                                painter.drawText(QPointF(x + index * cell_w, baseline), ch)
                x += width
        cursor_x, cursor_y, cursor_visible = self._frame.cursor
        if cursor_visible and self._was_alive and (self.hasFocus() or self.screen.hasFocus()):
            block = QColor(default_fg)
            block.setAlpha(170)
            painter.fillRect(QRectF(cursor_x * cell_w, cursor_y * cell_h, cell_w, cell_h),
                             block)
        if not self._was_alive:
            banner = tr('셸이 종료되었습니다 (코드 {0}) — [재시작] 을 눌러 주세요').format(
                self.session.exit_status)
            painter.fillRect(QRectF(0, 0, target.width(), cell_h + 6), QColor(0, 0, 0, 180))
            painter.setPen(QColor("#f14c4c"))
            painter.drawText(QPointF(6, ascent + 3), banner)
        painter.end()

    # ------------------------------------------------------------------ 입력

    def focusNextPrevChild(self, _next: bool) -> bool:  # noqa: N802 - Qt 시그니처
        """Tab 을 포커스 이동에 뺏기지 않는다.

        ★QWidget.event() 는 keyPressEvent **앞에서** Tab/Shift+Tab 을 가로채
        focusNextPrevChild() 를 부른다. 그게 True 를 돌려주면 키는 거기서 끝나고,
        터미널에서는 셸 자동완성이 통째로 죽는다 (실기 신고 — 도크의 버튼으로 포커스만
        옮겨갔다). False 를 돌려주면 Tab 이 keyPressEvent 로 내려온다.
        """
        return False

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        if event.matches(QKeySequence.Paste) or (
                event.key() == Qt.Key_Insert and event.modifiers() & Qt.ShiftModifier):
            self._paste()
            event.accept()
            return
        if event.key() == Qt.Key_PageUp:
            for _ in range(5):        # 페이지 = 휠 5칸 분량 (약 반 화면)
                self.session.buffer.page_up()
            self.pump()
            event.accept()
            return
        if event.key() == Qt.Key_PageDown:
            for _ in range(5):
                self.session.buffer.page_down()
            self.pump()
            event.accept()
            return
        data = encode_key(event)
        if data:
            # 타이핑하면 스크롤백을 접는다 — 실제 터미널과 같은 동작
            self.session.buffer.scroll_to_bottom()
            self.session.write(data)
            event.accept()
            return
        super().keyPressEvent(event)

    def refresh_theme(self) -> None:
        """셀 색표를 새 테마로 바꾸고 다시 그린다."""
        self.palette_colors = terminal_palette(theme.CURRENT)
        self.screen.update()      # 폰트는 소유자가 프로파일 값으로 다시 건다

    def set_font_size(self, point_size: int) -> None:
        """터미널 격자 폰트 — 콘솔과 별개 값이다 (격자 계산이 폰트에 묶여 있다)."""
        size = max(6, min(24, int(point_size)))
        self._term_font.setPointSize(size)
        self._bold_font.setPointSize(size)
        self.session.resize(*self._grid_size())
        self._sync_scrollbar()
        self.screen.update()

    def font_size(self) -> int:
        return self._term_font.pointSize()

    def _grid_size(self) -> tuple[int, int]:
        cell_w, cell_h = self._cell_size()
        return (max(20, int(self.screen.width() / cell_w)),
                max(5, int(self.screen.height() / cell_h)))

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.ControlModifier and delta:
            self.zoom_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        if delta == 0:
            super().wheelEvent(event)
            return
        for _ in range(max(1, abs(delta) // 120)):
            if delta > 0:
                self.session.buffer.page_up()
            else:
                self.session.buffer.page_down()
        self.pump()
        event.accept()

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
        # 스크롤바가 차지하는 폭을 빼고 격자를 잡는다 (screen 위젯 기준)
        self.session.resize(*self._grid_size())
        self._sync_scrollbar()
        super().resizeEvent(event)


class TerminalDock(QDockWidget):
    """터미널을 감싸는 도크 — 메인 창에 붙이거나 떼어내 독립 창으로 쓴다."""

    closed = Signal(object)
    _serial = 0   # id() 는 재사용돼 이름이 겹칠 수 있다 — 단조 증가 번호를 쓴다

    def __init__(self, parent: QWidget | None = None, session_factory=None):
        super().__init__(tr('터미널 — PowerShell'), parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        TerminalDock._serial += 1
        self.setObjectName(f"terminal_dock_{TerminalDock._serial}")
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
        self.maximize_button = make_maximize_button(self)
        top.addWidget(self.maximize_button)
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

    def refresh_theme(self) -> None:
        if self.pane is not None:
            self.pane.refresh_theme()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        self.closed.emit(self)
        if self.session is not None:
            self.session.close()   # 도크를 닫으면 셸도 끝낸다 — 백그라운드 잔류 금지
        super().closeEvent(event)
