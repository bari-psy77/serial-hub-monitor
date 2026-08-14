#!/usr/bin/env python3
"""사용 설명서(HTML) 생성 — 실제 UI 를 가상 DUT 로 띄워 캡처하고 한 파일로 묶는다.

  python make_docs.py

산출물 (이미지 base64 내장 — 파일 하나만 옮기면 된다):
  docs/SerialHub_사용설명서.html     한국어판
  docs/SerialHub_UserGuide_en.html   영어판 (도움말 F1 이 언어 설정에 맞는 쪽을 연다)

캡처는 uitest.py 의 가상 DUT(3콘솔 에뮬레이터)를 재사용한다 — 실제 장비 없이도
화면에 진짜 로그가 흐르는 상태를 만들 수 있고, 문서와 코드가 같이 늙지 않는다.
캡처 이미지는 두 판이 공유한다 (영어판에 한국어 UI 캡처가 실리는 것은 감수 —
캡션·본문은 각 언어로 쓴다).
"""

from __future__ import annotations

import base64
import html
import os
import shutil
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "serial_hub"

# ★offscreen 플랫폼은 폰트를 못 찾아 글자가 전부 두부 상자로 찍힌다 —
# 문서용 캡처는 실제 Windows 플랫폼으로 띄워야 한다 (uitest 임포트보다 먼저 지정).
os.environ["QT_QPA_PLATFORM"] = "windows"

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
OUT_KO = os.path.join(DOCS, "SerialHub_사용설명서.html")
OUT_EN = os.path.join(DOCS, "SerialHub_UserGuide_en.html")

from . import __version__  # noqa: E402
from .core import config as config_mod  # noqa: E402
from .core import diag as diag_mod  # noqa: E402
from .core import portscan  # noqa: E402

SHOTS: dict[str, bytes] = {}


def capture(widget, name: str, crop_height: int = 0) -> None:
    pixmap = widget.grab()
    if crop_height:
        from PySide6.QtCore import QRect
        pixmap = pixmap.copy(QRect(0, 0, pixmap.width(), min(crop_height, pixmap.height())))
    path = os.path.join(DOCS, f"{name}.png")
    pixmap.save(path, "PNG")
    with open(path, "rb") as fh:
        SHOTS[name] = fh.read()
    print(f"  캡처 {name}: {pixmap.width()}x{pixmap.height()}")


def img(name: str, caption: str = "") -> str:
    if name not in SHOTS:
        return f'<p class="missing">[캡처 없음: {name}]</p>'
    data = base64.b64encode(SHOTS[name]).decode("ascii")
    cap = f'<figcaption>{html.escape(caption)}</figcaption>' if caption else ""
    return (f'<figure><img alt="{html.escape(caption or name)}" '
            f'src="data:image/png;base64,{data}">{cap}</figure>')


def build_screens() -> None:  # noqa: PLR0915
    import tempfile

    from PySide6.QtWidgets import QApplication

    from .core import i18n
    from .core.config import Profile
    from .core.filters import FilterRule
    from .ui import theme
    from .ui.main_window import MainWindow
    from .uitest import VCOM_MLOG, VCOM_SHELL, VCOM_UCLI, VirtualDut, spin, wait_for

    # 캡처 이미지는 한/영 두 설명서가 공유한다. 기본 언어가 영어로 바뀌었지만
    # 캡처는 종전대로 한국어 UI 로 찍는다 — 영어판 본문·캡션은 각자 번역돼 있다.
    i18n.set_language("ko")

    # 화면에 찍히는 경로가 문서에서 읽히도록 짧고 대표적인 위치를 쓴다 (끝나면 지운다)
    tmp = os.path.join(tempfile.gettempdir(), "SerialHub_docs")
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    config_mod.DATA_DIR = os.path.join(tmp, "data")
    config_mod.PROFILE_DIR = os.path.join(tmp, "profiles")
    config_mod.SETTINGS_PATH = os.path.join(tmp, "settings.json")
    diag_mod.diag.reconfigure()

    dut = VirtualDut()
    dut.mlog_rate = 45
    original_open, original_list = portscan.open_serial, portscan.list_ports
    portscan.open_serial = dut.open
    portscan.list_ports = dut.list_ports

    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)

    profile = Profile()
    profile.name = "bench-A"
    profile.log_base_dir = os.path.join(tmp, "logs")
    profile.port("MLOG").com = VCOM_MLOG
    profile.port("SHELL").com = VCOM_SHELL
    profile.port("UCLI").com = VCOM_UCLI
    profile.saved_filters = [FilterRule(pattern="CASE", name="CASE 추적", ports=["MLOG"])]

    window = MainWindow(profile)
    window.resize(1500, 900)
    window.show()
    spin(app, 0.5)

    print("가상 DUT 연결…")
    window.connect_all()
    wait_for(app, lambda: all(window.session.is_connected(r)
                              for r in ("MLOG", "SHELL", "UCLI")), timeout=10.0)
    for reader in window.session.readers.values():
        reader.reconnect_interval = 0.3

    # 화면에 내용이 차도록 실제 명령을 주고받는다
    panel = window.command_panel
    panel.select_role("SHELL")
    for command in ("otcli state", "otcli childip", "wifi status"):
        panel.edit.setText(command)
        panel.send_current()
        spin(app, 0.4)
    panel.select_role("UCLI")
    panel.edit.setText("help")
    panel.send_current()
    spin(app, 1.6)
    window.insert_marker("T1 사이클 시작")
    spin(app, 1.4)

    capture(window, "monitor")

    # 병합 뷰
    window._apply_layout("merged")
    spin(app, 0.8)
    capture(window, "merged")
    window._apply_layout("split")
    spin(app, 0.4)

    # 명령 패널 — 스크래치패드 펼친 모습
    panel.pad_button.setChecked(True)
    panel.pad_edit.setPlainText(
        "# 자주 쓰는 세트 — `#` 줄은 전송하지 않는다\n"
        "otcli state\n"
        "otcli srp client host\n"
        "wifi status\n")
    spin(app, 0.4)
    capture(panel, "command_panel")
    panel.pad_button.setChecked(False)
    spin(app, 0.3)

    # 설정 모달 — 연결 / 규칙 / 로그
    settings = window.settings()
    settings.resize(1120, 720)
    settings.show()
    settings.go_to(settings.PAGE_CONNECTION)
    spin(app, 0.8)
    capture(settings, "connection")
    settings.go_to(settings.PAGE_RULES)
    spin(app, 0.6)
    capture(settings, "rules")
    settings.go_to(settings.PAGE_LOG)
    spin(app, 0.6)
    capture(settings, "logsetting")
    settings.hide()
    spin(app, 0.4)

    # 필터드뷰
    window.open_filter_view(FilterRule(pattern="CASE", ports=["MLOG"], name="CASE 추적"))
    view = window.filter_views[-1]
    view.resize(1000, 420)
    spin(app, 1.2)
    capture(view, "filterview")
    view.close()
    spin(app, 0.3)

    # 창 분리
    window.pop_out_pane(window.panes["MLOG"])
    spin(app, 1.0)
    popped = window.popped["MLOG"]
    popped.resize(900, 420)
    spin(app, 0.6)
    capture(popped, "popout")
    popped.close()
    spin(app, 0.5)

    # 기록 멈춤 상태 — 상단 바만 잘라 쓴다 (전체 창은 위에서 이미 보여줬다)
    window.toggle_recording_pause()
    spin(app, 0.6)
    capture(window, "paused", crop_height=175)
    window.toggle_recording_pause()
    spin(app, 0.3)

    window.close()
    spin(app, 0.3)
    dut.stop()
    portscan.open_serial = original_open
    portscan.list_ports = original_list
    diag_mod.diag.reconfigure()
    shutil.rmtree(tmp, ignore_errors=True)


# 각 원소 = {"ko": (제목, 본문), "en": (title, body)} — 한/영이 나란히 있어야
# 내용을 고칠 때 한쪽만 고치고 다른 쪽을 잊는 일이 없다.
SECTIONS: list[dict[str, tuple[str, str]]] = []


