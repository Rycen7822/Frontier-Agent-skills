# Deprecation and Migration Plans

Use this reference when planning removal or replacement of an API, schema, CLI behavior, tool schema, plugin/runtime surface, database shape, feature flag path, compatibility shim, generated artifact, or subsystem that may have consumers.

## Principle

Replacement comes first, migration comes second, deletion comes last. A deprecation is complete only when old code, tests, docs, config, examples, flags, and references are removed or explicitly retained as a supported contract.

## Plan workflow

1. **Inventory consumers.** Find code call sites, external users, cron jobs, skills, tests, docs, generated clients, configs, dashboards, and release artifacts that depend on the old surface.
2. **Define the replacement.** Specify the new owner seam, contract, compatibility story, and proof that it covers all critical use cases.
3. **Choose migration shape.** Use direct rewrite, strangler, adapter, dual-write/read, feature flag, staged rollout, or tooling only when that shape has an owner and removal gate.
4. **Measure active usage.** Add logs/metrics/searches/audits that prove remaining consumers; do not remove based on hope or stale code search alone.
5. **Migrate consumers.** Move one slice at a time, verifying behavior and compatibility after each slice.
6. **Stop new usage.** Mark old APIs/config/docs as deprecated, fail or warn in development where safe, and prevent new consumers.
7. **Delete the old path.** Remove old implementation, tests that only protect removed behavior, docs, examples, flags, config, snapshots, and migration notices once their purpose is complete.
8. **Audit leftovers.** Search for old names, tokens, file paths, feature flags, docs, and generated artifacts; classify intentional compatibility residues explicitly.

Before planning deletion, define a consumer oracle that can distinguish active, migrated, unknown, and intentionally supported consumers. Bind the rollback window to observed rollout evidence, and express every removal constraint as a hard contract condition when autonomous closure is active. A candidate cannot waive an unknown consumer, expire an adapter, or shorten that window.

## Design-ledger rows to include

| Row type | Required content |
|---|---|
| Baseline | Existing surface, consumers, compatibility assumptions, owner, usage evidence. |
| Decision | Replacement surface, migration shape, files/seams touched, rollout order, proof. |
| Compression | What old code/config/tests/docs will be deleted, merged, rewritten, or retained and why. |
| Proof | Consumer migration evidence, compatibility tests, zero-active-usage signal, rollback path. |

## Migration patterns

- **Direct rewrite:** Use when consumers are local and tests can prove all call paths.
- **Strangler:** Route one consumer class or endpoint at a time to the replacement while the old path remains fallback.
- **Adapter:** Keep the old interface temporarily while delegating to the new implementation; record expiry and deletion gate.
- **Feature flag:** Deploy inactive, enable for internal/beta/canary cohorts, monitor, then remove the flag after full rollout.
- **Dual-run or shadow:** Compare old/new outputs without changing production behavior before promotion.

## Done criteria

- Replacement is production-proven or locally proven at the risk level of the system.
- All active consumers have moved, with evidence from code search, runtime metrics/logs, or migration reports.
- Old code, tests, docs, examples, config, feature flags, and snapshots are removed or explicitly retained as supported compatibility.
- New usage of the deprecated surface is blocked by tests, lint, docs, or ownership review where practical.
- The rollback window is defined until the old path is deleted; after deletion, restoration path is the VCS revert or documented release rollback.
- Every removal constraint has passed its consumer oracle with fresh evidence; unknown external consumers remain blocking rather than being counted as zero.

## Red flags

- “Soft deprecation” with no owner, metric, or deletion date.
- New features added to the deprecated path.
- A compatibility adapter without tests or expiry.
- Removing code without proving zero active consumers.
- Renaming old files or docs while preserving the old behavior and calling it cleanup.
