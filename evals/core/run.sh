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
for name in ("container/ScorerContainerfile", "assert_run.py", "score_entrypoint.py", "fixture_bundle.py", "fixture_bundle.json.gz.b64"):
    digest.update(name.encode())
    digest.update(Path(name).read_bytes())
print(digest.hexdigest())
PY
)"
: "${BENCH_SCORER_IMAGE:=forge-bench-scorer:${SCORER_SOURCE_SHA256:0:16}}"

: "${BENCH_MOCK_AGENT:=}"
python3 - "$SCENARIOS" "$CONDITIONS" "$RUNS" "$BENCH_SEED" "$MAX_TURNS" "$AGENT_TIMEOUT" "$SCORER_TIMEOUT" "$BENCH_MOCK_AGENT" <<'PY'
import sys

for label, value, allowed in (("scenarios", sys.argv[1], {"b1", "b2", "b3", "b4"}),
                              ("conditions", sys.argv[2], {"baseline", "forge"})):
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
cleanup() {
  local credential
  for credential in "${CREDENTIAL_FILES[@]-}"; do
    [[ -n "$credential" ]] || continue
    rm -f "$credential"
  done
  rmdir "$OUT/.running" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
MOCK=false
[[ -n "$BENCH_MOCK_AGENT" ]] && MOCK=true

IFS=, read -ra SC <<<"$SCENARIOS"
IFS=, read -ra CO <<<"$CONDITIONS"
HAS_FORGE=false
for condition in "${CO[@]}"; do
  [[ "$condition" == "forge" ]] && HAS_FORGE=true
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

CONTAINER_RUNTIME=""
CONTAINER_IMAGE_ID=""
SCORER_IMAGE_ID=""
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
  AGENT_DESC="$(python3 "$HERE/container_run.py" "$CONTAINER_RUNTIME" 30 --network none "$CONTAINER_IMAGE_ID" claude --version 2>/dev/null | head -1)"
  [[ -n "$AGENT_DESC" ]] || {
    echo "Benchmark agent image does not expose a working 'claude' executable." >&2
    exit 2
  }
}

copy_credentials() {
  local cfg="$1"
  if [[ "${COPY_CREDENTIALS:-0}" == "1" ]]; then
    [[ -f "$HOME/.claude/.credentials.json" ]] || {
      echo "COPY_CREDENTIALS=1 but ~/.claude/.credentials.json does not exist." >&2
      exit 2
    }
    cp "$HOME/.claude/.credentials.json" "$cfg/.credentials.json"
    chmod 600 "$cfg/.credentials.json"
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
  if [[ "$condition" == "forge" && "$MOCK" == false ]]; then
    [[ -n "$FORGE_SRC" ]] || { echo "Forge source missing" >&2; exit 2; }
    mkdir -p "$cfg/skills/forge"
    local item
    for item in "${FORGE_RUNTIME_ITEMS[@]}"; do
      if [[ -e "$FORGE_SRC/$item" ]]; then
        mkdir -p "$cfg/skills/forge/$(dirname "$item")"
        cp -a "$FORGE_SRC/$item" "$cfg/skills/forge/$item"
      fi
    done
  fi
  [[ "$MOCK" == true ]] || copy_credentials "$cfg"
}

run_real_agent() {
  local repo="$1" cfg="$2" prompt="$3" transcript="$4" stderr="$5" max_turns="$6" timeout_s="$7"
  local -a perm envargs cmd
  read -r -a perm <<<"$PERMISSION_FLAGS"
  envargs=(-e CLAUDE_CONFIG_DIR=/config -e HOME=/tmp/bench-home)
  [[ -n "${ANTHROPIC_API_KEY:-}" ]] && envargs+=(-e ANTHROPIC_API_KEY)
  cmd=(claude -p "$prompt" --output-format stream-json --verbose --max-turns "$max_turns")
  [[ -n "${CLAUDE_MODEL:-}" ]] && cmd+=(--model "$CLAUDE_MODEL")
  cmd+=("${perm[@]}")

  local rc=0
  python3 "$HERE/container_run.py" "$CONTAINER_RUNTIME" "$timeout_s" -i \
    --user "$(id -u):$(id -g)" \
    "${envargs[@]}" \
    -v "$repo:/workspace:rw" \
    -v "$cfg:/config:rw" \
    -w /workspace \
    "$CONTAINER_IMAGE_ID" "${cmd[@]}" >"$transcript" 2>"$stderr" || rc=$?
  return "$rc"
}

run_agent() {
  local scenario="$1" condition="$2" stage="$3" repo="$4" cfg="$5" prompt="$6" outdir="$7"
  mkdir -p "$outdir"
  printf '%s\n' "$prompt" >"$outdir/prompt.txt"
  local start end rc=0
  start="$(python3 -c 'import time; print(time.monotonic())')"
  if [[ "$MOCK" == true ]]; then
    (cd "$repo" && python3 "$HERE/mock_agent.py" "$BENCH_MOCK_AGENT" "$scenario" "$stage") >"$outdir/stdout.txt" 2>"$outdir/stderr.txt" || rc=$?
    : >"$outdir/transcript.jsonl"
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
               "mock": os.environ.get("MOCK") == "true"}, stream, indent=2)
PY
}

