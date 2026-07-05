# PRD: CGU Claims Lodgement Agent

## Problem Statement

CGU (Australian insurance company) currently handles all insurance claim lodgements through a traditional phone hotline. Customers who want to lodge a claim must call and wait in a queue for a human agent. There is no self-service option for straightforward claims, and the process is slow even for simple cases where the customer knows exactly what information to provide.

## Solution

A new ElevenLabs voice AI agent — the **Claims Lodgement Officer** — that handles insurance claim lodgement via phone and WhatsApp. The agent supports two interaction modes:

1. **Guided flow** — a conversational, step-by-step process where the agent asks for each required field
2. **Express lodgement** — the customer provides everything upfront in one message, the agent parses it, verifies name spelling, checks for missing fields, and lodges

Both modes converge on the same outcome: verify completeness, confirm the claim, fire a webhook for backend processing, and tell the customer to expect an email within 1 business day.

## User Stories

### Claimant — Vehicle Claim

1. As a claimant, I want to lodge a motor vehicle claim by phone, so that I don't have to wait in a queue for a human agent
2. As a claimant, I want to provide my vehicle registration number as the way to identify my car, so that the claim is linked to the correct insured asset
3. As a claimant, I want to describe where the car crash happened (incident location), so that the circumstances of the loss are recorded
4. As a claimant, I want to provide the date and time of the incident, so that CGU can establish the timeline of the loss
5. As a claimant, I want to provide either my email or phone number as a contact method, so that CGU can follow up with me
6. As a claimant, I want the agent to confirm the spelling of my first and last name, so that my details are recorded correctly

### Claimant — Property Claim

7. As a claimant, I want to lodge a property claim by providing my property address, so that the claim is linked to the correct insured asset
8. As a claimant, I want the property address to also serve as the incident location, so that I don't have to repeat myself

### Claimant — Express Lodgement

9. As a claimant who knows all their details, I want to dump all the information in one message, so that I can lodge my claim quickly without back-and-forth
10. As a claimant using express lodgement, I want the agent to still verify the spelling of my name, so that my details are recorded correctly even in the fast path

### Claimant — Guided Flow

11. As a claimant who doesn't know what information is needed, I want the agent to walk me through each required field one at a time, so that I don't miss anything
12. As a claimant using the guided flow, I want the agent to ask whether my claim is about a vehicle or a property upfront, so that the correct fields are requested

### Claimant — Incomplete Information

13. As a claimant who doesn't have my policy number, I want to still lodge a claim, so that CGU can look up my policy using my asset details later
14. As a claimant who can't provide a required field after two attempts, I want the agent to lodge the claim with whatever information I've given, so that I'm not stuck in an endless loop

### Claimant — Multiple Claims

15. As a claimant with two separate incidents (e.g., a car crash and a property event), I want to lodge both claims in the same conversation, so that I don't have to call back

### Claimant — Nominated Representative

16. As a family member calling on behalf of a policyholder, I want to lodge a claim as a nominated representative, so that I can help someone who can't call themselves
17. As a nominated representative, I want my name recorded as the contact person, so that CGU can reach me about the claim

### Claimant — Emergency

18. As a claimant who is currently in danger, I want the agent to immediately tell me to call 000 and end the interaction, so that I get the right help fast

### Claimant — Non-Claims Inquiry

19. As a caller who wants to check my claim status, I want to be redirected to the standard support line (1300 943 690), so that I reach the right team
20. As a caller redirected for a non-claims inquiry, I want the agent to ask if I also have a new claim to lodge, so that I can handle both in one call if needed

### Claimant — Unresponsive

21. As a caller who says nothing for 10 seconds, I want the agent to prompt me, so that I know the call is active
22. As a caller who remains unresponsive after prompting, I want the agent to end the call, so that I'm not left in a dead line

### Claimant — Post-Lodgement

23. As a claimant after lodging, I want to be told to expect an email within 1 business day with my claim number, so that I know what happens next

### Claimant — Mid-Lodgement Hang-Up

24. As a claimant who hangs up mid-lodgement, I want the webhook to fire with whatever information was collected so far, so that my partial claim is not lost

### Claimant — WhatsApp Session Timeout

25. As a WhatsApp claimant who stops responding for over 1 hour, I want the agent to end the session and tell me to start a new interaction, so that I'm not left in a stale conversation

### Claimant — Wrong Number / Non-Claimant

26. As a caller who dialled the wrong number, I want the agent to say thank you and end the call, so that I'm not stuck in a claims flow
27. As a caller making small talk with no intention to lodge a claim, I want the agent to allow brief pleasantries but gently steer toward claim lodgement, so that the interaction stays productive
28. As a caller who is clearly not lodging a claim and not making a non-claims inquiry, I want to be redirected to the general inquiry line (1300 943 690), so that I reach the right team

