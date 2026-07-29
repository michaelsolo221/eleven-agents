import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.email_service import send_claim_email
from server.main import app
from server.templates import render_email_html
from server.tests.test_security import TEST_SECRET, create_signature_header

client = TestClient(app)


@pytest.fixture
def sample_payload() -> dict[str, Any]:
    return {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": "conv_test_12345",
            "agent_id": "agent_test_abc",
            "transcript": [
                {
                    "role": "agent",
                    "message": "Hi, my name is Amanda.",
                    "time_in_call_secs": 2,
                },
                {
                    "role": "user",
                    "message": "Hi Amanda, my car was rear-ended on George St.",
                    "time_in_call_secs": 10,
                },
            ],
            "metadata": {
                "termination_reason": "completed",
            },
            "analysis": {
                "call_successful": True,
                "transcript_summary": "Caller lodged a vehicle claim.",
                "evaluation_criteria_results": {
                    "asks-vehicle-or-property-upfront": {
                        "result": "success",
                        "rationale": "Asked vehicle vs property early",
                    },
                    "collects-all-required-fields": {
                        "result": "success",
                        "rationale": "Collected policy number and all claim details",
                    },
                    "confirms-name-spelling": {
                        "result": "pass",
                        "rationale": "Confirmed spelling of caller name",
                    },
                    "wraps-up-and-ends-call-when-complete": {
                        "result": "success",
                        "rationale": "Delivered promise and ended call",
                    },
                },
                "data_collection_results": {
                    "policy_number": {"value": "POL-987654"},
                    "claim_type": {"value": "vehicle"},
                    "first_name": {"value": "Jane"},
                    "last_name": {"value": "Doe"},
                    "contact_method": {"value": "0412345678"},
                    "incident_datetime": {"value": "2026-07-25 15:00"},
                    "what_happened": {"value": "Rear-ended at red light"},
                    "vehicle_registration": {"value": "1XYZ99"},
                    "property_address": {"value": None},
                    "incident_location": {"value": "George St, Sydney"},
                    "nominated_representative": {"value": False},
                },
            },
        },
    }


def test_render_email_html_basic(sample_payload: dict[str, Any]) -> None:
    html = render_email_html(sample_payload)

    assert "conv_test_12345" in html
    assert "COMPLETE" in html
    assert "POL-987654" in html
    assert "Vehicle" in html
    assert "Jane" in html
    assert "Doe" in html
    assert "1XYZ99" in html
    assert "George St, Sydney" in html
    assert "Asks vehicle or property upfront" in html
    assert "PASS" in html
    assert "Agent (Amanda)" in html
    assert "Caller" in html
    assert "my car was rear-ended on George St." in html


def test_render_email_html_escaping_hostile_input(
    sample_payload: dict[str, Any],
) -> None:
    # Inject hostile XSS input in transcript turn and data collection fields
    sample_payload["data"]["transcript"].append(
        {
            "role": "user",
            "message": '<script>alert("xss")</script> & <b>test</b>',
            "time_in_call_secs": 25,
        }
    )
    sample_payload["data"]["analysis"]["data_collection_results"]["first_name"] = {
        "value": "<img src=x onerror=alert(1)> \"Quoted\" & 'Single'"
    }

    html = render_email_html(sample_payload)

    # Unescaped scripts/tags MUST NOT be present
    assert '<script>alert("xss")</script>' not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert '<b style="color:red">dangerous</b>' not in html

    # Escaped HTML entities MUST be present
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&amp;" in html


