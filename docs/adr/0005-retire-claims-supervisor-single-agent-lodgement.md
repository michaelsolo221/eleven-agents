# Retire the Claims Supervisor — single-agent lodgement

## Problem

The two-agent split (ADR 0002) existed to give the lodgement flow a second, independent completeness check before a claim could be closed out, and to give the officer a well-defined boundary where it had to stop talking. In practice this bought correctness at the cost of a second agent, a second prompt to keep in sync, a `transfer_to_agent` hop whose condition text has already silently regressed once in production (see the Local↔Platform Sync Fields section of `CLAUDE.md`), and a "your claim has been lodged... expect an email with your claim number" promise that doesn't correspond to anything the business actually does downstream.

The business decision: stop promising a claim number or an email, and stop routing every closure through a second agent. Once details are recorded, the claimant is told the team will follow up within two business days — full stop. There's no lodgement confirmation step left to protect with a second agent.

## Decision

The Claims Lodgement Supervisor agent is retired. The Claims Officer ("Amanda") now owns the entire interaction, including the closing step:

- `transfer_to_agent` is removed from the Officer's tool set entirely.
- The Officer's `end_call` restriction (ADR 0003) is widened from two cases to five: Emergency, Wrong Number, Unresponsive Caller, WhatsApp Session Timeout, and **Completed Claim**. It was already the sole owner of the first two; it now owns closure outright rather than handing off for the rest.
- On a Completed Claim, the Officer performs its own completeness check (same field checklist the Supervisor used to re-verify), speaks the Closing Message — "I've recorded your details. Our team will be in touch within two business days." — and calls `end_call` itself. See the Closing Message glossary entry in `CONTEXT.md`.
- The Officer must never say "lodged," mention a claim number, or promise an email — that language belonged to the old Supervisor's closing script and doesn't describe this flow.
- The `Claim completeness before closing` guardrail (the mechanical backstop from ADR 0002/0003, layer 4) now covers *every* `end_call` on a completed claim, not just the old transfer condition, and additionally blocks an `end_call` that skips the Closing Message. It does not apply to the other four closure types, which have their own short, fixed scripts and no completeness dependency.

