"""LogViewer — 과거 로그 파일을 열어 분석하는 뷰어 (도킹 + 독립 창).

설계문서 docs/superpowers/specs/2026-08-14-log-viewer-design.md §3.2.
필터드뷰와 같은 상단 바(검색·정규식·소스 체크박스·저장)에 ConsolePane 을 물리되,
store 만 파일에서 복원한 읽기 전용 LogFileStore 로 바꾼 구조다. 정적 뷰라서
tick/pump 에 묶이지 않는다 — 소급 채움은 reload() 한 번으로 끝난다.
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QDockWidget, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..core.config import Profile
from ..core.diag import diag
from ..core.filters import FilterRule
from ..core.i18n import tr
from ..core.logfile import LARGE_WARN_BYTES, LogFileStore
from ..core.logstore import TS_OFF
from .console_pane import ConsolePane


def confirm_large(parent, total_bytes: int) -> bool:
    """전체 로드 정책 — 큰 파일 묶음은 로드 전에 한 번만 확인받는다 (테스트가 패치하는 지점)."""
    if total_bytes <= LARGE_WARN_BYTES:
        return True
    mb = total_bytes / (1024 * 1024)
    answer = QMessageBox.question(
        parent, tr('파일이 큽니다'),
        tr('선택한 로그가 총 {0:,.0f} MB 입니다. 전부 불러오면 메모리를 많이 쓰고 시간이 '
           '걸릴 수 있습니다. 계속할까요?').format(mb),
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    return answer == QMessageBox.Yes


class LogViewerWidget(QWidget):
    def __init__(self, profile: Profile, paths: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.profile = profile
        self.store = LogFileStore()
        self.rule = FilterRule(pattern="")
        self._compiled = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(tr('필터')))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr('매치되는 라인만 보여줍니다'))
        self.case_box = QCheckBox("Aa")
        self.regex_box = QCheckBox(".*")
        self.add_button = QPushButton(tr('파일 추가'))
        self.save_button = QPushButton(tr('결과 저장'))
        self.save_button.setToolTip(tr('지금 보이는 매치 결과를 텍스트 파일로 저장 (티켓 첨부용)'))
        row.addWidget(self.edit, 1)
        row.addWidget(self.case_box)
        row.addWidget(self.regex_box)
        row.addWidget(self.add_button)
        row.addWidget(self.save_button)
        outer.addLayout(row)

        self.sources_row = QHBoxLayout()
        self.sources_row.setSpacing(8)
        self.source_boxes: dict[str, QCheckBox] = {}
        self.sources_row.addStretch(1)
        outer.addLayout(self.sources_row)

        self.error_label = QLabel("")
        self.error_label.setObjectName("hint")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        outer.addWidget(self.error_label)

        self.pane = ConsolePane(tr('로그 뷰어'), self.store, [],
                                ts_mode=profile.ts_mode, hide_empty=profile.hide_empty,
                                max_blocks=50_000)
        self.pane.show_prefix = True   # 여러 파일을 섞어 보므로 출처 식별이 필요하다
        self.pane.extra_filter = self._match
        self.pane.state_pill.hide()
        if profile.highlight_rules:
            self.pane.set_highlight_rules(profile.highlight_rules)
        outer.addWidget(self.pane, 1)

        # 타이핑마다 전체를 다시 그리면 렉이 걸린다 — 필터드뷰와 같은 250ms 디바운스
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._refresh_pane)

        self.edit.textChanged.connect(self._on_rule_changed)
        self.case_box.toggled.connect(self._on_rule_changed)
        self.regex_box.toggled.connect(self._on_rule_changed)
        self.add_button.clicked.connect(self._browse_add)
        self.save_button.clicked.connect(self.save_to_file)

        if paths:
            self.add_files(paths)

    # ------------------------------------------------------------------ 파일

    def add_files(self, paths: list[str]) -> None:
        total = sum(os.path.getsize(path) for path in paths if os.path.exists(path))
        if not confirm_large(self, total):
            return
        errors = self.store.add_files(paths)
        if errors:
            names = ", ".join(os.path.basename(path) for path, _reason in errors)
            self.error_label.setText(tr('읽지 못한 파일: {0}').format(names))
            self.error_label.show()
        if self.store.all_plain():
            self.pane.ts_mode = TS_OFF   # 복원할 시각이 없는 파일뿐이면 타임스탬프를 끈다
        self._rebuild_source_boxes()
        self._sync_rule()
        self._refresh_pane()

    def _browse_add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr('로그 파일 선택'), "", "Log (*.log *.txt);;All (*)")
        if paths:
            self.add_files(paths)

    def _rebuild_source_boxes(self) -> None:
        """스토어 소스 목록에 맞춰 체크박스를 다시 깐다 — 기존 선택 상태는 유지한다."""
        prior = {key: box.isChecked() for key, box in self.source_boxes.items()}
        for box in self.source_boxes.values():
            self.sources_row.removeWidget(box)
            box.deleteLater()
        self.source_boxes = {}
        for index, source in enumerate(self.store.sources()):
            box = QCheckBox(source)
            box.setChecked(prior.get(source, True))
            box.toggled.connect(self._on_rule_changed)
            self.source_boxes[source] = box
            self.sources_row.insertWidget(index, box)

    # ------------------------------------------------------------------ 필터

    def _selected_sources(self) -> list[str]:
        chosen = [source for source, box in self.source_boxes.items() if box.isChecked()]
        return chosen or self.store.sources()

    def _match(self, line) -> bool:
        if self._compiled is None:
            return not self.rule.pattern
        return self._compiled.search(line.text) is not None

    def _sync_rule(self) -> None:
        self.rule.pattern = self.edit.text()
        self.rule.is_regex = self.regex_box.isChecked()
        self.rule.case_sensitive = self.case_box.isChecked()
        self.rule.ports = self._selected_sources()
        self._compiled = self.rule.compiled()
        self.pane.ports = list(self.rule.ports)

    def _on_rule_changed(self, *_args) -> None:
        self._sync_rule()
        self._refresh_timer.start()

    def _refresh_pane(self) -> None:
        self.pane.reload()

    # ------------------------------------------------------------------ 저장

    def save_to_file(self) -> None:
        """보이는 매치 결과를 그대로 저장 — 필터드뷰의 저장과 같은 사용법."""
        stamp = time.strftime("%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, tr('필터 결과 저장'), f"viewer_{stamp}.log", "Log (*.log *.txt);;All (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"# viewer: {', '.join(os.path.basename(p) for p in self.store.paths())}"
                         f"  filter: {self.rule.label()}"
                         f"  saved {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                fh.write(self.pane.view.toPlainText())
                fh.write("\n")
            self.save_button.setText(tr('저장됨 ✓'))
            QTimer.singleShot(2000, self.save_button,
                              lambda: self.save_button.setText(tr('결과 저장')))
        except Exception as exc:  # noqa: BLE001
            diag.exception("logviewer", f"뷰어 결과 저장 실패: {path}")
            self.save_button.setText(tr('저장 실패: {0}').format(str(exc)[:30]))


class LogViewerDock(QDockWidget):
    """뷰어를 감싸는 도크 — 메인 창에 붙이거나 떼어내 독립 창으로 쓴다."""

    closed = Signal(object)

    def __init__(self, profile: Profile, paths: list[str], parent: QWidget | None = None):
        super().__init__(tr('로그 뷰어'), parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setObjectName(f"logviewer_dock_{id(self):x}")
        self.viewer = LogViewerWidget(profile, paths, self)
        self.setWidget(self.viewer)
        names = [os.path.basename(path) for path in self.viewer.store.paths()]
        if names:
            shown = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
            self.setWindowTitle(tr('로그 뷰어 — {0}').format(shown))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        self.closed.emit(self)
        # extra_filter 가 위젯의 바운드 메서드라 순환 참조가 생긴다 — 닫을 때 끊어
        # 스크롤백을 문 채로 남지 않게 한다 (필터드뷰와 같은 처리)
        self.viewer.pane.extra_filter = None
        self.viewer.pane.clear_view()
        super().closeEvent(event)
