# tasks.json — Parallel Task DAG with Batched Context — Design

**Date:** 2026-07-06
**Status:** Approved (design) — pending implementation plan

## Problem

The impl pipelines (`workflows/backend_impl.yaml`, `workflows/frontend_impl.yaml`,
`workflows/qa.yaml`) each run implementation as a **single sequential `implementer`
step**. Two costs follow:

1. **No parallelism.** Independent slices of a feature (e.g. two unrelated endpoints,
   or two independent E2E scenarios) are built one after another even though nothing
   forces the order.
2. **SDK-call pressure.** The implementer re-reads the codebase with many individual
   `read_file` calls. Combined with test/fix loops this pushes a run toward the ~50
   SDK-call ceiling. The design skills already read the same code moments earlier —
   that context is thrown away and re-fetched.

The task plans that exist today (`.sdlc/<slug>/<stack>/tasks.md`, authored by
`backend-tasks` / `frontend-impl` plan mode / `qa-automation`) are **prose**: they carry
order and file hints for a human/agent to interpret, but nothing a skill can execute
deterministically as a dependency graph, and no explicit batched-read manifest.

## Goal

Author a **machine-readable `tasks.json`** — a dependency **DAG** plus a **batched-context
manifest** — during the design phase, and have the impl skills consume it to (a) execute
independent tasks **in parallel** (dependents wait for prerequisites) and (b) load context
in **as few tool calls as possible**, keeping each impl run under the ~50 SDK-call budget.

## Key constraint (shapes the whole design)

**Conductor `for_each` fans out over a runtime array, but is a flat concurrent map — not a
DAG executor.** `main.yaml`'s `implement` step already `for_each`-es over stacks in parallel
(`max_concurrent: 2`, `failure_mode: all_or_nothing`), and its `source` can be a prior step's
output (the repo comment reads *"Later, derive from `design.output.affected_repos`"*). So an
impl workflow **can** fan out over tasks emitted from `tasks.json` at runtime.

What `for_each` does **not** do is honor `depends_on` — it starts every item at once, so a
naive fan-out over all tasks would begin a dependent task before its prerequisite. The design
bridges this by fanning out over **independent slices**: `tasks.json` groups tasks so that
(a) no `depends_on` edge crosses a group and (b) groups have disjoint `writes`. `for_each`
runs the slices concurrently; each item runs its slice's tasks **in dependency order
internally**. Ordering that matters stays inside an item; only genuinely-independent work
runs in parallel. `tasks.json` is thus both a **DAG** (intra-slice order) and a
**fan-out source** (the slice list).

## Decisions

- **Parallel engine = Conductor `for_each` over independent slices.** Each impl workflow
  gains a `for_each` step whose `source` is the slice array emitted from `tasks.json`; each
  item invokes the implementer skill for **one slice** and runs that slice's tasks in
  dependency order. (Rejected: `for_each` **per wave** — hardcodes a max DAG depth and
  duplicates YAML across wave slots; and **DAG execution inside the skill** — flexible but
  parallelism is invisible in the Conductor run graph.)
- **Per-slice isolation + post-barrier merge.** Concurrent items edit in isolated git
  worktrees (via `using-git-worktrees`, already wired as `shared.external.worktrees`); after
  the `all_or_nothing` barrier a merge step recombines them — conflict-free because groups
  have disjoint `writes`.
- **Authoring folded into the design skills.** `backend-design` and `frontend-design` emit
  `tasks.json` alongside their LLD, reusing the code they already read (near-zero extra SDK
  cost). Authored pre-contract; acceptable because the backend **owns** its API surface and
  the frontend reconciles the published contract at impl time. (A separate post-contract step
  and a JSON-emitting impl-phase step were rejected — both re-read the code in a fresh
  session, spending the calls we set out to save.)
- **QA authors its own.** QA has no design-phase code-reading skill and its acceptance
  criteria come later from `/api-contract`, so `qa-automation` emits `tasks.json` in
  `qa.yaml`'s `author_tests` step — a flat scenario list (shallow DAG) with a shared
  fixture/page-object manifest.
- **Context = shared manifest + per-task deltas.** A top-level `context_manifest.read_once`
  is loaded **once** in a single batched call; each task lists only its extra `reads` and its
  `writes`. Fewest total calls. (Per-task full file lists and "implementer decides" were
  rejected as call-wasteful / non-guaranteeing.)
- **File naming.** `.sdlc/<slug>/<stack>/tasks.json` — disambiguated by the existing
  per-stack folder (matches `tasks.md`); the `stack` is also a field inside the JSON. No
  filename renaming.

