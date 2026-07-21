# Architecture Boundaries and Alternatives

## Purpose
Select coherent module/dependency ownership and the smallest evidence-supported architecture among materially different alternatives.

## Use when
- A change creates/moves/splits/merges ownership, dependency direction, cycles, trust/process boundaries, or a costly structural choice.

## Do not use when
- Only file layout/formatting changes or repository evidence leaves one obvious same-owner local seam.

## Required inputs
- task context; effective interface/callers; policy/state/failure/lifecycle owners; dependency/cycle graph; trust/process/provider/public consumers; current pressure; constraints; status quo/material alternatives; proof, reversibility, and migration facts.

## Procedure
1. Inventory names/types/defaults/invariants, errors/retry/partial/cancel/cleanup, order/idempotency/concurrency/state, construction/lifecycle, side effects, callers, and material resources.
2. Identify observed pressure—independent change, duplicated policy, defects, trust/process/shared-state coordination, or migration—before proposing a pattern.
3. Evaluate leverage, locality, coherence, deletion, and distribution: what policy/volatility disappears, and where must a representative policy change edit?
4. Classify dependencies as same-owner stable detail, independently changing policy, external provider, trust crossing, process/network/queue/persistence, or cross-package/team/plugin/external contract.
5. Keep stable details private; isolate only observed policy; adapt providers to hide material shape/failure/lifecycle; validate/authenticate/authorize at trust crossings; specify timeout/cancel/retry/idempotency/partial/recovery at process boundaries.
6. Follow ownership/volatility for direction, centralize construction/selection/defaults, and reject pass-through/test-only/hypothetical/vendor-leaking interfaces or injection that distributes construction.
7. Compare status quo and materially different architectures across caller knowledge, policy/state/failure ownership, compatibility/migration, trust/operations, measured performance, testability, reversibility, and deletion. Reject cosmetic variants.
8. Select the smallest supported design or emit a spike/decision blocker; record rejected rationale, consequences, validation/reversal triggers, and whether durable decision documentation is warranted by project convention and real cost.

## Required result
- One `domain-architecture-boundaries-and-alternatives` with interface/callers, pressure, module/dependency owner and directions, construction/lifecycle/failure contract, trust/public implications, options/evidence matrix, selected or blocked decision, rejected rationale, proof/reversal trigger, and migration need.

## Stop
Stop at one architecture decision or typed evidence blocker; do not implement or create documentation ceremony by default.
