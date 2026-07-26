import hashlib
import hmac
import logging
import time

logger = logging.getLogger(__name__)

TIMESTAMP_TOLERANCE_SECONDS = 300  # 5 min, per ElevenLabs' replay-attack guidance


def signed_message(timestamp: str, payload: bytes) -> bytes:
    """Builds the message ElevenLabs signs: "<timestamp>.<payload>"."""
    return f"{timestamp}.".encode() + payload


def verify_signature(
    payload: bytes, signature_header: str | None, secret: str | None
) -> bool:
    """
    Verifies an ElevenLabs webhook HMAC SHA-256 signature.

    Header format: t=<timestamp>,v0=<signature_hash>
    Signed message: <timestamp>.<payload_str>
    """
    if not secret or not signature_header or payload is None:
        return False

    try:
        parts = {}
        for item in signature_header.split(","):
            if "=" in item:
                key, val = item.strip().split("=", 1)
                parts[key.strip()] = val.strip()

        timestamp = parts.get("t")
        signature_hash = parts.get("v0")

        if not timestamp or not signature_hash:
            return False

        if abs(time.time() - int(timestamp)) > TIMESTAMP_TOLERANCE_SECONDS:
            return False

        expected_hash = hmac.new(
            secret.encode("utf-8"), signed_message(timestamp, payload), hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_hash, signature_hash)
    except Exception:
        logger.warning("Failed to parse/verify webhook signature", exc_info=True)
        return False
