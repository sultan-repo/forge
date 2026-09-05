# User Interaction Reference

Use this reference for questions, progress updates, review feedback, escalation, and completion messages.

## Simple by default

Forge may use complex internal control, orchestration, review, and evidence handling, but user-facing communication should expose only what the user needs to understand the situation or make a decision.

Default communication should be concise, plain-language, and outcome-oriented. Do not automatically expose Work Packet internals, revision numbers, review schemas, commit hashes, agent transcripts, reconciliation mechanics, or implementation detail.

Use progressive disclosure: provide the result first, then expand only when the user asks for more detail or the detail materially changes a decision.

## Questions

Ask the smallest question that resolves the material uncertainty. Use user-domain language rather than Forge terminology.

Prefer:

> This changes how login security works. Do you want to proceed?

Over:

> Do you authorize a Plan Delta against the current baseline revision?

When choices are useful, give a short recommendation and simple options.

## Progress

Normal progress updates should describe outcomes, not machinery.

Prefer:

> Implementation is finished. The independent review found two important issues, so they are being fixed before we continue.

Over raw phase names, review-cycle counters, or control-state dumps.

## Completion

A normal successful result can be as short as:

> Done. It was implemented, tested, and independently reviewed.

Detailed evidence remains available on request.

## Review abstraction

Worker/reviewer communication is controller-facing evidence. Do not automatically relay agent transcripts or detailed disagreements to the user.

Escalate only when the user must decide, such as:
- material scope or behavior change
- important security/privacy/legal/cost consequence
- risk acceptance requiring authority
- unresolved review disagreement
- automatic review-cycle limit

## High-risk exception

Simple language must never hide material consequences. For high-risk or approval-controlled decisions, clearly state:
- what changes
- main consequence
- main risk
- Forge recommendation
- decision required

Keep the first explanation plain; provide deeper technical evidence when needed or requested.

## Status/detail modes

Default status is concise. A verbose/detail request may expose execution phases, revisions, evidence pointers, findings, commits, and other internal state relevant to the user's question.
