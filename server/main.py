import os

from fastapi import FastAPI, HTTPException, Request, status

from server.security import verify_signature

app = FastAPI(title="ElevenLabs Webhook Receiver")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/webhooks/elevenlabs")
async def elevenlabs_webhook(request: Request) -> dict[str, str]:
    secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    signature_header = request.headers.get("elevenlabs-signature")
    payload = await request.body()

    if not verify_signature(payload, signature_header, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    return {"status": "received"}
