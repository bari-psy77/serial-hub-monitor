"""FilterView — 필터 매치 라인만 보이는 독립 창. UI 문서 §4.

여러 개를 동시에 띄울 수 있고, 창마다 자기 필터·자기 커서를 가진다.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QDockWidget, QPushButton, QVBoxLayout, QWidget)

from ..core.diag import diag
from ..core.filters import FilterRule, HighlightRule
from ..core.logstore import LogStore
from .console_pane import ConsolePane
from .dock_common import make_maximize_button
from ..core.i18n import tr


class FilterView(QDockWidget):
    """필터 매치만 보는 도크.

    ★래퍼(LogViewerDock 처럼 감싸기)를 쓰지 않고 이 클래스 자체를 도크로 만든다 —
    `view.pane`·`view.edit`·`view.save_button` 을 쓰는 호출부와 테스트가 그대로
    남고, 한 겹 더 들어가는 위임 계층이 생기지 않는다.
    """
    closed = Signal(object)
    _serial = 0   # id() 는 재사용돼 도크 배치 기억이 꼬인다 — 단조 증가 번호

    def __init__(self, store: LogStore, roles: list[str], rule: FilterRule,
                 ts_mode: str, hide_empty: bool,
                 highlight_rules: list[HighlightRule] | None = None,
                 labels: dict[str, str] | None = None,
                 parent: QWidget | None = None):
        super().__init__(tr('필터드뷰'), parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        FilterView._serial += 1
        self.setObjectName(f'filterview_dock_{FilterView._serial}')
        self.store = store
        self.roles = list(roles)
        # 화면에 보일 이름 — 사용자가 포트 이름을 바꿨으면 그 이름을 쓴다
        self.labels = dict(labels or {})
        self.rule = rule
        self._compiled = rule.compiled()

        body = QWidget(self)
        outer = QVBoxLayout(body)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(tr('필터')))
        self.edit = QLineEdit(rule.pattern)
        self.edit.setPlaceholderText(tr('매치되는 라인만 보여줍니다'))
        self.case_box = QCheckBox("Aa")
        self.case_box.setChecked(rule.case_sensitive)
        self.regex_box = QCheckBox(".*")
        self.regex_box.setChecked(rule.is_regex)
        self.backfill_box = QCheckBox(tr('소급 채움'))
        self.backfill_box.setChecked(True)
        self.backfill_box.setToolTip(tr('이미 받은 라인 중 매치되는 것도 채웁니다'))
        self.save_button = QPushButton(tr('파일로 저장'))
        self.save_button.setToolTip(tr('지금 보이는 매치 결과를 텍스트 파일로 저장 (티켓 첨부용)'))
        row.addWidget(self.edit, 1)
        row.addWidget(self.case_box)
        row.addWidget(self.regex_box)
        row.addWidget(self.backfill_box)
        row.addWidget(self.save_button)
        self.button_row = row

        self.port_boxes: dict[str, QCheckBox] = {}
        for role in self.roles:
            box = QCheckBox(self.labels.get(role) or role)
            box.setChecked(not rule.ports or role in rule.ports)
            box.toggled.connect(self._on_rule_changed)
            self.port_boxes[role] = box
            row.addWidget(box)
        outer.addLayout(row)

        self.pane = ConsolePane(tr('필터드뷰'), store, self._selected_ports(),
                                ts_mode=ts_mode, hide_empty=hide_empty, max_blocks=50_000)
        self.pane.show_prefix = True  # 출처 식별이 필요하다 (FR-3)
        self.pane.extra_filter = self._match
        self.pane.state_pill.hide()
        if highlight_rules:
            self.pane.set_highlight_rules(highlight_rules)
        outer.addWidget(self.pane, 1)
        self.setWidget(body)
        self.maximize_button = make_maximize_button(self)
        self.button_row.addWidget(self.maximize_button)

        # 타이핑마다 소급 채움을 다시 돌리면 렉이 걸린다
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._refresh_pane)

        self.edit.textChanged.connect(self._on_rule_changed)
        self.case_box.toggled.connect(self._on_rule_changed)
        self.regex_box.toggled.connect(self._on_rule_changed)
        self.backfill_box.toggled.connect(self._on_rule_changed)
        self.save_button.clicked.connect(self.save_to_file)

        self._sync_rule()
        self._refresh_pane()
        self.resize(900, 520)

    def _title(self) -> str:
        """모든 포트를 볼 때는 이름을 늘어놓지 않고 '전체' 로 줄인다."""
        if self.rule.name:
            return self.rule.name
        chosen = self._selected_ports()
        scope = (tr('전체') if len(chosen) == len(self.roles)
                 else ",".join(self.labels.get(r) or r for r in chosen))
        return f'"{self.rule.pattern}" — {scope}'

    def _selected_ports(self) -> list[str]:
        chosen = [role for role, box in self.port_boxes.items() if box.isChecked()]
        return chosen or list(self.roles)

    def _match(self, line) -> bool:
        if self._compiled is None:
            return not self.rule.pattern
        return self._compiled.search(line.text) is not None

    def _sync_rule(self) -> None:
        self.rule.pattern = self.edit.text()
        self.rule.is_regex = self.regex_box.isChecked()
        self.rule.case_sensitive = self.case_box.isChecked()
        self.rule.ports = self._selected_ports()
        self._compiled = self.rule.compiled()
        self.pane.ports = list(self.rule.ports)
        title = self._title()
        self.pane.title_label.setText(tr('필터드뷰: {0}').format(title))
        self.setWindowTitle(tr('필터드뷰 — {0}').format(title))

    def _on_rule_changed(self, *_args) -> None:
        self._sync_rule()
        self._refresh_timer.start()

    def _refresh_pane(self) -> None:
        if self.backfill_box.isChecked():
            self.pane.reload()
        else:
            self.pane.clear_view()

    def set_display(self, ts_mode: str, hide_empty: bool) -> None:
        changed = (self.pane.ts_mode != ts_mode) or (self.pane.hide_empty != hide_empty)
        self.pane.ts_mode = ts_mode
        self.pane.hide_empty = hide_empty
        if changed:
            self.pane.reload()

    def set_highlight_rules(self, rules: list[HighlightRule]) -> None:
        self.pane.set_highlight_rules(rules)

    def save_to_file(self) -> None:
        """보이는 매치 결과를 그대로 저장 — 티켓에 필터 결과만 첨부하는 용도."""
        stamp = time.strftime("%m%d_%H%M%S")
        safe = "".join(ch for ch in self.rule.pattern if ch.isalnum() or ch in "-_")[:24] or "filter"
        path, _ = QFileDialog.getSaveFileName(
            self, tr('필터 결과 저장'), f"filtered_{safe}_{stamp}.log", "Log (*.log *.txt);;All (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"# filter: {self.rule.label()}  saved {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                fh.write(self.pane.view.toPlainText())
                fh.write("\n")
            self.save_button.setText(tr('저장됨 ✓'))
            # receiver 를 지정해야 그 사이 창이 닫혔을 때 죽은 버튼을 만지지 않는다
            QTimer.singleShot(2000, self.save_button,
                              lambda: self.save_button.setText(tr('파일로 저장')))
        except Exception as exc:  # noqa: BLE001
            diag.exception("filterview", f"필터 결과 저장 실패: {path}")
            self.save_button.setText(tr('저장 실패: {0}').format(str(exc)[:30]))

    def pump(self) -> None:
        if self.pane.extra_filter is not None:
            self.pane.pump()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        self.closed.emit(self)
        # pane.extra_filter 가 자기 바운드 메서드라 순환 참조가 생긴다 —
        # 끊어주지 않으면 닫은 창이 스크롤백을 그대로 물고 남는다
        self._refresh_timer.stop()
        self.pane.extra_filter = None
        self.pane.clear_view()
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        super().closeEvent(event)