No channel-specific differentiation was needed for the Closing Message itself — "I've recorded your details, our team will be in touch within two business days" reads naturally on both a voice call and a WhatsApp thread. The channel differences that already existed (name-spelling skipped on text-only, 1-hour WhatsApp inactivity window vs. voice's single unresponsive-prompt) are unchanged; they just now end in the Officer's own `end_call` instead of a transfer.

## Consequences

- `agent_configs/Claims-Lodgement-Supervisor.json` deleted; its live agent and 3 attached tests deleted from the platform; its `agents.json` entry removed.
- `agent_configs/Claims-Lodgement-Officer.json`: `transfer_to_agent` tool removed; `end-call-restriction`, `closing-condition` (renamed from `transfer-condition`), and a new `closing-message` rule added; `post-transfer-silence` and `no-lodgement-language` rules replaced by `closing-message`; `unresponsive-caller` and `whatsapp-timeout` rules now call `end_call` directly; eval criterion `transfers-to-supervisor-when-complete` replaced by `wraps-up-and-ends-call-when-complete`.
- 3 Supervisor test configs deleted. Officer test configs renamed/rewritten: `Claims-Lodgement-Officer-completes-claim-and-ends-call.json` (was `-transfers-to-supervisor-when-complete`), `Claims-Lodgement-Officer-does-not-close-with-missing-fields.json` (was `-does-not-lodge-or-end-call`, inverted — the Officer is now expected to close when genuinely complete, so the test instead asserts it doesn't close with a field still missing). Several other Officer tests had their success conditions' "or transfer to the Supervisor" fallback branches removed.
- `CONTEXT.md`: **Claims Supervisor**, **Transfer**, and **Supervisor Review** glossary entries removed; **Claims Officer** rewritten to reflect sole ownership of closure; new **Closing Message** entry added; **Completeness Guardrail** updated to describe single-agent scope.
- ADR 0002 and ADR 0003 are **not** deleted — they remain the historical record of why the two-agent split existed and what it cost to build. This ADR supersedes their architectural conclusion, not their content.
- `docs/agents/claims-lodgement.tdd.md` Architecture/Tools/Routing sections and Coverage Map updated to match.

## Rollout incident: two live-state bugs discovered during migration (2026-07-26)

`elevenlabs agents push` reported success but left the live agent's `tools` array with **both** `end_call` and `transfer_to_agent`, even though `transfer_to_agent` had been removed from the local config — the CLI silently failed to delete it, the reverse direction of the already-known "CLI silently drops declared tools" bug (ADR 0002). `scripts/verify-live-tools.py` didn't catch it: it only checked that locally-declared tools were present live, never that the live agent had no *extra*, undeclared ones. Fixed by a direct `PATCH conversation_config.agent.prompt.tools` with just the intended tool list, and extended `verify-live-tools.py` to fail on undeclared live tools too.

**Also discovered: the same stale-`transfer_to_agent` bug reproduces on ephemeral PR-test branches, and appears unfixable via the same PATCH there.** CI's `pr-test` job (which pushes to an isolated `pr-<number>` branch and runs `verify-live-tools.py --branch-name`) failed on this PR for the identical reason — the branch-scoped push also left `transfer_to_agent` live. Unlike the main/production agent, neither a repeated `elevenlabs agents push --branch` nor a direct `PATCH ...?branch_id=...` with the same tools-only payload that fixed production actually changed the branch's live tools array (confirmed via a follow-up GET with the same `branch_id`) — `last_committed_at` advanced but the tools array didn't change, suggesting partial nested-field writes may not apply the same way to non-main branches as they do to the default branch. Not resolved as of this PR's merge; the production agent itself is independently verified correct (`verify-live-tools.py` clean, no `--branch-name` flag), so this is a CI-test-infrastructure gap on an ephemeral scratch branch, not a live-behavior regression. Needs its own investigation — possibly a branch-write quirk worth raising with ElevenLabs support, separate from the tools-array bug itself.

Separately, the orphaned `workflow` block from Known Issue #1 (`docs/agents/claims-lodgement.tdd.md` §9) turned out not to be inert: its `officer_node.additional_prompt` still read *"You must not call end_call yourself... A supervisor step reviews completeness independently before the call ends"* — directly contradicting this ADR's design — and was intermittently influencing responses despite `edges: {}` supposedly disconnecting the node from conversation routing (this is what produced the flaky ~1/3 failures on several tests during rollout: `handles-express-property-claim` fell back to calling `transfer_to_agent`, others avoided `end_call` outright). Fixed by PATCHing `workflow.nodes.officer_node.additional_prompt` and `workflow.nodes.supervisor_node.additional_prompt` to empty strings, leaving `edges: {}` and node structure otherwise untouched. The workflow block itself is still undeletable (per Known Issue #1's prior finding that `PATCH {"workflow": null}` is silently ignored) — only its leftover instruction text was cleared. Both PATCHes were confirmed via a subsequent live re-fetch and a clean `verify-live-tools.py` run.

## Alternatives considered

### Keep the Supervisor, just change its closing script

Rejected. If the Supervisor's only remaining job is to speak a different closing line and re-run the same completeness check the Officer already runs, it's a second agent doing the first agent's job over again for no independent value — the entire point of ADR 0002 was an independent transcript re-read protecting a *real* lodgement confirmation (claim number, email). With that promise gone, the second check protects nothing a same-agent guardrail can't equally protect.

### Keep `transfer_to_agent` for Unresponsive Caller / WhatsApp Timeout only, drop it for completed claims

Rejected. With no Supervisor left to transfer to, this isn't meaningfully different from having the Officer call `end_call` directly — it would just be a transfer to nowhere. Simpler to have the Officer own all five closure types outright.
