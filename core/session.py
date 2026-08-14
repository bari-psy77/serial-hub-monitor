"""SerialHubSession — 프로파일 · LogStore · PortReader 들을 묶는 Qt 비의존 오케스트레이터.

UI 가 없어도 동작하므로 헤드리스 테스트가 가능하다.
"""

from __future__ import annotations

import time

from .config import Profile
from .diag import diag
from .filters import Redactor
from .logstore import LogStore
from .port import STATE_CONNECTED, PortReader
from .i18n import tr


class SerialHubSession:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.store = LogStore(capacity_per_port=profile.capacity_per_port)
        self.redactor = Redactor(profile.redact_rules)
        self.store.set_redactor(self.redactor)
        self.store.set_ansi_strip(profile.strip_ansi)
        self.store.max_file_bytes = int(profile.max_log_mb) * 1024 * 1024
        profile.set_redactor(self.redactor)  # 프로파일 저장 경로도 마스킹을 거치게 한다
        diag.info("session", f"init profile=`{profile.name}` "
                             f"ports={[(p.role, p.com) for p in profile.ports]}")
        self.readers: dict[str, PortReader] = {}
        self.session_name: str = ""
        for role in profile.roles():
            self.store.register_port(role)

    # ------------------------------------------------------------------ 룰

    def apply_redact_rules(self) -> list[str]:
        """반환값 = 무력화된 룰 목록. 비어 있지 않으면 사용자에게 보여야 한다."""
        return self.redactor.set_rules(self.profile.redact_rules)

    # ------------------------------------------------------------------ 기록

    def new_session_name(self) -> str:
        return f"{self.profile.session_prefix}_{time.strftime('%H%M%S')}"

    def apply_log_naming(self) -> None:
        """프로파일의 포트별 파일명 설정을 store 에 반영한다 (다음 세션/분절부터)."""
        from .logstore import MERGED_KEY
        names = {entry.role: entry.log_name for entry in self.profile.ports if entry.log_name}
        names[MERGED_KEY] = self.profile.merged_log_name
        self.store.set_file_naming(names, self.profile.log_include_session)
        self.store.set_use_date_folder(self.profile.log_use_date_folder)

    def retarget_logs(self) -> tuple[str, str]:
        """기록 중 로그 폴더·파일명·접두어가 바뀌면 지금부터 새 파일에 쓴다.

        반환값 = (옛 폴더, 새 폴더). 기록 중이 아니면 ("", "") — 설정만 반영하고 끝난다.
        """
        old_dir = self.store.log_dir or ""
        self.apply_log_naming()
        if not self.store.recording:
            return "", ""
        prefix = self.profile.session_prefix
        name = self.session_name
        if prefix and not name.startswith(f"{prefix}_"):
            name = self.new_session_name()   # 접두어를 바꿨으면 세션 이름도 새로
            self.session_name = name
        else:
            name = None                      # 이름은 그대로, 위치/파일명만 갈아끼운다
        new_dir = self.store.relocate(self.profile.log_base_dir, name)
        return old_dir, new_dir

    def plan_recording(self, session_name: str) -> dict[str, str]:
        """이 이름으로 기록을 시작하면 만들어질 파일 경로 — 시작 전 존재 검사(덮어쓰기 확인)용."""
        self.apply_log_naming()
        return self.store.plan_paths(self.profile.log_base_dir, session_name,
                                     self.profile.active_roles())

    def start_recording(self, session_name: str | None = None, overwrite: bool = False) -> str:
        self.session_name = session_name or self.new_session_name()
        self.apply_log_naming()
        self.store.start_session(self.profile.log_base_dir, self.session_name,
                                 self.profile.active_roles(), overwrite=overwrite)
        return self.session_name

    def stop_recording(self) -> None:
        self.store.stop_session()

    # ------------------------------------------------------------------ 연결

    def connect(self, role: str) -> tuple[bool, str]:
        entry = self.profile.port(role)
        if entry is None:
            return False, tr('{0} 설정 없음').format(role)
        if not entry.com:
            return False, tr('{0} 포트 미지정').format(role)
        reader = self.readers.get(role)
        if reader is not None and reader.is_running:
            if reader.com == entry.com and reader.baud == entry.baud:
                return True, ""
            if not reader.stop():
                # 죽지 않은 스레드가 포트를 물고 있다. 새 reader 를 띄우면 라인이 두 번 들어온다
                return False, tr('{0} 기존 수신 스레드가 종료되지 않음 — 앱을 재시작하세요').format(role)
        reader = PortReader(role, entry.com, entry.baud, self.store)
        self.readers[role] = reader
        return reader.start()

    def disconnect(self, role: str) -> None:
        reader = self.readers.pop(role, None)
        if reader is not None:
            reader.stop()

    def connect_all(self) -> list[tuple[str, bool, str]]:
        results: list[tuple[str, bool, str]] = []
        for entry in self.profile.ports:
            if not entry.enabled or not entry.com:
                continue
            ok, err = self.connect(entry.role)
            results.append((entry.role, ok, err))
        diag.info("session", f"connect_all -> {[(r, ok) for r, ok, _e in results]}")
        return results

    def disconnect_all(self) -> None:
        for role in list(self.readers.keys()):
            self.disconnect(role)

    def shutdown(self) -> None:
        self.disconnect_all()
        self.stop_recording()

    # ------------------------------------------------------------------ 상태

    def state_of(self, role: str) -> str:
        reader = self.readers.get(role)
        return reader.state if reader is not None else "disconnected"

    def error_of(self, role: str) -> str:
        reader = self.readers.get(role)
        return reader.last_error if reader is not None else ""

    def is_connected(self, role: str) -> bool:
        return self.state_of(role) == STATE_CONNECTED

    def any_connected(self) -> bool:
        return any(r.state == STATE_CONNECTED for r in self.readers.values())

    def send(self, role: str, text: str) -> tuple[bool, str]:
        reader = self.readers.get(role)
        if reader is None:
            return False, tr('{0} 미연결 — 전송하지 않음').format(role)
        return reader.send(text)
