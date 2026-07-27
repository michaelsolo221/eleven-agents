import os

os.environ["TESTING"] = "true"

import hmac
import time

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.security import (
    TIMESTAMP_TOLERANCE_SECONDS,
    signed_message,
    verify_signature,
)

client = TestClient(app)
TEST_SECRET = "test_webhook_secret_123"


def create_signature_header(
    payload: bytes, secret: str, timestamp: str | None = None
) -> str:
    timestamp = timestamp or str(int(time.time()))
    msg = signed_message(timestamp, payload)
    sig = hmac.new(secret.encode("utf-8"), msg, "sha256").hexdigest()
    return f"t={timestamp},v0={sig}"


def test_health_check() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_verify_signature_unit() -> None:
    payload = b'{"event": "call_ended", "call_id": "123"}'

    # Valid signature
    sig_header = create_signature_header(payload, TEST_SECRET)
    assert verify_signature(payload, sig_header, TEST_SECRET) is True

    # Invalid signature hash
    stale_ts = str(int(time.time()))
    bad_header = f"t={stale_ts},v0=invalidhash12345"
    assert verify_signature(payload, bad_header, TEST_SECRET) is False

    # Missing secret
    assert verify_signature(payload, sig_header, None) is False
    assert verify_signature(payload, sig_header, "") is False

    # Missing header
    assert verify_signature(payload, None, TEST_SECRET) is False
    assert verify_signature(payload, "", TEST_SECRET) is False

    # Malformed header
    assert verify_signature(payload, "invalid_header_format", TEST_SECRET) is False
    assert verify_signature(payload, f"t={stale_ts}", TEST_SECRET) is False
    assert verify_signature(payload, "v0=abc123", TEST_SECRET) is False


def test_verify_signature_rejects_expired_timestamp() -> None:
    payload = b'{"event": "call_ended", "call_id": "123"}'
    expired_ts = str(int(time.time()) - TIMESTAMP_TOLERANCE_SECONDS - 1)
    sig_header = create_signature_header(payload, TEST_SECRET, timestamp=expired_ts)

    assert verify_signature(payload, sig_header, TEST_SECRET) is False


def test_webhook_valid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", TEST_SECRET)
    payload = b'{"type": "post_call_transcription", "data": "test"}'
    sig_header = create_signature_header(payload, TEST_SECRET)

    response = client.post(
        "/api/webhooks/elevenlabs",
        content=payload,
        headers={"ElevenLabs-Signature": sig_header},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "received"}


def test_webhook_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", TEST_SECRET)
    payload = b'{"event": "call_ended"}'
    bad_header = f"t={int(time.time())},v0=wrong_signature"

    response = client.post(
        "/api/webhooks/elevenlabs",
        content=payload,
        headers={"ElevenLabs-Signature": bad_header},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid signature"}


def test_webhook_missing_signature_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", TEST_SECRET)
    payload = b'{"event": "call_ended"}'

    response = client.post(
        "/api/webhooks/elevenlabs",
        content=payload,
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid signature"}


def test_webhook_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_WEBHOOK_SECRET", raising=False)
    payload = b'{"event": "call_ended"}'
    sig_header = create_signature_header(payload, TEST_SECRET)

    response = client.post(
        "/api/webhooks/elevenlabs",
        content=payload,
        headers={"ElevenLabs-Signature": sig_header},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid signature"}


def test_lifespan_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from server.main import lifespan

    async def run_lifespan() -> None:
        async with lifespan(app):
            pass

    monkeypatch.delenv("ELEVENLABS_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TESTING", raising=False)
    with pytest.raises(
        RuntimeError, match="ELEVENLABS_WEBHOOK_SECRET environment variable is missing"
    ):
        asyncio.run(run_lifespan())


def test_lifespan_with_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import asyncio

    from server.main import lifespan

    async def run_lifespan() -> None:
        async with lifespan(app):
            pass

    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", TEST_SECRET)
    with caplog.at_level("WARNING"):
        asyncio.run(run_lifespan())
    assert (
        "ELEVENLABS_WEBHOOK_SECRET environment variable is not set" not in caplog.text
    )
