#!/usr/bin/env python3
"""Local config validation for CI. Catches structural issues without deploying."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors = []

def fail(msg):
    errors.append(msg)
    print(f"  ✗ {msg}")

def ok(msg):
    print(f"  ✓ {msg}")

# --- 1. Validate agents.json structure ---
print("agents.json")
try:
    agents_data = json.loads((ROOT / "agents.json").read_text())
    agent_list = agents_data.get("agents", [])
    if not agent_list:
        fail("agents.json: 'agents' array is empty")
    for i, entry in enumerate(agent_list):
        for field in ("config", "id", "version_id", "branch_id"):
            if field not in entry:
                fail(f"agents.json: agents[{i}] missing '{field}'")
    ok(f"{len(agent_list)} agent(s) defined")
except (json.JSONDecodeError, KeyError) as e:
    fail(f"agents.json: {e}")

# --- 2. Validate agent configs ---
print("\nagent_configs/")
agent_ids = set()
for entry in agent_list:
    config_path = ROOT / entry["config"]
    agent_ids.add(entry["id"])
    if not config_path.exists():
        fail(f"{entry['config']}: file does not exist")
        continue
    try:
        data = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        fail(f"{entry['config']}: invalid JSON — {e}")
        continue
    # Required top-level fields
    if "name" not in data:
        fail(f"{entry['config']}: missing 'name'")
    if "conversation_config" not in data:
        fail(f"{entry['config']}: missing 'conversation_config'")
    else:
        cc = data["conversation_config"]
        if "agent" not in cc:
            fail(f"{entry['config']}: conversation_config missing 'agent'")
        elif "prompt" not in cc["agent"]:
            fail(f"{entry['config']}: conversation_config.agent missing 'prompt'")
    ok(f"{entry['config']}")

# --- 3. Validate tests.json ---
print("\ntests.json")
try:
    tests_data = json.loads((ROOT / "tests.json").read_text())
    test_list = tests_data.get("tests", [])
    if not test_list:
        fail("tests.json: 'tests' array is empty")
    for i, entry in enumerate(test_list):
        for field in ("config", "id", "type"):
            if field not in entry:
                fail(f"tests.json: tests[{i}] missing '{field}'")
    ok(f"{len(test_list)} test(s) defined")
except (json.JSONDecodeError, KeyError) as e:
    fail(f"tests.json: {e}")

# --- 4. Validate test configs ---
print("\ntest_configs/")
test_configs_dir = ROOT / "test_configs"
for entry in test_list:
    config_path = ROOT / entry["config"]
    if not config_path.exists():
        fail(f"{entry['config']}: file does not exist")
        continue
    try:
        data = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        fail(f"{entry['config']}: invalid JSON — {e}")
        continue
    # Required fields
    for field in ("name", "type", "chat_history", "success_condition"):
        if field not in data:
            fail(f"{entry['config']}: missing '{field}'")
    # chat_history must be non-empty array — except for `simulation` tests,
    # where an empty array is the normal fresh-start case (the simulated
    # user persona drives the conversation instead of scripted turns).
    if data.get("type") != "simulation":
        history = data.get("chat_history", [])
        if not isinstance(history, list) or len(history) == 0:
            fail(f"{entry['config']}: 'chat_history' must be a non-empty array")
    else:
        scenario = data.get("simulation_scenario")
        if not isinstance(scenario, str) or not scenario.strip():
            fail(f"{entry['config']}: 'simulation' test missing non-empty 'simulation_scenario'")
    ok(f"{entry['config']}")

# --- 5. Check for orphaned files ---
print("\nOrphan check")
config_files = {e["config"] for e in agent_list}
test_files = {e["config"] for e in test_list}
for p in sorted((ROOT / "agent_configs").glob("*.json")):
    rel = f"agent_configs/{p.name}"
    if rel not in config_files:
        fail(f"{rel}: exists on disk but not in agents.json")
for p in sorted(test_configs_dir.glob("*.json")):
    rel = f"test_configs/{p.name}"
    if rel not in test_files:
        fail(f"{rel}: exists on disk but not in tests.json")
ok("no orphaned config files")

# --- 6. Check attached_tests reference real tests.json entries ---
print("\nAttached-test cross-reference check")
test_ids = {e["id"] for e in test_list}
errors_before = len(errors)
for entry in agent_list:
    config_path = ROOT / entry["config"]
    if not config_path.exists():
        continue
    data = json.loads(config_path.read_text())
    attached = data.get("platform_settings", {}).get("testing", {}).get("attached_tests", [])
    referenced = set(data.get("platform_settings", {}).get("testing", {}).get("referenced_tests_ids", []))
    attached_ids = {t["test_id"] for t in attached if "test_id" in t}
    orphans = attached_ids - test_ids
    if orphans:
        fail(f"{entry['config']}: attached_tests {sorted(orphans)} not found in tests.json")
    mismatch = attached_ids.symmetric_difference(referenced)
    if mismatch:
        fail(f"{entry['config']}: attached_tests and referenced_tests_ids disagree on {sorted(mismatch)}")
if len(errors) == errors_before:
    ok("all attached_tests entries resolve to tests.json")

# --- 7. Check webhook configuration integrity ---
print("\nWebhook configuration check")
WEBHOOK_ID_RE = re.compile(r"^[0-9a-f]{32}$")
errors_before = len(errors)
for entry in agent_list:
    config_path = ROOT / entry["config"]
    if not config_path.exists():
        continue
    data = json.loads(config_path.read_text())
    webhooks = data.get("platform_settings", {}).get("workspace_overrides", {}).get("webhooks", {})
    if not webhooks:
        continue
    webhook_id = webhooks.get("post_call_webhook_id")
    if not webhook_id or not isinstance(webhook_id, str):
        fail(f"{entry['config']}: webhooks block present but 'post_call_webhook_id' is missing or empty")
    elif not WEBHOOK_ID_RE.match(webhook_id):
        fail(
            f"{entry['config']}: post_call_webhook_id '{webhook_id}' doesn't look like a real "
            "ElevenLabs webhook ID (expected 32 lowercase hex chars) — check for a placeholder or typo"
        )
    events = webhooks.get("events")
    if not isinstance(events, list) or not events:
        fail(f"{entry['config']}: webhooks.events must be a non-empty array")
if len(errors) == errors_before:
    ok("all webhooks entries are well-formed")

# --- Summary ---
print(f"\n{'='*40}")
if errors:
    print(f"FAILED — {len(errors)} error(s):")
    for e in errors:
        print(f"  • {e}")
    sys.exit(1)
else:
    print("All validations passed")
