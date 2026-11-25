#!/usr/bin/env bash
# Start the host-neutral design-discovery companion in the foreground.
# The active agent host must own the tracked background lifecycle.
# Usage: start-server.sh [--project-dir <path>] [--host <bind-host>] [--url-host <display-host>]
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_SCRIPT="$(realpath -e "$SCRIPT_DIR/server.cjs")"
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

if [[ "$BIND_HOST" != "127.0.0.1" && "$BIND_HOST" != "localhost" ]]; then
  echo '{"error":"--host must name a loopback interface (127.0.0.1 or localhost)"}'
  exit 1
fi

if [[ -z "$URL_HOST" ]]; then
  URL_HOST="localhost"
elif [[ "$URL_HOST" != "127.0.0.1" && "$URL_HOST" != "localhost" ]]; then
  echo '{"error":"--url-host must name a loopback interface (127.0.0.1 or localhost)"}'
  exit 1
fi

if [[ -n "$PROJECT_DIR" ]]; then
  PROJECT_ROOT="$(realpath -e "$PROJECT_DIR")"
  [[ -d "$PROJECT_ROOT" ]] || { echo '{"error":"--project-dir must be a directory"}'; exit 1; }
  SESSION_PARENT="${PROJECT_ROOT%/}/.agent-design-discovery"
  [[ ! -L "$SESSION_PARENT" ]] || { echo '{"error":"project session parent must not be a symlink"}'; exit 1; }
  if [[ -e "$SESSION_PARENT" ]]; then
    [[ -d "$SESSION_PARENT" ]] || { echo '{"error":"project session parent must be a directory"}'; exit 1; }
  else
    mkdir "$SESSION_PARENT"
  fi
  [[ "$(realpath -e "$SESSION_PARENT")" == "$SESSION_PARENT" ]] \
    || { echo '{"error":"project session parent escaped its canonical path"}'; exit 1; }
  chmod 700 "$SESSION_PARENT"
  SESSION_DIR="$(mktemp -d "$SESSION_PARENT/session-XXXXXXXX")"
  SESSION_CLASS="project-local"
else
  SESSION_DIR="$(mktemp -d /tmp/agent-design-discovery-XXXXXXXX)"
  SESSION_CLASS="temporary"
fi
SESSION_DIR="$(realpath -e "$SESSION_DIR")"
STATE_DIR="${SESSION_DIR}/state"
PID_FILE="${STATE_DIR}/server.pid"
OWNER_FILE="${STATE_DIR}/owner.json"
LOG_FILE="${STATE_DIR}/server.log"
mkdir -p "${SESSION_DIR}/content" "$STATE_DIR"
chmod 700 "$SESSION_DIR" "${SESSION_DIR}/content" "$STATE_DIR"

NONCE="$(node -e "process.stdout.write(require('crypto').randomBytes(32).toString('hex'))")"
printf '%s\n' "$$" > "$PID_FILE"
: > "$LOG_FILE"

OWNER_TMP="${STATE_DIR}/.owner.json.$$"
env \
  OWNER_TMP="$OWNER_TMP" \
  SESSION_DIR="$SESSION_DIR" \
  SESSION_CLASS="$SESSION_CLASS" \
  NONCE="$NONCE" \
  SERVER_PID="$$" \
  SERVER_SCRIPT="$SERVER_SCRIPT" \
  node - <<'NODE'
const fs = require('fs');
const owner = {
  schema: 'design-discovery-owner/1',
  session_root: process.env.SESSION_DIR,
  session_class: process.env.SESSION_CLASS,
  nonce: process.env.NONCE,
  server_pid: Number(process.env.SERVER_PID),
  server_script: process.env.SERVER_SCRIPT,
};
fs.writeFileSync(process.env.OWNER_TMP, JSON.stringify(owner) + '\n', { mode: 0o600, flag: 'wx' });
NODE
mv "$OWNER_TMP" "$OWNER_FILE"
chmod 600 "$OWNER_FILE" "$PID_FILE" "$LOG_FILE"

# exec keeps the PID file aligned with the tracked Node process.
exec env \
  BRAINSTORM_DIR="$SESSION_DIR" \
  BRAINSTORM_HOST="$BIND_HOST" \
  BRAINSTORM_URL_HOST="$URL_HOST" \
  BRAINSTORM_OWNER_PID="$PPID" \
  node "$SERVER_SCRIPT" --session-nonce "$NONCE"
