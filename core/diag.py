"""앱 자체 진단 로그 — 시리얼 수신 로그와는 별개다.

"어제 밤에 이상했다" 는 보고를 받았을 때 사후 분석할 수 있도록, 앱의 수명 이벤트
(연결/해제, 재접속, probe 판정, 기록 실패, 프로파일 전환, 예외)를
`<DATA_DIR>/app.log` 에 남긴다. 회전 보관(1MB × 3)이라 무한히 자라지 않는다.

사용: from .diag import diag; diag.info("port", "MLOG open COM4 ok")
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading

_LOG_NAME = "serialhub"
_MAX_BYTES = 1_000_000
_BACKUPS = 3


class _QuietRotatingHandler(logging.handlers.RotatingFileHandler):
    """앱을 두 번 띄우면 같은 app.log 를 두 핸들러가 쥐어 rename(롤오버)이 실패한다.

    그때 traceback 을 stderr 로 쏟아봐야 창 모드 exe 에서는 보이지도 않고 레코드만
    잃는다 — 롤오버를 포기하고 계속 append 하는 쪽이 진단 로그로서 유용하다.
    """

    def doRollover(self) -> None:  # noqa: N802 - logging 시그니처
        try:
            super().doRollover()
        except OSError:
            if self.stream is None:
                self.stream = self._open()

    def handleError(self, record) -> None:  # noqa: N802 - logging 시그니처
        pass


class _Diag:
    """지연 초기화 — config 의 DATA_DIR 이 정해진 뒤 첫 사용 시점에 파일을 연다."""

    def __init__(self):
        self._logger: logging.Logger | None = None
        self._lock = threading.Lock()
        self.path: str = ""

    def reconfigure(self) -> None:
        """DATA_DIR 이 바뀐 뒤 로그 파일을 다시 연다 (테스트·프로파일 이동).

        전역 `logging.getLogger` 는 프로세스 하나뿐이라, 참조만 지우면 옛 핸들러가
        남아 두 파일에 중복 기록되고 옛 파일 핸들이 안 닫혀 Windows 에서 삭제도 안 된다.
        """
        with self._lock:
            logger = logging.getLogger(_LOG_NAME)
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:  # noqa: BLE001
                    pass
            self._logger = None

    def _ensure(self) -> logging.Logger:
        with self._lock:
            if self._logger is not None:
                return self._logger
            logger = logging.getLogger(_LOG_NAME)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            for handler in list(logger.handlers):  # 재초기화 시 중복 부착 방지
                logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                from . import config as config_mod
                self.path = os.path.join(config_mod.DATA_DIR, "app.log")
                os.makedirs(config_mod.DATA_DIR, exist_ok=True)
                handler = _QuietRotatingHandler(
                    self.path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
                handler.setFormatter(logging.Formatter(
                    "%(asctime)s.%(msecs)03d %(levelname).1s [%(threadName)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S"))
                logger.addHandler(handler)
            except Exception:  # noqa: BLE001 - 진단 로그를 못 열어도 앱은 살아야 한다
                logger.addHandler(logging.NullHandler())
            self._logger = logger
            return logger

    def _fmt(self, area: str, message: str) -> str:
        return f"{area}: {message}"

    def info(self, area: str, message: str) -> None:
        self._ensure().info(self._fmt(area, message))

    def warn(self, area: str, message: str) -> None:
        self._ensure().warning(self._fmt(area, message))

    def error(self, area: str, message: str) -> None:
        self._ensure().error(self._fmt(area, message))

    def exception(self, area: str, message: str) -> None:
        """현재 예외의 traceback 을 함께 남긴다 — except 블록 안에서만 호출."""
        self._ensure().error(self._fmt(area, message), exc_info=sys.exc_info())


diag = _Diag()
