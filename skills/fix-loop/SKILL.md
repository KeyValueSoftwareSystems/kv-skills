---
name: fix-loop
description: Fix failing deterministic checks with a bounded loop of at most 3 autonomous attempts, root-cause first, editing only files related to the failure, then escalate to a human. Front door for /fix.
allowed-tools: Read, Grep, Glob, Bash, Edit
---

# fix-loop

Fix failing checks with a **bounded** loop. **Maximum 3 autonomous attempts.** The cap is
also enforced by the workflow (`maestro.config.yaml` → `fix_loop.max_attempts`) via a
route-back counter — respect it whether run in a workflow or standalone.

**Safety:** never run destructive commands (`rm -rf`, force-push, `DROP`/`TRUNCATE`) or write
prod config/secrets. Nothing auto-blocks this — you are the backstop, and this rule holds
regardless of environment. The escalation triggers below are hard stops.

## External skill (provision — debugging method)
Read `skills.config.yaml` → `shared.external.debug` (default `systematic-debugging`, from the
Superpowers pack, or `none`). If set, use its four-phase root-cause method — **do not "fix" what you have not
understood.** Whatever the method, it must: reproduce the failure, find the root cause,
predict the fix, and confirm. If `none`, follow the same discipline in-pack.

## Per attempt
1. **Reproduce** — quote the exact failing command and its real error output.
2. **Diagnose** — find the root cause (read the code/stack trace); distinguish a real bug
   from a flaky test or an environment problem. State the cause before touching code.
3. **Smallest fix** — edit **only** files related to that root cause; no broad refactors,
   no unrelated "drive-by" changes.
4. **Re-run the failing check**; record the result.
5. If green, run full verification (`/verify`); if a new failure appears, it counts as an attempt.

## Classify before you "fix"
- **Flaky test** — fix the test's determinism (waits/selectors/seeding), not the product,
  and never by weakening assertions.
- **Environment issue** (service down, port, missing dep) — fix the env / report it; not a
  code change to force green.
- **Real defect** — fix the code with a regression test that fails before and passes after.
- **Spec/contract ambiguity** — stop and ask; do not invent behavior.

## Stop and ask a human if
- a DB migration is required but not approved · the API contract would change ·
  auth/permission behavior changes · a dependency upgrade is needed · production config
  changes · the same error persists after 3 attempts · multiple valid designs exist ·
  the fix would weaken a test or a security control.

## Definition of done
Either: the targeted check and full `/verify` pass with a root-cause fix (and a regression
test for real defects); or you escalate with the exact commands, the root cause, files
changed, attempts used, and remaining risk. Escalation is success, not failure.
