# tasks.json Parallel DAG — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author a machine-readable `tasks.json` (a dependency DAG grouped into independent slices, plus a batched-context manifest) in the design phase, and have the impl/QA workflows fan out over its slices with Conductor `for_each` — enabling parallel builds while keeping each session under ~50 SDK calls.

**Architecture:** The design skills (`backend-design`, `frontend-design`) and `qa-automation` emit `tasks.json` reusing code they already read. A JSON Schema + a deterministic validator enforce the correctness invariants (intra-group `depends_on` only; disjoint `writes` across groups). Each impl workflow's `tasks` step loads-or-authors + validates the file and returns its `slices`; a `for_each` step runs each slice as an isolated worktree build (tasks in dependency order, test-first); a post-barrier `merge_slices` step recombines them. Existing test/verify/review/fix steps are unchanged.

**Tech Stack:** This is a **skills + workflow-definition repo** — the artifacts are Markdown (`SKILL.md`), Conductor workflow YAML, one JSON Schema, and one Python validator. There is no application code or unit-test framework. "Tests" therefore mean: JSON-Schema validation (`jsonschema`), YAML/JSON parse checks (`pyyaml`/`json`), and structural `grep`/`jq` presence checks — each run with `python3` (3.10), `jq` (1.7), all confirmed available. End-to-end Conductor execution is a manual follow-up (noted at the end), not part of these tasks.

## Global Constraints

- **JSON Schema is the source of truth** for `tasks.json`: `workflows/tasks.schema.json` (draft-07).
- **Correctness invariants** (validator-enforced): every `depends_on` edge stays within one `group_id`; no `writes` path is shared by two different groups; slice `task_ids` are in dependency order; no dependency cycles.
- **File locations:** `tasks.json` → `.sdlc/<slug>/<stack>/tasks.json` (`<stack>` ∈ {backend, frontend, qa}); disambiguated by folder, matching the existing `tasks.md` convention.
- **Batched reads:** consumers load `context_manifest.read_once` + `reference` in ONE `cat` call with `=== <path> ===` delimiters — never one `Read` per file.
- **Commit trailer:** end every commit message with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Branch:** work on `feature/tasks-json-parallel-dag` (already checked out).
- **Do not** change the test/verify/review/fix steps of any impl pipeline.

---

### Task 1: `tasks.json` schema + validator (source of truth)

**Files:**
- Create: `workflows/tasks.schema.json`
- Create: `workflows/validate_tasks.py`
- Create: `workflows/testdata/tasks.valid.json`
- Create: `workflows/testdata/tasks.invalid-crossgroup.json`

**Interfaces:**
- Produces: `workflows/validate_tasks.py <path>` — exits `0` and prints `OK: <path> (<n> tasks, <m> slices)` on success; exits `1` and prints `FAIL: <reason>` on any schema or invariant violation. Every later task's authoring step calls this.
- Produces: the schema shape (`schema_version`, `stack`, `feature_slug`, `context_manifest.{read_once,reference}`, `slices[].{group_id,task_ids}`, `tasks[].{id,group_id,title,depends_on,reads,writes,test,standards,needs_human_gate}`) that all authoring skills must emit.

- [ ] **Step 1: Write the valid fixture**

Create `workflows/testdata/tasks.valid.json`:

```json
{
  "schema_version": 1,
  "stack": "backend",
  "feature_slug": "saved-search",
  "context_manifest": {
    "read_once": ["src/searches/router.py", "src/searches/service.py", "src/db/models.py"],
    "reference": ["docs/technical/saved-search/lld/backend.md", "contracts/saved-search/openapi.yaml", "CLAUDE.md"]
  },
  "slices": [
    { "group_id": "g1", "task_ids": ["t1", "t2"] },
    { "group_id": "g2", "task_ids": ["t3"] }
  ],
  "tasks": [
    { "id": "t1", "group_id": "g1", "title": "SavedSearch schema + migration", "depends_on": [], "reads": [], "writes": ["src/db/models.py", "migrations/0007_saved_search.py"], "test": "tests/db/test_saved_search_model.py", "standards": ["migrations", "backward-compat"], "needs_human_gate": true },
    { "id": "t2", "group_id": "g1", "title": "Service create/list", "depends_on": ["t1"], "reads": ["src/searches/repository.py"], "writes": ["src/searches/service.py"], "test": "tests/searches/test_service.py", "standards": ["validation", "idempotency"], "needs_human_gate": false },
    { "id": "t3", "group_id": "g2", "title": "Audit-log endpoint", "depends_on": [], "reads": ["src/audit/router.py"], "writes": ["src/audit/handlers.py"], "test": "tests/audit/test_handlers.py", "standards": ["security", "observability"], "needs_human_gate": false }
  ]
}
```

- [ ] **Step 2: Write the invalid fixture (cross-group dependency + shared write)**

Create `workflows/testdata/tasks.invalid-crossgroup.json` — `t3` in `g2` depends on `t1` in `g1` (cross-group edge) AND writes a file `g1` also writes:

```json
{
  "schema_version": 1,
  "stack": "backend",
  "feature_slug": "saved-search",
  "context_manifest": { "read_once": ["src/db/models.py"], "reference": ["CLAUDE.md"] },
  "slices": [
    { "group_id": "g1", "task_ids": ["t1"] },
    { "group_id": "g2", "task_ids": ["t3"] }
  ],
  "tasks": [
    { "id": "t1", "group_id": "g1", "title": "Model", "depends_on": [], "reads": [], "writes": ["src/db/models.py"], "test": "tests/db/test_model.py", "standards": ["migrations"], "needs_human_gate": false },
    { "id": "t3", "group_id": "g2", "title": "Bad", "depends_on": ["t1"], "reads": [], "writes": ["src/db/models.py"], "test": "tests/x.py", "standards": [], "needs_human_gate": false }
  ]
}
```

