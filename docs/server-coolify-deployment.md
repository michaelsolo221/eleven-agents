# Server Deployment Guide: Coolify & VPS Architecture

This document describes the deployment architecture, configuration details, and provisioning procedures for the `server/` microservice (FastAPI post-call webhook receiver and Resend email dispatcher) hosted on Coolify per [ADR 0006](./adr/0006-post-call-webhook-email-notifications.md).

---

## 1. Coolify Infrastructure Registry

Server, project, environment, and application UUIDs, plus the VPS IP and
configured FQDN, are **deliberately not committed here** — they're
infrastructure-identifying details with no reason to sit in a git history
that outlives any single deployment. Look them up directly in the Coolify
dashboard (Servers / Projects / Applications) when you need them.

| Property | Notes |
| :--- | :--- |
| **Coolify Host** | `https://app.coolify.io` — cloud management dashboard |
| **Target Server** | `fb-messenger-oci` — server/project/environment UUIDs live in the Coolify dashboard |
| **Project** | `fb-messenger` |
| **Environment** | `production` |
| **Application Name** | `eleven-agents-webhook` — its UUID is stored as the `COOLIFY_APP_UUID` GitHub Actions repo variable (`gh variable list`), consumed by `scripts/deploy-and-verify-coolify.py` |
| **Configured FQDN** | Stored as the `COOLIFY_VERSION_URL` repo variable (`.../version`) — the same host serves `/health` and `/webhook/post-call` |
| **Base Directory** | `/server` — root of Python `uv` app & Dockerfile |
| **Exposed Port** | `8000` — FastAPI container application port |

---

## 2. Authentication & Deploy Keys

The application builds from this repository using a dedicated, read-only
SSH deploy key registered in Coolify (Coolify → Sources). Key ID and the
Coolify Private Key UUID are visible in the Coolify dashboard — not
committed here, same reasoning as §1.

---

## 3. Required Environment Variables

The following secrets are managed within Coolify environment variables (`PATCH /api/v1/applications/{uuid}/envs/bulk`):

* `ELEVENLABS_WEBHOOK_SECRET`: Secret key used to verify incoming `ElevenLabs-Signature` headers (`v0` scheme, 30-minute timestamp tolerance).
* `RESEND_API_KEY`: API key for delivering HTML email notifications via the Resend API.
* `FROM_EMAIL`: Sender address for Resend email notifications. Must be a verified domain in Resend (no sandbox fallback). **Live in production since 2026-07-29 (issue #55)** on a verified custom domain; the `onboarding@resend.dev` sandbox address from initial setup (ADR 0006) is no longer used anywhere.
* `NOTIFICATION_EMAIL`: Comma-separated list of recipient email addresses for post-call summaries and transcripts.

---

## 4. Triggering Deployments

Deployments can be triggered programmatically via the Coolify REST API:

```bash
# Trigger deployment for the microservice — $COOLIFY_APP_UUID is the
# COOLIFY_APP_UUID GitHub Actions repo variable (gh variable list), or
# look the UUID up in the Coolify dashboard
curl -X POST "https://app.coolify.io/api/v1/deploy?uuid=$COOLIFY_APP_UUID" \
  -H "Authorization: Bearer <COOLIFY_API_TOKEN>"
```

### Checking Deployment Status & Logs
```bash
# Check status of a deployment
curl -s -H "Authorization: Bearer <COOLIFY_API_TOKEN>" \
  "https://app.coolify.io/api/v1/deployments/<DEPLOYMENT_UUID>" | jq '{status, updated_at}'
```

---

## 5. Health Verification & Testing

The microservice includes a lightweight `/health` check endpoint that returns HTTP 200 OK without requiring authentication:

```bash
# Verify health directly against the server IP (with Host header) — get
# the IP and FQDN from the Coolify dashboard
curl -k -H "Host: <configured-fqdn>" https://<vps-ip>/health
# Response: {"status":"ok"}
```

### Verifying Deployed Version

`/version` reports the git commit and app version baked into the running image, so you can confirm a deploy actually picked up the latest push instead of trusting the dashboard. `$COOLIFY_VERSION_URL` is the `COOLIFY_VERSION_URL` GitHub Actions repo variable:

```bash
curl "$COOLIFY_VERSION_URL"
# Response: {"git_sha":"<commit sha>","app_version":"0.1.0"}
```

`git_sha` only populates if Coolify's **"Include Source Commit in Build"** toggle (per-application Advanced/General settings) is enabled — it's off by default to preserve Docker build caching. Without it, `git_sha` reports `"unknown"`. This is a one-time manual setting in the Coolify dashboard, not something the repo can set.

---

## 6. DNS Setup

To route external webhooks (e.g. from ElevenLabs) to the Coolify server:

* **Record Type**: `A`
* **Host / Subdomain**: see the Coolify dashboard's domain settings for the app
* **Target IP**: the VPS server IP — see the Coolify dashboard, not committed here
* **Live Webhook Endpoint**: `https://<configured-fqdn>/webhook/post-call`
