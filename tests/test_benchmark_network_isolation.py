"""Real Docker transport tests. No provider request or credential is used."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / "evals" / "core"
IMAGE = os.environ.get("BENCH_NETWORK_IMAGE", "forge-bench-egress:ci")


def docker_ready() -> bool:
    return shutil.which("docker") is not None and subprocess.run(
        ["docker", "info"], capture_output=True, check=False,
    ).returncode == 0


@pytest.mark.skipif(not docker_ready(), reason="Docker is required for provider network isolation")
def test_agent_has_no_direct_egress_and_provider_proxy_denies_repository_access(tmp_path: Path) -> None:
    # The proxy image is also a sufficient credential-free Python agent image.
    # Deliberately leave all network variables inherited: the wrapper replaces
    # them, and even unsetting them cannot defeat --network none.
    script = r'''
import json, os, socket, ssl, urllib.request
from urllib.parse import urlsplit
def cannot_connect(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        try:
            connection.connect((address, 443))
        except OSError:
            return True
        return False
assert all(cannot_connect(ip) for ip in ("1.1.1.1", "8.8.8.8", "172.17.0.1", "169.254.169.254", "2606:4700:4700::1111"))
assert os.environ["NO_PROXY"] == ""
endpoint = urlsplit(os.environ["HTTPS_PROXY"])
for host in ("github.com", "raw.githubusercontent.com", "127.0.0.1", "api.anthropic.com.evil.test"):
    with socket.create_connection((endpoint.hostname, endpoint.port), timeout=3) as connection:
        connection.sendall(f"CONNECT {host}:443 HTTP/1.1\r\n\r\n".encode())
        assert b"403 Forbidden" in connection.recv(4096)
# CONNECT to the allowed authority with a forbidden SNI must be closed before
# any DNS/provider connection. This tests domain-fronting at the TLS boundary.
with socket.create_connection((endpoint.hostname, endpoint.port), timeout=3) as connection:
    connection.sendall(b"CONNECT api.anthropic.com:443 HTTP/1.1\r\n\r\n")
    assert b"200 Connection Established" in connection.recv(4096)
    try:
        ssl.create_default_context().wrap_socket(connection, server_hostname="github.com")
    except (ssl.SSLError, OSError):
        pass
    else:
        raise AssertionError("mismatched TLS SNI escaped")
try:
    open("/forge-egress/socket/injected", "w").write("unsafe")
except OSError:
    pass
else:
    raise AssertionError("agent socket mount is writable")
print(json.dumps({"direct_egress": "denied", "forbidden_proxy_hosts": "denied", "mismatched_sni": "denied"}))
'''
    environment = {**os.environ, "BENCH_NETWORK_EVIDENCE": str(tmp_path / "network.json")}
    result = subprocess.run([
        sys.executable, str(CORE / "network_run.py"), "docker", "30", IMAGE, IMAGE,
        "--read-only", "--user", "10001:10001", "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777",
        "--", "python3", "-c", script,
    ], capture_output=True, text=True, check=False, timeout=90, env=environment)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["direct_egress"] == "denied"
    evidence = json.loads((tmp_path / "network.json").read_text())
    assert evidence["outcome"] == "completed"
    assert evidence["setup_seconds"] > 0
    assert evidence["agent_wall_seconds"] > 0
    for kind, resource in (("container", "proxy_container"), ("volume", "socket_volume")):
        inspected = subprocess.run([
            "docker", kind, "inspect", evidence["resources"][resource],
        ], capture_output=True, text=True, check=False)
        assert inspected.returncode != 0, f"proxy {kind} leaked"


@pytest.mark.skipif(not docker_ready(), reason="Docker is required for provider network cleanup")
def test_provider_proxy_and_socket_are_removed_after_agent_timeout(tmp_path: Path) -> None:
    environment = {**os.environ, "BENCH_NETWORK_EVIDENCE": str(tmp_path / "network.json")}
    result = subprocess.run([
        sys.executable, str(CORE / "network_run.py"), "docker", "1", IMAGE, IMAGE,
        "--", "python3", "-c", "import time; time.sleep(60)",
    ], capture_output=True, text=True, check=False, timeout=60, env=environment)
    assert result.returncode == 124, result.stderr
    evidence = json.loads((tmp_path / "network.json").read_text())
    assert evidence["outcome"] == "timeout"
    for kind, resource in (("container", "proxy_container"), ("volume", "socket_volume")):
        inspected = subprocess.run([
            "docker", kind, "inspect", evidence["resources"][resource],
        ], capture_output=True, text=True, check=False)
        assert inspected.returncode != 0, f"proxy {kind} leaked after timeout"