- [ ] **Step 3: Run the validator to verify it does not yet exist (RED)**

Run: `python3 workflows/validate_tasks.py workflows/testdata/tasks.valid.json`
Expected: FAIL — `python3: can't open file '.../workflows/validate_tasks.py': [Errno 2] No such file or directory`

- [ ] **Step 4: Write the schema**

Create `workflows/tasks.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://keyvalue.systems/sdlc/tasks.schema.json",
  "title": "SDLC tasks.json — parallel task DAG",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "stack", "feature_slug", "context_manifest", "slices", "tasks"],
  "properties": {
    "schema_version": { "const": 1 },
    "stack": { "enum": ["backend", "frontend", "qa"] },
    "feature_slug": { "type": "string", "minLength": 1 },
    "context_manifest": {
      "type": "object",
      "additionalProperties": false,
      "required": ["read_once", "reference"],
      "properties": {
        "read_once": { "type": "array", "items": { "type": "string", "minLength": 1 } },
        "reference": { "type": "array", "items": { "type": "string", "minLength": 1 } }
      }
    },
    "slices": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["group_id", "task_ids"],
        "properties": {
          "group_id": { "type": "string", "minLength": 1 },
          "task_ids": { "type": "array", "minItems": 1, "items": { "type": "string", "minLength": 1 } }
        }
      }
    },
    "tasks": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "group_id", "title", "depends_on", "reads", "writes", "test", "standards", "needs_human_gate"],
        "properties": {
          "id": { "type": "string", "minLength": 1 },
          "group_id": { "type": "string", "minLength": 1 },
          "title": { "type": "string", "minLength": 1 },
          "depends_on": { "type": "array", "items": { "type": "string", "minLength": 1 } },
          "reads": { "type": "array", "items": { "type": "string", "minLength": 1 } },
          "writes": { "type": "array", "minItems": 1, "items": { "type": "string", "minLength": 1 } },
          "test": { "type": "string", "minLength": 1 },
          "standards": { "type": "array", "items": { "type": "string" } },
          "needs_human_gate": { "type": "boolean" }
        }
      }
    }
  }
}
```

- [ ] **Step 5: Write the validator**

Create `workflows/validate_tasks.py`:

```python
#!/usr/bin/env python3
"""Validate a tasks.json against the schema + the parallel-safety invariants.

Usage: python3 workflows/validate_tasks.py <path-to-tasks.json>
Exit 0 = OK; exit 1 = FAIL (reason on stderr).
"""
import json
import sys
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).with_name("tasks.schema.json")


def fail(msg: str) -> "NoReturn":
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: validate_tasks.py <path-to-tasks.json>")
    path = Path(sys.argv[1])
    if not path.is_file():
        fail(f"not found: {path}")

    doc = json.loads(path.read_text())
    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as e:
        fail(f"schema: {e.message} (at {'/'.join(str(p) for p in e.absolute_path)})")

    tasks = {t["id"]: t for t in doc["tasks"]}
    if len(tasks) != len(doc["tasks"]):
        fail("duplicate task id")

    # slice <-> task consistency
    slice_ids = set()
    for sl in doc["slices"]:
        for tid in sl["task_ids"]:
            if tid not in tasks:
                fail(f"slice {sl['group_id']} references unknown task {tid}")
            if tasks[tid]["group_id"] != sl["group_id"]:
                fail(f"task {tid} group_id != slice {sl['group_id']}")
            slice_ids.add(tid)
    if slice_ids != set(tasks):
        fail(f"tasks not covered by exactly one slice: {set(tasks) ^ slice_ids}")

    # depends_on: exists + intra-group only
    for t in doc["tasks"]:
        for dep in t["depends_on"]:
            if dep not in tasks:
                fail(f"task {t['id']} depends on unknown {dep}")
            if tasks[dep]["group_id"] != t["group_id"]:
                fail(f"cross-group dependency: {t['id']} ({t['group_id']}) -> {dep} ({tasks[dep]['group_id']})")

    # disjoint writes across groups
    owner: dict[str, str] = {}
    for t in doc["tasks"]:
        for w in t["writes"]:
            if w in owner and owner[w] != t["group_id"]:
                fail(f"write '{w}' shared by groups {owner[w]} and {t['group_id']}")
            owner[w] = t["group_id"]

    # per-slice: dependency order + acyclic
    for sl in doc["slices"]:
        seen: set[str] = set()
        for tid in sl["task_ids"]:
            for dep in tasks[tid]["depends_on"]:
                if dep not in seen:
                    fail(f"slice {sl['group_id']}: {tid} listed before its dependency {dep}")
            seen.add(tid)

    print(f"OK: {path} ({len(tasks)} tasks, {len(doc['slices'])} slices)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the validator on the valid fixture (GREEN)**

Run: `python3 workflows/validate_tasks.py workflows/testdata/tasks.valid.json`
Expected: `OK: workflows/testdata/tasks.valid.json (3 tasks, 2 slices)`

- [ ] **Step 7: Run the validator on the invalid fixture (GREEN — rejects)**

Run: `python3 workflows/validate_tasks.py workflows/testdata/tasks.invalid-crossgroup.json`
Expected: exit 1, stderr starts with `FAIL: cross-group dependency: t3 (g2) -> t1 (g1)`
(Verify exit code: `echo $?` → `1`.)

- [ ] **Step 8: Commit**

```bash
git add workflows/tasks.schema.json workflows/validate_tasks.py workflows/testdata/
git commit -m "feat: add tasks.json schema + invariant validator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Register the `tasks.json` artifact paths in `skills.config.yaml`

