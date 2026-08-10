#!/usr/bin/env python3
"""PyInstaller 진입점.

`app.py` 를 직접 얼리면 상대 임포트(`from .core import ...`)를 정적 분석하지 못해
패키지가 통째로 번들에서 빠진다 — 실행하면 `No module named 'serial_hub'` 로 죽는다.
절대 임포트 한 줄을 거쳐야 PyInstaller 가 패키지를 따라 수집한다.
"""

import sys

from serial_hub.app import main

if __name__ == "__main__":
    sys.exit(main())
