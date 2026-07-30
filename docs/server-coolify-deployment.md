# Server Deployment Guide: Coolify & VPS Architecture

This document describes the deployment architecture, configuration details, and provisioning procedures for the `server/` microservice (FastAPI post-call webhook receiver and Resend email dispatcher) hosted on Coolify per [ADR 0006](./adr/0006-post-call-webhook-email-notifications.md).

---

## 1. Coolify Infrastructure Registry

| Property | Value / UUID | Notes |
| :--- | :--- | :--- |
| **Coolify Host** | `https://app.coolify.io` | Cloud management dashboard |
| **Target Server** | `fb-messenger-oci` (`163.192.27.254`) | Server UUID: `m04wsokkcgww4ows4gocs84g` |
| **Project** | `fb-messenger` | Project UUID: `g8cgwcc0kgk0og4s0kokckw0` |
| **Environment** | `production` | Environment UUID: `kwook4w4gwkko8g48gkko44w` |
| **Application Name** | `eleven-agents-webhook` | Application UUID: `k4k417px3sezrd3wvvimygs2` |
| **Configured FQDN** | `https://11-p.michael-lo.com` | Traefik reverse proxy endpoint |
| **Base Directory** | `/server` | Root of Python `uv` app & Dockerfile |
| **Exposed Port** | `8000` | FastAPI container application port |

---

## 2. Authentication & Deploy Keys

The application builds from the private repository `michaelsolo221/eleven-agents.git` using a dedicated SSH deploy key:

* **GitHub Deploy Key**: `Coolify Deploy Key` (ID: `158473763`, read-only access on GitHub repository).
* **Coolify Private Key**: Registered in Coolify under Private Key UUID `zqe4pwvqbpx6zw7uwyee2a3m`.

---

## 3. Required Environment Variables

The following secrets are managed within Coolify environment variables (`PATCH /api/v1/applications/{uuid}/envs/bulk`):

* `ELEVENLABS_WEBHOOK_SECRET`: Secret key used to verify incoming `ElevenLabs-Signature` headers (`v0` scheme, 30-minute timestamp tolerance).
* `RESEND_API_KEY`: API key for delivering HTML email notifications via the Resend API.
* `FROM_EMAIL`: Sender address for Resend email notifications. Must be a verified domain in Resend (no sandbox fallback). **Live in production since 2026-07-29 (issue #55)** as `lodgement@claims.michael-lo.com`; the `onboarding@resend.dev` sandbox address from initial setup (ADR 0006) is no longer used anywhere.
* `NOTIFICATION_EMAIL`: Comma-separated list of recipient email addresses for post-call summaries and transcripts.

---

## 4. Triggering Deployments

Deployments can be triggered programmatically via the Coolify REST API:

```bash
# Trigger deployment for the microservice
curl -X POST "https://app.coolify.io/api/v1/deploy?uuid=k4k417px3sezrd3wvvimygs2" \
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
# Verify health directly against the server IP (with Host header)
curl -k -H "Host: 11-p.michael-lo.com" https://163.192.27.254/health
# Response: {"status":"ok"}
```

### Verifying Deployed Version

`/version` reports the git commit and app version baked into the running image, so you can confirm a deploy actually picked up the latest push instead of trusting the dashboard:

```bash
curl https://11-p.michael-lo.com/version
# Response: {"git_sha":"<commit sha>","app_version":"0.1.0"}
```

`git_sha` only populates if Coolify's **"Include Source Commit in Build"** toggle (per-application Advanced/General settings) is enabled — it's off by default to preserve Docker build caching. Without it, `git_sha` reports `"unknown"`. This is a one-time manual setting in the Coolify dashboard, not something the repo can set.

---

## 6. DNS Setup

To route external webhooks (e.g. from ElevenLabs) to the Coolify server:

* **Record Type**: `A`
* **Host / Subdomain**: `11-p` (for `11-p.michael-lo.com`)
* **Target IP**: `163.192.27.254` (VPS Server IP)
* **Live Webhook Endpoint**: `https://11-p.michael-lo.com/webhook/post-call`
