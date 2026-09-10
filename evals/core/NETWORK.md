# Benchmark network boundary

Public tests should remain readable. Encoding a public test bundle does not
hide it from a model that can download and decode it. Real benchmark agent
containers therefore run with `--network none`; the scorer also retains its
separate no-network container. The agent never receives the scorer tree.

## Permitted transport

`network_run.py` starts one disposable provider proxy container and a named
Docker volume containing its Unix socket. The agent mounts that volume
read-only. `network_client.py`, also mounted read-only outside the project,
forwards a loopback proxy port to the socket and launches Claude Code with
`HTTPS_PROXY` and related variables pointing to it. A named volume keeps the
socket inside the container runtime, including on Docker Desktop for macOS.

The agent has no Ethernet interface or route to the host or internet. Changing
proxy variables, using Bash/curl, direct IPs, IPv6, DNS, another proxy protocol,
or killing the forwarder does not provide another network path. Container
capabilities are dropped and privilege escalation is disabled. Each invocation
gets its own proxy and socket volume, removed after success, failure, timeout,
or handled interruption.

The proxy implements a narrow HTTP CONNECT transport:

- Exact hosts in `network_policy.json`, currently `api.anthropic.com` for
  inference and `platform.claude.com` for OAuth token refresh; port 443 only.
- Matching, clear TLS SNI in the initial ClientHello. Missing SNI, mismatched
  SNI, encrypted ClientHello, malformed handshakes, IP authorities, plain HTTP,
  duplicate/conflicting headers and CONNECT request bodies are refused.
- Provider DNS must resolve only to public unicast addresses. The proxy
  connects to those validated addresses without a second DNS lookup.

There are no wildcard hosts or environment flags that enable general network
access. Package installation and interactive account sign-in happen before
the frozen run. The proxy receives neither the agent workspace nor its
credentials. It relays TLS without decrypting or logging API request bodies.

Claude Code documents standard proxy variables and the two API/OAuth origins
in its [network requirements](https://code.claude.com/docs/en/network-config).
The wrapper disables nonessential traffic, hosted MCP connectors, and
artifacts; the runner additionally disables WebFetch and WebSearch. These
settings avoid optional provider features becoming alternate retrieval paths.
Interactive sign-in pages, package registries, GitHub, raw GitHub content,
documentation sites, MCP proxies and artifact origins are excluded. A changed
provider endpoint requires a reviewed policy change, new image and new frozen
identity; the harness does not automatically expand the allowlist.

## Identities and use

Build and inspect the proxy without credentials or a model invocation:

```bash
docker build -f evals/core/container/NetworkProxyContainerfile \
  -t forge-bench-egress:local evals/core
python3 evals/core/network_run.py identity docker forge-bench-egress:local
```

Identity output includes the resolved proxy image ID and SHA-256 hashes of
the policy, proxy, forwarder, wrapper and imported container lifecycle helper,
plus a canonical
`network_identity_sha256`. Image-baked sources must match the checkout.
`BENCH_EXPECT_NETWORK_IDENTITY_SHA256` rejects changed local sources or image
identity before a session can begin. Each proxy also emits its baked source
hashes at startup; the wrapper compares them before launching the agent.

The runner invokes the wrapper as follows:

```text
python3 network_run.py RUNTIME TIMEOUT PROXY_IMAGE AGENT_IMAGE [CONTAINER_OPTIONS] -- COMMAND [ARGUMENTS]
```

Networking, namespace, privileged, entrypoint and capability-adding options
cannot be passed through. `BENCH_NETWORK_EVIDENCE` names a host-written JSON
record containing the identity, proxy setup time, agent/container wall time,
total wrapper time and exit disposition. Preserve total elapsed time in
comparisons and report proxy setup separately; infrastructure is not free.

## Validation and limits

Unit tests cover allowed requests with a local fake upstream, real TLS
ClientHello parsing and fragmentation, rejected destinations and DNS results,
override refusal, frozen identity changes, cleanup and timing evidence.
Docker tests exercise the production wrapper and socket volume: direct
IPv4/IPv6/host access fails, GitHub/raw requests and mismatched SNI are denied,
the socket mount is read-only, and success/timeout remove the proxy and volume.
They never connect to a provider or use account credentials. Run them with:

```bash
BENCH_NETWORK_IMAGE=forge-bench-egress:local python3 -m pytest -q \
  tests/test_benchmark_network.py tests/test_benchmark_network_isolation.py
```

Docker is validated locally and in CI. The interface uses Docker/Podman common
operations, but Podman requires its own isolation checks before publishing
results from that runtime. A process killed with SIGKILL or a host/runtime
crash cannot execute cleanup; containers named `forge-bench-egress-*` and
volumes labelled `forge.benchmark.egress=1` identify interrupted resources.
Do not remove resources belonging to a concurrent run.

This boundary prevents ordinary agent-side retrieval of public evaluation
sources through general network tools. It is not proof against training-data
contamination, an adversarial model abusing allowed provider APIs, a compromised
runtime/provider, or application-layer routing within an allowed TLS origin.
The proxy checks the CONNECT destination and clear SNI, not encrypted HTTP
paths or Host headers. Provider-mediated retrieval remains a reason to audit
transcripts and use fresh holdout tasks. No live Claude subscription session
has been run to validate this transport in this change; protocol compatibility
and offline isolation are the established evidence.
