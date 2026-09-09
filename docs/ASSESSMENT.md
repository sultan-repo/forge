# Forge end-to-end assessment and revision

This assessment started from GitHub `main` at `db120ae`. It covers the instruction package, optional execution helpers, persistent state, installation, public evaluation instrument, and CI. It uses source and failure-path tests as well as the earlier experimental benchmark findings. The experimental worktrees and private run artifacts are not shipped in this change.

## Intended value

Forge should preserve the user's intended outcome through interruptions, detours, and multiple workstreams. It should add little work to a bounded task and use more structure only when that structure prevents mistakes or repeated investigation. This is a design objective, not a measured guarantee of zero tokens, latency, or cost.

The previous package mixed an approximately 9.7 KB entrypoint with detailed control procedures and required substantial-work preflight. Its optional safeguards were sometimes treated as default steps. The public benchmark could also confuse preferred process artifacts with successful task behavior. These problems warranted changes across the package rather than another universal checklist.

## Required changes and disposition

| Area | Finding and required change | Revision / validation |
|---|---|---|
| Initial context | Every invocation loaded detailed planning, gate, and runner instructions. Route before loading mode-specific detail. | Short entrypoint; new planned/high-risk references; existing detailed references remain conditional. Package validation checks links. Byte reduction measures initial text only. |
| Small tasks | A proportionality slogan did not define a usable direct path or stop condition. | Inspect/edit/check/finish without setup, formal plan, new state, or extra agents by default. No arbitrary tool-call or testing cap. Behavioral scenarios cover escalation and stopping. |
| Authority | Setup and baseline confirmation could re-ask decisions already supplied. | Reuse current authorization; ask only for material missing decisions or consequential actions outside it. Necessary reversible implementation remains autonomous. |
| Plan synchronization | Relevant text updates could trigger a revision/decision ceremony or broaden an invariant exception. | Correct only the contradicted requirement, preserve unrelated invariants, and honor explicit project record rules. Material scope changes retain change control. |
| Persistent state | Parallel status/control/resume documents and repeated full-history loading could create more work and contradictory truth. | Prefer one existing current surface, evidence pointers, active-slice resume, and updates at material changes/handoff. Structured control remains optional except for helpers that require it. |
| Verification | Task labels, broad green suites, and reported gaps could be mistaken for verified completion. | Tie each affected claim to the actual check/result; distinguish failed/unverified/dispositioned from satisfied. Check relevant entry points and compare the starting state before attributing regressions. |
| Risk | A small edit can still have serious consequences; file count is a poor routing rule. | Route by actual security/data/production/compatibility consequences; retain safeguards and required review without requiring a multi-agent loop for every risk. |
| External readiness | Missing preferences and future Codex policies blocked unrelated work; live probing was the default preference. | Current-session work needs no CLI preflight. External readiness uses local defaults, checks the requested task/review route, and starts live probes only explicitly. |
| Probe truth | Successful process exit could be accepted without a valid expected provider response; old evidence could survive a failed probe. | Validate successful structured response and exact probe output, preserve original observation time, invalidate failed evidence, and version readiness reports. Tests exercise false-positive paths. |
| Authentication | Runner dispatch could ignore the project's saved subscription/authentication or live-readiness requirements. | Validate saved preferences before external dispatch without automatically making a provider call or switching credentials/billing. |
| Runner context | External prompts duplicated unrelated controller state and could imply review approval meant delivery was done. | Focus the execution contract on the active packet and relevant state; distinguish checkpoint approval from controller reconciliation and completed requirements. |
| Lifecycle hooks | Completion checked only the first named packet; subdirectory startup missed the project; validator failures could hang or obscure state problems. | Check every explicit packet, resolve project context, bound validators, show warnings, and reject stale or contradictory completion. Focused subprocess tests cover failures. |
| State compatibility | Completion fields could contradict `done`, and legacy states lacked evidence pointers. | Reject explicit contradictions; report missing legacy evidence as warnings so existing projects can resume without an unrelated migration. Structural validity still cannot prove business behavior. |
| Installation | Missing Python could bypass full package validation before replacement; preflight support files were not required. | Fail before mutation when validation cannot run, require shipped support files, retain atomic staging/rollback/locking. |
| Public scoring | Arbitrary plan/file/module gates and incomplete hidden-test accounting could reward the wrong behavior or hide missing evidence. | New versioned automatic criteria with public-contract tests, complete expected-test evidence, observed process metrics, and explicit pending semantic review. Historical criteria/results are distinct. |
| Comparison validity | Mixed criteria or incomplete matrices could still produce apparently comparable aggregate results. | Refuse incompatible inputs and suppress unsupported headline comparisons. Mocks test the instrument, not real agent outcomes. |
| Behavioral coverage | Many evaluation cases were process instructions rather than natural requests; instruction-only PRs could bypass relevant CI. | Add realistic direct/risk/resume cases and extend CI triggers. Scenario files are test specifications, not executed live measurements. |
| Release metadata | Main's draft 1.11 changelog heading disagreed with `VERSION` 1.10.0, breaking validation/install. | Keep unshipped work under Unreleased and retain the published version until a deliberate release change. No release is performed by this PR. |

## Retained mechanisms

Existing immutable review checkpoints, bounded correction cycles, read-only reviewer isolation, process cleanup, stale-result reconciliation, installation rollback, and release provenance checks solve concrete problems. Replacing those working mechanisms would add migration risk without demonstrated benefit. Hooks, external agents, and structured state remain available when their value or project policy justifies their overhead.

## What still needs measurement

Source changes and passing deterministic tests establish specific behavior and contracts. They do not prove that models follow every instruction, that a shorter entry reduces total session usage, or that Forge improves outcomes across projects.

Before making an effectiveness or release-readiness claim, run fresh matched comparisons on:

1. natural bounded tasks, measuring complete task correctness and paired tokens/time;
2. genuinely interrupted multi-session projects, measuring recovery time, repeated investigation, missed requirements, and state accuracy;
3. high-risk changes, measuring safeguard behavior and evidence, with speed reported separately;
4. realistic requirement changes and detours, measuring return to still-approved work.

Freeze task contracts, criteria, identities, comparison rules, and resource limits first. Use complete paired blocks and independent evidence review. Report uncertainty and failures; do not use small samples or equal pass totals as proof of equivalence. Provider-estimated dollars, reported tokens, and actual billing/subscription usage are different measurements.

This revision prepares the implementation and evaluation paths. It does not run a new paid/subscription benchmark, merge itself, or publish a release.
