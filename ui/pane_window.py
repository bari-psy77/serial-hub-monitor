"""PaneWindow — 콘솔 pane 을 별도 창으로 띄운다 (멀티 모니터 배치용).

pane 위젯 자체를 옮겨 담는다(복제 아님) — 그래서 분리한 창에서도 같은 커서·검색·
하이라이트가 그대로 살아 있고, 창을 닫으면 원래 레이아웃 자리로 되돌아간다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .console_pane import ConsolePane
from ..core.i18n import tr


class PaneWindow(QWidget):
    closed = Signal(object)   # 인자 = 되돌려줄 ConsolePane

    def __init__(self, pane: ConsolePane, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowTitle(f"Serial Hub — {title}")
        self.pane = pane

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(pane)
        pane.show()
        pane.pop_button.setText("⧉↩")
        pane.pop_button.setToolTip(tr('원래 자리로 되돌리기 (창을 닫아도 복귀합니다)'))
        self.resize(900, 560)

    def release(self) -> ConsolePane:
        """pane 을 레이아웃으로 돌려보내기 전에 소유권을 놓는다."""
        pane = self.pane
        self.layout().removeWidget(pane)
        pane.setParent(None)
        pane.pop_button.setText("⧉")
        pane.pop_button.setToolTip(tr('별도 창으로 분리 (닫으면 원래 자리로 복귀)'))
        self.pane = None
        return pane

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        if self.pane is not None:
            self.closed.emit(self)
        super().closeEvent(event)
