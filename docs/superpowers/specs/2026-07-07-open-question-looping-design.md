# Open-question looping in the plan/design flow

**Date:** 2026-07-07
**Status:** Approved (design) — ready for implementation plan
**Feature slug:** `open-question-looping`

## Context & problem

When the `/plan` skill produces an HLD, it lists **open questions** a human must
resolve before detailed design. Today those questions are prose in the HLD's
"Open questions" section, and the only way to act on them is the Conductor
`design.yaml` `hld_approval` gate's **"Request HLD revisions"** option, which
collects a single free-text `feedback` blob — the human answers *everything at
once* in one prose field. There is no per-question structure, no suggested
answers, and no iterative loop.

We want a **Claude `AskUserQuestion`-style experience**: each open question is
presented individually with 2–4 suggested answers plus an always-present
**Other** (custom text), the user answers per-question, the plan is **refined**
using those answers, and — because refinement can surface *new* questions — the
flow **loops until no open questions remain**.

A prior attempt to return open questions as a structured Conductor agent
`output:` field failed schema validation and was reverted (commit `a3caff4`).
This design deliberately avoids that: questions live in a **file artifact**,
never in an agent output field.

## Goals

- Present open questions one at a time, each with suggested answers + Other.
- Extra per-question escape hatches: **You decide** and **Skip / defer**.
- Refine the HLD from the answers, then **loop until resolved** (re-ask any new
  questions refinement surfaces).
- Work on **both** surfaces: interactive `/plan` (native `AskUserQuestion`) and
  the Conductor `design.yaml` workflow (script-driven gate loop).
- One shared, machine-readable source of truth for the questions.

## Non-goals

- No change to the LLD / contract phases beyond consuming a refined HLD.
- No dynamic per-question option *buttons* in Conductor (`human_gate` only
  supports a single choice from static options — accepted constraint).
- Do **not** return open questions as a Conductor agent structured-output field
  (caused the prior schema-validation error).

## Design

### 1. Shared source of truth — structured open-questions artifact

Both surfaces read/write one machine-readable file, mirroring the existing
`tasks.json` pattern:

- **Path:** `.sdlc/<slug>/open-questions.json` (add `artifacts.open_questions`
  to `skills.config.yaml`).
- **Schema:** new `workflows/open-questions.schema.json` (JSON Schema draft-07,
  same style as `tasks.schema.json`).
- **Validator:** new `workflows/validate_open_questions.py` (same style as
  `validate_tasks.py`; exit 0 = OK, exit 1 = FAIL with reason on stderr).

```jsonc
{
  "schema_version": 1,
  "feature_slug": "saved-search",
  "questions": [
    {
      "id": "q1",
      "question": "Should saved searches be per-user or shareable across a team?",
      "why": "Drives the data model and authz — blocks the LLD.",
      "options": ["Per-user only", "Team-shareable", "Both, with a visibility flag"],
      "status": "open",
      "resolution": null
    }
  ]
}
```

Field rules:

- `options`: 2–4 suggested answers authored by the plan skill.
- `status`: one of `open | resolved | deferred | folded`.
- `resolution`: `null` while `open`/`deferred`; otherwise
  `{ "kind": "picked" | "other" | "you-decide" | "skip", "answer": "<text>" }`.

**Status lifecycle:**

- `open` — awaiting an answer.
- `resolved` — answered, not yet folded into the HLD.
- `folded` — answer incorporated into the HLD prose.
- `deferred` — user chose Skip; stays in the HLD "Open questions" section and
  does **not** block approval.

The HLD keeps its human-readable "Open questions" prose section; the JSON is the
machine mirror. Scripts read the JSON — no agent ever returns it as `output:`.

### 2. `plan` skill (`skills/plan/SKILL.md`) — interactive loop

- Add `AskUserQuestion` to `allowed-tools`.
- Output step also **emits `open-questions.json`** (each question with `why` +
  2–4 suggested `options`), alongside the existing HLD prose section.
- New interactive behavior — when `AskUserQuestion` is available **and** open
  questions exist, **loop until resolved**:
  1. For each `open` question, call `AskUserQuestion` with its `options` (the
     tool auto-adds **Other**), plus explicit **"You decide"** and
     **"Skip / defer"** choices.
  2. Record each answer into `open-questions.json`
     (`resolved` with the chosen `kind`, or `deferred` for Skip) and update the
     HLD prose.
  3. Fold `resolved` answers into the HLD; for `you-decide`, pick a sensible
     default and record it as a **stated assumption** in the HLD.
  4. **Re-derive** open questions — refinement may surface new ones (append as
     new `open` entries).
  5. Repeat until no `open` questions remain (deferred ones may remain).
- Return value stays `hld_path`, `hld_summary` only — **no** structured
  questions field.

### 3. Conductor `design.yaml` — script-driven loop

The single `hld_approval` "Request HLD revisions → free-text feedback" path is
**removed**. New state machine inserted after `assert_hld`:

