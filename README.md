[English](README.md) | [한국어](README.ko.md)

# Serial Hub — unified serial monitor

Replaces three tools — VS Code Serial Monitor + Tera Term + MobaXterm — with one.
See all 3 consoles (User CLI / Matter log / Matter shell) on a single screen, watch
just the values you care about in filtered views, and keep saving logs **without
ever stopping reception**. Reopen past log files in a viewer for analysis, and use
a PowerShell terminal inside the same window.

## Installation (recommended)

Run `dist/SerialHub_Setup_1.3.0.exe` to start the setup wizard. No Python required,
and **no administrator rights required** (per-user install is the default).

Wizard steps: language → notes → install location → Start Menu → **log location** →
extra icons → summary → install → finish (with optional install check and launch).

- You pick the log location during installation. The default is `logs` under the
  install folder; you can change it later in [Settings → Log] inside the program.
- Settings and profiles live in `%LOCALAPPDATA%\SerialHub`, following Windows
  conventions.
- Uninstall from [Settings → Apps] or the Start Menu entry "Uninstall Serial Hub".
  The uninstaller asks whether to keep your settings, and **never deletes captured
  logs** (they are test evidence).

Unattended deployment:

```
SerialHub_Setup_1.3.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="D:\Tools\SerialHub"
unins000.exe /VERYSILENT /SUPPRESSMSGBOXES          # uninstall (settings are kept)
```

## Portable use (no install)

Unzip `dist/SerialHub_<date>.zip` and run `SerialHub.exe`. To keep the settings in
the folder and carry it around on a USB stick, create an empty `portable.txt` file
next to the exe.

```
SerialHub.exe                 # start with the last-used profile
SerialHub.exe --demo          # preview the UI without ports (synthetic logs)
SerialHub.exe --selfcheck     # check that this build is usable
SerialHub.exe --where         # show where settings are stored
```

Profiles, settings and `crash.log` accumulate **next to the exe** (if that location
is write-protected, the app automatically falls back to `%LOCALAPPDATA%\SerialHub`).
Copy the whole folder and the settings travel with it.

**On a new PC, run `--selfcheck` first.** A windowed exe has no console, so problems
get buried silently — this command actually exercises pyserial COM enumeration, Qt
and the writable paths, and leaves the results in `selfcheck.txt`. Unexpected errors
are recorded in `crash.log`.

### Rebuilding

```bash
python -m pip install pyinstaller
winget install --id JRSoftware.InnoSetup            # only needed to build the installer

python build_exe.py --zip        # folder-style exe + portable zip
python build_installer.py        # installer (builds the exe first if missing)
python build_exe.py --onefile    # single exe (~10 s startup, not recommended)
```

The setup wizard is configured in [installer.iss](installer.iss); the pre-install
notes live in [installer_info.txt](installer_info.txt).

To change the icon, edit the artwork in [make_icon.py](make_icon.py) and run it
again — it generates both `assets/serialhub.ico` (exe and installer) and
`ui/appicon.py` (window and taskbar). The 16 px size has its own artwork so it does
not smear in the taskbar.

The folder-style build is the default because of startup speed — onefile unpacks
112 MB into a temp folder on every launch. For a tool you use every day, that delay
matters.

## Running from source

The folder name is the package name, so you must clone it **as `serial_hub`**
(the default folder name `serial-hub-monitor` is not a valid Python package name):

```bash
git clone https://github.com/bari-psy77/serial-hub-monitor.git serial_hub
cd serial_hub
python -m pip install -r requirements.txt   # PySide6, pyserial, pyte, pywinpty
python app.py                 # start with the last-used profile
python app.py --profile bench-A
python app.py --demo          # preview the UI without ports (synthetic logs)
```

Run it on the PC that has the serial ports attached (the wireless Windows PC).
`--demo` is for exploring the layout, filters and highlighting without a DUT;
every line is tagged `[DEMO]`.

## First-use walkthrough

1. **[🔌 Connect]** in the toolbar — the Connection page of the settings dialog
   opens. First pick the number of UARTs this model has (1/2/3) in
   **[Consoles on this device]** at the top. Then pick the COM port and baud rate
   (default 115200) on each port card. COM numbers are not hardcoded anywhere
   (they differ per bench). Press `[↻]` to refresh the list.
