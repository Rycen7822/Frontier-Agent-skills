# Codebase Improve

[`codebase-improve`](../codebase-improve/SKILL.md) 1.0.0 is an explicitly invoked architecture audit and improvement workflow introduced in bundle 11.4.0. It examines responsibility, layering, module classification, abstraction granularity, caller obligations, and ownership of state or policy. It distinguishes structural debt from defects, style observations and unproven risks.

## Choose a scope

Request an audit of one subsystem without edits, a comprehensive manual audit with temporary notes, or a selected responsibility change with its required consumer migration. For example:

```text
Audit the ordering subsystem's responsibility boundaries without editing code.
Move this policy into one owner and migrate the necessary callers.
```

An audit-only request stays read-only. An improvement request continues through authorized implementation and sufficient verification. A generic architecture question does not invoke this skill automatically.

Work stays local unless the user authorizes a wider scope. Complete file coverage is required only for an explicitly comprehensive manual audit. Parallel work requires authorization and useful independent tasks. New checks and retirement of affected tests follow Test Behavior. The skill requires no fixed report format, model, reviewer count, prototype phase or test quota.

## Install and invoke

| Host | Command |
|---|---|
| Codex plugin | `$frontier-engineering-plugin:codebase-improve <request>` |
| Standalone Codex skill | `$codebase-improve <request>` |
| Pi | `/skill:codebase-improve <request>` |
| Classic Hermes CLI | `/codebase-improve <request>` |

Codex reads `allow_implicit_invocation: false` from `agents/openai.yaml`. Pi reads `disable-model-invocation: true` from `SKILL.md`. These policies preserve explicit loading while excluding the skill from default model discovery in their respective hosts. See [host installation](hosts.md) for setup.

The inspected Hermes skill loader does not honor those flags. Keep this directory out of `~/.hermes/skills` and other automatic skill roots. Install it as a standalone plugin as described in [the Hermes guide](hosts.md#hermes-agent). The adapter registers only the user command, reads instructions on invocation, and queues them through `inject_message`. It targets an attached classic CLI session, not a gateway or another session. A queued request is not a completed task.

Installation does not edit global `AGENTS.md` or `SOUL.md`, change permissions or install unrelated dependencies. Qoder includes the skill in its generated manifest, but its runtime invocation policy requires separate verification.

## Verification limits

Check default model visibility and explicit loading separately. For Hermes, confirm that the plugin appears in neither `skills_list` nor the default skill index, reads no instructions before invocation, and queues the actual packaged instructions afterward. Codex and Pi checks should observe their own loaders and prompts.

Repository and isolated host checks establish configuration, packaging and invocation behavior. They do not establish architecture-improvement quality or natural routing frequency.
