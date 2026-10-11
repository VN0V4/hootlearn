"""Finding a repository on disk (or cloning it) and listing its source files."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Folders that never contain hand-written source code worth learning from.
IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "third_party", "__pycache__",
    ".venv", "venv", "env", ".env", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", "target", "out", ".next", ".nuxt", ".idea", ".vscode", "coverage",
    ".gradle", "Pods", ".dart_tool", "site-packages", ".cache",
}

# Generated or binary-ish files that would only add noise.
IGNORED_SUFFIXES = (
    ".min.js", ".min.css", ".map", ".lock", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".svg", ".pdf", ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf", ".eot", ".mp3",
    ".mp4", ".wav", ".so", ".dll", ".dylib", ".exe", ".bin", ".class", ".jar", ".pyc",
    ".o", ".a", ".wasm", ".db", ".sqlite",
)
IGNORED_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "poetry.lock", "go.sum"}

MAX_FILE_BYTES = 400_000  # bigger files are almost always generated

CLONE_CACHE = Path.home() / ".cache" / "hootlearn" / "repos"

_URL_RE = re.compile(r"^(https?://|git@|ssh://|git://)")


@dataclass
class SourceFile:
    path: Path      # absolute path on disk
    rel: str        # path relative to the repo root, always with forward slashes
    size: int


def is_remote(target: str) -> bool:
    return bool(_URL_RE.match(target.strip()))


def resolve_repo(target: str, log=print) -> Path:
    """Return a local folder for `target`, cloning it first if it is a URL."""
    target = target.strip()
    if not is_remote(target):
        path = Path(target).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Not a folder: {path}")
        return path

    name = re.sub(r"\.git$", "", target.rstrip("/").split("/")[-1].split(":")[-1]) or "repo"
    digest = hashlib.sha1(target.encode()).hexdigest()[:8]
    dest = CLONE_CACHE / f"{name}-{digest}"
    if dest.exists():
        log(f"Updating cached clone in {dest}")
        result = subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"], capture_output=True, text=True)
        if result.returncode != 0:
            log("  (pull failed, using the existing copy)")
        return dest

    CLONE_CACHE.mkdir(parents=True, exist_ok=True)
    log(f"Cloning {target} ...")
    result = subprocess.run(["git", "clone", "--filter=blob:none", target, str(dest)], capture_output=True, text=True)
    if result.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(f"git clone failed:\n{result.stderr.strip()}")
    return dest


def is_git_repo(root: Path) -> bool:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _wanted(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in IGNORED_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    return name not in IGNORED_NAMES and not name.lower().endswith(IGNORED_SUFFIXES)


def list_files(root: Path) -> list[SourceFile]:
    """All candidate files, respecting .gitignore when the folder is a git repo."""
    if is_git_repo(root):
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True,
        ).stdout.decode("utf-8", "replace")
        rels = [r for r in out.split("\0") if r]
    else:
        rels = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
            for fn in filenames:
                rels.append(Path(dirpath, fn).relative_to(root).as_posix())

    files = []
    for rel in sorted(set(rels)):
        if not _wanted(rel):
            continue
        path = root / rel
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if path.is_file() and 0 < size <= MAX_FILE_BYTES:
            files.append(SourceFile(path, rel, size))
    return files


def read_text(path: Path) -> str | None:
    """Read a file as text, or None if it looks binary."""
    data = path.read_bytes()
    if b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", "replace")


def git_history(root: Path) -> dict:
    """Summarise how the project grew, using `git log`. Empty dict if not a git repo."""
    if not is_git_repo(root):
        return {}
    log = subprocess.run(
        ["git", "-C", str(root), "log", "--reverse", "--diff-filter=A", "--name-only", "--format=@@%h%x09%ad%x09%s", "--date=short"],
        capture_output=True, text=True,
    )
    if log.returncode != 0:
        return {}
    commits = []
    for line in log.stdout.splitlines():
        if line.startswith("@@"):
            sha, date, subject = (line[2:].split("\t") + ["", ""])[:3]
            commits.append({"sha": sha, "date": date, "subject": subject, "added": []})
        elif line.strip() and commits:
            commits[-1]["added"].append(line.strip())
    count = subprocess.run(["git", "-C", str(root), "rev-list", "--count", "HEAD"], capture_output=True, text=True)
    total = int(count.stdout.strip()) if count.returncode == 0 and count.stdout.strip().isdigit() else len(commits)
    return {"total_commits": total, "commits_adding_files": commits}
