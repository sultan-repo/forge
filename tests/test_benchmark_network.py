from __future__ import annotations

import importlib
import json
import socket
import ssl
import struct
import subprocess
import sys
import threading
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / "evals" / "core"
sys.path.insert(0, str(CORE))
proxy = importlib.import_module("network_proxy")
runner = importlib.import_module("network_run")
sys.path.pop(0)
ALLOWED = frozenset({"api.anthropic.com"})


def client_hello(host: str) -> bytes:
    context = ssl.create_default_context()
    outgoing = ssl.MemoryBIO()
    connection = context.wrap_bio(ssl.MemoryBIO(), outgoing, server_hostname=host)
    with pytest.raises(ssl.SSLWantReadError):
        connection.do_handshake()
    return outgoing.read()


def test_policy_is_explicit_provider_only() -> None:
    assert proxy.load_policy(CORE / "network_policy.json") == frozenset({"api.anthropic.com", "platform.claude.com"})


@pytest.mark.parametrize("changed", [
    {"allowed_tls_hosts": ["*.anthropic.com"]},
    {"allowed_tls_hosts": ["127.0.0.1"]},
    {"allowed_tls_hosts": []},
    {"require_public_address": False},
    {"require_matching_sni": False},
    {"allowed_port": 80},
])
def test_weakened_policy_is_refused(tmp_path: Path, changed: dict[str, object]) -> None:
    policy = json.loads((CORE / "network_policy.json").read_text())
    policy.update(changed)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(ValueError):
        proxy.load_policy(path)


def test_standard_connect_is_allowed() -> None:
    assert proxy.connect_host(b"CONNECT api.anthropic.com:443 HTTP/1.0\r\n\r\n", ALLOWED) == "api.anthropic.com"
    assert proxy.connect_host(
        b"CONNECT API.ANTHROPIC.COM:443 HTTP/1.1\r\nHost: api.anthropic.com:443\r\n\r\n", ALLOWED,
    ) == "api.anthropic.com"


@pytest.mark.parametrize("wire_request", [
    "CONNECT github.com:443 HTTP/1.1\r\n\r\n",
    "CONNECT raw.githubusercontent.com:443 HTTP/1.1\r\n\r\n",
    "CONNECT api.anthropic.com.evil.test:443 HTTP/1.1\r\n\r\n",
    "CONNECT api.anthropic.com.:443 HTTP/1.1\r\n\r\n",
    "CONNECT api.anthropic.com:80 HTTP/1.1\r\n\r\n",
    "CONNECT api.anthropic.com:0443 HTTP/1.1\r\n\r\n",
    "CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n",
    "CONNECT [::1]:443 HTTP/1.1\r\n\r\n",
    "CONNECT api.anthropic.com@github.com:443 HTTP/1.1\r\n\r\n",
    "GET https://api.anthropic.com/ HTTP/1.1\r\n\r\n",
    "CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: github.com:443\r\n\r\n",
    "CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: api.anthropic.com:443\r\nHost: github.com:443\r\n\r\n",
    "CONNECT api.anthropic.com:443 HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
    "CONNECT api.anthropic.com:443 HTTP/1.1\r\nContent-Length: 99\r\n\r\n",
    "CONNECT api.anthropic.com:443 HTTP/1.1\r\n Header: folded\r\n\r\n",
])
def test_forbidden_destinations_and_proxy_smuggling_fail(wire_request: str) -> None:
    with pytest.raises(ValueError):
        proxy.connect_host(wire_request.encode(), ALLOWED)


@pytest.mark.parametrize("host", ["github.com", "api.anthropic.com.evil.test", "127.0.0.1"])
def test_tls_sni_must_match_allowed_connect(host: str) -> None:
    left, right = socket.socketpair()
    with left, right:
        left.sendall(client_hello(host))
        with pytest.raises(ValueError):
            proxy.read_client_hello(right, "api.anthropic.com")


def test_real_client_hello_can_span_tls_records() -> None:
    original = client_hello("api.anthropic.com")
    body = original[5:]
    records = b"".join(struct.pack("!BBBH", 22, 3, 1, len(part)) + part for part in (body[:7], body[7:]))
    left, right = socket.socketpair()
    with left, right:
        left.sendall(records)
        assert proxy.read_client_hello(right, "api.anthropic.com") == records


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.1", "172.17.0.1", "192.168.1.1", "169.254.169.254",
    "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "ff02::1", "::ffff:8.8.8.8",
    "2002:0a00:0001::1",
])
def test_private_and_special_provider_dns_is_rejected(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    monkeypatch.setattr(proxy.socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)),
    ])
    with pytest.raises(ValueError):
        proxy.public_addresses("api.anthropic.com")


