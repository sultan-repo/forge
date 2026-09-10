#!/usr/bin/env bash
# Executable Forge benchmark runner.
# Real benchmark runs are fail-closed on four boundaries:
#   1) verified immutable Forge release provenance
#   2) agent isolation from scorer/hidden tests/other runs
#   3) isolated no-network scoring for all agent-modified code
#   4) Forge activation preflight before any Forge-arm cell is accepted
#
# Mock agents are trusted checked-in harness code and may use local scoring for self-tests only.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CALLER_DIR="$PWD"
cd "$HERE"

SCENARIOS="b1,b2,b3,b4"
CONDITIONS="baseline,forge"
RUNS=5
OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenarios|--conditions|--runs|--out)
      [[ $# -ge 2 && "$2" != --* ]] || { echo "missing value for $1" >&2; exit 2; }
      ;;
  esac
  case "$1" in
    --scenarios) SCENARIOS="$2"; shift 2 ;;
    --conditions) CONDITIONS="$2"; shift 2 ;;
    --runs) RUNS="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

: "${MAX_TURNS:=80}"
: "${AGENT_TIMEOUT:=2400}"
: "${SCORER_TIMEOUT:=1500}"
: "${PERMISSION_FLAGS:=--dangerously-skip-permissions}"
: "${FORGE_INVOCATION:=Use Forge for the following task.}"
: "${FORGE_REPO:=sultan-repo/forge}"
: "${BENCH_SEED:=1701}"
: "${CLAUDE_CODE_CHANNEL:=stable}"
: "${BENCH_AGENT_IMAGE:=forge-bench-agent:$CLAUDE_CODE_CHANNEL}"
# Include scorer source in the default tag so an older cached image can never
# silently score a newer controller run.
SCORER_SOURCE_SHA256="$(python3 - <<'PY'
import hashlib
from pathlib import Path

digest = hashlib.sha256()
names = ["container/ScorerContainerfile", "assert_run.py", "score_entrypoint.py", "fixture_bundle.py", "fixture_bundle.json.gz.b64", "fixture_supplements.json"]
names.extend(str(path) for path in sorted(Path("hidden").rglob("*.py")))
for name in names:
    digest.update(name.encode())
    digest.update(Path(name).read_bytes())
print(digest.hexdigest())
PY
)"
: "${BENCH_SCORER_IMAGE:=forge-bench-scorer:${SCORER_SOURCE_SHA256:0:16}}"
NETWORK_SOURCE_SHA256="$(python3 - <<'PY'
import hashlib
from pathlib import Path
digest = hashlib.sha256()
for name in ("container/NetworkProxyContainerfile", "network_policy.json", "network_proxy.py", "network_client.py", "network_run.py"):
    digest.update(name.encode())
    digest.update(Path(name).read_bytes())
print(digest.hexdigest())
PY
)"
: "${BENCH_NETWORK_IMAGE:=forge-bench-egress:${NETWORK_SOURCE_SHA256:0:16}}"
: "${BENCH_EXPECT_NETWORK_IMAGE_ID:=}" "${BENCH_EXPECT_NETWORK_IDENTITY_SHA256:=}"
# Fixture and criteria identity travel with every result so revisions cannot be pooled silently.
FIXTURE_VERSION="$(python3 - <<'PY'
from fixture_bundle import load_bundle
print(load_bundle().get("fixture_version", "unknown"))
PY
)"
export FIXTURE_VERSION

