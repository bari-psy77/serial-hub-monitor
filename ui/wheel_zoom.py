"""Ctrl+휠 확대/축소를 **애플리케이션 한 곳**에서 받는다.

★위젯마다 필터를 다는 방식은 창이 늘 때마다 구멍이 난다 — 본문(view)·viewport·
스크롤바·필터 입력칸·제목줄이 저마다 다른 위젯이라, 커서가 어디에 있었느냐로
동작이 갈렸다. 실사용 신고 "창이 생기고 처음 휠이 안 된다 (필터뷰 생성 → 휠)"
가 정확히 그 구멍이었다. 여기서 한 번에 받고 **어떤 pane 안이냐**로만 나눈다.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QDockWidget

from .console_pane import ConsolePane
from .terminal_pane import TerminalPane


class WheelZoomFilter(QObject):
    """QApplication 에 걸어 쓰는 필터 — 콘솔/터미널 안에서만 동작한다.

    창 여러 개(테스트의 가상 3콘솔)가 한 프로세스에 뜰 수 있으므로, 이벤트가
    **자기 창** 것일 때만 처리한다. 남의 창 글자를 건드리면 안 된다.
    """

    def __init__(self, owner, console_zoom, terminal_zoom):
        super().__init__(owner)
        self._owner = owner
        self._console_zoom = console_zoom
        self._terminal_zoom = terminal_zoom

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 시그니처
        if event.type() != QEvent.Wheel or not (event.modifiers() & Qt.ControlModifier):
            return False
        steps = event.angleDelta().y()
        if not steps:
            return False
        zoom = self._zoom_for(obj)
        if zoom is None:
            return False
        zoom(1 if steps > 0 else -1)
        return True

    def _zoom_for(self, obj):
        """이벤트가 떨어진 곳을 부모로 거슬러 올라가 담당 확대 함수를 찾는다.

        본문 밖(필터 입력칸·도크 제목줄·빈자리)이라도 **콘솔/터미널 창 안**이면
        그 창의 확대로 친다 — 새 창을 열자마자 돌린 휠이 여기 떨어진다.
        """
        node = obj
        dock = None
        while node is not None:
            if isinstance(node, ConsolePane):
                return self._console_zoom
            if isinstance(node, TerminalPane):
                return self._terminal_zoom
            if isinstance(node, QDockWidget):
                dock = node
            if node is self._owner:          # 우리 창 안에서 난 일이다
                return self._dock_zoom(dock)
            node = node.parent()
        return None

    def _dock_zoom(self, dock):
        """도크(필터드뷰·로그 뷰어·터미널) 안이면 그 안에 든 pane 종류로 정한다."""
        if dock is None:
            return None
        if dock.findChild(TerminalPane) is not None:
            return self._terminal_zoom
        if dock.findChild(ConsolePane) is not None:
            return self._console_zoom
        return None
