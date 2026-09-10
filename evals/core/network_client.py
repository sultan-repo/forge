"""Start a loopback-to-Unix proxy transport and run the benchmark CLI.

This file is mounted read-only outside the project. Removing its environment
or killing its forwarder cannot grant egress: the container has network none.
"""
from __future__ import annotations

import os
import selectors
import signal
import socket
import socketserver
import subprocess
import sys
import threading


class Forwarder(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    request_queue_size = 32


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("usage: network_client.py SOCKET COMMAND [ARGUMENTS...]")
    path = sys.argv[1]

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
                    upstream.connect(path)
                    with selectors.DefaultSelector() as selector:
                        selector.register(self.request, selectors.EVENT_READ, upstream)
                        selector.register(upstream, selectors.EVENT_READ, self.request)
                        while events := selector.select(timeout=300):
                            for key, _mask in events:
                                source = key.fileobj
                                assert isinstance(source, socket.socket)
                                data = source.recv(65536)
                                if not data:
                                    return
                                key.data.sendall(data)
            except OSError:
                return

    with Forwarder(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        environment = os.environ.copy()
        proxy = f"http://127.0.0.1:{server.server_address[1]}"
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            environment[name] = proxy
        environment["NO_PROXY"] = environment["no_proxy"] = ""
        # Suppress background updater/telemetry; only API inference is allowed.
        environment["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        environment["DISABLE_AUTOUPDATER"] = "1"
        environment["DISABLE_TELEMETRY"] = "1"
        environment["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
        environment["CLAUDE_CODE_DISABLE_ARTIFACT"] = "1"
        with subprocess.Popen(sys.argv[2:], env=environment) as process:
            def interrupt(signum: int, _frame: object) -> None:
                process.send_signal(signum)

            signal.signal(signal.SIGINT, interrupt)
            signal.signal(signal.SIGTERM, interrupt)
            try:
                return process.wait()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
