# Eleven Agents — Repo Guidance

ElevenLabs conversational AI agent config repo. JSON configs in `agent_configs/`, tests in `test_configs/`.

## Local Dev Tooling

- ElevenLabs CLI v0.5.5 at `/opt/homebrew/bin/elevenlabs`. `ELEVENLABS_API_KEY` is set in the environment.
- **Pre-push**: `make validate` (structural checks) then `make dry-run` (preview changes).
- **Full CI can be run locally**: `make push` (deploy), `python3 scripts/verify-live-tools.py` (integrity), `make test` (18 LLM agent tests).
- **Key Makefile targets**: `validate`, `dry-run`, `push`, `test`, `server-check`, `server-test`. Run `make help` for full list.

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

## TDD (Technical Design Document)

Each flow's living spec lives at `docs/agents/<flow>.tdd.md` — architecture,
tools, routing, guardrails, and a Coverage Map linking PRD stories to
`test_configs/*.json` with priority/severity/gaps. See
`docs/agents/tdd-guide.md` for the methodology and
`docs/agents/claims-lodgement.tdd.md` for the worked example. Update the
Coverage Map before adding/removing tests; update Architecture/Tools/Routing
before merging an `agent_configs/*.json` change that alters behavior.

## Agent Config

- New agents: use `elevenlabs agents add "Name" --from-file config.json --no-ui` to create on ElevenLabs and get real ID. Don't put placeholder IDs in `agents.json`.
- `platform_settings.testing.attached_tests` must reference test IDs from `tests.json`. Format: `[{"test_id": "test_xxx"}]`.
- `conversation_config_overrides.text_only` in platform settings: set `false` for voice agents.
- Warnings about non-persisted fields (custom_llm, shareable_token, widget colors) are harmless. All agents get them.
- `post_call_webhook_id` is NOT in that category — the CLI can silently drop it on push (ADR 0002). Always run `python3 scripts/verify-live-tools.py` after pushing an agent that sets one.

## CLI Commands

CLI is assumed installed (`elevenlabs --version`; if missing, `make install`). Use it over manual API calls or hand-written IDs — it's the source of truth for what's actually live.

- `elevenlabs tests push --config-dir test_configs` — push all test configs from directory
- `elevenlabs agents test <agent_id> --no-ui` — run tests for specific agent (no `--all` flag)
- `elevenlabs tests delete --all --no-ui` — clean slate for tests
- `elevenlabs agents push --dry-run` — preview changes

### New/edited test workflow (required order)

