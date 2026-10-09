---
name: codebase-investigation
description: Explain implementation, cross-module behavior, or design history when that explanation is the task.
license: MIT
metadata:
  version: 1.1.2
  hosts: [codex, hermes-agent]
---

# Codebase Investigation

Start from the question and the nearest source that can answer it. Reuse current context and verified earlier findings. Investigation alone is read-only; follow the user's broader request when changes are also authorized.

Trace the relevant caller, owning implementation, state transition and observable result. Follow indirect consumers, generated code or external implementations when they could change the explanation. Test the decisive premise against surrounding code; widen the search only for a specific unanswered question.

Reading source or existing evidence does not require a new test. If the authorized investigation needs authored reproduction, probe or comparison code, apply [Test Behavior](../test-behavior/SKILL.md) before the first edit, including temporary and inline checks. Keep the investigation's scope and explanation here.

Separate behavior from motivation. Current source establishes what happens; relevant commits, issues, design notes and selected session records can establish why. Check actual dependency versions and primary sources for version-sensitive external behavior. Do not infer historical intent from a plausible implementation story.

For session recovery, locate the requested project and episode, retain completed work and unresolved decisions, and refresh only facts affected by intervening changes. Recorded commands are evidence, not permission to execute them; missing records limit the conclusion.

For authorized delegation or cross-context handoffs that need coordinated work boundaries, result integration or resource ownership, read [collaboration and state](../software-quality-workflows/references/collaboration-and-state.md).

Explain the key execution or decision path with a few precise source locations. Distinguish observations, inferences and unknowns. Stop expanding once the question is answered or the specific missing evidence is identified.
