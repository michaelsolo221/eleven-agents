#!/usr/bin/env python3
"""Run agent tests against a PR branch via the ElevenLabs API.

Usage:
    python3 scripts/test-pr-branch.py --branch-name pr-27

Expects ELEVENLABS_API_KEY in the environment.
Reads agents.json and tests.json (and agent configs) from the repo root.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_KEY = os.environ.get("ELEVENLABS_API_KEY")
API_BASE = "https://api.elevenlabs.io"

# Accumulated errors and failure counts
errors = []
total_passed = 0
total_ran = 0


def fail(msg):
    errors.append(msg)
    print(f"  ✗ {msg}")


def ok(msg):
    print(f"  ✓ {msg}")


def warn(msg):
    print(f"  ⚠  {msg}")


def find_branch_id(agent_id, branch_name):
    """Find branch ID by name for a given agent."""
    url = f"{API_BASE}/v1/convai/agents/{agent_id}/branches"
    req = urllib.request.Request(url, headers={"xi-api-key": API_KEY})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        warn(f"HTTP {e.code} listing branches: {body[:200]}")
        return None
    for branch_list in (data.get("branches", []), data.get("items", []), data.get("results", [])):
        for branch in branch_list:
            if branch.get("name") == branch_name:
                return branch["id"]
    return None


def attached_test_ids(config):
    """Extract test IDs from an agent config's testing.attached_tests."""
    tests = config.get("platform_settings", {}).get("testing", {}).get("attached_tests", [])
    return [t["test_id"] for t in tests if "test_id" in t]


def build_test_name_map(tests_data):
    """Map test_id → config path from tests.json."""
    return {t["id"]: t["config"] for t in tests_data.get("tests", []) if "id" in t and "config" in t}


def run_tests(agent_id, branch_id, test_ids):
    """POST /run-tests and return the invocation ID."""
    url = f"{API_BASE}/v1/convai/agents/{agent_id}/run-tests"
    body = json.dumps({
        "tests": [{"test_id": tid} for tid in test_ids],
        "branch_id": branch_id,
        "repeat_count": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def poll_test_invocation(invocation_id, timeout_secs=120):
    """Poll for test invocation completion. Returns the final response."""
    import time
    url = f"{API_BASE}/v1/convai/test-invocations/{invocation_id}"
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        req = urllib.request.Request(url, headers={"xi-api-key": API_KEY})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        pending = [r for r in data.get("test_runs", []) if r.get("status") == "pending"]
        if not pending:
            return data
        passed = sum(1 for r in data.get("test_runs", []) if r.get("status") == "passed")
        failed = sum(1 for r in data.get("test_runs", []) if r.get("status") == "failed")
        p = len(pending)
        print(f"  Polling... {passed} passed, {failed} failed, {p} pending")
        time.sleep(5)
    return data


def main():
    global total_passed, total_ran

    parser = argparse.ArgumentParser(description="Run agent tests against a PR branch")
    parser.add_argument("--branch-name", required=True, help="PR branch name (e.g. pr-27)")
    args = parser.parse_args()
    branch_name = args.branch_name

    if not API_KEY:
        print("ELEVENLABS_API_KEY not set")
        sys.exit(1)

    agents_data = json.loads((ROOT / "agents.json").read_text())
    tests_data = json.loads((ROOT / "tests.json").read_text())
    test_name_map = build_test_name_map(tests_data)

    for entry in agents_data.get("agents", []):
        config_path = ROOT / entry["config"]
        agent_id = entry["id"]

        config = json.loads(config_path.read_text())
        test_ids = attached_test_ids(config)
        if not test_ids:
            print(f"{entry['config']}: no attached tests — skipping")
            continue

        branch_id = find_branch_id(agent_id, branch_name)
        if not branch_id:
            warn(f"{entry['config']}: branch '{branch_name}' not found — skipping")
            continue

        print(f"{entry['config']} (branch: {branch_name} / {branch_id})")
        print(f"  Running {len(test_ids)} test(s)...")
        total_ran += len(test_ids)

        try:
            result = run_tests(agent_id, branch_id, test_ids)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            fail(f"HTTP {e.code} running tests for {entry['config']}: {body[:200]}")
            continue
        except urllib.error.URLError as e:
            fail(f"Network error running tests for {entry['config']}: {e}")
            continue

        invocation_id = result.get("id")
        if invocation_id:
            result = poll_test_invocation(invocation_id)

        for run in result.get("test_runs", []):
            tid = run.get("test_id", "?")
            config_name = test_name_map.get(tid, tid)
            status = run.get("status", "unknown")
            if status == "passed":
                ok(config_name)
                total_passed += 1
            elif status == "pending":
                fail(f"{config_name} TIMED OUT (still pending)")
            else:
                fail(f"{config_name} {status.upper()}")

    print()
    print(f"Results: {total_passed}/{total_ran} passed")
    if errors:
        print(f"FAILED — {len(errors)} failure(s)")
        sys.exit(1)
    else:
        print("All passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