2. If you don't know which COM is which console, use **[Probe]** or **[Probe all]**.
   Probing never sends a real command — it sends one token that exists on no console
   and identifies the role from the unknown-command reply signature, so there is no
   risk of a real command like `swtimer ... set` running on a mis-assigned port.
3. Set port names via the name button on each card: `MLOG`/`SHELL`/`UCLI`/custom.
   If you don't set one, the COM number is used as-is (`COM4`). The name appears in
   console titles, status pills and log prefixes, and is saved in the profile.
4. Press **[Connect all]** — the settings dialog closes and reception starts.
5. To write files, press **[⏺ Start log]** — a dialog confirming the location and
   file names appears first.
6. Save with **[💾 Profile]** and the app starts exactly like this next time.

## The screen

The main window is **a single monitor**. Everything else lives behind the icon
buttons on the second row and the settings modal.

| Area | Contents |
|---|---|
| Main | Status pills + split consoles (1 left + 2 right by default) + command panel |
| Action bar | 🔌 Connect · ⚙ Settings · 🎨 Rules · 📁 Log · 💾 Profile · 🔎 Filtered view · ❓ Help |
| Settings (modal) | Connection / Rules / Log / Profile — navigate via the list on the left |

Pages in the settings dialog:

| Page | Contents |
|---|---|
| Connection | Console count (1/2/3) · port cards (COM · baud · name · Connect/↻/Probe) |
| Rules | Subtree on the left — highlight / redact / triggers / saved filters |
| Log | Folder · session prefix · per-port log names · merged (all) file name · rotation size (**takes effect on [OK]**) |
| Profile | Saved profile list · save / save as / load |
| General | Display language (한국어 / English) |

