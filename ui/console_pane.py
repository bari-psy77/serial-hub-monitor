"""ConsolePane — 포트 1개(또는 병합)의 콘솔 + 인라인 검색바. UI 문서 §2.

표시 전용이다. LogStore 를 50ms 주기로 pull 해서 새 라인만 덧붙인다
(라인마다 시그널을 쏘면 firehose 에서 이벤트 큐가 포화된다 — 설계 §3.1).
"""

from __future__ import annotations

import re
import time

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QKeySequence, QShortcut,
                           QSyntaxHighlighter, QTextBlockUserData, QTextCharFormat, QTextCursor,
                           QTextDocument)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget)

from ..core import filters as filters_mod
from ..core.filters import HighlightRule, compile_pattern
from ..core.logstore import (TS_ABSOLUTE, TS_MODES, TS_OFF, TS_RELATIVE, LogStore,
                             render_line, render_prefix_len)
from ..core import ansi
from . import theme
from ..core.i18n import tr

# 헤더 버튼은 아이콘 하나로 — 글자가 들어가면 콘솔 제목을 밀어낸다. 뜻은 툴팁으로 알린다.
TS_BUTTON_ICON = {TS_ABSOLUTE: "🕘", TS_RELATIVE: "⏱", TS_OFF: "🚫"}
TS_BUTTON_HINT = {TS_ABSOLUTE: '절대 시각', TS_RELATIVE: '상대 시각(경과)', TS_OFF: '시각 표시 끔'}
MAX_SEARCH_MATCHES = 2000
PUMP_LIMIT = 20_000
# 다시 그리기(타임스탬프/빈줄 토글)는 전체 스크롤백을 다시 렌더하면 그동안 UI 가 멈춘다.
# 50k 는 실측 1.3~1.6s 로 너무 길어서 20k(~0.5s)로 잡고, 잘린 만큼은 화면에 명시한다.
RELOAD_LIMIT = 20_000
SEARCH_DEBOUNCE_MS = 250
# 라인이 계속 들어오면 F3 마다 전체 재스캔(실측 150~190ms)이 걸린다. 이 간격 안에서는
# 직전 결과를 재사용하고, 지나면 새로 들어온 라인까지 포함해 다시 찾는다.
SEARCH_RESCAN_MIN_S = 0.5
_TX_LINE_RE = r"(?:^|(?<=\] ))>>> .*$"
_BANNER_LINE_RE = r"(?:^|(?<=\] ))!!.*$"


# (토큰, 배경여부, 테마) -> QColor. 테마가 바뀌면 키가 달라져 자연히 갈린다
_SPAN_COLOR_CACHE: dict = {}


class AnsiBlockData(QTextBlockUserData):
    """그 줄이 펌웨어에서 받은 색 구간. 블록에 붙여두면 스크롤백이 잘려도 따라간다."""

    def __init__(self, spans: tuple):
        super().__init__()
        self.spans = spans


