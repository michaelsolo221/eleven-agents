# CGU Claims Lodgement

An AI-assisted channel for lodging insurance claims with CGU (Australia). Customers interact via phone or WhatsApp to lodge new claims through either a guided conversation or an express dump of information.

## Language

**Claim**:
A request for insurance payout lodged by a customer. A single interaction may contain multiple claims (e.g., a vehicle claim and a property claim from separate incidents).
_Avoid_: Report, case, ticket, incident report

**Claimant**:
The person lodging the claim — the caller or message sender. May or may not be the policyholder.
_Avoid_: Caller, customer, user, client

**Policy Number**:
The unique identifier linking a claimant to their insurance policy. Not strictly required — headless claims can be looked up by asset ID later.
_Avoid_: Policy ID, account number, reference number

**Risk Asset**:
The insured item that suffered the loss or damage. Exactly one per claim. Either a Property or a Vehicle — never both in a single lodgement.
_Avoid_: Asset, insured item, subject of claim

**Property**:
A risk asset identified by its street address. Covers houses, commercial premises, and other real property.
_Avoid_: House, building, premises

**Vehicle**:
A risk asset identified by its Australian registration number. Covers cars, trucks, motorcycles, and other motor vehicles.
_Avoid_: Car, motor vehicle, auto

**Incident Date/Time**:
When the event that caused the claim occurred. A required field — the agent must capture at least the date; time is best-effort.
_Avoid_: Date of loss, when it happened

**Incident Location**:
Where the event that caused the claim occurred. Required for vehicle claims (the crash site, not where the car is now). For property claims, the property address serves this purpose.
_Avoid_: Scene, location of loss, where it happened

**Contact Method**:
Either an email address or a phone number — at least one required. Used for follow-up after lodgement.
_Avoid_: Contact details, phone/email

**Contact Person**:
The point of contact for the claim — whoever we can speak to. First name and last name required. Name spelling is always confirmed with the claimant on voice calls (any method — agent guesses or asks to spell). May be the policyholder or a Nominated Representative.
_Avoid_: Claimant name, caller name

**Nominated Representative**:
A person calling on behalf of the policyholder (e.g., a family member, fleet manager). The Nominated Representative becomes the Contact Person for the claim.
_Avoid_: Authorized caller, proxy, representative

## Interaction Modes

**Guided Flow**:
The agent leads the conversation, asking for each required field one at a time. Used when the claimant doesn't provide everything upfront.
_Avoid_: Slow mode, conversational mode

**Express Lodgement**:
The claimant provides most or all required information in a single message. The agent parses it, verifies name spelling, checks for missing fields, and proceeds. Not fully "express" — name spelling verification always occurs.
_Avoid_: Mag dump, fast mode, quick lodgement

## Verification & Escalation

**Claims Officer**:
The Agent that conducts intake — "Amanda". Owns the entire interaction end to end: greeting, Guided Flow / Express Lodgement, completeness confirmation, the closing wrap-up, and call termination. There is no separate lodgement/validation agent — see Completeness Guardrail. May call `end_call` for: Emergency redirect, Wrong Number, Unresponsive Caller, WhatsApp Session Timeout, and a completed claim (after delivering the Closing Message). Never says a claim has been "lodged" or mentions a claim number — see Closing Message.
_Avoid_: The agent, the bot, the assistant

**Closing Message**:
The line the Claims Officer speaks once every required field for a claim (including name spelling, on voice calls) has been collected: "I've recorded your details. Our team will be in touch within two business days." Spoken before `end_call`, on both voice and WhatsApp — the wording does not need to differ by channel. Replaces the old Claims Supervisor's lodgement confirmation; deliberately avoids "lodged," a claim number, or an email promise, since none of those exist in this flow. See `docs/adr/0005-retire-claims-supervisor-single-agent-lodgement.md`.
_Avoid_: Lodgement confirmation, claim number, transfer message

**Completeness Check**:
The Claims Officer's own silent check of captured data against the required field set, performed as it collects fields and again immediately before delivering the Closing Message. If fields are missing, the officer asks for them. After two failed attempts for any single field, the officer is expected to wrap up and end the call with whatever is available. This is the Officer's own judgment and can be wrong — see Completeness Guardrail.
_Avoid_: Validation, data check

**Completeness Guardrail**:
An automatic check on every Officer response that blocks — and forces a retry of — any response which ends the call, or declares a claim complete, while a required field is genuinely absent from the transcript, or which skips the Closing Message before a completed-claim `end_call`. The last line of defense if the Officer's own Completeness Check is wrong. Does not apply to Emergency, Wrong Number, Unresponsive Caller, or WhatsApp Session Timeout closures, which have their own short scripts.
_Avoid_: Safety check, content filter

**Name Spelling Confirmation**:
The agent confirms the exact spelling of the claimant's first and last name with the claimant. Any confirmation method is acceptable: the agent may ask the claimant to spell their name, or the agent may guess the spelling and ask the claimant to confirm. On text-only channels (WhatsApp), no spelling confirmation is needed — the typed name is exact. Always performed on voice calls, regardless of interaction mode.
_Avoid_: Name confirmation, identity check, name verification

**Emergency Redirect**:
Immediate termination when the claimant states they are in danger or unsafe right now. The agent says to call 000 and ends the interaction.
_Avoid_: Crisis handling, safety escalation

**Non-Claims Redirect**:
When the claimant's request is not about lodging a new claim (e.g., claim status, policy changes, complaints), redirect to 1300 943 690 for standard telephone support.
_Avoid_: General inquiries redirect

**Session Timeout**:
On WhatsApp text interactions, the agent ends the session after 1 hour of claimant inactivity. The agent tells the claimant the interaction is closing and to start a new one for a fresh claim.
_Avoid_: Idle timeout, conversation expiry
## Post-Call & Integrations

**Post-Call Webhook Receiver**:
An HTTP microservice (hosted via Coolify) that receives and authenticates ElevenLabs `post_call_transcription` webhook events immediately after a call or text interaction concludes.
_Avoid_: Webhook listener, state service, backend proxy

**Call Disposition Status**:
The outcome classification assigned to a completed interaction. ADR 0006 originally proposed four tags (`COMPLETE`, `INCOMPLETE`, `ALERT`, `REDIRECT`); only `COMPLETE`/`INCOMPLETE` are implemented (issue #45) since `end_call` has no structured reason parameter to drive `ALERT`/`REDIRECT` today. Explicitly prefixed in the email subject line to provide instant visibility to claims handlers.
_Avoid_: Call outcome, status label, status tag

**Claim Summary Email**:
An HTML notification email dispatched via Resend immediately after a call. Contains a structured claim field summary table, quality/evaluation check results, and a chronological conversation transcript log.
_Avoid_: Claim report email, transcript notification