Main shortcuts: `Ctrl+F` search, `F3`/`Shift+F3` next/previous match, `Ctrl+K` new
filtered view, `Ctrl+1/2/3` focus console, `` Ctrl+` `` command input, `Ctrl+Tab`
cycle target port, `Ctrl+T` timestamp mode, `Ctrl+Space` (or `Enter`) release
scroll lock, `Ctrl+L` clear view, `Ctrl+S` save profile, `F1` user guide.

## Console count — models with 1 or 2 UARTs

Devices differ in how many serial consoles they have. Always showing three would
waste screen space on unused consoles, so pick the number this device actually uses
at the top of **[Settings → Connection]**.

- **1** → one console fills the window. **2** → side-by-side split. **3** → 1 left + 2 right (default).
- For combinations that aren't "the first N" (e.g. MLOG + UCLI), use the
  **[Use this port]** checkbox on each card.
- A disabled port disappears from the view, status pills, **command targets**, log
  files and the bottom counters, and gets disconnected. Its COM, baud and name are
  kept, so re-enabling restores it (the scrollback is still there too).
- **Saved in the profile** — make one profile per model and it opens with the right
  count immediately. (e.g. `thermostat` (3), `sensor` (1))

## Log files

Logs go to **the folder you chose at install time** (default = `logs` under the
install folder); you can change it any time in [Settings → Log]. By default files
are written directly into that folder; turn on "Save into per-date (MMDD)
subfolders" to nest them by date.

- **Manual start**: connecting alone creates no files. Recording starts only when
  you press **[⏺ Start log]**, and every press first shows **a dialog confirming
  where this recording goes and what it is called** (every time, even after a
  restart). This prevents evidence from piling up somewhere you didn't know about.
  Once started, it keeps writing without stopping reception — there is no
  "stop receiving to save" step.
- **[⏹ Stop log]** closes the files at any time. What was already written stays.
- **If files with the same name already exist**, you are asked before recording
  starts — **Overwrite / Append / Cancel**, with the safe Append as the default
  button (the automation bridge path keeps appending without asking).
- **Pause / resume recording** (`⏸ Pause` or Ctrl+P): stops file writing only —
  the view and reception continue. Use it to keep only the stretches you need.
  The paused stretch is marked in each port file with
  `!! recording paused …` / `!! recording resumed — N line(s) during the pause are
  not in this file`, so a gap in the timestamps explains itself when you open the
  file later.
- **File naming**: in [Settings → Log], set the per-port log names (empty =
  `mlog`/`shell`/`ucli`), the merged file name and "include session prefix" on one
  page — turn the prefix off to keep appending to a fixed name like `matter.log`.
  A live preview shows the resulting names, and **nothing applies until you press
  [OK]** (applying as you type would create an empty file per keystroke).
- **No empty files**: a log file is created only when **the first line actually
  arrives** on that port. Quiet ports never produce a file.
- **Disk sync every 2 seconds**: while recording, other editors and `tail` see the
  latest content immediately (previously the file could look like 0 bytes until
  opened in Notepad).
- **Open log file** (File → Open log file): lists the files currently being written
  with their sizes, and flushes on open so the last line is included.
- **Save a copy** (File → Save a copy of the log so far): copies everything so far
  to another folder while recording continues. For ticket attachments.

```
<log folder>\<session>_mlog.log     [2026-08-02 01:19:12.165] <text>
<log folder>\<session>_shell.log
<log folder>\<session>_ucli.log
<log folder>\<session>_all.log      [01:19:12 +  123.4s] [MLOG] <text>
```

(With the date-subfolder option on, they go under `<log folder>\<MMDD>\` instead.)

Per-port files match the format of your existing Tera Term / VS Code saved logs;
the merged file matches the existing `run_*.py` transcripts — your existing greps
keep working. Control characters sent by the device (NUL etc.) are written as
`<00>` — a single one is enough to make editors treat the whole file as binary and
refuse to open it (the trace is preserved). Writing happens on the receive thread
with a flush per line, so logs survive a frozen GUI or a force-kill. Past midnight,
recording moves on to the new day's files automatically (a new MMDD folder when
date subfolders are on, otherwise the new date is appended to the file names).

## Opening past logs (viewer)

**File → Open log files (viewer)…** reopens previous logs for analysis. Per-port
and merged files come back with timestamps and sources restored; unknown text
formats still open as plain text. You get the same search tools as filtered views
(substring/regex/case), highlights and save-result. Opening several files merges
them in time order with a checkbox per source. The viewer docks at the bottom of
the main window; drag its title bar to float it — multiple viewers stack as tabs.
Files are only read, never locked, so you can open a file that is still being
recorded.

## Embedded terminal (PowerShell)

**View → Open terminal** — a real ConPTY terminal opens as a bottom dock (colors,
cursor movement and screen clearing all work; pywinpty + pyte). The default shell
is PowerShell starting in your home folder. The mouse wheel, the scrollbar on the
right and `PageUp`/`PageDown` walk back through past output; typing snaps back to
the bottom. `Ctrl+V` pastes, and the right-click menu offers copy-whole-screen and
restart. Several terminals are tabbed together at the bottom. Closing the dock
also ends the shell process. **Admin mode**: an elevated (UAC)
shell cannot be embedded, so the [Admin PowerShell (external window)] button
launches an elevated window separately. The terminal screen is never written to
the serial log files.

## Language (한국어 / English)

The default is English. You can switch to 한국어 (Korean) in **[Settings → General]**;
this is a per-person setting, not a profile setting, so it lives in
`%LOCALAPPDATA%\SerialHub\settings.json` (it follows you across profiles).
It **takes effect on the next start**, and any text without a translation falls
back to Korean.

The translation table is a single file: [core/i18n_en.py](core/i18n_en.py). If you
add a new string and forget the table, the "no missing English translations" check
in `selftest.py` catches it (it also compares `{0}` placeholder counts).

## redact

The PSK in `wifi connect <ssid> <psk>`, Thread `networkkey` and `pskc` are masked
by the default rules. **Masking applies to the view, the log files and the profile
JSON alike; only what goes out over the serial line is unmasked.** Profiles are
meant to be copied and shared between benches, so command history and the
scratchpad are masked on save too. Edit the rules in [Settings → Rules → redact];
turn regex off to match literally (for passwords containing regex metacharacters).
A rule with a broken regex raises a warning in the status bar — silently disabling
it would let plaintext through to the files.

**Limitation**: redact is applied per stored line. If a secret is split across a
line boundary (the first partial line right after connecting, a partial flush of a
prompt with no newline), the rule cannot match. Buffering lines would break
"write immediately", so this is an accepted trade-off — skim around `wifi connect`
before attaching a log externally.

## Bench conveniences

- **Markers** (`📍` button / Ctrl+M): inserts a `### …` separator line into the log —
  to mark "reproduction starts here" in a Jira attachment. Written to the merged
  file and `_mark.log`.
