# Debugging Failing Tests — Methodology

Adapted from Google's CXAS-SCRAPI `agent-foundry` debug methodology
(https://googlecloudplatform.github.io/cxas-scrapi/), ported to ElevenLabs'
`llm` / `tool` / `simulation` test types and this repo's single-agent
(Claims-Lodgement-Officer) architecture. Until `docs/adr/0005-retire-claims-supervisor-single-agent-lodgement.md`,
this was a two-agent (Officer → Supervisor) architecture — the cross-agent
regression check below described that era and no longer applies, but is
kept as a reminder of the pattern in case a second agent is reintroduced.

See `CLAUDE.md` → "Debugging Failing Tests" for the quick-reference version.
This file is the full methodology; load it when a fix isn't obvious from the
quick reference, or when failures span multiple tests.

## Core Principles

- **Default to fixing the agent, not the test.** `success_condition` /
  `success_examples` / `failure_examples` are the contract with the business
  (see `CONTEXT.md`). When a test fails, assume the agent is wrong first —
  never loosen a `success_condition` just to make a run go green.
- **Don't trust a single run.** The LLM evaluator has variance. A test that
  fails once may pass 2/3 times. Run any failing test **3 times** before
  deciding it's a real failure — only act on a test that fails **2 or more
  of 3** runs. A single flaky failure gets re-run, not fixed.
- **Don't ping-pong.** If a fix to one rule regresses a test tied to a
  different rule, don't flip the fix back and forth. Read both failing
  transcripts, find the actual instruction conflict, resolve it once. Check
  `experiment_log.md` first — the same conflict may already be documented
  from a prior iteration.
- **Full-suite regression check is still mandatory**, even single-agent: any
  instruction change must be validated against the Officer's **entire** test
  suite, not just the test(s) it was meant to fix — one rule change (e.g. to
  `closing-condition`) can silently break an unrelated test (e.g.
  `handles-missing-policy-number`) that depends on the same wording.
- **Check `experiment_log.md` before proposing a fix.** If a similar
  approach was already tried and reverted, don't repeat it — try a
  different strategy or escalate to the user.

## Fix-Order Priority

When multiple tests fail, fix in this order — earlier categories often
resolve later ones for free:

1. **EVAL_CONFIG_ERROR** — the test JSON itself is broken (wrong field name
   per `CLAUDE.md`'s Test Schema section, malformed `chat_history`, missing
   prior turns for a mid-flow test). Fix first so the pass rate you're
   reading is real signal, not noise.
2. **PLATFORM_ERROR** — API 429/5xx, timeout. Not an agent bug — retry,
   don't diagnose the agent for it.
3. **MISSING_TOOL_CALL / WRONG_TOOL_CALL** — most commonly `end_call` not
   fired when it should be (Officer never wraps up) or fired too early
   (Officer ends the call before intake is genuinely complete, or without
   the Closing Message). Highest-impact category: everything downstream of
   a missing/premature `end_call` fails too.
4. **WRONG_PARAMS** — right tool, wrong arguments.
5. **EXPECTATION_FAIL** — `success_condition` genuinely unmet. Read the
   failure transcript against `success_examples`/`failure_examples` to see
   which side the actual response landed closer to.
6. **HALLUCINATION** — agent states something false or premature (e.g. the
   Officer saying a claim is "lodged" or mentioning a claim number — see
   `CONTEXT.md`'s **Closing Message** entry, neither exists in this flow).
   Trust violation, fix by removing the ungrounded claim from the
   instruction, not by tightening the test.
7. **RULE_CONTRADICTION** — a fix for one rule (e.g. `closing-condition`)
   broke a test tied to a different rule (e.g. `multiple-claims`). See
   "full-suite regression check" above.
8. **TEXT/TONE_MISMATCH** — phrasing, verbosity, or persona drift. Lowest
   priority; often resolves itself once 3–7 are fixed.

**When several tests fail in the same category:** diagnose the simplest one
first — it gives a clean read for the harder ones. If 3+ tests fail for the
same underlying reason (e.g. all missing the `end_call` call), that is
**one fix**, not three — don't diagnose each test independently.

## The Iteration Loop

1. Run the failing test 3x via `elevenlabs agents test <agent_id> --no-ui`
   (or simulate directly per `CLAUDE.md`'s API snippet for a single
   response). Confirm it's a real failure (≥2/3), not evaluator variance.
2. Read the transcript against `success_examples` / `failure_examples`.
   Don't guess at what the evaluator wanted — the examples are the
   calibration.
3. Classify the failure using the Fix-Order Priority categories above.
4. Check `experiment_log.md` for a prior attempt at the same failure mode.
5. Apply the fix to `agent_configs/<Agent>.json` (instruction, tool config,
   or guardrail — whichever the category points to).
6. `elevenlabs agents push` (or `--dry-run` first to preview).
7. Re-run the fixed test 3x, **and** re-run the Officer's full suite
   (full-suite regression check).
8. Append an entry to `experiment_log.md` — what changed, why, which tests
   it was meant to fix, and the before/after result. Do this whether the fix
   worked or not; a documented failed attempt is what prevents ping-pong
   next time.

## Notes on `simulation` and `tool` Tests

All current tests in `test_configs/` are type `llm` (scenario tests). If
`tool` tests (tool-call parameter checks) or `simulation` tests (multi-turn
with a simulated user persona) are added later:

- **`tool` test failures** slot into categories 3–4 above (wrong tool /
  wrong params) — same diagnosis path, just a cleaner signal since there's
  no full-conversation text to wade through.
- **`simulation` test failures** need one extra check before blaming the
  agent: is the simulated persona's `response_guide` too vague or
  uncooperative? A sim user that goes off-script produces a failure that
  looks like an agent bug but is actually an eval-config issue. Rule of
  thumb from Google's methodology: goldens/scenario tests fail because of
  the agent; sims fail because of the agent *or* the sim config — check the
  sim config first.
