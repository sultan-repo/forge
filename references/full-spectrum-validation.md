# Full-Spectrum Validation Reference

Use for project inception/redefinition, major architecture/operating-model changes, repeated systemic failures, major milestones, production readiness, major releases, or explicit maximum-depth review.

Purpose: determine whether the project remains the strongest practical path to the ultimate objective, not merely whether current code is clean.

## Evidence base

Inspect applicable primary sources:
- requirements/invariants
- master plan, Plan Deltas, control state, requirement coverage
- architecture/decisions
- source/tests/config
- schemas/migrations
- infrastructure/deployment
- UI/workflows
- operations/runbooks
- logs/metrics
- AI evaluations/data
- risks/deferred work

State objective, success criteria, constraints, current milestone, active Work Packet, assumptions, plan coverage, and evidence gaps.

## Dynamic panel

Derive perspectives from project risk. No fixed roster.

Possible domains: product, business, domain, users, operations, architecture, software, data, AI, security, privacy, reliability, performance, UX, accessibility, QA, infrastructure, integrations, hardware, cost, legal/compliance, support, implementation feasibility.

Use the smallest complete panel and expand only when distinct expertise/evidence can change confidence.

Reviewers inspect primary sources independently.

Verify Critical/High findings against primary evidence and credible counterexamples before accepting them. A separate reviewer is useful when it can add evidence or expose a mistaken assumption; it is not required merely to fill a panel.

## Challenge direction and plan integrity

Assess preserve/revise/expand/reduce/replace/defer for requirements, scope, workflows, architecture, implementation, and operating model.

Also verify:
- no approved requirement disappeared
- no milestone silently vanished
- all detours are linked/dispositioned
- Plan Deltas explain material roadmap changes
- control state matches actual implementation
- resume queue is clear

Compare credible contemporary/proven alternatives where relevant.

Assess value, evidence, effort, migration risk, operational complexity, cost, skills, dependencies, lock-in, maintainability, and reversibility.

## Synthesis

Resolve contradictions, deduplicate findings, and separate root causes from symptoms.

Lead with whether the implementation serves the objective, the most important verified findings, and the evidence gaps. Explain scope or direction changes only when they are material.

Group actions by the actual work or risk. Do not invent empty categories, a UI/UX section for a non-UI project, or a separate roadmap for a short set of related fixes.

Priority:
- P0 immediate blocker/unacceptable risk
- P1 required before next major milestone/release
- P2 material improvement
- P3 optional optimization

For each material action include the problem, evidence, consequence, expected correction, and how to verify it. Add dependencies, effort, ownership, rollback, or control-state changes only where they help a decision or implementation.

Use a phased roadmap when sequencing or independent milestones justify one.

For material scope changes, provide:
- Baseline roadmap within approved scope
- Recommended roadmap with justified objective-serving changes

Separate safe-to-begin, approval required, evidence required, and deferred opportunities.

Implement corrections already authorized by the user. A review-only request does not authorize implementation, and recommendations that materially change approved scope still require normal decision authority. Do not ask again for authority already granted.

## Cross-cutting checks

A full-spectrum review must also evaluate:
- Plan Consistency: whether approved requirements have a coherent delivery/verification path
- Convergence: whether actual implementation matches canonical requirements/design
- Trust boundary: whether retrieved/untrusted content can influence privileged decisions or tool use
- Scope/review triage: whether review findings are being allowed to hijack current work
- Context/orchestration efficiency: whether controller context is overloaded or optional parallel mechanisms are being overused
- Canonicalization: whether accumulated deltas are obscuring current truth
- Methodology fit: whether Control Mode/process overhead remains proportional to project risk
