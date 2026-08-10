"""CommandPanel — 퀵 입력 + 스크래치패드. UI 문서 §3.

VS Code Serial Monitor 의 "명령용 text editor" 장점을 스크래치패드로 계승한다.
"""

from __future__ import annotations

import os
import re
import time

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..core.logstore import LogStore
from ..core.portscan import DEFAULT_PROBE_PATTERNS, expand_pattern
from . import theme
from .console_pane import HistoryCombo
from ..core.i18n import tr

SEQUENTIAL_INTERVAL_MS = 300
MISROUTE_WINDOW_S = 2.0


class HistoryLineEdit(HistoryCombo):
    """↑/↓ 히스토리 + 마우스로 여는 드롭다운. 목록은 프로파일에 저장돼 재실행해도 남는다."""

    history_up = Signal()
    history_down = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        """키가 콤보 자신에게 올 때 (Ctrl+` 로 포커스를 준 경우가 전부 여기).

        기본 QComboBox 는 ↑/↓ 로 항목 목록을 훑는데, 여기서는 그게 아니라 **포트별
        명령 히스토리**를 오르내려야 한다. HistoryCombo 쪽 주석 참조.
        """
        if event.key() == Qt.Key_Up:
            self.history_up.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Down:
            self.history_down.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 시그니처
        # 키가 lineEdit 에게 직접 올 때 (마우스로 눌러 편집 중).
        # 필터 설치는 HistoryCombo 가 이미 했다 (중복 설치 금지)
        if obj is self.lineEdit() and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                self.history_up.emit()
                return True
            if event.key() == Qt.Key_Down:
                self.history_down.emit()
                return True
        return super().eventFilter(obj, event)


