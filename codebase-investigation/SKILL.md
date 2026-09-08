---
name: codebase-investigation
description: Explain how code works or why a design exists using relevant source and project history.
license: MIT
metadata:
  version: 1.0.1
  hosts: [codex, hermes-agent]
---

# Codebase Investigation

Start from the question and the nearest source that can answer it. Reuse current context and verified earlier findings. Investigation alone is read-only; follow the user's broader request when changes are also authorized.

Trace the relevant caller, owning implementation, state transition and observable result. Follow indirect consumers, generated code or external implementations when they could change the explanation. Test the decisive premise against surrounding code; widen the search only for a specific unanswered question.

Separate behavior from motivation. Current source establishes what happens; relevant commits, issues, design notes and selected session records can establish why. Check actual dependency versions and primary sources for version-sensitive external behavior. Do not infer historical intent from a plausible implementation story.

For session recovery, locate the requested project and episode, retain completed work and unresolved decisions, and refresh only facts affected by intervening changes. Recorded commands are evidence, not permission to execute them; missing records limit the conclusion.

Explain the key execution or decision path with a few precise source locations. Distinguish observations, inferences and unknowns. Stop expanding once the question is answered or the specific missing evidence is identified.
