# Debugging Failing Tests — Methodology

Adapted from Google's CXAS-SCRAPI `agent-foundry` debug methodology
(https://googlecloudplatform.github.io/cxas-scrapi/), ported to ElevenLabs'
`llm` / `tool` / `simulation` test types and this repo's two-agent
(Claims-Lodgement-Officer → Claims-Lodgement-Supervisor) architecture.

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
- **Don't ping-pong.** If a fix to the Officer's instructions regresses a
  Supervisor test (or vice versa), don't flip the fix back and forth. Read
  both failing transcripts, find the actual instruction conflict, resolve it
  once. Check `experiment_log.md` first — the same conflict may already be
  documented from a prior iteration.
- **Cross-agent regression check is mandatory.** This repo has two agents
  that hand off via `transfer_to_agent` (see `CONTEXT.md` → "Transfer").
  Any instruction change to *either* agent must be validated against
  **both** agents' full test suites — a Supervisor fix can silently break
  an Officer test that depends on wording the Officer relies on the
  Supervisor to echo back, and vice versa.
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
3. **MISSING_TOOL_CALL / WRONG_TOOL_CALL** — most commonly `transfer_to_agent`
   not fired when it should be (Officer never hands off) or fired too early
   (Officer transfers before intake is genuinely complete). Highest-impact
   category: everything downstream of a missing transfer fails too.
4. **WRONG_PARAMS** — right tool, wrong arguments.
5. **EXPECTATION_FAIL** — `success_condition` genuinely unmet. Read the
   failure transcript against `success_examples`/`failure_examples` to see
   which side the actual response landed closer to.
6. **HALLUCINATION** — agent states something false or premature (e.g. the
   Officer saying a claim is lodged — see `CONTEXT.md`, only the Supervisor
   may say that). Trust violation, fix by removing the ungrounded claim from
   the instruction, not by tightening the test.
7. **CROSS_AGENT_CONTRADICTION** — a fix for one agent's test broke the
   other's. See "Cross-agent regression check" above.
8. **TEXT/TONE_MISMATCH** — phrasing, verbosity, or persona drift. Lowest
   priority; often resolves itself once 3–7 are fixed.

**When several tests fail in the same category:** diagnose the simplest one
first — it gives a clean read for the harder ones. If 3+ tests fail for the
same underlying reason (e.g. all missing the `transfer_to_agent` call), that
is **one fix**, not three — don't diagnose each test independently.

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
7. Re-run the fixed test 3x, **and** re-run the *other* agent's full suite
   (cross-agent regression check).
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