def section(title_ko: str, body_ko: str, title_en: str, body_en: str) -> None:
    SECTIONS.append({"ko": (title_ko, body_ko), "en": (title_en, body_en)})


PAGE_TEXT = {
    "ko": {"title": "Serial Hub 사용 설명서",
           "subtitle": f"포트 통합 시리얼 모니터 · v{__version__} · {{date}} 기준"},
    "en": {"title": "Serial Hub User Guide",
           "subtitle": f"Unified serial monitor · v{__version__} · as of {{date}}"},
}


def build_html(lang: str) -> str:
    nav = "\n".join(
        f'<li><a href="#s{index}">{html.escape(entry[lang][0])}</a></li>'
        for index, entry in enumerate(SECTIONS))
    blocks = "\n".join(
        f'<section id="s{index}"><h2>{html.escape(entry[lang][0])}</h2>{entry[lang][1]}</section>'
        for index, entry in enumerate(SECTIONS))
    icon = ""
    icon_path = os.path.join(HERE, "assets", "serialhub_64.png")
    if os.path.exists(icon_path):
        with open(icon_path, "rb") as fh:
            icon = ('<img class="logo" src="data:image/png;base64,'
                    + base64.b64encode(fh.read()).decode("ascii") + '" alt="">')
    title = PAGE_TEXT[lang]["title"]
    subtitle = PAGE_TEXT[lang]["subtitle"].format(date=time.strftime("%Y-%m-%d"))
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#F2F4F6; --card:#fff; --line:#E5E8EB; --text:#191F28; --sub:#8B95A1;
         --primary:#3182F6; --ok:#00C471; --warn:#FFB331; --danger:#F04452; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); line-height:1.7;
        font-family:"Pretendard","Malgun Gothic","Segoe UI",sans-serif; }}
header {{ background:var(--card); border-bottom:1px solid var(--line); padding:28px 32px; }}
header h1 {{ margin:0; font-size:26px; display:flex; align-items:center; gap:14px; }}
header p {{ margin:8px 0 0; color:var(--sub); }}
.logo {{ width:44px; height:44px; border-radius:10px; }}
.wrap {{ display:flex; gap:28px; max-width:1180px; margin:0 auto; padding:28px 20px 80px; }}
nav {{ position:sticky; top:20px; align-self:flex-start; width:230px; flex:none;
       background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 8px; }}
nav ol {{ margin:0; padding:0 0 0 22px; font-size:13px; }}
nav li {{ margin:6px 0; }}
nav a {{ color:var(--text); text-decoration:none; }}
nav a:hover {{ color:var(--primary); }}
main {{ flex:1; min-width:0; }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
           padding:22px 26px; margin-bottom:18px; }}
h2 {{ margin:0 0 14px; font-size:20px; border-bottom:2px solid var(--primary);
      padding-bottom:8px; display:inline-block; }}
