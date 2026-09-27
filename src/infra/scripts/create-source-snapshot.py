#!/usr/bin/env python3
"""Create a deterministic, secret-path-excluding snapshot for image builds."""

from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[3]
INCLUDED_ROOTS = (
    "src/backend/",
    "src/frontend/",
    "src/infra/",
    "tests/",
    "docs/",
    "evidence/",
    "analytics/",
    "data/",
)
INCLUDED_FILES = {
    "README.md",
    "AI_USE_DECLARATION.md",
    "TEAM_CONTRIBUTIONS.md",
    "project_manifest.yaml",
    "docker-compose.yml",
    "docker-compose.dev.yml",
    ".dockerignore",
    "src/README.md",
}
EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "dist"}


def run_git(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return [path.decode("utf-8") for path in result.stdout.split(b"\0") if path]


def parse_porcelain_status(status: bytes) -> list[str]:
    """Return changed destination paths from git's NUL-delimited v1 status."""
    entries = [entry for entry in status.split(b"\0") if entry]
    paths: list[str] = []
    index = 0
    while index < len(entries):
        record = entries[index]
        if len(record) < 4:
            raise SystemExit("Could not parse git status output safely.")
        status_code = record[:2]
        paths.append(record[3:].decode("utf-8"))
        index += 1
        if b"R" in status_code or b"C" in status_code:
            # With -z, the next field is the original path, not a new status row.
            index += 1
    return paths


def included(path: str) -> bool:
    candidate = Path(path)
    parts = candidate.parts
    if not parts or any(part in EXCLUDED_DIRS for part in parts):
        return False
    if any(part.startswith(".env") for part in parts):
        return False
    if any(part.endswith((".pyc", ".pyo")) for part in parts):
        return False
    return path in INCLUDED_FILES or path.startswith(INCLUDED_ROOTS)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: create-source-snapshot.py OUTPUT.tar.gz", file=sys.stderr)
        return 2
    output = Path(sys.argv[1]).expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise SystemExit("Snapshot output must be outside the repository to avoid recursive inclusion.")
    output.parent.mkdir(parents=True, exist_ok=True)

    status_result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    status_paths = parse_porcelain_status(status_result.stdout)
    for path in status_paths:
        if not included(path):
            raise SystemExit(f"Dirty path is outside the source snapshot allowlist: {path}")

    tracked = run_git("ls-files", "-z")
    untracked = run_git("ls-files", "--others", "--exclude-standard", "-z")
    paths = sorted({path for path in tracked + untracked if included(path)})
    for path in paths:
        source = ROOT / path
        if source.is_symlink() or not source.is_file():
            raise SystemExit(f"Snapshot refuses a non-regular source path: {path}")

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()
    file_records = []
    for path in paths:
        content_hash = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        source_stat = (ROOT / path).stat()
        file_records.append({
            "path": path,
            "sha256": content_hash,
            "bytes": source_stat.st_size,
            "mode": source_stat.st_mode & 0o777,
        })
    identity = {"commit": commit, "files": file_records}
    snapshot_sha = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = {
        "format": 1,
        "repository_commit": commit,
        "source_snapshot_sha256": snapshot_sha,
        "included_file_count": len(file_records),
        "files": file_records,
        "exclusions": [".env*", ".git", ".venv", "node_modules", "generated caches"],
        "dirty_state": "Included file hashes describe the current working tree, including uncommitted files.",
    }

    with tempfile.TemporaryDirectory(prefix="inf2006-snapshot-") as temporary:
        stage = Path(temporary)
        for record in file_records:
            relative = record["path"]
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
            destination.chmod(record["mode"])
            staged_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
            staged_mode = destination.stat().st_mode & 0o777
            if staged_hash != record["sha256"] or staged_mode != record["mode"]:
                raise SystemExit(f"Source changed while the snapshot was being staged: {relative}")
        (stage / "source-snapshot.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with output.open("wb") as raw_archive, gzip.GzipFile(
            filename="", fileobj=raw_archive, mode="wb", mtime=0
        ) as compressed:
            archive = tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT)
            for entry in sorted(stage.rglob("*")):
                if entry.is_file():
                    name = entry.relative_to(stage).as_posix()
                    info = tarfile.TarInfo(name)
                    info.size = entry.stat().st_size
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = entry.stat().st_mode & 0o777
                    with entry.open("rb") as source:
                        archive.addfile(info, source)
            archive.close()
    print(snapshot_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
