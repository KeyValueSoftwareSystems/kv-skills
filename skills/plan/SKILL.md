---
name: plan
description: Produce a high-level design (HLD) for a feature — frame the problem, weigh options with trade-offs, choose an approach, define non-functional requirements and risks, and write a standardized hld.md. Read-only (writes only the HLD doc). Use first, before detailed design. Front door for /plan.
allowed-tools: Read, Grep, Glob, Bash, Write
---

# plan — high-level design

Turn a feature request + PRD into a **high-level design**: the shape of the solution, the
options considered, the chosen approach, and the risks — enough for a human to approve the
*direction* before anyone designs APIs or writes code. This is a design artifact, not code.

## When to use / not use
- **Use** at the very start of a feature, once a PRD/intent exists.
- **Don't** design APIs, schemas, or code here — that is the design phase (per-stack LLDs +
  `/api-contract`) after approval.

## Inputs
- `feature` — one-line description.  `feature_slug` — kebab-case id for artifact paths.
- `prd_path` — the PRD (assumed to exist).
- **Artifact path** — you resolve it yourself from `skills.config.yaml` → `artifacts.hld`
  with `{slug}` = `feature_slug` (i.e. `docs/technical/<slug>/hld.md`). The caller does not
  pass a path; this skill owns where it writes.

## Steps
1. **Gather context** — read the PRD, related ADRs, `CLAUDE.md`, and any existing design.
   Identify the users, the job-to-be-done, and hard constraints (deadlines, platforms,
   compliance, budget).
2. **Clarify unknowns** — list assumptions explicitly; ask the human when a business rule,
   SLA, or data-ownership question is genuinely ambiguous. Do not silently guess.
3. **Diverge** — generate 2–3 genuinely different approaches (delegating to the external
   brainstorming skill if configured). Run a quick pre-mortem on each ("how would this
   fail?").
4. **Evaluate & choose** — score options against effort, risk, NFRs, and reversibility.
   Recommend one; say *why it wins* and what you're trading away.
5. **Sketch** — components, data flow, and the cross-repo boundary (which stacks change).
6. **Nail the NFRs and risks** — sections below.
7. **Write** the artifact and summarize open questions for the reviewer.

## What to cover (standard HLD sections — write all)
1. **Context & problem** — what, why, who; link the PRD.
2. **Goals / non-goals** — explicit scope boundaries.
3. **Options considered** — 2–3 approaches, each with trade-offs (cost, risk, effort, time-to-value).
4. **Chosen approach** — the recommendation and the reasoning.
5. **Architecture sketch** — components, data flow, boundaries, external dependencies.
6. **Non-functional requirements** — security & privacy (authz model, PII, threat surface),
   scale/throughput, availability/SLO, latency budget, cost, compliance/data residency.
7. **Data lifecycle** — what data is created/read/updated/deleted, retention, ownership,
   and any backfill/migration of existing data.
8. **Backward compatibility & migration** — impact on existing clients/data; additive vs breaking.
9. **Dependencies & sequencing** — other teams/services, feature flags, order of rollout.
10. **Rollout & backout** — flagging, phased rollout, metrics to watch, how to revert.
11. **Risks & mitigations** — top risks each with a mitigation and an owner.
12. **Open questions** — anything a human must resolve before LLD.

## Edge cases & failure modes to think through now
- Ambiguous or conflicting requirements; multiple stakeholders wanting different things.
- Greenfield vs brownfield (existing constraints, legacy data, in-flight migrations).
- Multi-tenant / data-isolation needs; regulated data (PII/PHI/PCI).
- Large existing dataset requiring backfill; zero-downtime migration.
- Third-party dependency risk (rate limits, outages, cost, lock-in).
- High-concurrency or spiky load; graceful degradation under partial failure.
- Reversibility: can we ship behind a flag and roll back cleanly?

## External skill (provision — ideation)
Read `skills.config.yaml` → `plan.external.brainstorm` (default `brainstorming`, from the
Superpowers pack, or `none`). If it names a skill, use it to diverge and pressure-test — but **you remain
responsible** for the coverage above. Whatever the external skill does, ensure it produced:
alternatives with trade-offs, surfaced assumptions, and a pre-mortem. If `none`, do this
yourself.
## Output
Write `docs/technical/<slug>/hld.md` with the sections above, including an
"Open questions" section. Return `hld_path` and `hld_summary` (2–3 sentences).
Keep open questions in the HLD's "Open questions" section — do not return them as a
separate structured output field.

## Definition of done
Every section present; ≥2 options with trade-offs; NFRs and risks concrete (not "TBD");
open questions listed. Do not proceed to detailed design — that is the design phase (LLD +
`/api-contract`) after human approval.
