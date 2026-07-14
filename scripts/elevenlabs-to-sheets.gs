/**
 * ElevenLabs Post-Call Webhook → Google Sheets
 * =============================================
 * Receives ElevenLabs post_call_transcription events and appends one row
 * per conversation to the active sheet.
 *
 * SECURITY: Set WEBHOOK_SECRET below to your ElevenLabs webhook signing
 * secret (Agent → Settings → Post-call webhook → Signing secret).
 * This prevents anyone without the secret from posting to this endpoint.
 *
 * DEPLOYMENT:
 * 1. Open your Google Sheet → Extensions → Apps Script → paste this file
 * 2. Deploy → New deployment → Web App
 *    - Execute as: Me, Who has access: Anyone
 * 3. Copy the Web App URL
 * 4. ElevenLabs Dashboard → Agent → Post-call webhook → paste URL
 */

var WEBHOOK_SECRET = ""; // 👈 SET THIS to your ElevenLabs webhook signing secret

function doPost(e) {
  try {
    // --- HMAC signature verification ---
    if (WEBHOOK_SECRET) {
      var sigHeader = e.parameter.sig || "";
      var computed = Utilities.computeHmacSha256Signature(e.postData.contents, WEBHOOK_SECRET);
      var computedHex = computed.map(function(b) { return ("0" + (b & 0xFF).toString(16)).slice(-2); }).join("");
      if (sigHeader !== computedHex) {
        return error("Invalid signature");
      }
    }

    var payload = JSON.parse(e.postData.contents);
    // Only process post_call_transcription events
    if (payload.type !== "post_call_transcription") {
      return ok({ skipped: true, type: payload.type });
    }

    var d = payload.data;
    var meta = d.metadata || {};
    var analysis = d.analysis || {};
    var evalResults = analysis.evaluation_criteria_results || {};
    var dataResults = analysis.data_collection_results || {};
    var feedback = meta.feedback || {};

    var row = [
      // --- Identity ---
      d.conversation_id,
      d.agent_id,
      iso(meta.start_time_unix_secs),
      meta.call_duration_secs,

      // --- Outcome ---
      d.status,
      analysis.call_successful,
      analysis.call_success_score,
      meta.termination_reason || "",

      // --- Evaluation Criteria (7) ---
      evalResult(evalResults, "asks-vehicle-or-property-upfront"),
      evalResult(evalResults, "collects-all-required-fields"),
      evalResult(evalResults, "verifies-name-spelling"),
      evalResult(evalResults, "transfers-to-supervisor-when-complete"),
      evalResult(evalResults, "supervisor-verifies-against-transcript"),
      evalResult(evalResults, "supervisor-respects-retry-cap"),
      evalResult(evalResults, "gives-correct-closing-message"),

      // --- Extracted Data Fields (10) ---
      dataValue(dataResults, "policy_number"),
      dataValue(dataResults, "what_happened"),
      dataValue(dataResults, "incident_datetime"),
      dataValue(dataResults, "claim_type"),
      dataValue(dataResults, "vehicle_registration"),
      dataValue(dataResults, "property_address"),
      dataValue(dataResults, "incident_location"),
      dataValue(dataResults, "contact_method"),
      dataValue(dataResults, "first_name"),
      dataValue(dataResults, "last_name"),

      // --- Summary ---
      truncate(analysis.transcript_summary, 500),

      // --- Feedback ---
      feedback.overall_score || "",
      feedback.comment || "",

      // --- Channel ---
      meta.conversation_initiation_source || "",
    ];

    SpreadsheetApp.getActiveSpreadsheet().getActiveSheet().appendRow(row);
    return ok({ rows: 1, conversation_id: d.conversation_id });

  } catch (err) {
    return error(err);
  }
}

// Test endpoint — visit the URL in a browser to confirm it's live
function doGet(e) {
  return ok({ status: "ElevenLabs → Google Sheets webhook is live" });
}

// --- Helpers ---

function evalResult(results, id) {
  var r = results[id];
  return r ? r.result : "";
}

function dataValue(results, id) {
  var v = results[id];
  return v != null ? v : "";
}

function iso(unix) {
  return unix ? new Date(unix * 1000).toISOString() : "";
}

function truncate(str, len) {
  return (str || "").substring(0, len);
}

function ok(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function error(err) {
  return ContentService.createTextOutput(JSON.stringify({
    status: "error",
    message: err.toString()
  })).setMimeType(ContentService.MimeType.JSON);
}
