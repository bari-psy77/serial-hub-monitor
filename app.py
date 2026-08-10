#!/usr/bin/env python3
"""Serial Hub 엔트리포인트.

  python app.py [--profile <이름>]
  python -m serial_hub.app          (scripts/ 를 sys.path 에 둔 경우)
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import traceback

if __package__ in (None, "") and not getattr(sys, "frozen", False):
    # 파일 경로로 직접 실행해도 패키지 상대 임포트가 되도록 scripts/ 를 경로에 넣는다.
    # exe 로 묶였을 때는 launcher.py 가 절대 임포트로 들어오므로 이 보정이 필요 없다
    # (오히려 번들 안의 가짜 __file__ 경로를 sys.path 에 넣게 된다).
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "serial_hub"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from . import __version__  # noqa: E402
from .core import config as config_mod  # noqa: E402
from .core.config import Profile  # noqa: E402
from .core import i18n  # noqa: E402
from .core.diag import diag  # noqa: E402

# ★UI 모듈을 임포트하기 **전에** 언어를 정한다. 모듈 최상위에서 tr() 를 부르는 상수가
#   있으면 임포트 시점의 언어로 굳기 때문이다 (selftest 가 그런 상수를 감시하지만,
#   순서를 지켜두면 애초에 문제가 되지 않는다).
i18n.set_language(config_mod.language())

from .ui import theme  # noqa: E402
from .ui.appicon import app_icon  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402
from .core.i18n import tr  # noqa: E402

DEMO_LINES = [
    ("MLOG", "[DEMO][ZCL] Thermostat: LocalTemperature = {n}"),
    ("MLOG", "[DEMO][DIS] mDNS advertise _matter._tcp"),
    ("MLOG", "[DEMO][apple-connectivity] CASE transports: wifi=1 thread=0"),
    ("MLOG", "[DEMO][SRP] client state: Registered"),
    ("SHELL", "[DEMO] leader"),
    ("UCLI", "[DEMO] heap: free 128456"),
]


def start_demo_feed(window: MainWindow) -> QTimer:
    """하드웨어 없이 화면을 확인하기 위한 합성 입력. 모든 줄에 [DEMO] 가 붙는다."""
    counter = {"n": 0}

    def feed() -> None:
        role, template = DEMO_LINES[counter["n"] % len(DEMO_LINES)]
        window.session.store.append(role, template.format(n=counter["n"]))
        counter["n"] += 1

    timer = QTimer(window)
    timer.setInterval(120)
    timer.timeout.connect(feed)
    timer.start()
    window.set_status(tr('데모 모드 — 화면의 [DEMO] 줄은 합성 데이터입니다 (실제 포트 아님)'), theme.WARNING)
    return timer


def install_crash_handler() -> str:
    """exe(창 모드)는 콘솔이 없어 예외가 통째로 사라진다 — 파일로 남기고 창으로 알린다."""
    log_path = os.path.join(config_mod.DATA_DIR, "crash.log")

    def write(kind: str, text: str) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n===== {kind} {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n{text}")
        except Exception:  # noqa: BLE001 - 로그도 못 쓰면 더 할 게 없다
            pass

    def hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        write("main", text)
        diag.error("crash", f"{exc_type.__name__}: {exc}")
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is not None:
                QMessageBox.critical(None, tr('Serial Hub 오류'),
                                     tr('{0}: {1}\n\n기록: {2}').format(exc_type.__name__, exc, log_path))
        except Exception:  # noqa: BLE001
            pass

    def thread_hook(args) -> None:
        name = args.thread.name if args.thread else "?"
        write(f"thread:{name}",
              "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
        diag.error("crash", f"thread {name}: {args.exc_type.__name__}: {args.exc_value}")

    sys.excepthook = hook
    threading.excepthook = thread_hook
    return log_path


def emit(lines: list[str], filename: str) -> str:
    """창 모드 exe 는 stdout 이 없다 — 파일로도 남겨야 결과를 볼 수 있다."""
    text = "\n".join(lines)
    path = os.path.join(config_mod.DATA_DIR, filename)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:  # noqa: BLE001
        path = tr('(파일 기록 실패)')
    if sys.stdout is not None:
        try:
            print(text)
            print(tr('\n기록: {0}').format(path))
        except Exception:  # noqa: BLE001
            pass
    return path


def selfcheck() -> tuple[bool, list[str]]:
    """빌드된 exe 가 진짜 쓸 수 있는 상태인지 확인한다.

    특히 pyserial 의 COM 열거는 `list_ports()` 가 예외를 삼키기 때문에, 번들에서
    빠져 있어도 화면상으로는 "포트 0개" 로만 보인다 — 여기서 직접 확인한다.
    """
    lines = [f"Serial Hub selfcheck  {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"frozen={getattr(sys, 'frozen', False)}  python={sys.version.split()[0]}",
             f"data_dir={config_mod.DATA_DIR}"]
    ok = True

    try:
        import serial
        from serial.tools import list_ports as lp
        ports = list(lp.comports())
        lines.append(
                tr('[OK] pyserial {0} — COM 열거 동작 ({1}개 발견)').format(serial.__version__, len(ports)))
        for info in ports:
            lines.append(f"       {info.device}  {info.description}")
        if not ports:
            lines.append(tr('       (이 PC 에 시리얼 포트가 없습니다 — 열거 기능 자체는 정상)'))
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(tr('[FAIL] pyserial 사용 불가: {0!r}').format(exc))

    try:
        from PySide6 import QtCore
        from PySide6.QtWidgets import QApplication  # noqa: F401
        lines.append(f"[OK] PySide6 {QtCore.__version__}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(tr('[FAIL] PySide6 사용 불가: {0!r}').format(exc))

    try:
        from .core.logstore import LogStore
        from .core.portscan import DEFAULT_PROBE_TOKEN, classify_probe_text
        store = LogStore()
        store.append("MLOG", "selfcheck")
        verdict, _ = classify_probe_text(
            f"Error {DEFAULT_PROBE_TOKEN}: 2f (Invalid argument)", DEFAULT_PROBE_TOKEN)
        assert store.last_seq() == 1 and verdict == "SHELL"
        lines.append(tr('[OK] core (LogStore / probe 판정)'))
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(tr('[FAIL] core 동작 이상: {0!r}').format(exc))

    try:
        if config_mod._writable(config_mod.PROFILE_DIR):
            lines.append(tr('[OK] 프로파일 저장 가능: {0}').format(config_mod.PROFILE_DIR))
        else:
            ok = False
            lines.append(tr('[FAIL] 프로파일 폴더에 쓸 수 없습니다: {0}').format(config_mod.PROFILE_DIR))
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(tr('[FAIL] 프로파일 폴더 확인 실패: {0!r}').format(exc))

    lines.append(tr('=> 사용 가능') if ok else tr('=> 문제 있음'))
    return ok, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=tr('Serial Hub — 포트 통합 시리얼 모니터'))
    parser.add_argument("--profile", default=None, help=tr('사용할 프로파일 이름 (기본: 마지막 사용)'))
    parser.add_argument("--demo", action="store_true",
                        help=tr('포트 없이 합성 로그로 화면만 확인 (기록·연결 없음)'))
    parser.add_argument("--where", action="store_true",
                        help=tr('프로파일·설정이 저장되는 경로를 출력하고 끝냅니다'))
    parser.add_argument("--selfcheck", action="store_true",
                        help=tr('이 빌드가 쓸 수 있는 상태인지 점검 (pyserial·Qt·저장 경로)'))
    parser.add_argument("--set-log-dir", metavar="PATH", default=None,
                        help=tr('새 프로파일의 로그 기본 위치를 지정 (설치 프로그램이 사용)'))
    args = parser.parse_args(argv)
    crash_log = install_crash_handler()
    if args.set_log_dir:
        path = config_mod.set_default_log_base(args.set_log_dir)
        emit([tr('로그 기본 위치를 설정했습니다: {0}')
            .format(args.set_log_dir), tr('기록: {0}').format(path)], "where.txt")
        return 0
    if args.where:
        emit([tr('데이터 폴더   : {0}').format(config_mod.DATA_DIR),
              tr('프로파일      : {0}').format(config_mod.PROFILE_DIR),
              tr('설정          : {0}').format(config_mod.SETTINGS_PATH),
              tr('로그 기본 위치: {0}').format(config_mod.default_log_base()),
              tr('크래시 로그   : {0}').format(crash_log)], "where.txt")
        return 0
    if args.selfcheck:
        ok, lines = selfcheck()
        path = emit(lines, "selfcheck.txt")
        if sys.stdout is None:
            # 창 모드 exe 는 콘솔이 없다 — 설치 직후 점검 결과를 볼 방법이 이것뿐이다
            app = QApplication.instance() or QApplication(sys.argv[:1])
            theme.apply_theme(app)
            box = QMessageBox(QMessageBox.Information if ok else QMessageBox.Critical,
                              tr('Serial Hub 설치 점검'),
                              tr('사용 가능한 상태입니다.') if ok
                              else tr('문제가 있습니다 — 아래 내용을 확인하세요.'))
            box.setDetailedText("\n".join(lines) + tr('\n\n기록: {0}').format(path))
            box.exec()
        return 0 if ok else 1

    diag.info("app", f"start v{__version__} frozen={getattr(sys, 'frozen', False)} "
                     f"argv={sys.argv[1:]} data={config_mod.DATA_DIR}")
    name = args.profile or config_mod.last_profile_name()
    profile, warning = Profile.load(name)
    if warning:
        diag.warn("app", warning)

    app = QApplication(sys.argv[:1])
    app.setWindowIcon(app_icon())
    app.setApplicationName("Serial Hub")
    theme.apply_theme(app)

    window = MainWindow(profile, warning)
    window.show()
    if args.demo:
        window._demo_timer = start_demo_feed(window)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
