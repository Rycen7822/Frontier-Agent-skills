# Shared-Ledger Delegation Runtime

Operator-only mechanics for children working in a plugin-managed room, ledger, or shared workspace. Load only after delegation admission and a successful live capability probe. This resource never grants plugin writes, publication, broad filesystem access, or skill-library maintenance.

## Capability probe

Inspect the active host's live delegation schema before dispatch. Pass only parameters it accepts; do not copy capability arguments from another host/version.

- With child toolset selection, give CLI-first plugins terminal/file/skill-reading access; give explicit tool-mode plugins their enabled toolset plus skill reading after a fresh session exposes it.
- Add web, browser, or external capabilities only to roles that require them.
- Without child toolset selection, project required operations and verify the child actually has them. Use the controller or a compatible runtime when a required capability is absent.

## Protocol order

1. Give each child stable room/task/agent/role identifiers and the exact workspace path.
2. Require registration/join/open before ordinary reads or writes.
3. Name the exact qualified plugin skill and require the child's skill-loading capability when procedural detail is needed; parent-loaded text is not inherited.
4. Put long JSON/generated requests in stable payload files and project their path/selector plus size/hash rather than truncated inline content.
5. Require a unique room artifact/evidence file and return its ID/path, top findings, and verification handle.
6. Controller reads back room status, artifact identity, terminal gate, and external side effects before any completion claim.

## Minimal worker projection

```text
Assigned identifiers: <room/task/agent/role>
First domain action: <register/join/open command or tool call>
Canonical protocol skill: <plugin>:<usage-skill> through the active host skill loader
Allowed operations: <bounded list>
Protected operations: no skill-library mutation, unassigned edits, publication, or destructive action
Payload identity: <workspace file/task selector plus stable size/hash>
Required output: <unique artifact/evidence path plus summary and verification handle>
Nesting: disabled unless explicitly authorized
```

## Shared-state controls

- Multiple children never edit the same canonical report, ledger row, dataset, or code path concurrently; use child-owned artifacts and controller fan-in.
- Workflow phase names are not terminal proof; inspect status and artifacts after each phase.
- Serialize any room action that changes state consumed by another child, or freeze a snapshot first.
- Verify long-payload identity before and after delegation.
- Explicitly prohibit skill-library mutation unless the delegated task is authorized skill-library maintenance, even if the capability is present.

## Fail closed

Stop or fall back to the controller when registration fails, capability is absent, payload identity drifts, artifacts cannot be read back, shared writers collide, or the runtime's asynchronous status cannot be resolved. Never infer plugin enablement, child inheritance, or completion from a worker summary.