class LineHighlighter(QSyntaxHighlighter):
    """펌웨어 ANSI 색 + 사용자 키워드 룰 + TX 에코 / `!!` 배너 내장 스타일 (FR-5)."""

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self.show_ansi = True
        self.rules: list[HighlightRule] = []
        self.set_rules([])

    def set_rules(self, rules: list[HighlightRule]) -> None:
        self.rules = list(rules)
        self.rebuild_formats()

    def rebuild_formats(self) -> None:
        """포맷을 현재 팔레트로 다시 만든다 — 테마를 바꾸면 색이 전부 달라진다."""
        compiled: list[tuple[re.Pattern, QTextCharFormat]] = []

        tx_format = QTextCharFormat()
        tx_format.setForeground(QColor(theme.TX_TEXT))
        tx_format.setFontWeight(700)
        compiled.append((re.compile(_TX_LINE_RE, re.MULTILINE), tx_format))

        banner_format = QTextCharFormat()
        banner_format.setBackground(QColor(theme.BANNER_BG))
        banner_format.setForeground(QColor(theme.BANNER_TEXT))
        compiled.append((re.compile(_BANNER_LINE_RE, re.MULTILINE), banner_format))

        for rule in self.rules:
            rx = rule.compiled()
            if rx is None:
                continue
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(rule.qcolor_hex()))
            compiled.append((rx, fmt))
        self._rules = compiled
        self.rehighlight()

    @staticmethod
    def span_color(token: str, background: bool):
        """span 토큰 -> QColor. 캐시해 두면 hex 문자열을 매번 파싱하지 않는다 (8배 빠름)."""
        if not token:
            return None
        key = (token, background, ansi._CURRENT)
        color = _SPAN_COLOR_CACHE.get(key)
        if color is None:
            hex_value = ansi.resolve(token, background=background)
            if not hex_value:
                return None
            color = QColor(hex_value)
            _SPAN_COLOR_CACHE[key] = color
        return color

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt 시그니처
        # 펌웨어 색을 먼저 깔고, 사용자 룰을 그 위에 덮는다 (룰이 우선)
        data = self.currentBlockUserData()
        if self.show_ansi and isinstance(data, AnsiBlockData):
            for start, end, fg, bg, bold in data.spans:
                if end <= start or start >= len(text):
                    continue
                fmt = QTextCharFormat()
                fg_color = self.span_color(fg, False)
                bg_color = self.span_color(bg, True)
                if fg_color is not None:
                    fmt.setForeground(fg_color)
                if bg_color is not None:
                    fmt.setBackground(bg_color)
                if bold:
                    fmt.setFontWeight(700)
                self.setFormat(start, min(end, len(text)) - start, fmt)
        for rx, fmt in self._rules:
            for match in rx.finditer(text):
                start, end = match.span()
                if end > start:
                    self.setFormat(start, end - start, fmt)


class HistoryCombo(QComboBox):
    """최근 입력을 드롭다운으로 보여주는 입력창.

    마우스로 눌러 지난 검색어를 고를 수 있어야 한다는 요구 — 재실행해도 유지되도록
    목록은 프로파일에 저장한다.
    """

    returnPressed = Signal()  # noqa: N815 - QLineEdit 시그니처를 흉내낸다

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(15)
        self.lineEdit().installEventFilter(self)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        """★키가 **콤보 자신**에게 올 때의 경로.

        `setFocus()` 로 포커스를 주면 포커스 위젯은 lineEdit 이 아니라 콤보다
        (Ctrl+F / Ctrl+` 로 들어오는 경우가 전부 여기). 이때 QComboBox 는 키를
        `lineEdit->event()` 로 넘기는데, 그 호출은 **이벤트 필터를 타지 않는다** —
        그래서 필터만으로는 Enter 가 통째로 사라진다. 여기서 직접 받는다.
        """
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 시그니처
        """키가 **lineEdit** 에게 직접 올 때의 경로 (마우스로 눌러 편집 중).

        QLineEdit 은 Return 을 처리한 뒤 ignore() 해서 부모로 흘려보내는데, 편집 가능한
        QComboBox 는 그걸 다시 lineEdit 으로 돌려준다 — returnPressed 가 두 번 발생해
        "다음 매치" 가 두 칸씩 건너뛴다. True 를 돌려 전파를 끊는다.
        """
        if (obj is self.lineEdit() and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)):
            self.returnPressed.emit()
            return True
        return super().eventFilter(obj, event)

    # QLineEdit 처럼 쓰기 위한 얇은 위임
    def text(self) -> str:
        return self.currentText()

    def setText(self, value: str) -> None:  # noqa: N802 - Qt 시그니처 흉내
        self.setEditText(value)

    def setPlaceholderText(self, value: str) -> None:  # noqa: N802
        self.lineEdit().setPlaceholderText(value)

    def selectAll(self) -> None:  # noqa: N802
        self.lineEdit().selectAll()

    def setCursorPosition(self, pos: int) -> None:  # noqa: N802
        self.lineEdit().setCursorPosition(pos)

    def cursorPosition(self) -> int:  # noqa: N802
        return self.lineEdit().cursorPosition()

    @property
    def textChanged(self):
        return self.editTextChanged

    def load_history(self, items: list[str]) -> None:
        current = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems([item for item in items if item])
        self.setEditText(current)
        self.blockSignals(False)

    def remember(self, value: str, store: list[str], limit: int = 30) -> None:
        value = value.strip()
        if not value:
            return
        if value in store:
            store.remove(value)
        store.append(value)
        del store[:-limit]
        self.load_history(list(reversed(store)))