forge_activation_preflight() {
  [[ "$MOCK" == false && "$HAS_FORGE" == true ]] || return 0
  local root repo cfg prompt marker rc=0
  root="$OUT/forge-activation-preflight"
  repo="$root/repo"
  cfg="$root/config"
  mkdir -p "$repo"
  printf '# Forge activation preflight\n' >"$repo/README.md"
  (cd "$repo" && git init -q -b main && git -c core.hooksPath=/dev/null add . && git -c core.hooksPath=/dev/null -c commit.gpgSign=false -c user.name=bench -c user.email=b@x commit -q -m init)
  make_config "$cfg" forge
  marker="FORGE_ACTIVE:$FORGE_VERSION"
  prompt="Use the Forge skill installed in your skill directory. Read its VERSION file and reply with FORGE_ACTIVE: followed by the exact version from that file, and nothing else. Do not modify the repository."
  run_real_agent "$repo" "$cfg" "$prompt" "$root/transcript.jsonl" "$root/stderr.txt" 8 240 || rc=$?
  [[ $rc -eq 0 ]] || { echo "Forge activation preflight agent failed rc=$rc" >&2; exit 2; }
  python3 - "$root/transcript.jsonl" "$marker" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
marker = sys.argv[2]
results = []
for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if isinstance(event, dict) and event.get("type") == "result":
        results.append(event)
if len(results) != 1 or results[0].get("is_error") or results[0].get("subtype") != "success" or results[0].get("result", "").strip() != marker:
    raise SystemExit(f"Forge activation preflight failed: expected exact successful result {marker!r}")
PY
  printf 'PASS %s\n' "$marker" >"$OUT/forge-activation.log"
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
ensure_container
python3 build_fixtures.py --out "$OUT/fixtures" "${SC[@]}" >/dev/null
forge_activation_preflight

if [[ "$MOCK" == true ]]; then
  AGENT_DESC="MOCK:${BENCH_MOCK_AGENT}"
  printf '%s\n' 'MOCK AGENT MODE: these results validate the harness only, not Forge.' >"$OUT/MOCK_RUN.txt"
fi

export OUT FORGE_TAG FORGE_VERSION FORGE_COMMIT FORGE_ASSET_SHA256 FORGE_VERIFIED FORGE_PROVENANCE
export AGENT_DESC CLAUDE_MODEL MAX_TURNS AGENT_TIMEOUT FORGE_INVOCATION SCENARIOS CONDITIONS RUNS BENCH_SEED
export CONTAINER_RUNTIME CONTAINER_IMAGE_ID SCORER_IMAGE_ID BENCH_AGENT_IMAGE BENCH_SCORER_IMAGE MOCK
export SCORER_SOURCE_SHA256 SCORER_TIMEOUT
export FORGE_RUNTIME_PATHS="${FORGE_RUNTIME_ITEMS[*]}"
python3 - <<'PY'
import datetime
import json
import os
import pathlib

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
    "scorer_timeout_s": int(os.environ["SCORER_TIMEOUT"]),
    "scorer_network": "not-applicable" if mock else "none",
    "b3_boundary": "fresh-config-second-session",
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
        if len(condition_order) == 2 and rng.randrange(2):
            condition_order.reverse()
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
    "evidence": evidence,
}
with open(path, "w", encoding="utf-8") as stream:
    stream.write(json.dumps(obj, indent=2) + "\n")
PY
}

run_one() {
  local scenario="$1" condition="$2" run_number="$3"
  local dir="$OUT/$scenario/$condition/run-$run_number" repo="$OUT/$scenario/$condition/run-$run_number/repo"
  mkdir -p "$dir"
  cp -a "$OUT/fixtures/$scenario" "$repo"
  local base
  base="$(git -C "$repo" rev-parse HEAD)"

  local prompt cfg main_dir rc wall timed transcript stderr stage1_result=""
  if [[ "$scenario" == "b3" ]]; then
    local stage1_dir="$dir/stage1" stage2_dir="$dir/stage2" cfg1="$dir/stage1-config" cfg2="$dir/stage2-config"
    make_config "$cfg1" "$condition"
    prompt="$(get_prompt b3-stage1)"
    [[ "$condition" == forge ]] && prompt="$FORGE_INVOCATION
$prompt"
    run_agent "$scenario" "$condition" stage1 "$repo" "$cfg1" "$prompt" "$stage1_dir"
    score_assertion stage1 b3 "$repo" "$stage1_dir/meta-stage.json" "$stage1_dir/transcript.jsonl" "$stage1_dir/run-stage1.json"
    stage1_result="$stage1_dir/run-stage1.json"
    bench_git "$repo" add -A
    bench_git "$repo" -c user.name=bench -c user.email=b@x commit -q -m "stage1 handoff" --allow-empty

    make_config "$cfg2" "$condition"
    prompt="$(get_prompt b3-stage2)"
    [[ "$condition" == forge ]] && prompt="$FORGE_INVOCATION
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
    [[ "$condition" == forge ]] && prompt="$FORGE_INVOCATION
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

while IFS=$'\t' read -r ordinal run_number scenario condition; do
  [[ "$ordinal" == "ordinal" ]] && continue
  run_one "$scenario" "$condition" "$run_number"
done <"$OUT/RUN_ORDER.tsv"

python3 aggregate.py "$OUT"
echo "Report: $OUT/REPORT.md"
