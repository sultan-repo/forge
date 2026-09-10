"""Seal and restore a B3 stage boundary without replaying its completed session."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path

EVIDENCE = {"run-stage1.json", "meta-stage.json", "transcript.jsonl", "full.diff", "diffstat.txt",
            "prompt.txt", "stdout.txt", "stderr.txt", "network.json"}
REQUIRED = {"run-stage1.json", "meta-stage.json", "transcript.jsonl"}


def file_hash(path: Path) -> str:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("stage evidence must be a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("snapshot root must be a directory")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        digest.update(os.fsencode(path.relative_to(root)))
        digest.update(f"\0{mode}\0".encode())
        if stat.S_ISLNK(mode):
            digest.update(os.fsencode(os.readlink(path)))
        elif stat.S_ISREG(mode):
            digest.update(file_hash(path).encode())
        elif not stat.S_ISDIR(mode):
            raise ValueError("snapshot contains a special file")
        digest.update(b"\0")
    return digest.hexdigest()


def capture(repo: Path, stage: Path) -> None:
    snapshot = stage / "repo-snapshot"
    if snapshot.exists() or (stage / "SNAPSHOT.json").exists():
        raise ValueError("stage boundary already exists; refusing replacement")
    # Reject special files before copy, and copy links without following them.
    original_hash = tree_hash(repo)
    shutil.copytree(repo, snapshot, symlinks=True)
    if tree_hash(snapshot) != original_hash:
        raise ValueError("repository changed during stage snapshot")
    evidence = {name: file_hash(stage / name) for name in sorted(EVIDENCE) if (stage / name).exists()}
    if not REQUIRED <= evidence.keys():
        raise ValueError("stage snapshot lacks required evidence")
    payload = {"version": 1, "scenario": "b3", "tree_sha256": original_hash, "evidence_sha256": evidence}
    (stage / "SNAPSHOT.json").write_text(json.dumps(payload, indent=2) + "\n")


def restore(source_stage: Path, repo: Path, stage: Path) -> None:
    if repo.exists() or stage.exists():
        raise ValueError("restored destinations must be new")
    if source_stage.is_symlink():
        raise ValueError("stage source cannot be a symlink")
    seal = json.loads((source_stage / "SNAPSHOT.json").read_text())
    if seal.get("version") != 1 or seal.get("scenario") != "b3":
        raise ValueError("unsupported stage snapshot")
    evidence = seal.get("evidence_sha256", {})
    if not isinstance(evidence, dict) or not REQUIRED <= evidence.keys() <= EVIDENCE:
        raise ValueError("invalid stage evidence map")
    if tree_hash(source_stage / "repo-snapshot") != seal.get("tree_sha256"):
        raise ValueError("stage repository snapshot changed")
    for name, expected in evidence.items():
        if file_hash(source_stage / name) != expected:
            raise ValueError("stage evidence changed")
    score = json.loads((source_stage / "run-stage1.json").read_text())
    if score.get("scenario") != "b3" or score.get("criteria_version") != "v4" or score.get("pass") is not True:
        raise ValueError("stage boundary lacks a passing current-criteria handoff")
    shutil.copytree(source_stage / "repo-snapshot", repo, symlinks=True)
    stage.mkdir(parents=True)
    for name in evidence:
        shutil.copy2(source_stage / name, stage / name)
    # Retain a self-contained sealed boundary for a further zero-work pause.
    capture(repo, stage)
    (stage / "RECOVERED_FROM.json").write_text(json.dumps({"source": str(source_stage.resolve())}) + "\n")


def main(args: list[str]) -> int:
    try:
        if len(args) == 3 and args[0] == "capture":
            capture(Path(args[1]), Path(args[2]))
        elif len(args) == 4 and args[0] == "restore":
            restore(Path(args[1]), Path(args[2]), Path(args[3]))
        else:
            raise ValueError("usage: stage_snapshot.py capture REPO STAGE | restore SOURCE_STAGE REPO STAGE")
    except (OSError, ValueError, KeyError) as error:
        print(f"stage boundary: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
