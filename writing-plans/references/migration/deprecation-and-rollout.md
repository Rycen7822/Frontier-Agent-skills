# Deprecation, Migration, and Rollout

## Purpose

Define replacement, coexistence, cutover, rollback, and removal for a real public or persisted compatibility boundary.

## Inputs

- Current and target contracts with known consumers and stored-state boundaries.
- Authority for each migration and rollout effect.
- Compatibility window, observability, rollback trigger, and terminal removal condition.

## Required result

Inside the canonical Program Plan, record:

- old-to-new contract mapping and affected consumers;
- ordered preparation, dual-operation only when unavoidable, cutover, and cleanup milestones;
- proof and rollback gate for every externally visible transition;
- temporary compatibility owner, observable removal condition, and deterministic removal gate;
- data/state handling, failure containment, and irreversible effects.

The final milestone removes superseded paths and tests after the removal gate passes. No compatibility path is permanent by omission.

## Failure boundary

Do not invent consumers or preserve speculative compatibility. Return unknown contracts, architecture choices, or operational authority to Software Quality Workflows. Create no migration tracker beside the Program Plan.