class SearchBar(QWidget):
    """인크리멘털 검색. 새로 들어오는 라인은 다음 검색 동작 때 반영된다."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.edit = HistoryCombo()
        self.edit.setPlaceholderText(tr('검색 (Enter/F3 다음, Shift+F3 이전) — 눌러서 최근 검색어 선택'))
        self.case_box = QCheckBox("Aa")
        self.case_box.setToolTip(tr('대소문자 구분'))
        self.regex_box = QCheckBox(".*")
        self.regex_box.setToolTip(tr('정규식'))
        self.count_label = QLabel("0/0")
        self.count_label.setObjectName("hint")
        self.prev_button = QPushButton("↑")
        self.next_button = QPushButton("↓")
        self.close_button = QPushButton("✕")
        for button in (self.prev_button, self.next_button, self.close_button):
            button.setFixedWidth(30)

        row.addWidget(QLabel("🔍"))
        row.addWidget(self.edit, 1)
        row.addWidget(self.case_box)
        row.addWidget(self.regex_box)
        row.addWidget(self.count_label)
        row.addWidget(self.prev_button)
        row.addWidget(self.next_button)
        row.addWidget(self.close_button)

        self.close_button.clicked.connect(self.closed.emit)


class ConsolePane(QWidget):
    """ports 가 2개 이상이면 병합 뷰 — 라인마다 `[MLOG]` prefix 를 붙인다 (FR-3)."""

    focus_gained = Signal(str)
    pop_out_requested = Signal(object)
    search_committed = Signal(str)
    zoom_requested = Signal(int)      # Ctrl+휠 — 소유자가 전 콘솔에 공통 적용한다

    def __init__(self, title: str, store: LogStore, ports: list[str],
                 ts_mode: str = TS_ABSOLUTE, hide_empty: bool = True,
                 max_blocks: int = 200_000, parent: QWidget | None = None):
        super().__init__(parent)
        self.title = title
        self.store = store
        self.ports = list(ports)
        self.show_prefix = len(self.ports) != 1
        self.ts_mode = ts_mode if ts_mode in TS_MODES else TS_ABSOLUTE
        self.hide_empty = hide_empty
        self.scroll_lock = False
        self.extra_filter = None  # FilterView 가 필터 조건을 꽂는 자리
        self._cursor_seq = -1
        self._pending_new = 0
        self._search_dirty = True
        self._matches: list[tuple[int, int]] = []
        self._match_index = -1
        self._last_search_at = 0.0

        # 최소 높이를 작게 잡아야 레이아웃을 바꿔도 하단(명령 패널)이 밀려 잘리지 않는다
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(90)

        card = theme.Card(parent=self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        body = card.body()

        header = QHBoxLayout()
        header.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.state_pill = theme.StatusPill()
        self.new_button = QPushButton("↓ 0 new")
        self.new_button.setObjectName("toolToggle")
        self.new_button.hide()

        self.ts_button = QPushButton(TS_BUTTON_ICON[self.ts_mode])
        self.ts_button.setObjectName("toolToggle")
        self._refresh_ts_button()
        self.empty_button = QPushButton("∅")
        self.empty_button.setObjectName("toolToggle")
        self.empty_button.setCheckable(True)
        self.empty_button.setChecked(hide_empty)
        self.empty_button.setToolTip(tr('빈 라인 숨김 — 펌웨어가 뱉는 빈 줄 다발을 걸러냅니다'))
        self.lock_button = QPushButton("⏸")
        self.lock_button.setObjectName("toolToggle")
        self.lock_button.setCheckable(True)
        self.lock_button.setToolTip(tr('자동 스크롤 정지 (Ctrl+Space) — 수신·기록은 계속됩니다'))
        self.search_button = QPushButton("🔍")
        self.search_button.setObjectName("toolToggle")
        self.search_button.setToolTip(tr('검색 (Ctrl+F)'))
        self.clear_button = QPushButton("🗑")
        self.clear_button.setObjectName("toolToggle")
        self.clear_button.setToolTip(tr('이 콘솔 화면 지우기 (Ctrl+L) — 로그 파일은 그대로'))
        self.pop_button = QPushButton("⧉")
        self.pop_button.setObjectName("toolToggle")
        self.pop_button.setToolTip(tr('별도 창으로 분리 (닫으면 원래 자리로 복귀)'))

        header.addWidget(self.title_label)
        header.addWidget(self.state_pill)
        header.addStretch(1)
        header.addWidget(self.new_button)
        for button in (self.ts_button, self.empty_button, self.lock_button, self.search_button,
                       self.clear_button, self.pop_button):
            button.setFixedWidth(34)   # 아이콘 전용 — 폭을 맞춰 줄이 흔들리지 않게
            header.addWidget(button)
        body.addLayout(header)

        families = QFontDatabase.families()
        self._font_family = next((f for f in ("Cascadia Mono", "Consolas", "D2Coding")
                                  if f in families), "monospace")
        self.view = QPlainTextEdit()
        self.set_font_size(12)
        self.view.setReadOnly(True)
        self.view.setUndoRedoEnabled(False)
        self.view.setMaximumBlockCount(max_blocks)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setFocusPolicy(Qt.StrongFocus)
        self.view.setMinimumHeight(40)
        body.addWidget(self.view, 1)

        self.highlighter = LineHighlighter(self.view.document())

        # 스크롤백이 크면 검색 1회가 수백만 자를 훑는다 — 타이핑마다 돌리지 않는다
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._run_search)

        self.search = SearchBar()
        self.search.hide()
        body.addWidget(self.search)

        self.ts_button.clicked.connect(self.cycle_ts_mode)
        self.empty_button.toggled.connect(self._on_hide_empty)
        self.lock_button.toggled.connect(self._on_scroll_lock)
        self.search_button.clicked.connect(self.focus_search)
        self.clear_button.clicked.connect(self.clear_view)
        self.pop_button.clicked.connect(lambda: self.pop_out_requested.emit(self))
        self.new_button.clicked.connect(self._jump_to_end)
        self.search.closed.connect(self.close_search)
        self.search.edit.textChanged.connect(self._on_search_changed)
        self.search.edit.returnPressed.connect(self._on_search_enter)
        self.search.case_box.toggled.connect(self._on_search_changed)
        self.search.regex_box.toggled.connect(self._on_search_changed)
        self.search.next_button.clicked.connect(lambda: self.step_match(1))
        self.search.prev_button.clicked.connect(lambda: self.step_match(-1))

        # 패널이 여러 개라 창 단위 컨텍스트로 두면 Qt 가 "ambiguous shortcut" 으로 전부 무시한다
        for keys, slot in (("Ctrl+F", self.focus_search),
                           ("F3", lambda: self.step_match(1)),
                           ("Shift+F3", lambda: self.step_match(-1))):
            shortcut = QShortcut(QKeySequence(keys), self, activated=slot)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        # ★Enter 는 QShortcut 으로 잡으면 안 된다. 단축키가 포커스 위젯보다 먼저 먹어서
        # 검색창의 returnPressed(= 다음 매치)가 아예 발생하지 않는다. 콘솔 본문에
        # 이벤트 필터를 걸어, 본문에 포커스가 있을 때만 스크롤 잠금을 푼다.
        self.view.installEventFilter(self)
        # 스크롤바가 휠을 먼저 먹어 Ctrl+휠 확대가 그 위에서만 안 먹었다 (실사용 신고)
        self.view.verticalScrollBar().installEventFilter(self)
        self.view.horizontalScrollBar().installEventFilter(self)
        escape = QShortcut(QKeySequence("Esc"), self.search, activated=self.close_search)
        escape.setContext(Qt.WidgetWithChildrenShortcut)

    # ------------------------------------------------------------------ 헤더

    def set_state(self, state: str, subtitle: str = "") -> None:
        self.state_pill.set_state(state)
        self.title_label.setText(f"{self.title}  {subtitle}" if subtitle else self.title)

    # ------------------------------------------------------------------ 표시 옵션

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        """Ctrl+휠 = 글자 크기. Ctrl 없이는 평소대로 스크롤한다."""
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y()
            if steps:
                self.zoom_requested.emit(1 if steps > 0 else -1)
                event.accept()
                return
        super().wheelEvent(event)

    def refresh_theme(self) -> None:
        """테마 교체 후 다시 칠한다 — 캐시·정적 포맷·폰트를 순서대로 되살린다.

        폰트는 여기서 건드리지 않는다 — repolish 직후 위젯에서 크기를 읽으면 무효값
        (-1)이 나와 최소값으로 주저앉는다. 정본은 프로파일이므로 소유자가 다시 건다.
        """
        _SPAN_COLOR_CACHE.clear()
        self.highlighter.rebuild_formats()   # rehighlight 까지 여기서 일어난다

    def set_font_size(self, point_size: int) -> None:
        """콘솔 폰트는 QSS 가 아니라 여기서만 정한다 (theme.py 주석 참조).

        QSS 에 폰트 룰이 있으면 repolish 마다 줌이 12px 로 되돌아간다.
        """
        font = QFont(self._font_family)
        font.setPointSize(max(7, min(28, point_size)))
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        self.view.setFont(font)

    def font_size(self) -> int:
        return self.view.font().pointSize()

    def set_word_wrap(self, enabled: bool) -> None:
        self.view.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if enabled else QPlainTextEdit.NoWrap)

    def cycle_ts_mode(self) -> None:
        order = list(TS_MODES)
        self.ts_mode = order[(order.index(self.ts_mode) + 1) % len(order)]
        self._refresh_ts_button()
        self.reload()

    def _refresh_ts_button(self) -> None:
        self.ts_button.setText(TS_BUTTON_ICON[self.ts_mode])
        self.ts_button.setToolTip(
            tr('타임스탬프: {0} — 눌러서 전환 (Ctrl+T)').format(tr(TS_BUTTON_HINT[self.ts_mode])))

    def _on_hide_empty(self, checked: bool) -> None:
        self.hide_empty = checked
        self.reload()

    def _on_scroll_lock(self, checked: bool) -> None:
        self.scroll_lock = checked
        if not checked:
            self._jump_to_end()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 시그니처
        # ★휠은 본문(QPlainTextEdit)이 먼저 받는다 — pane 의 wheelEvent 까지
        #   올라오지 않으므로 여기서 Ctrl+휠을 가로챈다
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier \
                and obj in (self.view, self.view.verticalScrollBar(),
                            self.view.horizontalScrollBar()):
            steps = event.angleDelta().y()
            if steps:
                self.zoom_requested.emit(1 if steps > 0 else -1)
                return True
        if (obj is self.view and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)):
            self._enter_pressed()
            return True
        return super().eventFilter(obj, event)

    def _enter_pressed(self) -> None:
        """콘솔 본문에서 Enter — 자동 스크롤을 풀고 맨 아래로."""
        if self.lock_button.isChecked():
            self.lock_button.setChecked(False)   # 풀리면서 _jump_to_end 가 돈다
        else:
            self._jump_to_end()

    def set_highlight_rules(self, rules: list[HighlightRule]) -> None:
        self.highlighter.set_rules(rules)

    def set_ansi_color(self, enabled: bool) -> None:
        """펌웨어가 보낸 색을 화면에 살릴지. 끄면 본문만 (파일은 어느 쪽이든 색 코드 없음)."""
        if self.highlighter.show_ansi != enabled:
            self.highlighter.show_ansi = enabled
            self.highlighter.rehighlight()

    def accepts(self, line) -> bool:
        if self.hide_empty and not line.text.strip():
            return False
        if self.extra_filter is not None and not self.extra_filter(line):
            return False
        return True

    # ------------------------------------------------------------------ 갱신

    def pump(self) -> None:
        result = self.store.pull_with_gap(self._cursor_seq, self.ports, limit=PUMP_LIMIT)
        if not result.lines:
            return
        self._cursor_seq = result.lines[-1].seq
        rendered = [(render_line(ln, self.ts_mode, self.show_prefix), self._shift(ln))
                    for ln in result.lines if self.accepts(ln)]
        # 화면이 크게 밀린 경우 — 파일에는 다 있다. 조용히 없어진 것처럼 보이면 안 된다
        if result.evicted:
            rendered.insert(0, (tr('    ⋯ 일부 라인이 버퍼에서 밀려남 (로그 파일에는 기록됨) ⋯'), ()))
        if result.skipped:
            rendered.insert(0, (tr('    ⋯ {0:,}줄 생략 (화면만 생략 — 로그 파일에는 기록됨) ⋯')
                .format(result.skipped), ()))
        if rendered:
            self._append("\n".join(text for text, _s in rendered), len(rendered))
            self._attach_spans(rendered)

    def _shift(self, line) -> tuple:
        """색 구간을 화면 표시 offset(타임스탬프·prefix 만큼 밀린 위치)으로 옮긴다."""
        if not line.spans:
            return ()
        offset = render_prefix_len(line, self.ts_mode, self.show_prefix)
        return tuple((start + offset, end + offset, fg, bg, bold)
                     for start, end, fg, bg, bold in line.spans)

    def reload(self) -> None:
        """표시 옵션이 바뀌면 ring 에서 다시 그린다 — 과거 라인의 시각도 정확히 유지된다."""
        limit = min(self.view.maximumBlockCount(), RELOAD_LIMIT)
        result = self.store.pull_with_gap(-1, self.ports, limit=limit)
        self.view.clear()
        rendered = [(render_line(ln, self.ts_mode, self.show_prefix), self._shift(ln))
                    for ln in result.lines if self.accepts(ln)]
        if result.skipped:
            note = tr('    ⋯ 이전 {0:,}줄 생략 (다시 그리기 상한 {1:,} — '
                      '로그 파일에는 기록됨) ⋯').format(result.skipped, limit)
            rendered.insert(0, (note, ()))
        if result.lines:
            self._cursor_seq = result.lines[-1].seq
        if rendered:
            self.view.appendPlainText("\n".join(text for text, _s in rendered))
            self._attach_spans(rendered)
        self._jump_to_end()
        self._search_dirty = True

    def clear_view(self) -> None:
        """화면만 지운다 — ring 과 파일은 그대로 (Ctrl+L)."""
        self.view.clear()
        self._cursor_seq = self.store.last_seq()
        self._matches = []
        self._match_index = -1
        self._search_dirty = True  # 문서가 비었으니 옛 오프셋은 무효
        self.search.count_label.setText("0/0")

    def _attach_spans(self, rendered: list[tuple[str, tuple]]) -> None:
        """방금 추가한 블록들에 색 구간을 붙인다 (색이 있는 줄이 하나도 없으면 비용 0)."""
        if not any(spans for _text, spans in rendered):
            return
        document = self.view.document()
        block = document.lastBlock()
        for _text, spans in reversed(rendered):
            if not block.isValid():
                break
            if spans:
                block.setUserData(AnsiBlockData(spans))
                self.highlighter.rehighlightBlock(block)
            block = block.previous()

    def _append(self, chunk: str, count: int) -> None:
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        keep = bar.value()
        self.view.appendPlainText(chunk)
        self._mark_search_dirty()  # 검색바가 닫혀 있으면 재스캔 표시조차 남기지 않는다
        if self.scroll_lock or not at_bottom:
            bar.setValue(min(keep, bar.maximum()))
            self._pending_new += count
            self.new_button.setText(f"↓ {self._pending_new} new")
            self.new_button.show()
        else:
            bar.setValue(bar.maximum())

    def _jump_to_end(self) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._pending_new = 0
        self.new_button.hide()

    # ------------------------------------------------------------------ 검색

    def focus_search(self) -> None:
        self.search.show()
        # 닫혀 있는 동안 유입·트리밍으로 문서가 바뀌었을 수 있다 — 옛 오프셋으로
        # 점프하면 엉뚱한 라인을 선택하므로 재열 때는 항상 재스캔 대상으로 표시한다
        self._search_dirty = True
        self._last_search_at = 0.0
        self.search.edit.setFocus()
        self.search.edit.selectAll()

    def close_search(self) -> None:
        self.search.hide()
        self.view.setExtraSelections([])
        self._search_dirty = True
        self.view.setFocus()

    def _on_search_enter(self) -> None:
        self.search_committed.emit(self.search.edit.text())
        self.step_match(1)

    def _on_search_changed(self, *_args) -> None:
        self._search_dirty = True
        self._search_timer.start()

    def _run_search(self) -> None:
        self._recompute_matches()
        if self._matches:
            self._match_index = 0
            self._reveal_match()

    def _recompute_matches(self) -> None:
        query = self.search.edit.text()
        self._matches = []
        self._match_index = -1
        if not query:
            self.view.setExtraSelections([])
            self.search.count_label.setText("0/0")
            self._search_dirty = False
            return

        rx = compile_pattern(query, self.search.regex_box.isChecked(),
                             self.search.case_box.isChecked())
        if rx is None:
            self.search.count_label.setText(tr('regex 오류'))
            self.view.setExtraSelections([])
            self._search_dirty = False
            return

        text = self.view.toPlainText()
        selections = []
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(filters_mod.search_hex()))
        document = self.view.document()
        for match in rx.finditer(text):
            start, end = match.span()
            if end == start:
                continue
            self._matches.append((start, end))
            selection = QTextEdit.ExtraSelection()  # QPlainTextEdit 에는 이 중첩 클래스가 없다
            cursor = QTextCursor(document)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            selection.cursor = cursor
            selection.format = fmt
            selections.append(selection)
            if len(self._matches) >= MAX_SEARCH_MATCHES:
                break
        self.view.setExtraSelections(selections)
        suffix = "+" if len(self._matches) >= MAX_SEARCH_MATCHES else ""
        self.search.count_label.setText(f"0/{len(self._matches)}{suffix}")
        self._search_dirty = False
        self._last_search_at = time.monotonic()

    def _mark_search_dirty(self) -> None:
        if not self.search.isHidden() and self.search.edit.text():
            self._search_dirty = True

    def step_match(self, direction: int) -> None:
        if self.search.isHidden():
            self.focus_search()
            return
        if self._search_dirty and (time.monotonic() - self._last_search_at) >= SEARCH_RESCAN_MIN_S:
            self._search_timer.stop()
            self._recompute_matches()
        if not self._matches:
            return
        self._match_index = (self._match_index + direction) % len(self._matches)
        self._reveal_match()

    def _reveal_match(self) -> None:
        if not (0 <= self._match_index < len(self._matches)):
            return
        start, end = self._matches[self._match_index]
        cursor = self.view.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()
        suffix = "+" if len(self._matches) >= MAX_SEARCH_MATCHES else ""
        self.search.count_label.setText(f"{self._match_index + 1}/{len(self._matches)}{suffix}")
