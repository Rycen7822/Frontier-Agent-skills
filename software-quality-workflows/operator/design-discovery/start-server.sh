#!/usr/bin/env bash
# Start the host-neutral design-discovery companion in the foreground.
# The active agent host must own the tracked background lifecycle.
# Usage: start-server.sh [--project-dir <path>] [--host <bind-host>] [--url-host <display-host>]
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR=""
BIND_HOST="127.0.0.1"
URL_HOST=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      [[ $# -ge 2 ]] || { echo '{"error":"--project-dir requires a path"}'; exit 1; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --host)
      [[ $# -ge 2 ]] || { echo '{"error":"--host requires a value"}'; exit 1; }
      BIND_HOST="$2"
      shift 2
      ;;
    --url-host)
      [[ $# -ge 2 ]] || { echo '{"error":"--url-host requires a value"}'; exit 1; }
      URL_HOST="$2"
      shift 2
      ;;
    *)
      printf '{"error":"Unknown argument: %s"}\n' "$1"
      exit 1
      ;;
  esac
done

if [[ -z "$URL_HOST" ]]; then
  if [[ "$BIND_HOST" == "127.0.0.1" || "$BIND_HOST" == "localhost" ]]; then
    URL_HOST="localhost"
  else
    URL_HOST="$BIND_HOST"
  fi
fi

SESSION_ID="$$-$(date +%s)"
if [[ -n "$PROJECT_DIR" ]]; then
  SESSION_DIR="${PROJECT_DIR}/.agent-design-discovery/${SESSION_ID}"
else
  SESSION_DIR="/tmp/agent-design-discovery-${SESSION_ID}"
fi
STATE_DIR="${SESSION_DIR}/state"
PID_FILE="${STATE_DIR}/server.pid"
mkdir -p "${SESSION_DIR}/content" "$STATE_DIR"

# exec keeps the PID file aligned with the tracked Node process.
echo "$$" > "$PID_FILE"
exec env   BRAINSTORM_DIR="$SESSION_DIR"   BRAINSTORM_HOST="$BIND_HOST"   BRAINSTORM_URL_HOST="$URL_HOST"   BRAINSTORM_OWNER_PID="$PPID"   node "$SCRIPT_DIR/server.cjs"
