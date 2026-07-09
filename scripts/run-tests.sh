#!/usr/bin/env bash
set -euo pipefail

failed=0
for agent_id in $(jq -r '.agents[].id' agents.json); do
  echo "Testing $agent_id..."
  if ! elevenlabs agents test "$agent_id" --no-ui; then
    echo "::error::Tests failed for $agent_id"
    failed=1
  fi
done
if [ "$failed" -eq 1 ]; then
  echo "::error::One or more agents had test failures"
  exit 1
fi
