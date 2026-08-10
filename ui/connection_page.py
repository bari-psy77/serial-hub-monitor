"""ConnectionPage — 포트 카드 + 세션/프로파일 카드. UI 문서 §6.

probe 는 무해 토큰 fingerprint 방식이라 오배정된 포트에서도 실명령이 실행되지 않는다
(설계 §5-7). PowerShell 점유 조회와 probe 는 백그라운드 스레드에서 돌리고 tick() 으로 회수한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget)

from ..core import portscan
from ..core.config import Profile
from ..core.port import STATE_CONNECTED, STATE_DISCONNECTED
from ..core.session import SerialHubSession
from . import theme
from ..core.i18n import tr


class PortCard(theme.Card):
    connect_toggled = Signal(str)
    probe_requested = Signal(str)
    log_naming_changed = Signal()
    label_changed = Signal()
    enabled_changed = Signal()

    def __init__(self, role: str, profile: Profile, parent: QWidget | None = None):
        super().__init__(f"{role} Connection", parent)
        self.role = role
        self.profile = profile
        self._probe_task = None
        self._holder_task = None
        self._last_state_key: tuple[str, str] | None = None
        self.live_com = ""  # reader 가 실제로 물고 있는 COM (프로파일 값과 다를 수 있다)
        self._error_shown = False   # 지난 실패 문구가 떠 있나 (다시 시도하면 지운다)
        self.last_verdict = ""      # 마지막 probe 판정 역할 — 전체 Probe 의 매핑 제안에 쓴다
        self.last_probed_com = ""   # 그 판정을 받은 실제 COM

        body = self.body()

        port_row = QHBoxLayout()
        port_row.addWidget(_field_label("PORT"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        port_row.addWidget(self.port_combo, 1)
        self.pill = theme.StatusPill()
        port_row.addWidget(self.pill)
        body.addLayout(port_row)

        baud_row = QHBoxLayout()
        baud_row.addWidget(_field_label("BAUD"))
        self.baud_combo = QComboBox()
        for baud in portscan.BAUD_CHOICES:
            self.baud_combo.addItem(str(baud), baud)
        baud_row.addWidget(self.baud_combo, 1)
        baud_row.addStretch(1)
        body.addLayout(baud_row)

        use_row = QHBoxLayout()
        self.use_box = QCheckBox(tr('이 포트 사용'))
        self.use_box.setToolTip(
            tr('끄면 이 콘솔은 화면·명령 대상·로그에서 빠집니다 (COM·이름 설정은 그대로 보관). UART 가 '
               '1~2개인 모델에서 빈 콘솔이 자리를 차지하지 않게 하는 스위치입니다.'))
        use_row.addWidget(self.use_box)
        use_row.addStretch(1)
        body.addLayout(use_row)

        name_row = QHBoxLayout()
        name_row.addWidget(_field_label(tr('이름')))
        self.label_button = QToolButton()
        self.label_button.setObjectName("fieldButton")
        self.label_button.setPopupMode(QToolButton.InstantPopup)
        self.label_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.label_button.setMinimumWidth(150)
        self.label_button.setToolTip(tr('화면에 표시할 이름 — 누르면 자주 쓰는 이름을 고르거나 직접 입력'))
        menu = QMenu(self.label_button)
        for preset in ("MLOG", "SHELL", "UCLI"):
            menu.addAction(preset, lambda p=preset: self._set_label(p))
        menu.addSeparator()
        menu.addAction(tr('포트 번호 사용 (기본)'), lambda: self._set_label(""))
        menu.addAction(tr('직접 입력…'), self._prompt_label)
        self.label_button.setMenu(menu)
        name_row.addWidget(self.label_button)
        name_row.addStretch(1)
        body.addLayout(name_row)

        self.log_name_edit = QLineEdit()   # 로그 파일명은 설정 > 로그 페이지에서 다룬다
        self.log_name_edit.hide()

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(34)
        body.addWidget(self.status)

        button_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.refresh_button = QPushButton("Refresh")
        self.probe_button = QPushButton("Probe")
        for button in (self.connect_button, self.refresh_button, self.probe_button):
            button_row.addWidget(button)
        body.addLayout(button_row)

        self.use_box.toggled.connect(self._on_use_toggled)
        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        self.probe_button.clicked.connect(lambda: self.probe_requested.emit(self.role))
        self.port_combo.currentTextChanged.connect(self._on_port_changed)
        self.baud_combo.currentIndexChanged.connect(self._on_baud_changed)
        self.log_name_edit.editingFinished.connect(self._on_log_name_changed)

        self.refresh_ports()
        self._load_from_profile()

    # ------------------------------------------------------------------ 프로파일 연동

    def _entry(self):
        return self.profile.port(self.role)

    def _load_from_profile(self) -> None:
        entry = self._entry()
        if entry is None:
            return
        self.port_combo.blockSignals(True)
        if entry.com:
            index = self.port_combo.findData(entry.com)
            if index < 0:
                self.port_combo.addItem(entry.com, entry.com)
                index = self.port_combo.count() - 1
            self.port_combo.setCurrentIndex(index)
        else:
            self.port_combo.setCurrentIndex(0)
        self.port_combo.blockSignals(False)

        self.baud_combo.blockSignals(True)
        index = self.baud_combo.findData(entry.baud)
        self.baud_combo.setCurrentIndex(index if index >= 0 else
                                        self.baud_combo.findData(portscan.DEFAULT_BAUD))
        self.baud_combo.blockSignals(False)

        self.log_name_edit.blockSignals(True)
        self.log_name_edit.setText(entry.log_name)
        self.log_name_edit.blockSignals(False)
        self.use_box.blockSignals(True)
        self.use_box.setChecked(entry.enabled)
        self.use_box.blockSignals(False)
        self._apply_enabled_style(entry.enabled)
        self._refresh_label()

    def reload_profile(self, profile: Profile) -> None:
        self.profile = profile
        self._load_from_profile()

    def _on_connect_clicked(self) -> None:
        self.clear_error()
        self.connect_toggled.emit(self.role)

    def _on_refresh_clicked(self) -> None:
        self.clear_error()
        self.refresh_ports()

    def clear_error(self) -> None:
        """다시 시도할 때 지난 실패 문구를 지운다.

        그대로 두면 지금 상태로 오해한다 — 연결에 성공했는데도 빨간 "열기 실패" 가
        남아 있는 식이다.
        """
        if not self._error_shown:
            return
        self._error_shown = False
        self._last_state_key = None
        self.set_status("")

    def refresh_ports(self) -> None:
        current = self.port_combo.currentData()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        self.port_combo.addItem(tr('(포트 선택)'), "")
        for info in portscan.list_ports():
            self.port_combo.addItem(info.label(), info.device)
        if current:
            index = self.port_combo.findData(current)
            if index < 0:
                self.port_combo.addItem(tr('{0}  —  (연결 안 됨)').format(current), current)
                index = self.port_combo.count() - 1
            self.port_combo.setCurrentIndex(index)
        self.port_combo.blockSignals(False)

    def _on_use_toggled(self, checked: bool) -> None:
        entry = self._entry()
        if entry is None:
            return
        entry.enabled = checked
        self._apply_enabled_style(checked)
        self.enabled_changed.emit()

    def _apply_enabled_style(self, enabled: bool) -> None:
        """안 쓰는 포트는 카드를 흐리게 — 설정은 남아 있다는 걸 보이게 한다."""
        for widget in (self.port_combo, self.baud_combo, self.label_button,
                       self.connect_button, self.refresh_button, self.probe_button):
            widget.setEnabled(enabled)
        self.setStyleSheet("" if enabled else
                           "QFrame#card { background: #F7F8FA; border-style: dashed; }")

    def _on_port_changed(self, _text: str) -> None:
        entry = self._entry()
        if entry is None:
            return
        entry.com = self.port_combo.currentData() or ""
        self._refresh_label()   # 이름을 안 정했으면 COM 번호가 곧 이름이다
        self.label_changed.emit()
        # 포트를 바꿨으면 옛 COM 에 대한 판정은 무효다 (제안에 섞이면 안 된다)
        if entry.com != self.last_probed_com:
            self.last_verdict = ""
        if self.live_com and entry.com != self.live_com:
            # 콤보를 바꿔도 이미 도는 reader 는 옛 COM 을 계속 읽는다 — 사실대로 알린다
            self._last_state_key = None
            self.set_status(tr('수신 중인 포트는 여전히 {0} 입니다 — Disconnect 후 다시 연결해야 적용됩니다')
                .format(self.live_com), theme.WARNING)

    def _on_baud_changed(self, _index: int) -> None:
        entry = self._entry()
        if entry is not None:
            entry.baud = self.baud_combo.currentData() or portscan.DEFAULT_BAUD

    def _on_log_name_changed(self) -> None:
        entry = self._entry()
        if entry is not None:
            entry.log_name = self.log_name_edit.text().strip()
            self.log_naming_changed.emit()

    def _set_label(self, label: str) -> None:
        entry = self._entry()
        if entry is None:
            return
        entry.label = label
        self._refresh_label()
        self.label_changed.emit()

    def _prompt_label(self) -> None:
        entry = self._entry()
        if entry is None:
            return
        text, ok = QInputDialog.getText(self, tr('이름 직접 입력'), tr('화면에 표시할 이름'),
                                        text=entry.label or entry.com)
        if ok:
            self._set_label(text.strip())

    def _refresh_label(self) -> None:
        entry = self._entry()
        if entry is None:
            return
        shown = entry.display()
        self.label_button.setText(f"{shown}  ▾")
        self.title_label.setText(tr('{0} 연결').format(shown))

    # ------------------------------------------------------------------ 상태 표시

    def set_state(self, state: str, error: str = "") -> None:
        self.pill.set_state(state)
        self.connect_button.setText("Disconnect" if state != STATE_DISCONNECTED else "Connect")
        busy = self._probe_task is not None or self._holder_task is not None
        entry = self._entry()
        in_use = entry.enabled if entry is not None else True
        self.probe_button.setEnabled(in_use and not busy)
        # 매 tick 다시 쓰면 probe 판정·점유 조회 결과를 50ms 만에 덮어버린다.
        # 오류 문구는 오류가 "바뀌었을 때"만 쓴다.
        key = (state, error)
        if key != self._last_state_key:
            self._last_state_key = key
            if error and state == STATE_DISCONNECTED:
                self.set_status(tr('열기 실패: {0}').format(error[:70]), theme.DANGER)
                self._error_shown = True
            elif state == STATE_CONNECTED:
                self.clear_error()   # 연결됐는데 옛 실패 문구가 남아 있으면 안 된다

    def set_status(self, text: str, color: str = theme.TEXT_SUB) -> None:
        if (text, color) == getattr(self, "_status_shown", None):
            return
        self._status_shown = (text, color)
        self.status.setText(text)
        self.status.setStyleSheet(f"QLabel {{ color: {color}; background: transparent; }}")

    # ------------------------------------------------------------------ 백그라운드 작업

    def start_probe(self, session: SerialHubSession) -> None:
        if self._probe_task is not None:
            return  # 연타하면 같은 COM 을 두 스레드가 열려다 "액세스 거부" 라는 거짓 결과가 난다
        entry = self._entry()
        if entry is None or not entry.com:
            self.set_status(tr('포트를 먼저 선택하세요'), theme.WARNING)
            return
        token = self.profile.probe_token
        patterns = self.profile.probe_patterns
        reader = session.readers.get(self.role)
        if reader is not None and reader.state == STATE_CONNECTED:
            self._probe_task = portscan.BackgroundTask(reader.probe, token, patterns)
        else:
            self._probe_task = portscan.BackgroundTask(
                portscan.probe_port, entry.com, entry.baud, token, patterns)
        self.set_status(tr('probe 중… (무해 토큰 `{0}` 1회 전송)').format(token), theme.TEXT_SUB)
        self.probe_button.setEnabled(False)

    @property
    def probing(self) -> bool:
        return self._probe_task is not None

    def start_holder_lookup(self) -> None:
        entry = self._entry()
        if entry is None or not entry.com or self._holder_task is not None:
            return
        self._holder_task = portscan.BackgroundTask(portscan.who_holds, entry.com)

    def tick(self) -> None:
        if self._probe_task is not None and self._probe_task.done:
            task, self._probe_task = self._probe_task, None
            self.probe_button.setEnabled(True)
            result = task.result
            # 판정과 "실제로 probe 한 COM" 을 짝으로 보관한다 — probe 중 콤보를 바꾸면
            # probe 한 적 없는 COM 이 제안에 섞인다
            if result is not None and result.ok:
                self.last_verdict, self.last_probed_com = result.verdict, result.com
            else:
                self.last_verdict, self.last_probed_com = "", ""
            if result is None:
                self.set_status(tr('probe 실패: {0}').format(task.error or '알 수 없음'), theme.DANGER)
            elif result.ok:
                matched = result.verdict == self.role
                color = theme.SUCCESS if matched else theme.WARNING
                suffix = "" if matched else tr(' — 이 카드는 {0} 인데 판정이 다릅니다').format(self.role)
                self.set_status(f"probe: {result.detail}{suffix}", color)
            else:
                self.set_status(f"probe: {result.detail}", theme.WARNING)

        if self._holder_task is not None and self._holder_task.done:
            task, self._holder_task = self._holder_task, None
            holders = task.result or []
            if holders:
                self.set_status(tr('점유 후보: ') + ", ".join(holders) +
                                tr(' — Tera Term / VS Code Serial Monitor 를 닫아 주세요 (추정)'),
                                theme.DANGER)
                self._error_shown = True
            else:
                # 후보가 없어도 조회했다는 사실은 남겨야 한다 (침묵은 오해를 만든다)
                self.set_status(tr('열기 실패 — 점유 프로세스를 찾지 못했습니다 (다른 계정/드라이버가 잡고 '
                                   '있을 수 있습니다)'), theme.DANGER)
                self._error_shown = True


class ConnectionPage(QWidget):
    ports_changed = Signal()          # 사용 포트 구성이 바뀌었다 (화면을 다시 짜야 한다)
    connect_all_requested = Signal()
    disconnect_all_requested = Signal()
    port_toggle_requested = Signal(str)
    probe_requested = Signal(str)
    probe_all_requested = Signal()
    profile_load_requested = Signal(str)
    profile_save_requested = Signal(str)
    log_naming_changed = Signal()
    label_changed = Signal()

    def __init__(self, session: SerialHubSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.profile = session.profile

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 16)
        outer.setSpacing(12)

        # ★모델마다 UART 개수가 다르다 (1개짜리도, 2개짜리도 있다). 늘 3개를 띄우면
        # 안 쓰는 콘솔이 화면만 차지하므로, 여기서 몇 개를 쓸지 먼저 고른다.
        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        count_row.addWidget(QLabel(tr('이 장비의 콘솔 수')))
        self.count_buttons: dict[int, QPushButton] = {}
        for count in range(1, len(self.profile.ports) + 1):
            button = QPushButton(tr('{0}개').format(count))
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.clicked.connect(lambda _checked, n=count: self._set_count(n))
            self.count_buttons[count] = button
            count_row.addWidget(button)
        self.count_hint = QLabel("")
        self.count_hint.setObjectName("hint")
        count_row.addWidget(self.count_hint, 1)
        outer.addLayout(count_row)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.cards: dict[str, PortCard] = {}
        for role in self.profile.roles():
            card = PortCard(role, self.profile)
            card.connect_toggled.connect(self.port_toggle_requested.emit)
            card.probe_requested.connect(self.probe_requested.emit)
            card.log_naming_changed.connect(self._on_log_naming_changed)
            card.label_changed.connect(self.label_changed.emit)
            card.enabled_changed.connect(self._on_card_enabled_changed)
            self.cards[role] = card
            cards_row.addWidget(card, 1)
        outer.addLayout(cards_row)

        session_card = theme.Card(tr('연결 제어'))
        body = session_card.body()

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addStretch(1)
        self.probe_all_button = QPushButton(tr('전체 Probe'))
        self.connect_all_button = QPushButton(tr('전체 연결'))
        self.connect_all_button.setObjectName("primary")
        row2.addWidget(self.probe_all_button)
        row2.addWidget(self.connect_all_button)
        body.addLayout(row2)

        self.note = QLabel(
            tr('probe 는 실제 명령을 보내지 않습니다 — 어느 콘솔에도 없는 토큰 1개를 보내고 unknown-command '
               '응답 서명으로 역할을 판정합니다 (오배정 포트에서 부수 효과 0).'))
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        body.addWidget(self.note)

        suggest_row = QHBoxLayout()
        self.suggestion = QLabel("")
        self.suggestion.setWordWrap(True)
        self.apply_suggestion_button = QPushButton(tr('제안 적용'))
        self.apply_suggestion_button.hide()
        suggest_row.addWidget(self.suggestion, 1)
        suggest_row.addWidget(self.apply_suggestion_button)
        body.addLayout(suggest_row)
        self.apply_suggestion_button.clicked.connect(self._apply_suggestion)
        self._suggested: dict[str, str] = {}

        outer.addWidget(session_card)
        outer.addStretch(1)

        self.connect_all_button.clicked.connect(self._on_connect_all)
        self.probe_all_button.clicked.connect(self.probe_all_requested.emit)
        self._refresh_count_row()

    # ------------------------------------------------------------------ 사용 포트 구성

    def _set_count(self, count: int) -> None:
        self.profile.set_active_count(count)
        for card in self.cards.values():
            card._load_from_profile()
        self._refresh_count_row()
        self.ports_changed.emit()

    def _on_card_enabled_changed(self) -> None:
        # 전부 끄면 남길 게 없다 — 마지막 하나는 되돌린다
        if not any(entry.enabled for entry in self.profile.ports):
            self.profile.ports[0].enabled = True
            self.cards[self.profile.ports[0].role]._load_from_profile()
        self._refresh_count_row()
        self.ports_changed.emit()

    def _refresh_count_row(self) -> None:
        active = [entry.role for entry in self.profile.ports if entry.enabled]
        contiguous = active == self.profile.roles()[:len(active)]
        for count, button in self.count_buttons.items():
            button.setChecked(contiguous and count == len(active))
        hidden = [entry.role for entry in self.profile.ports if not entry.enabled]
        self.count_hint.setText(
            tr('사용 안 함: {0} — 화면·명령 대상·로그에서 빠집니다').format(', '.join(hidden))
            if hidden else tr('3개 콘솔을 모두 사용합니다'))

    def _on_log_naming_changed(self, *_args) -> None:
        self.log_naming_changed.emit()

    # ------------------------------------------------------------------ 프로파일

    def refresh_profiles(self) -> None:
        pass   # 프로파일 UI 는 설정 > 프로파일 페이지가 담당한다

    def rebind(self, session: SerialHubSession) -> None:
        """프로파일을 갈아끼운 뒤 카드들을 새 값으로 다시 그린다."""
        self.session = session
        self.profile = session.profile
        for card in self.cards.values():
            card.reload_profile(self.profile)

    def _on_connect_all(self) -> None:
        if self.session.any_connected():
            self.disconnect_all_requested.emit()
        else:
            self.connect_all_requested.emit()

    # ------------------------------------------------------------------ 갱신

    def tick(self) -> None:
        busy = False
        for role, card in self.cards.items():
            reader = self.session.readers.get(role)
            card.live_com = reader.com if (reader is not None and reader.is_running) else ""
            card.set_state(self.session.state_of(role), self.session.error_of(role))
            card.tick()
            busy = busy or card.probing
        self.probe_all_button.setEnabled(not busy)
        self._update_suggestion()
        self.connect_all_button.setText(
            tr('전체 해제') if self.session.any_connected() else tr('전체 연결'))

    def start_probe(self, role: str) -> None:
        card = self.cards.get(role)
        if card is not None:
            card.start_probe(self.session)

    def start_probe_all(self) -> None:
        self._suggested = {}
        self.suggestion.setText("")
        self.apply_suggestion_button.hide()
        for card in self.cards.values():
            card.last_verdict = ""
        for role in self.cards:
            self.start_probe(role)

    def _update_suggestion(self) -> None:
        """probe 가 다 끝나면 포트↔역할 매핑을 제안한다.

        "COM4=shell, COM5=log 인 벤치도 있다" 는 절차서 경고에 대한 UI 차원의 답이다.
        적용은 사용자가 누른다 — 자동으로 바꾸지 않는다.
        """
        if any(card.probing for card in self.cards.values()):
            return
        verdicts = {role: card.last_verdict for role, card in self.cards.items()}
        if not all(verdicts.values()) or self._suggested:
            return
        if sorted(verdicts.values()) != sorted(self.cards.keys()):
            return  # 판정이 역할 전체의 순열이 아니면 제안하지 않는다 (중복·미확정)
        # 제안은 **실제로 probe 한 COM** 으로만 조립한다 (콤보 현재값이 아니라)
        if any(not self.cards[role].last_probed_com for role in verdicts):
            return
        proposal = {verdict: self.cards[role].last_probed_com
                    for role, verdict in verdicts.items()}
        current = {role: (self.profile.port(role).com if self.profile.port(role) else "")
                   for role in self.cards}
        if proposal == current:
            self.suggestion.setText(tr('probe 결과가 현재 매핑과 일치합니다.'))
            self.suggestion.setStyleSheet(f"QLabel {{ color: {theme.SUCCESS}; }}")
            self._suggested = proposal
            return
        self._suggested = proposal
        text = ", ".join(f"{role}={com}" for role, com in proposal.items() if com)
        self.suggestion.setText(tr('probe 결과가 현재 매핑과 다릅니다 → 제안: {0}').format(text))
        self.suggestion.setStyleSheet(f"QLabel {{ color: {theme.WARNING}; }}")
        self.apply_suggestion_button.show()

    def _apply_suggestion(self) -> None:
        if not self._suggested:
            return
        # CONNECTED 만 보면 재접속 루프 중인 reader(옛 COM 을 계속 여는 중)를 놓쳐,
        # 적용 후 카드가 "새 COM + Connected" 라는 거짓 표시를 하게 된다
        if any(reader.is_running for reader in self.session.readers.values()):
            self.suggestion.setText(tr('연결(또는 재접속 중인) 포트가 있습니다 — 전체 해제 후 적용하세요.'))
            self.suggestion.setStyleSheet(f"QLabel {{ color: {theme.WARNING}; }}")
            return
        for role, com in self._suggested.items():
            entry = self.profile.port(role)
            if entry is not None:
                entry.com = com
        for card in self.cards.values():
            card.reload_profile(self.profile)
        self.apply_suggestion_button.hide()
        self.suggestion.setText(tr('매핑을 적용했습니다 — [저장] 을 눌러 프로파일에 남기세요.'))
        self.suggestion.setStyleSheet(f"QLabel {{ color: {theme.SUCCESS}; }}")

    def report_open_failure(self, role: str, error: str) -> None:
        card = self.cards.get(role)
        if card is None:
            return
        # 다음 tick 의 set_state 가 이 안내를 덮지 않도록 키를 선점한다
        card._last_state_key = (STATE_DISCONNECTED, error)
        card._error_shown = True
        card.set_status(tr('열기 실패: {0} — 점유 프로세스 조회 중…').format(error[:80]), theme.DANGER)
        card.start_holder_lookup()


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionLabel")
    label.setAlignment(Qt.AlignVCenter)
    return label
