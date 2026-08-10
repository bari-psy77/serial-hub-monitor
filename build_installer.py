#!/usr/bin/env python3
"""Serial Hub 설치 프로그램 빌드 (Inno Setup).

  python build_installer.py            # exe 가 없으면 먼저 빌드
  python build_installer.py --rebuild   # exe 부터 새로 빌드

산출물: dist/SerialHub_Setup_<버전>.exe

Inno Setup 이 없으면: winget install --id JRSoftware.InnoSetup
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ISS = os.path.join(HERE, "installer.iss")
EXE_DIR = os.path.join(HERE, "dist", "SerialHub")

ISCC_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def find_iscc() -> str | None:
    for path in ISCC_CANDIDATES:
        if path and os.path.exists(path):
            return path
    from shutil import which
    return which("ISCC.exe")


def main() -> int:
    parser = argparse.ArgumentParser(description="Serial Hub 설치 프로그램 빌드")
    parser.add_argument("--rebuild", action="store_true", help="exe 부터 새로 빌드")
    args = parser.parse_args()

    iscc = find_iscc()
    if iscc is None:
        print("Inno Setup 이 없다. 설치: winget install --id JRSoftware.InnoSetup")
        return 2

    if args.rebuild or not os.path.exists(os.path.join(EXE_DIR, "SerialHub.exe")):
        print("exe 가 없거나 --rebuild — build_exe.py 를 먼저 돌린다")
        code = subprocess.run([sys.executable, os.path.join(HERE, "build_exe.py")], cwd=HERE)
        if code.returncode != 0:
            return code.returncode

    print(f"Inno Setup: {iscc}")
    started = time.monotonic()
    result = subprocess.run([iscc, ISS], cwd=HERE)
    if result.returncode != 0:
        print(f"!! ISCC 실패 (exit {result.returncode})")
        return result.returncode

    produced = [f for f in os.listdir(os.path.join(HERE, "dist"))
                if f.startswith("SerialHub_Setup_") and f.endswith(".exe")]
    print(f"빌드 완료 ({time.monotonic() - started:.0f}s)")
    for name in sorted(produced):
        path = os.path.join(HERE, "dist", name)
        print(f"산출물: {path}  ({os.path.getsize(path) / 1024 / 1024:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