h3 {{ font-size:15px; margin:22px 0 8px; }}
figure {{ margin:16px 0; }}
figure img {{ width:100%; border:1px solid var(--line); border-radius:10px; display:block; }}
figcaption {{ color:var(--sub); font-size:13px; margin-top:6px; }}
table {{ border-collapse:collapse; width:100%; margin:12px 0; font-size:14px; }}
th,td {{ border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }}
th {{ background:#F7F8F9; color:var(--sub); font-weight:700; }}
code,kbd {{ background:#F2F4F6; border:1px solid var(--line); border-radius:5px;
            padding:1px 6px; font-family:"Cascadia Mono",Consolas,monospace; font-size:13px; }}
kbd {{ box-shadow:0 1px 0 #C7CDD4; }}
pre {{ background:#1F2A37; color:#E5E8EB; padding:14px 16px; border-radius:10px;
       overflow-x:auto; font-family:"Cascadia Mono",Consolas,monospace; font-size:13px; }}
pre code {{ background:none; border:none; color:inherit; padding:0; }}
.note {{ border-left:4px solid var(--primary); background:#F4F8FF; padding:10px 14px;
         border-radius:0 8px 8px 0; margin:14px 0; }}
.warn {{ border-left:4px solid var(--warn); background:#FFF9EC; padding:10px 14px;
         border-radius:0 8px 8px 0; margin:14px 0; }}
.missing {{ color:var(--danger); }}
ul {{ padding-left:22px; }} li {{ margin:5px 0; }}
@media (max-width:900px) {{ .wrap {{ flex-direction:column; }} nav {{ width:auto; position:static; }} }}
</style></head><body>
<header><h1>{icon}{title}</h1>
<p>{subtitle}</p></header>
<div class="wrap"><nav><ol>{nav}</ol></nav><main>{blocks}</main></div>
</body></html>
"""


def compose() -> None:
    section("이 툴이 무엇인가", f"""
<p>대상 장비는 시리얼 콘솔이 3개다 — <b>User CLI</b>, <b>Matter 로그</b>, <b>Matter shell</b>.
지금까지는 VS Code Serial Monitor + Tera Term + MobaXterm 세 툴을 동시에 띄워야 했고,
① 3개를 한 화면에서 못 보고 ② 원하는 값만 걸러 볼 수 없고 ③ 로그를 저장하려면 수신을
멈춰야 했다. Serial Hub 는 이 셋을 하나로 대체한다.</p>
{img('monitor', '메인 화면 — 3개 콘솔을 한 화면에서 본다 (좌 MLOG, 우상 SHELL, 우하 UCLI)')}
<ul>
<li><b>3포트 동시 수신</b> — 포트마다 색·prefix 로 구분, 병합 뷰로 시간순 통합도 가능</li>
<li><b>무중단 저장</b> — 연결하는 순간부터 자동 기록. "저장하려고 멈추는" 동작이 없다</li>
<li><b>필터드뷰</b> — 원하는 패턴만 별도 창으로, 여러 개 동시에</li>
<li><b>명령 전송</b> — 어느 포트로든 명령을 보내고 응답을 같은 화면에서 확인</li>
<li><b>비밀값 마스킹</b> — Wi-Fi PSK·networkkey 는 화면·파일·프로파일에서 자동으로 가려진다</li>
</ul>""",
            "What this tool is", f"""
<p>The target device has three serial consoles — <b>User CLI</b>, <b>Matter log</b> and
<b>Matter shell</b>. Until now that meant running three tools side by side
(VS Code Serial Monitor + Tera Term + MobaXterm), and ① you could not see all three on one
screen, ② you could not filter for just the values you cared about, and ③ saving a log
meant stopping reception. Serial Hub replaces all three.</p>
{img('monitor',
     'Main window — all three consoles on one screen (MLOG left, SHELL top right, UCLI bottom right)')}
<ul>
<li><b>3 ports at once</b> — each port gets its own color and prefix; a merged view can
interleave them in time order</li>
<li><b>Non-stop saving</b> — recording never interrupts reception; there is no
"stop receiving to save" step</li>
<li><b>Filtered views</b> — only the patterns you want, in separate windows, several at once</li>
<li><b>Command sending</b> — send a command to any port and see the reply on the same screen</li>
<li><b>Secret masking</b> — the Wi-Fi PSK and networkkey are hidden automatically in the view,
the files and the profile</li>
</ul>""")

    section("설치와 첫 실행", f"""
<h3>설치</h3>
<p><code>SerialHub_Setup_{__version__}.exe</code> 를 실행한다. Python 을 깔 필요가 없고
<b>관리자 권한도 필요 없다</b>(기본이 사용자 단위 설치).</p>
<p>마법사 단계: 언어 → 안내 → 설치 위치 → 시작 메뉴 → <b>로그 저장 위치</b> →
추가 아이콘 → 요약 → 설치 → 완료.</p>
<p>무설치로 쓰려면 <code>SerialHub_&lt;날짜&gt;.zip</code> 을 풀어 <code>SerialHub.exe</code> 를 실행한다.
설정까지 폴더에 담아 USB 로 들고 다니려면 exe 옆에 빈 <code>portable.txt</code> 를 만든다.</p>
<div class="note"><b>새 PC 에서는 <code>--selfcheck</code> 를 먼저 돌려라.</b>
시작 메뉴의 "설치 상태 점검" 이 같은 일을 한다. 창 모드 프로그램은 콘솔이 없어 문제가
조용히 묻히는데, 이 점검이 COM 포트 열거·화면 라이브러리·저장 경로를 실제로 확인한다.</div>
<h3>화면 구성</h3>
<p>메인 창은 <b>모니터 하나</b>다. 탭이 없다 — 설정은 두 번째 줄의 아이콘으로 들어가는
<b>설정 창(모달)</b> 에 모여 있다.</p>
<table><tr><th>아이콘</th><th>여는 것</th></tr>
<tr><td>🔌 연결</td><td>설정 → 연결 (포트·baud·이름·probe)</td></tr>
<tr><td>⚙ 설정</td><td>설정 창 (마지막으로 본 페이지)</td></tr>
<tr><td>🎨 규칙</td><td>설정 → 규칙 (하이라이트·redact·트리거·저장된 필터)</td></tr>
<tr><td>📁 로그</td><td>설정 → 로그 설정 (폴더·파일명·회전)</td></tr>
<tr><td>💾 프로파일</td><td>설정 → 프로파일 (저장·불러오기)</td></tr>
<tr><td>🔎 필터드뷰</td><td>새 필터드뷰 창 (<kbd>Ctrl</kbd>+<kbd>K</kbd>)</td></tr>
<tr><td>❓ 도움말</td><td>이 문서 (<kbd>F1</kbd>)</td></tr></table>
<h3>처음 연결하기</h3>
<ol>
<li><b>[🔌 연결]</b> 을 누르고, 맨 위 <b>[이 장비의 콘솔 수]</b> 에서 이 모델의 UART
개수(1/2/3)를 고른다.</li>
<li>포트 카드마다 COM 과 baud(기본 115200)를 고른다. COM 목록이 낡았으면 <b>[↻]</b> 로 다시 읽는다.</li>
<li>어느 COM 이 어느 콘솔인지 모르면 <b>[전체 Probe]</b> — 판정 후 매핑을 제안한다.</li>
<li>포트 이름 버튼으로 <b>MLOG / SHELL / UCLI / 포트 번호 / 직접 입력</b> 중에 고른다.
지정하지 않으면 COM 번호가 그대로 이름이 된다.</li>
<li><b>[전체 연결]</b> 을 누르면 설정 창이 닫히고 수신이 시작된다.</li>
<li>파일로 남기려면 <b>[⏺ 로그 시작]</b> 을 누른다 — 저장 위치·파일명을 확인하는 창이 먼저 뜬다.</li>
<li><b>[💾 프로파일]</b> 에서 저장하면 다음부터 그대로 뜬다 (포트 이름·로그명 포함).</li>
</ol>""",
            "Installation and first run", f"""
<h3>Install</h3>
<p>Run <code>SerialHub_Setup_{__version__}.exe</code>. No Python required, and
<b>no administrator rights required</b> (per-user install is the default).</p>
<p>Wizard steps: language → notes → install location → Start Menu → <b>log location</b> →
extra icons → summary → install → finish.</p>
<p>For a no-install setup, unzip <code>SerialHub_&lt;date&gt;.zip</code> and run
<code>SerialHub.exe</code>. To carry the settings along in the folder on a USB stick,
create an empty <code>portable.txt</code> next to the exe.</p>
<div class="note"><b>On a new PC, run <code>--selfcheck</code> first.</b>
The Start Menu entry "installation check" does the same thing. A windowed program has no
console, so problems get buried silently — this check actually exercises COM port
enumeration, the display library and the writable paths.</div>
<h3>Screen layout</h3>
<p>The main window is <b>a single monitor</b>. There are no tabs — settings live in a
<b>modal settings dialog</b> opened from the icons on the second row.</p>
<table><tr><th>Icon</th><th>Opens</th></tr>
<tr><td>🔌 Connect</td><td>Settings → Connection (ports, baud, names, probe)</td></tr>
<tr><td>⚙ Settings</td><td>The settings dialog (last page viewed)</td></tr>
<tr><td>🎨 Rules</td><td>Settings → Rules (highlight, redact, triggers, saved filters)</td></tr>
<tr><td>📁 Log</td><td>Settings → Log (folder, file names, rotation)</td></tr>
<tr><td>💾 Profile</td><td>Settings → Profile (save, load)</td></tr>
<tr><td>🔎 Filtered view</td><td>A new filtered view window (<kbd>Ctrl</kbd>+<kbd>K</kbd>)</td></tr>
<tr><td>❓ Help</td><td>This document (<kbd>F1</kbd>)</td></tr></table>
<h3>Connecting for the first time</h3>
<ol>
<li>Press <b>[🔌 Connect]</b>, then pick the number of UARTs this model has (1/2/3) in
<b>[Consoles on this device]</b> at the top.</li>
<li>Pick the COM port and baud rate (default 115200) on each port card. If the COM list is
stale, refresh it with <b>[↻]</b>.</li>
<li>If you don't know which COM is which console, press <b>[Probe all]</b> — after the
verdict, a mapping is suggested.</li>
<li>Use the name button to pick <b>MLOG / SHELL / UCLI / port number / custom</b>. Without a
name, the COM number is used as-is.</li>
<li>Press <b>[Connect all]</b> — the settings dialog closes and reception starts.</li>
<li>To write files, press <b>[⏺ Start log]</b> — a dialog confirming the location and file
names appears first.</li>
<li>Save with <b>[💾 Profile]</b> and the app opens exactly like this next time (port names
and log names included).</li>
</ol>""")

    section("설정 › 연결 — 포트 지정과 probe", f"""
{img('connection', '설정 > 연결 — 포트 카드 3장 (포트·baud·이름·probe)')}
<h3>probe 가 하는 일</h3>
<p>COM 번호는 벤치마다 다르다(같은 장비인데 COM4=shell 인 벤치도, COM4=log 인 벤치도 있다).
그래서 이 툴은 COM 을 코드에 박아두지 않고, 대신 <b>probe</b> 로 역할을 판정한다.</p>
<div class="note"><b>probe 는 실제 명령을 보내지 않는다.</b> 어느 콘솔에도 존재하지 않는
토큰 1개를 보내고, 각 콘솔이 돌려주는 <i>모르는 명령</i> 응답의 형태로 역할을 가려낸다
(<code>Error &lt;명령&gt;:</code> → Matter shell, <code>Invalid command</code> → User CLI,
무응답 + 자발 트래픽 → 로그 포트). 오배정된 포트에서 엉뚱한 명령이 실행될 위험이 없다.</div>
<p><b>[전체 Probe]</b> 결과가 현재 매핑과 다르면 하단에 제안이 뜨고, <b>[제안 적용]</b> 을
누르면 반영된다(자동으로 바꾸지 않는다). 적용은 연결을 해제한 상태에서만 된다.</p>
<h3>콘솔 수 — UART 가 1개·2개인 모델</h3>
<p>장비마다 시리얼 콘솔 개수가 다르다. 늘 3개를 띄우면 안 쓰는 콘솔이 화면만 차지하므로,
연결 페이지 맨 위에서 <b>이 장비가 쓰는 콘솔 수</b>를 고른다.</p>
<table><tr><th>고른 값</th><th>메인 화면</th></tr>
<tr><td>1개</td><td>콘솔 하나가 창을 꽉 채운다</td></tr>
<tr><td>2개</td><td>좌우 분할</td></tr>
<tr><td>3개</td><td>좌1 + 우2 (기본)</td></tr></table>
<p>앞에서부터가 아닌 조합(예: MLOG + UCLI)이 필요하면 카드의 <b>[이 포트 사용]</b> 체크박스로
직접 고른다. 끈 포트는 화면·상태 필·<b>명령 대상</b>·로그 파일·하단 카운터에서 모두 빠지고
연결도 끊긴다.</p>
<div class="note"><b>설정은 사라지지 않는다.</b> 끈 포트의 COM·baud·이름은 그대로 보관되고,
다시 켜면 그동안 받아둔 스크롤백까지 살아 있다. 이 값은 <b>프로파일에 저장</b>되므로
모델별로 프로파일을 하나씩 만들어두면 열자마자 맞는 개수로 뜬다.</div>
<h3>포트 이름 바꾸기</h3>
<p>카드의 이름 버튼을 누르면 <b>MLOG / SHELL / UCLI / 포트 번호 사용 / 직접 입력…</b> 이 뜬다.
장비가 달라 콘솔 구성이 다르면 원하는 이름을 그대로 쓰면 된다. 이름은 콘솔 제목, 상단 상태 필,
명령 대상 목록, 로그 prefix 에 함께 반영되고 프로파일에 저장된다.</p>
<h3>포트가 안 열릴 때</h3>
<p>COM 은 한 프로그램만 잡을 수 있다. 실패하면 카드에 점유 후보 프로세스를 보여준다 —
Tera Term / VS Code Serial Monitor / 예전 <code>run_*.py</code> 를 닫고 다시 [Connect].</p>""",
            "Settings › Connection — ports and probing", f"""
{img('connection', 'Settings > Connection — three port cards (port, baud, name, probe)')}
<h3>What probing does</h3>
<p>COM numbers differ per bench (the same device can be COM4=shell on one bench and
COM4=log on another). So this tool never hardcodes COM numbers — it identifies the role
with a <b>probe</b> instead.</p>
<div class="note"><b>Probing never sends a real command.</b> It sends one token that exists
on no console and tells the roles apart by the shape of each console's <i>unknown command</i>
reply (<code>Error &lt;command&gt;:</code> → Matter shell, <code>Invalid command</code> →
User CLI, no reply + unsolicited traffic → the log port). There is no risk of a stray
command running on a mis-assigned port.</div>
<p>If the <b>[Probe all]</b> verdict differs from the current mapping, a suggestion appears
at the bottom; press <b>[Apply suggestion]</b> to take it (nothing changes automatically).
Applying requires all ports to be disconnected.</p>
<h3>Console count — models with 1 or 2 UARTs</h3>
<p>Devices differ in how many serial consoles they have. Always showing three would waste
screen space, so pick <b>the number of consoles this device uses</b> at the top of the
Connection page.</p>
<table><tr><th>Choice</th><th>Main window</th></tr>
<tr><td>1</td><td>One console fills the window</td></tr>
<tr><td>2</td><td>Side-by-side split</td></tr>
<tr><td>3</td><td>1 left + 2 right (default)</td></tr></table>
<p>For a combination that isn't "the first N" (e.g. MLOG + UCLI), use the
<b>[Use this port]</b> checkbox on each card. A disabled port disappears from the view,
the status pills, the <b>command targets</b>, the log files and the bottom counters, and
gets disconnected.</p>
<div class="note"><b>Nothing is lost.</b> A disabled port keeps its COM, baud and name, and
re-enabling it even restores the scrollback received so far. The choice is <b>saved in the
profile</b>, so make one profile per model and it opens with the right count immediately.</div>
<h3>Renaming ports</h3>
<p>The name button on each card offers <b>MLOG / SHELL / UCLI / use port number /
custom…</b>. If your device has a different console layout, just type the name you want.
The name shows up in console titles, the status pills, the command target list and the log
prefixes, and is saved in the profile.</p>
<h3>When a port won't open</h3>
<p>A COM port belongs to one program. On failure the card shows candidate holding
processes — close Tera Term / VS Code Serial Monitor / an old <code>run_*.py</code> and
press [Connect] again.</p>""")

    section("로그 저장", f"""
<h3>기록은 눌러야 시작된다</h3>
<div class="note"><b>연결만으로는 파일이 생기지 않는다.</b> <b>[⏺ 로그 시작]</b> 을 누르면
저장 위치·파일명을 확인하는 창이 먼저 뜨고, [기록 시작] 을 눌러야 그때부터 파일에 쌓인다.
이 창은 <b>누를 때마다</b> 뜬다 — 앱을 다시 켰든 설정을 안 만졌든, 이번 기록이 어디에 어떤
이름으로 남는지 매번 눈으로 확인하게 하려는 것이다. <b>[⏹ 로그 중지]</b> 로 언제든 닫는다.</div>
<p>시작하면 포트별 파일과 시간순 병합 파일이 <b>동시에</b> 기록된다.</p>
<pre><code>&lt;로그 폴더&gt;\\&lt;세션&gt;_mlog.log    [2026-08-04 03:19:12.165] &lt;본문&gt;
&lt;로그 폴더&gt;\\&lt;세션&gt;_shell.log
&lt;로그 폴더&gt;\\&lt;세션&gt;_ucli.log
&lt;로그 폴더&gt;\\&lt;세션&gt;_all.log     [03:19:12 + 123.4s] [MLOG] &lt;본문&gt;</code></pre>
<p>기본은 로그 폴더에 바로 저장이고, 설정에서 <b>날짜별(MMDD) 하위 폴더에 저장</b>을 켜면
<code>&lt;로그 폴더&gt;\\&lt;MMDD&gt;\\</code> 아래로 들어간다. 포트별 파일은 기존 Tera Term /
VS Code 저장 로그와, 병합 파일은 기존 <code>run_*.py</code> transcript 와 형식이 같다 —
지금까지 쓰던 grep 이 그대로 먹는다.</p>
<div class="note"><b>같은 이름의 파일이 이미 있으면</b> 시작 전에 물어본다 —
<b>덮어쓰기 / 이어쓰기 / 취소</b> 중 고를 수 있고, 기본 버튼은 안전한 이어쓰기다.</div>
<h3>기록 멈춤 / 재개</h3>
{img('paused', '기록을 멈추면 REC 표시가 노랑으로 바뀐다 — 수신·화면은 계속된다')}
<p><kbd>Ctrl</kbd>+<kbd>P</kbd> 또는 <b>⏸ 기록멈춤</b>. <b>파일 기록만</b> 멈추고 화면·수신은
계속된다. 필요한 구간만 파일에 남기고 싶을 때 쓴다. 멈춘 구간은 각 포트 파일에 이렇게 남는다:</p>
<pre><code>!! 기록 일시정지 — 여기부터 재개 표시까지는 파일에 없다
!! 기록 재개 — 정지 중 1,234줄은 이 파일에 없다</code></pre>
<p>나중에 파일만 열어봐도 시간이 왜 비는지 알 수 있게 하기 위함이다.</p>
<h3>저장 위치·파일 이름 바꾸기</h3>
{img('logsetting', '설정 > 로그 설정 — 폴더·세션 접두어·포트별 로그명·병합 파일명·회전 크기')}
<p><b>[📁 로그]</b> 에서 <b>로그 폴더</b>, <b>세션 접두어</b>, 포트별 <b>로그명</b>,
<b>병합(all) 파일명</b>, <b>세션 접두어 포함</b> 여부, <b>회전 크기</b>를 정한다.
결과 파일명 예시가 입력하는 대로 보인다.</p>
<div class="note"><b>[OK] 을 눌러야 반영된다.</b> 입력하는 즉시 반영하면 글자를 칠 때마다
그 이름의 파일이 하나씩 생긴다. 취소하면 원래 값으로 되돌아간다.</div>
<div class="note"><b>빈 파일을 만들지 않는다.</b> 로그 파일은 그 포트에 <b>첫 줄이 실제로 올 때</b>
만든다. 조용한 포트는 파일 자체가 생기지 않는다. 또 기록 중 <b>2초마다 디스크에 동기화</b>하므로
다른 편집기나 <code>tail</code> 로 열어도 최신 내용이 바로 보인다.</div>
<div class="note"><b>기록 중에 바꿔도 즉시 반영된다.</b> 그 시점에 파일을 닫고 새 위치·새
이름으로 다시 연다. 이미 쓴 파일은 옛 위치에 그대로 둔다(앱이 증적을 옮기지 않는다).
상태줄에 "지금부터 &lt;새 경로&gt;에 기록한다 (이전 파일은 &lt;옛 경로&gt;에 그대로)" 로 알린다.</div>
<h3>파일 관리</h3>
<ul>
<li><b>세션 분절</b> (<kbd>Ctrl</kbd>+<kbd>N</kbd>) — 연결을 유지한 채 지금부터를 새 파일로.
티켓에 작은 파일만 첨부할 때</li>
<li><b>크기 회전</b> — 병합 파일이 200MB 를 넘으면 <code>_p2</code>, <code>_p3</code> … 자동 분절</li>
<li><b>자정 전환</b> — 날짜가 바뀌면 새 날짜의 파일로 넘어간다 (날짜 폴더를 켰으면 새 MMDD
폴더로, 껐으면 파일명에 날짜를 붙여서 — 수신 중단 없음)</li>
<li><b>로그 파일 열기</b> (파일 메뉴) — 기록 중인 파일을 크기와 함께 나열, 여는 순간 flush</li>
<li><b>복사본 저장</b> — 기록을 이어가면서 지금까지를 다른 폴더로 복사 (첨부용)</li>
</ul>
<div class="warn"><b>제어문자 처리</b> — 장치가 보낸 NUL(0x00) 등이 그대로 들어가면 편집기가
파일 전체를 바이너리로 보고 열기를 거부한다. 그래서 <code>&lt;00&gt;</code> 표기로 바꿔 기록한다.
흔적은 남기되 파일은 텍스트로 유지한다.</div>""",
            "Saving logs", f"""
<h3>Recording starts on demand</h3>
<div class="note"><b>Connecting alone creates no files.</b> Press <b>[⏺ Start log]</b> and a
dialog confirming the location and file names appears first; lines go to file only after
you press [Start recording]. The dialog appears <b>every time</b> — whether you restarted
the app or never touched the settings, you always see with your own eyes where this
recording goes and what it is called. Close the files at any time with
<b>[⏹ Stop log]</b>.</div>
<p>Once started, per-port files and a time-ordered merged file are written
<b>simultaneously</b>.</p>
<pre><code>&lt;log folder&gt;\\&lt;session&gt;_mlog.log    [2026-08-04 03:19:12.165] &lt;text&gt;
&lt;log folder&gt;\\&lt;session&gt;_shell.log
&lt;log folder&gt;\\&lt;session&gt;_ucli.log
&lt;log folder&gt;\\&lt;session&gt;_all.log     [03:19:12 + 123.4s] [MLOG] &lt;text&gt;</code></pre>
<p>By default files go directly into the log folder; enable <b>Save into per-date (MMDD)
subfolders</b> in the settings to nest them under <code>&lt;log folder&gt;\\&lt;MMDD&gt;\\</code>.
Per-port files match your existing Tera Term / VS Code saved logs; the merged file
matches the existing <code>run_*.py</code> transcripts — the greps you already use keep
working.</p>
<div class="note"><b>If files with the same name already exist</b>, you are asked before
recording starts — <b>Overwrite / Append / Cancel</b>, with the safe Append as the default
button.</div>
<h3>Pausing / resuming recording</h3>
{img('paused', 'While recording is paused the REC indicator turns yellow — reception and the view continue')}
<p><kbd>Ctrl</kbd>+<kbd>P</kbd> or <b>⏸ Pause</b>. Only <b>file writing</b> stops; the view
and reception continue. Use it to keep only the stretch you need. The paused stretch is
marked in each port file like this:</p>
<pre><code>!! recording paused — nothing between here and the resume marker is in this file
!! recording resumed — 1,234 line(s) during the pause are not in this file</code></pre>
<p>So a gap in the timestamps explains itself when someone opens just the file later.</p>
<h3>Changing the location and file names</h3>
{img('logsetting',
     'Settings > Log — folder, session prefix, per-port log names, merged file name, rotation size')}
<p>Under <b>[📁 Log]</b>, set the <b>log folder</b>, the <b>session prefix</b>, the per-port
<b>log names</b>, the <b>merged (all) file name</b>, whether to <b>include the session
prefix</b>, and the <b>rotation size</b>. A preview of the resulting file names updates as
you type.</p>
<div class="note"><b>Nothing applies until you press [OK].</b> Applying as you type would
create a file for every keystroke. Cancel restores the previous values.</div>
<div class="note"><b>No empty files.</b> A log file is created only when <b>the first line
actually arrives</b> on that port. Quiet ports never produce a file. While recording, the
files are <b>synced to disk every 2 seconds</b>, so other editors and <code>tail</code> see
the latest content immediately.</div>
<div class="note"><b>Changes apply immediately even while recording.</b> The files are
closed at that moment and reopened at the new location with the new names. Files already
written stay where they were (the app never moves evidence). The status line says
"writing to &lt;new path&gt; from now on (earlier files stay in &lt;old path&gt;)".</div>
<h3>File management</h3>
<ul>
<li><b>Session split</b> (<kbd>Ctrl</kbd>+<kbd>N</kbd>) — start a new file from now on while
staying connected. For attaching only a small file to a ticket</li>
<li><b>Size rotation</b> — the merged file splits into <code>_p2</code>, <code>_p3</code> …
past 200 MB</li>
<li><b>Midnight rollover</b> — when the date changes, recording moves on to the new day's
files (into a new MMDD folder when date subfolders are on, otherwise with the new date
appended to the file names — no interruption)</li>
<li><b>Open log file</b> (File menu) — lists the files being written with their sizes,
flushing on open</li>
<li><b>Save a copy</b> — copies everything so far to another folder while recording
continues (for attachments)</li>
</ul>
<div class="warn"><b>Control characters</b> — a raw NUL (0x00) from the device makes editors
treat the whole file as binary and refuse to open it. So it is written as
<code>&lt;00&gt;</code> instead — the trace is kept and the file stays text.</div>""")

    section("보기 — 레이아웃·색·검색", f"""
<h3>레이아웃 4종</h3>
<p><b>보기</b> 메뉴에서 고른다: 좌1+우2(기본) / 3단 가로 / 탭 / <b>병합 뷰</b>.
분할 비율과 창 크기는 프로파일에 저장돼 다음 실행에 복원된다.</p>
{img('merged', '병합 뷰 — 3포트를 시간순으로 한 화면에, prefix 로 출처 구분')}
<h3>펌웨어 로그 색</h3>
<p>장치가 보낸 ANSI 색을 화면에 그대로 살린다(보기 → 펌웨어 로그 색 표시로 끌 수 있음).
<b>로그 파일에는 색 코드가 들어가지 않는다</b> — grep·첨부는 깨끗한 본문 그대로다.</p>
<h3>콘솔 헤더 버튼</h3>
<table><tr><th>버튼</th><th>기능</th></tr>
<tr><td><code>시각</code></td><td>타임스탬프 절대 → 상대 → 끔 (<kbd>Ctrl</kbd>+<kbd>T</kbd>)</td></tr>
<tr><td><code>∅ 빈줄</code></td><td>빈 라인 숨김 — 펌웨어가 뱉는 빈 줄 다발을 걸러낸다</td></tr>
<tr><td><code>⏸</code></td><td>자동 스크롤 정지 (수신·기록은 계속). 새 줄이 오면 "↓ N new"</td></tr>
<tr><td><code>🔍</code></td><td>검색 (<kbd>Ctrl</kbd>+<kbd>F</kbd>), <kbd>F3</kbd> 로 이동.
입력칸을 누르면 <b>최근 검색어</b>가 목록으로 뜨고, 프로그램을 다시 켜도 남는다</td></tr>
<tr><td><code>🗑</code></td><td>이 콘솔 화면만 지우기 — ring·파일은 유지</td></tr>
<tr><td><code>⧉</code></td><td>별도 창으로 분리 (<kbd>Ctrl</kbd>+<kbd>D</kbd>)</td></tr></table>
<h3>창 분리 — 멀티 모니터</h3>
{img('popout', '콘솔을 별도 창으로 빼면 다른 모니터에 크게 띄울 수 있다. 창을 닫으면 원래 자리로 복귀')}""",
            "Viewing — layouts, colors, search", f"""
<h3>Four layouts</h3>
<p>Pick one in the <b>View</b> menu: 1 left + 2 right (default) / 3 columns / tabs /
<b>merged view</b>. Split ratios and the window size are saved in the profile and restored
on the next run.</p>
{img('merged', 'Merged view — all 3 ports in time order on one screen, prefixes tell them apart')}
<h3>Firmware log colors</h3>
<p>ANSI colors sent by the device are rendered on screen as-is (turn off via View → Show
firmware log colors). <b>Color codes never go into the log files</b> — greps and
attachments get clean text.</p>
<h3>Console header buttons</h3>
<table><tr><th>Button</th><th>Function</th></tr>
<tr><td><code>time</code></td><td>Timestamps: absolute → relative → off
(<kbd>Ctrl</kbd>+<kbd>T</kbd>)</td></tr>
<tr><td><code>∅</code></td><td>Hide blank lines — filters the runs of empty lines the
firmware emits</td></tr>
<tr><td><code>⏸</code></td><td>Scroll lock (reception and recording continue). New lines
show as "↓ N new"</td></tr>
<tr><td><code>🔍</code></td><td>Search (<kbd>Ctrl</kbd>+<kbd>F</kbd>), <kbd>F3</kbd> to step.
Click the box to pick from <b>recent search terms</b>, which survive restarts</td></tr>
<tr><td><code>🗑</code></td><td>Clear this console's view only — the ring buffer and files
are kept</td></tr>
<tr><td><code>⧉</code></td><td>Pop out into its own window
(<kbd>Ctrl</kbd>+<kbd>D</kbd>)</td></tr></table>
<h3>Pop-out windows — multiple monitors</h3>
{img('popout',
     'A popped-out console can go full-size on another monitor. Closing the window docks it back')}""")

    section("필터드뷰 — 원하는 것만 보기", f"""
{img('filterview', '필터드뷰 — 매치되는 라인만 모아서 별도 창으로')}
<p><kbd>Ctrl</kbd>+<kbd>K</kbd> 또는 <b>필터</b> 메뉴로 연다. 여러 개를 동시에 띄울 수 있고
창마다 자기 조건을 가진다.</p>
<ul>
<li>기본은 부분일치, <code>.*</code> 를 켜면 정규식. <code>Aa</code> 는 대소문자 구분</li>
<li>대상 포트를 골라 특정 콘솔만 볼 수 있다</li>
<li><b>소급 채움</b> — 이미 받은 라인 중 매치되는 것도 채워준다</li>
<li><b>파일로 저장</b> — 지금 보이는 결과만 텍스트로 (티켓 첨부용)</li>
<li>자주 쓰는 필터는 [설정 → 규칙 → 저장된 필터] 에 두고 원클릭으로 재생성</li>
</ul>""",
            "Filtered views — see only what you need", f"""
{img('filterview', 'A filtered view — only the matching lines, in a separate window')}
<p>Open with <kbd>Ctrl</kbd>+<kbd>K</kbd> or the <b>Filter</b> menu. Several can be open at
once, each window with its own criteria.</p>
<ul>
<li>Substring match by default; turn on <code>.*</code> for regex. <code>Aa</code> matches
case</li>
<li>Pick target ports to watch a specific console only</li>
<li><b>Backfill</b> — also fills in matching lines that arrived earlier</li>
<li><b>Save to file</b> — just the results currently shown, as text (for ticket
attachments)</li>
<li>Keep frequent filters under [Settings → Rules → Saved filters] and recreate them with
one click</li>
</ul>""")

    section("로그 불러오기 — 지난 로그 분석", """
<p><b>파일 › 로그 파일 열기(뷰어)…</b> 로 예전에 기록한 로그 파일을 불러와 분석한다.
포트별 파일·병합 파일 형식은 타임스탬프와 출처를 그대로 복원하고, 모르는 형식의
텍스트 파일도 원문 그대로 열린다.</p>
<ul>
<li>필터드뷰와 같은 검색(부분일치 / 정규식 / 대소문자)과 하이라이트를 그대로 쓴다</li>
<li>여러 파일을 한 번에 열면 <b>시간순으로 병합</b>되고, 파일별 체크박스로 골라 본다</li>
<li>[파일 추가] 로 열린 창에 계속 합칠 수 있고, [결과 저장] 은 보이는 결과만 저장한다</li>
<li>뷰어는 <b>메인 창 하단에 도킹</b>되며, 제목줄을 끌면 독립 창이 된다. 여러 개를 열면
탭으로 묶인다</li>
<li>합계 200MB 를 넘는 묶음은 불러오기 전에 한 번 확인을 받는다</li>
</ul>
<div class="note">파일은 읽기만 하고 잠그지 않으므로, 기록 중인 파일도 열어볼 수 있습니다.</div>""",
            "Opening past logs — the log viewer", """
<p><b>File › Open log files (viewer)…</b> loads previously recorded logs for analysis.
Per-port and merged files come back with their timestamps and sources restored; text
files in unknown formats still open as plain text.</p>
<ul>
<li>The same search tools as filtered views (substring / regex / case) plus highlights</li>
<li>Open several files at once and they are <b>merged in time order</b>, with a checkbox
per source</li>
<li><b>Add files</b> keeps merging into the same window; <b>Save result</b> writes only
what is currently shown</li>
<li>The viewer <b>docks at the bottom of the main window</b>; drag its title bar to float
it as a separate window. Multiple viewers stack as tabs</li>
<li>Batches over 200 MB ask once before loading everything</li>
</ul>
<div class="note">Files are only read, never locked — you can open a file that is still
being recorded.</div>""")

    section("내장 터미널 — PowerShell 을 같은 창에서", """
<p><b>보기 › 터미널 열기</b> — 진짜 터미널(ConPTY)이 메인 창 하단 도크로 열린다.
색·커서 이동·화면 지움까지 그대로라 일반 명령은 물론 대부분의 콘솔 프로그램이 돈다.
제목줄을 끌면 독립 창이 되고, 여러 개를 열 수 있다.</p>
<ul>
<li>기본 셸은 <b>PowerShell</b>, 시작 위치는 사용자 홈 폴더</li>
<li><kbd>Ctrl</kbd>+<kbd>V</kbd> 붙여넣기, <kbd>PageUp</kbd>/<kbd>PageDown</kbd> 스크롤백,
우클릭 메뉴에서 화면 전체 복사·재시작</li>
<li>셸이 종료되면 종료 코드를 배너로 보여주고 [재시작] 으로 새 셸을 연다</li>
<li>도크를 닫으면 셸 프로세스도 함께 끝난다 — 백그라운드에 남지 않는다</li>
</ul>
<div class="warn"><b>관리자 모드</b> — UAC 로 승격된 셸은 보안 경계 때문에 창 안에 넣을 수
없습니다. [관리자 PowerShell (외부 창)] 버튼이 승격된 PowerShell 을 별도 창으로 띄웁니다.</div>
<div class="note">터미널 화면은 시리얼 로그 파일에 기록되지 않습니다 — 시리얼 경로와 완전히
분리돼 있습니다.</div>""",
            "Embedded terminal — PowerShell in the same window", """
<p><b>View › Open terminal</b> — a real terminal (ConPTY) opens as a bottom dock in the
main window. Colors, cursor movement and screen clearing all work, so most console
programs run as-is. Drag the title bar to float it; several can be open at once.</p>
<ul>
<li>The default shell is <b>PowerShell</b>, starting in your home folder</li>
<li><kbd>Ctrl</kbd>+<kbd>V</kbd> pastes, <kbd>PageUp</kbd>/<kbd>PageDown</kbd> scroll
history, and the right-click menu offers copy-whole-screen and restart</li>
<li>When the shell exits, its exit code is shown as a banner and [Restart] opens a fresh
shell</li>
<li>Closing the dock also ends the shell process — nothing lingers in the background</li>
</ul>
<div class="warn"><b>Admin mode</b> — an elevated (UAC) shell cannot be embedded across the
security boundary. The [Admin PowerShell (external window)] button launches an elevated
PowerShell as a separate window.</div>
<div class="note">The terminal screen is never written to the serial log files — it is
fully separate from the serial path.</div>""")

    section("설정 › 규칙 — 하이라이트·마스킹·트리거", f"""
{img('rules', '설정 > 규칙 — 왼쪽 트리로 하이라이트 / redact / 트리거 / 저장된 필터')}
<p>왼쪽 서브트리에서 <b>하이라이트 / redact / 트리거 / 저장된 필터</b> 중 하나를 고른다.
한 화면에 다 쌓지 않아 표가 잘리지 않는다.</p>
<h3>하이라이트 룰</h3>
<p>키워드에 색을 입힌다. <b>색 칸과 키워드 칸이 실제 그 색으로 칠해져</b> 로그에서 어떻게
보일지 바로 알 수 있다. 라이브 스트림에 즉시 반영된다.</p>
<h3>redact 룰 — 비밀값 마스킹</h3>
<p><code>wifi connect &lt;ssid&gt; &lt;psk&gt;</code> 의 PSK, Thread <code>networkkey</code>,
<code>pskc</code> 는 기본 룰로 가려진다. 키워드가 라인 경계로 잘려도 잡히도록
<b>32자 이상 연속 hex</b> 도 형태만으로 마스킹한다.</p>
<div class="note"><b>마스킹은 화면·로그 파일·프로파일 JSON 공통이고, 시리얼로 나가는 것만
원문이다.</b> 프로파일은 벤치 간 복사·공유용이라 명령 히스토리와 스크래치패드도 저장 시
마스킹된다. 로그를 티켓에 그대로 첨부해도 비밀값이 새지 않는다.</div>
<div class="warn">한계 — redact 는 저장되는 라인 단위로 적용된다. 값이 라인 경계로 쪼개지는
드문 경우엔 앞조각이 이미 기록됐을 수 있다. 외부에 첨부하기 전 <code>wifi connect</code>
근처를 한 번 훑어라.</div>
<h3>트리거 — 밤샘 수집용 집계</h3>
<p><code>WDOG</code> / <code>MemManage</code> / <code>HardFault</code> 가 기본 감시 대상이다.
발생 <b>횟수와 최근 시각</b>을 상단 <b>⚡</b> 칩에 집계한다 — 새벽에 지나간 이벤트를
아침에 확인할 수 있다. 하이라이트(눈에 띄게)와 다른 '세는' 채널이다.</p>""",
            "Settings › Rules — highlighting, masking, triggers", f"""
{img('rules', 'Settings > Rules — the tree on the left: highlight / redact / triggers / saved filters')}
<p>Pick one of <b>highlight / redact / triggers / saved filters</b> in the subtree on the
left. Not piling everything onto one page keeps the tables from getting cut off.</p>
<h3>Highlight rules</h3>
<p>Colors keywords. <b>The color cell and the keyword cell are painted in the actual
color</b>, so you see immediately how it will look in the log. Applies to the live stream
at once.</p>
<h3>redact rules — masking secrets</h3>
<p>The PSK in <code>wifi connect &lt;ssid&gt; &lt;psk&gt;</code>, Thread
<code>networkkey</code> and <code>pskc</code> are masked by the default rules. To catch
keys even when the keyword is cut off at a line boundary, <b>runs of 32+ hex
characters</b> are masked purely by shape too.</p>
<div class="note"><b>Masking applies to the view, the log files and the profile JSON alike;
only what goes out over the serial line is unmasked.</b> Profiles are meant to be copied
and shared between benches, so command history and the scratchpad are masked on save as
well. Attach a log to a ticket as-is and no secret leaks.</div>
<div class="warn">Limitation — redact is applied per stored line. In the rare case where a
value is split across a line boundary, the first fragment may already be on disk. Skim
around <code>wifi connect</code> before attaching a log externally.</div>
<h3>Triggers — tallies for overnight captures</h3>
<p><code>WDOG</code> / <code>MemManage</code> / <code>HardFault</code> are watched by
default. The <b>hit count and last-seen time</b> are tallied into the <b>⚡</b> chip at the
top — so you can check in the morning what flew by at 3 AM. A 'counting' channel, separate
from highlighting (which makes lines stand out).</p>""")

    section("명령 보내기", f"""
{img('command_panel', '명령 패널 — 퀵 입력 + 스크래치패드')}
<ul>
<li>대상 포트를 고르고 입력 후 <kbd>Enter</kbd>. <kbd>↑</kbd><kbd>↓</kbd> 로 히스토리
(포트별로 따로 기억하고, <b>프로그램을 다시 켜도 남는다</b>)</li>
<li><b>대상은 연결된 모든 포트</b>다. 장비마다 어느 콘솔이 입력을 받는지 다르므로
로그 전용으로 보이는 포트도 막지 않는다 (probe 를 보낼 수 있으면 명령도 보낼 수 있다)</li>
<li>보낸 명령은 콘솔에 <code>&gt;&gt;&gt;</code> 로 에코된다</li>
<li><b>스크래치패드</b> — 자주 쓰는 명령 세트를 파일처럼 편집·보관.
<kbd>Ctrl</kbd>+<kbd>Enter</kbd> 로 현재 줄만, [전체 순차 전송] 으로 위에서부터 차례로
(<kbd>Esc</kbd> 중단). <code>#</code> 로 시작하는 줄은 주석이다</li>
<li><b>대상 포트 오지정 힌트</b> — 보낸 명령을 그 콘솔이 모른다고 답하면 "대상 포트 확인"
경고가 뜬다 (SHELL 명령을 UCLI 로 보내는 실수를 즉시 알려준다)</li>
</ul>""",
            "Sending commands", f"""
{img('command_panel', 'The command panel — quick input + scratchpad')}
<ul>
<li>Pick the target port, type, press <kbd>Enter</kbd>. <kbd>↑</kbd><kbd>↓</kbd> walks the
history (kept per port, and <b>it survives restarts</b>)</li>
<li><b>Every connected port is a valid target.</b> Which console takes input differs per
device, so even ports that look log-only are not blocked (if a probe can be sent, a
command can too)</li>
<li>Sent commands are echoed into the console as <code>&gt;&gt;&gt;</code></li>
<li><b>Scratchpad</b> — edit and keep your frequent command sets like a file.
<kbd>Ctrl</kbd>+<kbd>Enter</kbd> sends the current line only; [Send all in order] sends
from the top (<kbd>Esc</kbd> stops). Lines starting with <code>#</code> are comments</li>
<li><b>Wrong-target hint</b> — if the console replies that it does not know the command you
sent, a "check the target port" warning appears (catches sending a SHELL command to UCLI
immediately)</li>
</ul>""")

    section("언어 — 한국어 / English", """
<p>기본은 English 다. <b>[설정 → 일반]</b> 에서 한국어로 바꿀 수 있다.</p>
<ul>
<li>언어는 프로파일이 아니라 <b>사람 설정</b>이라, 프로파일을 바꿔도 따라온다</li>
<li><b>다음에 프로그램을 켤 때부터</b> 적용된다</li>
<li>번역이 없는 문구는 한국어로 나온다 (빈 화면이 되지 않게)</li>
</ul>""",
            "Language — 한국어 / English", """
<p>The default is English. You can switch to 한국어 (Korean) in
<b>[Settings → General]</b>.</p>
<ul>
<li>The language is a <b>per-person setting</b>, not a profile setting — it follows you
across profiles</li>
<li>It takes effect <b>the next time you start the program</b></li>
<li>Text without a translation is shown in Korean (never a blank screen)</li>
</ul>""")

    section("자동화 브리지 — 스크립트 연동", """
<p>COM 은 한 프로그램만 잡는다. Serial Hub 를 켜두면 <code>serport.py</code>,
<code>run_*.py</code>, <code>otcli_dut.py</code> 같은 기존 자동화가 포트를 못 연다.
그래서 Serial Hub 가 <code>127.0.0.1:3341</code> 에 창구를 열어둔다 —
스크립트는 포트 대신 Serial Hub 를 거친다.</p>
<pre><code>from serial_hub.hub_client import HubClient

with HubClient() as hub:
    print(hub.status()["roles"])              # {'MLOG': 'connected', ...}
    print(hub.command("SHELL", "otcli state"))  # ['&gt; otcli state', 'leader', 'Done']
    hub.marker("### T1 cycle 3 start")         # 로그에 구분선 삽입</code></pre>
<p>CLI 로도 쓸 수 있다:</p>
<pre><code>python hub_client.py status
python hub_client.py send SHELL "otcli state"
python hub_client.py marker "### T1 시작"
python hub_client.py tail MLOG</code></pre>
<p>포트는 프로파일의 <code>bridge_port</code> 로 바꾸거나 <code>0</code> 으로 끌 수 있다.
127.0.0.1 에만 열리므로 외부에서는 접근할 수 없다.</p>""",
            "Automation bridge — script integration", """
<p>A COM port belongs to one program. With Serial Hub running, existing automation like
<code>serport.py</code>, <code>run_*.py</code> or <code>otcli_dut.py</code> cannot open the
ports. So Serial Hub opens a service window on <code>127.0.0.1:3341</code> — scripts go
through Serial Hub instead of the port.</p>
<pre><code>from serial_hub.hub_client import HubClient

with HubClient() as hub:
    print(hub.status()["roles"])              # {'MLOG': 'connected', ...}
    print(hub.command("SHELL", "otcli state"))  # ['&gt; otcli state', 'leader', 'Done']
    hub.marker("### T1 cycle 3 start")         # insert a separator into the log</code></pre>
<p>There is a CLI too:</p>
<pre><code>python hub_client.py status
python hub_client.py send SHELL "otcli state"
python hub_client.py marker "### T1 start"
python hub_client.py tail MLOG</code></pre>
<p>Change the port via the profile's <code>bridge_port</code>, or set <code>0</code> to turn
it off. It listens on 127.0.0.1 only, so it is unreachable from outside.</p>""")

    section("문제가 생기면", """
<h3>진단 로그</h3>
<p>앱은 자기 동작(연결/재접속/probe 판정/기록 실패/예외)을 <code>app.log</code> 에 남긴다
(1MB×3 회전). <b>도움말 → 진단 폴더 열기</b> 로 폴더를 열어 <code>app.log</code> 와
<code>crash.log</code> 를 그대로 전달하면 사후 분석이 된다.</p>
<h3>자주 겪는 것</h3>
<table>
<tr><th>증상</th><th>원인·조치</th></tr>
<tr><td>포트가 안 열린다</td><td>다른 프로그램이 COM 을 잡고 있다. 카드에 뜨는 점유 후보를
닫고 다시 [Connect]</td></tr>
<tr><td>로그 파일이 편집기에서 안 열린다</td><td>구버전에서 만든 파일에 NUL 이 들어간 경우다.
현재 버전은 <code>&lt;00&gt;</code> 으로 바꿔 기록한다</td></tr>
<tr><td>로그가 옛 위치에 쌓인다</td><td>구버전 문제. 현재 버전은 폴더를 바꾸면 기록 중에도
즉시 새 위치로 옮겨간다</td></tr>
<tr><td>probe 가 "미확정" 이라고 한다</td><td>펌웨어의 응답 문구가 바뀌었을 수 있다.
프로파일의 probe 패턴을 확인하라 (재빌드 없이 고칠 수 있다)</td></tr>
<tr><td>화면에 "⋯ N줄 생략" 이 뜬다</td><td>화면 갱신이 수신을 못 따라간 구간이다.
<b>로그 파일에는 다 있다</b></td></tr>
</table>
<h3>저장 위치</h3>
<table>
<tr><th>무엇</th><th>어디</th></tr>
<tr><td>설정·프로파일·app.log</td><td><code>%LOCALAPPDATA%\\SerialHub</code>
(포터블 모드면 exe 옆)</td></tr>
<tr><td>수집한 로그</td><td>설치할 때 고른 폴더 ([설정 → 로그 설정] 에서 변경 가능)</td></tr>
</table>""",
            "Troubleshooting", """
<h3>Diagnostic log</h3>
<p>The app records its own behavior (connects/reconnects/probe verdicts/write
failures/exceptions) in <code>app.log</code> (1 MB × 3 rotation). Open the folder with
<b>Help → Open diagnostics folder</b> and hand over <code>app.log</code> and
<code>crash.log</code> as-is for post-mortem analysis.</p>
<h3>Common issues</h3>
<table>
<tr><th>Symptom</th><th>Cause / action</th></tr>
<tr><td>A port won't open</td><td>Another program is holding the COM port. Close the
candidate holders shown on the card and press [Connect] again</td></tr>
<tr><td>A log file won't open in an editor</td><td>A file made by an old version contains a
raw NUL. The current version writes it as <code>&lt;00&gt;</code></td></tr>
<tr><td>Logs pile up in the old location</td><td>An old-version problem. The current version
switches to the new folder immediately, even mid-recording</td></tr>
<tr><td>Probe says "undetermined"</td><td>The firmware's reply wording may have changed.
Check the probe patterns in the profile (fixable without a rebuild)</td></tr>
<tr><td>The view shows "⋯ N lines omitted"</td><td>The display fell behind reception for a
stretch. <b>The log files have everything</b></td></tr>
</table>
<h3>Where things are stored</h3>
<table>
<tr><th>What</th><th>Where</th></tr>
<tr><td>Settings, profiles, app.log</td><td><code>%LOCALAPPDATA%\\SerialHub</code>
(next to the exe in portable mode)</td></tr>
<tr><td>Captured logs</td><td>The folder chosen at install time (changeable in
[Settings → Log])</td></tr>
</table>""")

    section("단축키", """
<table><tr><th>키</th><th>기능</th></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>F</kbd> / <kbd>F3</kbd></td><td>검색 / 다음 매치</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>K</kbd></td><td>새 필터드뷰</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></td><td>콘솔 포커스</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>`</kbd></td><td>명령 입력창</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>Tab</kbd></td><td>명령 대상 포트 전환</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>T</kbd></td><td>타임스탬프 모드</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>Space</kbd></td><td>자동 스크롤 정지 / 해제</td></tr>
<tr><td><kbd>Enter</kbd></td><td>(콘솔에서) 자동 스크롤 해제 — 맨 아래로 복귀</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>L</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>L</kbd></td>
<td>화면 지우기 / 전체 + 버퍼</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>M</kbd></td><td>마커 삽입</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>N</kbd></td><td>새 로그 파일로 분절</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>R</kbd></td><td>로그 기록 시작 / 중지</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>P</kbd></td><td>기록 멈춤 / 재개</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>D</kbd></td><td>콘솔 창 분리 / 복귀</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>=</kbd> <kbd>-</kbd> <kbd>0</kbd></td><td>글자 크기</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>S</kbd></td><td>프로파일 저장</td></tr>
<tr><td><kbd>F1</kbd></td><td>이 사용 설명서</td></tr></table>
<p style="margin-top:22px;color:#8b95a1;font-size:13px">Serial Hub · Copyright © psy-bari</p>""",
            "Keyboard shortcuts", """
<table><tr><th>Key</th><th>Function</th></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>F</kbd> / <kbd>F3</kbd></td><td>Search / next match</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>K</kbd></td><td>New filtered view</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></td><td>Focus console</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>`</kbd></td><td>Command input</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>Tab</kbd></td><td>Cycle command target port</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>T</kbd></td><td>Timestamp mode</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>Space</kbd></td><td>Scroll lock on / off</td></tr>
<tr><td><kbd>Enter</kbd></td><td>(in a console) release scroll lock — jump to the
bottom</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>L</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>L</kbd></td>
<td>Clear view / all views + buffer</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>M</kbd></td><td>Insert marker</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>N</kbd></td><td>Split into a new log file</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>R</kbd></td><td>Start / stop log recording</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>P</kbd></td><td>Pause / resume recording</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>D</kbd></td><td>Pop console out / dock back</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>=</kbd> <kbd>-</kbd> <kbd>0</kbd></td><td>Text size</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>S</kbd></td><td>Save profile</td></tr>
<tr><td><kbd>F1</kbd></td><td>This user guide</td></tr></table>
<p style="margin-top:22px;color:#8b95a1;font-size:13px">Serial Hub · Copyright © psy-bari</p>""")


def main() -> int:
    os.makedirs(DOCS, exist_ok=True)
    print("UI 캡처 중 (가상 DUT)…")
    build_screens()
    compose()
    for lang, out in (("ko", OUT_KO), ("en", OUT_EN)):
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(build_html(lang))
        size = os.path.getsize(out) / 1024
        print(f"생성: {out}  ({size:,.0f} KB, 이미지 {len(SHOTS)}장 내장)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
