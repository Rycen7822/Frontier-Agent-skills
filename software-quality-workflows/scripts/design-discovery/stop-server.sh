#!/usr/bin/env bash
# Stop one Hermes design-discovery companion and clean ephemeral state.
# Usage: stop-server.sh <session_dir>
set -u

SESSION_DIR="${1:-}"
if [[ -z "$SESSION_DIR" ]]; then
  echo '{"error":"Usage: stop-server.sh <session_dir>"}'
  exit 1
fi

STATE_DIR="${SESSION_DIR}/state"
PID_FILE="${STATE_DIR}/server.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo '{"status":"not_running"}'
  exit 0
fi

pid="$(<"$PID_FILE")"
kill "$pid" 2>/dev/null || true
for _ in {1..20}; do
  if ! kill -0 "$pid" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if kill -0 "$pid" 2>/dev/null; then
  echo '{"status":"failed","error":"process still running"}'
  exit 1
fi

rm -f "$PID_FILE" "${STATE_DIR}/server.log"
if [[ "$SESSION_DIR" == /tmp/hermes-design-discovery-* ]]; then
  rm -rf "$SESSION_DIR"
fi
echo '{"status":"stopped"}'
