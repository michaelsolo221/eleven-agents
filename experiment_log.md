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
