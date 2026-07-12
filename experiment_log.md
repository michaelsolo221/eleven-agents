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
