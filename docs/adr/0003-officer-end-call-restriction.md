# Officer end-call restriction and relaxed name spelling

## Problem

Two related issues observed in the most recent production conversation (conv_7401kxa80vzmfbdrdz33vav4x3jf, 2026-07-12):

### 1. Officer called `end_call` after a successful transfer

The officer correctly called `transfer_to_agent` after collecting all fields, the transfer succeeded (routing to the Supervisor), but the officer then continued speaking — declaring "Your claim has been lodged. Expect an email within 1 business day" — and called `end_call` itself. The Supervisor never received the conversation. 0 of 4 recent officer calls reached the Supervisor.

Root cause: the officer's prompt instructed it not to `end_call` for completed claims, but the model ignored this. ADR 0002 already acknowledged this risk ("Officer's prompt instruction to transfer rather than end the call on claim completion can be ignored or fired early — observed in testing").

### 2. Name spelling verification was overly strict

The evaluation criterion `verifies-name-spelling` required the officer to *ask the claimant to spell* their name. When the officer guessed "M-I-C-H-A-E-L?" and the claimant confirmed, this was marked FAILURE because the officer, not the claimant, initiated the spelling. In practice, agent-guessing + claimant-confirming achieves the same outcome with better UX.

## Decision

### End-call restriction tightened

The officer now:

- **May call `end_call` only for Emergency (caller in danger → redirect to 000) and Wrong Number (caller dialled wrong number)**
- **Must transfer to the Supervisor for ALL other call-ending scenarios:** Unresponsive Caller, WhatsApp Session Timeout, and completed claims
- **Must not speak or call any tools after a successful transfer** — the supervisor handles everything from that point

The Supervisor was updated to handle non-claim transfers: it reads the conversation history, detects Unresponsive/Timeout scenarios, and calls `end_call` immediately with no message.

This creates a single invariant: only the Supervisor may `end_call` for claim-related or session-timeout scenarios. The officer's `end_call` usage is restricted to two narrow, well-defined cases.

### Name spelling relaxed

Name spelling confirmation now accepts any method where the claimant explicitly confirms the spelling:

- Officer asks "could you spell your name?" → valid
- Officer guesses "is that M-I-C-H-A-E-L?" and claimant confirms → valid
- Officer guesses, claimant corrects → valid (the correction IS the confirmation)
- On text-only (WhatsApp), no spelling confirmation is needed — the typed text is exact

The evaluation criterion `verifies-name-spelling` was renamed to `confirms-name-spelling` and the prompt was relaxed. The `collects-all-required-fields` criterion now accepts confirmation-by-guess as meeting the name spelling requirement.

## Alternatives considered

### Strip `end_call` from the officer entirely

Rejected. Would break Emergency redirect (caller in danger needs immediate 000 instruction + call end, not a transfer hop) and Wrong Number (user-hostile to transfer just to say goodbye). ADR 0002's conclusion on this point stands.

### Keep Unresponsive/Timeout as officer `end_call` cases

Rejected. The officer already proved unreliable at following its `end_call` prompt restrictions. Reducing the officer's `end_call` surface area to only Emergency and Wrong Number — two scenarios with very distinct, hard-to-confuse triggers — makes prompt adherence more reliable.

### Keep strict "ask to spell" requirement

Rejected. Agent-guessing + claimant-confirming achieves the same correctness guarantee with better UX. The claimant is still explicitly confirming the spelling; who initiates the spelling doesn't affect data quality.

## Consequences

- Officer prompt now has explicit "After Transferring" and "When You May End the Call Yourself" sections
- Supervisor prompt now has a "First — Determine the Transfer Type" section handling non-claim transfers
- New test config: `Claims-Lodgement-Officer-does-not-lodge-or-end-call.json`
- Transfer test updated with stronger failure examples (claim lodged language, end_call)
- 3 evaluation criteria updated: `verifies-name-spelling` → `confirms-name-spelling`, `collects-all-required-fields` relaxed, `transfers-to-supervisor-when-complete` strengthened
- CONTEXT.md glossary entries updated for Claims Officer, Transfer, Name Spelling Confirmation, and Contact Person
- Guardrail audit confirmed: the `Claim completeness before closing` guardrail is in retry (block) mode — the prompt, not the guardrail, was the gap
