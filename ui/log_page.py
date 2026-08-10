"""LogPage — 로그 저장 설정. **OK 를 눌러야 적용된다.**

입력하는 즉시 반영하면 값을 고칠 때마다 로그 파일이 새로 열려 빈 파일이 쌓인다
(사용자 보고). 그래서 이 페이지는 편집 중엔 프로파일을 건드리지 않고,
`commit()` 에서만 한 번에 쓴다.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..core.config import Profile
from . import theme
from ..core.i18n import tr


class LogPage(QWidget):
    def __init__(self, profile: Profile, parent: QWidget | None = None):
        super().__init__(parent)
        self.profile = profile

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(12)

        location = theme.Card(tr('저장 위치'))
        form = QFormLayout()
        form.setSpacing(10)
        row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.browse_button = QPushButton(tr('찾아보기'))
        row.addWidget(self.dir_edit, 1)
        row.addWidget(self.browse_button)
        form.addRow(tr('로그 폴더'), row)
        self.dir_hint = QLabel(tr('이 아래에 날짜별(MMDD) 폴더가 자동으로 생깁니다'))
        self.dir_hint.setObjectName("hint")
        form.addRow("", self.dir_hint)
        location.add_layout(form)
        outer.addWidget(location)

        naming = theme.Card(tr('파일 이름'))
        name_form = QFormLayout()
        name_form.setSpacing(10)
        self.prefix_edit = QLineEdit()
        name_form.addRow(tr('세션 접두어'), self.prefix_edit)
        self.include_box = QCheckBox(tr('파일명에 세션 접두어 포함 (<접두어>_HHMMSS_<이름>.log)'))
        self.include_box.setToolTip(tr('끄면 <이름>.log 로 고정됩니다 — 매번 같은 파일에 이어 씁니다'))
        name_form.addRow("", self.include_box)
        self.port_edits: dict[str, QLineEdit] = {}
        self.port_labels: dict[str, QLabel] = {}
        for entry in self.profile.ports:
            edit = QLineEdit()
            edit.setPlaceholderText(tr('{0} (기본값)').format(entry.role.lower()))
            label = QLabel(tr('{0} 파일명').format(entry.role))
            self.port_edits[entry.role] = edit
            self.port_labels[entry.role] = label
            name_form.addRow(label, edit)
        self.merged_edit = QLineEdit()
        name_form.addRow(tr('병합 파일명'), self.merged_edit)
        naming.add_layout(name_form)
        self.preview = QLabel("")
        self.preview.setObjectName("hint")
        self.preview.setWordWrap(True)
        naming.add(self.preview)
        outer.addWidget(naming)

        rotate = theme.Card(tr('파일 분절'))
        rotate_form = QFormLayout()
        self.max_mb = QSpinBox()
        self.max_mb.setRange(0, 4096)
        self.max_mb.setSuffix(" MB")
        self.max_mb.setSpecialValueText(tr('사용 안 함'))
        self.max_mb.setToolTip(tr('병합 파일이 이 크기를 넘으면 _p2, _p3 … 로 나눕니다 (0 = 안 나눔)'))
        rotate_form.addRow(tr('크기 상한'), self.max_mb)
        rotate.add_layout(rotate_form)
        rotate.add(_hint(tr('자정을 넘기면 날짜 폴더가 바뀌는 것과는 별개입니다. 수신은 어느 쪽도 멈추지 '
                            '않습니다.')))
        outer.addWidget(rotate)

        outer.addWidget(_hint(tr('여기 설정은 [확인] 을 눌러야 적용됩니다 — 편집 도중에 반영하면 빈 로그 '
                                 '파일이 계속 생깁니다.')))
        outer.addStretch(1)

        self.browse_button.clicked.connect(self._browse)
        for widget in (self.prefix_edit, self.merged_edit, *self.port_edits.values()):
            widget.textChanged.connect(self._update_preview)
        self.include_box.toggled.connect(self._update_preview)

        self.revert()

    # ------------------------------------------------------------------ 값 이동

    def revert(self) -> None:
        """프로파일 값을 위젯으로 (창을 열 때 / 취소할 때)."""
        self.refresh_ports()
        self.dir_edit.setText(self.profile.log_base_dir)
        self.prefix_edit.setText(self.profile.session_prefix)
        self.include_box.setChecked(self.profile.log_include_session)
        self.merged_edit.setText(self.profile.merged_log_name)
        for entry in self.profile.ports:
            edit = self.port_edits.get(entry.role)
            if edit is not None:
                edit.setText(entry.log_name)
        self.max_mb.setValue(int(self.profile.max_log_mb))
        self._update_preview()

    def refresh_ports(self) -> None:
        """안 쓰는 포트는 파일명 칸도 감춘다 — 만들지도 않을 파일의 이름을 물을 이유가 없다."""
        active = self.profile.active_roles()
        for role, edit in self.port_edits.items():
            visible = role in active
            edit.setVisible(visible)
            self.port_labels[role].setVisible(visible)
        self._update_preview()

    def commit(self) -> bool:
        """위젯 값을 프로파일로. 반환값 = 실제로 바뀐 게 있나."""
        changed = False
        new_dir = self.dir_edit.text().strip()
        if new_dir and new_dir != self.profile.log_base_dir:
            self.profile.log_base_dir = new_dir
            changed = True
        prefix = self.prefix_edit.text().strip()
        if prefix and prefix != self.profile.session_prefix:
            self.profile.session_prefix = prefix
            changed = True
        if self.include_box.isChecked() != self.profile.log_include_session:
            self.profile.log_include_session = self.include_box.isChecked()
            changed = True
        merged = self.merged_edit.text().strip() or "all"
        if merged != self.profile.merged_log_name:
            self.profile.merged_log_name = merged
            changed = True
        for entry in self.profile.ports:
            edit = self.port_edits.get(entry.role)
            if edit is not None and edit.text().strip() != entry.log_name:
                entry.log_name = edit.text().strip()
                changed = True
        if self.max_mb.value() != self.profile.max_log_mb:
            self.profile.max_log_mb = self.max_mb.value()
            changed = True
        return changed

    # ------------------------------------------------------------------ 보조

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr('로그 폴더 선택'), self.dir_edit.text())
        if path:
            self.dir_edit.setText(os.path.normpath(path))

    def _update_preview(self, *_args) -> None:
        prefix = self.prefix_edit.text().strip() or "serialhub"
        session = f"{prefix}_HHMMSS"
        include = self.include_box.isChecked()
        names = []
        active = self.profile.active_roles()
        for entry in self.profile.ports:
            if entry.role not in active:
                continue
            edit = self.port_edits.get(entry.role)
            piece = (edit.text().strip() if edit else "") or entry.role.lower()
            names.append(f"{session}_{piece}.log" if include else f"{piece}.log")
        merged = self.merged_edit.text().strip() or "all"
        names.append(f"{session}_{merged}.log" if include else f"{merged}.log")
        self.preview.setText(tr('예: ') + ", ".join(names))


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label
