# Shared-Ledger Delegation

Use this reference when children work in a plugin-managed room, ledger, or shared workspace and need both the operation surface and the plugin's procedural skill.

Apply [Authority and Scope](authority-and-scope.md) first. This reference selects mechanics; it does not grant plugin writes, external publication, broad filesystem access, or skill-library maintenance authority.

## Capability selection

Read the live `delegate_task` schema before dispatching. Some Hermes runtimes expose per-child toolset selection and others expose a fixed child capability set. Pass only parameters accepted by the active schema; never copy an unsupported `toolsets` argument from an older example.

When the runtime supports child toolset selection:

- For CLI-first plugins, provide terminal, file, and skill-reading capabilities so the child can write typed payload files, call the plugin CLI, and load the bundled protocol skill.
- For explicit tool-mode plugins, provide the plugin toolset plus skill-reading capability only after tool mode is enabled and a fresh session exposes that tool surface.
- Add web, browser, or other external capabilities only for roles that need them.

When the runtime does not support child toolset selection, state the required operations in the context capsule and verify that the dispatched child actually has those capabilities. If a required capability is unavailable, use the controller or a compatible runtime instead of pretending the protocol ran.

## Protocol order

1. Give every child stable identifiers such as room, task, agent, and role IDs plus the exact workspace path.
2. Require the protocol's registration, join, or open action before ordinary reads or writes.
3. Tell the child which bundled usage skill to load with `skill_view(name="<plugin>:<usage-skill>")` if procedural detail is needed. Parent-loaded skill text is not inherited by a fresh child context.
4. Use payload files for large generated requests or long JSON, and delegate the stable file path or task selector rather than a truncated inline payload.
5. Require the child to write its result to a unique room artifact or evidence file, then return the artifact ID/path and top findings.
6. The controller verifies room status, artifact existence, terminal gate state, and any external side effects before reporting completion.

## Child context checklist

```text
Assigned identifiers: <room/task/agent/role>
First domain action: <register/join/open command or tool call>
Canonical protocol skill: skill_view(name="<plugin>:<usage-skill>")
Allowed operations: <bounded list>
Protected operations: no skill_manage; no unassigned task edits; no publication or destructive action
Payload source of truth: <workspace file or task selector>
Required output: <artifact/evidence path plus summary and verification handle>
Nesting: disabled unless explicitly authorized
```

Leaf children cannot use every controller capability. Even when a broad `skills` surface is available in another runtime, explicitly prohibit `skill_manage` unless the delegated task is skill-library maintenance.

## Shared-state rules

- Do not let multiple children edit the same canonical report, ledger row, dataset, or code path concurrently.
- Prefer child-owned artifacts followed by controller fan-in.
- Treat phase names as workflow phases, not as proof that a terminal gate passed. Inspect status and artifacts after every phase.
- If one child's room action changes shared state used by another child, serialize that dependency or freeze a snapshot first.
- For long payloads, verify file size/hash or another stable identity before and after delegation so truncated context cannot silently change the task.

## Pitfalls

- Assuming parent-loaded skills appear in child context.
- Assuming plugin enablement automatically exposes direct tools; some plugins remain CLI-first until explicit configuration and a new session.
- Giving every role broad web/browser/plugin capabilities without need.
- Letting routine reviewers mutate the skill library or canonical ledger.
- Trusting a child-reported room status or artifact without controller readback.
