"""SettingsDialog — Connection / Rules / Log / Profile 을 한 모달에 모은다.

메인 화면은 Monitor 만 남기고, 설정은 여기로 들어온다. 각 페이지는 기존 위젯을
그대로 재사용하므로 동작이 갈라지지 않는다.

★ 로그 설정은 **OK 를 눌러야** 적용된다 — 입력 도중 값이 반영되면 그때마다 파일이
새로 열려 쓸모없는 파일이 쌓인다 (사용자 보고).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QListWidget,
                               QListWidgetItem, QStackedWidget, QVBoxLayout, QWidget)

from ..core.config import Profile
from ..core.session import SerialHubSession
from . import theme
from .connection_page import ConnectionPage
from .general_page import GeneralPage
from .log_page import LogPage
from .profile_page import ProfilePage
from .rules_page import RulesPage
from ..core.i18n import tr

PAGE_CONNECTION = 0
PAGE_RULES = 1
PAGE_LOG = 2
PAGE_PROFILE = 3
PAGE_GENERAL = 4


class SettingsDialog(QDialog):
    """모달 설정 창. 페이지 전환은 왼쪽 목록으로."""

    PAGE_CONNECTION = PAGE_CONNECTION
    PAGE_RULES = PAGE_RULES
    PAGE_LOG = PAGE_LOG
    PAGE_PROFILE = PAGE_PROFILE
    PAGE_GENERAL = PAGE_GENERAL

    applied = Signal()          # 룰·연결 등 즉시 반영되는 변경
    log_settings_applied = Signal()
    theme_changed = Signal(str)   # OK 를 눌러 확정된 로그 설정

    def __init__(self, session: SerialHubSession, parent: QWidget | None = None,
                 page: int = PAGE_CONNECTION):
        super().__init__(parent)
        self.session = session
        self.profile: Profile = session.profile
        self.setWindowTitle(tr('설정'))
        self.setModal(True)
        self.resize(1120, 720)

        self.nav = QListWidget()
        self.nav.setFixedWidth(170)
        for label in (
                tr('연결 (Connection)'), tr('규칙 (Rules)'), tr('로그 (Log)'),
                tr('프로파일 (Profile)'), tr('일반 (General)')):
            QListWidgetItem(label, self.nav)
        self.nav.setCurrentRow(page)

        self.connection_page = ConnectionPage(session)
        self.rules_page = RulesPage(self.profile)
        self.log_page = LogPage(self.profile)
        # 콘솔 수를 바꾸면 로그 파일명 칸도 같이 접힌다 (창을 닫았다 열 필요 없이)
        self.connection_page.ports_changed.connect(self.log_page.refresh_ports)
        self.profile_page = ProfilePage(session)
        self.general_page = GeneralPage()
        self.general_page.theme_changed.connect(self.theme_changed)

        self.stack = QStackedWidget()
        for widget in (self.connection_page, self.rules_page, self.log_page, self.profile_page,
                       self.general_page):
            self.stack.addWidget(widget)
        self.stack.setCurrentIndex(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr('확인'))
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText(tr('닫기'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(10)
        outer.addLayout(body, 1)
        outer.addWidget(buttons)

        # 규칙/연결은 즉시 반영 (모니터를 보면서 조정하는 것들이다)
        self.rules_page.rules_changed.connect(self.applied.emit)
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}")


    def refresh_theme(self) -> None:
        """생성 때 한 번만 바른 배경을 다시 바른다 (QSS 로 안 덮인다)."""
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}")

    def go_to(self, page: int) -> None:
        self.nav.setCurrentRow(page)
        self.stack.setCurrentIndex(page)

    def accept(self) -> None:
        """OK — 여기서만 로그 설정을 확정한다."""
        if self.log_page.commit():
            self.log_settings_applied.emit()
        self.applied.emit()
        super().accept()

    def reject(self) -> None:
        self.log_page.revert()
        super().reject()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        # 입력란에서 Enter 를 눌렀다고 창이 닫히면 설정 도중에 튕긴다
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)
