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


def gh(args: list[str], *, check: bool = True, repo: str = "") -> subprocess.CompletedProcess:
    if repo and args and args[0] == "release":
        args = [*args, "--repo", repo]
    result = subprocess.run([gh_path(), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", cwd=HERE)
    if check and result.returncode != 0:
        raise ReleaseError(f"gh {' '.join(args)} 실패:\n{result.stderr.strip()}")
    return result


def ensure_auth() -> None:
    result = gh(["auth", "status"], check=False)
    if result.returncode != 0:
        raise ReleaseError("GitHub 로그인이 필요합니다 — 한 번만 `gh auth login` 을 실행하세요\n"
                           f"{result.stderr.strip()}")


def existing_releases(repo: str = "") -> list[dict]:
    result = gh(["release", "list", "--limit", "50", "--json", "tagName,name,createdAt"],
                repo=repo)
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []


def publish(version: str, artifacts: Artifacts, notes: str, prune: bool,
            repo: str = "") -> str:
    tag = f"v{version}"
    releases = existing_releases(repo)
    tags = {item.get("tagName") for item in releases}

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
    args = parser.parse_args(argv)

    try:
        version = read_version()
        artifacts = find_artifacts(DIST, version)
        print(f"버전 {version}")
        for path in artifacts.paths():
            print(f"  {os.path.basename(path)}  ({os.path.getsize(path) / 1024 / 1024:.0f} MB)")
        if args.dry_run:
            print(f"\n[dry-run] 태그 v{version} 로 올리고, "
                  f"{'옛 릴리스는 그대로 둡니다' if args.keep_old else '다른 릴리스는 지웁니다'}")
            return 0
        ensure_auth()
        repo = current_repo()
        print(f"저장소 {repo or '(원격에서 못 읽음 — gh 기본값 사용)'}")
        tag = publish(version, artifacts, release_notes(version),
                      prune=not args.keep_old, repo=repo)
        url = gh(["release", "view", tag, "--json", "url", "-q", ".url"],
                 repo=repo).stdout.strip()
        print(f"\n올렸습니다: {url}")
        return 0
    except ReleaseError as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
