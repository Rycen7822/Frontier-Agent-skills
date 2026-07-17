#!/usr/bin/env bash
# Stop one design-discovery companion only after proving its complete identity.
# Usage: stop-server.sh <session_dir>
set -euo pipefail

fail() {
  printf '{"status":"rejected","error":"%s"}\n' "$1"
  exit 1
}

[[ $# -eq 1 && -n "$1" ]] || fail "Usage: stop-server.sh <session_dir>"
[[ ! -L "$1" ]] || fail "session root must not be a symlink"
SESSION_DIR="$(realpath -e "$1" 2>/dev/null)" || fail "session root does not exist"
[[ -d "$SESSION_DIR" ]] || fail "session root must be a directory"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_SCRIPT="$(realpath -e "$SCRIPT_DIR/server.cjs")"
STATE_DIR="$SESSION_DIR/state"
[[ -d "$STATE_DIR" && ! -L "$STATE_DIR" ]] || fail "state directory is missing or unsafe"

OWNER_FILE="$STATE_DIR/owner.json"
PID_FILE="$STATE_DIR/server.pid"
LOG_FILE="$STATE_DIR/server.log"
for state_file in "$OWNER_FILE" "$PID_FILE" "$LOG_FILE"; do
  [[ -f "$state_file" && ! -L "$state_file" ]] || fail "required state file is missing or unsafe"
done

mapfile -t owner_fields < <(
  env OWNER_FILE="$OWNER_FILE" SESSION_DIR="$SESSION_DIR" SERVER_SCRIPT="$SERVER_SCRIPT" node - <<'NODE'
const fs = require('fs');
const expectedKeys = ['nonce', 'schema', 'server_pid', 'server_script', 'session_class', 'session_root'];
let owner;
try {
  owner = JSON.parse(fs.readFileSync(process.env.OWNER_FILE, 'utf8'));
} catch {
  process.exit(1);
}
const valid = owner !== null
  && typeof owner === 'object'
  && !Array.isArray(owner)
  && JSON.stringify(Object.keys(owner).sort()) === JSON.stringify(expectedKeys)
  && owner.schema === 'design-discovery-owner/1'
  && owner.session_root === process.env.SESSION_DIR
  && (owner.session_class === 'temporary' || owner.session_class === 'project-local')
  && /^[0-9a-f]{64}$/.test(owner.nonce)
  && Number.isSafeInteger(owner.server_pid)
  && owner.server_pid > 1
  && owner.server_script === process.env.SERVER_SCRIPT;
if (!valid) process.exit(1);
console.log(owner.server_pid);
console.log(owner.nonce);
console.log(owner.session_class);
NODE
) || fail "owner marker is malformed"
[[ ${#owner_fields[@]} -eq 3 ]] || fail "owner marker is malformed"
pid="${owner_fields[0]}"
nonce="${owner_fields[1]}"
session_class="${owner_fields[2]}"

pid_file_value="$(<"$PID_FILE")"
[[ "$pid_file_value" =~ ^[0-9]+$ ]] || fail "PID file is malformed"
[[ "$pid_file_value" == "$pid" ]] || fail "PID does not match owner marker"
[[ -r "/proc/$pid/cmdline" && -r "/proc/$pid/stat" ]] || fail "recorded process is not live"

env TARGET_PID="$pid" SERVER_SCRIPT="$SERVER_SCRIPT" NONCE="$nonce" node - <<'NODE' \
  || fail "live process identity does not match owner marker"
const fs = require('fs');
const argv = fs.readFileSync(`/proc/${process.env.TARGET_PID}/cmdline`)
  .toString('utf8').split('\0').filter(Boolean);
const scriptIndex = argv.indexOf(process.env.SERVER_SCRIPT);
const nonceFlagIndex = argv.indexOf('--session-nonce');
if (scriptIndex < 1
    || nonceFlagIndex !== scriptIndex + 1
    || argv[nonceFlagIndex + 1] !== process.env.NONCE
    || argv.length !== nonceFlagIndex + 2) process.exit(1);
NODE

process_state() {
  local stat_line remainder
  [[ -r "/proc/$pid/stat" ]] || { printf 'gone'; return; }
  stat_line="$(<"/proc/$pid/stat")"
  remainder="${stat_line##*) }"
  printf '%s' "${remainder%% *}"
}

[[ "$(process_state)" != "Z" ]] || fail "recorded process is stale"

if [[ "$session_class" == "temporary" ]]; then
  [[ "$(dirname "$SESSION_DIR")" == "/tmp" ]] || fail "temporary session is outside /tmp"
  [[ "$(basename "$SESSION_DIR")" =~ ^agent-design-discovery-[[:alnum:]]{8}$ ]] \
    || fail "temporary session name is not canonical"
fi

kill -TERM "$pid" 2>/dev/null || fail "failed to signal recorded process"
for _ in {1..20}; do
  state="$(process_state)"
  [[ "$state" == "gone" || "$state" == "Z" ]] && break
  sleep 0.1
done
state="$(process_state)"
[[ "$state" == "gone" || "$state" == "Z" ]] || fail "process still running after TERM timeout"

if [[ "$session_class" == "temporary" ]]; then
  rm -rf -- "$SESSION_DIR"
else
  rm -f -- "$OWNER_FILE" "$PID_FILE" "$LOG_FILE" "$STATE_DIR/server-info"
fi
echo '{"status":"stopped"}'
