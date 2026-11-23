# Codex skill reload supervisor

This optional developer tool is outside the Bundle 11.3.0 source-complete and release path. `scripts/codex_skill_reload_supervisor.py` keeps one exact Codex thread across local plugin reinstall cycles through a local Unix-socket app-server.

The replacement TUI launches with `danger-full-access` and approval policy `never`. Use this tool only where that permission boundary is intentional.

## Validate the host

The protocol is fail-closed and pinned to `codex-cli 0.144.6`. Validate the CLI schema and local Unix WebSocket transport before the first run:

```sh
scripts/codex_skill_reload_supervisor.py validate --probe-cwd "$PWD"
```

Exit the previously unsupervised TUI once, then start the exact existing session from an ordinary shell. A session UUID is mandatory. Names, pickers, `--last` and forked sessions are rejected.

```sh
scripts/codex_skill_reload_supervisor.py run \
  --thread-id <exact-session-uuid> \
  --cwd "$PWD"
```

## Checkpoint a completed change

The supervisor injects `CODEX_SKILL_RELOAD_STATE` into the app-server, TUI and agent shell commands. After the agent completes the normal local plugin build, reinstall and byte checks, its final shell step for that turn is:

```sh
scripts/codex_skill_reload_supervisor.py checkpoint \
  --plugin frontier-engineering-plugin@local-personal \
  --continue-skill frontier-engineering-plugin:software-quality-workflows
```

`checkpoint` resolves the exact enabled local plugin version, compares every source skill tree with the installed cache, and stores only their paths and hashes. `--continue-skill` selects one to three verified skills for the automatic continuation turn. It does not weaken full-plugin verification. For one standalone `--skill NAME=/absolute/path/to/SKILL.md`, that sole skill is selected automatically.

## Reload boundary

Codex's `agent-turn-complete` notifier changes the pending checkpoint only after the current turn finishes. The supervisor then snapshots the persisted goal, closes the old TUI and app-server, starts a new app-server, resumes the exact thread with full access, forces a disk skill rescan, verifies the exact skill paths and tree hashes, and opens the replacement TUI. It sends the continuation turn through `turn/start` with an explicit skill input only after every proof passes.

A goal returns to `active` only when it was `active` immediately before the reload boundary and is `paused` or `blocked` after resume. An intentionally paused, intentionally blocked, completed, usage-limited or budget-limited goal is never activated and receives no automatic continuation turn. Initial adoption does not infer prior goal intent.

The runtime keeps one compact private JSON state file and one transient Unix socket. It does not create per-turn receipts or history files. `status` prints a redacted summary:

```sh
scripts/codex_skill_reload_supervisor.py status
```

Any CLI version drift, schema drift, thread or working-directory mismatch, permission mismatch, plugin or cache mismatch, skill error, hash drift, or non-resumable goal transition stops the cycle before an automatic turn. Update the pin and contract tests deliberately when Codex changes the experimental app-server protocol.
