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

  **Text-only (WhatsApp) claim-summary-card (issue #64):** on a text-only
  conversation, once a claim's fields are complete per the data-completeness
  gate (§3), the Officer presents a plain text summary card of that claim's
  captured fields — one `Label: value` line per field, no asterisks, no
  bullet characters, no markdown headers, no emojis, digits for all numbers
  — and requires the claimant's explicit confirmation before moving on to
  ask about another claim or delivering the Closing Message. This happens
  once per claim (a multi-claim session gets one card per claim, right after
  that claim's own fields complete — not one consolidated card at the end).
  A claimant-flagged correction re-collects just that field, then
  re-presents the *complete* updated card (not a diff) and asks again. Card
  confirmation is a deliberately separate gate from data completeness — see
  §3 and the `text-summary-card-confirmation` prompt rule — kept distinct so
  neither can silently substitute for the other. Voice calls are entirely
  unaffected: no card, no extra confirmation step. An early triage draft of
  this feature specified WhatsApp-markdown formatting (`*bold*`, `•`
  bullets); that was reversed in favor of plain text before implementation
  (see issue #64's "Correction — card format changed to plain text" comment)
  — the card is plain text only, matching the behavior actually shipped.

  **Channel-aware response formatting (issue #63):** the Officer's `<tone>`
  prompt section splits number formatting by channel. On voice calls
  (`{{system__is_text_only}}` is false), numbers continue to be written as
  words so they're TTS-readable — unchanged from prior behavior — except
  phone/policy/registration numbers, which are read digit-by-digit (and
  letter-by-letter for any letters), never collapsed into a whole or rounded
  number (tightened during code review — see the Changelog entry below for
  why "remain as digits" alone wasn't a strong enough instruction). On
  text-only (WhatsApp) conversations (`{{system__is_text_only}}` is true),
  ALL numbers are written as digits — this broadens the historical
  phone/policy/registration-only digit exception into the default for
  text-only, rather than a narrow channel-independent carve-out. Separately,
  a new channel-independent `no-markdown-formatting` prompt rule blocks
  markdown formatting symbols (asterisks, bullet characters, headers, etc.)
  in every response, on both channels — a guard against model drift, not a
  description of a prior behavior difference. Ordinary conversational turns
  remain plain prose on both channels; this does not introduce any
  line-per-field or bulleted layout. Explicitly out of scope: any
  markdown/emoji/structured-layout formatting, and the WhatsApp
  claim-summary-card's own field layout (tracked separately in issue #64,
  above).

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
in the stack — which is exactly what made layer 2's `history_message_count: 0`
misconfiguration (fixed under issue #73, see Known Issues #10 and Changelog)
a load-bearing bug rather than a cosmetic one: with layer 2 blind, layer 1
was the *only* thing standing between a bad response and the caller.

**LLM: `qwen35-397b-a17b`, temperature 0.7 (unchanged; per the PRD) — a
tier swap was trialed and reverted under issue #73, see Known Issues #10.**
`claude-haiku-4-5` was trialed as a fix for repeated production incidents of
the model attaching `end_call` to a turn where its own reasoning had just
concluded it should ask a question instead (ADR 0004 already flagged this
general failure class — "LLM kept generating after the tool call, no 'stop
after tool X' mechanism" — as a platform-level risk, and the hosted
`qwen3.5` tier is optimized for cost/latency, not instruction-following
strictness). Verification against an isolated branch showed Haiku
overcorrected: `wraps-up-after-2-attempt-retry-cap` and
`completes-claim-and-ends-call` both failed consistently (5/5) — the agent
stopped ending the call even when it should, re-confirming or re-asking
indefinitely instead. Two unrelated channel-formatting tests
(`presents-whatsapp-summary-card`, `keeps-phone-and-policy-numbers-as-digits-on-voice`)
also newly failed consistently, suggesting Haiku follows this prompt's
channel-conditional instructions differently than `qwen3.5` did, not just
its `end_call` instructions. Reverted to `qwen35-397b-a17b` so the LLM tier
question can be isolated and evaluated as its own follow-up experiment,
separate from this urgent guardrail/tool fix — see Known Issues #10.

| Tool | Type | Purpose |
|---|---|---|
| `end_call` | `system` | Emergency, Wrong Number, Unresponsive Caller, WhatsApp Timeout, or Completed Claim (after the Closing Message). Never for a claim still missing required fields — enforced by prompt + guardrail. `description` populated with explicit preconditions/negative constraints and `pre_tool_speech: "force"` set (issue #73, was empty description + `"auto"` — see Known Issues #10); previously also duplicated verbatim in `prompt.tools[]`, now declared only once under `built_in_tools`. |

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

**Text-only claim-summary-card gate is separate from this one (issue #64).**
This closing-condition rule is, and remains, a pure *data*-completeness
check — it does not know or care whether a summary card was ever shown. On
a text-only conversation, satisfying this rule is *necessary but not
sufficient*: a second, independent prompt rule
(`text-summary-card-confirmation`) additionally requires the plain text
summary card to have been presented for that claim and explicitly confirmed
by the claimant before the Officer may ask about another claim or deliver
the Closing Message. The two gates are kept deliberately distinct rather
than merged into one "complete" condition. This mirrors the lesson of the
2026-07-22 incident described in §10's Changelog: a channel-conditional
exception added to the main prompt behavior was silently missed by three
independent enforcement layers (the `transfer_to_agent` condition, the
completeness guardrail, and the eval criterion) that weren't updated in the
same change, and the resulting bug shipped to production for over a week.
For issue #64, every enforcement point that reasons about "is this claim
ready to close" —
the `closing-condition`, `text-summary-card-confirmation`, `closing-message`,
`end-call-restriction`, and `multiple-claims` prompt rules, the `Claim
completeness before closing` guardrail, and the `wraps-up-and-ends-call-
when-complete` evaluation criterion — was updated together in the same
change, specifically to not repeat that failure mode.

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
  `gemini-2.5-flash-lite`, `history_message_count: 20`,
  `history_include_tool_calls: true`) — blocks and retries any response that
  ends the call or declares a claim complete for a Completed Claim closure
  while a required field is verifiably absent from the transcript, or that
  skips the Closing Message before `end_call`. Name spelling only counts as
  a required field on voice calls; on text-only (WhatsApp) conversations the
  typed name is exact and the guardrail does not require a spelling
  exchange. Exempt: Emergency, Wrong Number, Unresponsive Caller, WhatsApp
  Timeout. Feedback message quotes `{{trigger_reason}}` back to the agent.

  **Fixed under issue #73 (was `history_message_count: 0` since this
  guardrail's introduction in ADR 0002) — see Known Issues #10.** At 0, this
  guardrail evaluated every candidate response with zero transcript context,
  which cuts both ways: it couldn't reliably confirm a field was actually
  missing (root cause of two production incidents where the Officer called
  `end_call` mid-question with a required field genuinely uncollected — the
  guardrail should have blocked both and didn't), and separately, per
  `experiment_log.md` 2026-08-03, it was observed firing on `simulation`-type
  runs. That the 2026-08-03 run showed false-positive-shaped blocks (blocking
  well-formed mid-flow questions early in a conversation, burning retry
  budget) rather than only false negatives suggests the guardrail was
  guessing rather than reading transcript state either way. Raised to 20 so
  it can actually see the claim's data-collection history. The prompt also
  gained an explicit clause blocking `end_call` bundled with any unanswered
  question, checked independently of the field-completeness reasoning — a
  cheap, near-deterministic pattern match as defense-in-depth against the
  same self-contradiction seen in the production transcripts (the model's
  own chain-of-thought concluded a question was needed, then attached
  `end_call` anyway).

  **Extended for issue #64:** on a text-only conversation, this guardrail
  additionally blocks a response that ends the call, speaks the Closing
  Message, or moves on to ask about another claim, for a claim whose fields
  are otherwise complete, unless the transcript shows a plain text summary
  card was presented for that specific claim *and* the claimant explicitly
  confirmed it afterward. A card that was presented but only met with a
  correction (not a confirmation) does not satisfy this — the guardrail
  treats the claim as unconfirmed until a full updated card was re-presented
  and subsequently confirmed. This mirrors the `text-summary-card-
  confirmation` prompt rule so the guardrail can't silently drift out of
  sync with the prompt's actual text-only behavior (see §3's note on why
  these two gates are updated together).

  The evaluation criterion `wraps-up-and-ends-call-when-complete`
  (`platform_settings.evaluation.criteria`) was extended the same way, for
  the same reason — it now also fails a response that closes a text-only
  claim without a confirmed summary card, not just one with a missing data
  field.

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
**MEDIUM** · **LOW**. All tests below are type `llm` (single-response,
judged against the *last* `chat_history` turn only — see
`docs/agents/tdd-guide.md`) except one `simulation` test (full-conversation,
judged against the entire transcript), added 2026-08-03.

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
| 29 | WhatsApp channel, full lodgement happy path (incl. summary card presentation, confirmation, and correction — issue #64) | `llm` | `presents-whatsapp-summary-card`, `completes-whatsapp-claim-after-card-confirmation`, `recards-after-claimant-correction` | P1 | HIGH | whatsapp, channel, summary-card |
| 30 | Phone channel | *(implicit — default context of all tests)* | — | — | — | covered generically |
| 31 | Switch between text and voice mid-conversation | `llm` | `formats-numbers-as-digits-after-channel-switch-to-whatsapp`³, `keeps-phone-and-policy-numbers-as-digits-on-voice` | P2 | LOW | channel, formatting |
| — | Officer closes exactly when complete (routing, not a numbered story) | `llm` | `completes-claim-and-ends-call` | P0 | HIGH | routing, closing |
| — | Officer does not close or end call with a field still missing | `llm` | `does-not-close-with-missing-fields` | P0 | HIGH | routing, completeness |
| — | Full greeting-to-close vehicle guided-flow conversation, no field re-asked (structural gap, not a numbered PRD story) | `simulation` | `vehicle-guided-flow-full-conversation` | P1 | HIGH | vehicle, guided-flow, ordering, simulation |
| — | Officer does not silently end the call or attach `end_call` to a pending question after resuming from an off-topic redirect mid-flow (issue #73, not a numbered PRD story) | `llm` | `resumes-after-off-topic-redirect-without-ending-call` | P0 | NO-GO | routing, completeness, end-call, safety |

¹ Filename says "redirects-claim-status-inquiry" but the test's internal
`name` field reads "...redirects non-claims inquiries **from greeting**" —
naming drift between filename and content, worth fixing so triage doesn't
have to open the file to know what it tests.

² Stories 19/20 (claim status), the PRD's "policy changes" example, and
story 28 (clearly-not-lodging-and-not-a-non-claims-inquiry) are three
distinct guardrail branches sharing one redirect number and, effectively,
two tests — the boundary between "non-claims inquiry" and "not lodging,
not inquiring either" isn't tested as a distinct case.

³ Closed with a single-channel test, not a literal live channel handoff —
the CLI's `conversation_initiation_source` pins one channel per test run,
so there's no way to script an actual mid-call voice-to-WhatsApp switch
through this schema. The test instead opens `chat_history` with the
claimant stating they're continuing a claim started on a phone call, pinned
`conversation_initiation_source: "whatsapp"`, several turns into the
conversation (not a fresh greeting), and asserts the channel-conditional
number-formatting rule (§1) holds on the current channel for an
already-in-progress claim — the specific regression risk story 31 was
tracking (an agent that locks into whatever format it started with instead
of re-checking `{{system__is_text_only}}` each turn). The literal
"mid-conversation channel switch" mechanic remains untestable via `llm`/
`simulation` test-mode, same limitation as story 24 (§9, Known Issue 3).

**Structural gap, partially closed 2026-08-03:** every Officer `llm` test is
a mid-conversation snapshot — `chat_history` primes prior turns, only the
response to the *last* turn is judged. On its own this leaves ordering bugs
(e.g. the Officer re-asking a field it already has, three turns after
collecting it) with no coverage. Per `docs/agents/tdd-guide.md`, this is
exactly what `simulation`-type tests exist for. A first one now exists —
`vehicle-guided-flow-full-conversation` — covering the vehicle guided-flow
happy path end-to-end (greeting through closing-message + `end_call`,
asserting no field is ever re-asked). This is a start, not a close of the
gap: it covers one flow (vehicle, guided-flow, cooperative claimant) out of
several — property claims, express-lodgement ordering, multi-claim sessions,
and WhatsApp/text-only conversations are all still snapshot-only. See
`docs/agents/claims-lodgement.tdd.md`'s Coverage Map row above and Known
Issue #4.

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
| 2026-08-03 | First `simulation` test added (`vehicle-guided-flow-full-conversation`) | Officer now 19 tests, 18 `llm` + 1 `simulation` | New test failed once at `simulation_max_turns: 10` (turn budget exhausted one question before closing, not an agent defect — see `experiment_log.md`), passed cleanly at `simulation_max_turns: 20` on the immediate re-run. `llm` suite not re-run this session (no `agent_configs/` prompt/instruction change made — only `attached_tests`/`referenced_tests_ids` gained the new test ID). |
| 2026-08-07 | Issue #73 fix — first rigorous 3x-repeated run on an isolated branch (prior rows are single runs) | 26 tests (25 pre-existing + 1 new), baseline (pre-fix): ~19/26 typical across 3 runs | First time this suite was run 3x for a real pass-rate signal rather than once. Surfaced two tests (`wraps-up-after-2-attempt-retry-cap`, `presents-whatsapp-summary-card`) failing 3/3 **on the unmodified baseline config** despite both being logged "closed"/passing on 2026-08-03 — confirmed unrelated to issue #73 (Known Issue #9), filed as issues #74 and #75. Also surfaced `completes-claim-and-ends-call` degrading from ~2/3 baseline to consistently failing on the fixed config — see Known Issue #10 and Changelog for the tuning investigation. |

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
4. **`simulation`-type coverage: one test added 2026-08-03, most flows still
   gap.** See the structural gap note in §6. `vehicle-guided-flow-full-conversation`
   covers the vehicle guided-flow happy path only; property claims,
   express-lodgement, multi-claim sessions, and WhatsApp/text-only
   conversations remain untested end-to-end (only as `llm` snapshots).
   Building the first one surfaced a schema/mechanics nuance worth recording
   for whoever adds the next: `simulation_max_turns` needs headroom beyond
   the literal number of question/answer exchanges — a `Claim completeness
   before closing` guardrail retry (confirmed to actually fire on
   `simulation` runs, unlike `llm` test-mode runs — see Known Issue #5)
   consumes a turn without advancing the conversation, and 10 turns proved
   too tight for an 8-field vehicle claim plus name-spelling confirmation
   plus the mandatory "another claim?" question; 20 was sufficient. See
   `experiment_log.md` 2026-08-03.
5. **Guardrail test-mode coverage is confirmed absent for `llm`-type tests**
   (was previously listed as unverified) — see §5. The `Claim completeness
   before closing` guardrail never fires in `llm`-type test runs. **Update
   2026-08-03:** confirmed the guardrail *does* fire on `simulation`-type
   test runs via `POST /v1/convai/agents/{id}/run-tests` — real
   `guardrail_triggered` tool calls with populated `trigger_reason` observed
   twice while sanity-checking `vehicle-guided-flow-full-conversation` (see
   `experiment_log.md` 2026-08-03). This doesn't change the `llm`-type
   finding above, but it means `simulation` tests are the first CI-reachable
   mechanism in this repo that actually exercises this guardrail layer —
   still only for the one flow the new test covers, not a general claim
   about coverage.
6. Filename/content-name drift on `redirects-claim-status-inquiry.json`
   (§6, footnote 1) — low-severity but slows down triage.
7. **`collects-vehicle-claim-via-guided-flow` and `handles-express-vehicle-claim`
   remain the two flakiest tests post-2026-07-26** (~1/3 fail rate even with
   channel pinned) — reads as ordinary LLM-evaluator variance on a
   borderline-complete transcript, not a regression, but worth a wording
   pass if it doesn't settle.
8. **Digit-by-digit reading of phone/policy/registration numbers on voice
   is prompt-instructed but not test-verifiable.** The `<tone>` rule tells
   the agent to read these identifiers digit-by-digit (and letter-by-letter
   for any letters), never collapsed into a whole/rounded number — but this
   only constrains the agent's *text* output. Every test in this suite is
   `llm`/`simulation` type, judged against the transcript text the LLM
   produces, not the audio the TTS layer actually renders from it. A
   contiguous digit run (e.g. a policy number's "204958", with no internal
   spacing) is exactly the shape most at risk of a TTS engine reading it as
   one large number regardless of how explicit the prompt instruction is —
   and nothing in this repo's automated suite would catch that failure mode.
   The only way to confirm correct pronunciation is a manual voice-call
   listen-through; this is a structural limitation of the `llm`/`simulation`
   test types, not a coverage gap that can be closed with a better-written
   test.
9. **Two tests previously logged as passing/closed are now confirmed
   broken on the true pre-#73 baseline config — unrelated to issue #73,
   filed as #74 and #75.** While isolating the issue #73 fix, the
   investigation ran `wraps-up-after-2-attempt-retry-cap` (closed as
   passing under Known Issue #2 above, 2026-08-03; regression filed as
   **issue #74**) and `presents-whatsapp-summary-card` (closed as passing
   under issue #64, 2026-08-03; regression filed as **issue #75**) 3x each
   against a branch holding the exact unmodified, pre-#73 production config
   (`llm: qwen35-397b-a17b`, `history_message_count: 0`, empty `end_call`
   description) — both failed **3/3**, confirming this isn't caused by the
   #73 fix. Something regressed between 2026-08-03 and 2026-08-07 (or the
   original "closed" verification wasn't run with enough repetitions to
   catch existing flakiness — single runs, not the 3x this investigation
   used). Deliberately scoped out of
   the #73 fix/PR to avoid conflating two investigations (the same mistake
   the 2026-07-22 incident warns against, per that Changelog entry) — needs
   its own issue and debugging pass.
10. **Recurrence of a bug already "fixed" once — issue #73, premature
   `end_call` bundled with a pending question.** `experiment_log.md`
   2026-07-26 ("Fix 3") already added the `closing-condition` rule's
   "CRITICAL: ... do NOT call end_call" clause for this exact failure shape;
   it held for a while and then regressed in production (two incidents:
   silent `end_call` with no spoken response mid-claim, and `end_call`
   bundled with a spoken spelling-confirmation question — the model's own
   `end_call.reason` chain-of-thought in the first incident explicitly
   concluded it should ask for missing fields instead, then called
   `end_call` anyway). A second prompt-only patch was deliberately **not**
   used as the primary fix here, per `docs/agents/debugging-guide.md`'s
   guidance not to repeat an approach that already failed to hold — instead:
   `built_in_tools.end_call.description` (previously empty, see Tools table
   in §1) now states explicit preconditions; `pre_tool_speech` set to
   `"force"` so the agent can't silently go dead-air on `end_call`; the
   duplicate `end_call` entry removed from `prompt.tools[]`; the
   `Claim completeness before closing` guardrail's `history_message_count`
   fixed from `0` to `20` (see §5) so the one mechanical backstop can
   actually read transcript state, plus a new prompt clause giving it a
   second, pattern-matched way to catch the same failure independent of
   field-completeness reasoning. New regression test:
   `resumes-after-off-topic-redirect-without-ending-call` (§6).
   `scripts/validate-configs.py` extended to catch an empty
   `built_in_tools.<tool>.description` or a tool duplicated between
   `built_in_tools` and `prompt.tools[]`, so this class of gap can't ship
   silently again.

   **LLM tier swap trialed and reverted, same investigation.** The
   underlying LLM was also trialed as `claude-haiku-4-5` in place of the
   PRD-specified `qwen35-397b-a17b` (§1), on the theory that a hosted,
   cost/latency-optimized tier was a contributing cause of the unreliable
   tool-attachment (ADR 0004 precedent). Verified against an isolated
   ElevenLabs branch (`test-pr-branch.py`, 3 full suite runs plus
   confirmation reruns): the new test passed 3/3 and the guardrail-exercising
   `vehicle-guided-flow-full-conversation` `simulation` test passed 3/3 —
   but `wraps-up-after-2-attempt-retry-cap` and `completes-claim-and-ends-call`
   both **failed consistently, 5/5**, with the agent re-confirming or
   re-asking indefinitely instead of ever delivering the Closing Message or
   calling `end_call`. Two unrelated tests also newly failed consistently
   (`presents-whatsapp-summary-card`, `keeps-phone-and-policy-numbers-as-digits-on-voice`),
   indicating Haiku diverges from `qwen3.5` on this prompt's
   channel-conditional instructions generally, not just `end_call` timing.
   **Conclusion: stacking the LLM swap with the guardrail/tool fixes
   confounded the experiment** — the combined effect of three simultaneous
   negative-constraint tightenings on `end_call` (tool description, prompt,
   guardrail) plus a swap to a more conservative model produced the opposite
   failure mode (never closes) instead of a clean fix. Reverted the LLM
   field to `qwen35-397b-a17b` so this PR ships only the guardrail/tool
   fixes, verified in isolation; the LLM tier question is deferred to a
   separate follow-up experiment, one variable at a time, per this repo's
   own debugging methodology (`docs/agents/debugging-guide.md`).

   **`history_message_count` further tuned 20 → 10, `history_include_tool_calls`
   reverted true → false, after a second regression on the LLM-reverted
   config.** Even with `qwen35-397b-a17b` restored, `completes-claim-and-ends-call`
   still failed consistently. Root cause (confirmed via live transcript, not
   guessed): the guardrail has no direct access to `{{system__is_text_only}}`
   and must infer channel purely from transcript style; at
   `history_message_count: 20` the small eval model (`gemini-2.5-flash-lite`)
   had enough extra context to occasionally misjudge a voice-pinned test as
   text-only and wrongly demand the WhatsApp summary card, and the resulting
   bad retry-feedback pushed the primary agent into presenting a card and
   asking for confirmation instead of closing. Reducing to `10` (and
   dropping the unneeded `history_include_tool_calls`) eliminated that
   specific failure pattern in a follow-up verification round (0 recurrences
   in 8 samples, vs. 8/8 at `history_message_count: 20`).

   **A second, independent problem surfaced at the same time and was
   initially misattributed to the same regression — it is not one.**
   `completes-claim-and-ends-call` still failed intermittently (~50%) even
   after the history fix, but a live transcript showed a *different*, guardrail-
   uninvolved cause: the agent asked "Is there another claim you'd like to
   lodge?" instead of closing. That is *correct* behavior per the
   `multiple-claims` rule (§ prompt), which requires asking about additional
   claims on every voice call as soon as a claim's fields are complete,
   before ever delivering the Closing Message — **the test's own scripted
   `chat_history` never included that question-and-answer turn**, so it was
   testing a conversation shape the prompt was never going to produce. This
   is a pre-existing test/prompt mismatch, not something this fix broke; it
   was likely masked before because a blind guardrail (`history_message_count: 0`)
   correlated with the model following its own rules less consistently
   overall. Fixed by adding the missing "Is there another claim?" /
   "No, that's everything" turns to the test's `chat_history` (same `test_id`,
   updated in place via `elevenlabs tests push`) — not by changing agent
   behavior. `vehicle-guided-flow-full-conversation`'s `simulation_max_turns`
   raised 20 → 26 for the same reason (a properly-functioning, non-blind
   guardrail retries more often when it catches something real, and the
   turn budget needs headroom for that plus the now-mandatory
   multiple-claims round-trip).

## 10. Changelog

- **2026-07-12** — TDD created by reverse-engineering `agent_configs/`,
  `test_configs/`, the PRD, and both ADRs (no prior TDD existed). Baseline
  Coverage Map: 31 PRD stories + 3 Supervisor-specific behaviors, 6 gaps
  identified (Known Issues #1–2, #4 most actionable).
- **2026-07-12 (post-ADR 0003)** — Relaxed name-spelling (accepts agent-guessing + claimant-confirming). Officer `end_call` restricted to Emergency + Wrong Number only; Unresponsive/Timeout now route via Supervisor. Added `Claims-Lodgement-Officer-does-not-lodge-or-end-call` test. Updated evaluation criteria (`verifies-name-spelling` → `confirms-name-spelling`). Supervisor now handles non-claim transfers. See `docs/adr/0003-officer-end-call-restriction.md`.
- **2026-07-22** — Production trace review (conversation `conv_3001ky4r174yfggt53r26gtjazd6`, WhatsApp, contact `0404999621`) found the agent asking the claimant to confirm name-spelling letter-by-letter on a text-only WhatsApp conversation. Root cause: the 2026-07-12 channel-aware spelling fix (`a5c51bf`) only updated the main prompt's text-only exception — the `transfer_to_agent` condition, the `Claim completeness before closing` guardrail, and the `verifies-name-spelling`/`confirms-name-spelling` eval criterion (the rename itself never actually landed) were left requiring spelling confirmation unconditionally, so those three enforcement points overrode the prompt's correct "skip on text-only" instruction. Fixed all three to carry the same text-only exception; eval criterion renamed to `confirms-name-spelling` (completing the rename ADR 0003 had already decided).
  - While pushing the fix, discovered `elevenlabs agents push` was silently dropping the `transfer_to_agent` condition text specifically — two consecutive pushes left the live condition on stale, pre-2026-07-12 wording despite the local file and the push both reporting success. Confirmed via direct API fetch (eval criterion and guardrail persisted correctly on the same pushes; only `condition` didn't). Worked around with a direct API `PATCH` (documented in the repo's `CLAUDE.md` Local↔Platform Sync Fields section); `scripts/verify-live-tools.py` extended to diff local vs. live condition text per transfer target so this can't silently drift again.
  - §6 gap "29 | WhatsApp channel, full lodgement happy path" is the coverage hole that let the original spelling bug ship — still open, should be closed with a WhatsApp-channel express-lodgement test asserting NO spelling question is asked. **Closed 2026-08-03 by issue #64** — see that changelog entry below.
  - Also investigated a separate report of WhatsApp sessions with no delivered greeting (three consecutive sessions, `cost: 0`, "Client disconnected: 1000" within 6–14s). Attempted to remove the orphaned `workflow` block (Known Issue #1) as the leading repo-controllable suspect via `PATCH {"workflow": null}`; the platform silently ignored it. Confirmed `edges: {}` means the workflow is unreachable from `start_node` regardless, so it's unlikely to be the actual cause — issue remains unresolved and open, likely a WhatsApp/Meta-side delivery problem outside this repo.
- **2026-07-26** — Claims Lodgement Supervisor retired (ADR 0005): the flow no longer promises a claim number or lodgement email, so the independent second-agent completeness re-read was judged to protect nothing a same-agent guardrail couldn't. Officer absorbed all closing responsibility — `end_call` now covers Completed Claim, Unresponsive Caller, and WhatsApp Timeout in addition to Emergency and Wrong Number. New Closing Message: "I've recorded your details. Our team will be in touch within two business days." `transfer_to_agent` removed from the Officer's tool set. Architecture, Tools, Routing, Guardrails, and Coverage Map sections rewritten for the single-agent shape; Utility/Telecom Customer Intake agent (unrelated, separate flow) also removed from this repo in the same session.
- **2026-08-03** — Closed Coverage Map gap for story 14 (2-attempt cap then wrap up anyway), the highest-severity untested behavior in the flow (P1/HIGH, zero coverage — Known Issue #2). Added `test_configs/Claims-Lodgement-Officer-wraps-up-after-2-attempt-retry-cap.json` (`test_2701kz349q5gewdte703g5fm6fyj`): a vehicle claim where every required field except contact method is present (including confirmed name spelling on a pinned voice call), the Officer has already asked for contact method twice and been deflected twice, and the correct response to a third deflection is to skip a third ask and instead deliver the closing message + `end_call`, per the `completeness-check` rule's "maximum 2 attempts per missing field" clause. Deliberately avoided policy number as the missing field since `closing-condition` already exempts it as best-effort — this test needed a field with no separate exemption, to isolate the retry-cap behavior itself. Registered in both `attached_tests` and `referenced_tests_ids` on the Officer's agent config.
- **2026-08-03** — Added the repo's first `simulation`-type test,
  `test_configs/Claims-Lodgement-Officer-vehicle-guided-flow-full-conversation.json`
  (`test_2601kz34jff6edqa72x8wrf0n366`), closing part of the §6 structural
  gap / Known Issue #4: a cooperative-claimant vehicle guided-flow
  conversation judged end-to-end (greeting through closing-message +
  `end_call`) for zero repeated field-asks, all required fields collected,
  and a correctly-worded close. Companion fix to
  `scripts/validate-configs.py`: the `chat_history` non-empty-array check
  now only applies to `llm`/`tool` tests; `simulation` tests are validated
  for a non-empty `simulation_scenario` instead (an empty `chat_history` is
  the normal fresh-start case for a simulation, and the old check would have
  hard-failed every simulation test in CI). Sanity-checking the new test
  live surfaced two things not predicted going in — both logged in
  `experiment_log.md` 2026-08-03: (1) `simulation_max_turns: 10` was too
  tight (guardrail retries consume turns without advancing the
  conversation; raised to 20), and (2) the `Claim completeness before
  closing` guardrail is confirmed to actually fire on `simulation`-type
  `run-tests` calls, unlike the confirmed-absent case for `llm`-type
  test-mode runs (Known Issue #5, updated). This is a start on the
  structural gap, not a close of it — see the §6 gap note and Known Issue
  #4 for what's still snapshot-only (property claims, express-lodgement,
  multi-claim sessions, WhatsApp/text-only).
- **2026-08-03 (issue #64)** — Added the text-only (WhatsApp) claim-summary-card: once a claim's fields are complete, the Officer presents a plain text summary (one `Label: value` line per captured field, no markdown, no emojis, digits for numbers, policy number omitted entirely if not provided) and requires explicit claimant confirmation before moving on to ask about another claim or deliver the Closing Message, once per claim. A claimant correction re-collects just that field and re-presents the *full* updated card. An early triage draft (the "Agent Brief" comment on #64) specified WhatsApp-markdown formatting; that was reversed to plain text before implementation by a follow-up "Correction" comment on the same issue — the shipped behavior is plain text only.
  - New `<procedure id="claim-summary-card">` and `<rule id="text-summary-card-confirmation">` added to the prompt; `closing-message`, `end-call-restriction`, and `multiple-claims` rules updated to require the text-only card gate in addition to (not merged with) the existing `closing-condition` data-completeness gate — see §3's note on why the two gates stay separate. Learning from the 2026-07-22 incident (above): every enforcement point reasoning about "is this claim ready to close" was grepped and updated in the same change, not just the primary prompt instruction — this included the `Claim completeness before closing` guardrail and the `wraps-up-and-ends-call-when-complete` eval criterion (§5).
  - Closed Coverage Map gap #29 (WhatsApp full lodgement happy path) with three new `llm` tests: `Claims-Lodgement-Officer-presents-whatsapp-summary-card` (card presentation + format), `Claims-Lodgement-Officer-completes-whatsapp-claim-after-card-confirmation` (confirmation → no-more-claims → Closing Message/`end_call`), and `Claims-Lodgement-Officer-recards-after-claimant-correction` (correction → full re-presented card). All three pin `conversation_initiation_source: "whatsapp"` per the Test-mode channel pinning note above.
  - As with the rest of this guardrail layer, the text-only card-confirmation gate has no test-mode coverage — see §5 and Known Issue #5's note that guardrails don't fire in CLI/API test-mode runs; the three new `llm` tests exercise only the prompt's raw, first-pass behavior, not the guardrail's corrective retry.
  - A dedicated evaluation criterion for the card behavior itself (beyond the `wraps-up-and-ends-call-when-complete` extension above) is intentionally out of scope here — tracked separately in issue #67, blocked on this change landing first.
- **2026-08-03 (issue #63)** — Channel-aware response formatting. Split the `<tone>` section's number-formatting bullet by channel: voice calls keep writing numbers as words (unchanged); text-only (WhatsApp) conversations now write ALL numbers as digits, broadening the old phone/policy/registration-only digit exception into the text-only default. Added a new, channel-independent `no-markdown-formatting` prompt rule blocking markdown symbols (asterisks, bullets, headers, etc.) in every response on both channels — a guard against model drift, not a description of prior behavior. An early triage draft of this issue proposed WhatsApp markdown/emoji formatting; that was rejected during triage grilling (settled jointly with issue #64) in favor of plain prose on both channels — see the issue's "Agent Brief" comment. Deliberately scoped away from `closing-condition`, `closing-message`, `end-call-restriction`, `multiple-claims`, the `Claim completeness before closing` guardrail, and the `wraps-up-and-ends-call-when-complete` eval criterion — those are issue #64's (WhatsApp claim-summary-card) territory, kept untouched here so the two changes merge independently. Closed §6 gap "31 | Switch between text and voice mid-conversation" with `Claims-Lodgement-Officer-formats-numbers-as-digits-after-channel-switch-to-whatsapp` (see §6 footnote 3 for the CLI's single-channel-per-test limitation on what "closed" means here). New test registered via `elevenlabs tests push` (`test_3901kz2gz6pmey892jr524tp7nev`) and attached to the Officer's `platform_settings.testing.attached_tests`.
  - **Code-review fix (same day)**: the initial `<tone>` rewrite dropped the pre-existing "phone numbers, policy numbers, and registration numbers remain as digits" exception from the voice branch — a real regression that would have had the agent spell out phone/policy/registration numbers as words on voice calls, which the issue's brief explicitly required to stay unchanged. Caught during code review (Spec axis) before merge, not by CI — no test exercised phone-number formatting on a voice call. Restored the exception to the voice branch and added `Claims-Lodgement-Officer-keeps-phone-and-policy-numbers-as-digits-on-voice` (registered via `elevenlabs tests push`, `test_5401kz2hpmpaen3rgf0k9x81ce9g`, attached) to close that coverage hole going forward.
  - **Follow-up tightening (same day)**: "remain as digits" was ambiguous about *how* they should sound — it only constrains the agent's text output and relies on the TTS layer reading a digit string naturally, which is a much safer assumption for a spaced phone number ("0404 991 625") than for a contiguous run like a policy number's "204958". Reworded the voice exception to explicitly require digit-by-digit (and letter-by-letter) reading, never collapsed into a whole/rounded number, while still allowing either a digit-string or spelled-out-digit-by-digit text form. Documented the residual gap as Known Issue #8 (§9): this is a structural limitation of `llm`/`simulation` test types (they judge transcript text, not rendered audio), not something a better-written test can close — only a manual voice-call listen-through can actually confirm correct pronunciation.
