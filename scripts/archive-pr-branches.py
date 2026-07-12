#!/usr/bin/env python3
"""Archive PR branches across all agents in agents.json.

Best-effort: if the API key is missing or a branch is already gone, the
script continues gracefully.  Non-zero exit only on genuine failure.
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_BASE = "https://api.elevenlabs.io"
API_KEY = os.environ.get("ELEVENLABS_API_KEY")



def fail(msg):
    print(f"  ✗ {msg}")


def ok(msg):
    print(f"  ✓ {msg}")


def find_branch_id(agent_id, branch_name):
    url = f"{API_BASE}/v1/convai/agents/{agent_id}/branches"
    req = urllib.request.Request(url, headers={"xi-api-key": API_KEY})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        fail(f"Failed to list branches for {agent_id}: HTTP {e.code}")
        return None
    for branch_list in (data.get("branches", []), data.get("items", []), data.get("results", [])):
        for branch in branch_list:
            if branch.get("name") == branch_name:
                return branch["id"]
    return None


def archive_branch(agent_id, branch_id):
    url = f"{API_BASE}/v1/convai/agents/{agent_id}/branches/{branch_id}"
    body = json.dumps({"archived": True}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return True
    except urllib.error.HTTPError as e:
        fail(f"Archive failed for {branch_id}: HTTP {e.code}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Archive PR branches on ElevenLabs")
    parser.add_argument("--branch-name", required=True, help="Branch name to archive (e.g. pr-27)")
    args = parser.parse_args()

    if not API_KEY:
        print("ELEVENLABS_API_KEY not set — branch cleanup is best-effort, skipping")
        sys.exit(0)

    agents_data = json.loads((ROOT / "agents.json").read_text())
    agent_list = agents_data.get("agents", [])

    if not agent_list:
        print("No agents in agents.json — nothing to do")
        sys.exit(0)

    print(f"Archiving branch '{args.branch_name}' across {len(agent_list)} agent(s)\n")

    all_ok = True
    for entry in agent_list:
        agent_id = entry["id"]
        config = entry["config"]
        label = f"{config} ({agent_id})"

        branch_id = find_branch_id(agent_id, args.branch_name)
        if branch_id is None:
            print(f"{label}: branch '{args.branch_name}' not found (already archived or never created)")
            continue

        if archive_branch(agent_id, branch_id):
            ok(f"{label}: archived '{args.branch_name}' ({branch_id})")
        else:
            all_ok = False

    print(f"\n{'='*40}")
    if all_ok:
        print("All branches archived successfully (or already gone)")
    else:
        print("Some archives failed — see above")
        sys.exit(1)


if __name__ == "__main__":
    main()
