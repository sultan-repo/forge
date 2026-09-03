# Contributing to Forge

Forge is a methodology skill, so changes should be driven by observed behavior rather than prompt expansion for its own sake.

## Principles

- Preserve proportionality. Tiny tasks must remain lightweight.
- Prefer enforceable invariants over repeated prose when strict behavior matters.
- Avoid fixed technology stacks, folder trees, or agent rosters.
- Keep `SKILL.md` compact and move deep procedures into references.
- New universal rules should address a demonstrated cross-project failure mode.
- Do not weaken scope conservation, authority, trust boundaries, verification, or convergence.
- Preserve the one-prompt remote-bootstrap path and explicit-name-only auto-invocation behavior.

## Before submitting a change

Run:

```bash
python3 scripts/validate-skill-package.py
```

If the change affects behavior, add or update a regression scenario in `evals/evals.json`.

Useful evaluation compares the same realistic project scenario:

1. without Forge
2. with the current Forge release
3. with the proposed Forge change

Prefer changes that improve correctness, adherence, or efficiency without creating unnecessary ceremony.
