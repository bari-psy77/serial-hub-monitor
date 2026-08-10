#!/usr/bin/env python3
"""Serial Hub 실행파일 빌드 (PyInstaller, Windows).

  python build_exe.py            # 폴더형 (권장 — 기동 빠름)
  python build_exe.py --onefile  # 단일 exe (복사 편함, 기동 느림)
  python build_exe.py --zip      # 빌드 후 배포용 zip 까지

산출물: dist/SerialHub/SerialHub.exe

★ onefile 은 실행할 때마다 임시폴더에 통째로 풀기 때문에 PySide6 기준 기동이
  10초 안팎 걸린다. 매일 쓰는 툴이라 폴더형이 기본이다. 프로파일·설정·crash.log 는
  둘 다 exe 옆에 쌓인다 (core/config.py `_data_dir`).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(HERE)
APP_NAME = "SerialHub"

# PySide6 는 안 쓰는 모듈까지 통째로 딸려온다 — 빼면 산출물이 절반 이하로 줄어든다
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNetworkAuth",
    "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSvgWidgets", "PySide6.QtSerialPort", "PySide6.QtHelp",
    "tkinter", "unittest", "pydoc_data", "numpy", "matplotlib", "PIL",
]


def build(onefile: bool, clean: bool) -> int:
    # app.py 를 직접 얼리면 상대 임포트를 못 따라가 패키지가 빠진다 (launcher.py 주석 참조)
    entry = os.path.join(HERE, "launcher.py")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--windowed",                 # 콘솔 창 없이 — 예외는 crash.log 로 남는다
        "--noconfirm",
        "--paths", SCRIPTS_DIR,       # `serial_hub` 패키지를 찾게 한다
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build"),
        "--specpath", HERE,
        "--hidden-import", "serial.tools.list_ports",
        "--hidden-import", "serial.tools.list_ports_windows",
    ]
    # 사용 설명서를 exe 옆 docs\ 로 같이 넣는다 — 도움말(F1)이 이걸 연다
    guide = os.path.join(HERE, "docs", "SerialHub_사용설명서.html")
    if os.path.exists(guide):
        cmd += ["--add-data", f"{guide};docs"]
    else:
        print("!! 사용 설명서가 없다 — python make_docs.py 를 먼저 돌려라")
    icon = os.path.join(HERE, "assets", "serialhub.ico")
    if os.path.exists(icon):
        cmd += ["--icon", icon]
    else:
        print("!! 아이콘이 없다 — python make_icon.py 를 먼저 돌려라 (기본 아이콘으로 빌드)")
    for module in EXCLUDES:
        cmd += ["--exclude-module", module]
    if onefile:
        cmd.append("--onefile")
    if clean:
        cmd.append("--clean")
    cmd.append(entry)

    print("빌드 시작:", " ".join(cmd[:8]), "…")
    started = time.monotonic()
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print(f"!! PyInstaller 실패 (exit {result.returncode})")
        return result.returncode
    print(f"빌드 완료 ({time.monotonic() - started:.0f}s)")
    return 0


def report(onefile: bool) -> str:
    target = (os.path.join(HERE, "dist", f"{APP_NAME}.exe") if onefile
              else os.path.join(HERE, "dist", APP_NAME, f"{APP_NAME}.exe"))
    if not os.path.exists(target):
        print(f"!! 산출물이 없다: {target}")
        return ""
    if onefile:
        size = os.path.getsize(target)
    else:
        size = sum(os.path.getsize(os.path.join(root, name))
                   for root, _dirs, files in os.walk(os.path.dirname(target))
                   for name in files)
    print(f"산출물: {target}  ({size / 1024 / 1024:.0f} MB)")
    return target


def make_zip(onefile: bool) -> None:
    folder = os.path.join(HERE, "dist", APP_NAME)
    if onefile or not os.path.isdir(folder):
        print("zip 은 폴더형 빌드에서만 만든다")
        return
    archive = shutil.make_archive(os.path.join(HERE, "dist", f"{APP_NAME}_{time.strftime('%Y%m%d')}"),
                                  "zip", root_dir=os.path.join(HERE, "dist"), base_dir=APP_NAME)
    print(f"배포용 zip: {archive}  ({os.path.getsize(archive) / 1024 / 1024:.0f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Serial Hub 실행파일 빌드")
    parser.add_argument("--onefile", action="store_true", help="단일 exe (기동 느림)")
    parser.add_argument("--zip", action="store_true", help="빌드 후 배포용 zip 생성")
    parser.add_argument("--clean", action="store_true", help="PyInstaller 캐시 비우고 빌드")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller 가 없다: python -m pip install pyinstaller")
        return 2

    code = build(args.onefile, args.clean)
    if code != 0:
        return code
    report(args.onefile)
    if args.zip:
        make_zip(args.onefile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
