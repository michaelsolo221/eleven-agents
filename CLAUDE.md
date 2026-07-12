# Eleven Agents — Repo Guidance

ElevenLabs conversational AI agent config repo. JSON configs in `agent_configs/`, tests in `test_configs/`.

## Test Schema

ElevenLabs CLI test format — NOT generic JSON:

```json
{
    "name": "test name",
    "type": "llm",
    "chat_history": [{"role": "user", "time_in_call_secs": 5, "message": "..."}],
    "success_condition": "what the agent must do (string)",
    "success_examples": [{"response": "...", "type": "success"}],
    "failure_examples": [{"response": "...", "type": "failure"}]
}
```

Common mistakes:
- `evaluation_criteria` wrong field name. Use `success_condition`.
- `success_example` wrong field name. Use `success_examples` (array of objects with `response` + `type`).
- `failure_example` wrong field name. Use `failure_examples` (array).
- Scenario tests evaluate ONE response to the LAST chat_history message only. Agent greets first in fresh conversation. For mid-flow tests, include prior turns in chat_history so agent is already in conversation.

## Agent Config

- New agents: use `elevenlabs agents add "Name" --from-file config.json --no-ui` to create on ElevenLabs and get real ID. Don't put placeholder IDs in `agents.json`.
- `platform_settings.testing.attached_tests` must reference test IDs from `tests.json`. Format: `[{"test_id": "test_xxx"}]`.
- `conversation_config_overrides.text_only` in platform settings: set `false` for voice agents.
- Warnings about non-persisted fields (custom_llm, shareable_token, widget colors) are harmless. All agents get them.
- `post_call_webhook_id` is NOT in that category — the CLI can silently drop it on push (ADR 0002). Always run `python3 scripts/verify-live-tools.py` after pushing an agent that sets one.

## CLI Commands

- `elevenlabs tests push --config-dir test_configs` — push all test configs from directory
- `elevenlabs agents test <agent_id> --no-ui` — run tests for specific agent (no `--all` flag)
- `elevenlabs tests delete --all --no-ui` — clean slate for tests
- `elevenlabs agents push --dry-run` — preview changes

## CI

- `validate` job checks `agent_configs/*.json` only. Add `test_configs/*.json` schema validation.
- `test-pr` job runs on PRs: dry-run push + test all agents.
- `push` and `test` jobs run on main only.

## Sub-Agent Coordination

When delegating implementation:
- Tell sub-agents to read the GitHub issue first (it's the contract).
- Pass `CONTEXT.md` as context — glossary terms prevent re-derivation.
- Don't spawn parallel sub-agents that edit the same file. Make dependencies explicit.
- Sub-agents need the ElevenLabs test schema above. Don't assume they know it.

## Debugging Failing Tests
1. Use ElevenLabs API directly to simulate conversation and see agent's actual response:
   ```bash
   # POST https://api.elevenlabs.io/v1/convai/agents/{agent_id}/simulate
   # API key stored at ~/.elevenlabs/api_key
   ```
2. Don't guess at success_condition wording. Simulate first, then calibrate.
3. Probabilistic: LLM evaluator has variance. Run tests 2-3 times before declaring failure.
