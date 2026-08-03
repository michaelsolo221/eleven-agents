import logging
import os
from typing import Any

import resend
from tenacity import retry, stop_after_attempt, wait_random_exponential

from server.templates import render_email_html

logger = logging.getLogger(__name__)


@retry(
    wait=wait_random_exponential(min=1, max=10),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _send_email_with_retry(email_params: resend.Emails.SendParams) -> Any:
    return resend.Emails.send(email_params)


def send_claim_email(payload: dict[str, Any]) -> bool:
    """
    Sends a post-call claim email report asynchronously via Resend.

    Formats the subject line according to call disposition (COMPLETE vs INCOMPLETE)
    and renders an HTML email using Jinja2 with autoescaping. Catches all exceptions,
    logs any error with conversation_id, and returns False on failure.
    """
    d = (
        payload.get("data", payload)
        if isinstance(payload.get("data"), dict)
        else payload
    )
    conversation_id = str(d.get("conversation_id", "unknown"))

    try:
        resend_api_key = os.getenv("RESEND_API_KEY")
        if not resend_api_key:
            logger.warning(
                "RESEND_API_KEY environment variable is not set; "
                "email dispatch skipped for conversation_id=%s",
                conversation_id,
            )
            return False

        resend.api_key = resend_api_key

        analysis = d.get("analysis", {}) if isinstance(d.get("analysis"), dict) else {}
        metadata = d.get("metadata", {}) if isinstance(d.get("metadata"), dict) else {}
        data_col = (
            analysis.get("data_collection_results", {})
            if isinstance(analysis.get("data_collection_results"), dict)
            else {}
        )

        is_complete = False
        cs_raw = analysis.get("call_successful")
        if isinstance(cs_raw, bool):
            is_complete = cs_raw
        elif isinstance(cs_raw, str):
            is_complete = cs_raw.lower() in (
                "true",
                "success",
                "pass",
                "completed",
            )
        else:
            eval_results = analysis.get("evaluation_criteria_results", {})
            if isinstance(eval_results, dict):
                all_req = eval_results.get("collects-all-required-fields", {})
                if isinstance(all_req, dict) and all_req.get("result") in (
                    "success",
                    "pass",
                    True,
                    "SUCCESS",
                    "PASS",
                ):
                    is_complete = True

        if is_complete:
            claim_type_raw = str(
                data_col.get("claim_type", {}).get("value")
                if isinstance(data_col.get("claim_type"), dict)
                else data_col.get("claim_type") or ""
            ).strip()

            if "vehicle" in claim_type_raw.lower():
                claim_type_label = "Vehicle Claim"
            elif "property" in claim_type_raw.lower():
                claim_type_label = "Property Claim"
            elif claim_type_raw:
                claim_type_label = f"{claim_type_raw.capitalize()} Claim"
            else:
                claim_type_label = "Vehicle/Property Claim"

            first_name = str(
                data_col.get("first_name", {}).get("value")
                if isinstance(data_col.get("first_name"), dict)
                else data_col.get("first_name") or ""
            ).strip()
            last_name = str(
                data_col.get("last_name", {}).get("value")
                if isinstance(data_col.get("last_name"), dict)
                else data_col.get("last_name") or ""
            ).strip()
            name_parts = [p for p in [first_name, last_name] if p]
            name_str = " ".join(name_parts) if name_parts else "Unknown Claimant"

            subject = f"[CGU FNOL - COMPLETE] {claim_type_label} - {name_str}"
        else:
            termination_reason = str(metadata.get("termination_reason", "")).strip()
            if termination_reason:
                reason = termination_reason.replace("_", " ").title()
            else:
                reason = "Incomplete Claim Data"
            subject = f"[CGU FNOL - INCOMPLETE] Partial Claim Data - {reason}"

        html_content = render_email_html(payload)

        from_email = os.getenv("FROM_EMAIL")
        if not from_email:
            logger.warning(
                "FROM_EMAIL environment variable is not set; "
                "email dispatch skipped for conversation_id=%s",
                conversation_id,
            )
            return False

        notification_email = os.getenv("NOTIFICATION_EMAIL")
        if not notification_email:
            logger.warning(
                "NOTIFICATION_EMAIL environment variable is not set; "
                "email dispatch skipped for conversation_id=%s",
                conversation_id,
            )
            return False

        to_emails = [
            addr.strip()
            for addr in notification_email.split(",")
            if addr.strip()
        ]

        _send_email_with_retry(
            {
                "from": from_email,
                "to": to_emails,
                "subject": subject,
                "html": html_content,
            }
        )
        logger.info(
            "Successfully dispatched claim email for conversation_id=%s, subject=%s",
            conversation_id,
            subject,
        )
        return True
    except Exception as e:
        logger.error(
            "Error sending claim email for conversation_id=%s: %s",
            conversation_id,
            e,
            exc_info=True,
        )
        return False
