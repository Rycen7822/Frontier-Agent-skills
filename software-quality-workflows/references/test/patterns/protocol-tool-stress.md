# Protocol and Tool Stress Pattern

## Purpose
Exercise an agent-facing protocol/tool surface across positive, negative, boundary, timeout, cancellation, and budget behavior without exceeding authority.

## Use when
- A protocol server, tool bridge, or agent-facing interface needs more than a happy-path unit check.

## Do not use when
- The contract is undefined or a probe would invoke an unapproved stateful capability.

## Required inputs
- task context; advertised capability list; handshake/spec/schemas; error/timeout/cancellation contracts; installed/public entrypoint; per-capability side effects/authority; isolated substitutes; and total budget.

## Procedure
1. Capture baseline handshake/capability inventory and build a positive/negative/boundary/malformed/timeout/cancel/budget matrix.
2. Mark side effects before execution; use isolated state or controlled doubles and run only authorized actions.
3. Apply per-probe timeouts and a bounded total budget; record secret-free request/response, error class, duration, and cleanup state.
4. Classify failure as product defect, contract mismatch, stale probe, expected fail-closed, harness gap, unavailable environment, or permission denial.
5. Correct stale/invalid probes, then rerun representative positive smokes; direct library calls do not prove public protocol health.
6. Prove handshake/discovery, representative positive behavior, negative errors, timeout/cancel semantics, and installed routing; terminate only task-owned processes/state/ports.

## Required result
- One `test-patterns-protocol-tool-stress` with capability/probe matrix, authority and isolated-state refs, machine-readable outcomes/durations, classification, public/installed coverage, cleanup, and unresolved limits.

## Stop
Stop at bounded stress evidence; do not invoke unapproved capabilities or leave timed-out children/processes alive.
