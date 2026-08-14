# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:\\project\\serial_hub\\docs\\SerialHub_사용설명서.html', 'docs'), ('C:\\project\\serial_hub\\docs\\SerialHub_UserGuide_en.html', 'docs')]
binaries = []
hiddenimports = ['serial.tools.list_ports', 'serial.tools.list_ports_windows', 'winpty', 'pyte']
tmp_ret = collect_all('winpty')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\project\\serial_hub\\launcher.py'],
    pathex=['C:\\project'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.Qt3DCore', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtBluetooth', 'PySide6.QtNetworkAuth', 'PySide6.QtPositioning', 'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDesigner', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSvgWidgets', 'PySide6.QtSerialPort', 'PySide6.QtHelp', 'tkinter', 'unittest', 'pydoc_data', 'numpy', 'matplotlib', 'PIL'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SerialHub',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\project\\serial_hub\\assets\\serialhub.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SerialHub',
)
