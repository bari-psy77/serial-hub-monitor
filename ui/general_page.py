"""GeneralPage — 사람 단위 설정(언어). 프로파일이 아니라 settings.json 에 저장한다.

장비별 설정(프로파일)과 달리 언어는 쓰는 사람의 취향이라, 프로파일을 바꿔도
따라다녀야 한다.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget)

from ..core import config as config_mod
from ..core.i18n import LANGUAGES, current_language, tr
from . import theme


class GeneralPage(QWidget):
    language_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 16)
        outer.setSpacing(12)

        card = theme.Card(tr('언어 (Language)'))
        body = card.body()

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(tr('화면 언어')))
        self.combo = QComboBox()
        for code, label in LANGUAGES.items():
            self.combo.addItem(label, code)
        index = self.combo.findData(current_language())
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self.combo.setMinimumWidth(180)
        row.addWidget(self.combo)
        row.addStretch(1)
        body.addLayout(row)

        self.note = QLabel(tr('바꾸면 다음에 프로그램을 켤 때부터 적용됩니다. '
                              '번역이 없는 문구는 한국어로 나옵니다.'))
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        body.addWidget(self.note)

        outer.addWidget(card)
        outer.addStretch(1)

        self.combo.currentIndexChanged.connect(self._on_changed)

    def _on_changed(self) -> None:
        code = self.combo.currentData()
        config_mod.set_language(code)
        self.note.setText(tr('언어를 바꿨습니다 — 다음에 프로그램을 켤 때부터 적용됩니다.'))
        self.note.setStyleSheet(f"QLabel {{ color: {theme.SUCCESS}; background: transparent; }}")
        self.language_changed.emit(code)

    def reload(self) -> None:
        index = self.combo.findData(config_mod.language())
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self.combo.blockSignals(False)