```
assert_hld → serve ──(open Q exists)──────────→ ask_question (gate) → record_answer → serve
                │
                ├──(resolved-unfolded exist)───→ refine_hld → serve
                │
                └──(none open, none unfolded)──→ hld_approval → (Approve | Reject)
```

Steps:

- **`serve`** (`type: script`, routes on parsed JSON stdout): reads
  `open-questions.json`; if any `open`, emits the next one as JSON
  (`{ "state": "ask", "qid", "question", "why", "options_md": "1. ...\n2. ..." }`);
  else if any `resolved` (unfolded), emits `{ "state": "refine" }`;
  else emits `{ "state": "approve" }`. Routes branch on `state`.
- **`ask_question`** (`type: human_gate`): prompt renders
  `{{ serve.output.question }}`, `{{ serve.output.why }}`, and
  `{{ serve.output.options_md }}`. Static options:
  - **Answer** (`prompt_for: answer`) — user types a suggestion number or custom
    text (covers "picked" and "other").
  - **You decide**.
  - **Skip / defer**.
  All routes → `record_answer`.
- **`record_answer`** (`type: script`): given the qid (from `serve.output.qid`)
  and the gate choice/answer, updates `open-questions.json` — sets `status` and
  `resolution.kind`/`resolution.answer` (`resolved`, or `deferred` for Skip,
  `you-decide` kind for You decide). Routes → `serve`.
- **`refine_hld`** (`type: agent`, `model: claude-opus-4-8`): folds all
  `resolved` answers into `hld.md`, marks them `folded`, and re-derives &
  appends any **new** `open` questions to `open-questions.json`. For
  `you-decide` answers, picks a default and records it as a stated assumption in
  the HLD. Routes → `serve`.
- **`hld_approval`** keeps only **Approve** (→ `author_llds`) and **Reject**
  (→ `abort`). The "revise" option and its `feedback` prompt are removed.

**Termination:** the loop ends when `refine_hld` surfaces no new `open`
questions, so `serve` reaches the `approve` state. Deferred questions remain in
the HLD Open-questions section but never block. The workflow's existing
`limits.max_iterations` is the backstop against pathological cycles (bump if the
loop needs more headroom than the current cap).

### 4. Decisions confirmed during brainstorming

- **Surface:** both interactive `/plan` and Conductor `design.yaml`.
- **Loop shape:** loop until resolved (not one-pass, not capped — rely on natural
  convergence + `max_iterations` backstop).
- **Per-question hatches:** suggestions + Other (always) + **You decide** +
  **Skip / defer**.
- **Free-form revise path:** **replaced** (removed the single prose-blob feedback
  option).
- **You decide in Conductor:** `refine_hld` picks the default and records it as a
  stated assumption; the user sees it at the final `hld_approval` gate.
- **Skip/defer:** deferred questions stay in the HLD Open questions section and do
  not block approval.

## Files touched

- **New:** `workflows/open-questions.schema.json`
- **New:** `workflows/validate_open_questions.py`
- **Edit:** `skills/plan/SKILL.md` — add `AskUserQuestion` to allowed-tools; emit
  `open-questions.json`; document the interactive loop and status lifecycle.
- **Edit:** `skills.config.yaml` — add `artifacts.open_questions:
  .sdlc/<slug>/open-questions.json`.
- **Edit:** `workflows/design.yaml` — add `serve` / `ask_question` /
  `record_answer` / `refine_hld` steps; trim `hld_approval` to Approve/Reject;
  wire routes; bump `limits.max_iterations` if needed.
- **Edit:** `README.md` — document the open-question loop in the design phase.

## Testing

- **Validator:** `validate_open_questions.py` accepts a well-formed file and
  rejects: missing required fields, bad `status`/`kind` enums, `options` outside
  2–4, and a `resolution` that is non-null while `status: open`.
- **Fixtures:** add `testdata` open-questions.json examples (valid; and invalid
  cases the validator must reject).
- **Interactive `/plan`:** manual run — confirm each question is asked with
  suggestions + Other + You decide + Skip; confirm the HLD is refined and new
  questions re-asked until resolved.
- **Conductor `design.yaml`:** manual `conductor run design.yaml --web` — confirm
  the `serve → ask_question → record_answer → serve` loop, the `refine_hld`
  re-derivation, deferred questions not blocking, and termination into
  `hld_approval` with only Approve/Reject.

## Risks & mitigations

- **Non-terminating loop** (refinement keeps inventing questions) — mitigated by
  `limits.max_iterations` backstop; `refine_hld` prompt instructs it to only add
  questions that are genuinely new and blocking.
- **Schema-validation regression** (the reason the prior attempt was reverted) —
  mitigated by keeping questions in a file, never in an agent `output:` field.
- **Gate free-text ambiguity** (user types a number vs. prose) — `record_answer`
  accepts either: a bare integer maps to `options[n-1]` (kind `picked`); anything
  else is stored verbatim (kind `other`).
