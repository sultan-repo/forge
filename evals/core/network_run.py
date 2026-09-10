"""Run a benchmark agent with no network and one provider-only socket proxy.

Usage: network_run.py RUNTIME TIMEOUT PROXY_IMAGE AGENT_IMAGE [OPTIONS] -- COMMAND...
       network_run.py identity RUNTIME PROXY_IMAGE
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from container_run import interrupted, run_container
from network_proxy import source_identity

HERE = Path(__file__).resolve().parent


def runtime_command(runtime: str, arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [runtime, *arguments], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, check=check, timeout=30,
    )


def local_identity(runtime: str, image: str) -> dict[str, str]:
    image_id = runtime_command(runtime, ["image", "inspect", image, "--format", "{{.Id}}"]).stdout.strip()
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise ValueError("network image identity could not be resolved")
    identity = {
        **source_identity(),
        "wrapper_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "lifecycle_source_sha256": hashlib.sha256((HERE / "container_run.py").read_bytes()).hexdigest(),
        "proxy_image_id": image_id,
    }
    identity["network_identity_sha256"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    expected = os.environ.get("BENCH_EXPECT_NETWORK_IDENTITY_SHA256")
    if expected and identity["network_identity_sha256"] != expected:
        raise ValueError("network boundary differs from the frozen identity")
    return identity


def verify_baked_identity(payload: dict[str, object], expected: dict[str, str]) -> None:
    for key in source_identity():
        if payload.get(key) != expected[key]:
            raise ValueError(f"network image has stale or modified {key}; rebuild and refreeze")


def verify_identity(runtime: str, image: str) -> dict[str, str]:
    identity = local_identity(runtime, image)
    result = runtime_command(runtime, [
        "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", identity["proxy_image_id"],
        "python3", "/proxy/network_proxy.py", "--identity",
    ])
    verify_baked_identity(json.loads(result.stdout), identity)
    return identity


def validate_container_options(options: list[str]) -> None:
    """Accept only options used by this harness, never networking/namespace overrides."""
    flags = {"--read-only", "-i", "--interactive"}
    values = {
        "-v", "--volume", "-w", "--workdir", "-e", "--env", "--tmpfs",
        "--pids-limit", "--memory", "--cpus", "--user", "--cap-drop", "--security-opt",
    }
    index = 0
    while index < len(options):
        option = options[index]
        if option in flags:
            index += 1
            continue
        if option not in values or index + 1 >= len(options):
            raise ValueError(f"unsupported agent container option: {option}")
        value = options[index + 1]
        if option == "--cap-drop" and value != "ALL":
            raise ValueError("all agent capabilities must be dropped")
        if option == "--security-opt" and value not in {"no-new-privileges", "no-new-privileges:true"}:
            raise ValueError("security policy cannot be weakened")
        if option in {"-v", "--volume", "--tmpfs"} and "/forge-egress" in value:
            raise ValueError("the network helper mount is reserved")
        index += 2


def run_agent(runtime: str, timeout: float, proxy_image: str, agent_image: str,
              options: list[str], command: list[str]) -> int:
    validate_container_options(options)
    if not command or timeout <= 0:
        raise ValueError("agent command and positive timeout are required")
    started = time.monotonic()
    identity = local_identity(runtime, proxy_image)
    suffix = uuid.uuid4().hex
    proxy_name = "forge-bench-egress-" + suffix
    volume_name = "forge-bench-egress-" + suffix
    volume_created = False
    proxy_created = False
    agent_started: float | None = None
    agent_finished: float | None = None
    exit_code: int | None = None
    try:
        volume_created = True
        runtime_command(runtime, ["volume", "create", "--label", "forge.benchmark.egress=1", volume_name])
        proxy_created = True
        runtime_command(runtime, [
            "run", "-d", "--name", proxy_name, "--rm", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "96", "--memory", "128m", "--cpus", "0.5",
            "-v", f"{volume_name}:/socket:rw", identity["proxy_image_id"],
            "python3", "/proxy/network_proxy.py", "--socket", "/socket/provider.sock",
        ])
        deadline = time.monotonic() + 15
        while True:
            logs = runtime_command(runtime, ["logs", proxy_name]).stdout.splitlines()
            ready = next((json.loads(line) for line in logs if line.startswith('{"')), None)
            if ready is not None:
                if ready.get("ready") is not True:
                    raise ValueError("provider proxy did not declare readiness")
                verify_baked_identity(ready, identity)
                break
            if time.monotonic() >= deadline:
                raise ValueError("provider proxy did not become ready")
            time.sleep(0.1)
        agent_started = time.monotonic()
        exit_code = run_container(runtime, timeout, [
            *options, "--network", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "-v", f"{volume_name}:/forge-egress/socket:ro",
            "-v", f"{HERE / 'network_client.py'}:/forge-egress/network_client.py:ro",
            agent_image, "python3", "/forge-egress/network_client.py",
            "/forge-egress/socket/provider.sock", *command,
        ])
        agent_finished = time.monotonic()
        return exit_code
    finally:
        if agent_started is not None and agent_finished is None:
            agent_finished = time.monotonic()
        # The agent's named container is removed by run_container before this
        # socket/proxy pair is removed, including on timeout and interruption.
        try:
            if proxy_created:
                runtime_command(runtime, ["rm", "-f", proxy_name], check=False)
            if volume_created:
                cleanup = runtime_command(runtime, ["volume", "rm", "-f", volume_name], check=False)
                if cleanup.returncode and runtime_command(runtime, ["volume", "inspect", volume_name], check=False).returncode == 0:
                    raise RuntimeError(f"could not remove benchmark socket volume {volume_name}")
        finally:
            evidence_path = os.environ.get("BENCH_NETWORK_EVIDENCE")
            if evidence_path:
                finished = time.monotonic()
                agent_finished = agent_finished or finished
                evidence: dict[str, object] = {
                    "identity": identity,
                    "resources": {"proxy_container": proxy_name, "socket_volume": volume_name},
                    "setup_seconds": (agent_started or finished) - started,
                    "agent_wall_seconds": agent_finished - agent_started if agent_started is not None else None,
                    "total_wall_seconds": finished - started,
                    "exit_code": exit_code,
                    "outcome": "setup_failed" if agent_started is None else (
                        "interrupted" if exit_code is None else "timeout" if exit_code == 124 else "completed"
                    ),
                }
                destination = Path(evidence_path)
                descriptor, temporary = tempfile.mkstemp(prefix=".network-", dir=destination.parent)
                try:
                    with os.fdopen(descriptor, "w") as stream:
                        json.dump(evidence, stream, sort_keys=True, indent=2)
                        stream.write("\n")
                    os.replace(temporary, destination)
                finally:
                    Path(temporary).unlink(missing_ok=True)


def main(arguments: list[str]) -> int:
    try:
        if len(arguments) == 3 and arguments[0] == "identity":
            print(json.dumps(verify_identity(arguments[1], arguments[2]), sort_keys=True))
            return 0
        if len(arguments) < 6 or "--" not in arguments[4:]:
            raise ValueError(__doc__ or "invalid arguments")
        boundary = arguments.index("--", 4)
        return run_agent(arguments[0], float(arguments[1]), arguments[2], arguments[3],
                         arguments[4:boundary], arguments[boundary + 1:])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"benchmark network boundary: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    raise SystemExit(main(sys.argv[1:]))
