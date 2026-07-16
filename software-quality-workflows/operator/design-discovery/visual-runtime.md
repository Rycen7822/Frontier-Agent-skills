# Visual Design Companion

Use this optional companion only when the design question is inherently visual: mockups, layout, hierarchy, diagrams, spatial relationships, or side-by-side visual alternatives. Keep requirements, scope, technical trade-offs, and other text questions in the normal conversation.

## Safety and lifecycle

- Ask before opening a local visual session unless the user already requested visual treatment.
- Bind to `127.0.0.1` by default. A non-loopback bind is an external exposure and needs explicit scope plus an appropriate security review.
- Use a task-owned `/tmp` session by default. Pass `--project-dir` only when persistent mockups are wanted; this creates `<project>/.agent-design-discovery/`, whose tracked/ignored status must be checked before closeout.
- Keep one server per discovery session, record its process session ID and returned `screen_dir`/`state_dir`, and stop it when the visual question is resolved.

## Start with the active host

Resolve the active `software-quality-workflows` skill root from the host's loaded-skill metadata or installed path, then launch its script through the host's tracked long-running command/process capability. Require a process or session handle and wait for the `server-started` startup record:

```text
command: <skill-root>/operator/design-discovery/start-server.sh [--project-dir <project-root>]
lifecycle: tracked background process owned by the active host
startup match: server-started
```

The script runs in the foreground by design; the active host owns and observes the background process. Read initial output through that same tracked-process capability. The `server-started` JSON provides `url`, `screen_dir`, and `state_dir`. Do not add shell-level `nohup`, `disown`, or `&` wrappers.

If the user's browser cannot reach the loopback URL, diagnose the actual WSL/container/remote boundary before changing the bind host. Do not expose the server broadly as a first attempt.

## Per-question loop

1. Check the tracked process and `<state_dir>/server-info` before every screen write.
2. Write a new semantic HTML fragment such as `layout.html` or `layout-v2.html` into `screen_dir` with the host's bounded file-edit capability; never reuse a filename.
3. Open or inspect the returned URL with an available browser capability when useful, and tell the user what is shown and where to open it.
4. End the turn so the user can inspect and respond. Their conversation reply is authoritative; `<state_dir>/events` adds structured click evidence when present.
5. Read events with the host's bounded file-read capability, merge them with the user's reply, then revise the current screen or advance.
6. When moving back to a text-only question, write a fresh waiting screen so stale choices are not presented as current.

The server wraps HTML fragments in the shared frame and reloads the browser when a new `.html` file appears. A full `<!DOCTYPE html>` or `<html>` document is served as-is with the click helper injected.

## Minimal fragment

```html
<h2>Which layout best supports the primary task?</h2>
<p class="subtitle">Compare scanability and action hierarchy</p>
<div class="options">
  <div class="option" data-choice="a" onclick="toggleSelect(this)">
    <div class="letter">A</div>
    <div class="content"><h3>Focused column</h3><p>One clear reading and action path.</p></div>
  </div>
  <div class="option" data-choice="b" onclick="toggleSelect(this)">
    <div class="letter">B</div>
    <div class="content"><h3>Navigation plus canvas</h3><p>Persistent context beside the main task.</p></div>
  </div>
</div>
```

Available frame classes include `.options`, `.option`, `.cards`, `.card`, `.mockup`, `.split`, `.pros-cons`, `.placeholder`, `.mock-nav`, `.mock-sidebar`, `.mock-content`, `.mock-button`, and `.mock-input`. Use two to four choices and scale fidelity to the decision being made.

## Events

Choice clicks are appended as JSON lines to `<state_dir>/events`:

```json
{"type":"click","choice":"a","text":"Focused column ...","timestamp":1706000101}
```

The latest click may indicate the final selection, but the conversation reply remains primary. Do not infer approval from a click when the user's text expresses uncertainty or a different choice.

## Stop and clean up

Run the stop script from a separate bounded terminal call:

```text
command: <skill-root>/operator/design-discovery/stop-server.sh <session_dir>
```

Then verify the tracked process exited. The stop script removes task-owned `/tmp` sessions and preserves explicitly persistent project sessions. Delete persistent artifacts only when they are task-owned and the user or project workflow authorizes cleanup.

Runtime resources: [server](server.cjs), [start script](start-server.sh), [stop script](stop-server.sh), [frame](frame-template.html), and [click helper](helper.js). Upstream terms are preserved in [the bundled license](design-discovery-upstream-license.txt).
