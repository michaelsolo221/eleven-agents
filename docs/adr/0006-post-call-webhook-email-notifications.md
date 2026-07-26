# ADR 0006: Post-Call Webhook & Email Notification Architecture

## Status

Accepted

## Context

The Claims Lodgement Officer ("Amanda") operates as a single voice/text agent on ElevenLabs for CGU Insurance. As documented in ADR 0004 and ADR 0005, the agent collects 8+ required claim fields and executes `end_call`.

However, the agent's captured data was trapped inside ElevenLabs platform analytics:
1. No external post-call processing occurred.
2. Claims officers and underwriters had no automatic mechanism to receive structured claim details or transcripts upon call completion.
3. Direct integration from ElevenLabs webhooks to email providers like Resend is technically impossible because ElevenLabs sends a fixed `post_call_transcription` JSON schema that does not match Resend's expected request payload (`from`, `to`, `subject`, `html`), and post-call webhooks do not support custom Bearer auth headers.

## Decision

We will implement a lightweight, co-located Python (FastAPI) **Post-Call Webhook Receiver** hosted on a VPS via **Coolify**, with email notifications delivered via **Resend**:

1. **Repository Placement**: The server application code will live inside **this repository** under `server/`. Co-locating the webhook receiver with the ElevenLabs agent configuration (`agent_configs/Claims-Lodgement-Officer.json`) ensures that any changes to data collection fields or evaluation criteria are versioned and validated together in a single atomic Git commit.
2. **Framework & Execution**: Python FastAPI with `uvicorn`. The receiver will verify incoming requests using HMAC SHA-256 signatures (`ElevenLabs-Signature`), schedule email dispatch asynchronously via FastAPI `BackgroundTasks`, and return an HTTP `200 OK` response within 50 milliseconds to prevent ElevenLabs webhook timeout retries.
3. **Email Provider**: **Resend** API via the official `resend` Python SDK. Initial setup will use `onboarding@resend.dev` to allow rapid testing without immediate DNS configuration, targeting `michael@michael-lo.com`.
4. **Call Disposition Subject Lines**: Email subject lines will explicitly tag the outcome disposition to give handlers instant visibility:
   - `[CGU FNOL - COMPLETE] Vehicle/Property Claim - <Name>`
   - `[CGU FNOL - INCOMPLETE] Partial Claim Data - <Reason>`
   - `[CGU FNOL - ALERT] Emergency Redirect (000 Called)`
   - `[CGU FNOL - REDIRECT] Non-Claims Inquiry`
5. **Email Content Structure**: The HTML body will include:
   - A structured summary table of all 11 extracted fields (`platform_settings.data_collection`).
   - Quality and evaluation pass/fail status badges.
   - Chronological transcript log formatted for readability.
6. **Deployment & Secrets**: Deployed to Coolify using a multi-stage Dockerfile. Environment secrets (`RESEND_API_KEY`, `ELEVENLABS_WEBHOOK_SECRET`, `NOTIFICATION_EMAIL`) will be managed securely within Coolify environment variables.

## Consequences

- The `server/` directory becomes part of the codebase, tested via `pytest` and Dockerized for Coolify.
- ElevenLabs agent config `workspace_overrides.webhooks.post_call_webhook_id` will reference the Coolify webhook endpoint URL.
- Zero external state machine complexity is added to the live voice conversation, preserving low latency while guaranteeing 100% post-call delivery of claims data and transcripts.

## References

- [ADR 0004: ElevenLabs Platform Evaluation for FNOL](./0004-elevenlabs-platform-evaluation-for-fnol.md)
- [ADR 0005: Retire Claims Supervisor](./0005-retire-claims-supervisor-single-agent-lodgement.md)
- [CONTEXT.md](../../CONTEXT.md)
