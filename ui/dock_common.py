"""도크 공통 동작 — 뷰어·터미널 도크가 같이 쓴다."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QPushButton

from ..core.i18n import tr


def toggle_maximize(dock: QDockWidget) -> None:
    """도크 창을 최대화 / 원래 크기로.

    ★네이티브 프레임에 최대화 버튼을 달아주려고 setWindowFlags(Qt.Window|…) 로 창
    장식을 바꾸면 안 된다 — 그 프레임의 최대화 버튼을 **실제로 클릭**하는 순간 Qt 의
    도크 처리와 어긋나 도크가 통째로 파괴된다 (실기 재현: 뷰어가 사라지고 앱이 닫혔다).
    Qt 기본 창 장식을 그대로 두고, 우리 버튼에서 showMaximized/showNormal 만 부른다 —
    이 경로는 안전하다.
    """
    if not dock.isFloating():
        dock.setFloating(True)      # 도킹 중이면 떼어내고 바로 키운다 (클릭 한 번)
        dock.showMaximized()
        return
    if dock.windowState() & Qt.WindowMaximized:
        dock.showNormal()
    else:
        dock.showMaximized()


def make_maximize_button(dock: QDockWidget) -> QPushButton:
    """도크 툴바에 놓을 최대화/복원 버튼."""
    button = QPushButton("⛶")
    button.setToolTip(tr('창 최대화 / 복원 — 도킹 중이면 떼어내서 키웁니다'))
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(lambda: toggle_maximize(dock))
    return button