### Claimant — Channels

29. As a claimant, I want to lodge my claim via WhatsApp text message, so that I can use my preferred channel
30. As a claimant, I want to lodge my claim via phone call, so that I can speak naturally
31. As a claimant, I want the agent to handle both text and voice messages, so that I can switch between typing and speaking

## Implementation Decisions

### Agent Config

- Create a new agent config file `agent_configs/Claims-Lodgement-Officer.json` — do NOT modify the existing Support Agent (ADR 0001)
- Register the new agent in `agents.json`
- Create a test scenario in `test_configs/claims-lodgement-scenario.json`

### Agent Prompt Structure

The agent prompt should contain these sections:
- **Personality** — Amanda, a CGU claims lodgement officer
- **Environment** — phone and WhatsApp, text and voice
- **Tone** — professional, clear, efficient; empathetic when needed
- **Goal** — collect required claim fields, verify completeness, lodge the claim
- **Claim Types** — vehicle (identified by registration) or property (identified by address); ask upfront
- **Required Fields** — policy number (best-effort), what happened, date/time of incident, risk asset, incident location (vehicle only), contact method, first name, last name
- **Interaction Modes** — guided flow (ask one field at a time) vs express lodgement (parse what's given, verify name spelling, check for missing)
- **Verification** — name spelling always verified; silent completeness check against required fields; 2 attempts max per missing field then lodge with what's available
- **Guardrails** — emergency redirect to 000, non-claims redirect to 1300 943 690
- **Closing** — "I've lodged your claim, expect an email within 1 business day with your claim number"
- **Multiple Claims** — after lodging, ask if there's another claim
- **Unresponsive** — 10s wait, prompt, retry, hang up
- **WhatsApp Session Timeout** — 1 hour of inactivity on WhatsApp text → agent ends session with a message explaining the interaction is closing and to start a new one for a fresh claim
- **Mid-Lodgement Hang-Up** — if caller hangs up mid-lodgement, fire the webhook with whatever was collected so far; partial claim is not lost
- **One Asset Per Claim** — exactly one risk asset per claim; if multiple assets are mentioned, treat as separate claims
- **Small Talk** — allow brief pleasantries at the start; gently steer toward claim lodgement; if caller is clearly not lodging a claim and not making a non-claims inquiry, redirect to 1300 943 690
- **Wrong Number** — say thank you and end the call

### First Message

*"Hi, my name is Amanda. You've reached CGU claims lodgement. Can I help you lodge a new claim?"*

This gates the interaction: if the caller says "no" or asks about something else, redirect to 1300 943 690.

### Guardrails

- **Emergency detection** — trigger only on explicit "I'm in danger" / "unsafe right now" statements. Not on describing past events (e.g., "my house caught fire" is a valid claim, not an emergency)
- **Non-claims detection** — claim status, policy changes, complaints, general inquiries → redirect to 1300 943 690
- **Small talk / wrong number** — allow brief pleasantries; gently steer toward claim lodgement; wrong numbers get a polite goodbye and hang up; callers clearly not lodging and not making a non-claims inquiry → redirect to 1300 943 690
- **Content guardrails** — harassment and profanity thresholds at 0.5 (inherited from existing agent pattern)

### Post-Lodgement

- The agent's closing message triggers a post-call webhook (configured in `platform_settings.workspace_overrides.webhooks`)
- The webhook payload structure is out of scope for this PRD — tracked in [issue #2](https://github.com/michaelsolo221/eleven-agents/issues/2)

### Testing

- Create a test scenario that simulates a vehicle claim lodgement via guided flow
- Evaluation criteria: agent asks for vehicle/property upfront, collects all required fields, verifies name spelling, gives correct closing message
- Test both the happy path (all fields provided) and the missing-fields path (agent asks for missing info)

## Out of Scope

- **Backend claim processing** — the authorization API that processes claims after the webhook fires
- **Claim reference number generation** — handled by the backend, not the agent
- **Email/SMS sending** — handled by the backend
- **Payload structure and transcript-based multi-claim extraction** — tracked in [issue #2](https://github.com/michaelsolo221/eleven-agents/issues/2)
- **Policy lookup** — the agent does not query a policy system; headless claims are resolved by the backend using asset IDs
- **Multi-language support** — English only for the prototype
- **Claim status checking** — out of scope for this agent; redirected to 1300 943 690

## Further Notes

- The agent persona is "Amanda" — used in every greeting
- The agent should use Australian English (e.g., "rego" is acceptable colloquially, but the agent should use "registration" in its own speech)
- The `end_call` built-in tool should be available for emergency termination and unresponsive caller handling
- The LLM should be `gemini-2.5-flash` (matching the existing agent pattern) with temperature 0.7
