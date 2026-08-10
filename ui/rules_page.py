"""RulesPage — 하이라이트 / redact / 저장된 필터 룰 편집. UI 문서 §5.

편집 즉시 전 콘솔·필터드뷰에 반영하고, 프로파일 저장 시 함께 기록된다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.config import Profile
from ..core.filters import (DEFAULT_HIGHLIGHT_COLOR, HIGHLIGHT_COLORS, FilterRule, HighlightRule,
                            RedactRule, TriggerRule, compile_pattern)
from . import theme
from ..core.i18n import tr


def _checkbox_item(checked: bool) -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
    return item


def _table(headers: list[str], stretch_column: int) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
                          | QAbstractItemView.EditKeyPressed)
    header = table.horizontalHeader()
    for column in range(len(headers)):
        mode = QHeaderView.Stretch if column == stretch_column else QHeaderView.ResizeToContents
        header.setSectionResizeMode(column, mode)
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    fit_table(table)
    return table


def fit_table(table: QTableWidget, min_rows: int = 3, max_rows: int = 10) -> None:
    """행 수에 맞춰 높이를 잡는다.

    고정 높이로 두면 룰이 늘었을 때 행이 잘리고, 카드 안에서 버튼과 겹쳐 보인다.
    """
    row_height = table.verticalHeader().defaultSectionSize() or 24
    rows = max(min_rows, min(max_rows, table.rowCount()))
    header_height = table.horizontalHeader().height() or 26
    table.setFixedHeight(header_height + rows * row_height + 8)


class RulesPage(QWidget):
    rules_changed = Signal()
    filter_open_requested = Signal(object)

    def __init__(self, profile: Profile, parent: QWidget | None = None):
        super().__init__(parent)
        self.profile = profile
        self._loading = False

        # 왼쪽 트리로 항목을 고르고 오른쪽에 그 카드만 보여준다 — 네 종류를 한 화면에
        # 쌓으면 창이 작을 때 겹치고, 무엇을 고치는 중인지도 흐려진다
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(190)
        root = QTreeWidgetItem(self.tree, [tr('규칙')])
        root.setExpanded(True)
        self._tree_items = [QTreeWidgetItem(root, [name]) for name in
                            (tr('하이라이트'), tr('redact (마스킹)'), tr('트리거'), tr('저장된 필터'))]
        self.tree.expandAll()

        self.pages = QStackedWidget()
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 12, 16, 16)
        outer.setSpacing(12)

        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(12)
        shell.addWidget(self.tree)
        shell.addWidget(self.pages, 1)

        # ---------------------------------------------------------- 하이라이트
        highlight_card = theme.Card(tr('하이라이트 룰'))
        self.highlight_table = _table(["on", tr('키워드'), tr('색'), "regex", "Aa"], 1)
        highlight_card.add(self.highlight_table)
        highlight_card.add_layout(self._button_row(
            self._add_highlight, lambda: self._remove_row(self.highlight_table)))
        highlight_card.add(_hint(
                tr('라이브 스트림에 즉시 반영됩니다. `Error`(주황)·`!!`(노랑)은 기본 제공.')))
        self.pages.addWidget(_wrap(highlight_card))

        # ---------------------------------------------------------- redact
        redact_card = theme.Card(tr('redact 룰'))
        self.redact_table = _table(["on", tr('패턴'), tr('치환 문자열'), "regex"], 1)
        redact_card.add(self.redact_table)
        redact_card.add_layout(self._button_row(
            self._add_redact, lambda: self._remove_row(self.redact_table)))
        redact_card.add(_hint(
            tr('그룹 1이 있으면 그 부분만 치환합니다. regex 를 끄면 리터럴로 찾습니다 — 비밀번호에 정규식 '
               '메타문자가 있을 때 씁니다. 마스킹은 화면·파일·프로파일 공통이고, 시리얼로 나가는 것만 '
               '원문입니다.')))
        self.pages.addWidget(_wrap(redact_card))

        # ---------------------------------------------------------- 트리거
        trigger_card = theme.Card(tr('트리거 (발생 집계)'))
        self.trigger_table = _table(["on", tr('패턴'), tr('대상 포트'), "regex", "Aa"], 1)
        trigger_card.add(self.trigger_table)
        trigger_card.add_layout(self._button_row(
            self._add_trigger, lambda: self._remove_row(self.trigger_table)))
        trigger_card.add(_hint(
            tr('매치 횟수·최근 시각을 Monitor 의 ⚡ 칩에 집계합니다 — 밤샘 수집 중 WDOG/MemManage 같은 '
               '이벤트를 놓치지 않기 위한 것입니다. 하이라이트와는 별개입니다.')))
        self.pages.addWidget(_wrap(trigger_card))

        # ---------------------------------------------------------- 저장된 필터
        filter_card = theme.Card(tr('저장된 필터'))
        self.filter_table = _table([tr('이름'), tr('패턴'), tr('대상 포트'), "regex", "Aa"], 1)
        filter_card.add(self.filter_table)
        row = self._button_row(self._add_filter, lambda: self._remove_row(self.filter_table))
        self.open_filter_button = QPushButton(tr('선택 필터로 창 열기'))
        self.open_filter_button.setObjectName("primary")
        row.addWidget(self.open_filter_button)
        filter_card.add_layout(row)
        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        filter_card.add(self.status)
        self.pages.addWidget(_wrap(filter_card))

        self.tree.currentItemChanged.connect(self._on_tree_changed)
        self.tree.setCurrentItem(self._tree_items[0])

        self.highlight_table.itemChanged.connect(self._on_changed)
        self.redact_table.itemChanged.connect(self._on_changed)
        self.trigger_table.itemChanged.connect(self._on_changed)
        self.filter_table.itemChanged.connect(self._on_changed)
        self.filter_table.itemDoubleClicked.connect(lambda _i: self._open_selected_filter())
        self.open_filter_button.clicked.connect(self._open_selected_filter)

        self.reload()

    # ------------------------------------------------------------------ 구성

    def _button_row(self, on_add, on_remove) -> QHBoxLayout:
        row = QHBoxLayout()
        add_button = QPushButton(tr('추가'))
        remove_button = QPushButton(tr('삭제'))
        add_button.clicked.connect(on_add)
        remove_button.clicked.connect(on_remove)
        row.addWidget(add_button)
        row.addWidget(remove_button)
        row.addStretch(1)
        return row

    def _on_tree_changed(self, current, _previous) -> None:
        if current in self._tree_items:
            self.pages.setCurrentIndex(self._tree_items.index(current))

    def show_page(self, index: int) -> None:
        if 0 <= index < len(self._tree_items):
            self.tree.setCurrentItem(self._tree_items[index])

    def reload(self, profile: Profile | None = None) -> None:
        if profile is not None:
            self.profile = profile
        self._loading = True
        try:
            self._fill_highlight()
            self._fill_redact()
            self._fill_triggers()
            self._fill_filters()
            for table in (self.highlight_table, self.redact_table,
                          self.trigger_table, self.filter_table):
                fit_table(table)
        finally:
            self._loading = False

    def _fill_highlight(self) -> None:
        table = self.highlight_table
        table.setRowCount(0)
        for rule in self.profile.highlight_rules:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, _checkbox_item(rule.enabled))
            # 키워드 칸을 그 룰의 색으로 칠한다 — 로그에서 보일 모습과 같게
            keyword = QTableWidgetItem(rule.pattern)
            keyword.setBackground(QBrush(QColor(rule.qcolor_hex())))
            keyword.setForeground(QBrush(QColor(theme.TEXT)))
            table.setItem(row, 1, keyword)
            table.setCellWidget(row, 2, self._color_combo(rule.color))
            table.setItem(row, 3, _checkbox_item(rule.is_regex))
            table.setItem(row, 4, _checkbox_item(rule.case_sensitive))

    def _color_combo(self, current: str) -> QComboBox:
        """색 이름만 흰 칸에 띄우면 실제 하이라이트가 어떻게 보일지 알 수 없다 —
        칸과 목록을 그 색으로 칠해 로그에서 보일 모습 그대로 보여준다."""
        combo = QComboBox()
        for name, hex_value in HIGHLIGHT_COLORS.items():
            combo.addItem(tr(name), name)   # 보이는 건 번역, 저장되는 값은 원래 이름
            row = combo.count() - 1
            combo.setItemData(row, QBrush(QColor(hex_value)), Qt.BackgroundRole)
            combo.setItemData(row, QBrush(QColor(theme.TEXT)), Qt.ForegroundRole)
            combo.setItemData(row, hex_value, Qt.ToolTipRole)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else combo.findData(DEFAULT_HIGHLIGHT_COLOR))
        combo.currentIndexChanged.connect(lambda _i, c=combo: self._paint_combo(c))
        combo.currentIndexChanged.connect(self._on_changed)
        self._paint_combo(combo)
        return combo

    @staticmethod
    def _paint_combo(combo: QComboBox) -> None:
        hex_value = HIGHLIGHT_COLORS.get(combo.currentData(),
                                         HIGHLIGHT_COLORS[DEFAULT_HIGHLIGHT_COLOR])
        combo.setStyleSheet(
            f"QComboBox {{ background: {hex_value}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 4px 8px; }}")

    def _fill_redact(self) -> None:
        table = self.redact_table
        table.setRowCount(0)
        for rule in self.profile.redact_rules:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, _checkbox_item(rule.enabled))
            table.setItem(row, 1, QTableWidgetItem(rule.pattern))
            table.setItem(row, 2, QTableWidgetItem(rule.replacement))
            table.setItem(row, 3, _checkbox_item(rule.is_regex))

    def _fill_triggers(self) -> None:
        table = self.trigger_table
        table.setRowCount(0)
        for rule in self.profile.trigger_rules:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, _checkbox_item(rule.enabled))
            table.setItem(row, 1, QTableWidgetItem(rule.pattern))
            table.setItem(row, 2, QTableWidgetItem(",".join(rule.ports)))
            table.setItem(row, 3, _checkbox_item(rule.is_regex))
            table.setItem(row, 4, _checkbox_item(rule.case_sensitive))

    def _fill_filters(self) -> None:
        table = self.filter_table
        table.setRowCount(0)
        for rule in self.profile.saved_filters:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(rule.name))
            table.setItem(row, 1, QTableWidgetItem(rule.pattern))
            table.setItem(row, 2, QTableWidgetItem(",".join(rule.ports)))
            table.setItem(row, 3, _checkbox_item(rule.is_regex))
            table.setItem(row, 4, _checkbox_item(rule.case_sensitive))

    # ------------------------------------------------------------------ 편집

    def _add_highlight(self) -> None:
        self.profile.highlight_rules.append(HighlightRule("", DEFAULT_HIGHLIGHT_COLOR))
        self.reload()
        self.rules_changed.emit()

    def _add_redact(self) -> None:
        self.profile.redact_rules.append(RedactRule("", "<redacted>", is_regex=True))
        self.reload()
        self.rules_changed.emit()

    def _add_filter(self) -> None:
        self.profile.saved_filters.append(FilterRule(name=tr('새 필터')))
        self.reload()
        self.rules_changed.emit()

    def _add_trigger(self) -> None:
        self.profile.trigger_rules.append(TriggerRule(""))
        self.reload()
        self.rules_changed.emit()

    def _remove_row(self, table: QTableWidget) -> None:
        row = table.currentRow()
        if row < 0:
            return
        target = {id(self.highlight_table): self.profile.highlight_rules,
                  id(self.redact_table): self.profile.redact_rules,
                  id(self.trigger_table): self.profile.trigger_rules,
                  id(self.filter_table): self.profile.saved_filters}[id(table)]
        if row < len(target):
            del target[row]
        self.reload()
        self.rules_changed.emit()

    def _on_changed(self, *_args) -> None:
        if self._loading:
            return
        self._collect()
        self._repaint_highlight_rows()
        self.rules_changed.emit()

    def _repaint_highlight_rows(self) -> None:
        """색을 바꾸면 키워드 칸도 즉시 그 색으로 — 편집 결과를 바로 눈으로 확인한다."""
        for row, rule in enumerate(self.profile.highlight_rules):
            item = self.highlight_table.item(row, 1)
            if item is not None:
                item.setBackground(QBrush(QColor(rule.qcolor_hex())))
                item.setForeground(QBrush(QColor(theme.TEXT)))

    def _collect(self) -> None:
        errors: list[str] = []

        rules: list[HighlightRule] = []
        for row in range(self.highlight_table.rowCount()):
            pattern = _text(self.highlight_table, row, 1)
            is_regex = _checked(self.highlight_table, row, 3)
            combo = self.highlight_table.cellWidget(row, 2)
            color = combo.currentData() if isinstance(combo, QComboBox) else DEFAULT_HIGHLIGHT_COLOR
            if pattern and is_regex and compile_pattern(pattern, True, False) is None:
                errors.append(tr('하이라이트 regex 오류: {0}').format(pattern))
            rules.append(HighlightRule(pattern, color, is_regex,
                                       case_sensitive=_checked(self.highlight_table, row, 4),
                                       enabled=_checked(self.highlight_table, row, 0)))
        self.profile.highlight_rules = rules

        redacts: list[RedactRule] = []
        for row in range(self.redact_table.rowCount()):
            pattern = _text(self.redact_table, row, 1)
            is_regex = _checked(self.redact_table, row, 3)
            if pattern and is_regex and compile_pattern(pattern, True, True) is None:
                # 룰이 깨지면 마스킹이 조용히 사라진다 — 평문 기록으로 이어지므로 크게 알린다
                errors.append(tr('redact regex 오류(마스킹 안 됨): {0}').format(pattern))
            redacts.append(RedactRule(pattern, _text(self.redact_table, row, 2) or "<redacted>",
                                      enabled=_checked(self.redact_table, row, 0),
                                      is_regex=is_regex))
        self.profile.redact_rules = redacts

        triggers: list[TriggerRule] = []
        for row in range(self.trigger_table.rowCount()):
            pattern = _text(self.trigger_table, row, 1)
            is_regex = _checked(self.trigger_table, row, 3)
            if pattern and is_regex and compile_pattern(pattern, True, True) is None:
                errors.append(tr('트리거 regex 오류: {0}').format(pattern))
            ports = [p.strip().upper() for p in _text(self.trigger_table, row, 2).split(",")
                     if p.strip()]
            triggers.append(TriggerRule(pattern, is_regex,
                                        case_sensitive=_checked(self.trigger_table, row, 4),
                                        ports=ports,
                                        enabled=_checked(self.trigger_table, row, 0)))
        self.profile.trigger_rules = triggers

        filters: list[FilterRule] = []
        for row in range(self.filter_table.rowCount()):
            ports = [p.strip().upper() for p in _text(self.filter_table, row, 2).split(",") if p.strip()]
            filters.append(FilterRule(pattern=_text(self.filter_table, row, 1),
                                      is_regex=_checked(self.filter_table, row, 3),
                                      case_sensitive=_checked(self.filter_table, row, 4),
                                      ports=ports,
                                      name=_text(self.filter_table, row, 0)))
        self.profile.saved_filters = filters

        if errors:
            self.status.setText("⚠ " + " / ".join(errors[:3]) + tr(' — 해당 룰은 무시됩니다'))
            self.status.setStyleSheet(f"QLabel {{ color: {theme.DANGER}; background: transparent; }}")
        else:
            self.status.setText("")

    def _open_selected_filter(self) -> None:
        row = self.filter_table.currentRow()
        if 0 <= row < len(self.profile.saved_filters):
            self.filter_open_requested.emit(self.profile.saved_filters[row])


def _text(table: QTableWidget, row: int, column: int) -> str:
    item = table.item(row, column)
    return item.text().strip() if item is not None else ""


def _checked(table: QTableWidget, row: int, column: int) -> bool:
    item = table.item(row, column)
    return bool(item is not None and item.checkState() == Qt.Checked)


def _wrap(card: QWidget) -> QWidget:
    """카드 하나를 스크롤 가능한 페이지로 — 룰이 많아도 잘리지 않는다."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.addWidget(card)
    layout.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setWidget(page)
    return scroll


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label
