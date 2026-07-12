# Technical Design Document (TDD) Guide

Adapted from Google's CXAS-SCRAPI `agent-foundry` TDD methodology
(https://googlecloudplatform.github.io/cxas-scrapi/), ported to ElevenLabs
agent configs and this repo's Officer/Supervisor architecture.

A TDD (`docs/agents/<flow>.tdd.md`) is the living source of truth for one
conversational flow — its architecture and its eval coverage. Write it once
(usually by reverse-engineering the existing agent configs + PRD, since most
agents in this repo predate a TDD), then keep it in sync as the agent
evolves. See `docs/agents/claims-lodgement.tdd.md` for a worked example.

## When to Write One

| Situation | Approach |
|---|---|
| New agent, has a PRD | Write Architecture from the PRD's Implementation Decisions, then derive the Coverage Map from the User Stories |
| Existing agent, no TDD | Reverse-engineer from `agent_configs/*.json` + `test_configs/*.json` + the PRD, if one exists |
| Existing agent, has a TDD | Verify it's still accurate (configs drift faster than docs), then use as-is |

## Sections

### Agent Design

1. **Architecture** — every registered agent involved, how they hand off,
   and any dead/inactive config found along the way (see the Known Issues
   note below — this is not hypothetical in this repo).
2. **Tools** — every tool in each agent's `tools[]`/`built_in_tools`, real
   name, type (`system` / `webhook` / `client`), purpose, and which agent(s)
   it's attached to.
3. **Routing Logic** — how a conversation moves between agents:
   `transfer_to_agent` conditions, `workflow` edges (if any are actually
   live — see below), guardrail-triggered `end_call`.
4. **Session/Data Variables** — every field in `platform_settings.data_collection`,
   whether it's required or best-effort, and which claim type(s) it applies to.
5. **Guardrails** — ElevenLabs' equivalent of GECX callbacks: everything
   under `platform_settings.guardrails` (content filters, `custom` LLM-judged
   rules) plus prompt-level guardrail sections. Note execution mode
   (`blocking` vs `streaming`) and `trigger_action`.

### Eval Design

6. **Coverage Map** — one row per PRD user story (or per distinct behavior,
   if there's no PRD):

   | Story | Behavior | Eval Type | Test File | Priority | Severity | Tags |
   |---|---|---|---|---|---|---|

   **Eval type decision** (ElevenLabs has three: `llm`, `tool`, `simulation`):
   - **`llm`** (scenario test) — a single decisive response, evaluated
     against `success_condition` via LLM judge, with `chat_history` scripting
     the setup. Use when the behavior IS one response: a guardrail trigger,
     a redirect, a transfer decision, a closing message. This is what most
     of this repo's tests are, and per `CLAUDE.md` it only ever judges the
     response to the *last* `chat_history` turn — it cannot verify anything
     about turns 1 through N-1 except that they set up the right context.
   - **`tool`** — use when the correctness of specific tool-call *parameters*
     matters more than the surrounding text (e.g., a webhook receiving
     structured data). Neither agent in this repo has a data-capturing
     webhook tool yet (claim data is extracted from the transcript webhook
     post-call, per PRD's Out of Scope) — so no `tool` tests exist here yet.
     If a structured webhook tool is ever added, its parameter correctness
     belongs in a `tool` test, not folded into an `llm` test's
     `success_condition`.
   - **`simulation`** — use when the behavior spans *many* turns and no
     single response proves it: does the Officer ask fields in a sensible
     order without repeating itself across a full guided-flow conversation
     from greeting to hand-off? An `llm` test literally cannot check this —
     it only ever sees the last turn. **This repo currently has zero
     `simulation` tests**, and all 16 Officer `llm` tests are mid-conversation
     snapshots (chat_history primes prior turns; only the next response is
     judged) — true start-to-finish flow correctness is an untested gap. See
     Known Issues in the worked example TDD.

7. **Test Data** — ElevenLabs `llm`/`simulation` tests don't have GECX-style
   `session_parameters`; claimant details live inline in each test's
   `chat_history`. List the fake registration numbers, addresses, names,
   and contact details already used across `test_configs/` here so new tests
   reuse them instead of inventing fresh fake data every time (keeps
   transcripts easy to diff/compare when debugging).

### Tracking

8. **Pass Rate History** — table updated after each CI test run (`scripts/run-tests.sh`
   output). First row is the baseline at TDD creation time.
9. **Known Issues** — anything found during reverse-engineering that doesn't
   match the PRD or the ADRs, plus genuine coverage gaps from the Coverage Map.
10. **Changelog** — dated log of TDD edits, cross-referenced to the commit
    or PR that motivated them.

## Reverse-Engineering Rule

**Write every section from the real `agent_configs/*.json` data — never
assume the PRD or `CONTEXT.md` still matches the shipped config.** This repo
has a concrete example of why: `docs/adr/0002-claims-supervisor-as-separate-agent.md`
documents switching the Officer/Supervisor handoff from `workflow` nodes to
`transfer_to_agent` because the workflow-node edge was verified not to work.
Commit `fda75cc` removed the `workflow` block for exactly that reason. But
the *current* `agent_configs/Claims-Lodgement-Officer.json` has a `workflow`
block again — reintroduced by the later "split into a separate agent" commit
— containing a second, drifting copy of the Supervisor's prompt. Reading the
ADR alone would miss this; only reading the current JSON catches it. Treat
this as the standing example of why the reverse-engineering step is not
optional busywork.

## Keeping the TDD Current

- Requirement changes → update the PRD first, then the TDD's Coverage Map,
  then `test_configs/`.
- Agent behavior changes (`agent_configs/*.json` edited) → update
  Architecture/Tools/Routing/Guardrails to match before merging.
- After each CI run → append to Pass Rate History.
- After a debugging iteration (see `docs/agents/debugging-guide.md`) →
  the Changelog entry and the `experiment_log.md` entry should reference
  each other.
