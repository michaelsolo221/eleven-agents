from typing import Any

from jinja2 import DictLoader, Environment, select_autoescape

FIELD_SPECS = [
    ("policy_number", "Policy Number"),
    ("claim_type", "Claim Type"),
    ("first_name", "First Name"),
    ("last_name", "Last Name"),
    ("contact_method", "Contact Method"),
    ("incident_datetime", "Incident Date & Time"),
    ("what_happened", "What Happened"),
    ("vehicle_registration", "Vehicle Registration"),
    ("property_address", "Property Address"),
    ("incident_location", "Incident Location"),
    ("nominated_representative", "Nominated Representative"),
]

KNOWN_CRITERIA = {
    "asks-vehicle-or-property-upfront": "Asks vehicle or property upfront",
    "collects-all-required-fields": "Collects all required fields",
    "confirms-name-spelling": "Confirms name spelling",
    "wraps-up-and-ends-call-when-complete": "Wraps up and ends call when complete",
}

EMAIL_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background-color: #f4f6f8;
    margin: 0;
    padding: 20px;
    color: #1f2937;
  }
  .container {
    max-width: 680px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    border: 1px solid #e5e7eb;
  }
  .header {
    background-color: #0f172a;
    color: #ffffff;
    padding: 24px;
  }
  .header h1 {
    margin: 0 0 8px 0;
    font-size: 20px;
    font-weight: 600;
  }
  .header .meta {
    font-size: 13px;
    color: #94a3b8;
  }
  .status-pill {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 9999px;
    font-size: 12px;
    font-weight: 600;
    margin-top: 8px;
  }
  .status-complete {
    background-color: #dcfce7;
    color: #166534;
  }
  .status-incomplete {
    background-color: #fef2f2;
    color: #991b1b;
  }
  .section {
    padding: 24px;
    border-bottom: 1px solid #e5e7eb;
  }
  .section:last-child {
    border-bottom: none;
  }
  .section-title {
    font-size: 16px;
    font-weight: 600;
    margin: 0 0 16px 0;
    color: #111827;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .summary-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }
  .summary-table th, .summary-table td {
    padding: 10px 12px;
    text-align: left;
    border-bottom: 1px solid #f3f4f6;
  }
  .summary-table tr:last-child td {
    border-bottom: none;
  }
  .summary-table th {
    width: 35%;
    color: #4b5563;
    font-weight: 500;
    background-color: #f9fafb;
  }
  .summary-table td {
    color: #111827;
    font-weight: 600;
  }
  .badge-grid {
    display: block;
    width: 100%;
  }
  .badge-card {
    display: block;
    width: 100%;
    box-sizing: border-box;
    margin-bottom: 12px;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px;
    background-color: #f9fafb;
  }
  .badge-card:last-child {
    margin-bottom: 0;
  }
  .badge-header {
    display: block;
    margin-bottom: 4px;
  }
  .badge-name {
    font-size: 13px;
    font-weight: 600;
    color: #374151;
  }
  .badge {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
  }
  .badge-pass {
    background-color: #dcfce7;
    color: #15803d;
  }
  .badge-fail {
    background-color: #fee2e2;
    color: #b91c1c;
  }
  .badge-unknown {
    background-color: #f3f4f6;
    color: #4b5563;
  }
  .badge-rationale {
    font-size: 12px;
    color: #6b7280;
    margin-top: 4px;
  }
  .transcript-container {
    display: block;
    width: 100%;
  }
  .turn {
    display: block;
    width: 100%;
    box-sizing: border-box;
    margin-bottom: 12px;
    padding: 12px 16px;
    border-radius: 8px;
    font-size: 14px;
    line-height: 1.5;
  }
  .turn:last-child {
    margin-bottom: 0;
  }
  .turn-caller {
    background-color: #eff6ff;
    border-left: 4px solid #3b82f6;
  }
  .turn-agent {
    background-color: #f0fdf4;
    border-left: 4px solid #22c55e;
  }
  .turn-system {
    background-color: #f3f4f6;
    border-left: 4px solid #9ca3af;
  }
  .turn-meta {
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 4px;
    color: #4b5563;
  }
  .turn-time {
    font-weight: normal;
    color: #9ca3af;
    margin-left: 8px;
  }
  .turn-message {
    color: #1f2937;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: break-word;
  }
  .summary-box {
    background-color: #fffbe0;
    border-left: 4px solid #eab308;
    padding: 12px 16px;
    border-radius: 4px;
    font-size: 14px;
    margin-bottom: 16px;
  }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>CGU Insurance — Claim Lodgement Report</h1>
    <div class="meta">Conversation ID: {{ conversation_id }}</div>
    {% if call_successful is not none %}
      {% if call_successful %}
        <span class="status-pill status-complete">COMPLETE</span>
      {% else %}
        <span class="status-pill status-incomplete">INCOMPLETE</span>
      {% endif %}
    {% endif %}
  </div>

  {% if summary_text %}
  <div class="section">
    <div class="section-title">Executive Summary</div>
    <div class="summary-box">{{ summary_text }}</div>
  </div>
  {% endif %}

  <!-- 1. Summary Table (11 fields) -->
  <div class="section">
    <div class="section-title">Claim Data Summary</div>
    <table class="summary-table">
      <tbody>
        {% for field in summary_fields %}
        <tr>
          <th>{{ field.label }}</th>
          <td>{{ field.value }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- 2. Evaluation Audit Badges -->
  <div class="section">
    <div class="section-title">Quality & Evaluation Audit</div>
    <div class="badge-grid" style="display: block; width: 100%;">
      {% for item in eval_badges %}
      <div class="badge-card" style="display: block; width: 100%;
           box-sizing: border-box; margin-bottom: 12px;">
          <span class="badge-name">{{ item.name }}</span>
          <span class="badge badge-{{ item.badge_class }}"
                style="margin-left: 8px;">{{ item.status }}</span>
        </div>
        {% if item.rationale %}
        <div class="badge-rationale" style="margin-top: 4px;">{{ item.rationale }}</div>
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- 3. Transcript Log -->
  <div class="section">
    <div class="section-title">Transcript Log</div>
    <div class="transcript-container" style="display: block; width: 100%;">
      {% for turn in transcript_turns %}
      <div class="turn turn-{{ turn.role_class }}" style="display: block;
           width: 100%; box-sizing: border-box; margin-bottom: 12px;">
          {{ turn.role }}
          {% if turn.time %}<span class="turn-time">[{{ turn.time }}]</span>{% endif %}
        </div>
        <div class="turn-message" style="white-space: pre-wrap;
             word-break: break-word; overflow-wrap: break-word;"
        >{{ turn.message }}</div>
      </div>
      {% endfor %}
    </div>
  </div>
</div>
</body>
</html>
"""

env = Environment(
    loader=DictLoader({"email.html": EMAIL_HTML_TEMPLATE}),
    autoescape=select_autoescape(
        enabled_extensions=("html", "xml"),
        default_for_string=True,
    ),
)


def _classify_result(res: Any) -> tuple[str, str]:
    """Maps a raw evaluation-criterion result value to (status, badge_class)."""
    if res in ("success", "pass", True, "PASS", "SUCCESS", "true"):
        return "PASS", "pass"
    if res in ("failure", "fail", False, "FAIL", "FAILURE", "false"):
        return "FAIL", "fail"
    return (str(res).upper() if res else "UNKNOWN"), "unknown"


def render_email_html(data: dict[str, Any]) -> str:
    """
    Renders the post-call email report HTML using Jinja2 with autoescaping.

    Accepts the full webhook payload dict or the inner 'data' payload dict.
    """
    d = data.get("data", data) if isinstance(data.get("data"), dict) else data

    conversation_id = str(d.get("conversation_id", "N/A"))
    analysis = d.get("analysis", {}) if isinstance(d.get("analysis"), dict) else {}

    call_successful_raw = analysis.get("call_successful")
    if isinstance(call_successful_raw, bool):
        call_successful: bool | None = call_successful_raw
    elif isinstance(call_successful_raw, str):
        call_successful = call_successful_raw.lower() in (
            "true",
            "success",
            "pass",
            "completed",
        )
    else:
        call_successful = None

    summary_text = str(analysis.get("transcript_summary", "")).strip()

    raw_data_col = analysis.get("data_collection_results", {})
    if not isinstance(raw_data_col, dict):
        raw_data_col = {}

    summary_fields = []
    for field_key, field_label in FIELD_SPECS:
        field_item = raw_data_col.get(field_key)
        if isinstance(field_item, dict):
            val = field_item.get("value")
        else:
            val = field_item

        if val is None or val == "":
            formatted_val = "Not provided"
        elif isinstance(val, bool):
            formatted_val = "Yes" if val else "No"
        else:
            formatted_val = str(val)

        summary_fields.append(
            {"key": field_key, "label": field_label, "value": formatted_val}
        )

    raw_eval = analysis.get("evaluation_criteria_results", {})
    if not isinstance(raw_eval, dict):
        raw_eval = {}

    eval_badges = []
    processed_criteria = set()

    for crit_key, crit_name in KNOWN_CRITERIA.items():
        processed_criteria.add(crit_key)
        crit_item = raw_eval.get(crit_key)
        if crit_item is not None:
            if isinstance(crit_item, dict):
                res = crit_item.get("result")
                rationale = str(crit_item.get("rationale", "")).strip()
            else:
                res = crit_item
                rationale = ""

            status, badge_class = _classify_result(res)
        else:
            status = "N/A"
            badge_class = "unknown"
            rationale = ""

        eval_badges.append(
            {
                "key": crit_key,
                "name": crit_name,
                "status": status,
                "badge_class": badge_class,
                "rationale": rationale,
            }
        )

    for crit_key, crit_item in raw_eval.items():
        if crit_key in processed_criteria:
            continue
        crit_name = crit_key.replace("-", " ").replace("_", " ").title()
        if isinstance(crit_item, dict):
            res = crit_item.get("result")
            rationale = str(crit_item.get("rationale", "")).strip()
        else:
            res = crit_item
            rationale = ""

        status, badge_class = _classify_result(res)

        eval_badges.append(
            {
                "key": crit_key,
                "name": crit_name,
                "status": status,
                "badge_class": badge_class,
                "rationale": rationale,
            }
        )

    raw_transcript = d.get("transcript", [])
    if not isinstance(raw_transcript, list):
        raw_transcript = []

    transcript_turns = []
    for turn in raw_transcript:
        if isinstance(turn, dict):
            role_raw = str(turn.get("role", "unknown")).lower()
            msg = str(
                turn.get("message") or turn.get("text") or turn.get("content") or ""
            )
            time_secs = turn.get("time_in_call_secs")
        else:
            role_raw = "unknown"
            msg = str(turn)
            time_secs = None

        if role_raw in ("user", "caller", "customer"):
            display_role = "Caller"
            role_class = "caller"
        elif role_raw in ("agent", "assistant", "bot"):
            display_role = "Agent (Amanda)"
            role_class = "agent"
        else:
            display_role = role_raw.capitalize()
            role_class = "system"

        time_str = None
        if time_secs is not None and isinstance(time_secs, (int, float)):
            mins = int(time_secs) // 60
            secs = int(time_secs) % 60
            time_str = f"{mins:02d}:{secs:02d}"

        transcript_turns.append(
            {
                "role": display_role,
                "role_class": role_class,
                "message": msg,
                "time": time_str,
            }
        )

    template = env.get_template("email.html")
    return template.render(
        conversation_id=conversation_id,
        call_successful=call_successful,
        summary_text=summary_text,
        summary_fields=summary_fields,
        eval_badges=eval_badges,
        transcript_turns=transcript_turns,
    )
