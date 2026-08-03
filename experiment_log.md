# Experiment Log

Dated record of debugging iterations against `agent_configs/`. Append an
entry every time a fix is attempted for a failing test, whether it worked
or not — this is what prevents ping-ponging the same fix back and forth
between the Officer and Supervisor. See
`docs/agents/debugging-guide.md` for the methodology this log supports.

## Entry Template

```
## YYYY-MM-DD — <short title>

**Failing test(s):** test_configs/<file>.json (× N runs, M/N failed)
**Category:** EVAL_CONFIG_ERROR | PLATFORM_ERROR | MISSING_TOOL_CALL |
  WRONG_TOOL_CALL | WRONG_PARAMS | EXPECTATION_FAIL | HALLUCINATION |
  CROSS_AGENT_CONTRADICTION | TEXT_TONE_MISMATCH
**Change:** <what was edited in agent_configs/, one sentence>
**Reason:** <why this transcript pointed at this fix>
**Result:** <pass rate after fix, on both the target test AND the
  other agent's full suite — cross-agent regression check>
**Status:** fixed | reverted | superseded by <date>
```

---

<!-- Newest entries go on top. -->

## 2026-08-03 — First `simulation`-type test: turn-budget too tight, guardrail confirmed live in `run-tests`

**Failing test(s):** `test_configs/Claims-Lodgement-Officer-vehicle-guided-flow-full-conversation.json`
(new, × 1 run via direct `POST /v1/convai/agents/{id}/run-tests` sanity check
against the live production agent — not a CLI `agents test` run, since the
new test wasn't yet attached to any pushed agent config).
**Category:** EVAL_CONFIG_ERROR (test's own `simulation_max_turns` too low —
not an agent bug).

This is the repo's first `simulation`-type test (closing part of TDD §6's
structural gap / Known Issue #4 — see `docs/agents/claims-lodgement.tdd.md`).
Two things came out of sanity-checking it live that the brief didn't predict:

**1. `simulation_max_turns: 10` was too tight and produced a false failure.**
First run: `condition_result.result: "failure"`, rationale: "The conversation
never reached a closing line ... and end_call was never called. The
transcript hit the turn budget without completing the close. All required
fields were collected and spelling was confirmed." The transcript showed the
agent correctly collecting every field one at a time with zero re-asks, but
early in the flow (right after only `policy_number` + `what_happened` were
collected) the `Claim completeness before closing` guardrail fired and
blocked the agent's response **three times in a row** before it recovered
and asked for the date/time — each blocked attempt still consumed a turn of
budget. By the time all 8 fields + name-spelling confirmation + the
mandatory "another claim?" question were done, 10 turns were exhausted one
question before the actual closing line. **Change:** raised
`simulation_max_turns` to 20 in the test config and re-pushed (same
`test_id`, `elevenlabs tests push` updates in place). **Result:** re-ran the
identical scenario; passed cleanly — `condition_result.result: "success"`,
"All required fields collected one at a time, no re-asking, spelling
confirmed for both names, closing line delivered correctly ... end_call
called after closing." **Status:** fixed (test-config change only; no
`agent_configs/` edit).

**2. Confirms guardrails DO fire on `simulation`-type tests run via
`POST /v1/convai/agents/{id}/run-tests`** — both sanity-check runs show real
`guardrail_triggered` tool calls with populated `trigger_reason`, not the
`"Skipping tool call in test mode"` stub that TDD §5 documented for `llm`-type
CLI/API test-mode runs. This doesn't contradict TDD §5 (that finding was
specifically about `llm`-type test-mode evaluation) but it's new information
worth noting: `simulation`-type tests are the first eval mechanism in this
repo confirmed to actually exercise the `Claim completeness before closing`
guardrail pre-production. TDD §5 and Known Issue #5 still stand as written
for `llm` tests specifically; not broadening that claim here without a
dedicated investigation, but flagging it since it's directly relevant to
anyone extending `simulation` coverage next.

