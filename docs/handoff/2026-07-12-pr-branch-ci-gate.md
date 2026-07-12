# Handoff — PR-branch CI gate (#36, #37)

**Date:** 2026-07-12  
**PR:** #38 (merged as `94e79a8`)  
**Author:** Main agent + sub-agents

## What shipped

A new `pr-test` GitHub Actions job that pushes agent configs to an isolated ElevenLabs branch on every PR, verifies platform state, and runs tests — **before** merge. Previously, PRs only got local JSON validation; platform push and tests only ran post-merge on `main`.

### Pipeline

```
validate → create-branch → push → verify → test (non-blocking)
```

- **Create branch:** `POST /v1/convai/agents/{id}/branches` — idempotent, accepts 200/400/422
- **Push:** `elevenlabs agents push --agent <id> --branch pr-N` (CLI 0.5.5+)
- **Verify:** `verify-live-tools.py --branch-name pr-N` — cross-checks tools, webhook, attached_tests
- **Test:** `test-pr-branch.py --branch-name pr-N` — calls `POST run-tests` with `branch_id`, polls for completion (180s timeout)
- **Cleanup:** `pr-cleanup.yml` archives `pr-*` branches on PR close via `PATCH`

### Files (6 files, +359/-29)

| File | Change |
|------|--------|
| `.github/workflows/agents.yml` | New `pr-test` job, `timeout-minutes: 10` |
| `.github/workflows/pr-cleanup.yml` | New: branch archival on PR close |
| `scripts/verify-live-tools.py` | `--branch-name` support, `find_branch_id` with error handling |
| `scripts/test-pr-branch.py` | New: API-based test runner with async polling |
| `scripts/archive-pr-branches.py` | New: branch archival via PATCH |
| `CLAUDE.md` | Updated CI docs |

### Design decisions

1. **`run-tests` not `simulate-conversation`** — the latter is deprecated. `run-tests` accepts `branch_id` and uses the same infrastructure as the main-branch test job
2. **`continue-on-error: true` on test step** — LLM-evaluated tests are flaky (see #31). The mechanical guardrail provides defense; the test is a sanity check. Remove once #31 is resolved
3. **Stdlib-only Python** — no pip dependencies; all scripts use `urllib.request`

## Immediate next steps

### 1. Verify the pipeline on next PR

Open a small test PR. Confirm:
- `pr-test` job triggers and passes
- `pr-cleanup.yml` archives the PR branch after merge/close
- Branch creation is idempotent on re-pushes

### 2. Resolve #31 (flaky `catches-missing-field` test)

Current state: ~50% pass rate via `run-tests`. The test is non-blocking (`continue-on-error: true`).

Lowest-effort fix (est. 15 min):
- Add 2-3 more `success_examples` and `failure_examples` to the test config for evaluator calibration
- Tighten the `success_condition` — remove the triple-negative pattern

Once pass rate exceeds ~80% across 5 runs:
- Remove `continue-on-error: true` from `pr-test` job (line 77 in `agents.yml`)

### 3. Monitor PR gate signal quality

After a few PRs, assess:
- Is `pr-test` catching real issues (tool drops, webhook mismatches)?
- Is the flaky test rate acceptable?
- Are branches accumulating? (cleanup workflow should handle this)

## Known issues

- **`find_branch_id` duplicated across 3 scripts** — if the API response key changes, fix in all three places. Consider extracting to `scripts/_elevenlabs_api.py` in a follow-up
- **CLI `--branch` requires `--agent`** — the `for agent_id in ...` loop works around this. If the CLI adds bulk `--branch` support, the push step can simplify
- **Test step is non-blocking** — until #31 resolves, test failures don't block merge

## Reference

- PR #38: https://github.com/michaelsolo221/eleven-agents/pull/38
- Issue #31: https://github.com/michaelsolo221/eleven-agents/issues/31
- Issue #36: https://github.com/michaelsolo221/eleven-agents/issues/36
- Issue #37: https://github.com/michaelsolo221/eleven-agents/issues/37
- `continue-on-error` line: `agents.yml:77`
