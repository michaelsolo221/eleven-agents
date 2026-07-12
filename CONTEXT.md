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
The Agent that conducts intake — "Amanda". A separate registered ElevenLabs Agent, not a persona within a larger agent. Owns the greeting, Guided Flow / Express Lodgement, and every guardrail except final lodgement. May call `end_call` only for Emergency redirects and Wrong Number. All other call-ending paths (Unresponsive Caller, WhatsApp Session Timeout, completed claims) route through the Claims Supervisor via `transfer_to_agent`. Must not speak or act after a successful transfer — the Supervisor continues the conversation.
_Avoid_: The agent, the bot, the assistant

**Claims Supervisor**:
A second, separate registered Agent that the Claims Officer hands the call to once it believes intake is complete. Its only job is to re-verify completeness against the actual conversation transcript — not against the officer's own belief — and either confirm and lodge the claim, or collect whatever is genuinely missing. It is the only agent that ever tells a claimant their claim has been lodged.
_Avoid_: QA agent, reviewer, validator agent

**Transfer**:
The hand-off from the Claims Officer to the Claims Supervisor, via the `transfer_to_agent` mechanism — a genuine switch to a different Agent, not a change of persona within one agent. After a successful transfer, the officer must not speak again or call any further tools. The supervisor handles all remaining interaction including lodgement confirmation and call termination. See `docs/adr/0002-claims-supervisor-as-separate-agent.md` for the original architecture decision, and `docs/adr/0003-officer-end-call-restriction.md` for the revised handoff rules.
_Avoid_: Handoff (fine informally, but "Transfer" is the term used in config and should be used consistently in prompts/docs), escalation

**Completeness Check**:
The Claims Officer's own silent check of captured data against the required field set, performed as it collects fields. If fields are missing, the officer asks for them. After two failed attempts for any single field, the officer is expected to lodge with whatever is available. This is the Officer's own judgment and can be wrong — see Supervisor Review.
_Avoid_: Validation, data check

**Supervisor Review**:
A second, independent completeness check performed by the Claims Supervisor after the Transfer — re-reading the actual transcript rather than trusting the officer's self-assessment. Exists specifically because the officer's own Completeness Check can be wrong: the officer may believe a field was collected, or believe the claim is complete, when it wasn't, and may Transfer before intake is genuinely finished. Mirrors the officer's two-attempt-then-lodge-anyway rule for any fields it finds missing. The Supervisor Review can itself be wrong; see Completeness Guardrail.
_Avoid_: Second check, double-check, QA pass

**Completeness Guardrail**:
An automatic check on every agent response, independent of both the Officer and the Supervisor, that blocks — and forces a retry of — any response which ends the call or declares the claim lodged while a required field is genuinely absent from the transcript. The last line of defense if both the officer's and the supervisor's own completeness judgment are wrong. Configured identically on both agents.
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
