# TDD: CGU Claims Lodgement (Officer)

Reverse-engineered from `agent_configs/Claims-Lodgement-Officer.json`,
`test_configs/*.json`, `docs/prd/001-claims-lodgement-agent.md`, and the ADRs
in `docs/adr/`. See `docs/agents/tdd-guide.md` for the methodology and
section definitions. Domain terms below (Claim, Claimant, Risk Asset, etc.)
are defined in `CONTEXT.md`.

**Written from the current shipped config, not from `CONTEXT.md` or the
ADRs alone** — see Known Issues #1 for a case where the two disagree.

**Historical note:** until `docs/adr/0005-retire-claims-supervisor-single-agent-lodgement.md`,
this flow was split across two registered agents (Officer + Supervisor),
connected by `transfer_to_agent`. ADR 0002/0003 document why that shape was
chosen and what it cost; ADR 0005 documents why it was retired. This TDD
describes the current, single-agent shape only — see those ADRs for the
prior design.

## 1. Architecture

One registered ElevenLabs agent, `agents.json`:

- **Claims Lodgement Officer** ("Amanda") — opens every conversation and
  owns it end to end: the greeting, claim-type branch (vehicle/property),
  guided-flow and express-lodgement field collection, name-spelling
  confirmation, every guardrail (emergency, non-claims redirect, wrong
  number, small talk, unresponsive caller, WhatsApp timeout), its own
  completeness confirmation, the Closing Message, and call termination.
  May call `end_call` for: Emergency, Wrong Number, Unresponsive Caller,
  WhatsApp Session Timeout, and Completed Claim. Never declares a claim
  "lodged," never mentions a claim number or an email confirmation — the
  Closing Message ("I've recorded your details. Our team will be in touch
  within two business days.") is the entire promise. See `CONTEXT.md`'s
  **Closing Message** and **Completeness Guardrail** entries.

**Layered defense** (reduced from ADR 0002's four layers to two, since the
independent second-agent re-read no longer exists — see ADR 0005 for why
that was judged an acceptable trade):
1. Officer's own silent completeness self-check, performed while collecting
   fields and again immediately before delivering the Closing Message.
2. `Claim completeness before closing` custom guardrail (blocking) — forces
   a retry if a response ends the call or declares a claim complete while a
   required field is verifiably absent from the transcript, or skips the
   Closing Message before a completed-claim `end_call`. Does not apply to
   Emergency, Wrong Number, Unresponsive Caller, or WhatsApp Timeout, which
   have their own fixed short scripts and no completeness dependency.

Layer 1 alone is not reliable (this is the same risk ADR 0002 flagged for
the old officer-side self-check); layer 2 is the only mechanical check left
in the stack.

| Tool | Type | Purpose |
|---|---|---|
| `end_call` | `system` | Emergency, Wrong Number, Unresponsive Caller, WhatsApp Timeout, or Completed Claim (after the Closing Message). Never for a claim still missing required fields — enforced by prompt + guardrail. |

No `transfer_to_agent` tool — removed under ADR 0005.

No webhook tool captures structured claim data — the backend parses the
post-call transcript webhook (`platform_settings.workspace_overrides.webhooks`,
event `transcript`). Payload structure is explicitly out of scope (PRD,
tracked in issue #2). This is why there are no `tool`-type tests in this
suite; all coverage is `llm`-type conversational eval.

## 2. Routing

Single agent, no cross-agent handoff. A second claim in the same session
does not restart the conversation — the Officer continues in place,
collecting the next claim's fields before delivering a single Closing
Message and ending the call (story 15; see the `multiple-claims` prompt
rule).

## 3. Closing Condition

Before delivering the Closing Message or calling `end_call` for a completed
claim, the Officer's own `closing-condition` rule requires every one of the
following to have been *explicitly and separately* stated by the claimant,
earlier in the same conversation: claim type; policy number (or asked and
unavailable — best-effort only); what happened; date/time; registration or
address (matching claim type); incident location (vehicle only); a contact
method; first name; last name; **and**, on a *voice* call, the spelling of
both names explicitly confirmed by the claimant in any form (agent guessing
+ claimant confirming is valid). On a *text-only* conversation (e.g.
WhatsApp), the typed name is exact and no spelling confirmation is required.
Any doubt on any item → treat as missing, ask for it, do not close.

## 4. Session / Data Variables

`platform_settings.data_collection`:

| Field | Type | Required for | Notes |
|---|---|---|---|
| `claim_type` | string | all | vehicle \| property |
| `policy_number` | string | — | best-effort only; headless claims accepted |
| `what_happened` | string | all | free text |
| `incident_datetime` | string | all | |
| `vehicle_registration` | string | vehicle | |
| `property_address` | string | property | doubles as incident location |
| `incident_location` | string | vehicle only | property claims use `property_address` instead |
| `contact_method` | string | all | email OR phone, either satisfies |
| `first_name` / `last_name` | string | all | on voice calls, spelling must be *explicitly confirmed by the claimant*, not just stated (any confirmation method — agent guessing + claimant confirming is valid); on text-only conversations (e.g. WhatsApp) the typed name is exact and spelling confirmation must NOT be requested |
| `nominated_representative` | boolean | — | true when caller is not the policyholder |

## 5. Guardrails

`platform_settings.guardrails`:

- `focus` + `prompt_injection` — enabled, defaults.
- `content` — `harassment` and `profanity` at threshold 0.5, execution mode
  `streaming`, `trigger_action: end_call`. `sexual` / `violence` / `self_harm`
  / `religion_or_politics` / `medical_and_legal_information` disabled.
- `custom` → **Claim completeness before closing** (blocking, model
  `gemini-2.5-flash-lite`, `history_message_count: 0`) — blocks and retries
  any response that ends the call or declares a claim complete for a
  Completed Claim closure while a required field is verifiably absent from
  the transcript, or that skips the Closing Message before `end_call`. Name
  spelling only counts as a required field on voice calls; on text-only
  (WhatsApp) conversations the typed name is exact and the guardrail does
  not require a spelling exchange. Exempt: Emergency, Wrong Number,
  Unresponsive Caller, WhatsApp Timeout. Feedback message quotes
  `{{trigger_reason}}` back to the agent.

Prompt-level guardrail sections (not a platform guardrail — enforced by
instruction text): Emergency, Non-Claims Inquiries, Wrong Number, Small
Talk, Unresponsive Caller, WhatsApp Session Timeout, Mid-Lodgement Hang-Up.

**Confirmed 2026-07-26 (was previously an open question): guardrails do NOT
fire in CLI/API test-mode runs.** Tool call results in test-mode responses
consistently show `"is_blocked": false` and `"reason": "Skipping tool call
in test mode"`, including on responses that a live conversation's
`Claim completeness before closing` guardrail should have blocked (e.g. an
`end_call` attempt with a required field genuinely absent). This means the
completeness guardrail — the one mechanical layer in the stack (§1) — has
**zero regression coverage** from `test_configs/*.json`, confirmed, not
just suspected. It can only be exercised via a real `simulate-conversation`
or live call. Test-mode `llm` evals are therefore evaluating the raw,
first-pass LLM judgment only, with no corrective retry loop — this is why
tests near the completeness boundary (spelling not yet confirmed, terse
"what happened" text) read as more failure-prone in CI than the agent
actually is live, where the guardrail would catch and retry a bad attempt
before it reaches the caller. See `docs/adr/0005-...md`'s rollout incident
section for the investigation.

**Test-mode channel pinning:** `llm`-type tests have no explicit
voice/text-only signal by default — `{{system__is_text_only}}` resolves
inconsistently run to run, which made every spelling-confirmation-dependent
test flaky before this was found. `conversation_initiation_source` (e.g.
`"twilio"`, `"whatsapp"`, `"widget"` — see `ConversationInitiationSource` in
the CLI's bundled SDK types) is a real, CLI-supported per-test field that
pins the simulated channel deterministically. Not documented anywhere in
ElevenLabs' CLI docs at time of writing; discovered by inspecting the
bundled SDK's TypeScript definitions. Voice-dependent tests in this repo
now set `"conversation_initiation_source": "twilio"`; the WhatsApp-timeout
test sets `"whatsapp"`. Tests without a channel-dependent assertion are left
unset.

## 6. Coverage Map

Priority: **P0** (safety/compliance-critical) · **P1** (core UX) · **P2**
(polish). Severity: **NO-GO** (ships broken = incident) · **HIGH** ·
**MEDIUM** · **LOW**. All existing tests are type `llm` (single-response,
judged against the *last* `chat_history` turn only — see
`docs/agents/tdd-guide.md`).

| # | Story (PRD) | Eval Type | Test File | Priority | Severity | Tags |
|---|---|---|---|---|---|---|
| 1–2 | Lodge vehicle claim, registration as asset ID | `llm` | `collects-vehicle-claim-via-guided-flow` | P1 | HIGH | vehicle, guided-flow |
| 3–5 | Incident location, date/time, contact method (vehicle) | `llm` | `collects-vehicle-claim-via-guided-flow` (implicit — fields present in setup, not individually asserted) | P2 | MEDIUM | vehicle, guided-flow, PARTIAL |
| 6 | Confirm name spelling | `llm` | `collects-*-via-guided-flow`, `handles-express-*-claim`, `completes-claim-and-ends-call` | P0 | HIGH | name-spelling |
| 7–8 | Property claim via address; address doubles as incident location | `llm` | `collects-property-claim-via-guided-flow` | P1 | HIGH | property, guided-flow |
| 9–10 | Express lodgement dump; name spelling still verified | `llm` | `handles-express-property-claim`, `handles-express-vehicle-claim` | P1 | HIGH | express |
| 11 | Guided flow, one field at a time | `llm` | `collects-*-via-guided-flow` | P1 | MEDIUM | guided-flow |
| 12 | Ask vehicle/property upfront | *(none)* | — platform `evaluation.criteria: asks-vehicle-or-property-upfront` exists but is analysis-only scoring, not a CI-gating test | P1 | MEDIUM | **GAP** |
| 13 | Missing policy number (headless claim) | `llm` | `handles-missing-policy-number` | P0 | HIGH | best-effort-field |
| 14 | 2-attempt cap then wrap up anyway | `llm` | `wraps-up-after-2-attempt-retry-cap` | P1 | HIGH | retry-cap |
| 15 | Multiple claims, one session | `llm` | `handles-multiple-claims` | P1 | MEDIUM | multi-claim |
| 16–17 | Nominated representative | `llm` | `handles-nominated-representative` | P1 | MEDIUM | nominated-rep |
| 18 | Emergency → 000, end call | `llm` | `handles-emergency-redirect` + negative case `treats-past-events-as-valid-claims` | P0 | NO-GO | emergency, safety |
| 19–20 | Claim status redirect, offer new claim | `llm` | `redirects-claim-status-inquiry`¹ | P1 | MEDIUM | redirect |
| 21–22 | Unresponsive caller: prompt, then end call | `llm` | `handles-unresponsive-caller` | P0 | HIGH | safety, unresponsive |
| 23 | Post-completion Closing Message | `llm` | `completes-claim-and-ends-call` | P0 | HIGH | closing-message |
| 24 | Hang-up mid-lodgement → webhook fires with partial data | *(none — untestable as an `llm`/`simulation` chat eval)* | — | P1 | HIGH | **GAP — different remediation path**, see below |
| 25 | WhatsApp session timeout (1hr) | `llm` | `handles-whatsapp-session-timeout` | P1 | MEDIUM | whatsapp, timeout |
| 26 | Wrong number | `llm` | `handles-wrong-number` | P1 | MEDIUM | redirect |
| 27 | Small talk, steer back | `llm` | `steers-small-talk` | P2 | LOW | small-talk |
| 29 | WhatsApp channel, full lodgement happy path | *(none — only the timeout edge case is WhatsApp-specific)* | — | P2 | LOW | **GAP** — channel |
| 30 | Phone channel | *(implicit — default context of all tests)* | — | — | — | covered generically |
| 31 | Switch between text and voice mid-conversation | *(none)* | — | P2 | LOW | **GAP** — channel |
| — | Officer closes exactly when complete (routing, not a numbered story) | `llm` | `completes-claim-and-ends-call` | P0 | HIGH | routing, closing |
| — | Officer does not close or end call with a field still missing | `llm` | `does-not-close-with-missing-fields` | P0 | HIGH | routing, completeness |

¹ Filename says "redirects-claim-status-inquiry" but the test's internal
`name` field reads "...redirects non-claims inquiries **from greeting**" —
naming drift between filename and content, worth fixing so triage doesn't
have to open the file to know what it tests.

² Stories 19/20 (claim status), the PRD's "policy changes" example, and
story 28 (clearly-not-lodging-and-not-a-non-claims-inquiry) are three
distinct guardrail branches sharing one redirect number and, effectively,
two tests — the boundary between "non-claims inquiry" and "not lodging,
not inquiring either" isn't tested as a distinct case.

**Structural gap, not row-specific:** every Officer `llm` test is a
mid-conversation snapshot — `chat_history` primes prior turns, only the
response to the *last* turn is judged. No test exercises a full
greeting-to-close conversation end-to-end, so ordering bugs (e.g. the
Officer re-asking a field it already has, three turns after collecting it)
have no coverage. Per `docs/agents/tdd-guide.md`, this is exactly what
`simulation`-type tests exist for; none are configured yet.

## 7. Test Data

Fake data conventions already in use across `test_configs/` — reuse these
rather than inventing new values, so transcripts stay easy to diff:

- **Policy numbers**: `POL-######` (6 digits), or claim-type-prefixed
  (`PROP-555111`) for a headless/no-policy-number scenario.
- **Vehicle registration**: 3 letters–3 digits, e.g. `ABC-123`, `DEF-456`,
  `XYZ-789`.
- **Property addresses**: Australian street format, e.g. `15 Smith Street,
  Melbourne`, `88 George Street Brisbane`, `42 Wallaby Way, Sydney`.
- **Contact**: `firstname.lastname@example.com` or `04XX XXX XXX` mobile
  format.
- **Names**: ordinary Anglo names (John Smith, Sarah Chen, Emily Park,
  James Murphy) — none currently exercise a name with ambiguous/non-obvious
  spelling, which is the one case story 6's spelling-confirmation behavior
  is actually meant for. Worth a future test with a name like "Siobhan" or
  "Xuan" rather than only names whose spelling is already unambiguous from
  being spoken.

## 8. Pass Rate History

| Date | Trigger | Officer (18 tests) | Notes |
|---|---|---|---|
| 2026-07-12 | ADR 0003 redesign | 18/21 passing (officer: 18 tests, supervisor: 3 tests — supervisor since retired) | Relaxed name-spelling. Added `does-not-lodge-or-end-call` test. Updated transfer test. Officer end_call restricted to Emergency + Wrong Number only. |
| 2026-07-26 | ADR 0005 — Supervisor retired | 16-18/18 typical (settled, after 3 fixes) | Supervisor removed; 3 Supervisor tests deleted; Officer gained `end_call` for Completed Claim, Unresponsive Caller, WhatsApp Timeout. Two tests renamed/rewritten (`completes-claim-and-ends-call`, `does-not-close-with-missing-fields`); several others had their transfer-fallback branches removed. Initial rollout was flaky (13/18) due to two live-state bugs (stale `transfer_to_agent` tool, orphaned workflow prompt injection — see `experiment_log.md` 2026-07-26 and ADR 0005's rollout incident section) plus test-mode channel ambiguity, all fixed same day. Remaining ~2/18 flakiness is ordinary evaluator variance (Known Issue #7). |

Append a row after every CI run referenced in a debugging iteration (see
`docs/agents/debugging-guide.md`) or before/after a Coverage Map change.

## 9. Known Issues

1. **`workflow` block is confirmed live, not dead config — contradicts ADR
   0002, and is now a suspect in a second production incident.**
   `agent_configs/Claims-Lodgement-Officer.json` has `"workflow": null`
   locally, but the *platform* has always kept a separate `officer_node`/
   `supervisor_node` workflow that `elevenlabs agents push` cannot delete
   (confirmed by `GET /v1/convai/agents/{id}` returning a populated
   `workflow` object even after local removal). On 2026-07-15 this block's
   `officer_to_supervisor` edge was firing `transfer_to_agent` autonomously
   before name-spelling was confirmed, causing guardrail exhaustion on 3
   consecutive calls (commit `2dbb58b`). The fix PATCHed the platform
   directly (`edges={}`, `entry_behavior=wait_for_user` on `officer_node`)
   rather than removing the workflow — so a `wait_for_user` node still sits
   on the live agent with no edges into or out of it. On 2026-07-22, three
   consecutive WhatsApp sessions immediately following a successful call
   show the agent's greeting recorded in the transcript (`time_in_call_secs:
   0`) but the session terminating in 6–14s with `cost: 0` and zero user
   messages ("Client disconnected: 1000") — i.e. the greeting appears to
   have been generated but never delivered. Not yet confirmed whether the
   orphaned workflow node is the cause (vs. a WhatsApp/Meta delivery-layer
   issue outside this repo's control), but it's the most repo-controllable
   suspect given it already has one confirmed production incident on its
   record. **Tried removing it via `PATCH {"workflow": null}` — the platform
   silently ignored the null and returned the workflow completely unchanged**
   (same nodes, same `edges: {}`), just under a new version_id. This is the
   same silent-drop character as the CLI issues above, but on a direct API
   PATCH this time, not the CLI. Given `edges: {}` means `start_node` has no
   path to `officer_node`/`supervisor_node`/`end_node` at all, the workflow
   is very likely genuinely disconnected from conversation routing already —
   which fits the successful 2026-07-22 call (`conv_3001ky4r...`) completing
   a normal 29-message exchange under the identical workflow config.
   **Revised conclusion: the orphaned workflow is probably not the cause of
   the undelivered-greeting sessions** — still present and undeletable via
   this API, still worth raising with ElevenLabs support since a `null`
   PATCH being silently ignored is itself a bug, but no longer the leading
   suspect for the delivery issue. That investigation should now look at the
   WhatsApp/Meta delivery layer instead (outside this repo). **Now that the
   Supervisor is retired (ADR 0005), the orphaned `supervisor_node` this
   workflow references points at a deleted agent — worth re-checking whether
   the platform errors or silently no-ops on a workflow edge targeting a
   deleted agent ID, next time this is touched.**
2. ~~**No regression test for the Officer's 2-attempt retry cap** (story 14).~~
   **Closed 2026-08-03** — `wraps-up-after-2-attempt-retry-cap` forces two
   failed attempts to collect contact method (every other required field,
   including confirmed name spelling, already present) and asserts the
   Officer wraps up with the closing message + `end_call` on the third turn
   instead of asking again. Still only an `llm`-type test, so it's subject
   to the same test-mode guardrail gap as everything else in §5 — it
   exercises the Officer's own completeness-check judgment, not the
   `Claim completeness before closing` guardrail (which never fires in
   test-mode runs).
3. **Story 24 (hang-up mid-lodgement fires the webhook with partial data)
   cannot be covered by `llm`/`simulation` chat tests at all** — it's a
   disconnect-triggered backend behavior, not a scripted response. Needs a
   different verification mechanism (e.g. an integration check against
   actual webhook delivery) once the webhook payload work in issue #2 lands
   — tracking it here so it isn't mistaken for a testable Coverage Map gap.
4. **Zero `simulation`-type tests** — see the structural gap note in §6.
5. **Guardrail test-mode coverage is confirmed absent** (was previously
   listed as unverified) — see §5. The `Claim completeness before closing`
   guardrail never fires in `llm`-type test runs; only a live call or
   `simulate-conversation` exercises it. No CI-gating test protects this
   layer.
6. Filename/content-name drift on `redirects-claim-status-inquiry.json`
   (§6, footnote 1) — low-severity but slows down triage.
7. **`collects-vehicle-claim-via-guided-flow` and `handles-express-vehicle-claim`
   remain the two flakiest tests post-2026-07-26** (~1/3 fail rate even with
   channel pinned) — reads as ordinary LLM-evaluator variance on a
   borderline-complete transcript, not a regression, but worth a wording
   pass if it doesn't settle.

## 10. Changelog

- **2026-07-12** — TDD created by reverse-engineering `agent_configs/`,
  `test_configs/`, the PRD, and both ADRs (no prior TDD existed). Baseline
  Coverage Map: 31 PRD stories + 3 Supervisor-specific behaviors, 6 gaps
  identified (Known Issues #1–2, #4 most actionable).
- **2026-07-12 (post-ADR 0003)** — Relaxed name-spelling (accepts agent-guessing + claimant-confirming). Officer `end_call` restricted to Emergency + Wrong Number only; Unresponsive/Timeout now route via Supervisor. Added `Claims-Lodgement-Officer-does-not-lodge-or-end-call` test. Updated evaluation criteria (`verifies-name-spelling` → `confirms-name-spelling`). Supervisor now handles non-claim transfers. See `docs/adr/0003-officer-end-call-restriction.md`.
- **2026-07-22** — Production trace review (conversation `conv_3001ky4r174yfggt53r26gtjazd6`, WhatsApp, contact `0404999621`) found the agent asking the claimant to confirm name-spelling letter-by-letter on a text-only WhatsApp conversation. Root cause: the 2026-07-12 channel-aware spelling fix (`a5c51bf`) only updated the main prompt's text-only exception — the `transfer_to_agent` condition, the `Claim completeness before closing` guardrail, and the `verifies-name-spelling`/`confirms-name-spelling` eval criterion (the rename itself never actually landed) were left requiring spelling confirmation unconditionally, so those three enforcement points overrode the prompt's correct "skip on text-only" instruction. Fixed all three to carry the same text-only exception; eval criterion renamed to `confirms-name-spelling` (completing the rename ADR 0003 had already decided).
  - While pushing the fix, discovered `elevenlabs agents push` was silently dropping the `transfer_to_agent` condition text specifically — two consecutive pushes left the live condition on stale, pre-2026-07-12 wording despite the local file and the push both reporting success. Confirmed via direct API fetch (eval criterion and guardrail persisted correctly on the same pushes; only `condition` didn't). Worked around with a direct API `PATCH` (documented in the repo's `CLAUDE.md` Local↔Platform Sync Fields section); `scripts/verify-live-tools.py` extended to diff local vs. live condition text per transfer target so this can't silently drift again.
  - §6 gap "29 | WhatsApp channel, full lodgement happy path" is the coverage hole that let the original spelling bug ship — still open, should be closed with a WhatsApp-channel express-lodgement test asserting NO spelling question is asked.
  - Also investigated a separate report of WhatsApp sessions with no delivered greeting (three consecutive sessions, `cost: 0`, "Client disconnected: 1000" within 6–14s). Attempted to remove the orphaned `workflow` block (Known Issue #1) as the leading repo-controllable suspect via `PATCH {"workflow": null}`; the platform silently ignored it. Confirmed `edges: {}` means the workflow is unreachable from `start_node` regardless, so it's unlikely to be the actual cause — issue remains unresolved and open, likely a WhatsApp/Meta-side delivery problem outside this repo.
- **2026-07-26** — Claims Lodgement Supervisor retired (ADR 0005): the flow no longer promises a claim number or lodgement email, so the independent second-agent completeness re-read was judged to protect nothing a same-agent guardrail couldn't. Officer absorbed all closing responsibility — `end_call` now covers Completed Claim, Unresponsive Caller, and WhatsApp Timeout in addition to Emergency and Wrong Number. New Closing Message: "I've recorded your details. Our team will be in touch within two business days." `transfer_to_agent` removed from the Officer's tool set. Architecture, Tools, Routing, Guardrails, and Coverage Map sections rewritten for the single-agent shape; Utility/Telecom Customer Intake agent (unrelated, separate flow) also removed from this repo in the same session.
- **2026-08-03** — Closed Coverage Map gap for story 14 (2-attempt cap then wrap up anyway), the highest-severity untested behavior in the flow (P1/HIGH, zero coverage — Known Issue #2). Added `test_configs/Claims-Lodgement-Officer-wraps-up-after-2-attempt-retry-cap.json` (`test_2701kz349q5gewdte703g5fm6fyj`): a vehicle claim where every required field except contact method is present (including confirmed name spelling on a pinned voice call), the Officer has already asked for contact method twice and been deflected twice, and the correct response to a third deflection is to skip a third ask and instead deliver the closing message + `end_call`, per the `completeness-check` rule's "maximum 2 attempts per missing field" clause. Deliberately avoided policy number as the missing field since `closing-condition` already exempts it as best-effort — this test needed a field with no separate exemption, to isolate the retry-cap behavior itself. Registered in both `attached_tests` and `referenced_tests_ids` on the Officer's agent config.
