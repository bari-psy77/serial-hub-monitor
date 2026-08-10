"""LogStartDialog — 기록을 시작하기 직전에 저장 위치·파일명을 확인받는 창.

기록은 자동으로 시작하지 않는다. 연결만으로 파일이 생기면 어떤 이름으로 어디에
쌓이는지 모른 채 증적이 만들어지고, 나중에 티켓에 붙일 파일을 찾느라 헤맨다.
[로그 시작] 을 누를 때마다 이 창을 띄워 이번 기록의 이름을 눈으로 확인하게 한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.config import Profile
from .log_page import LogPage
from ..core.i18n import tr


class LogStartDialog(QDialog):
    def __init__(self, profile: Profile, parent: QWidget | None = None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle(tr('로그 기록 시작'))
        self.setModal(True)
        self.resize(860, 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        intro = QLabel(tr('이번 기록을 어디에 어떤 이름으로 남길지 확인해 주세요. [기록 시작] 을 누르면 '
                          '그때부터 파일에 쌓입니다.'))
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.log_page = LogPage(profile)
        layout.addWidget(self.log_page, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton(tr('취소'))
        self.start_button = QPushButton(tr('기록 시작'))
        self.start_button.setObjectName("primary")
        self.start_button.setDefault(True)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)

        self.start_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.log_page.revert()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        # 파일명을 입력하다 Enter 를 치면 창이 닫히는 게 아니라 입력이 끝나야 한다
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def accept(self) -> None:  # noqa: D102
        self.log_page.commit()
        super().accept()

    def reject(self) -> None:  # noqa: D102
        self.log_page.revert()
        super().reject()