class CommandPanel(QWidget):
    def __init__(self, roles: list[str], send_fn, store: LogStore,
                 history: dict[str, list[str]] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.send_fn = send_fn
        self.store = store
        self.history: dict[str, list[str]] = history if history is not None else {}
        self._history_pos: dict[str, int] = {}
        self._redactor = None
        self._misroute_seq = -1
        self._misroute_role = ""
        self._misroute_until = 0.0
        self._misroute_token = ""
        self._queue: list[str] = []
        self._queue_role = ""
        self._total = 0

        card = theme.Card(parent=self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        body = card.body()

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(tr('명령 ▸')))
        # 표시는 사용자가 정한 포트 이름, 값(itemData)은 내부 role — 이름을 바꿔도
        # 전송 대상이 흔들리지 않는다.
        self.target = QComboBox()
        for role in roles:
            self.target.addItem(role, role)
        self.target.setMinimumWidth(110)
        self.edit = HistoryLineEdit()
        self.edit.setPlaceholderText(tr('명령 입력 후 Enter — 대상 포트는 왼쪽에서 선택 (Ctrl+Tab 전환)'))
        self.send_button = QPushButton(tr('보내기'))
        self.send_button.setObjectName("primary")
        self.pad_button = QPushButton(tr('스크래치패드'))
        self.pad_button.setCheckable(True)
        row.addWidget(self.target)
        row.addWidget(self.edit, 1)
        row.addWidget(self.send_button)
        row.addWidget(self.pad_button)
        body.addLayout(row)

        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        body.addWidget(self.hint)

        self.pad = QWidget()
        pad_layout = QVBoxLayout(self.pad)
        pad_layout.setContentsMargins(0, 6, 0, 0)
        pad_layout.setSpacing(6)
        self.pad_edit = QPlainTextEdit()
        self.pad_edit.setPlaceholderText(tr('자주 쓰는 명령 세트. `#` 로 시작하는 줄은 주석 — 전송하지 '
                                            '않습니다.'))
        self.pad_edit.setMinimumHeight(110)
        pad_layout.addWidget(self.pad_edit)
        pad_row = QHBoxLayout()
        self.pad_send_line = QPushButton(tr('현재 줄 전송 (Ctrl+Enter)'))
        self.pad_send_all = QPushButton(tr('전체 순차 전송'))
        self.pad_stop = QPushButton(tr('중단 (Esc)'))
        self.pad_open = QPushButton(tr('열기'))
        self.pad_save = QPushButton(tr('저장'))
        self.pad_status = QLabel("")
        self.pad_status.setObjectName("hint")
        for button in (self.pad_send_line, self.pad_send_all, self.pad_stop):
            pad_row.addWidget(button)
        pad_row.addWidget(self.pad_status, 1)
        pad_row.addWidget(self.pad_open)
        pad_row.addWidget(self.pad_save)
        pad_layout.addLayout(pad_row)
        self.pad.hide()
        body.addWidget(self.pad)

        self._timer = QTimer(self)
        self._timer.setInterval(SEQUENTIAL_INTERVAL_MS)
        self._timer.timeout.connect(self._pump_queue)

        self.send_button.clicked.connect(self.send_current)
        self.edit.returnPressed.connect(self.send_current)
        self.edit.textChanged.connect(self._update_hint)
        self.edit.history_up.connect(lambda: self._step_history(-1))
        self.edit.history_down.connect(lambda: self._step_history(1))
        self.target.currentIndexChanged.connect(self._on_target_changed)
        self.pad_button.toggled.connect(self.pad.setVisible)
        self.pad_send_line.clicked.connect(self.send_pad_line)
        self.pad_send_all.clicked.connect(self.send_pad_all)
        self.pad_stop.clicked.connect(self.abort_queue)
        self.pad_open.clicked.connect(self.open_pad_file)
        self.pad_save.clicked.connect(self.save_pad_file)

        self._reload_dropdown(self.current_role())
        for keys, slot in (("Ctrl+Return", self.send_pad_line),
                           ("Esc", lambda: self.abort_queue())):
            shortcut = QShortcut(QKeySequence(keys), self.pad_edit, activated=slot)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._update_pad_buttons()

    # ------------------------------------------------------------------ 설정

    def set_redactor(self, redactor) -> None:
        self._redactor = redactor
        self._update_hint()

    def set_roles(self, roles: list[str], labels: dict[str, str] | None = None) -> None:
        current = self.current_role()
        self.target.blockSignals(True)
        self.target.clear()
        for role in roles:
            self.target.addItem((labels or {}).get(role) or role, role)
        index = self.target.findData(current)
        if index >= 0:
            self.target.setCurrentIndex(index)
        self.target.blockSignals(False)
        self._on_target_changed()

    def set_labels(self, labels: dict[str, str]) -> None:
        """포트 이름만 바뀐 경우 — 목록 재구성 없이 표시 문구만 갈아끼운다."""
        for index in range(self.target.count()):
            role = self.target.itemData(index)
            self.target.setItemText(index, labels.get(role) or role)

    def current_role(self) -> str:
        data = self.target.currentData()
        return data if data is not None else self.target.currentText()

    def select_role(self, role: str) -> bool:
        index = self.target.findData(role)
        if index >= 0:
            self.target.setCurrentIndex(index)
        return index >= 0

    def _on_target_changed(self, *_args) -> None:
        self._reload_dropdown(self.current_role())   # 히스토리는 포트별로 따로 기억한다
        self._update_hint()

    def cycle_target(self) -> None:
        count = self.target.count()
        if count:
            self.target.setCurrentIndex((self.target.currentIndex() + 1) % count)

    def focus_input(self) -> None:
        self.edit.setFocus()
        self.edit.selectAll()

    # ------------------------------------------------------------------ 전송

    def send_current(self) -> None:
        text = self.edit.text().strip()
        if not text:
            return
        role = self.current_role()
        ok, err = self._send(role, text)
        if ok:
            self._push_history(role, text)
            self.edit.clear()
            self._update_hint()

    def _send(self, role: str, text: str) -> tuple[bool, str]:
        ok, err = self.send_fn(role, text)
        if not ok:
            self._set_hint(f"⚠ {err}", theme.DANGER)  # 입력 내용은 지우지 않는다 (설계 §7)
            return False, err
        self._misroute_seq = self.store.last_seq()
        self._misroute_role = role
        self._misroute_until = time.monotonic() + MISROUTE_WINDOW_S
        self._misroute_token = text.split()[0] if text.split() else text
        self._set_hint(tr('{0} 로 전송: {1}').format(role, self._masked(text)), theme.TEXT_SUB)
        return True, ""

    def send_pad_line(self) -> None:
        cursor = self.pad_edit.textCursor()
        line = cursor.block().text().strip()
        if not line or line.startswith("#"):
            return
        self._send(self.current_role(), line)
        cursor.movePosition(QTextCursor.MoveOperation.NextBlock)
        self.pad_edit.setTextCursor(cursor)

    def send_pad_all(self) -> None:
        lines = [ln.strip() for ln in self.pad_edit.toPlainText().splitlines()]
        self._queue = [ln for ln in lines if ln and not ln.startswith("#")]
        self._queue_role = self.current_role()
        if not self._queue:
            self.pad_status.setText(tr('전송할 줄이 없습니다'))
            return
        self.pad_status.setText(tr('순차 전송 0/{0}').format(len(self._queue)))
        self._total = len(self._queue)
        self._timer.start()
        self._update_pad_buttons()

    def _pump_queue(self) -> None:
        if not self._queue:
            self.abort_queue(finished=True)
            return
        line = self._queue.pop(0)
        ok, _err = self._send(self._queue_role, line)
        done = self._total - len(self._queue)
        self.pad_status.setText(tr('순차 전송 {0}/{1}').format(done, self._total))
        if not ok:
            self.abort_queue()

    def abort_queue(self, finished: bool = False) -> None:
        was_running = self._timer.isActive()
        self._timer.stop()
        remaining = len(self._queue)
        self._queue = []
        if finished:
            self.pad_status.setText(tr('순차 전송 완료'))
        elif was_running:
            self.pad_status.setText(tr('순차 전송 중단 — {0}줄 남김').format(remaining))
        self._update_pad_buttons()

    def _update_pad_buttons(self) -> None:
        running = self._timer.isActive()
        self.pad_send_all.setEnabled(not running)
        self.pad_send_line.setEnabled(not running)
        self.pad_stop.setEnabled(running)

    # ------------------------------------------------------------------ 히스토리

    def _push_history(self, role: str, text: str) -> None:
        items = self.history.setdefault(role, [])
        if text in items:
            items.remove(text)
        items.append(text)
        del items[:-200]
        self._history_pos[role] = len(items)
        self._reload_dropdown(role)

    def _reload_dropdown(self, role: str) -> None:
        """최근 것이 위로 오도록 — 마우스로 눌러 고를 수 있어야 한다는 요구."""
        self.edit.load_history(list(reversed(self.history.get(role, []))))

    def _step_history(self, direction: int) -> None:
        role = self.current_role()
        items = self.history.get(role, [])
        if not items:
            return
        pos = self._history_pos.get(role, len(items))
        pos = max(0, min(len(items), pos + direction))
        self._history_pos[role] = pos
        self.edit.setText("" if pos >= len(items) else items[pos])
        self.edit.setCursorPosition(len(self.edit.text()))

    # ------------------------------------------------------------------ 힌트

    def _masked(self, text: str) -> str:
        if self._redactor is None:
            return text
        return self._redactor.apply(text)

    def _update_hint(self) -> None:
        text = self.edit.text()
        if not text:
            self._set_hint("", theme.TEXT_SUB)
            return
        masked = self._masked(text)
        if masked != text:
            self._set_hint(tr('🔒 로그 기록본: {0}').format(masked), theme.TEXT_SUB)
        else:
            self._set_hint("", theme.TEXT_SUB)

    def _set_hint(self, text: str, color: str) -> None:
        self.hint.setText(text)
        self.hint.setStyleSheet(f"QLabel {{ color: {color}; background: transparent; }}")

    def poll_misroute(self, patterns: dict[str, str] | None = None) -> None:
        """보낸 명령이 unknown-command 서명으로 되돌아오면 대상 포트 오지정을 의심한다 (UI 문서 §3)."""
        if self._misroute_seq < 0:
            return
        if time.monotonic() > self._misroute_until:
            self._misroute_seq = -1
            return
        lines = [ln for ln in self.store.pull(self._misroute_seq, [self._misroute_role])
                 if not ln.is_tx]
        if not lines:
            return
        blob = "\n".join(ln.text for ln in lines)
        for _role, pattern in (patterns or DEFAULT_PROBE_PATTERNS).items():
            try:
                if re.search(expand_pattern(pattern, self._misroute_token), blob, re.IGNORECASE):
                    self._set_hint(
                        tr('⚠ {0} 가 이 명령을 모른다고 응답했습니다 — 대상 포트 확인')
                            .format(self._misroute_role),
                        theme.WARNING)
                    self._misroute_seq = -1
                    return
            except re.error:
                continue

    # ------------------------------------------------------------------ 파일

    def open_pad_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr('명령 세트 열기'), "", "Text (*.txt *.md);;All (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                self.pad_edit.setPlainText(fh.read())
            self.pad_status.setText(tr('불러옴: {0}').format(os.path.basename(path)))
        except Exception as exc:  # noqa: BLE001
            self.pad_status.setText(tr('열기 실패: {0}').format(str(exc)[:60]))

    def save_pad_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr('명령 세트 저장'), "commands.txt",
                                              "Text (*.txt);;All (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.pad_edit.toPlainText())
            self.pad_status.setText(tr('저장: {0}').format(os.path.basename(path)))
        except Exception as exc:  # noqa: BLE001
            self.pad_status.setText(tr('저장 실패: {0}').format(str(exc)[:60]))
