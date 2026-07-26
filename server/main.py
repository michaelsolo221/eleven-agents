import json
import logging
import os
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status

from server.email_service import send_claim_email
from server.security import verify_signature

logger = logging.getLogger(__name__)

app = FastAPI(title="ElevenLabs Webhook Receiver")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/webhooks/elevenlabs")
async def elevenlabs_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> dict[str, str]:
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
