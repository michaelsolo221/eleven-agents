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
The point of contact for the claim — whoever we can speak to. First name and last name required. Name spelling is always verified, even in express mode. May be the policyholder or a Nominated Representative.
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

**Completeness Check**:
A silent check of captured data against the required field set. If fields are missing, the agent asks for them. After two failed attempts for any single field, the agent lodges with whatever is available.
_Avoid_: Validation, data check

**Name Spelling Verification**:
The agent confirms the exact spelling of the claimant's first and last name. Always performed, regardless of interaction mode.
_Avoid_: Name confirmation, identity check

**Emergency Redirect**:
Immediate termination when the claimant states they are in danger or unsafe right now. The agent says to call 000 and ends the interaction.
_Avoid_: Crisis handling, safety escalation

**Non-Claims Redirect**:
When the claimant's request is not about lodging a new claim (e.g., claim status, policy changes, complaints), redirect to 1300 943 690 for standard telephone support.
_Avoid_: General inquiries redirect

**Session Timeout**:
On WhatsApp text interactions, the agent ends the session after 1 hour of claimant inactivity. The agent tells the claimant the interaction is closing and to start a new one for a fresh claim.
_Avoid_: Idle timeout, conversation expiry
