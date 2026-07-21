# Context Capsule Section

## Purpose

Bound the information needed for one target execution context without creating another plan truth.

## Use when

Use only when the target context has a demonstrated input budget and the canonical Handoff or Program is larger than that budget. Otherwise keep ordinary source pointers in the relevant slice.

## Required result

Add one section inside the canonical document containing only:

- current goal;
- essential source paths and ranges;
- locked decisions and invariants;
- current frontier;
- blockers;
- exact next action.

Keep authority, protected work, acceptance evidence, and rollback in the parent document and link to their sections. Refresh the capsule in place when the frontier changes.

## Failure boundary

Do not omit a safety-critical fact to meet a byte target. If the minimum facts do not fit, reduce the execution slice or stop with a size blocker. Never create a capsule file, locator, cache, or sidecar.
