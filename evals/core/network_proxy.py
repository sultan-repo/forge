"""Provider-only CONNECT proxy, reached through a Docker-volume Unix socket.

The agent has --network none. This is its only external transport. The proxy
does not receive provider credentials, terminate TLS, or log request bodies.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import selectors
import socket
import socketserver
import struct
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MAX_HELLO = 65536


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_identity() -> dict[str, str]:
    return {
        "policy_sha256": sha256(HERE / "network_policy.json"),
        "proxy_source_sha256": sha256(HERE / "network_proxy.py"),
        "client_source_sha256": sha256(HERE / "network_client.py"),
    }


def load_policy(path: Path) -> frozenset[str]:
    policy = json.loads(path.read_text())
    if (
        policy.get("version") != 1
        or policy.get("allowed_port") != 443
        or policy.get("require_public_address") is not True
        or policy.get("require_matching_sni") is not True
    ):
        raise ValueError("unsupported or weakened network policy")
    hosts = policy.get("allowed_tls_hosts")
    if not isinstance(hosts, list) or not hosts:
        raise ValueError("network policy needs explicit TLS hosts")
    if any(not isinstance(h, str) or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)+", h) for h in hosts):
        raise ValueError("wildcards, IP literals and noncanonical hosts are forbidden")
    for host in hosts:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            continue
        raise ValueError("IP literals are forbidden")
    return frozenset(hosts)


def connect_host(header: bytes, allowed: frozenset[str]) -> str:
    """Strictly parse one CONNECT request; reject alternate proxy protocols."""
    if len(header) > 8192 or not header.endswith(b"\r\n\r\n"):
        raise ValueError("invalid proxy header")
    lines = header.decode("ascii", errors="strict").split("\r\n")
    request = re.fullmatch(r"CONNECT ([a-zA-Z0-9.-]+):443 HTTP/1\.[01]", lines[0])
    if request is None:
        raise ValueError("only CONNECT to an explicit TLS host on port 443 is permitted")
    host = request.group(1).lower()
    if host not in allowed:
        raise ValueError("destination is outside provider policy")
    seen: set[str] = set()
    for line in lines[1:-2]:
        name, separator, value = line.partition(":")
        name = name.lower()
        if not separator or not re.fullmatch(r"[a-z][a-z0-9-]*", name) or name in seen:
            raise ValueError("invalid or duplicate proxy header")
        seen.add(name)
        if name == "host" and value.strip().lower() != host + ":443":
            raise ValueError("conflicting proxy Host")
        if name == "transfer-encoding" or (name == "content-length" and value.strip() != "0"):
            raise ValueError("CONNECT bodies are forbidden")
    return host


def recv_exact(connection: socket.socket, count: int) -> bytes:
    result = bytearray()
    while len(result) < count:
        chunk = connection.recv(count - len(result))
        if not chunk:
            raise ValueError("truncated TLS hello")
        result.extend(chunk)
    return bytes(result)


def hello_sni(hello: bytes) -> str:
    """Extract clear SNI from one complete ClientHello; malformed/ECH fails closed."""
    if len(hello) < 4 or hello[0] != 1 or int.from_bytes(hello[1:4], "big") != len(hello) - 4:
        raise ValueError("expected exactly one ClientHello")
    offset = 4

    def take(count: int) -> bytes:
        nonlocal offset
        if count < 0 or offset + count > len(hello):
            raise ValueError("malformed TLS hello")
        part = hello[offset:offset + count]
        offset += count
        return part

    take(34)  # legacy_version, random
    take(take(1)[0])
    cipher_length = int.from_bytes(take(2), "big")
    if cipher_length == 0 or cipher_length % 2:
        raise ValueError("invalid cipher suites")
    take(cipher_length)
    take(take(1)[0])
    extensions_length = int.from_bytes(take(2), "big")
    if offset + extensions_length != len(hello):
        raise ValueError("invalid extensions length")
    names: list[str] = []
    seen_extensions: set[int] = set()
    while offset < len(hello):
        kind = int.from_bytes(take(2), "big")
        body = take(int.from_bytes(take(2), "big"))
        if kind in seen_extensions or kind == 0xFE0D:
            raise ValueError("duplicate extension or encrypted ClientHello")
        seen_extensions.add(kind)
        if kind == 0:
            if len(body) < 5 or int.from_bytes(body[:2], "big") != len(body) - 2:
                raise ValueError("invalid SNI list")
            if body[2] != 0 or int.from_bytes(body[3:5], "big") != len(body) - 5:
                raise ValueError("exactly one DNS SNI is required")
            names.append(body[5:].decode("ascii").lower())
    if len(names) != 1:
        raise ValueError("one clear SNI is required")
    return names[0]


def read_client_hello(connection: socket.socket, expected_host: str) -> bytes:
    records = bytearray()
    handshake = bytearray()
    while len(records) < MAX_HELLO:
        header = recv_exact(connection, 5)
        content_type, major, _minor, length = struct.unpack("!BBBH", header)
        if content_type != 22 or major != 3 or not 0 < length <= 18432:
            raise ValueError("only a TLS handshake may follow CONNECT")
        body = recv_exact(connection, length)
        records.extend(header + body)
        handshake.extend(body)
        if len(handshake) >= 4:
            expected_length = 4 + int.from_bytes(handshake[1:4], "big")
            if expected_length > MAX_HELLO:
                raise ValueError("TLS hello exceeds limit")
            if len(handshake) >= expected_length:
                if hello_sni(bytes(handshake[:expected_length])) != expected_host:
                    raise ValueError("TLS SNI differs from permitted CONNECT destination")
                if len(handshake) != expected_length:
                    raise ValueError("extra handshake messages before server reply")
                return bytes(records)
    raise ValueError("TLS hello exceeds limit")


def public_addresses(host: str) -> list[tuple[Any, ...]]:
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("provider DNS returned no addresses")
    for _family, _kind, _protocol, _canonical, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if (
            not ip.is_global or ip.is_multicast or ip.is_reserved
            or (isinstance(ip, ipaddress.IPv6Address) and (
                ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None
            ))
        ):
            raise ValueError("provider DNS returned a nonpublic address")
    return addresses


def open_provider(host: str) -> socket.socket:
    # Connect to the validated address itself, never resolve a second time.
    last_error: OSError | None = None
    for family, kind, protocol, _canonical, address in public_addresses(host):
        upstream = socket.socket(family, kind, protocol)
        upstream.settimeout(15)
        try:
            upstream.connect(address)
            return upstream
        except OSError as error:
            last_error = error
            upstream.close()
    raise OSError("provider connection failed") from last_error


def relay(left: socket.socket, right: socket.socket) -> None:
    with selectors.DefaultSelector() as selector:
        selector.register(left, selectors.EVENT_READ, right)
        selector.register(right, selectors.EVENT_READ, left)
        while events := selector.select(timeout=300):
            for key, _mask in events:
                source = key.fileobj
                assert isinstance(source, socket.socket)
                data = source.recv(65536)
                if not data:
                    return
                key.data.sendall(data)


def serve_connection(connection: socket.socket, allowed: frozenset[str]) -> None:
    connection.settimeout(15)
    acknowledged = False
    try:
        header = bytearray()
        while not header.endswith(b"\r\n\r\n") and len(header) <= 8192:
            header.extend(recv_exact(connection, 1))
        host = connect_host(bytes(header), allowed)
        connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        acknowledged = True
        hello = read_client_hello(connection, host)
        with open_provider(host) as upstream:
            upstream.sendall(hello)
            relay(connection, upstream)
    except (OSError, ValueError, UnicodeError):
        if not acknowledged:
            try:
                connection.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass


class ProxyServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 32


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", action="store_true")
    parser.add_argument("--socket", type=Path)
    args = parser.parse_args()
    allowed = load_policy(HERE / "network_policy.json")
    if args.identity:
        print(json.dumps(source_identity(), sort_keys=True))
        return 0
    if args.socket is None:
        parser.error("--socket is required")

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            serve_connection(self.request, allowed)

    with ProxyServer(str(args.socket), Handler) as server:
        args.socket.chmod(0o666)  # agent is unprivileged; volume is read-only there
        print(json.dumps({"ready": True, **source_identity()}, sort_keys=True), flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
