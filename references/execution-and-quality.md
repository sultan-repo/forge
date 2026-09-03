# Execution, Verification, Review, and Safety Reference

Load this reference for implementation, debugging, validation design, high-risk changes, independent review, or completion gates.

## Verification-first

Every meaningful change should have an observable way to determine whether it works.

Select evidence by change:
- unit/integration/contract/end-to-end/regression tests
- expected output
- visual/screenshot comparison
- types/lint/static analysis
- dependency/security checks
- migration/rollback tests
- performance/load/resilience tests
- accessibility/usability checks
- concurrency/timeout/retry/recovery tests
- operational workflow simulations
- data integrity/reconciliation
- AI evaluations/calibration/fallback/drift checks
- runtime metrics

For UI work, verify rendered behavior when tools allow.

## Spec compliance before code quality

First ask:
- Was the approved behavior implemented?
- Are linked requirements/acceptance criteria satisfied?
- Are invariants preserved?
- Did work stay within the packet or use an explicit Plan Delta?
- Is any approved plan item no longer accounted for?

Then assess engineering quality: correctness, architecture/maintainability, security/privacy, performance/reliability, operations, failure handling, tests, and unnecessary complexity.

## Independent review contract

For each reviewer provide:
- objective
- bounded question
- parent milestone/packet
- linked requirements
- scope
- required primary sources
- evidence expected
- output format
- edit permissions
- prohibited changes
- completion criteria
- return_to

Reviewers inspect primary evidence and work independently before synthesis.

Finding fields:
- ID/title
- Severity: Critical/High/Medium/Low
- Confidence: High/Medium/Low
- Evidence
- Impact
- Root cause
- Alternative explanations
- Recommendation/alternatives
- Effort/dependencies/reversibility
- Acceptance criteria
- Validation method
- Approval/external-validation need

## Adversarial verification

Every Critical/High finding should be independently challenged.

Attempt to reproduce/verify, disprove, find supporting/contradictory evidence, identify alternatives, assess reachability/probability/impact, change severity when warranted, separate cause from symptom, and assess whether the remedy addresses root cause.

Verdicts:
- Confirmed
- Confirmed with Modified Severity
- Partially Confirmed
- Unverified
- Rejected
- Requires Runtime/Field/External Validation

Unverified serious risks go to a validation backlog with a concrete evidence-gathering action.

## Completion gates

Work Packet gate:
- acceptance criteria dispositioned
- required validation recorded
- linked requirements/invariants updated
- discovered work classified
- Plan Delta recorded when needed
- reconciliation complete
- return_to resolved

Milestone gate:
- all planned packets terminal or explicitly moved by Plan Delta
- linked requirements covered
- required validation passes
- final diff reviewed
- Critical findings resolved
- High findings resolved or explicitly accepted
- resume queue known

## Debugging

For non-trivial failures:
1. reproduce
2. establish expected behavior
3. narrow failing path
4. determine root cause
5. distinguish cause/symptom
6. add regression evidence where practical
7. smallest justified fix
8. rerun reproduction
9. broader relevant regression checks
10. reconcile to parent Work Packet

Never weaken tests, suppress errors, or add unexplained retries just to turn checks green.

## Change safety

Never without appropriate authorization/safeguards:
- expose/commit secrets
- weaken security controls
- destructively alter production data
- force-push or rewrite shared history
- delete ambiguous user-authored files
- silently change licensing/legal terms
- mix unrelated mass refactoring into scoped work

For risky work, establish a reversible checkpoint.

## Deterministic guardrails

If a rule must always hold, encode it through the strongest appropriate mechanism: tests, types, schema/database constraints, CI, permissions, hooks, automated checks, or infrastructure policy.

Do not rely on prose alone for hard guarantees.

## Review finding triage

Classify every material review finding on two independent axes:

### Severity
`Critical | High | Medium | Low`

### Scope relevance
- `current_required`: directly required to satisfy current packet/spec
- `current_blocking`: prevents safe/correct completion of current work
- `adjacent`: useful improvement near current code but not required now
- `future`: relevant to an approved later milestone
- `unrelated`: legitimate issue outside current approved scope

Only `current_required` and `current_blocking` automatically enter current implementation.

A Critical/High finding that is adjacent/future/unrelated must be surfaced promptly and given an explicit disposition according to risk/authority. Severity does not grant permission to silently rewrite scope.

## Verification mechanism ladder

Prefer the lowest-cost mechanism that gives confidence appropriate to risk:
1. deterministic test/check/expected output
2. focused manual/runtime/UI verification
3. independent verification subagent/reviewer
4. session-level goal/completion condition where supported
5. TaskCompleted/Stop/lifecycle enforcement where deterministic and worth the overhead

Do not add hooks or multi-agent review when a simple deterministic check proves the requirement.

## Convergence handoff

Packet/milestone quality review does not replace project convergence. At major closure, use the Convergence Gate to compare actual behavior against canonical requirements and architecture, including missing requirements and material unapproved excess scope.