**Files:**
- Modify: `skills.config.yaml` (the `artifacts:` block, ~end of file)

- [ ] **Step 1: Add the tasks paths under `artifacts:`**

In `skills.config.yaml`, in the `artifacts:` map, add a `tasks:` entry after the `work_dir:` line:

```yaml
  work_dir:    .sdlc/<slug>/                          # tasks, verify, reviews, review-pack
  tasks:       .sdlc/<slug>/<stack>/tasks.json        # machine-readable task DAG (<stack> = backend|frontend|qa)
```

- [ ] **Step 2: Verify the YAML still parses and the key exists**

Run:
```bash
python3 -c "import yaml; d=yaml.safe_load(open('skills.config.yaml')); print(d['artifacts']['tasks'])"
```
Expected: `.sdlc/<slug>/<stack>/tasks.json`

- [ ] **Step 3: Commit**

```bash
git add skills.config.yaml
git commit -m "feat: register tasks.json artifact path

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `backend-design` emits `tasks.json`

**Files:**
- Modify: `skills/backend-design/SKILL.md`

**Interfaces:**
- Consumes: `workflows/tasks.schema.json`, `workflows/validate_tasks.py` (Task 1).
- Produces: `.sdlc/<slug>/backend/tasks.json`; the skill now also returns `tasks_path`.

- [ ] **Step 1: Add step 8 to the `## Steps` list**

In `skills/backend-design/SKILL.md`, after the line `7. **Write** the backend LLD; flag every breaking change in plain language.`, add:

```markdown
8. **Emit the task DAG** — write `.sdlc/<slug>/backend/tasks.json` (see section below),
   reusing the code you already read. No re-reading.
```

- [ ] **Step 2: Add the emission section**

Immediately before the `## Output` section, insert:

```markdown
## Emit tasks.json (the parallel task DAG)
Write `.sdlc/<slug>/backend/tasks.json` conforming to `workflows/tasks.schema.json`. It is
the plan the backend impl phase fans out over — build it from the LLD you just wrote, reusing
the files you already read (do not re-read the codebase):
- `context_manifest.read_once` = the code files the tasks edit against; `reference` = this LLD
  path, the (pending) contract path, and `CLAUDE.md`/`AGENTS.md`.
- One `tasks[]` entry per ≤1-commit slice, each with `id`, `group_id`, `title`, `depends_on`
  (**intra-group only**), `reads` (files needed beyond the manifest), `writes` (exact files),
  `test` (the failing test to write first), `standards`, `needs_human_gate` (true for DB
  migration, auth/permission, payment, prod config, or dependency changes).
- **Grouping into independent slices:** two tasks share a `group_id` **iff** one depends on
  the other OR they write a common file; otherwise put them in different groups. Then fill
  `slices[]` — one entry per group, `task_ids` in dependency order.
- **Validate before returning:** run
  `python3 workflows/validate_tasks.py .sdlc/<slug>/backend/tasks.json` — it must print `OK`.
  Fix any `FAIL` (cross-group edge, shared write, mis-ordered slice) before finishing.
```

- [ ] **Step 3: Update the `## Output` section to return `tasks_path`**

In the `## Output` section, change `Return \`lld_path\` and a short list...` to:

```markdown
`file:line`. Return `lld_path`, `tasks_path` (`.sdlc/<slug>/backend/tasks.json`), and a short
list of the **decisions/constraints that shape the contract** (e.g. "auth is centralized in X
```
(Leave the rest of that sentence unchanged.)

- [ ] **Step 4: Verify the file mentions the schema, validator, and tasks_path**

Run:
```bash
grep -c "tasks.schema.json\|validate_tasks.py\|tasks_path" skills/backend-design/SKILL.md
```
Expected: `3` or more.

- [ ] **Step 5: Commit**

```bash
git add skills/backend-design/SKILL.md
git commit -m "feat(backend-design): emit tasks.json task DAG

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `frontend-design` emits `tasks.json`

**Files:**
- Modify: `skills/frontend-design/SKILL.md`

**Interfaces:**
- Produces: `.sdlc/<slug>/frontend/tasks.json`; returns `tasks_path`.

- [ ] **Step 1: Add step 8 to the `## Steps` list**

After the line `7. **Write** the frontend LLD; flag anything that forces a backend/contract change.`, add:

```markdown
8. **Emit the task DAG** — write `.sdlc/<slug>/frontend/tasks.json` (see section below),
   reusing the code you already read. No re-reading.
```

- [ ] **Step 2: Add the emission section**

Immediately before the `## Output` section, insert:

