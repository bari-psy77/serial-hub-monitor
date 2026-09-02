#!/usr/bin/env python3
"""GitHub 릴리스 배포 — 포터블 zip + 설치본을 **가장 최신 것만** 올린다.

  python publish_release.py --dry-run     # 무엇을 올릴지 먼저 확인
  python publish_release.py               # 릴리스 생성/갱신 + 옛 릴리스 정리

`dist/` 는 gitignore 라 저장소에 바이너리가 들어가지 않는다 — 배포물은 GitHub
릴리스에만 둔다. 저장소에는 85MB 짜리 산출물을 커밋하지 않는다.

인증은 GitHub CLI(`gh auth login`)를 쓴다. 토큰을 이 저장소나 코드에 두지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")
ZIP_RE = re.compile(r"^SerialHub_(\d{8})\.zip$")
# git@host:owner/repo.git · https://host/owner/repo.git 둘 다 — host 는 SSH 별칭일 수 있다
SLUG_RE = re.compile(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$")
LF = chr(10)          # 여러 줄 안내문에 쓰는 줄바꿈


class ReleaseError(RuntimeError):
    """배포를 멈춰야 하는 상황 — 조용히 옛 파일을 올리는 것보다 낫다."""


@dataclass(frozen=True, slots=True)
class Artifacts:
    installer: str
    portable: str

    def paths(self) -> list[str]:
        return [self.installer, self.portable]


def read_version() -> str:
    with open(os.path.join(HERE, "__init__.py"), encoding="utf-8") as fh:
        match = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read())
    if not match:
        raise ReleaseError("__init__.py 에서 __version__ 을 찾지 못했습니다")
    return match.group(1)


def find_artifacts(dist_dir: str, version: str) -> Artifacts:
    """이 버전의 설치본 + 가장 최신 포터블 zip.

    설치본은 **파일명에 버전이 박혀 있다** — 다른 버전만 있으면 실패시킨다.
    빌드를 깜빡하고 옛 설치본을 올리는 사고가 가장 비싸기 때문이다.
    """
    installer = os.path.join(dist_dir, f"SerialHub_Setup_{version}.exe")
    if not os.path.exists(installer):
        others = sorted(f for f in _listdir(dist_dir) if f.startswith("SerialHub_Setup_"))
        hint = f" (있는 것: {', '.join(others)})" if others else ""
        raise ReleaseError(f"Setup 파일이 없습니다: {os.path.basename(installer)}{hint}"
                           f" — python build_installer.py 를 먼저 돌리세요")
    zips = [os.path.join(dist_dir, name) for name in _listdir(dist_dir) if ZIP_RE.match(name)]
    if not zips:
        raise ReleaseError("포터블 zip 이 없습니다 — python build_exe.py --zip 을 먼저 돌리세요")
    portable = max(zips, key=os.path.getmtime)   # 날짜 이름이라도 mtime 이 정본이다
    return Artifacts(installer, portable)


def _listdir(path: str) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


# ---------------------------------------------------------------- GitHub CLI

def repo_slug(remote_url: str) -> str:
    """원격 URL -> `owner/repo`.

    이 벤치의 원격은 `git@github-bari:owner/repo.git` 처럼 **SSH 별칭**을 쓴다 —
    gh 는 호스트가 github.com 이 아니면 저장소를 스스로 알아내지 못하므로 명시해 준다.
    """
    if not remote_url or remote_url.startswith("file:"):
        return ""
    match = SLUG_RE.search(remote_url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def current_repo() -> str:
    result = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True,
                            text=True, cwd=HERE)
    return repo_slug(result.stdout) if result.returncode == 0 else ""


def gh_path() -> str:
    for candidate in ("gh", os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                          "GitHub CLI", "gh.exe")):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            return candidate
        except (OSError, subprocess.CalledProcessError):
            continue
    raise ReleaseError("GitHub CLI(gh)를 찾지 못했습니다 — winget install --id GitHub.cli")


def describe_args(args: list[str]) -> str:
    """에러 메시지에 쓸 명령 요약 — 릴리스 노트 본문까지 쏟아내지 않는다."""
    shown = []
    skip_next = False
    for arg in args:
        if skip_next:
            shown.append("<생략>")
            skip_next = False
            continue
        if arg == "--notes":
            shown.append(arg)
            skip_next = True
            continue
        shown.append(os.path.basename(arg) if os.path.sep in arg else arg)
    return " ".join(shown)


def permission_hint(stderr: str) -> str:
    """403 은 거의 항상 토큰 권한 문제다 — 무엇을 고쳐야 하는지 바로 알려준다."""
    if "403" not in stderr and "not accessible" not in stderr:
        return ""
    return (
        LF + "토큰 권한이 부족합니다 (인증은 됐지만 릴리스를 만들 수 없음)." + LF
        + "  fine-grained 토큰: Repository access 에 serial-hub-monitor 를 넣고," + LF
        + "    Repository permissions > Contents 를 Read and write 로 바꾸세요." + LF
        + "    (릴리스는 Contents 권한이 관장합니다 — 저장 후 바로 적용됩니다)" + LF
        + "  classic 토큰이라면 repo 스코프가 필요합니다 (비공개 저장소)."
    )


def gh(args: list[str], *, check: bool = True, repo: str = "") -> subprocess.CompletedProcess:
    if repo and args and args[0] == "release":
        args = [*args, "--repo", repo]
    result = subprocess.run([gh_path(), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", cwd=HERE)
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        raise ReleaseError(f"gh {describe_args(args)} 실패:" + LF + stderr
                           + permission_hint(stderr))
    return result


def ensure_auth() -> str:
    """인증 확인 + **어느 계정으로 올리는지** 알려준다.

    이 PC 는 회사 계정도 함께 쓴다 — 브라우저로 로그인하면 브라우저에 로그인돼 있는
    그 계정으로 붙는다. 올리기 전에 계정 이름을 찍어 두면 엉뚱한 계정으로 올리는 것을
    바로 알아챌 수 있다. 아무것도 저장하지 않으려면 GH_TOKEN 으로 1회용 토큰을 쓴다.
    """
    result = gh(["auth", "status"], check=False)
    if result.returncode != 0:
        raise ReleaseError(
            "GitHub 인증이 필요합니다. 둘 중 하나면 됩니다:" + LF
            + "  1) 1회용 — 이 저장소에만 Contents:write 를 준 fine-grained 토큰을" + LF
            + "     GH_TOKEN 환경변수로 넘기기 (아무것도 저장되지 않습니다)" + LF
            + "  2) gh auth login — 다른 계정이 있어도 지워지지 않습니다" + LF
            + "     (gh auth switch 로 전환, 브라우저 대신 토큰 붙여넣기 권장)" + LF
            + result.stderr.strip())
    who = gh(["api", "user", "-q", ".login"], check=False)
    return who.stdout.strip() if who.returncode == 0 else "(계정 확인 실패)"


def existing_releases(repo: str = "") -> list[dict]:
    result = gh(["release", "list", "--limit", "50", "--json", "tagName,name,createdAt"],
                repo=repo)
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []


def publish(version: str, artifacts: Artifacts, notes: str, prune: bool,
            repo: str = "", notes_only: bool = False) -> str:
    tag = f"v{version}"
    releases = existing_releases(repo)
    tags = {item.get("tagName") for item in releases}

    if notes_only:
        if tag not in tags:
            raise ReleaseError(f"릴리스 {tag} 가 아직 없습니다 — 먼저 그냥 올리세요")
        gh(["release", "edit", tag, "--notes", notes], repo=repo)
        print("  릴리스 노트만 갱신했습니다 (자산은 그대로)")
        return tag

    if tag in tags:
        # 같은 버전을 다시 올리는 경우 — 자산만 덮어쓴다 (--clobber)
        gh(["release", "upload", tag, *artifacts.paths(), "--clobber"], repo=repo)
        gh(["release", "edit", tag, "--notes", notes, "--latest"], repo=repo)
    else:
        gh(["release", "create", tag, *artifacts.paths(),
            "--title", f"Serial Hub {version}", "--notes", notes, "--latest"], repo=repo)

    if prune:
        for item in releases:
            other = item.get("tagName")
            if other and other != tag:
                # ★가장 최신만 남긴다 (사용자 합의) — 릴리스와 태그를 같이 지운다
                gh(["release", "delete", other, "--yes", "--cleanup-tag"],
                   check=False, repo=repo)
                print(f"  옛 릴리스 삭제: {other}")
    return tag


def release_notes(version: str) -> str:
    """CHANGELOG 의 해당 버전 절을 그대로 릴리스 노트로 쓴다."""
    path = os.path.join(HERE, "CHANGELOG.md")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return f"Serial Hub {version}"
    match = re.search(rf"^## {re.escape(version)}.*?(?=^## |\Z)", text, re.M | re.S)
    body = match.group(0).strip() if match else f"Serial Hub {version}"
    return (f"{body}\n\n---\n"
            f"- 설치본: `SerialHub_Setup_{version}.exe`\n"
            f"- 무설치(포터블): `SerialHub_<날짜>.zip` — 풀고 `SerialHub.exe` 실행\n"
            f"- 새 PC 에서는 `SerialHub.exe --selfcheck` 를 먼저 돌려 보세요\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub 릴리스에 최신 배포물 올리기")
    parser.add_argument("--dry-run", action="store_true", help="올리지 않고 계획만 출력")
    parser.add_argument("--keep-old", action="store_true",
                        help="옛 릴리스를 지우지 않는다 (기본은 최신 하나만 남김)")
    parser.add_argument("--notes-only", action="store_true",
                        help="자산은 그대로 두고 릴리스 노트만 다시 쓴다")
    args = parser.parse_args(argv)

    try:
        version = read_version()
        artifacts = find_artifacts(DIST, version)
        print(f"버전 {version}")
        for path in artifacts.paths():
            print(f"  {os.path.basename(path)}  ({os.path.getsize(path) / 1024 / 1024:.0f} MB)")
        if args.dry_run:
            plan = ("릴리스 노트만 갱신합니다" if args.notes_only else f"태그 v{version} 로 올리고, "
                    + ("옛 릴리스는 그대로 둡니다" if args.keep_old else "다른 릴리스는 지웁니다"))
            print(f"\n[dry-run] {plan}")
            return 0
        account = ensure_auth()
        token_used = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        print(f"계정 {account} ({'GH_TOKEN' if token_used else 'gh 로그인'})")
        repo = current_repo()
        print(f"저장소 {repo or '(원격에서 못 읽음 — gh 기본값 사용)'}")
        tag = publish(version, artifacts, release_notes(version),
                      prune=not args.keep_old, repo=repo,
                      notes_only=args.notes_only)
        url = gh(["release", "view", tag, "--json", "url", "-q", ".url"],
                 repo=repo).stdout.strip()
        print(f"\n올렸습니다: {url}")
        return 0
    except ReleaseError as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
