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

## 2026-08-07 — Issue #73: premature `end_call` regression (was "fixed" 2026-07-26)

**Failing test(s):** none locally reproducible pre-fix at time of writing —
the bug is documented via two real production transcripts in issue #73
(`conv_7201kzd0gz9vewpavb1bxy8tt5pg`, `conv_0001kykqhmvyesjve5e6vt63avew`),
not a failing CI test. See Coverage Map gap this closes: the new
`resumes-after-off-topic-redirect-without-ending-call` test (§6).
**Category:** WRONG_TOOL_CALL (`end_call` fired while the agent's own
response was, or should have been, a pending question) + PLATFORM_ERROR
(the one mechanical backstop, the `Claim completeness before closing`
guardrail, was structurally blind — see below).

**This is a recurrence, not a fresh bug.** The 2026-07-26 entry below ("Fix
3") already added the `closing-condition` prompt rule's "CRITICAL: ... do
NOT call end_call" clause for this exact shape (model bundling a legitimate
follow-up question inside `end_call`'s spoken message). It was logged
"Status: fixed" and held for about two weeks, then regressed in production.
Per `docs/agents/debugging-guide.md`'s "don't repeat an approach that
already failed to hold," a second prompt-only patch was deliberately not
used as the primary fix.

**Change:**
1. `platform_settings.guardrails.custom.config.configs[0].history_message_count`
   0 → 20 (`history_include_tool_calls` false → true). This guardrail is
   confirmed (2026-08-03 entry below) to actually fire on live calls and
   `simulation`-type test runs — but at `history_message_count: 0` it judged
   every candidate response with no transcript context, i.e. it could not
   actually check the "has this field been collected" question its own
   prompt asks it to answer. Both real incidents involve exactly the field
   the guardrail is supposed to catch missing (a genuinely-missing field in
   incident 1; unconfirmed name spelling in incident 2) — plausible root
   cause for why the mechanical backstop didn't block either one.
2. Added an explicit clause to that guardrail's prompt blocking `end_call`
   bundled with any unanswered question, checked independently of the
   field-completeness reasoning — cheap, near-deterministic pattern match as
   defense-in-depth, since the production evidence shows the model's own
   chain-of-thought already recognized the contradiction and produced the
   bad tool call anyway (reasoning-level fixes clearly aren't sufficient
   alone).
3. `built_in_tools.end_call.description` populated (was empty string since
   this tool was first declared); `pre_tool_speech` "auto" → "force" so a
   silent immediate hangup (incident 1's shape) can't recur even in a worst
   case; removed a duplicate `end_call` entry from `prompt.tools[]`.
4. Trialed `conversation_config.agent.prompt.llm` "qwen35-397b-a17b" →
   "claude-haiku-4-5" — deviates from the PRD's explicit LLM spec (flagged
   in `docs/agents/claims-lodgement.tdd.md` §1 and Known Issues #9, pending
   stakeholder sign-off). Motivation: ADR 0004 already named this general
   failure class ("LLM kept generating after the tool call — no 'stop after
   tool X' mechanism") a platform-level risk, and the hosted `qwen3.5`
   tier is a cost/latency-optimized model, not one advertised for strict
   instruction-following.
**Reason:** both production transcripts point at the same root shape
(model reasons correctly, attaches `end_call` anyway) that a prompt-only
patch already failed to hold against once; the guardrail — the only
mechanical layer left in the stack per ADR 0002/0005 — was misconfigured
in a way that would explain why it didn't catch either incident live.
**Result:** Verified against an isolated ElevenLabs branch. `verify-live-tools.py`
clean. `test-pr-branch.py`, 3 full suite runs + confirmation reruns on
specific tests: new test `resumes-after-off-topic-redirect-without-ending-call`
passed 3/3; `vehicle-guided-flow-full-conversation` (`simulation`-type, the
only test type confirmed to exercise the guardrail) passed 3/3;
`does-not-close-with-missing-fields` passed 3/4 (one isolated flake, not a
regression). Simulate-API replay of the two real incidents was attempted but
skipped — the endpoint's `branch_id` parameter was confirmed silently
ignored (identical behavior with a real vs. bogus branch ID; the endpoint is
also flagged deprecated in ElevenLabs' own docs in favor of `run-tests`).

**But `claude-haiku-4-5` (item 4) overcorrected**: `wraps-up-after-2-attempt-retry-cap`
and `completes-claim-and-ends-call` both failed **5/5** (3 suite runs + 2
isolated reruns) — the agent now re-confirms or re-asks indefinitely instead
of ever delivering the Closing Message or calling `end_call`. Two unrelated
tests also newly failed consistently, `presents-whatsapp-summary-card` and
`keeps-phone-and-policy-numbers-as-digits-on-voice`, indicating the model
swap affected channel-conditional instruction-following generally, not just
`end_call` timing. Stacking three simultaneous `end_call` negative
constraints (tool description, prompt, guardrail) with a swap to a more
conservative model produced the opposite failure mode. **Reverted item 4**
(`llm` field and the matching `<prompt_model>` tag back to
`qwen35-397b-a17b`) so this fix ships with one variable changed — the
guardrail/tool fixes — verified in isolation. Re-verification of the
guardrail/tool-only fix (no LLM swap) against the isolated branch: see
follow-up entry below / this session's PR description.

**Follow-up (same day) — further tuning after a second regression on the
LLM-reverted config:** `completes-claim-and-ends-call` still failed
consistently even with `qwen35-397b-a17b` restored. Live transcript showed
the same channel-misjudgment pattern as the LLM-swap round (guardrail
wrongly demanding a WhatsApp card on a voice-pinned test) — root cause:
the guardrail has no direct access to `{{system__is_text_only}}` and infers
channel purely from transcript style, and `history_message_count: 20` gave
the small eval model (`gemini-2.5-flash-lite`) enough extra context to
occasionally misjudge it. Reduced to `10` and reverted
`history_include_tool_calls` to `false` (wasn't proven necessary). Result:
0/8 → this specific failure pattern gone in the next round.

A second, unrelated failure pattern was then found in the same test and
initially conflated with the above before a closer look: the agent asking
"Is there another claim you'd like to lodge?" instead of closing — which is
*correct* per the `multiple-claims` prompt rule (mandatory on every voice
call before the Closing Message), but the test's `chat_history` never
included that question/answer turn. Pre-existing test/prompt mismatch, not
an agent regression. Fixed by adding the missing turns to
`test_configs/Claims-Lodgement-Officer-completes-claim-and-ends-call.json`
and re-pushing (same `test_id`). Also raised
`Claims-Lodgement-Officer-vehicle-guided-flow-full-conversation.json`'s
`simulation_max_turns` 20 → 26 for the same reason (a non-blind guardrail
retries more, plus the now-consistently-triggered multiple-claims turn adds
to the conversation length).

**Blocked mid-final-verification by ElevenLabs account TTS quota exhaustion**
(confirmed independently via `GET /v1/user/subscription`:
148,499/148,500 characters used, resets 2026-08-12) — the last verification
round's 4th run returned 0/26 with every test failing on
`401 quota_exceeded`, not a real regression; discarded. Runs 1-3 of that
round (quota draining but not yet exhausted) showed:
`resumes-after-off-topic-redirect-without-ending-call` 3/3 (holds),
`completes-claim-and-ends-call` 2/3 (improved, not yet cleanly confirmed
reliable), `vehicle-guided-flow-full-conversation` 1/3 (still shaky, cause
unconfirmed — could be genuine or quota-adjacent noise),
`does-not-close-with-missing-fields` 2/3 (same flakiness as prior round),
`keeps-phone-and-policy-numbers-as-digits-on-voice` 3/3 **FAIL** (persists
from the prior round's 4/4 fail — a real, reproducible issue, but not yet
checked against the true pre-#73 baseline to know if it's pre-existing or
newly introduced).

**Also caught and fixed during this investigation, unrelated to the fix
itself:** one verification agent's `elevenlabs agents push --branch
issue-73-verify` call silently rewrote the repo's local `agents.json` to
point `branch_id`/`version_id` at the isolated verification branch instead
of Main/production. Caught via `git diff` before any commit, reverted with
`git checkout -- agents.json`. Worth remembering next time an agent-facing
subagent is given `push --branch` access: it can mutate this tracking file
as a side effect even when the agent-side push target is correctly scoped.

**Status:** Core fix (guardrail history-blindness + `end_call`
description/dedup/`pre_tool_speech`) — fixed, verified via the actual bug
reproduction test (3/3, every round, never failed). Two secondary test
issues found and fixed along the way (channel-misjudgment side effect;
`completes-claim-and-ends-call`'s missing multiple-claims turn). LLM swap
(item 4) — reverted same day; tracked as a separate follow-up experiment.
`wraps-up-after-2-attempt-retry-cap` and `presents-whatsapp-summary-card`
confirmed pre-existing and unrelated, filed as **issue #74** and
**issue #75** respectively — not part of this fix. **Not fully closed**:
final clean verification blocked on ElevenLabs quota reset (2026-08-12) for
`completes-claim-and-ends-call`, `vehicle-guided-flow-full-conversation`,
and `keeps-phone-and-policy-numbers-as-digits-on-voice` (this last one not
yet filed as an issue — not confirmed pre-existing vs. fix-caused, pending
baseline check after quota resets). PR opened with these caveats explicit;
do not merge until a clean post-reset verification pass confirms all three.

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
