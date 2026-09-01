"""도크 공통 동작 — 뷰어·터미널 도크가 같이 쓴다."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget

# 떼어낸 도크에 붙일 창 장식. QDockWidget 의 기본 플로팅 창은 닫기 버튼뿐이라
# 최대화가 안 된다 — 로그 뷰어를 크게 보려면 창을 손으로 끌어 늘려야 했다 (실기 신고).
FLOATING_FLAGS = (Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                  | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
                  | Qt.WindowCloseButtonHint)


def enable_maximize_when_floating(dock: QDockWidget) -> None:
    """도크를 떼어내면 보통 창처럼 최소화·최대화 버튼을 갖게 한다."""

    def _on_top_level_changed(floating: bool) -> None:
        if not floating:
            return   # 다시 붙을 때는 Qt 가 자기 플래그로 되돌린다
        dock.setWindowFlags(FLOATING_FLAGS)
        dock.show()  # ★플래그를 바꾸면 창이 숨겨진다 — 다시 띄우지 않으면 사라진다

    dock.topLevelChanged.connect(_on_top_level_changed)
