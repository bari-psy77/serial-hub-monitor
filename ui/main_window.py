"""MainWindow — 세그먼트 탭 · 분할 콘솔 · 명령 패널 조립. UI 문서 §1 / §7 / §8.

QTimer 1개(50ms)가 모든 뷰의 pump 와 상태 갱신을 돌린다 — 라인마다 시그널을 쏘지 않는다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

from PySide6 import QtCore
from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QSplitter, QTabWidget, QVBoxLayout,
                               QWidget)

from ..core import config as config_mod
from ..core.bridge import BridgeServer
from ..core.config import Profile
from ..core.diag import diag
from ..core.filters import TriggerWatcher
from ..core.logstore import MARKER_PORT, render_line
from ..core.filters import FilterRule
from ..core.port import STATE_DISCONNECTED
from ..core.session import SerialHubSession
from . import theme
from .appicon import app_icon
from .command_panel import CommandPanel
from .console_pane import ConsolePane
from .filter_view import FilterView
from .log_start_dialog import LogStartDialog
from .log_viewer import LogViewerDock
from .pane_window import PaneWindow
from .terminal_pane import TerminalDock
from ..core.terminal import launch_admin_shell
from .settings_dialog import SettingsDialog
from ..core.i18n import tr

TICK_MS = 50
LAYOUT_SPLIT = "split"
LAYOUT_COLUMNS = "columns"
LAYOUT_TABS = "tabs"
LAYOUT_MERGED = "merged"
# ★모듈 최상위에서 tr() 를 부르면 **임포트 시점**에 굳는다 — 언어 설정은 그보다 뒤에
#   정해지므로 늘 한국어가 박힌다. 화면에 쓸 때 번역하도록 함수로 둔다.
LAYOUT_MODES = (LAYOUT_SPLIT, LAYOUT_COLUMNS, LAYOUT_TABS, LAYOUT_MERGED)


def layout_labels() -> dict[str, str]:
    return {
        LAYOUT_SPLIT: tr('좌1 + 우2 (기본)'),
        LAYOUT_COLUMNS: tr('3단 가로'),
        LAYOUT_TABS: tr('탭'),
        LAYOUT_MERGED: tr('병합 뷰'),
    }


class MainWindow(QMainWindow):
    def __init__(self, profile: Profile, warning: str = ""):
        super().__init__()
        self.session = SerialHubSession(profile)
        self.profile = profile
        self.filter_views: list[FilterView] = []
        self.viewer_docks: list[LogViewerDock] = []
        self.terminal_docks: list[TerminalDock] = []
        self.layout_mode = str(profile.layout.get("mode", LAYOUT_SPLIT))
        self._console_container: QWidget | None = None
        self._splitters: list[tuple[str, QSplitter]] = []
        self.popped: dict[str, PaneWindow] = {}   # 별도 창으로 분리한 콘솔

        self.setWindowTitle(f"Serial Hub — {profile.name}")
        self.resize(1360, 860)

        # 메인은 Monitor 하나만 — 설정은 모달로 뺀다
        self.monitor_page = self._build_monitor_page()
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)
        outer.addWidget(self._build_action_bar())
        outer.addWidget(self.monitor_page, 1)
        self.setCentralWidget(central)
        self.settings_dialog: SettingsDialog | None = None

        self._build_menus()
        self._build_status_bar()

        self.trigger_watcher = TriggerWatcher()
        self.bridge = BridgeServer(self.session, self.profile.bridge_port or 0)
        if self.profile.bridge_port:
            self.bridge.start()  # 실패해도 앱은 산다 — 칩 툴팁에 사유 표시

        self.apply_rules()
        self._sync_active_ports()
        self._restore_geometry()

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

        if warning:
            self.set_status(warning, theme.WARNING)
        elif not self.profile.enabled_ports():
            self.set_status(tr('포트가 아직 지정되지 않았습니다 — [연결] 을 눌러 COM 을 고르고 [전체 연결]'),
                            theme.TEXT_SUB)

    # ------------------------------------------------------------------ 구성

    def _build_monitor_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        pill_row = QHBoxLayout()
        pill_row.setSpacing(8)
        self.pills: dict[str, theme.StatusPill] = {}
        for role in self.profile.roles():
            pill = theme.StatusPill()
            pill.setToolTip(tr('클릭 = 해당 콘솔로 이동'))
            pill.mousePressEvent = self._pill_click_handler(role)
            self.pills[role] = pill
            pill_row.addWidget(pill)
        pill_row.addStretch(1)
        self.trigger_chip = QPushButton("⚡ 0")
        self.trigger_chip.setObjectName("toolToggle")
        self.trigger_chip.setToolTip(tr('트리거 발생 집계 (설정 > 규칙에서 편집) — 클릭 = 카운터 초기화'))
        self.trigger_chip.clicked.connect(self.reset_triggers)
        pill_row.addWidget(self.trigger_chip)
        self.clear_all_button = QPushButton(tr('🗑 버퍼'))
        self.clear_all_button.setToolTip(
            tr('전 콘솔 화면 + 메모리 버퍼 비우기 (Ctrl+Shift+L) — 로그 파일은 그대로 남습니다'))
        self.clear_all_button.clicked.connect(self.clear_all_buffers)
        pill_row.addWidget(self.clear_all_button)
        self.marker_button = QPushButton(tr('📍 마커'))
        self.marker_button.setToolTip(tr('로그에 `### …` 구분 마커 삽입 (Ctrl+M) — 재현 시점 표시'))
        self.marker_button.clicked.connect(self.insert_marker)
        pill_row.addWidget(self.marker_button)
        self.log_button = QPushButton(tr('⏺ 로그 시작'))
        self.log_button.setObjectName("primary")
        self.log_button.setToolTip(
            tr('파일 기록을 시작합니다 — 누르면 저장 위치·파일명을 먼저 확인합니다. 연결만으로는 기록이 '
               '시작되지 않습니다.'))
        self.log_button.clicked.connect(self.toggle_logging)
        pill_row.addWidget(self.log_button)
        self.pause_button = QPushButton(tr('⏸ 기록멈춤'))
        self.pause_button.setToolTip(
            tr('파일 기록만 멈춥니다 (Ctrl+P) — 화면·수신은 계속. 멈춘 구간은 파일에 안 남습니다'))
        self.pause_button.clicked.connect(self.toggle_recording_pause)
        pill_row.addWidget(self.pause_button)
        self.rec_button = QPushButton("⏺ REC —")
        self.rec_button.setToolTip(tr('현재 기록 폴더 — 클릭하면 탐색기로 엽니다'))
        self.rec_button.clicked.connect(self.open_log_dir)
        pill_row.addWidget(self.rec_button)
        layout.addLayout(pill_row)

        self.panes: dict[str, ConsolePane] = {}
        for role in self.profile.roles():
            pane = ConsolePane(role, self.session.store, [role],
                               ts_mode=self.profile.ts_mode,
                               hide_empty=self.profile.hide_empty,
                               max_blocks=min(self.profile.capacity_per_port, 200_000))
            pane.pop_out_requested.connect(self.pop_out_pane)
            pane.search_committed.connect(self._remember_search)
            pane.search.edit.load_history(
                list(reversed(self.profile.search_history.get("console", []))))
            self.panes[role] = pane
        # MARK 를 처음부터 포함시킨다 — 브리지(자동화)가 넣은 마커도 병합 뷰에 보여야 한다
        self.merged_pane = ConsolePane(tr('병합 뷰'), self.session.store,
                                       [*self.profile.roles(), MARKER_PORT],
                                       ts_mode=self.profile.ts_mode,
                                       hide_empty=self.profile.hide_empty,
                                       max_blocks=min(self.profile.capacity_per_port, 200_000))
        self.merged_pane.state_pill.hide()
        self.merged_pane.pop_out_requested.connect(self.pop_out_pane)

        self.console_holder = QWidget()
        self.console_holder_layout = QVBoxLayout(self.console_holder)
        self.console_holder_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.console_holder, 1)

        # 명령 대상은 전 포트다 — 장비마다 어느 콘솔이 입력을 받는지 다르고,
        # probe 를 모든 포트에 할 수 있으니 명령도 막아둘 이유가 없다.
        # 잘못 보낸 경우는 오지정 힌트(unknown-command 응답 감지)가 잡는다.
        commandable = self.profile.active_roles()
        self.command_panel = CommandPanel(commandable, self.session.send, self.session.store,
                                          self.profile.command_history)
        self.command_panel.set_labels(self._port_labels())
        self.command_panel.set_redactor(self.session.redactor)
        self.command_panel.pad_edit.setPlainText(self.profile.scratchpad)
        layout.addWidget(self.command_panel)

        for pane in [*self.panes.values(), self.merged_pane]:
            pane.set_font_size(self.profile.console_font_size)
            pane.set_word_wrap(self.profile.word_wrap)
            pane.set_ansi_color(self.profile.ansi_color)

        self._apply_layout(self.layout_mode)
        return page

    def _restore_sizes(self, splitter: QSplitter, key: str, fallback: list[int]) -> None:
        stored = self.profile.layout.get("splitters", {}).get(key)
        splitter.setSizes(usable_sizes(stored, splitter.count()) or fallback)

    def _capture_splitter_sizes(self) -> None:
        stored = self.profile.layout.setdefault("splitters", {})
        for key, splitter in self._splitters:
            try:
                stored[key] = list(splitter.sizes())
            except RuntimeError:
                continue  # 이미 파괴된 splitter — 이전 값을 유지한다

    def _capture_layout(self) -> None:
        """분할 비율·창 지오메트리를 프로파일에 담는다 (UI 문서 §1 이 약속한 복원)."""
        self._capture_splitter_sizes()
        self.profile.layout["mode"] = self.layout_mode
        self.profile.layout["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")

    def _restore_geometry(self) -> None:
        raw = self.profile.layout.get("geometry")
        if not isinstance(raw, str) or not raw:
            return
        try:
            self.restoreGeometry(QByteArray.fromBase64(raw.encode("ascii")))
        except Exception:  # noqa: BLE001 - 깨진 지오메트리로 기동을 막지 않는다
            pass

    def _build_action_bar(self) -> QWidget:
        """탭 대신 아이콘 바 — 설정은 모달로 열린다."""
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        def add(text: str, tip: str, slot) -> QPushButton:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            row.addWidget(button)
            return button

        self.connect_action_button = add(
            tr('🔌 연결'), tr('포트 지정·probe·연결 (Ctrl+E)'),
            lambda: self.open_settings(SettingsDialog.PAGE_CONNECTION))
        add(tr('⚙ 설정'), tr('연결·규칙·로그·프로파일 설정 (Ctrl+,)'),
            lambda: self.open_settings(SettingsDialog.PAGE_CONNECTION))
        add(tr('🎨 규칙'), tr('하이라이트·마스킹·트리거·저장된 필터'),
            lambda: self.open_settings(SettingsDialog.PAGE_RULES))
        add(tr('📁 로그'), tr('저장 위치·파일 이름·분절'),
            lambda: self.open_settings(SettingsDialog.PAGE_LOG))
        add(tr('💾 프로파일'), tr('프로파일 저장·불러오기'),
            lambda: self.open_settings(SettingsDialog.PAGE_PROFILE))
        row.addSpacing(10)
        add(tr('🔎 필터드뷰'), tr('매치 라인만 보는 창 (Ctrl+K)'), lambda: self.open_filter_view(None))
        self.terminal_button = add(tr('🖥 터미널'), tr('PowerShell 터미널을 하단 도크로 엽니다'),
                                   self.open_terminal)
        row.addStretch(1)
        add(tr('❓ 도움말'), tr('사용 설명서 열기 (F1)'), self.open_help)
        return bar

    def settings(self) -> SettingsDialog:
        """설정 창은 하나를 만들어 재사용한다 — 열 때마다 새로 만들면 probe 진행 상태가 날아간다."""
        if self.settings_dialog is not None:
            return self.settings_dialog
        dialog = SettingsDialog(self.session, self)
        dialog.applied.connect(self._on_settings_applied)
        dialog.log_settings_applied.connect(self.retarget_logs)
        dialog.connection_page.connect_all_requested.connect(self.connect_all)
        dialog.connection_page.disconnect_all_requested.connect(self.disconnect_all)
        dialog.connection_page.port_toggle_requested.connect(self.toggle_port)
        dialog.connection_page.probe_requested.connect(dialog.connection_page.start_probe)
        dialog.connection_page.probe_all_requested.connect(dialog.connection_page.start_probe_all)
        dialog.connection_page.label_changed.connect(self._refresh_port_labels)
        dialog.connection_page.log_naming_changed.connect(self.retarget_logs)
        dialog.connection_page.ports_changed.connect(self.apply_active_ports)
        dialog.rules_page.filter_open_requested.connect(self.open_filter_view)
        dialog.profile_page.save_requested.connect(self.save_profile_as)
        dialog.profile_page.load_requested.connect(self.load_profile)
        self.settings_dialog = dialog
        return dialog

    def open_settings(self, page: int = 0) -> None:
        dialog = self.settings()
        dialog.log_page.revert()      # 지난번에 취소한 편집이 남아 있지 않게
        dialog.profile_page.refresh()
        dialog.go_to(page)
        dialog.exec()

    # 테스트·외부에서 페이지에 바로 닿기 위한 별칭
    @property
    def connection_page(self):
        return self.settings().connection_page

    @property
    def rules_page(self):
        return self.settings().rules_page

    @property
    def log_page(self):
        return self.settings().log_page

    @property
    def profile_page(self):
        return self.settings().profile_page

    def _on_settings_applied(self) -> None:
        self.apply_rules()
        self._refresh_port_labels()

    def _remember_search(self, text: str) -> None:
        """검색어를 프로파일에 남겨 재실행해도 드롭다운에 뜨게 한다."""
        text = text.strip()
        if not text:
            return
        items = self.profile.search_history.setdefault("console", [])
        if text in items:
            items.remove(text)
        items.append(text)
        del items[:-30]
        recent = list(reversed(items))
        for pane in self._all_panes():
            pane.search.edit.load_history(recent)

    def _refresh_settings_pages(self) -> None:
        dialog = self.settings_dialog
        if dialog is None:
            return   # 아직 설정을 연 적이 없다 — 열 때 새 프로파일로 만들어진다
        dialog.connection_page.rebind(self.session)
        dialog.rules_page.reload(self.profile)
        dialog.log_page.profile = self.profile
        dialog.log_page.revert()
        dialog.profile_page.session = self.session
        dialog.profile_page.refresh()

    def _report_open_failure(self, role: str, error: str) -> None:
        self.settings().connection_page.report_open_failure(role, error)

    def _sync_active_ports(self) -> None:
        """화면 구성만 현재 프로파일에 맞춘다 (기동·프로파일 전환용, 안내 문구 없음)."""
        active = self.profile.active_roles()
        for role, pill in self.pills.items():
            pill.setVisible(role in active)
        self.command_panel.set_roles(active, self._port_labels())
        self._apply_layout(self.layout_mode)

    def apply_active_ports(self) -> None:
        """사용 포트 구성이 바뀌었을 때 화면 전체를 다시 맞춘다.

        슬롯(패널·필)은 만들어 둔 채 **보이기만** 끈다 — 다시 켤 때 스크롤백과
        검색 히스토리가 살아 있어야 하고, 도중에 위젯을 파괴하면 tick() 이 죽는다.
        """
        active = self.profile.active_roles()
        for role in self.profile.roles():
            if role not in active and self.session.is_connected(role):
                self.session.disconnect(role)   # 안 쓰는 포트를 계속 물고 있을 이유가 없다
        self._sync_active_ports()
        self.retarget_logs()
        hidden = [r for r in self.profile.roles() if r not in active]
        self.set_status(
            tr('콘솔 {0}개 사용 — {1} 은(는) 숨김').format(len(active), ', '.join(hidden)) if hidden
            else tr('콘솔 {0}개 모두 사용').format(len(active)),
            theme.TEXT_SUB)

    def _port_labels(self) -> dict[str, str]:
        return {role: (entry.display() if entry else role)
                for role in self.profile.roles()
                for entry in [self.profile.port(role)]}

    def _refresh_port_labels(self) -> None:
        """포트 표시 이름이 바뀌면 콘솔 제목·상태 필·명령 대상에 반영한다."""
        labels = self._port_labels()
        for role, pane in self.panes.items():
            pane.title = labels.get(role, role)
        self.command_panel.set_labels(labels)
        self._rec_shown = None

    def open_help(self) -> None:
        """설명서 HTML — 설치본에 같이 들어간다. 없으면 온라인 대신 안내만."""
        name = tr('SerialHub_사용설명서.html')
        roots = [
            getattr(sys, "_MEIPASS", ""),                              # onefile 번들
            os.path.dirname(os.path.abspath(sys.executable)),          # exe 옆
            os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "_internal"),
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # 소스 실행
        ]
        candidates = [os.path.join(root, "docs", name) for root in roots if root]
        for path in candidates:
            if os.path.exists(path):
                self._open_path(path)
                return
        self.set_status(tr('사용 설명서 파일을 찾지 못했습니다 (docs\\SerialHub_사용설명서.html)'),
                        theme.WARNING)

    def _pill_click_handler(self, role: str):
        def handler(_event) -> None:
            self.focus_pane(role)
        return handler

    def _apply_layout(self, mode: str) -> None:
        # ★비율을 먼저 거두고 목록을 비운다. 아래에서 컨테이너를 deleteLater() 하면
        # 그 안의 splitter 가 C++ 쪽에서 파괴되는데, 탭·병합 모드는 _splitters 를
        # 새로 채우지 않아 다음 전환 때 죽은 객체를 만지고 RuntimeError 로 창이 멈춘다.
        self._capture_splitter_sizes()
        self._splitters = []
        self.layout_mode = mode if mode in LAYOUT_MODES else LAYOUT_SPLIT
        panes = [*self.panes.values(), self.merged_pane]
        popped_panes = {w.pane for w in self.popped.values() if w.pane is not None}
        if self.layout_mode == LAYOUT_MERGED and self.merged_pane in popped_panes:
            self.layout_mode = LAYOUT_SPLIT  # 병합 뷰가 분리 창에 있으면 본창은 분할로
        for pane in panes:
            if pane in popped_panes:
                continue  # 별도 창이 소유 중 — 건드리면 그 창에서 사라진다
            pane.setParent(None)
        if self._console_container is not None:
            self.console_holder_layout.removeWidget(self._console_container)
            # 병합 모드에서는 컨테이너가 merged_pane 자체다. 그걸 지우면 다음 전환에서
            # pane 이 파괴돼 tick() 이 RuntimeError 로 죽고 UI 가 영구 정지한다.
            if self._console_container not in panes:
                self._console_container.deleteLater()
            self._console_container = None

        active = self.profile.active_roles()
        roles = [r for r in self.panes
                 if r in active and self.panes[r] not in popped_panes]
        if not roles and self.layout_mode != LAYOUT_MERGED:
            roles = active[:1]  # 전부 분리된 상태 — 빈 컨테이너를 만들지 않는다
        if self.layout_mode == LAYOUT_MERGED:
            container: QWidget = self.merged_pane  # pane 자체가 컨테이너 — 절대 삭제하면 안 된다
        elif self.layout_mode == LAYOUT_TABS:
            tabs = QTabWidget()
            for role in roles:
                tabs.addTab(self.panes[role], role)
            container = tabs
        elif self.layout_mode == LAYOUT_COLUMNS or len(roles) != 3:
            splitter = QSplitter(Qt.Horizontal)
            for role in roles:
                splitter.addWidget(self.panes[role])
            self._splitters = [("columns", splitter)]
            container = splitter
        else:
            right = QSplitter(Qt.Vertical)
            right.addWidget(self.panes[roles[1]])
            right.addWidget(self.panes[roles[2]])
            splitter = QSplitter(Qt.Horizontal)
            splitter.addWidget(self.panes[roles[0]])
            splitter.addWidget(right)
            self._splitters = [("split_main", splitter), ("split_right", right)]
            container = splitter

        # 컨테이너에 안 들어간 pane 을 show() 하면 부모가 없어 별도 창으로 떠버린다.
        # 분리 창이 소유한 pane 은 그 창이 보여주므로 여기서 건드리지 않는다.
        merged_on = self.merged_pane if self.layout_mode == LAYOUT_MERGED else None
        for role, pane in self.panes.items():
            if pane not in popped_panes:
                pane.setVisible(merged_on is None and role in roles)
        active = merged_on
        if self.merged_pane not in popped_panes:
            self.merged_pane.setVisible(active is not None)

        self._console_container = container
        self.console_holder_layout.addWidget(container)
        container.show()
        # setSizes 는 splitter 가 레이아웃에 붙은 뒤에 해야 먹는다 — 붙기 전에 부르면
        # 이후 레이아웃 계산이 값을 덮어써서 저장한 비율이 조용히 무시된다
        for key, splitter in self._splitters:
            self._restore_sizes(splitter, key, [1] * splitter.count())
        if active is not None:
            self.merged_pane.reload()
        # 위젯을 갈아끼운 뒤 지오메트리를 즉시 재계산시킨다. 안 하면 다음 리페인트까지
        # 옛 크기가 남아 하단(명령 패널)이 잘려 보이고, 창을 흔들어야 제자리를 찾는다.
        self.console_holder_layout.invalidate()
        self.console_holder_layout.activate()
        self.console_holder.updateGeometry()
        central = self.centralWidget()
        if central is not None and central.layout() is not None:
            central.layout().invalidate()
            central.layout().activate()
        self.profile.layout["mode"] = self.layout_mode

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu(tr('파일'))
        file_menu.addAction(_action(self, tr('프로파일 저장'), self.save_profile, "Ctrl+S"))
        file_menu.addAction(_action(self, tr('로그 폴더 열기'), self.open_log_dir))
        file_menu.addSeparator()
        file_menu.addAction(_action(self, tr('로그 기록 시작 / 중지'), self.toggle_logging, "Ctrl+R"))
        file_menu.addAction(_action(self, tr('기록 멈춤 / 재개'), self.toggle_recording_pause, "Ctrl+P"))
        self.log_menu = file_menu.addMenu(tr('로그 파일 열기'))
        self.log_menu.aboutToShow.connect(self._rebuild_log_menu)
        file_menu.addAction(_action(self, tr('로그 파일 열기(뷰어)…'), self.open_log_viewer))
        file_menu.addAction(_action(self, tr('지금까지의 로그를 복사본으로 저장'),
                                    self.save_log_snapshot))
        file_menu.addSeparator()
        file_menu.addAction(_action(self, tr('마커 삽입'), self.insert_marker, "Ctrl+M"))
        file_menu.addAction(_action(self, tr('새 로그 파일로 분절 (연결 유지)'), self.split_log_session,
                                    "Ctrl+N"))
        file_menu.addSeparator()
        file_menu.addAction(_action(self, tr('종료'), self.close, "Ctrl+Q"))

        view_menu = bar.addMenu(tr('보기'))
        for mode, label in layout_labels().items():
            view_menu.addAction(_action(self, label, lambda m=mode: self._apply_layout(m)))
        view_menu.addSeparator()
        view_menu.addAction(_action(self, tr('타임스탬프 모드 순환'), self.cycle_ts, "Ctrl+T"))
        view_menu.addAction(_action(self, tr('자동 스크롤 정지 토글'), self.toggle_scroll_lock, "Ctrl+Space"))
        view_menu.addAction(_action(self, tr('화면 지우기 (ring·파일 유지)'), self.clear_pane, "Ctrl+L"))
        view_menu.addAction(_action(self, tr('전 콘솔 + 버퍼 비우기 (파일 유지)'),
                                    self.clear_all_buffers, "Ctrl+Shift+L"))
        view_menu.addSeparator()
        view_menu.addAction(_action(self, tr('포커스 콘솔 창 분리'), self.pop_out_current, "Ctrl+D"))
        view_menu.addAction(_action(self, tr('분리한 창 모두 복귀'), self.dock_all_panes))
        view_menu.addSeparator()
        view_menu.addAction(_action(self, tr('글자 크게'), lambda: self.change_font(+1), "Ctrl+="))
        view_menu.addAction(_action(self, tr('글자 작게'), lambda: self.change_font(-1), "Ctrl+-"))
        view_menu.addAction(_action(self, tr('글자 크기 초기화'), lambda: self.change_font(0), "Ctrl+0"))
        self.wrap_action = _action(self, tr('줄바꿈'), self.toggle_word_wrap)
        self.wrap_action.setCheckable(True)
        self.wrap_action.setChecked(self.profile.word_wrap)
        view_menu.addAction(self.wrap_action)
        self.ansi_action = _action(self, tr('펌웨어 로그 색 표시'), self.toggle_ansi_color)
        self.ansi_action.setCheckable(True)
        self.ansi_action.setChecked(self.profile.ansi_color)
        self.ansi_action.setToolTip(tr('장치가 보낸 ANSI 색을 화면에 살립니다 (로그 파일은 항상 색 코드 '
                                       '없음)'))
        view_menu.addAction(self.ansi_action)
        view_menu.addSeparator()
        view_menu.addAction(_action(self, tr('터미널 열기'), self.open_terminal))
        view_menu.addAction(_action(self, tr('관리자 PowerShell 열기 (외부 창)'),
                                    self.open_admin_shell))

        self.filter_menu = bar.addMenu(tr('필터'))
        self._rebuild_filter_menu()

        help_menu = bar.addMenu(tr('도움말'))
        help_menu.addAction(_action(self, tr('사용 설명서'), self.open_help, "F1"))
        help_menu.addAction(_action(self, tr('진단 폴더 열기 (app.log·crash.log·설정)'), self.open_data_dir))
        help_menu.addSeparator()
        help_menu.addAction(_action(self, tr('정보'), self.show_about))

        # Ctrl+K 는 필터 메뉴의 QAction 이 들고 있다 — QShortcut 을 또 걸면
        # Qt 가 ambiguous 로 판단해 양쪽 다 발화하지 않는다
        QShortcut(QKeySequence("Ctrl+`"), self, activated=self.command_panel.focus_input)
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=self.command_panel.cycle_target)
        for index, role in enumerate(self.profile.roles()[:9], start=1):
            QShortcut(QKeySequence(f"Ctrl+{index}"), self,
                      activated=lambda r=role: self.focus_pane(r))

    def _rebuild_filter_menu(self) -> None:
        # 룰이 바뀔 때마다 다시 만든다 — QAction 을 메뉴에 parent 시켜야 clear() 가 같이 지운다
        self.filter_menu.clear()
        self.filter_menu.addAction(_action(self.filter_menu, tr('새 필터드뷰'),
                                           lambda: self.open_filter_view(None), "Ctrl+K"))
        if self.profile.saved_filters:
            self.filter_menu.addSeparator()
            for rule in self.profile.saved_filters:
                self.filter_menu.addAction(
                    _action(self.filter_menu, rule.label(), lambda r=rule: self.open_filter_view(r)))

    def _build_status_bar(self) -> None:
        self.status_left = QLabel("")
        self.status_right = QLabel("")
        self.status_right.setObjectName("hint")
        bar = self.statusBar()
        bar.addWidget(self.status_left, 1)
        bar.addPermanentWidget(self.status_right)

    def set_status(self, text: str, color: str = theme.TEXT_SUB) -> None:
        self.status_left.setText(text)
        self.status_left.setStyleSheet(f"QLabel {{ color: {color}; background: transparent; }}")

    # ------------------------------------------------------------------ 주기 갱신

    def _shown_com(self, role: str) -> str:
        """연결 중이면 reader 가 실제로 물고 있는 COM 을 보여준다.

        설정 > 연결에서 콤보만 바꾼 상태에서 프로파일 값을 그대로 띄우면
        "COM8 Connected" 인데 실제로는 COM5 를 읽고 있는 거짓말이 된다.
        """
        reader = self.session.readers.get(role)
        if reader is not None and reader.is_running:
            return reader.com
        entry = self.profile.port(role)
        return entry.com if entry and entry.com else tr('미지정')

    def tick(self) -> None:
        active = self.profile.active_roles()
        for role, pane in self.panes.items():
            if role not in active:
                continue
            state = self.session.state_of(role)
            entry = self.profile.port(role)
            shown = entry.display() if entry else role
            pane.title = shown
            com = self._shown_com(role)
            # 이름을 따로 안 붙였으면 제목이 곧 COM 이다 — "VCOM1 (VCOM1)" 은 소음이다
            pane.set_state(state, "" if com == shown else f"({com})")
            pane.pump()
        if self.layout_mode == LAYOUT_MERGED or self.merged_pane in (
                w.pane for w in self.popped.values()):
            self.merged_pane.pump()  # 안 보일 때는 안 돌린다 — 전환 시 reload 로 채운다
        for view in list(self.filter_views):
            view.pump()
        for dock in list(self.terminal_docks):
            dock.pump()

        for role, pill in self.pills.items():
            if role not in active:
                continue
            entry = self.profile.port(role)
            shown = entry.display() if entry else role
            com = self._shown_com(role)
            pill.set_state(self.session.state_of(role),
                           shown if com == shown else f"{shown} {com}")

        if self.settings_dialog is not None:
            # 창을 닫아도 계속 돌린다 — probe 가 진행 중일 수 있고, 결과를 회수해야 한다
            self.settings_dialog.connection_page.tick()
        self.command_panel.poll_misroute(self.profile.probe_patterns)

        hits = self.trigger_watcher.scan(self.session.store)
        if hits:
            pattern, line = hits[-1]
            self.set_status(tr('⚡ 트리거 `{0}` — [{1}] {2}')
                .format(pattern, line.port, line.text[:80]), theme.WARNING)
            diag.warn("trigger", f"`{pattern}` [{line.port}] {line.text[:120]}")
        self._update_trigger_chip()

        counters = self.session.store.counters()
        labels = self._port_labels()
        self.status_right.setText("   ".join(
            f"{labels.get(role, role)} {counters.get(role, 0):,}" for role in active))

        self._update_rec_button()

    def _update_rec_button(self) -> None:
        store = self.session.store
        error = store.write_error()
        state = "error" if error else ("paused" if store.paused else
                                       ("rec" if store.recording else "idle"))
        if error:
            text = tr('⚠ 기록 실패 — {0}').format(error[:40])
        elif store.recording:
            total = sum(store.file_sizes().values())
            size = f"{total / 1024 / 1024:.1f}MB" if total >= 1024 * 1024 else f"{total // 1024}KB"
            mark = tr('⏸ 기록멈춤') if store.paused else "⏺ REC"
            text = f"{mark}  {size}  {store.log_dir}"
        else:
            text = tr('기록 안 함')
        if (text, state) == getattr(self, "_rec_shown", None):
            return  # 매 tick setStyleSheet 하면 repolish 비용이 그대로 든다
        self._rec_shown = (text, state)
        self.rec_button.setText(text)
        colors = {"error": theme.DANGER, "paused": theme.WARNING}
        background = colors.get(state)
        self.rec_button.setStyleSheet(
            f"QPushButton {{ color: #FFFFFF; background: {background}; border: none; }}"
            if background else "")
        self.pause_button.setText(tr('▶ 기록재개') if store.paused else tr('⏸ 기록멈춤'))
        self.pause_button.setEnabled(store.recording)
        self.log_button.setText(tr('⏹ 로그 중지') if store.recording else tr('⏺ 로그 시작'))
        self.log_button.setObjectName("" if store.recording else "primary")
        self.log_button.style().unpolish(self.log_button)
        self.log_button.style().polish(self.log_button)

    # ------------------------------------------------------------------ 연결

    def connect_all(self) -> None:
        # ★기록은 자동으로 시작하지 않는다 — [⏺ 로그 시작] 을 눌러야 파일이 생긴다.
        results = self.session.connect_all()
        if not results:
            self.set_status(
                    tr('연결할 포트가 없습니다 — [설정 > 연결] 에서 COM 을 지정하세요'), theme.WARNING)
            return
        failed = [(role, err) for role, ok, err in results if not ok]
        for role, err in failed:
            self._report_open_failure(role, err)
        if failed:
            self.set_status(tr('일부 포트 열기 실패: ') +
                            ", ".join(f"{role}({err[:40]})" for role, err in failed), theme.DANGER)
        else:
            tail = (tr('기록 중: {0}').format(self.session.store.log_dir) if self.session.store.recording
                    else tr('기록은 [⏺ 로그 시작] 을 눌러야 시작됩니다'))
            self.set_status(tr('{0}개 포트 연결됨 — {1}').format(len(results), tail), theme.SUCCESS)

    def disconnect_all(self) -> None:
        self.session.disconnect_all()
        self.set_status(tr('전체 해제됨 (기록 파일은 그대로 유지)'), theme.TEXT_SUB)

    def toggle_port(self, role: str) -> None:
        if self.session.state_of(role) == STATE_DISCONNECTED:
            ok, err = self.session.connect(role)
            if ok:
                self.set_status(tr('{0} 연결됨').format(role), theme.SUCCESS)
            else:
                self._report_open_failure(role, err)
                self.set_status(tr('{0} 열기 실패: {1}').format(role, err[:80]), theme.DANGER)
        else:
            self.session.disconnect(role)
            self.set_status(tr('{0} 해제됨').format(role), theme.TEXT_SUB)

    # ------------------------------------------------------------------ 룰 / 필터

    def apply_rules(self) -> None:
        self.trigger_watcher.set_rules(self.profile.trigger_rules)
        invalid = self.session.apply_redact_rules()
        if invalid:
            # 마스킹 룰이 조용히 빠지면 비밀값이 평문으로 기록된다 — 반드시 눈에 보이게
            self.set_status(tr('⚠ redact 룰 {0}개가 정규식 오류로 무력화됨 ({1}…) — [설정 > 규칙] 에서 고쳐 '
                               '주세요').format(len(invalid), invalid[0][:40]), theme.DANGER)
        rules = self.profile.highlight_rules
        # rehighlight() 는 pane 당 0.5~1.2s 다. redact/필터 표만 건드렸을 때는 돌리지 않는다
        signature = [r.to_dict() for r in rules]
        if signature != getattr(self, "_highlight_signature", None):
            self._highlight_signature = signature
            for pane in [*self.panes.values(), self.merged_pane]:
                pane.set_highlight_rules(rules)
            for view in self.filter_views:
                view.set_highlight_rules(rules)
        self._rebuild_filter_menu()

    def open_filter_view(self, rule: FilterRule | None = None) -> None:
        pane = self._current_pane()
        # 안 쓰는 포트는 필터드뷰에도 나오면 안 된다 (콘솔 수 설정과 어긋난다)
        active = self.profile.active_roles()
        base = FilterRule(ports=list(active))
        if isinstance(rule, FilterRule):
            base = FilterRule.from_dict(rule.to_dict())
            base.ports = [r for r in base.ports if r in active] or list(active)
        view = FilterView(self.session.store, active, base,
                          ts_mode=pane.ts_mode if pane else self.profile.ts_mode,
                          hide_empty=pane.hide_empty if pane else self.profile.hide_empty,
                          highlight_rules=self.profile.highlight_rules,
                          labels=self._port_labels())
        view.pane.set_font_size(self.profile.console_font_size)
        view.pane.set_word_wrap(self.profile.word_wrap)
        view.pane.set_ansi_color(self.profile.ansi_color)
        view.closed.connect(self._on_filter_closed)
        self.filter_views.append(view)
        view.show()
        view.edit.setFocus()

    def _on_filter_closed(self, view: FilterView) -> None:
        if view in self.filter_views:
            self.filter_views.remove(view)

    # ------------------------------------------------------------------ 포커스 동작

    def _current_pane(self) -> ConsolePane | None:
        widget = self.focusWidget()
        while widget is not None:
            if isinstance(widget, ConsolePane):
                return widget
            widget = widget.parentWidget()
        if self.layout_mode == LAYOUT_MERGED:
            return self.merged_pane
        panes = list(self.panes.values())
        return panes[0] if panes else None

    def focus_pane(self, role: str) -> None:
        pane = self.panes.get(role)
        if pane is None:
            return
        if self.layout_mode == LAYOUT_TABS and isinstance(self._console_container, QTabWidget):
            self._console_container.setCurrentWidget(pane)
        elif self.layout_mode == LAYOUT_MERGED:
            self._apply_layout(LAYOUT_SPLIT)
        pane.view.setFocus()

    def cycle_ts(self) -> None:
        pane = self._current_pane()
        if pane is not None:
            pane.cycle_ts_mode()
            self.profile.ts_mode = pane.ts_mode

    def toggle_scroll_lock(self) -> None:
        pane = self._current_pane()
        if pane is not None:
            pane.lock_button.setChecked(not pane.lock_button.isChecked())

    def clear_pane(self) -> None:
        pane = self._current_pane()
        if pane is not None:
            pane.clear_view()

    def clear_all_buffers(self) -> None:
        """전 콘솔 화면 + 메모리 ring 을 비운다. 파일은 그대로 — 이미 남긴 증적은 지우지 않는다."""
        dropped = self.session.store.clear_buffer()
        for pane in self._all_panes():
            pane.clear_view()
        self.trigger_watcher.reset()
        self._update_trigger_chip(force=True)
        self.set_status(
            tr('버퍼를 비웠습니다 ({0:,}줄) — 로그 파일은 그대로 있습니다').format(dropped),
            theme.TEXT_SUB)

    # ------------------------------------------------------------------ 창 분리

    def _pane_title(self, pane: ConsolePane) -> str:
        for role, candidate in self.panes.items():
            if candidate is pane:
                return role
        return tr('병합 뷰')

    def pop_out_pane(self, pane: ConsolePane) -> None:
        """콘솔을 별도 창으로 분리한다 (멀티 모니터). 이미 분리돼 있으면 되돌린다."""
        title = self._pane_title(pane)
        if title in self.popped:
            self.dock_pane(self.popped[title])
            return
        pane.setParent(None)
        window = PaneWindow(pane, title, None)
        window.closed.connect(self.dock_pane)
        self.popped[title] = window
        self._apply_layout(self.layout_mode)   # 남은 pane 으로 본창 재배치
        window.show()
        window.raise_()
        diag.info("app", f"콘솔 분리: {title}")

    def dock_pane(self, window: PaneWindow) -> None:
        title = next((k for k, v in self.popped.items() if v is window), "")
        if not title:
            return
        self.popped.pop(title, None)
        if window.pane is not None:
            window.release()
        self._apply_layout(self.layout_mode)
        window.deleteLater()
        diag.info("app", f"콘솔 복귀: {title}")

    def pop_out_current(self) -> None:
        pane = self._current_pane()
        if pane is not None:
            self.pop_out_pane(pane)

    def dock_all_panes(self) -> None:
        for window in list(self.popped.values()):
            window.close()

    def _all_panes(self) -> list[ConsolePane]:
        panes = [*self.panes.values(), self.merged_pane]
        panes += [view.pane for view in self.filter_views]
        return panes

    def change_font(self, delta: int) -> None:
        """콘솔 글자 크기 — 전 콘솔·필터드뷰 공통. 0 = 기본값 복원."""
        size = 12 if delta == 0 else self.profile.console_font_size + delta
        self.profile.console_font_size = max(7, min(28, size))
        for pane in self._all_panes():
            pane.set_font_size(self.profile.console_font_size)

    def toggle_word_wrap(self) -> None:
        self.profile.word_wrap = self.wrap_action.isChecked()
        for pane in self._all_panes():
            pane.set_word_wrap(self.profile.word_wrap)

    def toggle_ansi_color(self) -> None:
        self.profile.ansi_color = self.ansi_action.isChecked()
        for pane in self._all_panes():
            pane.set_ansi_color(self.profile.ansi_color)

    def insert_marker(self, text: str = "") -> None:
        """`### …` 구분 마커 — 병합 뷰·병합 파일에서 재현 시점을 표시한다 (GAP-1)."""
        if not text:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(self, tr('마커 삽입'), tr('마커 내용 (### 자동 부착)'))
            if not ok or not text.strip():
                return
        line = self.session.store.marker(text.strip())
        self.set_status(
                tr('마커 기록: {0}').format(render_line(line, 'off', show_prefix=True)), theme.SUCCESS)
        diag.info("app", f"marker: {line.text}")

    def split_log_session(self) -> None:
        """연결을 유지한 채 지금부터를 새 로그 파일로 받는다 (GAP-4, 티켓용 작은 파일)."""
        if not self.session.store.recording:
            self.set_status(tr('기록 중이 아닙니다 — [⏺ 로그 시작] 을 먼저 누르세요'), theme.WARNING)
            return
        name = self.session.store.split_session()
        self.set_status(tr('새 로그 파일로 분절됨: {0}_*.log').format(name), theme.SUCCESS)

    def reset_triggers(self) -> None:
        self.trigger_watcher.reset()
        self.trigger_watcher.set_rules(self.profile.trigger_rules)
        self._update_trigger_chip(force=True)

    def _update_trigger_chip(self, force: bool = False) -> None:
        total = self.trigger_watcher.total()
        if not force and total == getattr(self, "_trigger_shown", None):
            return
        self._trigger_shown = total
        self.trigger_chip.setText(f"⚡ {total}")
        if total:
            def _hit_line(pattern: str, count: int) -> str:
                when = time.strftime('%H:%M:%S',
                                     time.localtime(self.trigger_watcher.last_hit[pattern].t_wall))
                return tr('{0}: {1}회, 최근 {2}').format(pattern, count, when)

            tooltip = "\n".join(
                _hit_line(pattern, count)
                for pattern, count in self.trigger_watcher.counts.items() if count)
            self.trigger_chip.setToolTip(tooltip)
            self.trigger_chip.setStyleSheet(
                f"QPushButton {{ color: #FFFFFF; background: {theme.WARNING}; border: none; }}")
        else:
            self.trigger_chip.setToolTip(tr('트리거 발생 집계 (설정 > 규칙에서 편집) — 클릭 = 카운터 초기화'))
            self.trigger_chip.setStyleSheet("")

    def retarget_logs(self) -> None:
        """로그 폴더·파일명·접두어를 바꾸면 기록 중이라도 지금부터 새 파일에 쓴다.

        멈춘 상태에서 바꾸고 재개했더니 옛 위치에 계속 쌓이던 문제를 없앤다.
        """
        old_dir, new_dir = self.session.retarget_logs()
        if not new_dir:
            return   # 기록 중이 아니면 설정만 반영 — 다음 연결부터 적용된다
        if os.path.normpath(old_dir or "") == os.path.normpath(new_dir):
            self.set_status(tr('로그 파일명 변경됨 — 지금부터 {0}').format(new_dir), theme.SUCCESS)
        else:
            self.set_status(tr('로그 위치 변경 — 지금부터 {0} 에 기록합니다 (이전 파일은 {1} 에 그대로)')
                .format(new_dir, old_dir), theme.SUCCESS)
        self._update_rec_button()

    def toggle_logging(self) -> None:
        """[⏺ 로그 시작] / [⏹ 로그 중지].

        시작할 때마다 파일명 확인 창을 띄운다 — 앱을 다시 켰거나 설정을 안 만졌어도
        이번 기록이 어디에 어떤 이름으로 남는지 매번 눈으로 보게 하려는 것이다.
        """
        if self.session.store.recording:
            self.stop_logging()
        else:
            self.start_logging()

    def start_logging(self, ask: bool = True) -> bool:
        if self.session.store.recording:
            return True
        overwrite = False
        # 세션 이름은 여기서 한 번만 만든다 — 검사한 경로와 실제 기록 경로가 같아야 한다
        name = self.session.new_session_name()
        if ask:
            dialog = LogStartDialog(self.profile, self)
            if dialog.exec() != QDialog.Accepted:
                self.set_status(tr('기록을 시작하지 않았습니다'), theme.TEXT_SUB)
                return False
            name = self.session.new_session_name()   # 확인 창에서 접두어를 바꿨을 수 있다
            existing = [path for path in self.session.plan_recording(name).values()
                        if os.path.exists(path)]
            if existing:
                choice = self._ask_overwrite(existing)
                if choice == "cancel":
                    self.set_status(tr('기록을 시작하지 않았습니다'), theme.TEXT_SUB)
                    return False
                overwrite = choice == "overwrite"
        # ask=False(자동화·브리지)는 묻지 않고 기존 동작대로 이어쓴다
        name = self.session.start_recording(name, overwrite=overwrite)
        diag.info("app", f"기록 시작 (사용자) `{name}` dir={self.session.store.log_dir}"
                         f"{' overwrite' if overwrite else ''}")
        self.set_status(tr('기록 시작 — {0} ({1})').format(self.session.store.log_dir, name), theme.SUCCESS)
        self._update_rec_button()
        return True

    def _ask_overwrite(self, existing: list[str]) -> str:
        """같은 이름의 로그 파일이 이미 있을 때 — 덮어쓰기 / 이어쓰기 / 취소.

        반환값 = "overwrite" | "append" | "cancel". 기본 버튼은 안전한 이어쓰기다.
        """
        names = "\n".join(os.path.basename(path) for path in existing[:6])
        if len(existing) > 6:
            names += "\n…"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(tr('같은 이름의 로그 파일이 있습니다'))
        box.setText(tr('아래 파일이 이미 있습니다.\n\n{0}\n\n덮어쓰면 기존 내용이 지워집니다. '
                       '이어쓰면 기존 파일 끝에 계속 기록합니다.').format(names))
        overwrite_button = box.addButton(tr('덮어쓰기'), QMessageBox.DestructiveRole)
        append_button = box.addButton(tr('이어쓰기'), QMessageBox.AcceptRole)
        box.addButton(tr('취소'), QMessageBox.RejectRole)
        box.setDefaultButton(append_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is overwrite_button:
            return "overwrite"
        if clicked is append_button:
            return "append"
        return "cancel"

    def stop_logging(self) -> None:
        if not self.session.store.recording:
            return
        count = len(self.session.store.file_paths())
        self.session.stop_recording()
        diag.info("app", f"기록 중지 (사용자) files={count}")
        self.set_status(tr('기록 중지 — 파일 {0}개는 그대로 남아 있습니다').format(count), theme.TEXT_SUB)
        self._update_rec_button()

    def toggle_recording_pause(self) -> None:
        """파일 기록만 멈춘다 — 수신·화면은 계속 돈다 (증상 재현 구간만 남기고 싶을 때)."""
        store = self.session.store
        if not store.recording:
            self.set_status(tr('기록 중이 아닙니다 — [⏺ 로그 시작] 을 먼저 누르세요'), theme.WARNING)
            return
        dropped = store.set_paused(not store.paused)
        if store.paused:
            self.set_status(tr('기록 멈춤 — 화면·수신은 계속됩니다 (이 구간은 파일에 안 남습니다)'),
                            theme.WARNING)
        else:
            self.set_status(
                    tr('기록 재개 — 멈춘 동안 {0:,}줄은 파일에 없습니다').format(dropped), theme.SUCCESS)
        self._update_rec_button()

    def _rebuild_log_menu(self) -> None:
        """지금 기록 중인 파일 목록 — 여는 순간 flush 해서 마지막 줄까지 반영한다."""
        self.log_menu.clear()
        store = self.session.store
        if not store.recording:
            self.log_menu.addAction(_action(self.log_menu, tr('(기록 중이 아닙니다)'), lambda: None))
            return
        store.flush()
        sizes = store.file_sizes()
        for key, path in sorted(store.file_paths().items()):
            size = sizes.get(key, 0)
            label = f"{os.path.basename(path)}   ({size / 1024:,.0f} KB)"
            self.log_menu.addAction(_action(self.log_menu, label,
                                            lambda p=path: self._open_path(p)))

    def open_log_viewer(self, paths: list[str] | None = None) -> LogViewerDock | None:
        """과거 로그 파일을 뷰어 도크로 연다 — 메인 창에 붙이거나 떼어내 별도 창으로 쓴다.

        대용량 확인은 뷰어의 add_files 가 한 번만 묻는다 (여기서 또 물으면 두 번 뜬다).
        """
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, tr('로그 파일 선택'), self.profile.log_base_dir,
                "Log (*.log *.txt);;All (*)")
        if not paths:
            return None
        dock = LogViewerDock(self.profile, paths, self)
        self._add_bottom_dock(dock)
        dock.closed.connect(self._on_viewer_closed)
        self.viewer_docks.append(dock)
        diag.info("app", f"로그 뷰어 열림 files={len(paths)}")
        self.set_status(tr('로그 뷰어 열림 — 파일 {0}개').format(len(paths)), theme.TEXT_SUB)
        return dock

    def _bottom_docks(self) -> list:
        """지금 하단에 붙어 있는(떠 있지 않은) 도크들 — 새 도크를 여기에 탭으로 묶는다."""
        return [dock for dock in [*self.viewer_docks, *self.terminal_docks]
                if dock.isVisible() and not dock.isFloating()]

    def _add_bottom_dock(self, dock) -> None:
        """도크는 항상 하단에 붙이고, 이미 있으면 **탭으로 묶는다**.

        그냥 addDockWidget 을 반복하면 도크가 옆으로 나란히 늘어서 저마다 좁아진다
        (실기 보고). 탭으로 묶으면 폭을 온전히 쓰고 제목 탭으로 오간다.
        """
        existing = self._bottom_docks()
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        if existing:
            self.tabifyDockWidget(existing[-1], dock)
        dock.setFloating(False)   # 열 때마다 떠 있던 문제 — 항상 도킹 상태로 시작
        dock.show()
        dock.raise_()

    def _drop_dock(self, dock) -> None:
        """닫힌 도크를 창에서 완전히 떼어낸다 — 안 하면 빈 도크 영역이 자리를 물고 있다."""
        try:
            self.removeDockWidget(dock)
        except RuntimeError:
            pass   # 이미 파괴됨 (WA_DeleteOnClose)

    def _on_viewer_closed(self, dock) -> None:
        if dock in self.viewer_docks:
            self.viewer_docks.remove(dock)
        self._drop_dock(dock)

    def open_terminal(self) -> TerminalDock | None:
        """내장 터미널 도크 — 메인 창에 붙이거나 떼어내 별도 창으로 쓴다."""
        dock = TerminalDock(self)
        self._add_bottom_dock(dock)
        dock.closed.connect(self._on_terminal_closed)
        self.terminal_docks.append(dock)
        if dock.pane is not None:
            dock.pane.setFocus()
            self.set_status(tr('터미널 열림 — PowerShell'), theme.TEXT_SUB)
        else:
            self.set_status(tr('내장 터미널을 쓸 수 없습니다 — pywinpty/pyte 설치가 필요합니다'),
                            theme.WARNING)
        diag.info("app", f"터미널 열림 available={dock.pane is not None}")
        return dock

    def _on_terminal_closed(self, dock) -> None:
        if dock in self.terminal_docks:
            self.terminal_docks.remove(dock)
        self._drop_dock(dock)

    def open_admin_shell(self) -> None:
        """관리자(UAC 승격) PowerShell — 임베드가 불가능해 외부 창으로 띄운다."""
        if not launch_admin_shell():
            self.set_status(tr('관리자 PowerShell 실행이 취소되었습니다'), theme.WARNING)

    def _open_path(self, path: str) -> None:
        try:
            os.startfile(path)  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            self.set_status(tr('열기 실패: {0}').format(exc), theme.DANGER)

    def save_log_snapshot(self) -> None:
        """기록을 이어가면서 '지금까지' 를 복사본으로 뜬다 — 티켓 첨부용.

        원본은 앱이 계속 쓰고 있어 편집기가 잠글 수 있으니, 복사본을 주는 편이 안전하다.
        """
        store = self.session.store
        if not store.recording:
            self.set_status(tr('기록 중이 아닙니다 — [⏺ 로그 시작] 을 먼저 누르세요'), theme.WARNING)
            return
        store.flush()
        target = QFileDialog.getExistingDirectory(self, tr('복사본을 저장할 폴더'),
                                                  self.profile.log_base_dir)
        if not target:
            return
        stamp = time.strftime("%m%d_%H%M%S")
        copied = 0
        for path in store.file_paths().values():
            if not os.path.exists(path):
                continue
            base, ext = os.path.splitext(os.path.basename(path))
            try:
                shutil.copyfile(path, os.path.join(target, f"{base}_snap{stamp}{ext}"))
                copied += 1
            except Exception as exc:  # noqa: BLE001
                diag.exception("app", f"스냅샷 복사 실패: {path}")
                self.set_status(tr('복사 실패: {0}').format(exc), theme.DANGER)
                return
        self.set_status(
                tr('복사본 {0}개 저장: {1} (기록은 계속됩니다)').format(copied, target), theme.SUCCESS)

    def open_data_dir(self) -> None:
        """문제 보고 받을 때 "도움말 → 진단 폴더 열기" 한 번으로 app.log 를 얻기 위한 통로."""
        try:
            from ..core import config as cfg
            os.startfile(cfg.DATA_DIR)  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            self.set_status(tr('진단 폴더 열기 실패: {0}').format(exc), theme.DANGER)

    # ------------------------------------------------------------------ 프로파일

    def _sync_profile_from_ui(self) -> None:
        self.profile.scratchpad = self.command_panel.pad_edit.toPlainText()
        self.profile.command_history = self.command_panel.history
        self._capture_layout()
        pane = self.panes.get(self.profile.roles()[0]) if self.profile.roles() else None
        if pane is not None:
            self.profile.ts_mode = pane.ts_mode
            self.profile.hide_empty = pane.hide_empty

    def save_profile(self) -> None:
        self.save_profile_as(self.profile.name)

    def save_profile_as(self, name: str) -> None:
        if not name:
            return
        self._sync_profile_from_ui()
        self.profile.name = name
        ok, detail = self.profile.save()
        if ok:
            config_mod.remember_profile(name)
            self.setWindowTitle(f"Serial Hub — {name}")
            self._refresh_settings_pages()
            self.set_status(tr('프로파일 저장: {0}').format(detail), theme.SUCCESS)
        else:
            self.set_status(tr('프로파일 저장 실패: {0}').format(detail), theme.DANGER)

    def load_profile(self, name: str) -> None:
        if name == self.profile.name:
            return
        if self.session.any_connected():
            answer = QMessageBox.question(
                self, tr('프로파일 전환'),
                tr('연결된 포트가 있습니다. 전부 해제하고 프로파일을 바꾸시겠습니까?'))
            if answer != QMessageBox.Yes:
                self._refresh_settings_pages()
                return
        # 되돌릴 수 없는 shutdown 전에 먼저 검사한다 — 취소했는데 포트만 끊겨 있으면 안 된다
        profile, warning = Profile.load(name)
        if profile.roles() != self.profile.roles():
            QMessageBox.information(
                self, tr('프로파일 전환'),
                tr('역할 구성이 다른 프로파일입니다. 적용하려면 앱을 다시 실행하세요.\n현재 연결은 그대로 '
                   '유지했습니다.'))
            self._refresh_settings_pages()
            return
        self.session.shutdown()
        for view in list(self.filter_views):
            view.close()  # 옛 store 를 붙들고 있으면 안 된다
        self.profile = profile
        self.session = SerialHubSession(profile)
        self._refresh_settings_pages()
        for pane in list(self.panes.values()) + [self.merged_pane]:
            pane.store = self.session.store
            pane.clear_view()
        self.command_panel.store = self.session.store
        self.command_panel.send_fn = self.session.send
        self.command_panel.history = profile.command_history
        self.command_panel.set_redactor(self.session.redactor)
        self.command_panel.pad_edit.setPlainText(profile.scratchpad)
        # 브리지: 세션 재바인딩 + 새 프로파일의 포트 설정으로 재기동
        # (bridge_port=0 프로파일로 바꿨는데 옛 통로가 계속 열려 있으면 안 된다)
        self.bridge.stop()
        self.bridge = BridgeServer(self.session, self.profile.bridge_port or 0)
        if self.profile.bridge_port:
            self.bridge.start()
        self.trigger_watcher.reset(rewind=True)  # store 가 바뀌었다 — 커서도 되돌린다
        self.apply_rules()
        self.wrap_action.setChecked(self.profile.word_wrap)
        for pane in self._all_panes():
            pane.set_font_size(self.profile.console_font_size)
            pane.set_word_wrap(self.profile.word_wrap)
            pane.set_ansi_color(self.profile.ansi_color)
        self._sync_active_ports()   # 새 프로파일의 콘솔 수를 화면에 반영
        config_mod.remember_profile(name)
        self.setWindowTitle(f"Serial Hub — {name}")
        diag.info("app", f"프로파일 전환 -> `{name}`" + (f" (경고: {warning})" if warning else ""))
        self.set_status(warning or tr('프로파일 `{0}` 적용됨 — [설정 > 연결] 에서 연결하세요').format(name),
                        theme.WARNING if warning else theme.TEXT_SUB)

    # ------------------------------------------------------------------ 기타

    def open_log_dir(self) -> None:
        path = self.session.store.log_dir or self.profile.log_base_dir
        if not path or not os.path.isdir(path):
            self.set_status(tr('로그 폴더가 아직 없습니다: {0}').format(path), theme.WARNING)
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:  # noqa: BLE001
            self.set_status(tr('폴더 열기 실패: {0}').format(exc), theme.DANGER)

    def show_about(self) -> None:
        from .. import __version__
        box = QMessageBox(self)
        box.setWindowTitle(tr('Serial Hub 정보'))
        box.setIconPixmap(app_icon().pixmap(64, 64))
        box.setText(tr('<b>Serial Hub</b><br>포트 통합 시리얼 모니터<br><br>버전 {0}').format(__version__))
        box.setInformativeText(
            tr('Python {0} · PySide6 {1}\n데이터 폴더: {2}\n\nCopyright © psy-bari')
                .format(sys.version.split()[0], QtCore.__version__, config_mod.DATA_DIR))
        box.exec()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        diag.info("app", "종료 (closeEvent)")
        self.bridge.stop()
        self.timer.stop()
        for window in list(self.popped.values()):
            window.pane = None    # 복귀 처리 없이 창만 닫는다 (앱이 끝나는 중)
            window.close()
        self.popped.clear()
        self._sync_profile_from_ui()
        self.profile.save()
        config_mod.remember_profile(self.profile.name)
        for view in list(self.filter_views):
            view.close()
        for dock in list(self.terminal_docks):
            if dock.session is not None:
                dock.session.close()   # 앱이 끝나면 셸도 끝낸다 — 백그라운드 잔류 금지
        self.session.shutdown()
        super().closeEvent(event)


def usable_sizes(stored, count: int) -> list[int] | None:
    """저장된 분할 비율이 지금 splitter 에 그대로 쓸 수 있는 값인지 검사한다.

    프로파일은 손으로 고칠 수 있는 파일이고 레이아웃이 바뀌면 칸 수도 달라진다 —
    엉뚱한 값을 그대로 넣으면 패널 하나가 폭 0 으로 사라진다.
    """
    if not isinstance(stored, list) or len(stored) != count or count == 0:
        return None
    # bool 은 int 의 서브클래스다 — 손편집 프로파일의 [true, false] 가 [1, 0] 으로
    # 통과하면 이 함수가 막겠다던 "패널 폭 0" 이 그대로 난다
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in stored):
        return None
    if sum(stored) <= 0:
        return None
    return list(stored)


def _action(parent, text: str, slot, shortcut: str = "") -> QAction:
    action = QAction(text, parent)
    if shortcut:
        action.setShortcut(QKeySequence(shortcut))
    action.triggered.connect(lambda _checked=False: slot())
    return action
