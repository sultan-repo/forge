# High-risk work

Read before work that changes access/security/privacy boundaries, can destroy data, affects production, creates costly commitments, or materially changes compatibility or migrations. Risk depends on consequences, not the number of edited lines.

1. Identify the affected behavior, failure consequence, target environment, and existing authorization. Reuse explicit permission already given. Ask before a material action outside that authority; a skill does not grant additional permission.
2. Establish proportionate safeguards: a reversible checkpoint, validated backup/rollback where relevant, narrow targeting, least privilege, and observable acceptance checks. Investigate locally and prepare reviewable changes before an external approval step.
3. Verify the risky path and relevant failure/recovery paths. For a destructive operation, a happy-path test alone does not establish the safeguard. For security or privacy, check the actual boundary being changed. Follow [trust and security](trust-and-security.md) where applicable.
4. Obtain independent review when required by the user/project or when its likely information value justifies the cost. If a required reviewer is unavailable, surface the blocker and continue independent safe work; do not silently reduce assurance. A tiny risky edit does not automatically need a multi-agent implementation loop.
5. Record the evidence and any residual uncertainty or accepted risk in the existing project surface. A failed check or missing rollback proof remains unresolved until corrected or dispositioned by the appropriate authority. Risk acceptance is not a statement that the requirement passed.

For multi-step or interrupted work also load [planned work](planned-work.md). For a bounded risky change these checks may fit in the existing task without new control files. For an explicitly requested external agent route use [project preflight](project-preflight.md); current-session implementation does not require a separate CLI authentication probe.