```markdown
## Emit tasks.json (the parallel task DAG)
Write `.sdlc/<slug>/frontend/tasks.json` conforming to `workflows/tasks.schema.json`. Build it
from the LLD you just wrote, reusing files you already read (do not re-read the codebase):
- `context_manifest.read_once` = the component/state/hook files the tasks edit against;
  `reference` = this LLD path, the (pending) contract path, and `CLAUDE.md`.
- One `tasks[]` entry per ≤1-commit slice (e.g. types/API-client, a component + its UI states,
  form+validation, a route), each with `id`, `group_id`, `title`, `depends_on`
  (**intra-group only**), `reads`, `writes` (exact files), `test`, `standards`,
  `needs_human_gate` (true for auth/permission, prod config, or dependency changes).
- **Grouping:** two tasks share a `group_id` **iff** one depends on the other OR they write a
  common file; otherwise different groups. Fill `slices[]`, `task_ids` in dependency order.
- **Validate before returning:** `python3 workflows/validate_tasks.py .sdlc/<slug>/frontend/tasks.json`
  must print `OK`.
```

- [ ] **Step 3: Update `## Output` to return `tasks_path`**

In `## Output`, change `Return \`lld_path\` and a short list...` to:

```markdown
`file:line`. Return `lld_path`, `tasks_path` (`.sdlc/<slug>/frontend/tasks.json`), and a short
list of the **decisions/constraints that shape the contract** (e.g. "data-fetching goes through
```
(Leave the rest of that sentence unchanged.)

- [ ] **Step 4: Verify**

Run: `grep -c "tasks.schema.json\|validate_tasks.py\|tasks_path" skills/frontend-design/SKILL.md`
Expected: `3` or more.

- [ ] **Step 5: Commit**

```bash
git add skills/frontend-design/SKILL.md
git commit -m "feat(frontend-design): emit tasks.json task DAG

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `qa-automation` emits `tasks.json` (scenario groups)

**Files:**
- Modify: `skills/qa-automation/SKILL.md`

**Interfaces:**
- Produces: `.sdlc/<slug>/qa/tasks.json` (one single-task group per scenario) + returns `slices`.

- [ ] **Step 1: Add a step to `## Steps`**

In `skills/qa-automation/SKILL.md`, after step `4. **Author tests**...`, insert a new step (renumber the following steps 6/7):

```markdown
5. **Emit the scenario DAG** — write `.sdlc/<slug>/qa/tasks.json` (see section below) so the
   suite can be authored in parallel.
```

- [ ] **Step 2: Add the emission section**

Immediately before the `## Output` section, insert:

```markdown
## Emit tasks.json (parallel scenario authoring)
Write `.sdlc/<slug>/qa/tasks.json` conforming to `workflows/tasks.schema.json`, with
`"stack": "qa"`. Scenarios are independent, so each scenario is its **own single-task group**:
- `context_manifest.read_once` = shared fixtures / page objects / test helpers the specs use;
  `reference` = the acceptance-criteria path and the contract summary.
- One `tasks[]` entry per scenario: `id`, its own `group_id`, `title` (the journey), empty
  `depends_on`, `reads` (extra fixtures), `writes` (the spec file it creates), `test` (the
  scenario id), `standards` (e.g. `["risk-tiered","determinism","isolation"]`),
  `needs_human_gate: false`. `slices[]` = one group per scenario.
- **Validate before returning:** `python3 workflows/validate_tasks.py .sdlc/<slug>/qa/tasks.json`
  must print `OK`.
```

- [ ] **Step 3: Update `## Output` to return `slices`**

In `## Output`, change `Return \`suite_path\` and \`tests_passed\`.` to:

```markdown
out-of-scope, data strategy). Also write `.sdlc/<slug>/qa/tasks.json`. Return `suite_path`,
`tasks_path`, `slices` (the `slices` array from tasks.json), and `tests_passed`.
```

- [ ] **Step 4: Verify**

Run: `grep -c "tasks.schema.json\|validate_tasks.py\|slices" skills/qa-automation/SKILL.md`
Expected: `3` or more.

- [ ] **Step 5: Commit**

```bash
git add skills/qa-automation/SKILL.md
git commit -m "feat(qa-automation): emit tasks.json scenario groups

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `backend-tasks` becomes the JSON fallback authoring path

**Files:**
- Modify: `skills/backend-tasks/SKILL.md`

**Interfaces:**
- Produces: `.sdlc/<slug>/backend/tasks.json` (same schema as Task 3) when no design-phase file exists; returns `tasks_path`, `slices`, `risky`.

- [ ] **Step 1: Update the header note (When to use)**

In `skills/backend-tasks/SKILL.md`, replace the first paragraph under `# backend-tasks` final sentence "Read-only — produces a task list, not code." by appending:

```markdown
This is the **fallback** author: the design phase normally emits `tasks.json` via
`/backend-design`. Run this only when `.sdlc/<slug>/backend/tasks.json` is absent (e.g. a
standalone `/backend-impl` run with no design phase).
```

- [ ] **Step 2: Replace the `## Output` section**

Replace the `## Output` section body with:

```markdown
## Output
Write the DAG to `.sdlc/<slug>/backend/tasks.json` conforming to `workflows/tasks.schema.json`
(same shape `/backend-design` emits): `context_manifest` (batched-read files), `tasks[]`
(`id`, `group_id`, `title`, `depends_on` intra-group only, `reads`, `writes`, `test`,
`standards`, `needs_human_gate`), and `slices[]` (one per independent group — two tasks share
a group iff one depends on the other or they write a common file). Validate with
`python3 workflows/validate_tasks.py .sdlc/<slug>/backend/tasks.json` (must print `OK`).
Return `tasks_path`, `slices`, and `risky` (true if any task needs a human gate).
```

- [ ] **Step 3: Update the `## Definition of done`**

