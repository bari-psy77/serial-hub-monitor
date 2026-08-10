"""영어 문구표. 키 = 소스에 적힌 한국어 문장 그대로.

여기에 없는 키는 한국어가 그대로 나온다 (번역 누락이 빈 화면으로 이어지지 않게).
새 문구를 추가하면 `python -m serial_hub.selftest` 의 번역 누락 검사가 알려준다.
"""

from __future__ import annotations

EN: dict[str, str] = {
    # ---------------------------------------------------------------- 공통 버튼/라벨
    "확인": "OK",
    "취소": "Cancel",
    "닫기": "Close",
    "저장": "Save",
    "열기": "Open",
    "추가": "Add",
    "삭제": "Delete",
    "종료": "Quit",
    "정보": "About",
    "설정": "Settings",
    "규칙": "Rules",
    "파일": "File",
    "보기": "View",
    "필터": "Filter",
    "도움말": "Help",
    "프로파일": "Profile",
    "이름": "Name",
    "패턴": "Pattern",
    "키워드": "Keyword",
    "색": "Color",
    "전체": "All",
    "미지정": "not set",
    "정규식": "Regular expression",
    "대소문자 구분": "Match case",
    "줄바꿈": "Word wrap",
    "탭": "Tabs",
    "병합 뷰": "Merged view",
    "찾아보기": "Browse",
    "불러오기": "Load",
    "다른 이름으로": "Save as",
    "다른 이름으로 저장": "Save as",
    "예: ": "e.g. ",
    "저장됨 ✓": "Saved ✓",
    "사용 안 함": "Disabled",
    "글자 크게": "Larger text",
    "글자 작게": "Smaller text",
    "글자 크기 초기화": "Reset text size",
    "보내기": "Send",
    "스크래치패드": "Scratchpad",
    "중단 (Esc)": "Stop (Esc)",
    "제안 적용": "Apply suggestion",
    "연결 제어": "Connection control",
    "전체 Probe": "Probe all",
    "전체 연결": "Connect all",
    "전체 해제": "Disconnect all",
    "대상 포트": "Target port",
    "명령 ▸": "Command ▸",
    "소급 채움": "Backfill",
    "파일로 저장": "Save to file",
    "새 필터": "New filter",
    "새 필터드뷰": "New filtered view",
    "필터드뷰": "Filtered view",
    "필터드뷰 — {0}": "Filtered view — {0}",
    "필터드뷰: {0}": "Filtered view: {0}",
    "필터 결과 저장": "Save filter results",
    "선택 필터로 창 열기": "Open selected filter in a window",
    "저장된 필터": "Saved filters",
    "하이라이트": "Highlight",
    "하이라이트 룰": "Highlight rules",
    "redact (마스킹)": "redact (masking)",
    "redact 룰": "redact rules",
    "트리거": "Triggers",
    "트리거 (발생 집계)": "Triggers (hit counter)",
    "치환 문자열": "Replacement",
    "regex 오류": "regex error",
    "마커 삽입": "Insert marker",
    "마커 내용 (### 자동 부착)": "Marker text (### is added automatically)",
    "화면 언어": "Display language",
    "언어 (Language)": "Language",
    "일반 (General)": "General",
    "연결 (Connection)": "Connection",
    "규칙 (Rules)": "Rules",
    "로그 (Log)": "Log",
    "프로파일 (Profile)": "Profile",
    "저장 위치": "Save location",
    "파일 이름": "File names",
    "파일 분절": "File splitting",
    "로그 폴더": "Log folder",
    "로그 폴더 선택": "Choose log folder",
    "로그 폴더 열기": "Open log folder",
    "로그 파일 열기": "Open log file",
    "세션 접두어": "Session prefix",
    "병합 파일명": "Merged file name",
    "크기 상한": "Size limit",
    "기록 시작": "Start recording",
    "로그 기록 시작": "Start log recording",
    "로그 기록 시작 / 중지": "Start / stop log recording",
    "기록 멈춤 / 재개": "Pause / resume recording",
    "기록 안 함": "Not recording",
    "⏺ 로그 시작": "⏺ Start log",
    "⏹ 로그 중지": "⏹ Stop log",
    "⏸ 기록멈춤": "⏸ Pause",
    "▶ 기록재개": "▶ Resume",
    "🗑 버퍼": "🗑 Buffer",
    "📍 마커": "📍 Marker",
    "🔌 연결": "🔌 Connect",
    "⚙ 설정": "⚙ Settings",
    "🎨 규칙": "🎨 Rules",
    "📁 로그": "📁 Log",
    "💾 프로파일": "💾 Profile",
    "🔎 필터드뷰": "🔎 Filtered view",
    "❓ 도움말": "❓ Help",
    "사용 설명서": "User guide",
    "프로파일 이름": "Profile name",
    "프로파일 저장": "Save profile",
    "현재 설정 저장": "Save current settings",
    "프로파일 전환": "Switch profile",
    "이 포트 사용": "Use this port",
    "이 장비의 콘솔 수": "Consoles on this device",
    "포트 번호 사용 (기본)": "Use port number (default)",
    "직접 입력…": "Custom…",
    "이름 직접 입력": "Enter a name",
    "화면에 표시할 이름": "Name shown on screen",
    "(포트 선택)": "(select a port)",
    "(기록 중이 아닙니다)": "(not recording)",
    "(백업 실패)": "(backup failed)",
    "(파일 기록 실패)": "(file write failed)",
    "점유 후보: ": "Possible holders: ",
    "일부 포트 열기 실패: ": "Some ports failed to open: ",
    "전송할 줄이 없습니다": "Nothing to send",
    "순차 전송 완료": "Sequential send finished",
    "현재 줄 전송 (Ctrl+Enter)": "Send current line (Ctrl+Enter)",
    "전체 순차 전송": "Send all in order",
    "명령 세트 열기": "Open command set",
    "명령 세트 저장": "Save command set",
    "복사본을 저장할 폴더": "Folder for the copy",
    "지금까지의 로그를 복사본으로 저장": "Save a copy of the log so far",
    "새 로그 파일로 분절 (연결 유지)": "Split into a new log file (stay connected)",
    "포커스 콘솔 창 분리": "Pop out focused console",
    "분리한 창 모두 복귀": "Dock all popped-out windows",
    "화면 지우기 (ring·파일 유지)": "Clear view (ring buffer and files kept)",
    "전 콘솔 + 버퍼 비우기 (파일 유지)": "Clear all consoles and buffers (files kept)",
    "자동 스크롤 정지 토글": "Toggle scroll lock",
    "타임스탬프 모드 순환": "Cycle timestamp mode",
    "펌웨어 로그 색 표시": "Show firmware log colors",
    "좌1 + 우2 (기본)": "1 left + 2 right (default)",
    "3단 가로": "3 columns",
    "진단 폴더 열기 (app.log·crash.log·설정)": "Open diagnostics folder (app.log, crash.log, settings)",
    "폴더 열기": "Open folder",
    # 색 이름
    "노랑": "Yellow",
    "주황": "Orange",
    "빨강": "Red",
    "초록": "Green",
    "파랑": "Blue",
    "보라": "Purple",
    "회색": "Gray",
    # ---------------------------------------------------------------- 안내/상태 문장
    "3개 콘솔을 모두 사용합니다": "Using all three consoles",
    "콘솔 {0}개 모두 사용": "Using all {0} consoles",
    "콘솔 {0}개 사용 — {1} 은(는) 숨김": "Using {0} console(s) — {1} hidden",
    "사용 안 함: {0} — 화면·명령 대상·로그에서 빠집니다":
        "Disabled: {0} — excluded from the view, command targets and logs",
    "{0}개": "{0}",
    "{0} 연결": "{0} connection",
    "{0} 연결됨": "{0} connected",
    "{0} 해제됨": "{0} disconnected",
    "{0} 설정 없음": "no settings for {0}",
    "{0} 포트 미지정": "no COM port set for {0}",
    "{0} 열기 실패: {1}": "{0} failed to open: {1}",
    "{0} 미연결 — probe 불가": "{0} is not connected — cannot probe",
    "{0} 미연결 — 전송하지 않음": "{0} is not connected — nothing was sent",
    "{0} 로 전송: {1}": "Sent to {0}: {1}",
    "{0} 파일명": "{0} file name",
    "{0} (기본값)": "{0} (default)",
    "{0}   ← 현재": "{0}   ← current",
    "{0}  —  (연결 안 됨)": "{0}  —  (not present)",
    "{0}개 포트 연결됨 — {1}": "{0} port(s) connected — {1}",
    "{0}: {1}회, 최근 {2}": "{0}: {1} hit(s), last {2}",
    "{0}: {1}\n\n기록: {2}": "{0}: {1}\n\nWritten to: {2}",
    "기록: {0}": "Written to: {0}",
    "\n기록: {0}": "\nWritten to: {0}",
    "\n\n기록: {0}": "\n\nWritten to: {0}",
    "저장: {0}": "Saved: {0}",
    "저장 실패: {0}": "Save failed: {0}",
    "복사 실패: {0}": "Copy failed: {0}",
    "열기 실패: {0}": "Failed to open: {0}",
    "폴더 열기 실패: {0}": "Failed to open folder: {0}",
    "진단 폴더 열기 실패: {0}": "Failed to open diagnostics folder: {0}",
    "불러옴: {0}": "Loaded: {0}",
    "프로파일 저장: {0}": "Profile saved: {0}",
    "프로파일 저장 실패: {0}": "Failed to save profile: {0}",
    "마커 기록: {0}": "Marker written: {0}",
    "기록 시작 — {0} ({1})": "Recording started — {0} ({1})",
    "기록 중: {0}": "Recording to: {0}",
    "기록 중지 — 파일 {0}개는 그대로 남아 있습니다":
        "Recording stopped — {0} file(s) are kept",
    "기록을 시작하지 않았습니다": "Recording was not started",
    "기록은 [⏺ 로그 시작] 을 눌러야 시작됩니다":
        "press [⏺ Start log] to begin recording",
    "기록 중이 아닙니다 — [⏺ 로그 시작] 을 먼저 누르세요":
        "Not recording — press [⏺ Start log] first",
    "기록 멈춤 — 화면·수신은 계속됩니다 (이 구간은 파일에 안 남습니다)":
        "Recording paused — the view and reception continue (this stretch is not written to file)",
    "기록 재개 — 멈춘 동안 {0:,}줄은 파일에 없습니다":
        "Recording resumed — {0:,} line(s) from the pause are not in the file",
    "새 로그 파일로 분절됨: {0}_*.log": "Split into new log files: {0}_*.log",
    "복사본 {0}개 저장: {1} (기록은 계속됩니다)":
        "Saved {0} copy/copies to {1} (recording continues)",
    "로그 위치 변경 — 지금부터 {0} 에 기록합니다 (이전 파일은 {1} 에 그대로)":
        "Log location changed — writing to {0} from now on (earlier files stay in {1})",
    "로그 파일명 변경됨 — 지금부터 {0}": "Log file name changed — {0} from now on",
    "로그 폴더가 아직 없습니다: {0}": "The log folder does not exist yet: {0}",
    "로그 기본 위치를 설정했습니다: {0}": "Default log location set: {0}",
    "버퍼를 비웠습니다 ({0:,}줄) — 로그 파일은 그대로 있습니다":
        "Buffers cleared ({0:,} lines) — the log files are untouched",
    "전체 해제됨 (기록 파일은 그대로 유지)":
        "All ports disconnected (log files are kept)",
    "연결할 포트가 없습니다 — [설정 > 연결] 에서 COM 을 지정하세요":
        "No port to connect — set a COM port in [Settings > Connection]",
    "포트가 아직 지정되지 않았습니다 — [연결] 을 눌러 COM 을 고르고 [전체 연결]":
        "No port set yet — press [Connect], pick a COM port, then [Connect all]",
    "포트를 먼저 선택하세요": "Select a port first",
    "연결(또는 재접속 중인) 포트가 있습니다 — 전체 해제 후 적용하세요.":
        "Some ports are connected (or reconnecting) — disconnect all before applying.",
    "연결된 포트가 있습니다. 전부 해제하고 프로파일을 바꾸시겠습니까?":
        "Some ports are connected. Disconnect all and switch profile?",
    "역할 구성이 다른 프로파일입니다. 적용하려면 앱을 다시 실행하세요.\n현재 연결은 그대로 유지했습니다.":
        "This profile has a different role layout. Restart the app to apply it.\n"
        "The current connections were left untouched.",
    "프로파일 `{0}` 적용됨 — [설정 > 연결] 에서 연결하세요":
        "Profile `{0}` applied — connect from [Settings > Connection]",
    "프로파일 `{0}` 파싱 실패 ({1}) — 기본값으로 기동, 원본 보존: {2}":
        "Could not parse profile `{0}` ({1}) — started with defaults, original kept at {2}",
    "수신 중인 포트는 여전히 {0} 입니다 — Disconnect 후 다시 연결해야 적용됩니다":
        "The port being read is still {0} — disconnect and reconnect to apply",
    "매핑을 적용했습니다 — [저장] 을 눌러 프로파일에 남기세요.":
        "Mapping applied — press [Save] to store it in the profile.",
    "열기 실패 — 점유 프로세스를 찾지 못했습니다 (다른 계정/드라이버가 잡고 있을 수 있습니다)":
        "Failed to open — no holding process found "
        "(another account or a driver may be holding it)",
    "열기 실패: {0} — 점유 프로세스 조회 중…":
        "Failed to open: {0} — looking for the holding process…",
    " — Tera Term / VS Code Serial Monitor 를 닫아 주세요 (추정)":
        " — please close Tera Term / VS Code Serial Monitor (best guess)",
    " — 이 카드는 {0} 인데 판정이 다릅니다": " — this card is {0}, but the probe says otherwise",
    " — 해당 룰은 무시됩니다": " — that rule is ignored",
    "probe 결과가 현재 매핑과 다릅니다 → 제안: {0}":
        "The probe result differs from the current mapping → suggestion: {0}",
    "probe 결과가 현재 매핑과 일치합니다.": "The probe result matches the current mapping.",
    "probe 실패: {0}": "Probe failed: {0}",
    "probe 전송 실패: {0}": "Probe send failed: {0}",
    "probe 중… (무해 토큰 `{0}` 1회 전송)":
        "Probing… (sending the harmless token `{0}` once)",
    "probe 는 실제 명령을 보내지 않습니다 — 어느 콘솔에도 없는 토큰 1개를 보내고 "
    "unknown-command 응답 서명으로 역할을 판정합니다 (오배정 포트에서 부수 효과 0).":
        "Probing never sends a real command — it sends one token that exists on no console and "
        "identifies the role from the unknown-command reply (no side effects on a mis-assigned port).",
    "{0} 판정 — 명령 응답 없음, 자발 트래픽 {1}줄":
        "Detected {0} — no reply to the command, {1} unsolicited line(s)",
    "{0} 판정 — 응답 `{1}`": "Detected {0} — reply `{1}`",
    "미확정 — 알려진 응답 서명이 없습니다. 서명이 바뀌었을 수 있으니 프로파일의 probe 패턴을 확인하세요":
        "Undetermined — no known reply signature. It may have changed; "
        "check the probe patterns in the profile",
    "미확정 — 알려진 응답 서명이 없습니다. 서명이 바뀌었을 수 있으니 "
    "Rules/프로파일의 probe 패턴을 확인하세요":
        "Undetermined — no known reply signature. It may have changed; "
        "check the probe patterns under Rules / the profile",
    "미확정 — 명령을 되찍었는데(입력 콘솔) 알려진 서명이 아닙니다. 프로파일의 probe 패턴을 확인하세요":
        "Undetermined — the console echoed the command (so it takes input) but the signature is "
        "unknown; check the probe patterns in the profile",
    "미확정 — 명령을 되찍었는데(입력 콘솔) 알려진 서명이 아닙니다. SDK 응답 문구가 바뀌었을 수 있으니 "
    "프로파일의 probe 패턴을 확인하세요":
        "Undetermined — the console echoed the command (so it takes input) but the signature is "
        "unknown; the SDK wording may have changed, check the probe patterns in the profile",
    "⚠ {0} 가 이 명령을 모른다고 응답했습니다 — 대상 포트 확인":
        "⚠ {0} replied that it does not know this command — check the target port",
    "⚠ 기록 실패 — {0}": "⚠ Write failed — {0}",
    "⚠ redact 룰 {0}개가 정규식 오류로 무력화됨 ({1}…) — [설정 > 규칙] 에서 고쳐 주세요":
        "⚠ {0} redact rule(s) disabled by a regex error ({1}…) — fix them in [Settings > Rules]",
    "⚡ 트리거 `{0}` — [{1}] {2}": "⚡ Trigger `{0}` — [{1}] {2}",
    "하이라이트 regex 오류: {0}": "Highlight regex error: {0}",
    "redact regex 오류(마스킹 안 됨): {0}": "redact regex error (not masked): {0}",
    "트리거 regex 오류: {0}": "Trigger regex error: {0}",
    "순차 전송 0/{0}": "Sequential send 0/{0}",
    "순차 전송 {0}/{1}": "Sequential send {0}/{1}",
    "순차 전송 중단 — {0}줄 남김": "Sequential send stopped — {0} line(s) left",
    "수신 스레드가 종료되지 않음 — 포트를 계속 점유할 수 있습니다":
        "The reader thread did not stop — it may keep holding the port",
    "{0} 기존 수신 스레드가 종료되지 않음 — 앱을 재시작하세요":
        "{0}: the previous reader thread did not stop — please restart the app",
    "세션이 시작되지 않았습니다 — start_session() 이 먼저입니다":
        "The session has not started — call start_session() first",
    "사용 설명서 파일을 찾지 못했습니다 (docs\\SerialHub_사용설명서.html)":
        "Could not find the user guide (docs\\SerialHub_사용설명서.html)",
    "언어를 바꿨습니다 — 다음에 프로그램을 켤 때부터 적용됩니다.":
        "Language changed — it takes effect the next time you start the program.",
    "바꾸면 다음에 프로그램을 켤 때부터 적용됩니다. 번역이 없는 문구는 한국어로 나옵니다.":
        "Takes effect the next time you start the program. "
        "Text without a translation is shown in Korean.",
    # ---------------------------------------------------------------- 로그/파일 배너
    "!! 기록 일시정지 — 여기부터 재개 표시까지는 파일에 없습니다":
        "!! recording paused — nothing between here and the resume marker is in this file",
    "!! 기록 재개 — 정지 중 {0:,}줄은 이 파일에 없습니다":
        "!! recording resumed — {0:,} line(s) during the pause are not in this file",
    "!! (앞 조각과 합쳐 재판정: 비밀값 마스킹)":
        "!! (re-checked together with the previous fragment: secret masked)",
    "🔒 로그 기록본: {0}": "🔒 Log copy: {0}",
    "    ⋯ {0:,}줄 생략 (화면만 생략 — 로그 파일에는 기록됨) ⋯":
        "    ⋯ {0:,} line(s) omitted (view only — they are in the log file) ⋯",
    "    ⋯ 이전 {0:,}줄 생략 (다시 그리기 상한 {1:,} — 로그 파일에는 기록됨) ⋯":
        "    ⋯ {0:,} earlier line(s) omitted (redraw limit {1:,} — they are in the log file) ⋯",
    "    ⋯ 일부 라인이 버퍼에서 밀려남 (로그 파일에는 기록됨) ⋯":
        "    ⋯ some lines were pushed out of the buffer (they are in the log file) ⋯",
    "-- tail {0} (Ctrl+C 종료) --": "-- tail {0} (Ctrl+C to quit) --",
    # ---------------------------------------------------------------- 툴팁/설명
    "클릭 = 해당 콘솔로 이동": "Click to jump to that console",
    "트리거 발생 집계 (설정 > 규칙에서 편집) — 클릭 = 카운터 초기화":
        "Trigger hit counter (edit under Settings > Rules) — click to reset",
    "전 콘솔 화면 + 메모리 버퍼 비우기 (Ctrl+Shift+L) — 로그 파일은 그대로 남습니다":
        "Clear every console view and the memory buffer (Ctrl+Shift+L) — log files are kept",
    "로그에 `### …` 구분 마커 삽입 (Ctrl+M) — 재현 시점 표시":
        "Insert a `### …` marker into the log (Ctrl+M) — marks the moment of reproduction",
    "파일 기록을 시작합니다 — 누르면 저장 위치·파일명을 먼저 확인합니다. 연결만으로는 기록이 "
    "시작되지 않습니다.":
        "Starts writing to file — you confirm the location and file names first. "
        "Connecting alone does not start recording.",
    "파일 기록만 멈춥니다 (Ctrl+P) — 화면·수신은 계속. 멈춘 구간은 파일에 안 남습니다":
        "Pauses file writing only (Ctrl+P) — the view and reception continue; "
        "the paused stretch is not written",
    "현재 기록 폴더 — 클릭하면 탐색기로 엽니다":
        "Current recording folder — click to open it in Explorer",
    "이 콘솔 화면 지우기 (Ctrl+L) — 로그 파일은 그대로":
        "Clear this console view (Ctrl+L) — the log file is untouched",
    "자동 스크롤 정지 (Ctrl+Space) — 수신·기록은 계속됩니다":
        "Scroll lock (Ctrl+Space) — reception and recording continue",
    "빈 라인 숨김 — 펌웨어가 뱉는 빈 줄 다발을 걸러냅니다":
        "Hide blank lines — filters the runs of empty lines the firmware emits",
    "타임스탬프: {0} — 눌러서 전환 (Ctrl+T)": "Timestamp: {0} — click to switch (Ctrl+T)",
    "절대 시각": "absolute time",
    "상대 시각(경과)": "relative time (elapsed)",
    "시각 표시 끔": "timestamps off",
    "검색 (Ctrl+F)": "Search (Ctrl+F)",
    "검색 (Enter/F3 다음, Shift+F3 이전) — 눌러서 최근 검색어 선택":
        "Search (Enter/F3 next, Shift+F3 previous) — click to pick a recent term",
    "별도 창으로 분리 (닫으면 원래 자리로 복귀)":
        "Pop out into its own window (closing it docks the console back)",
    "원래 자리로 되돌리기 (창을 닫아도 복귀합니다)":
        "Dock back (closing this window docks it too)",
    "매치 라인만 보는 창 (Ctrl+K)": "A window showing only matching lines (Ctrl+K)",
    "매치되는 라인만 보여줍니다": "Shows only the matching lines",
    "이미 받은 라인 중 매치되는 것도 채웁니다":
        "Also fills in matching lines that arrived earlier",
    "지금 보이는 매치 결과를 텍스트 파일로 저장 (티켓 첨부용)":
        "Save the matches currently shown as a text file (to attach to a ticket)",
    "포트 지정·probe·연결 (Ctrl+E)": "Ports, probing and connections (Ctrl+E)",
    "연결·규칙·로그·프로파일 설정 (Ctrl+,)":
        "Connection, rules, log and profile settings (Ctrl+,)",
    "하이라이트·마스킹·트리거·저장된 필터":
        "Highlighting, masking, triggers and saved filters",
    "저장 위치·파일 이름·분절": "Location, file names and splitting",
    "프로파일 저장·불러오기": "Save and load profiles",
    "사용 설명서 열기 (F1)": "Open the user guide (F1)",
    "화면에 표시할 이름 — 누르면 자주 쓰는 이름을 고르거나 직접 입력":
        "Name shown on screen — click to pick a common name or enter your own",
    "끄면 이 콘솔은 화면·명령 대상·로그에서 빠집니다 (COM·이름 설정은 그대로 보관). "
    "UART 가 1~2개인 모델에서 빈 콘솔이 자리를 차지하지 않게 하는 스위치입니다.":
        "Turn this off and the console disappears from the view, the command targets and the logs "
        "(its COM port and name are kept). Use it so unused consoles do not take up room on "
        "devices with only one or two UARTs.",
    "이 아래에 날짜별(MMDD) 폴더가 자동으로 생깁니다":
        "Date folders (MMDD) are created under this automatically",
    "끄면 <이름>.log 로 고정됩니다 — 매번 같은 파일에 이어 씁니다":
        "Turn this off for a fixed <name>.log — every run appends to the same file",
    "파일명에 세션 접두어 포함 (<접두어>_HHMMSS_<이름>.log)":
        "Include the session prefix in file names (<prefix>_HHMMSS_<name>.log)",
    "병합 파일이 이 크기를 넘으면 _p2, _p3 … 로 나눕니다 (0 = 안 나눔)":
        "Split the merged file into _p2, _p3 … past this size (0 = never split)",
    "자정을 넘기면 날짜 폴더가 바뀌는 것과는 별개입니다. 수신은 어느 쪽도 멈추지 않습니다.":
        "This is separate from the date folder rolling over at midnight. "
        "Neither one interrupts reception.",
    "여기 설정은 [확인] 을 눌러야 적용됩니다 — 편집 도중에 반영하면 빈 로그 파일이 계속 생깁니다.":
        "These settings apply when you press [OK] — applying them as you type would keep "
        "creating empty log files.",
    "이번 기록을 어디에 어떤 이름으로 남길지 확인해 주세요. [기록 시작] 을 누르면 그때부터 파일에 쌓입니다.":
        "Confirm where this recording goes and what it is called. "
        "Lines are written to file from the moment you press [Start recording].",
    "라이브 스트림에 즉시 반영됩니다. `Error`(주황)·`!!`(노랑)은 기본 제공.":
        "Applies to the live stream immediately. `Error` (orange) and `!!` (yellow) are built in.",
    "그룹 1이 있으면 그 부분만 치환합니다. regex 를 끄면 리터럴로 찾습니다 — 비밀번호에 정규식 "
    "메타문자가 있을 때 씁니다. 마스킹은 화면·파일·프로파일 공통이고, 시리얼로 나가는 것만 원문입니다.":
        "If group 1 exists only that part is replaced. Turn regex off to match literally — "
        "useful when a password contains regex metacharacters. Masking applies to the view, the "
        "files and the profile alike; only what goes out over the serial line is unmasked.",
    "매치 횟수·최근 시각을 Monitor 의 ⚡ 칩에 집계합니다 — 밤샘 수집 중 WDOG/MemManage 같은 "
    "이벤트를 놓치지 않기 위한 것입니다. 하이라이트와는 별개입니다.":
        "Counts hits and the last time into the ⚡ chip on the monitor — so events like WDOG or "
        "MemManage are not missed during an overnight capture. Separate from highlighting.",
    "프로파일에는 포트 매핑·baud·로그 설정·룰·창 배치가 들어갑니다. 파일로 복사하면 다른 벤치에서 "
    "그대로 쓸 수 있습니다.":
        "A profile holds the port mapping, baud rates, log settings, rules and window layout. "
        "Copy the file to use the same setup on another bench.",
    "장치가 보낸 ANSI 색을 화면에 살립니다 (로그 파일은 항상 색 코드 없음)":
        "Show the ANSI colors the device sends (log files never contain color codes)",
    "자주 쓰는 명령 세트. `#` 로 시작하는 줄은 주석 — 전송하지 않습니다.":
        "Your frequently used command set. Lines starting with `#` are comments and are not sent.",
    "명령 입력 후 Enter — 대상 포트는 왼쪽에서 선택 (Ctrl+Tab 전환)":
        "Type a command and press Enter — pick the target port on the left (Ctrl+Tab to cycle)",
    # ---------------------------------------------------------------- CLI / 진단
    "Serial Hub — 포트 통합 시리얼 모니터": "Serial Hub — unified serial monitor",
    "Serial Hub 설치 점검": "Serial Hub installation check",
    "Serial Hub 오류": "Serial Hub error",
    "Serial Hub 정보": "About Serial Hub",
    "SerialHub_사용설명서.html": "SerialHub_사용설명서.html",
    "<b>Serial Hub</b><br>포트 통합 시리얼 모니터<br><br>버전 {0}":
        "<b>Serial Hub</b><br>Unified serial monitor<br><br>Version {0}",
    "Python {0} · PySide6 {1}\n데이터 폴더: {2}\n\nCopyright © psy-bari":
        "Python {0} · PySide6 {1}\nData folder: {2}\n\nCopyright © psy-bari",
    "사용할 프로파일 이름 (기본: 마지막 사용)": "profile to use (default: last used)",
    "포트 없이 합성 로그로 화면만 확인 (기록·연결 없음)":
        "preview the UI with synthetic logs, no ports (no recording, no connections)",
    "프로파일·설정이 저장되는 경로를 출력하고 끝냅니다":
        "print where profiles and settings are stored, then exit",
    "이 빌드가 쓸 수 있는 상태인지 점검 (pyserial·Qt·저장 경로)":
        "check that this build is usable (pyserial, Qt, writable paths)",
    "새 프로파일의 로그 기본 위치를 지정 (설치 프로그램이 사용)":
        "set the default log location for new profiles (used by the installer)",
    "데모 모드 — 화면의 [DEMO] 줄은 합성 데이터입니다 (실제 포트 아님)":
        "Demo mode — the [DEMO] lines are synthetic, not from a real port",
    "데이터 폴더   : {0}": "Data folder   : {0}",
    "프로파일      : {0}": "Profiles      : {0}",
    "설정          : {0}": "Settings      : {0}",
    "로그 기본 위치: {0}": "Default logs  : {0}",
    "크래시 로그   : {0}": "Crash log     : {0}",
    "=> 사용 가능": "=> usable",
    "=> 문제 있음": "=> problems found",
    "사용 가능한 상태입니다.": "This build is usable.",
    "문제가 있습니다 — 아래 내용을 확인하세요.": "There is a problem — see the details below.",
    "[OK] pyserial {0} — COM 열거 동작 ({1}개 발견)":
        "[OK] pyserial {0} — COM enumeration works ({1} found)",
    "       (이 PC 에 시리얼 포트가 없습니다 — 열거 기능 자체는 정상)":
        "       (no serial ports on this PC — enumeration itself is fine)",
    "[FAIL] pyserial 사용 불가: {0!r}": "[FAIL] pyserial unusable: {0!r}",
    "[FAIL] PySide6 사용 불가: {0!r}": "[FAIL] PySide6 unusable: {0!r}",
    "[OK] core (LogStore / probe 판정)": "[OK] core (LogStore / probe detection)",
    "[FAIL] core 동작 이상: {0!r}": "[FAIL] core misbehaving: {0!r}",
    "[OK] 프로파일 저장 가능: {0}": "[OK] profiles are writable: {0}",
    "[FAIL] 프로파일 폴더에 쓸 수 없습니다: {0}": "[FAIL] profile folder is not writable: {0}",
    "[FAIL] 프로파일 폴더 확인 실패: {0!r}": "[FAIL] could not check the profile folder: {0!r}",
}
