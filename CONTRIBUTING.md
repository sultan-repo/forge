# Contributing to Forge

Forge is a methodology skill. Changes should be driven by observed behavior rather than prompt expansion for its own sake.

## Principles

- Preserve proportionality.
- Prefer enforceable invariants over repeated prose when strict behavior matters.
- Do not hardcode model names, model generations, platform versions, or temporary tool availability as policy.
- Detect capabilities at runtime and provide graceful fallbacks.
- Avoid fixed technology stacks, folder trees, and agent rosters.
- Keep `SKILL.md` compact; put deep mechanics in references.
- New universal rules should address demonstrated cross-project failure modes.
- Preserve scope conservation, authority, trust boundaries, verification, and convergence.
- Preserve safe remote-bootstrap behavior.

## Before submitting a methodology change

1. run `python3 scripts/validate-skill-package.py`
2. add/update a regression scenario when behavior changes
3. for broad control changes, run the relevant core benchmarks
4. compare baseline, current Forge, and candidate/ablation when removing or relocating rules
5. record results rather than inferring improvement from prompt quality

See `evals/README.md`.
