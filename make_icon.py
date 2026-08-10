#!/usr/bin/env python3
"""앱 아이콘 생성 — Qt 로 그려서 .ico 와 런타임용 PNG(base64) 를 만든다.

  python make_icon.py

산출물:
  assets/serialhub.ico        PyInstaller(exe) · Inno Setup(설치 마법사)
  ui/appicon.py               창 아이콘용 PNG(base64) — 별도 데이터 파일 없이 번들에 들어간다

도안: 짙은 콘솔 패널 위에 3개의 로그 줄, 왼쪽에 포트 상태 점 3개(초록/노랑/파랑).
"3포트 콘솔 모니터" 를 16px 에서도 알아볼 수 있게 요소를 최소화했다.
"""

from __future__ import annotations

import base64
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
ICO_PATH = os.path.join(ASSETS, "serialhub.ico")
PY_PATH = os.path.join(HERE, "ui", "appicon.py")

SIZES = (16, 24, 32, 48, 64, 128, 256)

PANEL = "#1F2A37"      # 콘솔 패널 (어두운 배경 = 터미널 연상)
PANEL_EDGE = "#111827"
ACCENT = "#3182F6"     # Toss 계열 파랑 — 앱 테마와 같은 색
DOTS = ("#00C471", "#FFB331", "#3182F6")   # MLOG / SHELL / UCLI 상태 점
LINES = ("#E5E8EB", "#C7CDD4", "#9AA3AD")


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    unit = size / 32.0          # 32px 기준으로 그리고 배율만 바꾼다
    radius = 7 * unit
    body = QRectF(1.5 * unit, 1.5 * unit, 29 * unit, 29 * unit)

    path = QPainterPath()
    path.addRoundedRect(body, radius, radius)
    painter.fillPath(path, QColor(PANEL))
    painter.setPen(QColor(PANEL_EDGE))
    painter.drawPath(path)

    # 상단 액센트 바 — 툴바를 연상시키고 색으로 앱을 식별하게 한다
    top = QPainterPath()
    top.addRoundedRect(QRectF(1.5 * unit, 1.5 * unit, 29 * unit, 6 * unit),
                       radius * 0.8, radius * 0.8)
    painter.fillPath(top.intersected(path), QColor(ACCENT))

    if size >= 24:
        # 3포트 상태 점 + 로그 줄
        for index in range(3):
            y = (12.5 + index * 6.0) * unit
            painter.setBrush(QColor(DOTS[index]))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(6 * unit, y - 1.6 * unit, 3.2 * unit, 3.2 * unit))
            painter.setBrush(QColor(LINES[index]))
            width = (15.5, 13.0, 10.0)[index] * unit
            painter.drawRoundedRect(QRectF(11 * unit, y - 1.1 * unit, width, 2.2 * unit),
                                    1.1 * unit, 1.1 * unit)
    else:
        # 16px 에서는 점·줄이 뭉개진다 — 굵은 줄 3개만 남긴다
        painter.setPen(Qt.NoPen)
        for index in range(3):
            y = (13.0 + index * 5.6) * unit
            painter.setBrush(QColor(DOTS[index]))
            painter.drawRoundedRect(QRectF(6 * unit, y, (18 - index * 4) * unit, 2.8 * unit),
                                    1.2 * unit, 1.2 * unit)

    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    # QByteArray 를 지역 변수로 붙들어야 한다 — 임시로 넘기면 QBuffer 보다 먼저
    # 해제돼 access violation 이 난다 (PySide6 수명 함정)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def write_ico(path: str, images: list[QImage]) -> None:
    """크기별 PNG 를 담은 멀티사이즈 ICO 를 직접 조립한다.

    Qt 의 ICO 라이터는 QImage 하나만 받아서 256px 한 장짜리가 되고, Windows 가 그걸
    16px 로 축소하면 뭉개진다. 크기마다 전용 도안을 넣어야 작업표시줄에서도 선명하다.
    (PNG 를 그대로 담는 ICO 는 Vista 이후 표준)
    """
    payloads = [png_bytes(image) for image in images]
    count = len(payloads)
    header = (0).to_bytes(2, "little") + (1).to_bytes(2, "little") + count.to_bytes(2, "little")
    offset = 6 + 16 * count
    entries, blobs = [], []
    for image, payload in zip(images, payloads, strict=True):
        side = image.width() if image.width() < 256 else 0
        entries.append(bytes([side, side, 0, 0])
                       + (1).to_bytes(2, "little") + (32).to_bytes(2, "little")
                       + len(payload).to_bytes(4, "little") + offset.to_bytes(4, "little"))
        blobs.append(payload)
        offset += len(payload)
    with open(path, "wb") as fh:
        fh.write(header + b"".join(entries) + b"".join(blobs))


def main() -> int:
    app = QApplication.instance() or QApplication([])  # noqa: F841 - QPainter 에 필요
    os.makedirs(ASSETS, exist_ok=True)

    images = [draw(size) for size in SIZES]
    write_ico(ICO_PATH, images)
    for size, image in zip(SIZES, images, strict=True):
        image.save(os.path.join(ASSETS, f"serialhub_{size}.png"), "PNG")

    encoded = base64.b64encode(png_bytes(images[-1])).decode("ascii")
    chunks = [encoded[i:i + 96] for i in range(0, len(encoded), 96)]
    body = "\n".join(f'    "{chunk}"' for chunk in chunks)
    with open(PY_PATH, "w", encoding="utf-8") as fh:
        fh.write(
            '"""앱 아이콘(PNG, base64) — make_icon.py 가 생성한다. 직접 고치지 마라.\n\n'
            '별도 데이터 파일로 두면 PyInstaller 번들 경로 문제가 생겨서, 코드에 심는다.\n'
            '"""\n\nimport base64\n\nfrom PySide6.QtGui import QIcon, QPixmap\n\n'
            'ICON_PNG_B64 = (\n'
            f'{body}\n)\n\nICON_PNG = base64.b64decode(ICON_PNG_B64)\n\n\n'
            '_cached: QIcon | None = None\n\n\n'
            'def app_icon() -> QIcon:\n'
            '    """창·작업표시줄 아이콘. QApplication 생성 후에 호출할 것."""\n'
            '    global _cached\n'
            '    if _cached is None:\n'
            '        pixmap = QPixmap()\n'
            '        pixmap.loadFromData(ICON_PNG, "PNG")\n'
            '        _cached = QIcon(pixmap)\n'
            '    return _cached\n')

    print(f"아이콘 생성: {ICO_PATH}")
    print(f"런타임 아이콘: {PY_PATH} ({len(encoded)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