## `tasks.json` schema

Defined once in a shared reference file: `workflows/tasks.schema.json`.

```jsonc
{
  "schema_version": 1,
  "stack": "backend",                     // backend | frontend | qa
  "feature_slug": "saved-search",
  "context_manifest": {
    "read_once": ["src/searches/router.py", "src/searches/service.py", "src/db/models.py"],
    "reference": ["docs/technical/saved-search/lld/backend.md",
                  "contracts/saved-search/openapi.yaml", "CLAUDE.md"]
  },
  "slices": [                             // the for_each fan-out source (mutually independent)
    { "group_id": "g1", "task_ids": ["t1", "t2"] },   // task_ids in dependency order
    { "group_id": "g2", "task_ids": ["t3"] }
  ],
  "tasks": [
    {
      "id": "t1",
      "group_id": "g1",
      "title": "SavedSearch schema + migration",
      "depends_on": [],                    // DAG edges — must stay WITHIN the same group
      "reads": [],                         // delta files beyond context_manifest.read_once
      "writes": ["src/db/models.py", "migrations/0007_saved_search.py"],
      "test": "tests/db/test_saved_search_model.py",  // failing test written first
      "standards": ["migrations", "backward-compat"],
      "needs_human_gate": true
    },
    {
      "id": "t2",
      "group_id": "g1",
      "title": "Service create/list",
      "depends_on": ["t1"],                // same group as t1 — runs after t1 in-item
      "reads": ["src/searches/repository.py"],
      "writes": ["src/searches/service.py"],
      "test": "tests/searches/test_service.py",
      "standards": ["validation", "idempotency"],
      "needs_human_gate": false
    },
    {
      "id": "t3",
      "group_id": "g2",
      "title": "Audit-log endpoint (independent slice)",
      "depends_on": [],
      "reads": ["src/audit/router.py"],
      "writes": ["src/audit/handlers.py"],
      "test": "tests/audit/test_handlers.py",
      "standards": ["security", "observability"],
      "needs_human_gate": false
    }
  ]
}
```

Every task retains the fields `backend-tasks` already mandates — `id`, `title`, `test`,
`standards` (subset of {security, backward-compat, rate-limiting, idempotency, validation,
observability, migrations, performance}), `needs_human_gate` — plus:

- `group_id` — which independent slice the task belongs to. **Invariant:** every
  `depends_on` edge stays within one group; groups never share a `writes` path.
- `depends_on: [id]` — DAG edges (intra-group only). Empty = runs first within its slice.
- `reads: [path]` — files this task needs **beyond** the shared manifest.
- `writes: [path]` — files this task creates/edits. Basis of the parallel-safety invariant.

`slices` is the precomputed fan-out source: one entry per group, `task_ids` in dependency
order. The authoring skill derives it from the DAG (weakly-connected components), so the impl
`for_each` iterates it directly.

QA tasks use the same shape; each scenario is typically its own single-task group (scenarios
are independent), `writes` are the spec files, `reads` are fixtures/page objects, `test` is
the scenario id.

## Authoring changes (design phase)

- **`skills/backend-design/SKILL.md`, `skills/frontend-design/SKILL.md`:** add a final step —
  emit `tasks.json` next to the LLD, reusing already-read code. `writes`/`reads` come from the
  component/sequence design; `depends_on` from the natural build order (types → domain →
  persistence → API expressed as a chain within a slice; independent slices left unlinked so
  they parallelize). Return `tasks_path` in addition to `lld_path`.
- **`skills/qa-automation/SKILL.md`:** emit `tasks.json` (flat scenarios + shared fixture/
  page-object manifest) in `author_tests`.
- **`skills/backend-tasks/SKILL.md`:** retargeted to emit `tasks.json` (same schema) instead
  of `tasks.md`. It now serves only as the **fallback** authoring path for standalone impl
  runs where no design phase produced the file.

## Consumption & execution (impl phase)

Execution splits across the workflow (fan-out) and the skill (one slice per item).

**Workflow (`backend_impl.yaml` / `frontend_impl.yaml`):**

1. **`tasks` step — locate or author.** If `.sdlc/<slug>/<stack>/tasks.json` exists (from the
   design phase), load it; otherwise author it via the fallback (`backend-tasks`, JSON). The
   step returns `slices` (the fan-out array) and `tasks_path`.
2. **`implement` `for_each` step.** `source: {{ tasks.output.slices }}`, `as: slice`,
   `max_concurrent: N`, `failure_mode: all_or_nothing`. Each item runs in its own git worktree
   and invokes the implementer skill with `group_id = slice.group_id` and `tasks_path`.
