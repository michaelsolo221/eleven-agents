# TDD: CGU Claims Lodgement (Officer + Supervisor)

Reverse-engineered from `agent_configs/Claims-Lodgement-Officer.json`,
`agent_configs/Claims-Lodgement-Supervisor.json`, `test_configs/*.json`,
`docs/prd/001-claims-lodgement-agent.md`, and both ADRs. See
`docs/agents/tdd-guide.md` for the methodology and section definitions.
Domain terms below (Claim, Claimant, Risk Asset, etc.) are defined in
`CONTEXT.md`.

**Written from the current shipped config, not from `CONTEXT.md` or the
ADRs alone** — see Known Issues #1 for a case where the two disagree.

## 1. Architecture

Two registered ElevenLabs agents, `agents.json`:

- **Claims Lodgement Officer** ("Amanda") — opens every conversation. Owns
  the greeting, claim-type branch (vehicle/property), guided-flow and
  express-lodgement field collection, name-spelling confirmation, and every
  guardrail except final lodgement (emergency, non-claims redirect, wrong
  number, small talk, unresponsive caller, WhatsApp timeout). May call
  `end_call` only for Emergency and Wrong Number — all other call-ending
  paths route through the Supervisor via `transfer_to_agent`. Must not
  speak or act after a successful transfer. Never declares a claim lodged.
- **Claims Lodgement Supervisor** — never opens a conversation; only
  entered via `transfer_to_agent` from the Officer. First determines the
  transfer type: if Unresponsive Caller or WhatsApp Timeout, calls
  `end_call` immediately; otherwise re-reads the full transcript
  (`{{system__conversation_history}}`) independently — does not trust the
  Officer's own belief that collection is complete. Either confirms +
  lodges (only agent that says "Your claim has been lodged") or asks for
  whatever it finds missing, capped at 2 attempts per field.

Per ADR 0002, the intended handoff mechanism is the `transfer_to_agent`
system tool (a real cross-agent transfer), **not** ElevenLabs' `workflow`
node graph — the workflow-node edge was tested and found not to reliably
transition between two `override_agent` persona nodes. See Known Issues #1:
the shipped Officer config still contains a `workflow` block that the ADR
says was abandoned for exactly this reason.

**Layered defense** (ADR 0002, "no single layer is airtight"):
1. Officer's own silent completeness self-check before deciding to transfer.
2. Officer's prompt instruction to transfer rather than self-end on completion.
3. Supervisor's independent transcript re-read.
4. `Claim completeness before closing` custom guardrail (blocking, both
   agents) — forces a retry if a response ends the call or declares
   lodgement while a required field is verifiably absent from the transcript.

None of 1–3 are individually reliable per the ADR; layer 4 is the only
mechanical check in the stack.

| Tool | Type | Agent(s) | Purpose |
| `end_call` | `system` | Officer, Supervisor | Officer: emergency, wrong number only (never for completed claims, unresponsive caller, or WhatsApp timeout — those route through Supervisor). Supervisor: after confirming lodgement, exhausting retries, or handling non-claim transfers. |

| Tool | Type | Agent(s) | Purpose |
|---|---|---|---|
| `end_call` | `system` | Officer, Supervisor | Officer: emergency, wrong number, unresponsive caller, WhatsApp timeout (never for a completed claim — enforced by prompt + guardrail, not by withholding the tool; see ADR 0002 "Officer keeps `end_call`"). Supervisor: after confirming lodgement or exhausting retries. |
| `transfer_to_agent` | `system` | Officer only | Hands off to the Supervisor (`agent_8101kx3drtdwfmqtv6085k716gsz`). Condition is LLM-judged prose requiring every field to have been *explicitly* stated and name spelling *explicitly* confirmed — see §3. |

