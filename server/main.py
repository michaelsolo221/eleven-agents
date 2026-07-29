import json
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status

from server.email_service import send_claim_email
from server.security import exceeds_max_body_size, verify_signature

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    if not secret and os.getenv("TESTING") != "true":
        msg = "ELEVENLABS_WEBHOOK_SECRET environment variable is missing"
        logger.critical(msg)
        raise RuntimeError(msg)

    from_email = os.getenv("FROM_EMAIL")
    if not from_email and os.getenv("TESTING") != "true":
        msg = "FROM_EMAIL environment variable is missing"
        logger.critical(msg)
        raise RuntimeError(msg)

    notification_email = os.getenv("NOTIFICATION_EMAIL")
    if not notification_email and os.getenv("TESTING") != "true":
        msg = "NOTIFICATION_EMAIL environment variable is missing"
        logger.critical(msg)
        raise RuntimeError(msg)

    yield


app = FastAPI(
    title="ElevenLabs Webhook Receiver", version="0.1.0", lifespan=lifespan
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    return {
        "git_sha": os.getenv("SOURCE_COMMIT", "unknown"),
        "app_version": app.version,
    }


@app.post("/api/webhooks/elevenlabs")
@app.post("/webhook/post-call")
async def elevenlabs_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> dict[str, str]:
    if exceeds_max_body_size(request.headers.get("content-length")):
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Payload too large",
        )

    secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    signature_header = request.headers.get("elevenlabs-signature")
    payload_bytes = await request.body()

    if not verify_signature(payload_bytes, signature_header, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    try:
        payload: dict[str, Any] = json.loads(payload_bytes)
    except Exception:
        logger.warning("Invalid JSON payload in webhook request", exc_info=True)
        return {"status": "ignored"}

    event_type = payload.get("type")
    if event_type != "post_call_transcription":
        return {"status": "ignored"}

    background_tasks.add_task(send_claim_email, payload)
    return {"status": "received"}
