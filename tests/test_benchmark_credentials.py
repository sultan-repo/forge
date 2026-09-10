"""Private credential refresh continuity with synthetic secrets only."""
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / "evals/core"
spec = importlib.util.spec_from_file_location("credential_cache", CORE / "credential_cache.py")
assert spec and spec.loader
cache_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache_module)


def setup_cache(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"synthetic": "original"}))
    cache = tmp_path / "private"
    cache.mkdir(mode=0o700)
    config = tmp_path / "config"
    config.mkdir()
    cache_module.init(source, cache)
    return source, cache, config


def test_refresh_is_carried_forward_without_changing_user_source(tmp_path: Path) -> None:
    source, cache, config = setup_cache(tmp_path)
    original = source.read_bytes()
    cache_module.copy_to_config(cache, config)
    refreshed = json.dumps({"synthetic": "session-refresh"}).encode()
    (config / ".credentials.json").write_bytes(refreshed)
    cache_module.handoff(cache, config)
    cache_module.init(source, cache)  # resume must preserve the refresh
    second = tmp_path / "next-config"
    second.mkdir()
    cache_module.copy_to_config(cache, second)
    assert (second / ".credentials.json").read_bytes() == refreshed
    assert source.read_bytes() == original
    assert stat.S_IMODE((cache / "credentials.json").stat().st_mode) == 0o600
    cache_module.cleanup(cache)
    assert not cache.exists() and source.read_bytes() == original


def test_external_login_wins_over_stale_session_handoff(tmp_path: Path) -> None:
    source, cache, config = setup_cache(tmp_path)
    cache_module.copy_to_config(cache, config)
    source.write_text(json.dumps({"synthetic": "new-host-login"}))
    (config / ".credentials.json").write_text(json.dumps({"synthetic": "stale-session"}))
    cache_module.handoff(cache, config)
    assert (cache / "credentials.json").read_bytes() == source.read_bytes()
    assert "new-host-login" in source.read_text()


def test_external_login_before_next_cell_is_adopted(tmp_path: Path) -> None:
    source, cache, config = setup_cache(tmp_path)
    source.write_text(json.dumps({"synthetic": "external"}))
    cache_module.copy_to_config(cache, config)
    assert (config / ".credentials.json").read_bytes() == source.read_bytes()


def test_symlink_handoff_cannot_read_unrelated_file(tmp_path: Path) -> None:
    source, cache, config = setup_cache(tmp_path)
    cache_module.copy_to_config(cache, config)
    (config / ".credentials.json").unlink()
    (config / ".credentials.json").symlink_to(source)
    with pytest.raises(ValueError, match="regular file"):
        cache_module.handoff(cache, config)


def test_cache_rejects_nonprivate_directory_and_unmarked_cleanup(tmp_path: Path) -> None:
    source, cache, _ = setup_cache(tmp_path)
    os.chmod(cache, 0o755)
    with pytest.raises(ValueError, match="private directory"):
        cache_module.init(source, cache)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(mode=0o700)
    (unrelated / "keep").write_text("user data")
    with pytest.raises(OSError):
        cache_module.cleanup(unrelated)
    assert (unrelated / "keep").exists()


def test_invalid_secret_is_never_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source, cache, _ = setup_cache(tmp_path)
    cache_module.cleanup(cache)
    cache.mkdir(mode=0o700)
    source.write_text("synthetic-sensitive-value-not-json")
    assert cache_module.main(["init", str(source), str(cache)]) == 2
    assert "synthetic-sensitive-value" not in capsys.readouterr().err
