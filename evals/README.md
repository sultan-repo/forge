# Forge Skill Evals

This directory contains behavioral regression scenarios for the methodology.

`evals.json` follows Anthropic skill-creator's eval schema: each case contains a realistic prompt, expected behavior, and verifiable expectations.

The skill is intentionally `disable-model-invocation: true`, so these are behavior/quality evals, not automatic-trigger evals.

Recommended evaluation loop after material skill changes:
1. validate/package the skill
2. run the same eval prompts with the skill and against a no-skill baseline using Anthropic's current skill-creator workflow
3. grade expectations and compare quality, token use, and execution time
4. inspect failures/false bureaucracy manually
5. modify the skill only when evidence supports the change

Important regression targets include proportionality, requirements discovery, plan consistency, scope conservation, stale workers, convergence, prompt injection, review triage, compaction recovery, and capability-aware orchestration.
