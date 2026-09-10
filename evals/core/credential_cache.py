"""Carry CLI token refreshes in a private run cache, never back into user credentials."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

MARKER = "forge-benchmark-credentials-v1"


def private_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("credential cache must be an owned private directory with mode 0700")


def credential_bytes(path: Path) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
        raise ValueError("credential input must be a bounded regular file, not a symlink")
    data = path.read_bytes()
    if not isinstance(json.loads(data), dict):
        raise TypeError("credential input must be a JSON object")
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".credential-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def metadata(cache: Path) -> dict[str, Any]:
    private_directory(cache)
    value = json.loads((cache / "metadata.json").read_text())
    if not isinstance(value, dict) or value.get("kind") != MARKER:
        raise ValueError("directory is not a Forge credential cache")
    return value


def init(source: Path, cache: Path) -> None:
    private_directory(cache)
    source = source.absolute()
    if (cache / "metadata.json").exists():
        current = metadata(cache)
        if current["source"] != str(source):
            raise ValueError("credential source changed; create a new private cache")
        return
    if any(cache.iterdir()):
        raise ValueError("new credential cache must be empty")
    data = credential_bytes(source)
    atomic_write(cache / "credentials.json", data)
    atomic_write(cache / "metadata.json", json.dumps({
        "kind": MARKER, "source": str(source), "source_sha256": digest(data),
    }).encode())


def refresh_source(cache: Path) -> dict[str, Any]:
    current = metadata(cache)
    data = credential_bytes(Path(current["source"]))
    if digest(data) != current["source_sha256"]:
        # A separate login/CLI refreshed the original. Adopt it at the next
        # boundary, never overwrite it with a potentially stale session copy.
        atomic_write(cache / "credentials.json", data)
        current["source_sha256"] = digest(data)
        atomic_write(cache / "metadata.json", json.dumps(current).encode())
    return current


def copy_to_config(cache: Path, config: Path) -> None:
    current = refresh_source(cache)
    if config.is_symlink() or not config.is_dir():
        raise ValueError("session config must be a directory")
    atomic_write(config / ".credentials.json", credential_bytes(cache / "credentials.json"))
    # Store the snapshot outside the agent mount so agent text cannot authorize
    # replacing a newer source credential or alter the controller's identity.
    atomic_write(cache / "active.json", json.dumps({
        "config": str(config.resolve()), "source_sha256": current["source_sha256"],
    }).encode())


def handoff(cache: Path, config: Path) -> None:
    current = metadata(cache)
    active = json.loads((cache / "active.json").read_text())
    if active["config"] != str(config.resolve()):
        raise ValueError("credential handoff does not match the active session")
    source = credential_bytes(Path(current["source"]))
    if digest(source) != active["source_sha256"]:
        refresh_source(cache)
        return
    updated = credential_bytes(config / ".credentials.json")
    atomic_write(cache / "credentials.json", updated)


def cleanup(cache: Path) -> None:
    metadata(cache)
    shutil.rmtree(cache)


def main(args: list[str]) -> int:
    try:
        if len(args) == 3 and args[0] == "init":
            init(Path(args[1]), Path(args[2]))
        elif len(args) == 3 and args[0] in {"copy", "handoff"}:
            operation = copy_to_config if args[0] == "copy" else handoff
            operation(Path(args[1]), Path(args[2]))
        elif len(args) == 2 and args[0] == "cleanup":
            cleanup(Path(args[1]))
        else:
            raise ValueError("usage: credential_cache.py init SOURCE CACHE | copy CACHE CONFIG | handoff CACHE CONFIG | cleanup CACHE")
    except (OSError, ValueError, TypeError, KeyError) as error:
        # Never include JSON decoder excerpts or file contents in diagnostics.
        print(f"credential cache operation failed ({type(error).__name__}); inspect private cache/source permissions and identity", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