def test_send_claim_email_complete_subject(
    sample_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key_123")
    monkeypatch.setenv("FROM_EMAIL", "claims@example.com")
    monkeypatch.setenv("NOTIFICATION_EMAIL", "test_recipient@example.com")

    sent_emails: list[dict[str, Any]] = []

    def mock_send(params: dict[str, Any]) -> dict[str, Any]:
        sent_emails.append(params)
        return {"id": "msg_12345"}

    monkeypatch.setattr("resend.Emails.send", mock_send)

    success = send_claim_email(sample_payload)
    assert success is True
    assert len(sent_emails) == 1

    email = sent_emails[0]
    assert email["to"] == ["test_recipient@example.com"]
    assert email["from"] == "claims@example.com"
    assert email["subject"] == "[CGU FNOL - COMPLETE] Vehicle Claim - Jane Doe"
    assert "conv_test_12345" in email["html"]


def test_send_claim_email_incomplete_subject(
    sample_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key_123")
    monkeypatch.setenv("FROM_EMAIL", "claims@example.com")
    monkeypatch.setenv("NOTIFICATION_EMAIL", "test_recipient@example.com")
    sample_payload["data"]["analysis"]["call_successful"] = False
    sample_payload["data"]["metadata"]["termination_reason"] = "unresponsive_caller"

    sent_emails: list[dict[str, Any]] = []

    def mock_send(params: dict[str, Any]) -> dict[str, Any]:
        sent_emails.append(params)
        return {"id": "msg_67890"}

    monkeypatch.setattr("resend.Emails.send", mock_send)

    success = send_claim_email(sample_payload)
    assert success is True
    assert len(sent_emails) == 1

    email = sent_emails[0]
    assert (
        email["subject"]
        == "[CGU FNOL - INCOMPLETE] Partial Claim Data - Unresponsive Caller"
    )


def test_send_claim_email_missing_api_key(
    sample_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("RESEND_API_KEY", raising=False)

    success = send_claim_email(sample_payload)
    assert success is False
    assert "RESEND_API_KEY environment variable is not set" in caplog.text


def test_send_claim_email_handles_exception_safely(
    sample_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key_123")
    monkeypatch.setenv("FROM_EMAIL", "claims@example.com")
    monkeypatch.setenv("NOTIFICATION_EMAIL", "test_recipient@example.com")

    def mock_send_fail(params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Resend API service error")

    monkeypatch.setattr("resend.Emails.send", mock_send_fail)

    success = send_claim_email(sample_payload)
    assert success is False
    assert (
        "Error sending claim email for conversation_id=conv_test_12345" in caplog.text
    )


def test_webhook_non_transcription_event_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", TEST_SECRET)

    # 1. post_call_audio event -> 200 ignored
    audio_payload = json.dumps({"type": "post_call_audio", "data": {}}).encode("utf-8")
    audio_sig = create_signature_header(audio_payload, TEST_SECRET)
    res_audio = client.post(
        "/api/webhooks/elevenlabs",
        content=audio_payload,
        headers={"ElevenLabs-Signature": audio_sig},
    )
    assert res_audio.status_code == 200
    assert res_audio.json() == {"status": "ignored"}

    # 2. call_initiation_failure event -> 200 ignored
    fail_payload = json.dumps({"type": "call_initiation_failure", "data": {}}).encode(
        "utf-8"
    )
    fail_sig = create_signature_header(fail_payload, TEST_SECRET)
    res_fail = client.post(
        "/api/webhooks/elevenlabs",
        content=fail_payload,
        headers={"ElevenLabs-Signature": fail_sig},
    )
    assert res_fail.status_code == 200
    assert res_fail.json() == {"status": "ignored"}

    # 3. missing type field -> 200 ignored
    empty_type_payload = json.dumps({"data": {}}).encode("utf-8")
    empty_type_sig = create_signature_header(empty_type_payload, TEST_SECRET)
    res_empty = client.post(
        "/api/webhooks/elevenlabs",
        content=empty_type_payload,
        headers={"ElevenLabs-Signature": empty_type_sig},
    )
    assert res_empty.status_code == 200
    assert res_empty.json() == {"status": "ignored"}


def test_webhook_rejects_oversized_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", TEST_SECRET)

    payload = b'{"type": "post_call_transcription", "data": {}}'
    sig_header = create_signature_header(payload, TEST_SECRET)

    response = client.post(
        "/api/webhooks/elevenlabs",
        content=payload,
        headers={
            "ElevenLabs-Signature": sig_header,
            "Content-Length": "3000000",
        },
    )
    assert response.status_code == 413


def test_webhook_post_call_transcription_dispatches(
    sample_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key_123")

    dispatched_payloads: list[dict[str, Any]] = []

    def mock_send_email(payload: dict[str, Any]) -> bool:
        dispatched_payloads.append(payload)
        return True

    monkeypatch.setattr("server.main.send_claim_email", mock_send_email)

    payload_bytes = json.dumps(sample_payload).encode("utf-8")
    sig_header = create_signature_header(payload_bytes, TEST_SECRET)

    response = client.post(
        "/api/webhooks/elevenlabs",
        content=payload_bytes,
        headers={"ElevenLabs-Signature": sig_header},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "received"}
    assert len(dispatched_payloads) == 1
    assert dispatched_payloads[0]["data"]["conversation_id"] == "conv_test_12345"


def test_send_claim_email_multiple_recipients(
    sample_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key_123")
    monkeypatch.setenv("FROM_EMAIL", "claims@example.com")
    monkeypatch.setenv(
        "NOTIFICATION_EMAIL",
        "  primary@example.com , secondary@example.com, third@example.com  ",
    )

    sent_emails: list[dict[str, Any]] = []

    def mock_send(params: dict[str, Any]) -> dict[str, Any]:
        sent_emails.append(params)
        return {"id": "msg_multirecipient"}

    monkeypatch.setattr("resend.Emails.send", mock_send)

    success = send_claim_email(sample_payload)
    assert success is True
    assert len(sent_emails) == 1

    email = sent_emails[0]
    assert email["to"] == [
        "primary@example.com",
        "secondary@example.com",
        "third@example.com",
    ]
    assert email["from"] == "claims@example.com"


def test_lifespan_requires_from_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.delenv("FROM_EMAIL", raising=False)
    monkeypatch.setenv("NOTIFICATION_EMAIL", "admin@example.com")
    monkeypatch.delenv("TESTING", raising=False)

    from server.main import lifespan

    fresh_app = FastAPI(
        title="ElevenLabs Webhook Receiver", version="0.1.0", lifespan=lifespan
    )

    with pytest.raises(RuntimeError, match="FROM_EMAIL"):
        with TestClient(fresh_app):
            pass


def test_lifespan_requires_notification_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setenv("FROM_EMAIL", "claims@example.com")
    monkeypatch.delenv("NOTIFICATION_EMAIL", raising=False)
    monkeypatch.delenv("TESTING", raising=False)

    from server.main import lifespan

    fresh_app = FastAPI(
        title="ElevenLabs Webhook Receiver", version="0.1.0", lifespan=lifespan
    )

    with pytest.raises(RuntimeError, match="NOTIFICATION_EMAIL"):
        with TestClient(fresh_app):
            pass