Append to the `## Definition of done` sentence: `; tasks.json validates against the schema (no cross-group edges, disjoint writes across groups).`

- [ ] **Step 4: Verify**

Run: `grep -c "tasks.schema.json\|slices\|group_id" skills/backend-tasks/SKILL.md`
Expected: `3` or more.

- [ ] **Step 5: Commit**

```bash
git add skills/backend-tasks/SKILL.md
git commit -m "feat(backend-tasks): author tasks.json as JSON fallback

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `backend-implement` gains per-slice execution

**Files:**
- Modify: `skills/backend-implement/SKILL.md`

**Interfaces:**
- Consumes: `.sdlc/<slug>/backend/tasks.json`; invoked once per slice with `group_id` + `tasks_path` (from Task 9's `for_each`).

- [ ] **Step 1: Add the slice-mode section**

In `skills/backend-implement/SKILL.md`, immediately after the `## Before editing` section, insert:

```markdown
## Slice execution (one invocation per slice, from the impl `for_each`)
When called with a `group_id` and `tasks_path`, implement **only that slice**:
1. **Batch-load context once** — `cat` every path in `context_manifest.read_once` +
   `context_manifest.reference` in a SINGLE call, delimited by `=== <path> ===`. Do not use
   one `Read` per file. This is how the run stays under ~50 SDK calls.
2. **Run the slice in order** — for each `task_id` in the slice's `task_ids` (already
   dependency-ordered), batch-read that task's `reads` delta, then TDD it (write the failing
   `test` → minimal code → refactor) before moving to the next task.
3. **Human gates** — stop and ask before any task with `needs_human_gate: true`.
4. **Stay in scope** — edit only files in the slice's tasks' `writes`. Work in the worktree
   the `for_each` item provides; commit the slice on its worktree branch.

If no `tasks.json` exists (standalone run), author it first via `/backend-tasks`, then proceed
over its slices sequentially in this one session.
```

- [ ] **Step 2: Add outputs note**

In the `## Definition of done` section, change the final `Outputs: \`branch\`, \`summary\`, \`tests_passed\`.` to:

```markdown
Outputs: `branch`, `summary`, `tests_passed`. In slice mode, also return `worktree` and
`tasks_done` (the ids implemented).
```

- [ ] **Step 3: Verify**

Run: `grep -c "Slice execution\|group_id\|=== <path> ===" skills/backend-implement/SKILL.md`
Expected: `3` or more.

- [ ] **Step 4: Commit**

```bash
git add skills/backend-implement/SKILL.md
git commit -m "feat(backend-implement): per-slice batched execution

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: `frontend-implement` gains per-slice execution

**Files:**
- Modify: `skills/frontend-implement/SKILL.md`

**Interfaces:**
- Consumes: `.sdlc/<slug>/frontend/tasks.json`; invoked once per slice with `group_id` + `tasks_path` (from Task 10's `for_each`).

- [ ] **Step 1: Add the slice-mode section**

In `skills/frontend-implement/SKILL.md`, immediately after the `## Before editing` section, insert:

```markdown
## Slice execution (one invocation per slice, from the impl `for_each`)
When called with a `group_id` and `tasks_path`, implement **only that slice**:
1. **Batch-load context once** — `cat` every path in `context_manifest.read_once` +
   `context_manifest.reference` in a SINGLE call, delimited by `=== <path> ===` (not one
   `Read` per file). Keeps the run under ~50 SDK calls.
2. **Run the slice in order** — for each `task_id` in the slice's `task_ids`, batch-read its
   `reads` delta, then build test-first, wiring every required UI state for that task.
3. **Human gates** — stop and ask before any task with `needs_human_gate: true`.
4. **Stay in scope** — edit only files in the slice's tasks' `writes`, in the worktree the
   `for_each` item provides; commit the slice on its worktree branch.

This is distinct from **Plan mode** (produce the task/UI-state list and stop). If no
`tasks.json` exists (standalone run), author it first (plan mode), then proceed over its
slices sequentially in this one session.
```

- [ ] **Step 2: Add outputs note**

In `## Definition of done`, change `Outputs: \`branch\`, \`summary\`, \`tests_passed\`.` to:

```markdown
Outputs: `branch`, `summary`, `tests_passed`. In slice mode, also return `worktree` and
`tasks_done`.
```

- [ ] **Step 3: Verify**

Run: `grep -c "Slice execution\|group_id\|=== <path> ===" skills/frontend-implement/SKILL.md`
Expected: `3` or more.

- [ ] **Step 4: Commit**