: "${BENCH_MOCK_AGENT:=}"
# Execution controls, normally set by evals/core/pilot_launch.py from a frozen manifest. All optional.
#   BENCH_LEDGER                 append-only session ledger; every agent session is checked before and recorded after
#   BENCH_INVOCATION_CEILING     maximum number of agent sessions (preflights and stages included)
#   BENCH_CEILING_EXCLUDES_UNREACHABLE=1   count the ceiling over sessions that reached the provider only
#   BENCH_USD_CEILING            optional spending ceiling on provider estimates (BENCH_SESSION_RESERVE_USD reserved per
#                                session); unset = no spending rule, estimates recorded as informational metrics only
#   BENCH_PINNED_MODEL           the main model every session must report; a mismatch is an infrastructure failure
#   BENCH_EXPECT_AGENT_IMAGE_ID / BENCH_EXPECT_SCORER_IMAGE_ID   image identities that must resolve exactly
#   BENCH_EXPECT_FORGE_SHA256 / BENCH_EXPECT_CANDIDATE_SHA256   runtime-projection hashes each installed config must match
#   BENCH_EXPECT_RUN_ORDER_SHA256  sha256 the generated RUN_ORDER.tsv must have
#   BENCH_CELL_FILTER            whitespace-separated "scenario/condition/run-N" cells to run (retries); order unchanged
#   BENCH_SCORER_LOCAL=1         test-only: score with the local scorer instead of the isolated container (recorded)
#   BENCH_MOCK_INFRA_FAIL        test-only, mock mode: cells whose agent session is replaced by a runtime failure
#   BENCH_MOCK_PROVIDER_LIMIT    test-only, mock mode: cells whose first session ends on a subscription usage limit
# A session that ends on a provider limit (subscription cap, rate limit, overload) pauses the run: PAUSED.json is
# written and run.sh exits 4; the launcher resumes the unscored cells after the reset. Not a failure.
: "${BENCH_LEDGER:=}" "${BENCH_INVOCATION_CEILING:=}" "${BENCH_USD_CEILING:=}" "${BENCH_SESSION_RESERVE_USD:=}"
: "${BENCH_PINNED_MODEL:=}" "${BENCH_EXPECT_AGENT_IMAGE_ID:=}" "${BENCH_EXPECT_SCORER_IMAGE_ID:=}"
: "${BENCH_EXPECT_FORGE_SHA256:=}" "${BENCH_EXPECT_CANDIDATE_SHA256:=}" "${BENCH_EXPECT_RUN_ORDER_SHA256:=}"
: "${BENCH_CEILING_EXCLUDES_UNREACHABLE:=}"
: "${BENCH_STAGE1_RECOVERY:=}"
: "${BENCH_CELL_FILTER:=}" "${BENCH_SCORER_LOCAL:=}" "${BENCH_MOCK_INFRA_FAIL:=}" "${BENCH_MOCK_USAGE_USD:=0.5}" "${BENCH_MOCK_PROVIDER_LIMIT:=}"
if [[ -n "$BENCH_LEDGER" ]]; then
  [[ -n "$BENCH_INVOCATION_CEILING" ]] || { echo "BENCH_LEDGER requires BENCH_INVOCATION_CEILING." >&2; exit 2; }
  if [[ -n "$BENCH_USD_CEILING" || -n "$BENCH_SESSION_RESERVE_USD" ]]; then
    [[ -n "$BENCH_USD_CEILING" && -n "$BENCH_SESSION_RESERVE_USD" ]] || {
      echo "a spending rule needs both BENCH_USD_CEILING and BENCH_SESSION_RESERVE_USD." >&2; exit 2; }
  fi
  [[ "$BENCH_LEDGER" == /* ]] || BENCH_LEDGER="$CALLER_DIR/$BENCH_LEDGER"
fi
python3 - "$SCENARIOS" "$CONDITIONS" "$RUNS" "$BENCH_SEED" "$MAX_TURNS" "$AGENT_TIMEOUT" "$SCORER_TIMEOUT" "$BENCH_MOCK_AGENT" <<'PY'
import sys

for label, value, allowed in (("scenarios", sys.argv[1], {"b1", "b2", "b3", "b4", "b4n", "b4a", "q4", "s2", "v1"}),
                              ("conditions", sys.argv[2], {"baseline", "forge", "candidate"})):
    items = value.split(",")
    if not set(items) <= allowed or len(items) != len(set(items)):
        raise SystemExit(f"invalid or duplicate {label}: {value}")
for label, value in zip(("runs", "seed", "max turns", "agent timeout", "scorer timeout"), sys.argv[3:8]):
    try:
        number = int(value)
    except ValueError:
        raise SystemExit(f"{label} must be an integer") from None
    if label != "seed" and number <= 0:
        raise SystemExit(f"{label} must be positive")
if sys.argv[8] not in ("", "reference", "noop", "drifter"):
    raise SystemExit("unknown BENCH_MOCK_AGENT")
PY
if [[ -z "$OUT" ]]; then
  mkdir -p "$HERE/results"
  OUT="$(mktemp -d "$HERE/results/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
else
  [[ "$OUT" == /* ]] || OUT="$CALLER_DIR/$OUT"
  python3 - "$OUT" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.mkdir(parents=True, exist_ok=True)
if any(path.iterdir()):
    raise SystemExit(f"output directory must be empty to preserve existing evidence: {path}")
PY
fi
OUT="$(cd "$OUT" && pwd)"
# Claim even an explicitly supplied empty output before writing any evidence.
mkdir "$OUT/.running" || { echo "output directory is already in use: $OUT" >&2; exit 2; }
CREDENTIAL_FILES=()
OWN_CREDENTIAL_CACHE=false
: "${BENCH_CREDENTIAL_CACHE_DIR:=}"
cleanup() {
  local credential
  for credential in "${CREDENTIAL_FILES[@]-}"; do
    [[ -n "$credential" ]] || continue
    rm -f "$credential"
  done
  if [[ "$OWN_CREDENTIAL_CACHE" == true && -d "$BENCH_CREDENTIAL_CACHE_DIR" ]]; then
    python3 "$HERE/credential_cache.py" cleanup "$BENCH_CREDENTIAL_CACHE_DIR" || true
  fi
  rmdir "$OUT/.running" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
MOCK=false
[[ -n "$BENCH_MOCK_AGENT" ]] && MOCK=true
if [[ "$MOCK" == false ]]; then
  [[ -n "$BENCH_LEDGER" && -n "$BENCH_INVOCATION_CEILING" && -n "$BENCH_PINNED_MODEL" ]] || {
    echo "Real runs require a ledger, explicit invocation ceiling, and pinned model; use pilot_launch.py." >&2; exit 2; }
  [[ "${CLAUDE_MODEL:-}" == "$BENCH_PINNED_MODEL" ]] || { echo "CLAUDE_MODEL must equal BENCH_PINNED_MODEL." >&2; exit 2; }
  [[ -z "$BENCH_SCORER_LOCAL$BENCH_MOCK_INFRA_FAIL$BENCH_MOCK_PROVIDER_LIMIT${BENCH_CONFIG_SEED_DIR:-}${BENCH_AGENT_RUN_EXTRA_ARGS:-}" ]] || {
    echo "Real runs refuse test overrides, config seeds, and extra container arguments." >&2; exit 2; }
  [[ "$PERMISSION_FLAGS" == "--dangerously-skip-permissions" ]] || {
    echo "Real runs use the fixed isolated benchmark permission policy." >&2; exit 2; }
fi

IFS=, read -ra SC <<<"$SCENARIOS"
IFS=, read -ra CO <<<"$CONDITIONS"
HAS_FORGE=false
HAS_CANDIDATE=false
for condition in "${CO[@]}"; do
  [[ "$condition" == "forge" ]] && HAS_FORGE=true
  [[ "$condition" == "candidate" ]] && HAS_CANDIDATE=true
done

FORGE_SRC=""
FORGE_TAG=""
FORGE_VERSION=""
FORGE_COMMIT=""
FORGE_ASSET_SHA256=""
FORGE_VERIFIED=false
FORGE_PROVENANCE="none"
# Releases contain developer evaluations as well as the runtime skill. Never
# mount those evaluations (including reference solutions) into an agent arm.
FORGE_RUNTIME_ITEMS=(SKILL.md README.md BOOTSTRAP.md VERSION LICENSE references templates scripts docs/runner.md)

prepare_forge() {
  [[ "$HAS_FORGE" == true ]] || return 0
  if [[ "$MOCK" == true ]]; then
    FORGE_TAG="mock"
    FORGE_VERSION="mock"
    FORGE_COMMIT="mock"
    FORGE_PROVENANCE="mock-selftest"
    return 0
  fi

  if [[ -n "${FORGE_DIR:-}" ]]; then
    [[ "${ALLOW_UNVERIFIED_FORGE:-0}" == "1" ]] || {
      echo "FORGE_DIR is unverified candidate input. Set ALLOW_UNVERIFIED_FORGE=1 for candidate/ablation runs." >&2
      exit 2
    }
    [[ "$FORGE_DIR" == /* ]] || FORGE_DIR="$CALLER_DIR/$FORGE_DIR"
    FORGE_SRC="$(cd "$FORGE_DIR" && pwd)"
    (cd "$FORGE_SRC" && python3 scripts/validate-skill-package.py) >"$OUT/forge-validate.log" 2>&1
    FORGE_VERSION="$(tr -d '[:space:]' < "$FORGE_SRC/VERSION")"
    FORGE_TAG="local-$FORGE_VERSION"
    FORGE_COMMIT="$(git -C "$FORGE_SRC" rev-parse HEAD 2>/dev/null || echo local-unversioned)"
    FORGE_PROVENANCE="local-unverified"
    return 0
  fi

  command -v gh >/dev/null 2>&1 || {
    echo "Real Forge benchmark runs require GitHub CLI with release verification support." >&2
    exit 2
  }
  gh release verify --help >/dev/null 2>&1 || {
    echo "Installed GitHub CLI lacks 'gh release verify'; upgrade it before running a publishable benchmark." >&2
    exit 2
  }
  gh release verify-asset --help >/dev/null 2>&1 || {
    echo "Installed GitHub CLI lacks 'gh release verify-asset'; upgrade it before running a publishable benchmark." >&2
    exit 2
  }

  if [[ -n "${FORGE_REF:-}" ]]; then
    FORGE_TAG="$FORGE_REF"
  else
    FORGE_TAG="$(gh release view --repo "$FORGE_REPO" --json tagName,isDraft,isPrerelease --jq '.tagName')"
  fi
  [[ "$FORGE_TAG" == v* ]] || {
    echo "FORGE_REF must name an immutable release tag (for example v1.7.0), not a branch/commit." >&2
    exit 2
  }

  local release_json
  release_json="$(gh release view "$FORGE_TAG" --repo "$FORGE_REPO" --json tagName,isDraft,isPrerelease)"
  python3 - "$release_json" <<'PY'
import json
import sys

release = json.loads(sys.argv[1])
if release.get("isDraft") or release.get("isPrerelease"):
    raise SystemExit("Benchmark requires a published stable release, not draft/prerelease")
PY

  gh release verify "$FORGE_TAG" --repo "$FORGE_REPO" >"$OUT/forge-release-verify.log" 2>&1

  local rel_dir asset unpack
  rel_dir="$OUT/verified-forge-release"
  mkdir -p "$rel_dir"
  asset="forge-skill-${FORGE_TAG}.zip"
  gh release download "$FORGE_TAG" --repo "$FORGE_REPO" --pattern "$asset" --dir "$rel_dir"
  gh release verify-asset "$FORGE_TAG" "$rel_dir/$asset" --repo "$FORGE_REPO" >"$OUT/forge-asset-verify.log" 2>&1
  FORGE_ASSET_SHA256="$(python3 - "$rel_dir/$asset" <<'PY'
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
print(digest.hexdigest())
PY
)"

  unpack="$rel_dir/unpacked"
  mkdir -p "$unpack"
  python3 - "$rel_dir/$asset" "$unpack" <<'PY'
import pathlib
import stat
import sys
import zipfile

source, destination = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
with zipfile.ZipFile(source) as archive:
    for info in archive.infolist():
        path = pathlib.PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"unsafe archive member: {info.filename}")
    archive.extractall(destination)
    # ZipFile deliberately drops Unix permission metadata. Git release archives
    # use it for executable launchers, which package validation must preserve.
    # Restore only execute bits on regular files, never special permission bits.
    for info in archive.infolist():
        mode = info.external_attr >> 16
        if stat.S_ISREG(mode):
            path = destination / pathlib.PurePosixPath(info.filename)
            path.chmod((path.stat().st_mode & 0o666) | (mode & 0o111))
PY
  FORGE_SRC="$unpack/forge"
  [[ -f "$FORGE_SRC/SKILL.md" && -f "$FORGE_SRC/VERSION" ]] || {
    echo "Verified release asset does not contain the expected Forge package." >&2
    exit 2
  }
  (cd "$FORGE_SRC" && python3 scripts/validate-skill-package.py) >"$OUT/forge-validate.log" 2>&1
  FORGE_VERSION="$(tr -d '[:space:]' < "$FORGE_SRC/VERSION")"
  [[ "$FORGE_TAG" == "v$FORGE_VERSION" ]] || {
    echo "Verified release tag $FORGE_TAG does not match package VERSION $FORGE_VERSION" >&2
    exit 2
  }
  FORGE_COMMIT="$(gh api "repos/$FORGE_REPO/commits/$FORGE_TAG" --jq '.sha')"
  FORGE_VERIFIED=true
  FORGE_PROVENANCE="github-immutable-release-attestation"
}

# Third arm: a local, unverified Forge candidate package (methodology under test), installed
# from CANDIDATE_DIR with the same runtime projection and the same invocation as the forge arm.
CANDIDATE_SRC=""
CANDIDATE_VERSION=""
CANDIDATE_COMMIT=""
CANDIDATE_TREE_SHA256=""
prepare_candidate() {
  [[ "$HAS_CANDIDATE" == true ]] || return 0
  if [[ "$MOCK" == true ]]; then
    CANDIDATE_VERSION="mock"
    CANDIDATE_COMMIT="mock"
    return 0
  fi
  [[ -n "${CANDIDATE_DIR:-}" ]] || { echo "condition 'candidate' requires CANDIDATE_DIR (a local Forge package checkout)." >&2; exit 2; }
  [[ "$CANDIDATE_DIR" == /* ]] || CANDIDATE_DIR="$CALLER_DIR/$CANDIDATE_DIR"
  CANDIDATE_SRC="$(cd "$CANDIDATE_DIR" && pwd)"
  (cd "$CANDIDATE_SRC" && python3 scripts/validate-skill-package.py) >"$OUT/candidate-validate.log" 2>&1
  CANDIDATE_VERSION="$(tr -d '[:space:]' < "$CANDIDATE_SRC/VERSION")"
  CANDIDATE_COMMIT="$(git -C "$CANDIDATE_SRC" rev-parse HEAD 2>/dev/null || echo local-unversioned)"
  CANDIDATE_TREE_SHA256="$(runtime_projection_sha256 "$CANDIDATE_SRC")"
}

# Content hash of the runtime projection actually installed into an arm's config directory.
runtime_projection_sha256() {
  python3 - "$1" "${FORGE_RUNTIME_ITEMS[@]}" <<'PY'
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
# Bytecode caches are build artefacts (the harness's own package validation writes them); never package content.
def content_file(p):
    return p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")
for item in sys.argv[2:]:
    base = root / item
    paths = sorted(p for p in base.rglob("*") if content_file(p)) if base.is_dir() else ([base] if base.is_file() else [])
    for path in paths:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
print(digest.hexdigest())
PY
}

FORGE_TREE_SHA256=""
CONTAINER_RUNTIME=""
CONTAINER_IMAGE_ID=""
SCORER_IMAGE_ID=""
NETWORK_IMAGE_ID=""
AGENT_DESC=""
ensure_container() {
  [[ "$MOCK" == false ]] || return 0
  if [[ -n "${BENCH_CONTAINER_RUNTIME:-}" ]]; then
    CONTAINER_RUNTIME="$BENCH_CONTAINER_RUNTIME"
  elif command -v docker >/dev/null 2>&1; then
    CONTAINER_RUNTIME=docker
  elif command -v podman >/dev/null 2>&1; then
    CONTAINER_RUNTIME=podman
  else
    echo "Real benchmark runs require Docker or Podman for both agent and scoring isolation." >&2
    exit 2
  fi
  "$CONTAINER_RUNTIME" info >/dev/null 2>&1 || {
    echo "$CONTAINER_RUNTIME is installed but not available/running." >&2
    exit 2
  }
  if ! "$CONTAINER_RUNTIME" image inspect "$BENCH_AGENT_IMAGE" >/dev/null 2>&1; then
    "$CONTAINER_RUNTIME" build \
      --build-arg "CLAUDE_CODE_CHANNEL=$CLAUDE_CODE_CHANNEL" \
      -t "$BENCH_AGENT_IMAGE" -f container/Containerfile .
  fi
  if ! "$CONTAINER_RUNTIME" image inspect "$BENCH_SCORER_IMAGE" >/dev/null 2>&1; then
    "$CONTAINER_RUNTIME" build \
      -t "$BENCH_SCORER_IMAGE" -f container/ScorerContainerfile .
  fi
  CONTAINER_IMAGE_ID="$("$CONTAINER_RUNTIME" image inspect "$BENCH_AGENT_IMAGE" --format '{{.Id}}' 2>/dev/null || true)"
  SCORER_IMAGE_ID="$("$CONTAINER_RUNTIME" image inspect "$BENCH_SCORER_IMAGE" --format '{{.Id}}' 2>/dev/null || true)"
  [[ -n "$CONTAINER_IMAGE_ID" && -n "$SCORER_IMAGE_ID" ]] || {
    echo "Benchmark container images could not be resolved." >&2
    exit 2
  }
  if [[ -n "$BENCH_EXPECT_AGENT_IMAGE_ID" && "$CONTAINER_IMAGE_ID" != "$BENCH_EXPECT_AGENT_IMAGE_ID" ]]; then
    echo "agent image $BENCH_AGENT_IMAGE resolves to $CONTAINER_IMAGE_ID, not the frozen $BENCH_EXPECT_AGENT_IMAGE_ID." >&2; exit 2
  fi
  if [[ -n "$BENCH_EXPECT_SCORER_IMAGE_ID" && "$SCORER_IMAGE_ID" != "$BENCH_EXPECT_SCORER_IMAGE_ID" ]]; then
    echo "scorer image $BENCH_SCORER_IMAGE resolves to $SCORER_IMAGE_ID, not the frozen $BENCH_EXPECT_SCORER_IMAGE_ID." >&2; exit 2
  fi
  if ! "$CONTAINER_RUNTIME" image inspect "$BENCH_NETWORK_IMAGE" >/dev/null 2>&1; then
    "$CONTAINER_RUNTIME" build -t "$BENCH_NETWORK_IMAGE" -f "$HERE/container/NetworkProxyContainerfile" "$HERE" >"$OUT/network-build.log" 2>&1
  fi
  NETWORK_IMAGE_ID="$("$CONTAINER_RUNTIME" image inspect "$BENCH_NETWORK_IMAGE" --format '{{.Id}}')"
  if [[ -n "$BENCH_EXPECT_NETWORK_IMAGE_ID" && "$NETWORK_IMAGE_ID" != "$BENCH_EXPECT_NETWORK_IMAGE_ID" ]]; then
    echo "Network proxy image differs from the frozen identity." >&2; exit 2
  fi
  python3 "$HERE/network_run.py" identity "$CONTAINER_RUNTIME" "$NETWORK_IMAGE_ID" >"$OUT/NETWORK_IDENTITY.json"
  BENCH_EXPECT_NETWORK_IDENTITY_SHA256="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["network_identity_sha256"])' "$OUT/NETWORK_IDENTITY.json")"
  export BENCH_EXPECT_NETWORK_IDENTITY_SHA256
  AGENT_DESC="$(python3 "$HERE/container_run.py" "$CONTAINER_RUNTIME" 30 --network none "$CONTAINER_IMAGE_ID" claude --version 2>/dev/null | head -1)"
  [[ -n "$AGENT_DESC" ]] || {
    echo "Benchmark agent image does not expose a working 'claude' executable." >&2
    exit 2
  }
}

: "${BENCH_CREDENTIALS_FILE:=$HOME/.claude/.credentials.json}"
copy_credentials() {
  local cfg="$1"
  if [[ "${COPY_CREDENTIALS:-0}" == "1" ]]; then
    [[ -f "$BENCH_CREDENTIALS_FILE" ]] || {
      echo "COPY_CREDENTIALS=1 but $BENCH_CREDENTIALS_FILE does not exist." >&2
      exit 2
    }
    if [[ -z "$BENCH_CREDENTIAL_CACHE_DIR" ]]; then
      BENCH_CREDENTIAL_CACHE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/forge-bench-credentials.XXXXXX")"
      chmod 700 "$BENCH_CREDENTIAL_CACHE_DIR"
      OWN_CREDENTIAL_CACHE=true
    fi
    python3 "$HERE/credential_cache.py" init "$BENCH_CREDENTIALS_FILE" "$BENCH_CREDENTIAL_CACHE_DIR"
    python3 "$HERE/credential_cache.py" copy "$BENCH_CREDENTIAL_CACHE_DIR" "$cfg"
    CREDENTIAL_FILES+=("$cfg/.credentials.json")
  elif [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "Set ANTHROPIC_API_KEY or COPY_CREDENTIALS=1 for real benchmark runs." >&2
    exit 2
  fi
}

make_config() {
  local cfg="$1" condition="$2"
  rm -rf "$cfg"
  mkdir -p "$cfg"
  local src=""
  [[ "$condition" == "forge" ]] && src="$FORGE_SRC"
  [[ "$condition" == "candidate" ]] && src="$CANDIDATE_SRC"
  if [[ -n "$src" && "$MOCK" == false ]]; then
    mkdir -p "$cfg/skills/forge"
    local item
    for item in "${FORGE_RUNTIME_ITEMS[@]}"; do
      if [[ -e "$src/$item" ]]; then
        mkdir -p "$cfg/skills/forge/$(dirname "$item")"
        cp -a "$src/$item" "$cfg/skills/forge/$item"
      fi
    done
  fi
  [[ "$MOCK" == true ]] || copy_credentials "$cfg"
  # Optional per-arm config seed (for example nested-CLI permission settings in
  # a dual-agent arm). Applied identically to every cell of the matrix.
  if [[ -n "${BENCH_CONFIG_SEED_DIR:-}" ]]; then
    cp -a "$BENCH_CONFIG_SEED_DIR/." "$cfg/"
  fi
  # Record what was actually installed, after every configuration step, and verify it against the content
  # hashed at preparation time: a package edited while the matrix runs stops the run before the next session.
  if [[ -n "$src" && "$MOCK" == false ]]; then
    local installed expected=""
    installed="$(runtime_projection_sha256 "$cfg/skills/forge")"
    printf '%s\n' "$installed" >"$cfg/installed-package.sha256"
    [[ "$condition" == "forge" ]] && expected="$FORGE_TREE_SHA256"
    [[ "$condition" == "candidate" ]] && expected="$CANDIDATE_TREE_SHA256"
    if [[ -n "$expected" && "$installed" != "$expected" ]]; then
      echo "installed $condition package content $installed differs from the prepared package $expected (edited during the run?)." >&2
      exit 2
    fi
  fi
}

# Session accounting (BENCH_LEDGER). `ledger_check` stops the run (exit 3, STOPPED.json) before a session that
# would exceed the invocation ceiling or the spending policy; `ledger_record` appends the session's usage, cost,
# model identity and failure classification after it.
SESSION_KIND="main"
SESSION_CELL="preflight"
ledger_check() {
  local session_out="$1"
  [[ -n "$BENCH_LEDGER" ]] || return 0
  local rc=0
  local -a spend=()
  [[ -n "$BENCH_USD_CEILING" ]] && spend+=(--usd-ceiling "$BENCH_USD_CEILING" --reserve-usd "$BENCH_SESSION_RESERVE_USD")
  [[ "$BENCH_CEILING_EXCLUDES_UNREACHABLE" == "1" ]] && spend+=(--exclude-unreachable)
  python3 "$HERE/pilot_ledger.py" start --ledger "$BENCH_LEDGER" --ceiling "$BENCH_INVOCATION_CEILING" \
    --kind "$SESSION_KIND" --cell "$SESSION_CELL" --out-dir "$session_out" \
    ${spend[@]+"${spend[@]}"} >"$OUT/ledger-start.json" 2>"$OUT/ledger-stop.json" || rc=$?
  if [[ $rc -ne 0 ]]; then
    cp "$OUT/ledger-stop.json" "$OUT/STOPPED.json"
    echo "BUDGET/INVOCATION STOP before $SESSION_KIND $SESSION_CELL: $(cat "$OUT/STOPPED.json")" >&2
    exit 3
  fi
  rm -f "$OUT/ledger-stop.json"
}
ledger_record() {
  local transcript="$1" rc="$2" outdir="$3" stderr_path="${4:-}"
  [[ -n "$BENCH_LEDGER" ]] || return 0
  local -a extra=()
  [[ "$MOCK" == true ]] && extra+=(--mock-usd "$BENCH_MOCK_USAGE_USD")
  [[ -n "$BENCH_PINNED_MODEL" ]] && extra+=(--pinned-model "$BENCH_PINNED_MODEL")
  [[ -n "$stderr_path" ]] && extra+=(--stderr "$stderr_path")
  local lrc=0
  python3 "$HERE/pilot_ledger.py" record --ledger "$BENCH_LEDGER" --kind "$SESSION_KIND" --cell "$SESSION_CELL" \
    --transcript "$transcript" --rc "$rc" --out-dir "$outdir" ${extra[@]+"${extra[@]}"} >"$OUT/ledger-last.json" || lrc=$?
  if [[ $lrc -eq 5 ]]; then
    # Provider limit: preserve everything, record the pause, and hand control back to the launcher.
    python3 - "$OUT/ledger-last.json" "$OUT/PAUSED.json" "$SESSION_CELL" "$SESSION_KIND" <<'PY'
import json
import pathlib
import sys
import time

detail = json.loads(pathlib.Path(sys.argv[1]).read_text() or "{}")
detail.update({"event": "paused", "cell": sys.argv[3], "session_kind": sys.argv[4], "paused_at_epoch": int(time.time()),
               "action": "resume the unscored cells after the reset; this attempt is preserved and is not a failure"})
pathlib.Path(sys.argv[2]).write_text(json.dumps(detail, indent=2) + "\n")
PY
    echo "PROVIDER LIMIT during $SESSION_KIND $SESSION_CELL: $(cat "$OUT/PAUSED.json")" >&2
    exit 4
  fi
  if [[ $lrc -ne 0 ]]; then
    echo "Session accounting or identity check failed; stopping without another session." >&2
    exit "$lrc"
  fi
}

# Preserve CLI refreshes privately between cells; never write the user's source credentials.
credential_handoff() {
  local cfg="$1"
  [[ "${COPY_CREDENTIALS:-0}" == "1" ]] || return 0
  python3 "$HERE/credential_cache.py" handoff "$BENCH_CREDENTIAL_CACHE_DIR" "$cfg"
}

run_real_agent() {
  local repo="$1" cfg="$2" prompt="$3" transcript="$4" stderr="$5" max_turns="$6" timeout_s="$7"
  local -a perm envargs cmd
  ledger_check "$(dirname "$transcript")"
  read -r -a perm <<<"$PERMISSION_FLAGS"
  envargs=(-e CLAUDE_CONFIG_DIR=/config -e HOME=/tmp/bench-home)
  [[ -n "${ANTHROPIC_API_KEY:-}" ]] && envargs+=(-e ANTHROPIC_API_KEY)
  # Optional extra container arguments (for example a reviewer-CLI auth mount
  # in a dual-agent arm). Recorded in MANIFEST.json.
  local -a extra=()
  [[ -n "${BENCH_AGENT_RUN_EXTRA_ARGS:-}" ]] && read -r -a extra <<<"$BENCH_AGENT_RUN_EXTRA_ARGS"
  cmd=(claude -p "$prompt" --output-format stream-json --verbose --max-turns "$max_turns" --disallowedTools WebFetch WebSearch)
  [[ -n "${CLAUDE_MODEL:-}" ]] && cmd+=(--model "$CLAUDE_MODEL")
  cmd+=("${perm[@]}")

  local rc=0
  BENCH_NETWORK_EVIDENCE="$(dirname "$transcript")/network.json" \
  python3 "$HERE/network_run.py" "$CONTAINER_RUNTIME" "$timeout_s" "$NETWORK_IMAGE_ID" "$CONTAINER_IMAGE_ID" \
    --user "$(id -u):$(id -g)" \
    "${envargs[@]}" \
    ${extra[@]+"${extra[@]}"} \
    -v "$repo:/workspace:rw" \
    -v "$cfg:/config:rw" \
    -w /workspace \
    -- "${cmd[@]}" >"$transcript" 2>"$stderr" </dev/null || rc=$?
  local credential_rc=0
  credential_handoff "$cfg" || credential_rc=$?
  ledger_record "$transcript" "$rc" "$(dirname "$transcript")" "$stderr"
  if [[ $credential_rc -ne 0 ]]; then
    echo "Credential handoff failed after session accounting; inspect cache before resuming." >&2
    exit 2
  fi
  return "$rc"
}

run_agent() {
  local scenario="$1" condition="$2" stage="$3" repo="$4" cfg="$5" prompt="$6" outdir="$7"
  mkdir -p "$outdir"
  printf '%s\n' "$prompt" >"$outdir/prompt.txt"
  local start end rc=0
  start="$(python3 -c 'import time; print(time.monotonic())')"
  SESSION_KIND="$stage"
  [[ "$stage" == "main" || "$stage" == "stage1" || "$stage" == "stage2" ]] || SESSION_KIND="main"
  if [[ "$MOCK" == true ]]; then
    ledger_check "$outdir"
    if [[ " $BENCH_MOCK_INFRA_FAIL " == *" $SESSION_CELL "* ]]; then
      # test-only: an injected runtime failure (no session started, no transcript)
      echo "injected container runtime failure" >"$outdir/stderr.txt"
      : >"$outdir/stdout.txt"
      rc=125
    elif [[ " $BENCH_MOCK_PROVIDER_LIMIT " == *" $SESSION_CELL "* && ! -f "$OUT/../.mock-limit-consumed-$(echo "$SESSION_CELL" | tr / _)" ]]; then
      # test-only: an injected subscription usage limit on the first attempt of this cell (reset 3 s later)
      : >"$OUT/../.mock-limit-consumed-$(echo "$SESSION_CELL" | tr / _)"
      python3 - "$outdir/transcript.jsonl" <<'PY'
import json
import sys
import time

with open(sys.argv[1], "w", encoding="utf-8") as stream:
    stream.write(json.dumps({"type": "system", "subtype": "init", "model": "mock-model"}) + "\n")
    stream.write(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                             "result": f"Claude AI usage limit reached|{int(time.time()) + 3}"}) + "\n")
PY
      : >"$outdir/stdout.txt"
      : >"$outdir/stderr.txt"
      rc=1
      ledger_record "$outdir/transcript.jsonl" "$rc" "$outdir" "$outdir/stderr.txt"
    else
      (cd "$repo" && python3 "$HERE/mock_agent.py" "$BENCH_MOCK_AGENT" "$scenario" "$stage") >"$outdir/stdout.txt" 2>"$outdir/stderr.txt" || rc=$?
    fi
    : >"$outdir/transcript.jsonl"
    ledger_record "$outdir/transcript.jsonl" "$rc" "$outdir"
  else
    run_real_agent "$repo" "$cfg" "$prompt" "$outdir/transcript.jsonl" "$outdir/stderr.txt" "$MAX_TURNS" "$AGENT_TIMEOUT" || rc=$?
  fi
  end="$(python3 -c 'import time; print(time.monotonic())')"
  python3 - "$outdir/meta-stage.json" "$rc" "$start" "$end" <<'PY'
import json
import os
import sys

path, rc, start, end = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
with open(path, "w", encoding="utf-8") as stream:
    json.dump({"rc": rc, "timed_out": rc == 124, "wall_seconds": round(end - start, 2),
               "mock": os.environ.get("MOCK") == "true",
               "fixture_version": os.environ.get("FIXTURE_VERSION"),
               "criteria_version": os.environ.get("CRITERIA_VERSION")}, stream, indent=2)
PY
}

forge_activation_preflight() {
  local condition="${1:-forge}" expected_version="${2:-$FORGE_VERSION}" log_name="${3:-forge-activation}"
  [[ "$MOCK" == false ]] || return 0
  local root repo cfg prompt marker rc=0
  root="$OUT/$log_name-preflight"
  repo="$root/repo"
  cfg="$root/config"
  mkdir -p "$repo"
  printf '# Forge activation preflight\n' >"$repo/README.md"
  (cd "$repo" && git init -q -b main && git -c core.hooksPath=/dev/null add . && git -c core.hooksPath=/dev/null -c commit.gpgSign=false -c user.name=bench -c user.email=b@x commit -q -m init)
  make_config "$cfg" "$condition"
  SESSION_KIND="preflight"
  SESSION_CELL="$log_name"
  marker="FORGE_ACTIVE:$expected_version"
  prompt="Use the Forge skill installed in your skill directory. Read its VERSION file and reply with FORGE_ACTIVE: followed by the exact version from that file, and nothing else. Do not modify the repository."
  run_real_agent "$repo" "$cfg" "$prompt" "$root/transcript.jsonl" "$root/stderr.txt" 8 240 || rc=$?
  [[ $rc -eq 0 ]] || { echo "Forge activation preflight agent failed rc=$rc" >&2; exit 2; }
  python3 - "$root/transcript.jsonl" "$expected_version" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
version = sys.argv[2]
marker = f"FORGE_ACTIVE:{version}"
results = []
for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if isinstance(event, dict) and event.get("type") == "result":
        results.append(event)
# The prompt says "FORGE_ACTIVE: followed by the exact version"; accept only
# optional whitespace after the colon, never a different or padded version.
reply = results[0].get("result", "") if results else ""
exact = isinstance(reply, str) and re.fullmatch(r"FORGE_ACTIVE:\s*" + re.escape(version), reply.strip()) is not None
if len(results) != 1 or results[0].get("is_error") or results[0].get("subtype") != "success" or not exact:
    raise SystemExit(f"Forge activation preflight failed: expected exact successful result {marker!r}")
PY
  printf 'PASS %s\n' "$marker" >"$OUT/$log_name.log"
}

get_prompt() {
  python3 - "$1" <<'PY'
import sys
from fixture_bundle import load_bundle

bundle = load_bundle()
key = sys.argv[1]
try:
    print(bundle["prompts"][key], end="")
except KeyError as exc:
    raise SystemExit(f"unknown prompt key: {key}") from exc
PY
}

# Any Git command after an agent may execute repository-controlled helpers.
# Real runs therefore execute those commands inside the isolated scorer image.
bench_git() {
  local repo="$1"
  shift
  if [[ "$MOCK" == true ]]; then
    git -C "$repo" -c core.hooksPath=/dev/null -c core.fsmonitor=false -c commit.gpgSign=false "$@"
    return
  fi
  python3 "$HERE/container_run.py" "$CONTAINER_RUNTIME" "$SCORER_TIMEOUT" \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
    -e HOME=/tmp \
    -v "$repo:/workspace:rw" \
    -w /workspace \
    "$SCORER_IMAGE_ID" \
    git -c safe.directory=/workspace -c core.hooksPath=/dev/null -c core.fsmonitor=false -c commit.gpgSign=false "$@"
}

print_score_progress() {
  local path="$1" phase="$2"
  python3 - "$path" "$phase" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
phase = sys.argv[2]
print(
    f"[{payload.get('scenario')}/{payload.get('condition')}/{phase}/run-{payload.get('run')}] "
    f"{'PASS' if payload.get('pass') else 'FAIL'} {payload.get('failed_assertions', [])}"
)
PY
}

score_assertion() {
  local phase="$1" scenario="$2" repo="$3" meta="$4" transcript="$5" out="$6"
  local stage1_transcript="${7:-}" stage1_result="${8:-}"
  if [[ "$MOCK" == true ]]; then
    local -a cmd
    cmd=(python3 "$HERE/assert_run.py" --phase "$phase" --scenario "$scenario" --repo "$repo" --meta "$meta" --transcript "$transcript" --out "$out")
    [[ -n "$stage1_transcript" ]] && cmd+=(--stage1-transcript "$stage1_transcript")
    [[ -n "$stage1_result" ]] && cmd+=(--stage1-result "$stage1_result")
    "${cmd[@]}" | tee -a "$OUT/progress.log"
    return
  fi

  local tmp_out="$out.tmp"
  local -a mounts args
  mounts=(
    -v "$repo:/input:ro"
    -v "$meta:/evidence/meta.json:ro"
    -v "$transcript:/evidence/transcript.jsonl:ro"
  )
  args=(
    python3 /scorer/score_entrypoint.py
    --phase "$phase"
    --scenario "$scenario"
    --meta /evidence/meta.json
    --transcript /evidence/transcript.jsonl
  )
  if [[ -n "$stage1_transcript" ]]; then
    mounts+=(-v "$stage1_transcript:/evidence/stage1-transcript.jsonl:ro")
    args+=(--stage1-transcript /evidence/stage1-transcript.jsonl)
  fi
  if [[ -n "$stage1_result" ]]; then
    mounts+=(-v "$stage1_result:/evidence/stage1-result.json:ro")
    args+=(--stage1-result /evidence/stage1-result.json)
  fi

  python3 "$HERE/container_run.py" "$CONTAINER_RUNTIME" "$SCORER_TIMEOUT" \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --pids-limit 128 \
    --memory 768m \
    --cpus 1 \
    --tmpfs /work:rw,nosuid,nodev,size=512m,mode=1777 \
    --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 \
    "${mounts[@]}" \
    "$SCORER_IMAGE_ID" \
    "${args[@]}" >"$tmp_out"

  python3 - "$tmp_out" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(payload, dict) or "pass" not in payload or "scenario" not in payload:
    raise SystemExit("isolated scorer returned an invalid result")
PY
  mv "$tmp_out" "$out"
  print_score_progress "$out" "$phase" | tee -a "$OUT/progress.log"
}

prepare_forge
[[ "$HAS_FORGE" == true && "$MOCK" == false ]] && FORGE_TREE_SHA256="$(runtime_projection_sha256 "$FORGE_SRC")"
if [[ -n "$BENCH_EXPECT_FORGE_SHA256" && "$HAS_FORGE" == true && "$MOCK" == false && "$FORGE_TREE_SHA256" != "$BENCH_EXPECT_FORGE_SHA256" ]]; then
  echo "forge package content $FORGE_TREE_SHA256 does not match the frozen BENCH_EXPECT_FORGE_SHA256." >&2; exit 2
fi
prepare_candidate
if [[ -n "$BENCH_EXPECT_CANDIDATE_SHA256" && "$HAS_CANDIDATE" == true && "$MOCK" == false && "$CANDIDATE_TREE_SHA256" != "$BENCH_EXPECT_CANDIDATE_SHA256" ]]; then
  echo "candidate package content $CANDIDATE_TREE_SHA256 does not match the frozen BENCH_EXPECT_CANDIDATE_SHA256." >&2; exit 2
fi
if [[ "$MOCK" == false && "$HAS_FORGE" == true && "$HAS_CANDIDATE" == true && "$FORGE_TREE_SHA256" == "$CANDIDATE_TREE_SHA256" ]]; then
  echo "Forge and candidate runtime contents are identical; use distinct treatments." >&2; exit 2
fi
ensure_container
python3 build_fixtures.py --out "$OUT/fixtures" "${SC[@]}" >/dev/null

if [[ "$MOCK" == true ]]; then
  AGENT_DESC="MOCK:${BENCH_MOCK_AGENT}"
  printf '%s\n' 'MOCK AGENT MODE: these results validate the harness only, not Forge.' >"$OUT/MOCK_RUN.txt"
fi

export OUT FORGE_TAG FORGE_VERSION FORGE_COMMIT FORGE_ASSET_SHA256 FORGE_VERIFIED FORGE_PROVENANCE
export CANDIDATE_SRC CANDIDATE_VERSION CANDIDATE_COMMIT CANDIDATE_TREE_SHA256 FORGE_TREE_SHA256
export BENCH_LEDGER BENCH_INVOCATION_CEILING BENCH_USD_CEILING BENCH_SESSION_RESERVE_USD BENCH_PINNED_MODEL BENCH_CEILING_EXCLUDES_UNREACHABLE
export BENCH_EXPECT_AGENT_IMAGE_ID BENCH_EXPECT_SCORER_IMAGE_ID BENCH_EXPECT_FORGE_SHA256 BENCH_EXPECT_CANDIDATE_SHA256
export BENCH_EXPECT_RUN_ORDER_SHA256 BENCH_CELL_FILTER BENCH_SCORER_LOCAL BENCH_MOCK_INFRA_FAIL BENCH_MOCK_PROVIDER_LIMIT BENCH_CREDENTIALS_FILE
export AGENT_DESC CLAUDE_MODEL MAX_TURNS AGENT_TIMEOUT FORGE_INVOCATION SCENARIOS CONDITIONS RUNS BENCH_SEED
export CONTAINER_RUNTIME CONTAINER_IMAGE_ID SCORER_IMAGE_ID BENCH_AGENT_IMAGE BENCH_SCORER_IMAGE MOCK
export SCORER_SOURCE_SHA256 SCORER_TIMEOUT NETWORK_IMAGE_ID BENCH_NETWORK_IMAGE BENCH_EXPECT_NETWORK_IDENTITY_SHA256
export BENCH_AGENT_RUN_EXTRA_ARGS="${BENCH_AGENT_RUN_EXTRA_ARGS:-}" BENCH_CONFIG_SEED_DIR="${BENCH_CONFIG_SEED_DIR:-}" BENCH_ARM_LABEL="${BENCH_ARM_LABEL:-}"
export FORGE_RUNTIME_PATHS="${FORGE_RUNTIME_ITEMS[*]}"
python3 - <<'PY'
import datetime
import json
import os
import pathlib
from assert_run import criteria_for

path = pathlib.Path(os.environ["OUT"]) / "MANIFEST.json"
mock = os.environ.get("MOCK") == "true"
obj = {
    "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "forge_ref": os.environ.get("FORGE_TAG"),
    "forge_version": os.environ.get("FORGE_VERSION"),
    "forge_commit": os.environ.get("FORGE_COMMIT"),
    "forge_asset_sha256": os.environ.get("FORGE_ASSET_SHA256"),
    "forge_verified": os.environ.get("FORGE_VERIFIED") == "true",
    "forge_provenance": os.environ.get("FORGE_PROVENANCE"),
    "forge_runtime_paths": os.environ["FORGE_RUNTIME_PATHS"].split(),
    "candidate_source": os.environ.get("CANDIDATE_SRC") or None,
    "candidate_version": os.environ.get("CANDIDATE_VERSION") or None,
    "candidate_commit": os.environ.get("CANDIDATE_COMMIT") or None,
    "candidate_runtime_sha256": os.environ.get("CANDIDATE_TREE_SHA256") or None,
    "candidate_provenance": "local-unverified" if os.environ.get("CANDIDATE_SRC") else None,
    "agent": os.environ.get("AGENT_DESC"),
    "model": os.environ.get("CLAUDE_MODEL") or "default",
    "max_turns": int(os.environ["MAX_TURNS"]),
    "timeout_s": int(os.environ["AGENT_TIMEOUT"]),
    "forge_invocation": os.environ.get("FORGE_INVOCATION"),
    "scenarios": os.environ.get("SCENARIOS"),
    "conditions": os.environ.get("CONDITIONS"),
    "runs_per_cell": int(os.environ["RUNS"]),
    "seed": int(os.environ["BENCH_SEED"]),
    "mock": mock,
    "isolation": "mock-local-trusted" if mock else "agent-container+isolated-scorer-container",
    "container_runtime": os.environ.get("CONTAINER_RUNTIME"),
    "agent_container_image": os.environ.get("BENCH_AGENT_IMAGE"),
    "agent_container_image_id": os.environ.get("CONTAINER_IMAGE_ID"),
    "scorer_container_image": os.environ.get("BENCH_SCORER_IMAGE"),
    "scorer_container_image_id": os.environ.get("SCORER_IMAGE_ID"),
    "scorer_source_sha256": os.environ.get("SCORER_SOURCE_SHA256"),
    "fixture_version": os.environ.get("FIXTURE_VERSION"),
    "criteria_by_scenario": {s: criteria_for(s) for s in os.environ["SCENARIOS"].split(",")},
    "scorer_timeout_s": int(os.environ["SCORER_TIMEOUT"]),
    "scorer_network": "not-applicable" if mock else "none",
    "agent_network": "mock-local-trusted" if mock else "none-with-provider-socket-proxy",
    "network_identity": None if mock else json.loads((path.parent / "NETWORK_IDENTITY.json").read_text()),
    "b3_boundary": "fresh-config-second-session",
    "agent_run_extra_args": os.environ.get("BENCH_AGENT_RUN_EXTRA_ARGS") or None,
    "config_seed_dir": os.environ.get("BENCH_CONFIG_SEED_DIR") or None,
    "forge_runtime_sha256": os.environ.get("FORGE_TREE_SHA256") or None,
    "execution_controls": {
        "ledger": os.environ.get("BENCH_LEDGER") or None,
        "invocation_ceiling": int(os.environ["BENCH_INVOCATION_CEILING"]) if os.environ.get("BENCH_INVOCATION_CEILING") else None,
        "ceiling_counts": "sessions that reached the provider" if os.environ.get("BENCH_CEILING_EXCLUDES_UNREACHABLE") == "1" else "every session",
        "usd_ceiling": float(os.environ["BENCH_USD_CEILING"]) if os.environ.get("BENCH_USD_CEILING") else None,
        "session_reserve_usd": float(os.environ["BENCH_SESSION_RESERVE_USD"]) if os.environ.get("BENCH_SESSION_RESERVE_USD") else None,
        "pinned_model": os.environ.get("BENCH_PINNED_MODEL") or None,
        "expected_agent_image_id": os.environ.get("BENCH_EXPECT_AGENT_IMAGE_ID") or None,
        "expected_scorer_image_id": os.environ.get("BENCH_EXPECT_SCORER_IMAGE_ID") or None,
        "expected_forge_sha256": os.environ.get("BENCH_EXPECT_FORGE_SHA256") or None,
        "expected_candidate_sha256": os.environ.get("BENCH_EXPECT_CANDIDATE_SHA256") or None,
        "expected_run_order_sha256": os.environ.get("BENCH_EXPECT_RUN_ORDER_SHA256") or None,
        "cell_filter": os.environ.get("BENCH_CELL_FILTER").split() if os.environ.get("BENCH_CELL_FILTER") else None,
        "scorer_local_test_only": os.environ.get("BENCH_SCORER_LOCAL") == "1",
        "mock_infra_fail_test_only": os.environ.get("BENCH_MOCK_INFRA_FAIL").split() if os.environ.get("BENCH_MOCK_INFRA_FAIL") else None,
    "mock_provider_limit_test_only": os.environ.get("BENCH_MOCK_PROVIDER_LIMIT").split() if os.environ.get("BENCH_MOCK_PROVIDER_LIMIT") else None,
        "spending_rule": "enforced" if os.environ.get("BENCH_USD_CEILING") else "none (provider estimates informational)",
    },
    "arm_label": os.environ.get("BENCH_ARM_LABEL") or None,
}
path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
PY

python3 - "$RUNS" "$SCENARIOS" "$CONDITIONS" "$BENCH_SEED" >"$OUT/RUN_ORDER.tsv" <<'PY'
import random
import sys

runs = int(sys.argv[1])
scenarios = sys.argv[2].split(",")
conditions = sys.argv[3].split(",")
seed = int(sys.argv[4])
rng = random.Random(seed)
print("ordinal\trun\tscenario\tcondition")
ordinal = 0
for run in range(1, runs + 1):
    scenario_order = scenarios[:]
    rng.shuffle(scenario_order)
    for scenario in scenario_order:
        condition_order = conditions[:]
        rng.shuffle(condition_order)  # balanced randomised arm order within each scenario/run block
        for condition in condition_order:
            ordinal += 1
            print(f"{ordinal}\t{run}\t{scenario}\t{condition}")
PY

commit_and_capture() {
  local repo="$1" base="$2" outdir="$3"
  bench_git "$repo" add -A >/dev/null 2>&1
  bench_git "$repo" -c user.name=bench -c user.email=b@x commit -q -m "agent output" --allow-empty >/dev/null 2>&1
  local final
  final="$(bench_git "$repo" rev-parse HEAD)"
  bench_git "$repo" --no-pager diff --no-ext-diff --stat "$base" "$final" >"$outdir/diffstat.txt" 2>/dev/null || true
  bench_git "$repo" --no-pager diff --no-ext-diff "$base" "$final" >"$outdir/full.diff" 2>/dev/null || true
  bench_git "$repo" reset -q --soft "$base"
}

write_final_meta() {
  local path="$1" scenario="$2" condition="$3" run="$4" wall="$5" rc="$6" timeout_flag="$7" repo="$8" transcript="$9" stderr="${10}" diff="${11}" stage1="${12:-}"
  python3 - "$path" "$scenario" "$condition" "$run" "$wall" "$rc" "$timeout_flag" "$repo" "$transcript" "$stderr" "$diff" "$stage1" "$FORGE_COMMIT" <<'PY'
import json
import os
import sys

(path, scenario, condition, run, wall, rc, timed_out, repo, transcript, stderr, diff, stage1, commit) = sys.argv[1:]
evidence = {"repo": repo, "transcript": transcript, "stderr": stderr, "diff": diff}
if stage1:
    evidence["stage1_result"] = stage1
obj = {
    "scenario": scenario,
    "condition": condition,
    "run": int(run),
    "rc": int(rc),
    "mock": os.environ.get("MOCK") == "true",
    "timed_out": timed_out == "true",
    "wall_seconds": float(wall),
    "forge_commit": commit,
    "fixture_version": os.environ.get("FIXTURE_VERSION"),
    "criteria_version": os.environ.get("CRITERIA_VERSION"),
    "evidence": evidence,
}
with open(path, "w", encoding="utf-8") as stream:
    stream.write(json.dumps(obj, indent=2) + "\n")
PY
}

run_one() {
  local scenario="$1" condition="$2" run_number="$3"
  local dir="$OUT/$scenario/$condition/run-$run_number" repo="$OUT/$scenario/$condition/run-$run_number/repo"
  SESSION_CELL="$scenario/$condition/run-$run_number"
  CRITERIA_VERSION="$(python3 -c 'from assert_run import criteria_for; import sys; print(criteria_for(sys.argv[1]))' "$scenario")"
  export CRITERIA_VERSION
  mkdir -p "$dir"
  local recovered_stage=""
  if [[ "$scenario" == "b3" && -n "$BENCH_STAGE1_RECOVERY" ]]; then
    recovered_stage="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$BENCH_STAGE1_RECOVERY" "$SESSION_CELL")"
  fi
  if [[ -n "$recovered_stage" ]]; then
    python3 "$HERE/stage_snapshot.py" restore "$recovered_stage" "$repo" "$dir/stage1"
  else
    cp -a "$OUT/fixtures/$scenario" "$repo"
  fi
  local base
  base="$(git -C "$repo" rev-parse HEAD)"

  local prompt cfg main_dir rc wall timed transcript stderr stage1_result=""
  if [[ "$scenario" == "b3" ]]; then
    local stage1_dir="$dir/stage1" stage2_dir="$dir/stage2" cfg1="$dir/stage1-config" cfg2="$dir/stage2-config"
    if [[ -z "$recovered_stage" ]]; then
    make_config "$cfg1" "$condition"
    prompt="$(get_prompt b3-stage1)"
    [[ "$condition" == forge || "$condition" == candidate ]] && prompt="$FORGE_INVOCATION
$prompt"
    run_agent "$scenario" "$condition" stage1 "$repo" "$cfg1" "$prompt" "$stage1_dir"
    # Score all Stage-1 changes against the fixture even when the agent committed
    # its handoff. A clean working tree can still contain valid durable evidence.
    commit_and_capture "$repo" "$base" "$stage1_dir"
    score_assertion stage1 b3 "$repo" "$stage1_dir/meta-stage.json" "$stage1_dir/transcript.jsonl" "$stage1_dir/run-stage1.json"
    python3 "$HERE/stage_snapshot.py" capture "$repo" "$stage1_dir"
    fi
    stage1_result="$stage1_dir/run-stage1.json"
    bench_git "$repo" add -A
    bench_git "$repo" -c user.name=bench -c user.email=b@x commit -q -m "stage1 handoff" --allow-empty

    make_config "$cfg2" "$condition"
    prompt="$(get_prompt b3-stage2)"
    [[ "$condition" == forge || "$condition" == candidate ]] && prompt="$FORGE_INVOCATION
$prompt"
    run_agent "$scenario" "$condition" stage2 "$repo" "$cfg2" "$prompt" "$stage2_dir"
    rc="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["rc"])' "$stage2_dir/meta-stage.json")"
    local wall1 wall2
    wall1="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["wall_seconds"])' "$stage1_dir/meta-stage.json")"
    wall2="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["wall_seconds"])' "$stage2_dir/meta-stage.json")"
    wall="$(python3 -c "print(round(float('$wall1')+float('$wall2'),2))")"
    timed="$(python3 - "$stage1_dir/meta-stage.json" "$stage2_dir/meta-stage.json" <<'PY'
import json
import sys
print(str(any(json.load(open(path)).get("timed_out") for path in sys.argv[1:])).lower())
PY
)"
    bench_git "$repo" add -A
    bench_git "$repo" -c user.name=bench -c user.email=b@x commit -q -m "stage2 output" --allow-empty
    local final
    final="$(bench_git "$repo" rev-parse HEAD)"
    bench_git "$repo" --no-pager diff --no-ext-diff --stat "$base" "$final" >"$dir/diffstat.txt" || true
    bench_git "$repo" --no-pager diff --no-ext-diff "$base" "$final" >"$dir/full.diff" || true
    bench_git "$repo" reset -q --soft "$base"
    transcript="$stage2_dir/transcript.jsonl"
    stderr="$stage2_dir/stderr.txt"
    write_final_meta "$dir/meta.json" "$scenario" "$condition" "$run_number" "$wall" "$rc" "$timed" "$repo" "$transcript" "$stderr" "$dir/full.diff" "$stage1_result"
    score_assertion final "$scenario" "$repo" "$dir/meta.json" "$stage2_dir/transcript.jsonl" "$dir/run.json" "$stage1_dir/transcript.jsonl" "$stage1_result"
  else
    main_dir="$dir/session"
    cfg="$dir/config"
    make_config "$cfg" "$condition"
    prompt="$(get_prompt "$scenario")"
    [[ "$condition" == forge || "$condition" == candidate ]] && prompt="$FORGE_INVOCATION
$prompt"
    run_agent "$scenario" "$condition" main "$repo" "$cfg" "$prompt" "$main_dir"
    rc="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["rc"])' "$main_dir/meta-stage.json")"
    wall="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["wall_seconds"])' "$main_dir/meta-stage.json")"
    timed="$(python3 -c 'import json,sys;print(str(json.load(open(sys.argv[1]))["timed_out"]).lower())' "$main_dir/meta-stage.json")"
    commit_and_capture "$repo" "$base" "$dir"
    transcript="$main_dir/transcript.jsonl"
    stderr="$main_dir/stderr.txt"
    write_final_meta "$dir/meta.json" "$scenario" "$condition" "$run_number" "$wall" "$rc" "$timed" "$repo" "$transcript" "$stderr" "$dir/full.diff" ""
    score_assertion final "$scenario" "$repo" "$dir/meta.json" "$transcript" "$dir/run.json"
  fi
}

if [[ -n "$BENCH_EXPECT_RUN_ORDER_SHA256" ]]; then
  actual_order_sha="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$OUT/RUN_ORDER.tsv")"
  if [[ "$actual_order_sha" != "$BENCH_EXPECT_RUN_ORDER_SHA256" ]]; then
    echo "generated RUN_ORDER.tsv ($actual_order_sha) differs from the frozen order ($BENCH_EXPECT_RUN_ORDER_SHA256)." >&2; exit 2
  fi
fi

[[ "$HAS_FORGE" == true ]] && forge_activation_preflight forge "$FORGE_VERSION" forge-activation
[[ "$HAS_CANDIDATE" == true ]] && forge_activation_preflight candidate "$CANDIDATE_VERSION" candidate-activation

# Read the run order on a dedicated descriptor: agent containers run with
# stdin attached (-i) and would otherwise consume the remaining cells.
while IFS=$'\t' read -r -u 3 ordinal run_number scenario condition; do
  [[ "$ordinal" == "ordinal" ]] && continue
  if [[ -n "$BENCH_CELL_FILTER" && " $BENCH_CELL_FILTER " != *" $scenario/$condition/run-$run_number "* ]]; then
    continue
  fi
  run_one "$scenario" "$condition" "$run_number" </dev/null
done 3<"$OUT/RUN_ORDER.tsv"

# Reports are written per criteria label; labels are never pooled (aggregate.py refuses mixed input otherwise).
python3 aggregate.py --by-criteria "$OUT"
echo "Report: $OUT/REPORT.md"