- **Session split** (File → Ctrl+N): starts a new log file from now on while
  staying connected — attach only a small file to the ticket.
- **Triggers** ([Settings → Rules → Triggers]): `WDOG`/`MemManage`/`HardFault`
  watched by default. Hit counts and the last-seen time are tallied in the
  monitor's `⚡` chip — for spotting events that flew by at 3 AM during an
  overnight capture.
- **Size rotation**: the merged file splits into `_p2`, `_p3` … past 200 MB
  (separate from the midnight date-folder rollover).
- **Zoom / word wrap**: Ctrl+= / Ctrl+- / Ctrl+0, View → Word wrap.
- **Firmware log colors**: ANSI colors sent by the device are rendered on screen
  (toggle via View → Show firmware log colors). **Color codes never go into the
  log files** — grep and Jira attachments get clean text. Redacted lines drop their
  colors because masking shifts character positions.
- **Clearing buffers**: `🗑` in a console header = that console's view only;
  `🗑 Buffer` at the top = every console view + the memory buffer (Ctrl+Shift+L).
  **Neither touches the log files.**
- **Pop-out windows**: `⧉` in a console header (or Ctrl+D) moves a console into its
  own window — e.g. MLOG enlarged on a second monitor. Closing the window docks it
  back (View → Dock all popped-out windows).

## Automation bridge (external scripts)

A COM port belongs to one program — while the hub is running, `serport.py` /
`run_*.py` cannot open the ports. So the hub listens on `127.0.0.1:3341`
(JSON Lines; change via the profile's `bridge_port`, 0 = off). External scripts go
through the hub instead of the port:

```python
from serial_hub.hub_client import HubClient
with HubClient() as hub:
    print(hub.command("SHELL", "otcli state"))   # ['> otcli state', 'leader', 'Done']
    hub.marker("### T1 cycle 3 start")
```

CLI: `python hub_client.py status | send SHELL "otcli state" | marker "..." | tail MLOG`

## When something goes wrong (diagnostics)

The app records its own behavior in `app.log` (connects/reconnects/probe verdicts/
write failures/exceptions, 1 MB × 3 rotation). Open the folder via
**Help → Open diagnostics folder** and hand over `app.log` + `crash.log` as-is for
post-mortem analysis.

## When a port won't open

A COM port belongs to one program. When opening fails, the port card in
Settings → Connection shows candidate holding processes (a heuristic — this
environment has no `handle.exe`). Close Tera Term / VS Code Serial Monitor / an
old `run_*.py` and press [Connect] again.

## Self-test

```bash
python selftest.py          # core (no hardware needed)
python selftest.py --gui    # includes offscreen Qt
```

Verifies line assembly, partial lines, auto-reconnect, sending, redact, probe
verdicts, profile round-trips, filtered views and a 20k-line load — all against a
fake serial port. On-device verification (design doc §8, items 2–6) is not replaced
by this script.

## CI

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on pushes to `main`
and on pull requests targeting `main` — ubuntu-latest, Python 3.12, no scheduled runs. It installs
`requirements.txt` plus the Qt runtime libraries the wheels expect (`libegl1`, `libgl1`,
`libxkbcommon0`, `libdbus-1-3`, `libfontconfig1`), then runs both halves of the self-test:
`python selftest.py` and `python selftest.py --gui` with `QT_QPA_PLATFORM=offscreen`.

The workflow checks the repository out into a folder named `serial_hub` on purpose: `selftest.py`
imports relatively via `__package__ = "serial_hub"`, so the checkout folder name *is* the package
name. `uitest.py` is not in CI — it has not been verified under Linux/offscreen.

## Layout

```
core/          The Qt-free layer — logstore (ring+files) · port (receive thread) · filters ·
               config (profiles) · portscan (enumeration/holders/probe) · session (orchestrator)
ui/            PySide6 display layer — a single 50 ms QTimer pumps every view
               main_window (monitor+action bar) · settings_dialog (connection/rules/log/profile modal)
app.py         Entry point (for running from source)
launcher.py    PyInstaller entry point — freezing app.py directly breaks relative imports
               and drops the package from the bundle
build_exe.py   Executable build
selftest.py    Hardware-free verification (core)
uitest.py      Automated GUI scenarios against a virtual 3-console DUT
```