```bash
git add skills/frontend-implement/SKILL.md
git commit -m "feat(frontend-implement): per-slice batched execution

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: `backend_impl.yaml` — `for_each` over slices + merge

**Files:**
- Modify: `workflows/backend_impl.yaml`

**Interfaces:**
- Consumes: `tasks.output.slices` (array of `{group_id, task_ids}`); each item invokes `/backend-impl` in slice mode (Task 7).
- Produces: `implement.outputs[<group_id>].{worktree,tasks_done}`; `merge_slices` lands them on `feature/<slug>-backend`.

- [ ] **Step 1: Replace the `tasks` step to load-or-author + return `slices`**

In `workflows/backend_impl.yaml`, replace the whole `- name: tasks` agent block (currently routing `to: implementer`) with:

```yaml
  # ---- 0. TASK DAG (load design-phase tasks.json, else author via /backend-tasks) ----
  - name: tasks
    description: Load-or-author the task DAG (tasks.json) and return the fan-out slices.
    prompt: |
      Ensure `.sdlc/{{ workflow.input.feature_slug }}/backend/tasks.json` exists and is valid:
      - If present (authored by /backend-design in the design phase), validate it:
        `python3 workflows/validate_tasks.py .sdlc/{{ workflow.input.feature_slug }}/backend/tasks.json`
      - If absent, run the **/backend-tasks** skill to author it (JSON, schema-valid), then validate.
      Inputs:
      - feature:          {{ workflow.input.feature }}
      - feature_slug:     {{ workflow.input.feature_slug }}
      - contract_summary: {{ workflow.input.contract_summary }}
      {% if workflow.input.lld_path %}- lld_path: {{ workflow.input.lld_path }}{% endif %}
      Return: tasks_path, slices (the `slices` array from tasks.json), risky.
    output:
      tasks_path: { type: string }
      slices: { type: array }
      risky: { type: boolean }
    routes:
      - to: implement
```

- [ ] **Step 2: Add the `for_each` fan-out block**

At the top level of the file (after the `workflow:` block, mirroring `main.yaml`'s `for_each:`), add:

```yaml
# ----------------------------------------------------------------------------
# Fan-out: one isolated build per INDEPENDENT slice, concurrently. Each slice's
# tasks are dependency-ordered inside the item (the skill runs them in order);
# groups are mutually independent (disjoint writes — validated), so parallel is safe.
# ----------------------------------------------------------------------------
for_each:
  - name: implement
    type: for_each
    description: Build independent task slices in parallel (each slice = ordered tasks).
    source: tasks.output.slices
    as: slice
    key_by: slice.group_id
    max_concurrent: 3
    failure_mode: all_or_nothing
    agent:
      name: build_slice
      model: claude-sonnet-5
      prompt: |
        Run the **/backend-impl** skill in SLICE mode — implement ONLY this slice. Inputs:
        - feature:          {{ workflow.input.feature }}
        - feature_slug:     {{ workflow.input.feature_slug }}
        - group_id:         {{ slice.group_id }}
        - tasks_path:       {{ tasks.output.tasks_path }}
        - branch:           feature/{{ workflow.input.feature_slug }}-backend/{{ slice.group_id }}
        - contract_summary (backend OWNS this — implement it exactly): {{ workflow.input.contract_summary }}
        Batch-load the context manifest in one call; run the slice's tasks in dependency order,
        test-first, in an isolated git worktree on the branch above. Return: worktree, tasks_done.
      output:
        worktree: { type: string }
        tasks_done: { type: array }
    routes:
      - to: merge_slices
```

- [ ] **Step 3: Delete the old `implementer` agent step**

Remove the entire `- name: implementer` block (the one with `model: claude-sonnet-5` routing `to: unit_tests`) — its role is now the `for_each` above.

- [ ] **Step 4: Add the `merge_slices` step before `unit_tests`**

Insert before `- name: unit_tests`:

```yaml
  # ---- 1b. MERGE SLICES (conflict-free by the disjoint-writes invariant) ---
  - name: merge_slices
    type: script
    description: Merge each slice's worktree branch onto the stack branch, then run tests once.
    command: bash
    args:
      - "-c"
      - |
        set -uo pipefail
        base="feature/{{ workflow.input.feature_slug }}-backend"
        echo "[backend] git checkout $base"
        {% for gid, out in implement.outputs.items() %}
        echo "[backend] merge slice {{ gid }} (worktree {{ out.worktree }})"
        # Real: git merge --no-ff "$base/{{ gid }}" -m "merge slice {{ gid }}"
        {% endfor %}
        echo "[backend] slices merged (disjoint writes -> no conflicts)"
        exit 0
    timeout: 600
    routes:
      - to: unit_tests
```

- [ ] **Step 5: Update the `output:` block references (implementer → implement)**

The final `output:` block references `implementer.output.*`. Change the `branch`/`summary` lines to derive from the fan-out and the stack branch:

```yaml
output:
  branch: "feature/{{ workflow.input.feature_slug }}-backend"
  summary: "{% if implement is defined %}{{ implement.outputs | length }} slice(s) built{% endif %}"
  tests_passed: "{% if reviewers is defined %}true{% else %}false{% endif %}"
  review_path: "{% if reviewers is defined %}{{ reviewers.output.review_path }}{% endif %}"
```

Also update the `done` terminate step's `output_template.branch`/`summary` the same way
(`branch: "feature/{{ workflow.input.feature_slug }}-backend"`,
`summary: "{{ implement.outputs | length }} slice(s) built"`).

- [ ] **Step 6: Verify the YAML parses and the fan-out is present**

Run:
```bash
python3 -c "import yaml; d=yaml.safe_load(open('workflows/backend_impl.yaml')); \
fe=d['for_each'][0]; assert fe['source']=='tasks.output.slices'; assert fe['name']=='implement'; \
names=[a['name'] for a in d['agents']]; assert 'merge_slices' in names and 'implementer' not in names; \
print('OK', fe['source'], names)"
```
Expected: `OK tasks.output.slices [...'tasks', 'merge_slices', 'unit_tests'...]` (no `implementer`).

- [ ] **Step 7: Commit**

```bash
git add workflows/backend_impl.yaml
git commit -m "feat(backend_impl): for_each over slices + merge

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: `frontend_impl.yaml` — `for_each` over slices + merge

**Files:**
- Modify: `workflows/frontend_impl.yaml`

