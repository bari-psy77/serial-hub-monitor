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
    theme_changed = Signal(str)

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

        theme_card = theme.Card(tr('화면 테마'))
        theme_body = theme_card.body()
        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        theme_row.addWidget(QLabel(tr('밝기')))
        self.theme_combo = QComboBox()
        # ★itemData 는 저장되는 키(light/dark), itemText 는 표시명 — 언어가 바뀌어도
        #   저장 값이 흔들리면 안 된다 (색 이름·포트 role 과 같은 규칙)
        for key, label in (("light", tr('라이트')), ("dark", tr('다크'))):
            self.theme_combo.addItem(label, key)
        index = self.theme_combo.findData(config_mod.theme())
        self.theme_combo.setCurrentIndex(index if index >= 0 else 0)
        self.theme_combo.setMinimumWidth(180)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch(1)
        theme_body.addLayout(theme_row)
        theme_note = QLabel(tr('고르면 바로 적용됩니다 (언어와 달리 다시 켜지 않아도 됩니다).'))
        theme_note.setObjectName("hint")
        theme_note.setWordWrap(True)
        theme_body.addWidget(theme_note)

        outer.addWidget(card)
        outer.addWidget(theme_card)
        outer.addStretch(1)

        self.combo.currentIndexChanged.connect(self._on_changed)

    def _on_theme_changed(self, _index: int) -> None:
        self.theme_changed.emit(self.theme_combo.currentData())

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