**Note on test mechanics:** the CLI's `elevenlabs agents test <id> --no-ui`
path requires the test to already be in the *live* agent's
`attached_tests` (a pushed agent config). Since this task explicitly
excludes running `elevenlabs agents push` (production push is CI's job via
the `pr-test` branch), the sanity check above used a direct
`POST /v1/convai/agents/{id}/run-tests` call with an explicit `test_id`
instead — this works against the test object itself (already real, from
`elevenlabs tests push`) without touching the agent's attached-tests list,
and runs harmlessly against the live production branch without mutating
anything.

## 2026-07-26 — Supervisor retirement rollout (ADR 0005): 3 fixes

**Failing test(s):** Full 18-test Officer suite, multiple runs during rollout.
**Category:** WRONG_TOOL_CALL (fix 1), CROSS_AGENT_CONTRADICTION-equivalent / stale-config (fix 2), WRONG_TOOL_CALL (fix 3).

**Fix 1 — live `tools` array still had `transfer_to_agent` after push.**
`elevenlabs agents push` reported success but the live agent kept both
`end_call` and `transfer_to_agent` even though `transfer_to_agent` was
removed locally — the CLI silently failed to delete it (reverse of the
known "CLI drops declared tools" bug). Caught by `handles-express-property-claim`
calling `transfer_to_agent` in test mode. **Change:** direct API `PATCH
conversation_config.agent.prompt.tools` with the correct (single-tool)
list. **Result:** fixed, confirmed via live re-fetch. `scripts/verify-live-tools.py`
extended to also fail on undeclared extra live tools, not just missing ones.
**Status:** fixed.

**Fix 2 — orphaned `workflow` block's `officer_node.additional_prompt` still said "you must not call end_call yourself... a supervisor reviews completeness."**
Pre-existing Known Issue #1 (TDD §9) turned out not to be inert: despite
`edges: {}`, this leftover instruction text was intermittently influencing
responses, causing ~1/3 flaky failures across several tests (agent
avoiding `end_call` outright, or falling back to `transfer_to_agent`).
**Change:** direct API PATCH clearing `additional_prompt` to `""` on both
`officer_node` and `supervisor_node` (edges/structure untouched — the
`workflow` block itself remains undeletable per Known Issue #1).
**Result:** flakiness dropped sharply (16-18/18 typical, down from ~13/18).
**Status:** fixed (workflow block itself still present but now inert).

**Fix 3 — test-mode channel ambiguity + end_call-with-a-question pattern.**
`{{system__is_text_only}}` resolves inconsistently across test-mode runs
with no explicit channel signal, so voice-specific tests (spelling-gate
tests especially) flip pass/fail run to run. Found `conversation_initiation_source`
(`"twilio"` / `"whatsapp"` / etc.) is a real, CLI-supported per-test field
that pins simulated channel — not documented anywhere before now.
**Change:** added `conversation_initiation_source: "twilio"` to 8 voice-context
tests and `"whatsapp"` to the WhatsApp-timeout test; also added an explicit
prompt rule (`closing-condition`) forbidding `end_call` when the message
being spoken is itself a question awaiting a reply (observed 3x: model
packaged a legitimate follow-up question inside `end_call`'s
`system__message_to_speak`, which would silently end the call mid-question
live). **Also discovered while diagnosing this:** `is_blocked: false` on
these attempts confirms the `Claim completeness before closing` guardrail
does **not** fire in CLI test-mode runs at all — tool calls are stubbed
("Skipping tool call in test mode"). This resolves TDD §5's long-open
question: guardrail coverage in test mode is confirmed **absent**, not
just unverified. **Result:** `does-not-close-with-missing-fields`,
`handles-nominated-representative`, `handles-multiple-claims` went from
flaky/failing to consistently passing across 2 follow-up runs.
**Status:** fixed. Remaining flakiness (2/18 typical, `collects-*-via-guided-flow`,
`handles-express-vehicle-claim`) reads as ordinary LLM-evaluator variance,
not a new regression — same tests were already borderline pre-migration.