**Interfaces:**
- Consumes: `tasks.output.slices`; each item invokes `/frontend-impl` in slice mode (Task 8).

- [ ] **Step 1: Replace the `tasks` step**

Replace the `- name: tasks` block (routing `to: implementer`) with:

```yaml
  # ---- 0. TASK DAG (load design-phase tasks.json, else author via /frontend-impl plan) ----
  - name: tasks
    description: Load-or-author the task DAG (tasks.json) and return the fan-out slices.
    prompt: |
      Ensure `.sdlc/{{ workflow.input.feature_slug }}/frontend/tasks.json` exists and is valid:
      - If present (authored by /frontend-design), validate it:
        `python3 workflows/validate_tasks.py .sdlc/{{ workflow.input.feature_slug }}/frontend/tasks.json`
      - If absent, run **/frontend-impl** in PLAN mode to author it (JSON, schema-valid), then validate.
      Inputs:
      - feature:          {{ workflow.input.feature }}
      - contract_summary: {{ workflow.input.contract_summary }}
      {% if workflow.input.lld_path %}- lld_path: {{ workflow.input.lld_path }}{% endif %}
      Return: tasks_path, slices.
    output:
      tasks_path: { type: string }
      slices: { type: array }
    routes:
      - to: implement
```

- [ ] **Step 2: Add the `for_each` block (top level, after `workflow:`)**

```yaml
# ----------------------------------------------------------------------------
# Fan-out: one isolated build per INDEPENDENT slice, concurrently (disjoint writes).
# ----------------------------------------------------------------------------
for_each:
  - name: implement
    type: for_each
    description: Build independent frontend slices in parallel (each slice = ordered tasks).
    source: tasks.output.slices
    as: slice
    key_by: slice.group_id
    max_concurrent: 3
    failure_mode: all_or_nothing
    agent:
      name: build_slice
      model: claude-sonnet-5
      prompt: |
        Run the **/frontend-impl** skill in SLICE mode — implement ONLY this slice. Inputs:
        - feature:          {{ workflow.input.feature }}
        - feature_slug:     {{ workflow.input.feature_slug }}
        - group_id:         {{ slice.group_id }}
        - tasks_path:       {{ tasks.output.tasks_path }}
        - branch:           feature/{{ workflow.input.feature_slug }}-frontend/{{ slice.group_id }}
        - contract_summary (frontend CONSUMES this exactly): {{ workflow.input.contract_summary }}
        Batch-load the context manifest in one call; run the slice's tasks in dependency order,
        test-first, wiring every required UI state, in an isolated worktree. Return: worktree, tasks_done.
      output:
        worktree: { type: string }
        tasks_done: { type: array }
    routes:
      - to: merge_slices
```

- [ ] **Step 3: Delete the old `implementer` step** (the `model: claude-sonnet-5` block routing `to: component_tests`).

- [ ] **Step 4: Add `merge_slices` before `component_tests`**

```yaml
  # ---- 1b. MERGE SLICES (conflict-free by the disjoint-writes invariant) ---
  - name: merge_slices
    type: script
    description: Merge each slice's worktree branch onto the stack branch, then test once.
    command: bash
    args:
      - "-c"
      - |
        set -uo pipefail
        base="feature/{{ workflow.input.feature_slug }}-frontend"
        {% for gid, out in implement.outputs.items() %}
        echo "[frontend] merge slice {{ gid }} (worktree {{ out.worktree }})"
        {% endfor %}
        echo "[frontend] slices merged (disjoint writes -> no conflicts)"
        exit 0
    timeout: 600
    routes:
      - to: component_tests
```

- [ ] **Step 5: Update `output:` and the `done` `output_template`** the same way as Task 9 Step 5, using `-frontend`:

```yaml
output:
  branch: "feature/{{ workflow.input.feature_slug }}-frontend"
  summary: "{% if implement is defined %}{{ implement.outputs | length }} slice(s) built{% endif %}"
  tests_passed: "{% if reviewers is defined %}true{% else %}false{% endif %}"
  review_path: "{% if reviewers is defined %}{{ reviewers.output.review_path }}{% endif %}"
```

- [ ] **Step 6: Verify**

Run:
```bash
python3 -c "import yaml; d=yaml.safe_load(open('workflows/frontend_impl.yaml')); \
fe=d['for_each'][0]; assert fe['source']=='tasks.output.slices'; \
names=[a['name'] for a in d['agents']]; assert 'merge_slices' in names and 'implementer' not in names; \
print('OK', names)"
```
Expected: `OK [...'tasks', 'merge_slices', 'component_tests'...]`.

- [ ] **Step 7: Commit**

```bash
git add workflows/frontend_impl.yaml
git commit -m "feat(frontend_impl): for_each over slices + merge

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: `qa.yaml` — parallel scenario authoring via `for_each`

**Files:**
- Modify: `workflows/qa.yaml`

**Interfaces:**
- Consumes: `author_tests.output.slices` (one group per scenario, from Task 5).
- Produces: parallel-authored spec files; the existing `run_e2e` script runs the whole suite once (unchanged).

- [ ] **Step 1: Add `slices` to the `author_tests` output**

In `workflows/qa.yaml`, in the `- name: author_tests` step, change its `output:` to add `slices` and route to a new authoring fan-out:

```yaml
    output:
      suite_path: { type: string }
      tasks_path: { type: string }
      slices: { type: array }
    routes:
      - to: author_specs
