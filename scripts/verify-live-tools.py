#!/usr/bin/env python3
"""Verify that every tool declared in a local agent config is actually present
on the live agent after push.

Exists because 'elevenlabs agents push' (CLI 0.5.4/0.5.5) has been observed to
silently drop certain tool entries (inline webhook tools, transfer_to_agent)
from the request it sends to the API, with no warning and no error — the push
reports success while the live agent quietly loses the tool. A direct PATCH to
the API does persist these correctly, so the bug is in the CLI's request
serialization, not the API. Until that's fixed upstream, this script closes
the gap: it re-fetches each agent from the live API after push and fails loudly
if a locally-declared tool didn't make it across.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_KEY = os.environ.get("ELEVENLABS_API_KEY")
errors = []


def fail(msg):
    errors.append(msg)
    print(f"  ✗ {msg}")


def ok(msg):
    print(f"  ✓ {msg}")


def fetch_live_agent(agent_id):
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}",
        headers={"xi-api-key": API_KEY},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def local_tool_names(config):
    prompt = config.get("conversation_config", {}).get("agent", {}).get("prompt", {})
    return {t["name"] for t in prompt.get("tools", []) if "name" in t}


def live_tool_names(agent):
    prompt = agent.get("conversation_config", {}).get("agent", {}).get("prompt", {})
    return {t["name"] for t in prompt.get("tools", []) if "name" in t}



def local_webhook_id(config):
    return config.get("platform_settings", {}).get("workspace_overrides", {}).get("webhooks", {}).get("post_call_webhook_id")


def live_webhook_id(agent):
    return agent.get("platform_settings", {}).get("workspace_overrides", {}).get("webhooks", {}).get("post_call_webhook_id")


def attached_test_ids(config):
    tests = config.get("platform_settings", {}).get("testing", {}).get("attached_tests", [])
    return {t["test_id"] for t in tests if "test_id" in t}

if not API_KEY:
    print("ELEVENLABS_API_KEY not set — skipping live verification")
    sys.exit(0)

agents_data = json.loads((ROOT / "agents.json").read_text())
for entry in agents_data.get("agents", []):
    config_path = ROOT / entry["config"]
    local = json.loads(config_path.read_text())
    expected_tools = local_tool_names(local)
    expected_webhook = local_webhook_id(local)
    expected_tests = attached_test_ids(local)
    if not expected_tools and not expected_webhook and not expected_tests:
        ok(f"{entry['config']}: no tools, webhook, or attached tests declared, nothing to verify")
        continue
    try:
        live = fetch_live_agent(entry["id"])
    except Exception as e:
        fail(f"{entry['config']}: could not fetch live agent {entry['id']} — {e}")
        continue
    if expected_tools:
        actual_tools = live_tool_names(live)
        missing = expected_tools - actual_tools
        if missing:
            fail(
                f"{entry['config']}: tool(s) {sorted(missing)} declared locally but "
                f"missing from the live agent {entry['id']} after push — the CLI "
                f"likely dropped them silently during push. Patch the API directly "
                f"to fix (see scripts/verify-live-tools.py docstring)."
            )
        else:
            ok(f"{entry['config']}: all {len(expected_tools)} declared tool(s) present live")
    if expected_webhook:
        live_wid = live_webhook_id(live)
        if live_wid != expected_webhook:
            fail(
                f"{entry['config']}: post_call_webhook_id mismatch — "
                f"local: {expected_webhook}, live: {live_wid}"
            )
        else:
            ok(f"{entry['config']}: post_call_webhook_id matches live")
    if expected_tests:
        live_tests = attached_test_ids(live)
        missing = expected_tests - live_tests
        if missing:
            fail(
                f"{entry['config']}: attached test(s) {sorted(missing)} declared locally "
                f"but missing from the live agent {entry['id']} after push — same CLI "
                f"silent-drop failure mode as tools/webhook (see #29, #35)."
            )
        else:
            ok(f"{entry['config']}: all {len(expected_tests)} attached test(s) present live")

print(f"\n{'='*40}")
if errors:
    print(f"FAILED — {len(errors)} error(s):")
    for e in errors:
        print(f"  • {e}")
    sys.exit(1)
else:
    print("All live tool checks passed")
