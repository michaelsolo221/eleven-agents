#!/usr/bin/env python3
"""Trigger a Coolify deploy of the webhook receiver and verify it actually
went live, running the expected commit (or a later one).

Exists per ADR 0007 (docs/adr/0007-scoped-server-cd-and-post-deploy-verification.md):
Coolify's own GitHub-webhook auto-deploy is fire-and-forget from GitHub's side
and was found to be unregistered anyway (see that ADR for the diagnosis).
This script makes CI itself own the trigger -> poll -> verify loop so a
broken or stale deploy fails visibly as a CI check instead of silently.

Design notes (also from ADR 0007, restated here since they affect correctness):
- Coolify's deploy API can't be pinned to a commit — it always builds
  whatever is at the tip of the configured branch. So a second push landing
  on main while this script is polling is a legitimate reason for the live
  git_sha to be a *later* commit, not a failure. The check below accepts
  "expected commit, or a descendant of it" rather than exact equality.
- The POST /deploy response's `deployments[]` array includes each
  deployment's own `deployment_uuid` directly (confirmed against Coolify's
  published OpenAPI spec) — used here instead of guessing which deployment
  is ours by matching timestamps against the deployments-list endpoint.
  Timestamp-matching would be a real bug, not just inelegant: clock skew
  between this runner and Coolify's server, or a second overlapping push,
  could misattribute a different deployment to this run. See CLAUDE.md's
  "verify third-party wire formats against real docs, not just your own
  tests" lesson.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

COOLIFY_HOST = os.environ.get("COOLIFY_HOST", "https://app.coolify.io")
COOLIFY_TOKEN = os.environ.get("COOLIFY_TOKEN")
APP_UUID = os.environ.get("COOLIFY_APP_UUID")
VERSION_URL = os.environ.get("COOLIFY_VERSION_URL")

# Coolify Cloud's edge blocks urllib's default "Python-urllib/x.y" User-Agent
# outright (403, before the request reaches the app) — confirmed empirically
# 2026-07-29, unrelated to the token's permissions. Every outbound request
# needs an explicit, non-generic User-Agent to get past it.
USER_AGENT = "eleven-agents-ci/1.0"

DEFAULT_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 10
POLL_RETRIES = 3
POLL_RETRY_DELAY_SECONDS = 5
VERSION_CHECK_RETRIES = 5
VERSION_CHECK_RETRY_DELAY_SECONDS = 5
TERMINAL_STATUSES = ("finished", "failed")


def api_get(path):
    req = urllib.request.Request(
        f"{COOLIFY_HOST}{path}",
        headers={
            "Authorization": f"Bearer {COOLIFY_TOKEN}",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_get_with_retry(path, retries=POLL_RETRIES, delay=POLL_RETRY_DELAY_SECONDS):
    """A single flaky GET shouldn't crash a ~10-minute poll loop outright —
    retry a few times before giving up, same spirit as the /version retries
    below."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return api_get(path)
        except Exception as e:
            last_err = e
            print(f"  GET {path} attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    raise last_err


def trigger_deploy():
    """POST /deploy and return the deployment_uuid Coolify assigned to our
    app, read directly from the response body."""
    req = urllib.request.Request(
        f"{COOLIFY_HOST}/api/v1/deploy?uuid={APP_UUID}",
        headers={
            "Authorization": f"Bearer {COOLIFY_TOKEN}",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())

    deployment = next(
        (d for d in body.get("deployments", []) if d.get("resource_uuid") == APP_UUID),
        None,
    )
    if not deployment:
        raise RuntimeError(
            f"POST /deploy response didn't include a deployment for {APP_UUID}: {body}"
        )
    print(f"  triggered deployment {deployment['deployment_uuid']}")
    return deployment["deployment_uuid"]


def wait_for_deployment(timeout_seconds):
    """Trigger a deploy, then poll that specific deployment until it reaches
    a terminal status. Returns (deployment, error_message)."""
    deployment_uuid = trigger_deploy()

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        deployment = api_get_with_retry(f"/api/v1/deployments/{deployment_uuid}")
        if deployment["status"] in TERMINAL_STATUSES:
            return deployment, None
        time.sleep(POLL_INTERVAL_SECONDS)

    return None, f"deployment {deployment_uuid} did not reach a terminal status within timeout"


def fetch_live_git_sha():
    req = urllib.request.Request(VERSION_URL, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, VERSION_CHECK_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get("git_sha")
        except Exception as e:
            print(f"  /version check attempt {attempt} failed: {e}")
            if attempt < VERSION_CHECK_RETRIES:
                time.sleep(VERSION_CHECK_RETRY_DELAY_SECONDS)
    return None


def is_commit_or_descendant(expected_sha, reported_sha):
    """True if reported_sha == expected_sha, or expected_sha is an ancestor
    of reported_sha. Requires full git history (fetch-depth: 0 in the
    calling CI job) — a shallow checkout would make every ancestor check
    fail closed even when it should pass."""
    if expected_sha == reported_sha:
        return True
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", expected_sha, reported_sha],
        capture_output=True,
    )
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-sha",
        default=os.environ.get("GITHUB_SHA"),
        help="Commit that should end up live, or be an ancestor of what's live",
    )
    parser.add_argument(
        "--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS
    )
    args = parser.parse_args()

    if not COOLIFY_TOKEN:
        print("COOLIFY_TOKEN not set — cannot trigger or verify a deploy")
        sys.exit(1)
    if not APP_UUID:
        print("COOLIFY_APP_UUID not set — cannot trigger or verify a deploy")
        sys.exit(1)
    if not VERSION_URL:
        print("COOLIFY_VERSION_URL not set — cannot verify the deploy")
        sys.exit(1)
    if not args.expected_sha:
        print("--expected-sha not given and GITHUB_SHA not set")
        sys.exit(1)

    print(
        f"Triggering Coolify deploy for {APP_UUID} "
        f"(expecting commit {args.expected_sha} or later)..."
    )
    deployment, error = wait_for_deployment(args.timeout_seconds)
    if error:
        print(f"  ✗ {error}")
        sys.exit(1)
    if deployment["status"] != "finished":
        print(
            f"  ✗ Coolify deployment {deployment['deployment_uuid']} "
            f"ended with status={deployment['status']}"
        )
        sys.exit(1)
    print(f"  ✓ deployment {deployment['deployment_uuid']} finished")

    print(f"Checking {VERSION_URL} ...")
    reported_sha = fetch_live_git_sha()
    if not reported_sha:
        print("  ✗ could not reach /version after deployment finished")
        sys.exit(1)
    if reported_sha == "unknown":
        print(
            '  ✗ /version reports git_sha="unknown" — Coolify\'s '
            '"Include Source Commit in Build" toggle is likely disabled '
            "for this app (see ADR 0007)"
        )
        sys.exit(1)

    if not is_commit_or_descendant(args.expected_sha, reported_sha):
        print(
            f"  ✗ live git_sha={reported_sha} is not {args.expected_sha} "
            f"or a later commit reachable from it"
        )
        sys.exit(1)

    print(
        f"  ✓ live git_sha={reported_sha} matches or supersedes "
        f"expected {args.expected_sha}"
    )


if __name__ == "__main__":
    main()
