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

Always fetches by branch tip (defaulting to "Main", every agent's permanent
production branch), never the unqualified GET /v1/convai/agents/{id}. That
unqualified form was found (2026-07-29, issue #55) to reflect draft/in-progress
edits rather than the actually-committed version real conversations run
against — it gave a false "matches live" for post_call_webhook_id right after
a push whose committed version still held the stale value, and only a
follow-up dashboard commit actually fixed it. Fetching by branch_id returns the
branch's last *committed* version, which is what a real call actually uses.
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_KEY = os.environ.get("ELEVENLABS_API_KEY")
API_BASE = "https://api.elevenlabs.io"
errors = []


def fail(msg):
    errors.append(msg)
    print(f"  ✗ {msg}")


def ok(msg):
    print(f"  ✓ {msg}")


def find_branch_id(agent_id, branch_name):
    url = f"{API_BASE}/v1/convai/agents/{agent_id}/branches"
    req = urllib.request.Request(url, headers={"xi-api-key": API_KEY})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  (error listing branches for {agent_id}: {e})")
        return None
    for key in ("branches", "items", "results"):
        for branch in data.get(key, []):
            if branch.get("name") == branch_name:
                return branch["id"]
    return None

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


def local_webhook_events(config):
    return config.get("platform_settings", {}).get("workspace_overrides", {}).get("webhooks", {}).get("events", [])


def live_webhook_events(agent):
    return agent.get("platform_settings", {}).get("workspace_overrides", {}).get("webhooks", {}).get("events", [])


def transfer_conditions(config):
    """Map transfer target agent_id -> condition text, for every transfer_to_agent tool."""
    prompt = config.get("conversation_config", {}).get("agent", {}).get("prompt", {})
    conditions = {}
    for tool in prompt.get("tools", []):
        if tool.get("params", {}).get("system_tool_type") != "transfer_to_agent":
            continue
        for transfer in tool["params"].get("transfers", []):
            conditions[transfer.get("agent_id")] = transfer.get("condition")
    return conditions


def attached_test_ids(config):
    tests = config.get("platform_settings", {}).get("testing", {}).get("attached_tests", [])
    return {t["test_id"] for t in tests if "test_id" in t}

if not API_KEY:
    print("ELEVENLABS_API_KEY not set — skipping live verification")
    sys.exit(0)

agents_data = json.loads((ROOT / "agents.json").read_text())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--branch-name",
    default="Main",
    help="Branch to check (defaults to 'Main', every agent's permanent production branch)",
)
args = parser.parse_args()

for entry in agents_data.get("agents", []):
    config_path = ROOT / entry["config"]
    local = json.loads(config_path.read_text())
    expected_tools = local_tool_names(local)
    expected_webhook = local_webhook_id(local)
    expected_events = local_webhook_events(local)
    expected_tests = attached_test_ids(local)
    expected_conditions = transfer_conditions(local)
    if not expected_tools and not expected_webhook and not expected_tests:
        ok(f"{entry['config']}: no tools, webhook, or attached tests declared, nothing to verify")
        continue
    target = f"branch '{args.branch_name}' of agent {entry['id']}"
    try:
        branch_id = find_branch_id(entry["id"], args.branch_name)
        if not branch_id:
            fail(f"{entry['config']}: no branch named '{args.branch_name}' found")
            continue
        url = f"{API_BASE}/v1/convai/agents/{entry['id']}?branch_id={branch_id}"
        req = urllib.request.Request(url, headers={"xi-api-key": API_KEY})
        with urllib.request.urlopen(req) as resp:
            live = json.loads(resp.read())
    except Exception as e:
        fail(f"{entry['config']}: could not fetch {target} — {e}")
        continue
    if expected_tools:
        actual_tools = live_tool_names(live)
        missing = expected_tools - actual_tools
        extra = actual_tools - expected_tools
        if missing:
            msg = (
                f"{entry['config']}: tool(s) {sorted(missing)} declared locally but "
                f"missing from {target}"
                f" after push — the CLI likely dropped them silently during push."
                f" Patch the API directly to fix (see scripts/verify-live-tools.py docstring)."
            )
            fail(msg)
        elif extra:
            msg = (
                f"{entry['config']}: tool(s) {sorted(extra)} present on "
                f"{target}"
                f" but not declared locally — the CLI likely failed to remove a deleted tool during push"
                f" (same silent-drop bug as missing tools, in reverse; see the 2026-07-26 transfer_to_agent"
                f" incident in docs/adr/0005-retire-claims-supervisor-single-agent-lodgement.md)."
                f" Patch the API directly to remove it."
            )
            fail(msg)
        else:
            ok(f"{entry['config']}: all {len(expected_tools)} declared tool(s) present live, no undeclared extras")
    if expected_webhook:
        live_wid = live_webhook_id(live)
        if live_wid != expected_webhook:
            fail(
                f"{entry['config']}: post_call_webhook_id mismatch on {target} — "
                f"local: {expected_webhook}, live: {live_wid}"
            )
        else:
            ok(f"{entry['config']}: post_call_webhook_id matches live")
    if expected_events:
        live_events = live_webhook_events(live)
        if set(live_events) != set(expected_events):
            fail(
                f"{entry['config']}: webhooks.events mismatch on {target} — "
                f"local: {sorted(expected_events)}, live: {sorted(live_events)} — "
                f"same CLI silent-drop failure mode as post_call_webhook_id."
            )
        else:
            ok(f"{entry['config']}: webhooks.events matches live")
    if expected_tests:
        live_tests = attached_test_ids(live)
        missing = expected_tests - live_tests
        if missing:
            fail(
                f"{entry['config']}: attached test(s) {sorted(missing)} declared locally "
                f"but missing from {target} after push — same CLI "
                f"silent-drop failure mode as tools/webhook (see #29, #35)."
            )
        else:
            ok(f"{entry['config']}: all {len(expected_tests)} attached test(s) present live")
    if expected_conditions:
        live_conditions = transfer_conditions(live)
        mismatched = {
            aid: cond for aid, cond in expected_conditions.items()
            if live_conditions.get(aid) != cond
        }
        if mismatched:
            fail(
                f"{entry['config']}: transfer_to_agent condition for target(s) "
                f"{sorted(mismatched)} does not match {target} — the CLI can silently "
                f"drop or stale this nested field on push even when the tool itself is "
                f"present (see 2026-07-22 incident). Patch the API directly to fix."
            )
        else:
            ok(f"{entry['config']}: all {len(expected_conditions)} transfer_to_agent condition(s) match live")

print(f"\n{'='*40}")
if errors:
    print(f"FAILED — {len(errors)} error(s):")
    for e in errors:
        print(f"  • {e}")
    sys.exit(1)
else:
    print("All live tool checks passed")
