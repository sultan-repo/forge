# Requirements Discovery and Applicability Reference

Load this reference when eliciting, challenging, consolidating, or changing requirements.

## Interview discipline

Ask questions only when answers can materially alter objective, scope, behavior, architecture, data, security/privacy, operations, integrations, cost, deployment, acceptance criteria, or sequencing.

Prefer batches of roughly 3-7 related questions when practical.

Stop interviewing when remaining uncertainty can safely be represented as reversible assumptions, evidence gaps, or deferred items.

When the user is uncertain:
1. identify credible options
2. explain meaningful trade-offs
3. recommend one
4. allow delegated decision-making

Do not ask the user to rediscover facts available from source code, config, docs, tests, schemas, or runtime evidence.

## Applicability dimensions

Assess where relevant:

### Product/business
Problem, user value, success measures, adoption, business viability, cost/value.

### Users/stakeholders
Customers, end users, admins, employees, operators, reviewers, supervisors, support, field staff, external parties.

### Functional behavior
Primary flows, alternate flows, invalid states, edge cases, misuse, errors, recovery, lifecycle.

### Human operations
Roles, permissions, segregation of duties, availability, working hours, intake, queues, priorities, SLAs, assignment, claiming, reservation, reassignment, concurrency, locking, duplicate work, workload/capacity, escalation, timeout, abandonment, second review, disagreement, appeal, override, handover, supervision, auditability, fraud, collusion, manipulation, misuse.

Do not introduce operational machinery unless the actual operating model needs it.

### UX/accessibility
Journeys, information architecture, friction, accessibility, responsiveness, loading, error/empty/offline states, destructive actions, recovery, onboarding.

### Architecture
Boundaries, responsibilities, interfaces, state ownership, coupling/cohesion, maintainability, testability, failure isolation.

### Data
Ownership/source of truth, schemas, validation, quality, consistency, lineage, retention, deletion, privacy classification, migration, reconciliation, backup.

### AI/automation
Only when relevant: responsibilities, models, prompts, tools, agents, evaluations, calibration, confidence, hallucination risk, guardrails, fallback, human oversight, drift, privacy, latency, cost, observability.

### Security/privacy
Authentication, authorization, least privilege, secrets, input/output validation, injection, privilege escalation, sensitive data, encryption, audit, abuse/fraud, supply-chain risk.

### Integrations
APIs, vendors, contracts, auth, quotas, rate limits, timeouts, retries, degraded mode, fallback, versioning, lock-in, cost.

### Hardware/environment
Devices, sensors, OS, connectivity, power, environmental limits, physical failure/abuse, maintenance.

### Performance/scale
Expected workload, concurrency, latency, bottlenecks, capacity, storage growth, scaling strategy, cost.

### Reliability/operations
Availability, logs, metrics, alerts, retries, timeouts, idempotency, backup, disaster recovery, reconciliation, incident handling, support ownership.

### Delivery/lifecycle
Testing, CI/CD, environments, deployment, migrations, rollback, monitoring, upgrades, backward compatibility, support, decommissioning.

### Legal/compliance
Only when relevant: laws, regulations, contracts, licensing, privacy, retention, data residency, industry standards.

Mark meaningful exclusions as Not Applicable when ambiguity would otherwise remain.

## Readiness baseline

A material requirements baseline should normally contain:

1. Ultimate objective
2. Success measures
3. Users/stakeholders
4. Scope/priorities
5. Non-goals
6. Mandatory constraints
7. Functional requirements
8. Applicable non-functional requirements
9. User journeys
10. Operational workflows where applicable
11. Edge cases/misuse/failure handling
12. Data requirements
13. Security/privacy
14. Integrations
15. Technical/environment constraints
16. Assumptions
17. Recommended changes to initial scope
18. Deferred items
19. Blocking decisions/evidence gaps
20. Measurable acceptance criteria
21. Project invariants

For substantial projects, give stable IDs to requirements where useful.

## Change control

When a confirmed material requirement changes, record:
- previous requirement/intention
- new requirement
- reason
- approving decision
- affected architecture/components
- affected tests/acceptance criteria
- master-plan and migration impact

Prefer explicit deltas to silently rewriting history when historical intent matters.

## Assumption checkpoint

Before an expensive/high-risk milestone, surface only assumptions that could invalidate substantial planned work. Record evidence/confidence, impact if false, validation trigger, and decision authority. Low-risk reversible assumptions should not create user-interruption overhead.

## User-facing acceptance scenarios

For important user journeys, describe observable behavior in Given/When/Then or equivalent plain language when useful. Acceptance scenarios should test the user's outcome, including relevant failure/recovery behavior, not merely implementation details.

Trace scenarios back to requirement IDs when practical.
