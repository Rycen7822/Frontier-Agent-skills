# Behavior evidence and test retention

## Purpose

Resolve genuine ambiguity about the behavior distinction, oracle, test shape, or retention class without turning every change into a mandatory test ceremony.

## Establish the distinction

State the trigger/input, required output or state transition, boundary/error behavior, non-goals, and compatibility. Use the lightest channel that reaches the real owner surface: an existing test, focused regression, temporary reproduction, smoke, property/metamorphic check, benchmark, installed surface, browser, or real runtime.

Strict RED is not required. A valid pre-change failure reaches the intended surface and shows the missing or wrong behavior; syntax, setup, fixture, permission, harness, or unavailable-environment failures do not. If a focused test already passes, distinguish existing behavior, a weak oracle, and the wrong surface before editing.

Derive expected values from a requirement, worked literal, independent reference, fixed cross-version fixture, or property. Name a plausible wrong implementation the check rejects. Add an independent fixed expectation when both sides of a round trip could share one defect. Prefer public behavior over private call order.

## Implement and prove

Preserve user patches and valid contracts. Complete the smallest coherent owner set before proof. When an unresolved risk or explicit gate remains, run the lowest-cost independent evidence that decides it; escalate only when that evidence cannot support the claim. Never weaken the oracle, skip a required gate, or change expectations merely to obtain GREEN.

## Retention classes

Classify every test added or materially changed in the current diff exactly once:

| Class | Disposition | Boundary |
|---|---|---|
| `durable_contract` | retain | Stable observable behavior |
| `regression` | retain | Confirmed reproducible defect |
| `risk_boundary` | retain | Authority, safety, data, error, or other high-risk boundary |
| `migration_temporary` | conditional | Temporary old/new/rollback proof with a removal contract |
| `temporary_probe` | remove | One-off reproduction or exploration |
| `duplicate` | remove or merge | No unique protection or localization |
| `implementation_coupled` | rewrite or remove | Protects private structure rather than stable behavior |

`migration_temporary` requires nearby equivalent information:

```text
Temporary migration test
Owner: <component/team>
Remove when: <observable condition>
Removal gate: <command or deterministic check>
```

Refactors, documentation, configuration, generated artifacts, and spikes default to no new permanent behavior test. Complex pure logic retains only a small non-duplicate example/property set. Review the current diff only; do not create a registry or audit the historical suite.

## Required result

Record the distinction, oracle provenance, wrong implementation rejected, pre-change evidence or limitation, owner seam, focused and affected proof, retained contracts, per-test class, removed probes/duplicates, and remaining evidence limits.