3. **`merge_slices` step (post-barrier).** After all items succeed, merge the per-slice
   worktrees back onto the stack branch — conflict-free by the disjoint-`writes` invariant.
4. Downstream `unit_tests` → `contract_check` → `reviewers` → `fix` steps are **unchanged**;
   they run once, after the merge, over the whole branch.

**Skill (per `for_each` item — implements ONE slice):**

1. **Load once.** Read `context_manifest.read_once` **and** `context_manifest.reference` in a
   **single batched call** — one `Bash` `cat` over all paths (both lists concatenated) with
   `=== <path> ===` delimiters — instead of N `Read` calls. (`read_once` = code the tasks edit
   against; `reference` = the LLD, contract, and repo conventions the tasks must honor.)
2. **Run the slice in order.** For each `task_id` in the slice's `task_ids` (already dependency
   -ordered), batch-read the task's `reads` delta, then do test-first TDD (write failing
   `test` → implement → refactor) before the next task.
3. **Stop at gates.** A task with `needs_human_gate: true` surfaces for approval before it runs
   (migrations, auth, payments, prod config, deps) — same gate rule as today, keyed off the flag.

**QA (`qa.yaml`):** `author_tests` emits `tasks.json` (scenario groups) and returns `slices`;
an `authoring` `for_each` writes the scenario specs in parallel; the existing `run_e2e` script
then runs the whole suite once (unchanged).

## Parallel-safety & SDK-call budget rules

- **Disjoint writes across groups (correctness invariant).** Two different groups MUST have
  **non-overlapping `writes`**, and no `depends_on` edge may cross a group. The authoring skill
  enforces this: if two tasks share a `writes` path or have a dependency between them, they are
  placed in the **same** group (serialized in-item). This is what makes concurrent slices safe.
- **Parallelism is across slices, not within one.** Intra-slice TDD/dependency order is
  sequential inside the `for_each` item; only independent slices run concurrently.
- **Worktree isolation + merge.** Each `for_each` item edits an isolated worktree; the
  post-barrier `merge_slices` step recombines them (conflict-free by the invariant above).
- **`needs_human_gate` tasks** surface before they run (migrations, auth, payments, prod
  config, deps) — same gate rule as today, keyed off the flag in the JSON.
- **Budget.** Each `for_each` item is its own agent session with its own budget: it batch-reads
  its context once and implements only its slice, so per-session calls stay well under the
  target of **≤ 50 SDK calls per session**. Trade-off vs a single shared session: the manifest
  is re-read once per slice rather than once total, but each read is small and bounded.

## Files touched

**New**
- `workflows/tasks.schema.json` — the `tasks.json` JSON Schema (source of truth for the shape).
- `docs/superpowers/specs/2026-07-06-tasks-json-dag-design.md` — this spec.

**Edited — skills**
- `skills/backend-design/SKILL.md` — emit `tasks.json` (incl. `slices`); return `tasks_path`.
- `skills/frontend-design/SKILL.md` — emit `tasks.json` (incl. `slices`); return `tasks_path`.
- `skills/qa-automation/SKILL.md` — emit `tasks.json` (scenario groups + fixture manifest);
  return `slices`.
- `skills/backend-implement/SKILL.md` — consume `tasks.json` **for one slice** (`group_id`
  input): batched manifest read + in-order TDD; fallback-author if absent.
- `skills/frontend-implement/SKILL.md` — same per-slice consumption protocol.
- `skills/backend-tasks/SKILL.md` — emit JSON (schema above, incl. `slices`); role narrowed to
  fallback authoring.

**Edited — workflows**
- `workflows/backend_impl.yaml` — `tasks` step returns `slices`; replace the single
  `implementer` step with an `implement` **`for_each`** over `slices` (worktree-isolated,
  `all_or_nothing`) + a `merge_slices` step before `unit_tests`.
- `workflows/frontend_impl.yaml` — same `for_each` + merge structure.
- `workflows/qa.yaml` — `author_tests` emits `tasks.json`/`slices`; add an `authoring`
  `for_each` over scenario groups before `run_e2e`.

**Edited — config**
- `skills.config.yaml` — add `tasks` artifact paths (`.sdlc/<slug>/<stack>/tasks.json`).
  (`using-git-worktrees` is already registered as `shared.external.worktrees` for per-slice
  isolation.)

## Out of scope

- `for_each` **per-wave** execution (finer parallelism but hardcodes max DAG depth).
- Cross-stack parallelism beyond what `main.yaml`/`dispatch.yaml` already provide.
- Changing the test/verify/review/fix steps of the impl pipelines (they run once, post-merge).
