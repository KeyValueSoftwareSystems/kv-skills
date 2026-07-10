# Maestro — KeyValue AI-SDLC

Run the full software lifecycle — design → review → implement → QA → release — as an
orchestrated, resumable workflow **inside your own AI coding session**. No headless
runners, no API keys, no per-seat orchestration bill: the *lead agent* is your
interactive Claude Code / Cursor session, driven by one skill.

```
requirement → HLD → [open-questions loop → approve] → parallel LLDs → API contract
   → functional test cases → architecture review → [approve]
   → implement per stack (parallel, sliced, reviewed, bounded fix loop)
   → QA → review pack → [approve → release]
```

Every producing step writes an artifact to disk and the engine refuses to advance
without it — **proof, not promises**. Every irreversible decision goes through a human
gate. Kill your session anytime; the run resumes exactly where it stopped.

## How it works

```
            you: /maestro my-feature
                     │
       ┌─────────────▼──────────────┐    engine/maestroctl.py (stdlib python3)
       │  LEAD AGENT (your session) │───► next → ONE action as JSON
       │  dispatches, never decides │◄─── complete / gate-record / fail
       └──┬─────────┬──────────┬────┘
          ▼         ▼          ▼
      subagents   scripts    you (gates)
      (skill +    (validators,
       model per   stubs)
       step)
```

- **`workflow.yaml`** — the graph: 5 node types (`agent`, `gate`, `script`, `parallel`,
  `subworkflow`), per-node routes with tiny conditions, and **back-edges for loops**
  (an arrow to any earlier step; the engine cascade-resets downstream work and enforces
  a per-node visit cap so loops can't run away). Spec: [docs/workflow-spec.md](docs/workflow-spec.md).
- **`.maestro/<slug>/state.yaml`** — the run ledger. Only the engine writes it. Resume,
  revise-cascades, gate history, parallel-join bookkeeping all live here.
- **The lead agent never interprets the graph.** The deterministic resolver serves one
  fully-rendered action at a time; the LLM just dispatches it. That is what makes an
  LLM-driven orchestrator reliable — and it's all plain, tested Python
  (`python3 engine/tests/run_all.py`, no LLM in the loop).
- **Agent steps are instruction-first**: write what the step should do; optionally pin
  a skill (the shipped workflows pin everything for reproducibility) and a model.
  Subagents run in parallel where the harness supports it (Claude Code); elsewhere the
  same workflow runs inline and sequential — same engine, same state.

## The visual builder

`maestro ui` (or double-click `ui/builder.html`) — a single self-contained page, no
server, works offline:

- start from a **template gallery** (the shipped SDLC workflows) or a blank canvas;
- **instruction-first node editing** — describe the step; skill defaults to *Auto*
  (pin one under Advanced), model/agent are dropdowns;
- drag arrows between nodes — **arrows pointing back create loops**, shown dashed with
  their repeat-limit badge;
- gates' options *are* their outgoing edges; parallel branches edit via drill-in;
- live validation with friendly messages; one-click export that the engine accepts
  (positions persist in a `ui:` key the engine ignores).

## Install

From the root of your project repo:

```bash
curl -fsSL https://raw.githubusercontent.com/KeyValueSoftwareSystems/kv-skills/main/install.sh \
  | bash -s -- claude-code cursor        # pick your IDE(s)
```

Installs: our skills/commands/agents into `.claude/` / `.cursor/`, the six external
Superpowers skills the flow delegates to, `engine/` + `workflows/` + `ui/` +
`maestro.config.yaml` into your repo, and the `maestro` CLI onto your PATH. The engine
is stdlib-only python3 — nothing else to install.

## Run

```bash
maestro init my-feature      # scaffolds .maestro/my-feature/requirement/
# drop requirement files in (PRDs, tickets, notes — every file is read)
```

Then in your IDE:

```
/maestro my-feature                          # full pipeline (workflows/sdlc-main.yaml)
/maestro my-feature workflows/design.yaml    # just one phase
```

The lead agent validates, resumes or starts the run, spawns a subagent per step, asks
you at gates, and reports where every artifact landed. Useful alongside:

```bash
maestro status my-feature                    # step table, gate history, active steps
maestro validate workflows/my-flow.yaml      # lint any workflow
maestro reset my-feature --step review --cascade   # force a rebuild from a step
maestro ui                                   # the builder
```

Prefer manual control? Every skill is also a slash command (`/plan`, `/backend-impl`,
`/qa`, …) — same skills, no orchestration.

## Layout

```
skills/      one SKILL.md per SDLC step + skills/maestro (the lead agent)
agents/      subagent definitions (planner, implementer, reviewer, qa, analyst, general)
commands/    thin slash-command shims
workflows/   the example pack: sdlc-main / design / impl / qa  — customize or replace
engine/      the deterministic engine (validate · init · next · complete · gate-record
             · fail · reset · rebase · status · graph) + schemas + helper validators
ui/          builder.html (single-file visual editor) + embed.py
maestro.config.yaml   models & aliases, engine defaults, fix-loop cap, external-skill
                      delegation, artifact path map
.maestro/<slug>/      everything for one feature: requirement/ + all artifacts + state.yaml
```

## Customizing

- **Change a step's behavior** — edit its skill (`skills/*/SKILL.md`).
- **Change the flow** — edit the workflow YAML (or use `maestro ui`). Steps name skills
  directly; swapping one is a one-line change.
- **Models** — per node (`model: sonnet`), per workflow (`defaults.model`), or globally
  (`maestro.config.yaml → models`). Aliases keep workflows stable when model ids rotate.
- **Loop bounds** — per node `max_visits` (+ `on_exhausted`), backstopped by
  `defaults.max_visits`; the fix loops use `${config.fix_loop.max_attempts}`.
- The merge/contract-check/archive scripts in the example pack are **POC stubs** —
  wire them to your real runners.

## Checks

```bash
python3 engine/tests/run_all.py          # 66 tests: parser, validator, ledger, resolver
                                         # simulations, full-SDLC e2e (no LLM needed)
python3 testdata/test_ui_schema_sync.py  # UI ↔ engine anti-drift (+ cross-parser test)
open ui/builder.html#selftest            # in-browser round-trip suite
```
