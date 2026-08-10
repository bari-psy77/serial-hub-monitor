"""ProfilePage — 프로파일 저장/불러오기. 벤치마다 COM 매핑이 달라 파일로 공유한다."""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QListWidget, QPushButton,
                               QVBoxLayout, QWidget)

from ..core import config as config_mod
from ..core.session import SerialHubSession
from . import theme
from ..core.i18n import tr


class ProfilePage(QWidget):
    load_requested = Signal(str)
    save_requested = Signal(str)

    def __init__(self, session: SerialHubSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(12)

        card = theme.Card(tr('프로파일'))
        self.list = QListWidget()
        self.list.setMinimumHeight(220)
        card.add(self.list)

        row = QHBoxLayout()
        self.save_button = QPushButton(tr('현재 설정 저장'))
        self.save_button.setObjectName("primary")
        self.save_as_button = QPushButton(tr('다른 이름으로'))
        self.load_button = QPushButton(tr('불러오기'))
        for button in (self.save_button, self.save_as_button, self.load_button):
            row.addWidget(button)
        row.addStretch(1)
        card.add_layout(row)
        card.add(_hint(tr('프로파일에는 포트 매핑·baud·로그 설정·룰·창 배치가 들어갑니다. 파일로 복사하면 '
                          '다른 벤치에서 그대로 쓸 수 있습니다.')))
        outer.addWidget(card)

        info = theme.Card(tr('저장 위치'))
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setObjectName("hint")
        info.add(self.path_label)
        self.open_button = QPushButton(tr('폴더 열기'))
        info.add(self.open_button)
        outer.addWidget(info)
        outer.addStretch(1)

        self.save_button.clicked.connect(lambda: self.save_requested.emit(self.session.profile.name))
        self.save_as_button.clicked.connect(self._save_as)
        self.load_button.clicked.connect(self._load)
        self.list.itemDoubleClicked.connect(lambda _i: self._load())
        self.open_button.clicked.connect(self._open_folder)

        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        current = self.session.profile.name
        for name in config_mod.list_profiles():
            label = tr('{0}   ← 현재').format(name) if name == current else name
            self.list.addItem(label)
            if name == current:
                self.list.setCurrentRow(self.list.count() - 1)
        self.path_label.setText(config_mod.PROFILE_DIR)

    def _selected(self) -> str:
        item = self.list.currentItem()
        return item.text().split("   ←")[0].strip() if item else ""

    def _save_as(self) -> None:
        name, ok = QInputDialog.getText(self, tr('다른 이름으로 저장'), tr('프로파일 이름'))
        if ok and name.strip():
            self.save_requested.emit(name.strip())

    def _load(self) -> None:
        name = self._selected()
        if name and name != self.session.profile.name:
            self.load_requested.emit(name)

    def _open_folder(self) -> None:
        try:
            os.makedirs(config_mod.PROFILE_DIR, exist_ok=True)
            os.startfile(config_mod.PROFILE_DIR)  # noqa: S606
        except Exception:  # noqa: BLE001
            pass


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label
