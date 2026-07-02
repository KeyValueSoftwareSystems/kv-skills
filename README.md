# KeyValue AI-SDLC

A ready-to-install pack of **AI skills** and a **Conductor workflow** that runs a feature
through the KeyValue software-development lifecycle: high-level design → detailed design →
implementation → review → QA → release — with a human approval at each gate.

## Why

Building a feature well means the same steps every time: design it, review the design,
implement to a contract, test it, review the code, QA it, ship it. This pack encodes those
steps once so every developer runs them the same way.

- **Run it your way.** Each step is a slash command (`/plan`, `/api-contract`, `/backend-impl`, …)
  you can run in Claude Code, Cursor, or Copilot — or run the whole pipeline end-to-end with
  Conductor.
- **One place to change behavior.** Every step's behavior lives in its skill; which skill (and
  any helper skill) backs each step is one line in [`skills.config.yaml`](skills.config.yaml).
  Change it there and it changes everywhere.
- **Proof, not promises.** Every step writes an artifact to disk, and the pipeline checks the
  file exists before moving on.

## Install

One command from the root of **your** repo:

```bash
curl -fsSL https://raw.githubusercontent.com/keyvalue/kv-sdlc-skills/main/install.sh | bash -s -- claude-code
# ...or for several IDEs at once:
curl -fsSL https://raw.githubusercontent.com/keyvalue/kv-sdlc-skills/main/install.sh | bash -s -- claude-code cursor
```

Prefer to read the script before running it? Download it first, then run it:

```bash
curl -fsSLO https://raw.githubusercontent.com/keyvalue/kv-sdlc-skills/main/install.sh
bash install.sh claude-code
```

The installer:

1. installs **our skills** (`npx skills add keyvalue/kv-sdlc-skills`);
2. installs the **external helper skills** the flow uses ([Superpowers](https://github.com/obra/superpowers) — brainstorming, planning, TDD, code review, debugging, worktrees);
3. copies the **Conductor workflows** + `skills.config.yaml` into your repo (fetched from the repo tarball when run piped);
4. installs **Conductor** if [`uv`](https://github.com/astral-sh/uv) is available (skip with `--no-conductor`).

> Needs Node.js (`npx`) — plus `curl` + `tar` for the no-clone path (both standard on macOS/Linux).
> Conductor runs the full pipeline; you don't need it if you only use the slash commands.

## Use

**As slash commands** (any IDE) — run them in order; you review each artifact before the next:

```
/plan feature="Add saved-search" feature_slug="saved-search"   # high-level design, then approve
/backend-design  ∥  /frontend-design   # author the per-stack LLDs
/api-contract          # reconcile the LLDs → the cross-repo contract
/architecture-review → /backend-impl → /backend-review
/frontend-impl → /frontend-review → /qa → /verify → /fix → /review-pack
```

**As the full pipeline** (Conductor) — the same skills, plus automatic approval gates:

```bash
cd workflows
conductor validate main.yaml
conductor run main.yaml --web \
  --input feature="Add saved-search" --input feature_slug="saved-search"
```

Any single phase also runs on its own, e.g. `conductor run workflows/design.yaml --web --input feature="…" --input feature_slug="saved-search"` (the design phase has a human approval gate, so use `--web`).

> The test / merge / verify shell steps in the workflows are **POC stubs** (`echo` + exit 0).
> Wire them to your real test runner and `kv up` / `kv down` before relying on the pipeline's
> green/red result. Conductor also needs the `claude-agent-sdk` provider — the installer sets
> this up when `uv` is present.

## The flow

```
feature → design phase ─ HLD → [approve]
                         → per-stack LLDs (backend ∥ frontend) → /api-contract
        → architecture-review → [approve]
        → implement (backend ∥ frontend: tasks → code → tests → verify → review)
        → integrate → QA → review pack → [approve → release]
```

The whole design phase is one workflow ([workflows/design.yaml](workflows/design.yaml)): it
authors the HLD, pauses for human approval, then `backend-design` and `frontend-design` each
author one LLD for their stack (`docs/technical/<slug>/lld/`), and `/api-contract` reconciles
them into the cross-repo contract (`contracts/<slug>/`). A human reviews the LLDs + contract
at the next gate. Per-run proof lands under `.sdlc/`; exact paths are in `skills.config.yaml`
under `artifacts:`.

## Skills

| Skill | Command | Edits code? | Purpose |
|-------|---------|:-----------:|---------|
| `plan` | `/plan` | no | High-level design (HLD): options, choice, risks |
| `backend-design` / `frontend-design` | `/backend-design` · `/frontend-design` | no | Author the per-stack low-level design (LLD) — how the feature fits each stack |
| `api-contract` | `/api-contract` | no | Reconcile the LLDs into the OpenAPI contract + acceptance criteria |
| `backend-tasks` | `/backend-tasks` | no | Split scope into ordered tasks + test plan |
| `backend-implement` | `/backend-impl` | yes | Implement to the contract, test-first, to backend standards |
| `frontend-implement` | `/frontend-impl` | yes | Implement UI states + tests to frontend standards |
| `qa-automation` | `/qa` | tests | Critical-journey E2E from acceptance criteria |
| `architecture-review` | `/architecture-review` | no | Review the design: gaps, security, scaling |
| `backend-review` / `frontend-review` | `/backend-review` · `/frontend-review` | no | Review the implementation |
| `verify` | `/verify` | no | Run deterministic checks → proof report |
| `fix-loop` | `/fix` | bounded | Fix failing checks (≤3 attempts), then escalate |
| `human-review-pack` | `/review-pack` | no | Assemble the PR/release pack |

Each editing skill carries the **standards** a change must meet (security, backward
compatibility, migrations, accessibility, performance, …) and a **Safety** section: it will
not write secrets or production config, and it stops to ask a human before anything
destructive.

## Configure

[`skills.config.yaml`](skills.config.yaml) is the one file you edit. It selects, per step:

- which skill runs it;
- which **helper skill** (if any) it delegates part of the work to — a bare skill name, or
  `none` to keep everything in-pack;
- the reviewer per stack and the artifact paths.

The default flow needs exactly one external pack (Superpowers, installed by the script). Every
other helper slot ships as `none`. **Review any third-party skill before wiring it in** — treat
marketplace skills as untrusted code.

Conductor-only knobs (fix-loop cap, coverage gate, environment lifecycle) live in
[`workflows/workflow.config.yaml`](workflows/workflow.config.yaml). Per-step model choices are
set directly on each workflow step (`model:` field).