Adding a test config file is not enough — it must be pushed and attached, or it silently never runs (see #29 and its repeat in PR #35):

1. Write the test config in `test_configs/`.
2. `elevenlabs tests push --config-dir test_configs` — get the real `test_id` back. Never hand-write a `test_xxx` ID into `tests.json`.
3. Add that real ID to the target agent's `platform_settings.testing.attached_tests` in `agent_configs/*.json`.
4. `elevenlabs agents push` the agent config.
5. `python3 scripts/verify-live-tools.py` — confirms attached tests and `post_call_webhook_id` match what's live.

## CI

Defined in `.github/workflows/agents.yml`. Four jobs:

- `validate` — runs on every push and PR. Runs `scripts/validate-configs.py`, which checks `agent_configs/*.json`, `tests.json`, `test_configs/*.json`, orphaned files, and that `attached_tests` cross-references `tests.json`.
- `pr-test` — runs on PRs only (not main), after `validate`. Pushes agent configs to an isolated `pr-<number>` ElevenLabs branch, then runs `verify-live-tools.py` and API-based tests against that branch via `test-pr-branch.py`. Blocks merge on failure. Uses `elevenlabs agents push --branch` (CLI 0.5.5+) and `POST /v1/convai/agents/{id}/run-tests` with `branch_id`.
- `push` and `test` — main only (`if: github.ref == 'refs/heads/main' && github.event_name == 'push'`). Push agents to production and run the full CLI-based test suite.

A separate workflow (`.github/workflows/pr-cleanup.yml`) archives `pr-*` branches when a PR is merged or closed.

## Server (`server/`)

FastAPI webhook receiver (+ future email dispatch), per ADR 0006. Dependency-managed with `uv`.

- **Verify third-party wire formats against real docs, not just your own tests** — a test fixture built on the same wrong assumption as the code under test still passes. Discovered 2026-07-26: `security.py` parsed the ElevenLabs signature as `v1`; the real header uses `v0`. Tests stayed green because `test_security.py` built headers with the same wrong key — every real webhook call would have 401'd in production.
- **HMAC checks need a replay/timestamp window, not just a valid-hash check.** `verify_signature` enforces `TIMESTAMP_TOLERANCE_SECONDS` (30 min) for this reason — keep it for any future signature verification added here.

## Local↔Platform Sync Fields

Fields like `attached_tests`, tool names, `post_call_webhook_id`, and a `transfer_to_agent` tool's `condition` text all have the same failure mode: the CLI can silently drop them on push (ADR 0002), and CI's `push`/`test` jobs are main-only, so nothing confirms live state pre-merge (see CI section above). The `pr-test` job (added for #36/#37) closes this gap for PRs — it pushes to an isolated branch, verifies, and tests pre-merge. Main-only checks (`push`/`test` jobs) still apply post-merge.

- `condition` is a sharper case of the drop than the others: the `transfer_to_agent` *tool itself* stays present (so a name-presence check passes), but the nested `condition` string silently reverts to a stale value. Discovered 2026-07-22 — the officer's transfer condition had been stuck on pre-2026-07-12 wording for over a week despite multiple local edits and pushes, because the CLI never actually sent that field. Fixed by a direct `PATCH /v1/convai/agents/{id}` with just `conversation_config.agent.prompt.tools` (same workaround as ADR 0002/0003's workflow PATCH). `scripts/verify-live-tools.py` now diffs local vs. live condition text per transfer target, not just tool presence.

- Adding a **new** field of this kind: extend `scripts/validate-configs.py` (local cross-reference check) and `scripts/verify-live-tools.py` (live-state check) in the **same commit/PR** that introduces the field. Don't ship the field first and the check later — that gap is exactly how #29 and PR #35 happened.
- **Definition of done** for any change touching a synced field: run `python3 scripts/verify-live-tools.py` (with `ELEVENLABS_API_KEY` set) yourself before calling the work finished. Don't wait for CI or a review to catch it — CI only checks this post-merge.
- Note the residual gap even with both checks: a hand-written ID that's *consistent* across `tests.json` and `attached_tests` (same fake string in both) still passes the local check — only the live check catches a genuinely fake/unpushed ID. Prefer IDs that came from a real `elevenlabs tests push`/`agents add` output, never typed by hand.

## Sub-Agent Coordination

When delegating implementation:
- Tell sub-agents to read the GitHub issue first (it's the contract).
- Pass `CONTEXT.md` as context — glossary terms prevent re-derivation.
- Don't spawn parallel sub-agents that edit the same file. Make dependencies explicit.
- Sub-agents need the ElevenLabs test schema above. Don't assume they know it.

## Debugging Failing Tests

Full methodology: `docs/agents/debugging-guide.md`. Log every fix attempt
(worked or not) in `experiment_log.md` — prevents ping-ponging between
conflicting fixes.

1. Use ElevenLabs API directly to simulate conversation and see agent's actual response:
   ```bash
   # POST https://api.elevenlabs.io/v1/convai/agents/{agent_id}/simulate
   # API key stored at ~/.elevenlabs/api_key
   ```
2. Don't guess at success_condition wording. Simulate first, then calibrate.
3. Probabilistic: LLM evaluator has variance. Run tests 3x; only act on a
   test that fails ≥2/3 runs.
4. **Fix order** (earlier categories cascade-fix later ones — see full guide
   for detail): eval-config error → platform error → missing/wrong tool call
   (esp. `end_call`) → wrong params → expectation fail → hallucination →
   rule contradiction → text/tone.
5. **Full-suite regression check is mandatory**: any instruction change must
   be re-validated against the Officer's entire test suite before calling a
   fix done — a change to one rule can silently break a test tied to a
   different rule. (Single agent as of ADR 0005 — see `docs/agents/debugging-guide.md`
   if a second agent is ever reintroduced.)
## Python Server (`server/`)

FastAPI post-call webhook receiver and email dispatch microservice hosted on Coolify (`uv` toolchain, Python 3.13).

- **Dev & Test**: `make server-check` (ruff + mypy strict) and `make server-test` (pytest).
- **Local Server**: `cd server && uv run uvicorn main:app --reload`
- **Security**: Validate HMAC signatures via `verify_signature` against `ElevenLabs-Signature` (`t=<ts>,v0=<hash>`) with `TIMESTAMP_TOLERANCE_SECONDS = 1800` (30-min replay window) using `hmac.compare_digest`. Log fail-closed security events at `DEBUG`/`WARNING`.