def test_proxy_permits_matching_tls_to_local_fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the actual parser/relay with a fake upstream, without internet."""
    client, proxy_side = socket.socketpair()
    upstream, fake_provider = socket.socketpair()
    opened: list[str] = []

    def open_fake(host: str) -> socket.socket:
        opened.append(host)
        return upstream

    monkeypatch.setattr(proxy, "open_provider", open_fake)
    handler = threading.Thread(target=proxy.serve_connection, args=(proxy_side, ALLOWED), daemon=True)
    handler.start()
    with client, proxy_side, fake_provider:
        client.settimeout(3)
        fake_provider.settimeout(3)
        client.sendall(b"CONNECT api.anthropic.com:443 HTTP/1.1\r\n\r\n")
        assert b"200 Connection Established" in client.recv(4096)
        hello = client_hello("api.anthropic.com")
        client.sendall(hello)
        assert proxy.recv_exact(fake_provider, len(hello)) == hello
        fake_provider.sendall(b"fake-provider-response")
        assert client.recv(4096) == b"fake-provider-response"
        assert opened == ["api.anthropic.com"]
        client.shutdown(socket.SHUT_RDWR)
        handler.join(timeout=3)
        assert not handler.is_alive()


def test_forbidden_connect_never_resolves_or_opens_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(_host: str) -> socket.socket:
        raise AssertionError("forbidden host reached DNS/upstream")

    monkeypatch.setattr(proxy, "open_provider", forbidden)
    client, proxy_side = socket.socketpair()
    with client, proxy_side:
        client.sendall(b"CONNECT raw.githubusercontent.com:443 HTTP/1.1\r\n\r\n")
        proxy.serve_connection(proxy_side, ALLOWED)
        assert b"403 Forbidden" in client.recv(4096)


@pytest.mark.parametrize("options", [
    ["--network", "host"], ["--network=host"], ["--privileged"], ["--cap-add", "NET_ADMIN"],
    ["--entrypoint", "sh"], ["--pid", "host"], ["--device", "/dev/net/tun"],
    ["--security-opt", "seccomp=unconfined"], ["-v", "/tmp:/forge-egress/socket"],
])
def test_wrapper_refuses_network_and_namespace_overrides(options: list[str]) -> None:
    with pytest.raises(ValueError):
        runner.validate_container_options(options)


def test_frozen_identity_detects_policy_or_source_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        stdout = "sha256:" + "a" * 64

    monkeypatch.setattr(runner, "runtime_command", lambda *_args, **_kwargs: Result())
    original = runner.local_identity("docker", "test")
    monkeypatch.setenv("BENCH_EXPECT_NETWORK_IDENTITY_SHA256", original["network_identity_sha256"])
    monkeypatch.setattr(runner, "source_identity", lambda: {"policy_sha256": "changed"})
    with pytest.raises(ValueError, match="frozen identity"):
        runner.local_identity("docker", "test")


def test_frozen_identity_detects_container_lifecycle_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        stdout = "sha256:" + "a" * 64

    monkeypatch.setattr(runner, "runtime_command", lambda *_args, **_kwargs: Result())
    original = runner.local_identity("docker", "test")
    monkeypatch.setenv("BENCH_EXPECT_NETWORK_IDENTITY_SHA256", original["network_identity_sha256"])
    read_bytes = Path.read_bytes

    def changed_lifecycle(path: Path) -> bytes:
        if path == CORE / "container_run.py":
            return b"modified container launch arguments"
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", changed_lifecycle)
    with pytest.raises(ValueError, match="frozen identity"):
        runner.local_identity("docker", "test")


def test_proxy_startup_failure_cleans_known_container_and_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def runtime(_runtime: str, arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[:2] == ["run", "-d"]:
            raise subprocess.CalledProcessError(1, ["fake-runtime"])
        return subprocess.CompletedProcess(arguments, 0, "sha256:" + "a" * 64, "")

    monkeypatch.setattr(runner, "runtime_command", runtime)
    with pytest.raises(subprocess.CalledProcessError):
        runner.run_agent("fake", 30, "proxy", "agent", [], ["true"])
    assert any(call[:2] == ["rm", "-f"] for call in calls)
    assert any(call[:3] == ["volume", "rm", "-f"] for call in calls)


def test_network_setup_and_task_time_are_separately_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_path = tmp_path / "network.json"
    monkeypatch.setenv("BENCH_NETWORK_EVIDENCE", str(evidence_path))

    def runtime(_runtime: str, arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output = json.dumps({"ready": True, **proxy.source_identity()}) if arguments[0] == "logs" else "sha256:" + "a" * 64
        return subprocess.CompletedProcess(arguments, 0, output, "")

    def agent(_runtime: str, _timeout: float, arguments: list[str]) -> int:
        assert arguments[arguments.index("--network") + 1] == "none"
        assert any("/forge-egress/socket:ro" in argument for argument in arguments)
        return 124

    monkeypatch.setattr(runner, "runtime_command", runtime)
    monkeypatch.setattr(runner, "run_container", agent)
    assert runner.run_agent("fake", 30, "proxy", "agent", [], ["true"]) == 124
    evidence = json.loads(evidence_path.read_text())
    assert evidence["outcome"] == "timeout"
    assert evidence["exit_code"] == 124
    assert evidence["setup_seconds"] >= 0
    assert evidence["agent_wall_seconds"] >= 0
    assert evidence["total_wall_seconds"] >= evidence["agent_wall_seconds"] + evidence["setup_seconds"]
    assert evidence["identity"]["policy_sha256"] == proxy.source_identity()["policy_sha256"]


def test_stale_baked_policy_is_refused() -> None:
    expected = proxy.source_identity()
    with pytest.raises(ValueError, match="stale or modified"):
        runner.verify_baked_identity({**expected, "policy_sha256": "old"}, expected)
