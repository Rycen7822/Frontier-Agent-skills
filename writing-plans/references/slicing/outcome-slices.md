# Outcome Slices

## Purpose

Split a Handoff or Program into the fewest independently acceptable outcomes while preserving dependency order and integration evidence.

## Inputs

- The canonical plan's goal, scope, decisions, and acceptance evidence.
- Real dependency edges, shared owner seams, protected work, and rollback boundaries.

## Required result

For each slice record:

- observable outcome and non-goals;
- owned files or seams and allowed effects;
- prerequisites and downstream dependents;
- implementation boundary, acceptance evidence, and rollback;
- blockers and exact next action.

Order slices by dependency. Prefer a vertical behavior slice that can be verified in isolation; combine work sharing one owner seam when separation would create duplicated setup or a false intermediate contract.

## Failure boundary

Do not split merely to parallelize or mirror architectural layers. If a slice cannot produce independent evidence, merge it with its owning outcome. Write slices only inside the canonical Handoff or Program.