```

(Update the `author_tests` prompt's final line to: `Return: suite_path, tasks_path, slices.`)

- [ ] **Step 2: Add the `for_each` authoring block (top level, after `workflow:`)**

```yaml
# ----------------------------------------------------------------------------
# Fan-out: author each critical-journey spec in parallel (scenarios are independent).
# ----------------------------------------------------------------------------
for_each:
  - name: author_specs
    type: for_each
    description: Author each E2E scenario spec in parallel (one group per scenario).
    source: author_tests.output.slices
    as: slice
    key_by: slice.group_id
    max_concurrent: 3
    failure_mode: all_or_nothing
    agent:
      name: author_scenario
      prompt: |
        Run the **/qa** skill in SCENARIO mode — author ONLY this scenario's spec. Inputs:
        - feature:      {{ workflow.input.feature }}
        - feature_slug: {{ workflow.input.feature_slug }}
        - group_id:     {{ slice.group_id }}
        - tasks_path:   {{ author_tests.output.tasks_path }}
        Batch-load the fixture manifest in one call; write the scenario's spec file(s) with
        stable selectors and real assertions. Return: spec_path.
      output:
        spec_path: { type: string }
    routes:
      - to: run_e2e
```

- [ ] **Step 3: Verify** (`run_e2e`, `qa_fix`, `done` stay unchanged; only the entry route changed)

Run:
```bash
python3 -c "import yaml; d=yaml.safe_load(open('workflows/qa.yaml')); \
fe=d['for_each'][0]; assert fe['source']=='author_tests.output.slices'; \
names=[a['name'] for a in d['agents']]; assert 'run_e2e' in names; \
print('OK', fe['name'], names)"
```
Expected: `OK author_specs [...'author_tests', 'run_e2e'...]`.

- [ ] **Step 4: Add a scenario-mode note to the qa skill**

In `skills/qa-automation/SKILL.md`, append to the `## Emit tasks.json` section:

```markdown
**Scenario mode:** when invoked with a `group_id` and `tasks_path`, author only that one
scenario's spec file (batch-load the fixture manifest once) and return `spec_path`.
```

- [ ] **Step 5: Commit**

```bash
git add workflows/qa.yaml skills/qa-automation/SKILL.md
git commit -m "feat(qa): parallel scenario authoring via for_each

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: `design.yaml` — surface `tasks_path` from the design steps

**Files:**
- Modify: `workflows/design.yaml`

**Interfaces:**
- Consumes: `backend_design`/`frontend_design` now return `tasks_path` (Tasks 3–4).

- [ ] **Step 1: Add `tasks_path` to `backend_design` output + prompt**

In `workflows/design.yaml`, in `- name: backend_design`: change the prompt's `Return: lld_path.` to `Return: lld_path, tasks_path.` and change its `output:` to:

```yaml
    output:
      lld_path: { type: string }
      tasks_path: { type: string }
```

- [ ] **Step 2: Same for `frontend_design`**

In `- name: frontend_design`: `Return: lld_path, tasks_path.` and:

```yaml
    output:
      lld_path: { type: string }
      tasks_path: { type: string }
```

- [ ] **Step 3: Add the tasks paths to the workflow `output:` block**

In the final `output:` block, after the `frontend_lld_path:` line, add:

```yaml
  backend_tasks_path:  ".sdlc/{{ workflow.input.feature_slug }}/backend/tasks.json"
  frontend_tasks_path: ".sdlc/{{ workflow.input.feature_slug }}/frontend/tasks.json"
```

- [ ] **Step 4: Verify**

Run:
```bash
python3 -c "import yaml; d=yaml.safe_load(open('workflows/design.yaml')); \
a={x['name']:x for x in d['agents']}; \
assert 'tasks_path' in a['backend_design']['output']; \
assert 'tasks_path' in a['frontend_design']['output']; \
assert 'backend_tasks_path' in d['output']; print('OK')"
```
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add workflows/design.yaml
git commit -m "feat(design): surface tasks_path from design steps

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification (after all tasks)

- [ ] **All workflow YAML parses:**
  ```bash
  for f in workflows/*.yaml; do python3 -c "import yaml,sys; yaml.safe_load(open('$f')); print('OK', '$f')"; done
  ```
  Expected: `OK` for every file.

- [ ] **Validator passes on the fixtures:**
  ```bash
  python3 workflows/validate_tasks.py workflows/testdata/tasks.valid.json && \
  python3 workflows/validate_tasks.py workflows/testdata/tasks.invalid-crossgroup.json; echo "exit=$?"
  ```
  Expected: first prints `OK ...`; second prints `FAIL ...` with `exit=1`.

- [ ] **No skill still promises `tasks.md` as its primary output:**
  ```bash
  grep -rn "tasks.md" skills/ workflows/ || echo "clean"
  ```
  Expected: any remaining hits are intentional (human-readable notes), not the machine artifact.

## Manual follow-up (out of plan scope)

End-to-end execution requires a Conductor runtime, which is not available in this repo's test
harness. After merge, run `conductor run workflows/backend_impl.yaml --input feature="..."
--input feature_slug="..." --input contract_summary="..."` against a feature that produced a
`tasks.json`, and confirm: (a) the `for_each` fans out per slice, (b) `max_concurrent` is
honored, and (c) `merge_slices` lands all branches. If Conductor rejects a prompt-only
`for_each` agent (requiring `type: workflow`), wrap `build_slice` in a one-step sub-workflow —
the slice prompt is unchanged.