No webhook tool captures structured claim data — the backend parses the
post-call transcript webhook (`platform_settings.workspace_overrides.webhooks`,
event `transcript`). Payload structure is explicitly out of scope (PRD,
tracked in issue #2). This is why there are no `tool`-type tests in this
Officer → Supervisor, via `transfer_to_agent`, condition (paraphrased from
the live config): true only if the claimant has *explicitly and separately*
stated, earlier in the same conversation — claim type; what happened; date/time;
registration or address (matching claim type); incident location (vehicle
only); a contact method; first name; last name; **and**, on a *voice* call,
had the spelling of both names explicitly confirmed by the claimant in any
form (agent guessing + claimant confirming is valid). On a *text-only*
conversation (e.g. WhatsApp), the typed name is exact and no spelling
confirmation is required for this condition. Any doubt on any item →
condition is false.

There is no routing back from Supervisor to Officer. A second claim in the
same session restarts the Officer's own claim-type branch (story 15) — the
Officer, not a fresh transfer, drives multi-claim continuation.

## 4. Session / Data Variables

`platform_settings.data_collection` (identical schema on both agents):

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

Both agents share the same `platform_settings.guardrails` shape:

- `focus` + `prompt_injection` — enabled, defaults.
- `content` — `harassment` and `profanity` at threshold 0.5, execution mode
  `streaming`, `trigger_action: end_call`. `sexual` / `violence` / `self_harm`
  / `religion_or_politics` / `medical_and_legal_information` disabled.
- `custom` → **Claim completeness before closing** (blocking, model
  `gemini-2.5-flash-lite`, `history_message_count: 0`) — blocks and retries
  any response that ends the call or declares lodgement while a required
  field is verifiably absent from the transcript. Name spelling only counts
  as a required field on voice calls; on text-only (WhatsApp) conversations
  the typed name is exact and the guardrail does not require a spelling
  exchange. Feedback message quotes `{{trigger_reason}}` back to the agent.

Prompt-level guardrail sections (Officer only, not a platform guardrail —
enforced by instruction text): Emergency, Non-Claims Inquiries, Wrong
Number, Small Talk, Unresponsive Caller, WhatsApp Session Timeout,
Mid-Lodgement Hang-Up.

**Open question, not yet verified:** does the platform actually invoke
`platform_settings.guardrails` during `agents test` / scenario-test runs, or
only in live conversations? If test-mode skips guardrail evaluation, the
completeness guardrail — the one mechanical layer in the stack — has no
regression coverage at all, on top of the gaps in §6. Worth confirming
against ElevenLabs docs before relying on CI to catch a guardrail
regression.

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
| 6 | Confirm name spelling | `llm` | `collects-*-via-guided-flow`, `handles-express-*-claim`, `transfers-to-supervisor-when-complete` | P0 | HIGH | name-spelling |
| 7–8 | Property claim via address; address doubles as incident location | `llm` | `collects-property-claim-via-guided-flow` | P1 | HIGH | property, guided-flow |
| 9–10 | Express lodgement dump; name spelling still verified | `llm` | `handles-express-property-claim`, `handles-express-vehicle-claim` | P1 | HIGH | express |
| 11 | Guided flow, one field at a time | `llm` | `collects-*-via-guided-flow` | P1 | MEDIUM | guided-flow |
| 12 | Ask vehicle/property upfront | *(none)* | — platform `evaluation.criteria: asks-vehicle-or-property-upfront` exists but is analysis-only scoring, not a CI-gating test | P1 | MEDIUM | **GAP** |
| 13 | Missing policy number (headless claim) | `llm` | `handles-missing-policy-number` | P0 | HIGH | best-effort-field |
| 14 | 2-attempt cap then lodge anyway (Officer side) | *(none)* | — | P1 | HIGH | **GAP** — retry-cap |
| 15 | Multiple claims, one session | `llm` | `handles-multiple-claims` | P1 | MEDIUM | multi-claim |
| 16–17 | Nominated representative | `llm` | `handles-nominated-representative` | P1 | MEDIUM | nominated-rep |
| 18 | Emergency → 000, end call | `llm` | `handles-emergency-redirect` + negative case `treats-past-events-as-valid-claims` | P0 | NO-GO | emergency, safety |
| 19–20 | Claim status redirect, offer new claim | `llm` | `redirects-claim-status-inquiry`¹ | P1 | MEDIUM | redirect |
| 21–22 | Unresponsive caller: prompt, then end call | `llm` | `handles-unresponsive-caller` | P0 | HIGH | safety, unresponsive |
| 23 | Post-lodgement closing message | `llm` | `Claims-Lodgement-Supervisor-confirms-when-complete` | P0 | HIGH | closing-message |
| 24 | Hang-up mid-lodgement → webhook fires with partial data | *(none — untestable as an `llm`/`simulation` chat eval)* | — | P1 | HIGH | **GAP — different remediation path**, see below |
| 25 | WhatsApp session timeout (1hr) | `llm` | `handles-whatsapp-session-timeout` | P1 | MEDIUM | whatsapp, timeout |
| 26 | Wrong number | `llm` | `handles-wrong-number` | P1 | MEDIUM | redirect |
| 27 | Small talk, steer back | `llm` | `steers-small-talk` | P2 | LOW | small-talk |
| 21–22 | Unresponsive caller: prompt, then transfer to Supervisor | `llm` | `handles-unresponsive-caller` | P0 | HIGH | safety, unresponsive |
| 29 | WhatsApp channel, full lodgement happy path | *(none — only the timeout edge case is WhatsApp-specific)* | — | P2 | LOW | **GAP** — channel |
| 30 | Phone channel | *(implicit — default context of all tests)* | — | — | — | covered generically |
| 31 | Switch between text and voice mid-conversation | *(none)* | — | P2 | LOW | **GAP** — channel |
| — | Officer transfers exactly when complete (routing, not a numbered story) | `llm` | `transfers-to-supervisor-when-complete` | P0 | HIGH | routing |
| — | Supervisor catches a field the Officer missed | `llm` | `Claims-Lodgement-Supervisor-catches-missing-field` | P0 | HIGH | supervisor, safety-net |
| — | Officer does not lodge or end call after all fields collected | `llm` | `Claims-Lodgement-Officer-does-not-lodge-or-end-call` | P0 | HIGH | routing, post-transfer |

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
greeting-to-transfer conversation end-to-end, so ordering bugs (e.g. the
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

| Date | Trigger | Officer (16 tests) | Supervisor (2 tests) | Notes |
|---|---|---|---|---|
| 2026-07-12 | ADR 0003 redesign | 18/21 passing (officer: 18 tests, supervisor: 3 tests) | Relaxed name-spelling. Added `does-not-lodge-or-end-call` test. Updated transfer test. Officer end_call restricted to Emergency + Wrong Number only. |
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
   WhatsApp/Meta delivery layer instead (outside this repo).
2. **No regression test for either agent's 2-attempt retry cap** (story 14,
   and the Supervisor's own `supervisor-respects-retry-cap` criterion). Both
   are prompt instructions with a platform `evaluation.criteria` entry on
   the Supervisor side, but neither has a `test_configs/*.json` that forces
   two failed attempts and asserts "lodge anyway" happens on the third.
3. **Story 24 (hang-up mid-lodgement fires the webhook with partial data)
   cannot be covered by `llm`/`simulation` chat tests at all** — it's a
   disconnect-triggered backend behavior, not a scripted response. Needs a
   different verification mechanism (e.g. an integration check against
   actual webhook delivery) once the webhook payload work in issue #2 lands
   — tracking it here so it isn't mistaken for a testable Coverage Map gap.
4. **Zero `simulation`-type tests** — see the structural gap note in §6.
5. **Guardrail test-mode coverage is unverified**, not confirmed absent —
   see §5's open question.
6. Filename/content-name drift on `redirects-claim-status-inquiry.json`
   (§6, footnote 1) — low-severity but slows down triage.

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
