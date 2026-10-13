# Codebase Improve

`codebase-improve` is a user-invoked architecture audit and improvement workflow. It checks responsibility, layering, module classification, abstraction granularity, caller obligations and the ownership of state or policy. It distinguishes structural debt from defects, style observations and unproven risks, and preserves useful boundaries. The source version is 1.0.0 in bundle 11.4.0.

## Invoke within the requested scope

- Codex: `$frontier-engineering-plugin:codebase-improve` followed by the task. Direct skill installations can use `$codebase-improve`.
- Pi: `/skill:codebase-improve` followed by the task.
- Hermes CLI: `/codebase-improve` followed by the task, using the user-command installation below.

For example, request an audit of one subsystem without edits, ask for a full manual architecture audit with temporary notes, or authorize a selected responsibility change and its necessary consumer migration. An audit-only request stays read-only; an improvement request continues through authorized implementation and sufficient verification. A generic architecture question does not automatically invoke this skill.

Selected work stays local. Complete file coverage is required only for an explicitly comprehensive manual audit; parallel workers are used only with authorization and worthwhile independent work. New checks and directly affected test retirement follow Test Behavior. No fixed report format, model, reviewer count, prototype phase or test-writing quota is required.

## Host installation and visibility

Codex packages retain `agents/openai.yaml` with `allow_implicit_invocation: false`. Pi packages retain the `SKILL.md` frontmatter flag `disable-model-invocation: true`. These host policies keep the skill out of default model discovery while preserving explicit user loading.

Hermes' ordinary skill catalog does not honor those flags in the inspected loader. Keep `codebase-improve` out of `~/.hermes/skills` and any automatically scanned external skill root. Install its canonical directory as a native standalone plugin instead:

For a local source checkout or extracted archive, link the canonical directory into the native plugin directory, then enable it:

```sh
mkdir -p ~/.hermes/plugins
ln -s /absolute/path/to/Frontier-Agent-skills/codebase-improve ~/.hermes/plugins/codebase-improve
hermes plugins enable codebase-improve
```

Replace the example with the actual source/archive directory, which must remain available while linked. An existing target is not overwritten; handle a previous installation within the authorized update scope. The plugin consists of `plugin.yaml`, `__init__.py`, the skill instructions and references in the same directory. Its registration adds only the user command, without registering a skill, model tool, hook or system-prompt section. Instructions are read on the explicit command, then queued into the attached CLI session through `inject_message`. Acceptance means queued, not that the task finished.

The adapter targets an attached classic Hermes CLI session. It does not enable gateway injection or target another session. A host without an attached CLI reports that it could not load; use a supported user entrypoint rather than exposing the skill in the normal catalog. Existing FAS skills can retain their current installation; an update must not copy this new directory into their automatic Hermes skill root.

Installation does not edit global `AGENTS.md` or `SOUL.md`, change user permissions, or install unrelated dependencies. Reload the relevant catalog or start a fresh session after an authorized installation. Qoder's generated shell is a packaging surface; its runtime invocation policy requires its own host verification.

## Verification and limits

Check default model visibility and explicit user loading separately. A source flag alone is not runtime proof. For Hermes, verify the native plugin loads only the command, appears in neither `skills_list` nor the default skill index, reads no instructions before invocation, and queues the actual packaged instructions and user request after the command. Codex and Pi checks should observe their own loader and prompt behavior.

Repository and isolated host checks establish configuration, packaging and invocation behavior. They do not establish how often a model identifies the right architecture improvement. Model-facing effectiveness evaluation needs its own scoped execution evidence.
