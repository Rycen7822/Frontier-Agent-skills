# Test Patterns Handbook

This handbook owns reusable, product-neutral testing patterns distilled from prior debugging and TDD cases. Load only the pattern that matches the current contract. Authorization and verification policy remain in their canonical owners.

## Contents

- [Pattern map](#pattern-map)
- [PAT-01 — Primary and optional workflow boundaries](#pat-01--primary-and-optional-workflow-boundaries)
- [PAT-05 — Public adapter contract migration](#pat-05--public-adapter-contract-migration)
- [PAT-06 — Cross-language contract refactor](#pat-06--cross-language-contract-refactor)
- [PAT-07 — Local read-only dashboard](#pat-07--local-read-only-dashboard)
- [PAT-08 — Dashboard data lineage](#pat-08--dashboard-data-lineage)
- [PAT-09 — Protocol and tool stress testing](#pat-09--protocol-and-tool-stress-testing)
- [PAT-10 — Native rewrite parity](#pat-10--native-rewrite-parity)
- [PAT-11 — Retrieval fixture curation](#pat-11--retrieval-fixture-curation)
- [PAT-12 — Semantic contract upgrade](#pat-12--semantic-contract-upgrade)
- [PAT-13 — Benchmark fixture curation](#pat-13--benchmark-fixture-curation)
- [PAT-14 — Legacy manifest comparison](#pat-14--legacy-manifest-comparison)
- [Cross-pattern closeout](#cross-pattern-closeout)

## Pattern map

| ID | Canonical owner |
|---|---|
| PAT-01 | This file: primary and optional workflow boundaries. |
| PAT-02 | [Managed Runtime SDK Smoke](managed-runtime-sdk-smoke.md): version-bound public-path smoke. |
| PAT-03 | [Debugger-Assisted Diagnosis](debugger-assisted-diagnosis.md): task-owned live-process evidence. |
| PAT-04 | [Dependency and Lockfile Drift](dependency-lockfile-drift.md): updater and lockfile drift. |
| PAT-05 | This file: public adapter contract migration. |
| PAT-06 | This file: cross-language contract refactor. |
| PAT-07 | This file: local read-only dashboard. |
| PAT-08 | This file: dashboard data lineage. |
| PAT-09 | This file: protocol and tool stress testing. |
| PAT-10 | This file: native rewrite parity. |
| PAT-11 | This file: retrieval fixture curation. |
| PAT-12 | This file: semantic contract upgrade. |
| PAT-13 | This file: benchmark fixture curation. |
| PAT-14 | This file: legacy manifest comparison. |

Risk labels and action permissions come from [Authority and Scope](authority-and-scope.md). Gate names, evidence labels, and completion claims come from [Verification Discipline](verification-discipline.md).

## PAT-01 — Primary and optional workflow boundaries

**Applies when:** A required operation is followed by optional rendering, decoration, notification, upload, summary, or other post-processing.

**Do not use when:** The downstream step is required for correctness, security, compliance, recoverability, or the user’s requested artifact. Required work must not be relabeled optional to make a workflow green.

**Risk class:** Inherit the highest risk of the primary and optional operations; resolve permission in the authority owner.

**Canonical source:** The target workflow contract, job graph, exit semantics, and consumer requirements.

**Pattern:**

1. Define the primary success artifact and failure status independently of post-processing.
2. Run optional work only after primary success.
3. Catch failure only at the optional boundary, not around the primary operation.
4. Preserve primary failure unchanged.
5. Make optional failure observable with its own status and diagnostic evidence.
6. Ensure later steps consume the primary artifact rather than assuming decoration succeeded.

**Verification:** Exercise primary failure, primary success plus optional success, and primary success plus optional failure. Confirm the first remains failed, the second is complete, and the third preserves the primary result while exposing partial optional status.

**Cleanup/rollback:** Remove only task-owned optional artifacts. Do not delete or overwrite the primary result during optional cleanup.

## PAT-05 — Public adapter contract migration

**Applies when:** Internal runtime tests pass but a CLI, wrapper, protocol, schema, preflight, router, installer, or other public adapter is being migrated or still fails.

**Do not use when:** The change is wholly internal and no public boundary or state identity changes.

**Risk class:** Usually LOCAL_REVERSIBLE in isolated state; inherit a higher class if the public path writes external or shared state.

**Canonical source:** The public contract, schema, entrypoint documentation, state identity rules, and pre-migration behavior inventory.

**Pattern:**

1. Inventory every public adapter that translates arguments, identity, paths, schemas, or errors.
2. Create a task-unique fresh state root and neutral working directory.
3. Prove read-only calls do not create durable state.
4. Prove the first authorized write creates only the canonical new state.
5. Exercise stale or legacy selectors and confirm the documented compatibility or rejection behavior.
6. Compare wrapper, preflight, schema, and runtime outcomes; do not infer adapter parity from internal unit success.
7. Scan dormant and generated surfaces that may still encode the old contract.

**Verification:** Run a public-path smoke in addition to internal tests. Assert state location, schema, errors, read/write boundaries, and absence or compatibility of retired selectors according to the approved contract.

**Cleanup/rollback:** Remove only isolated test state and restore task-owned configuration. Preserve migration artifacts needed for rollback until the contract gate passes.

## PAT-06 — Cross-language contract refactor

**Applies when:** Two or more language implementations must preserve the same observable behavior during extraction, rewrite, or consolidation.

**Do not use when:** The implementations intentionally expose different contracts, or when sharing a fixture would erase platform-specific semantics.

**Risk class:** Usually LOCAL_REVERSIBLE; resolve generated artifacts or external fixtures through the authority owner.

**Canonical source:** A versioned, data-only fixture schema with a documented oracle and an inventory of each implementation’s public behavior.

**Pattern:**

1. Characterize the current public behavior in every implementation.
2. Define a data-only fixture containing inputs, expected outputs, error cases, and schema version.
3. Keep fixture loading and execution native to each language.
4. Add a behavior RED in each implementation for the gap being changed.
5. Refactor language-local helpers and caller wiring in small slices.
6. Record intentional platform differences explicitly rather than hiding them in fixture code.
7. Never make one runtime call through the other merely to claim parity.

**Verification:** Run each language’s focused test against the same fixture, then the affected public surfaces. Compare serialized outputs and errors under a canonical normalization rule.

**Cleanup/rollback:** Remove temporary generated fixtures and restore only task-owned wiring. Keep the previous implementation available until parity and allowed differences are documented.

## PAT-07 — Local read-only dashboard

**Applies when:** A local dashboard or inspection UI reads persisted records, streams updates, or exposes a browser-visible installed surface.

**Do not use when:** The UI is allowed to mutate the backing store, is internet-facing, or requires a product-specific deployment topology; those need their own design and security review.

**Risk class:** Commonly LOCAL_REVERSIBLE because a loopback process, port, temporary data, or browser session is created.

**Canonical source:** The backing-store read contract, HTTP/API schema, public launch entrypoint, and [Browser Runtime Verification](browser-runtime-verification.md).

**Pattern:**

1. Use an isolated copy or explicitly read-only connection to the store.
2. Assert that missing data is reported without creating a new store.
3. Test the data layer, API, launch entrypoint, and browser surface as separate slices.
4. For streams, test initial data, incremental events, disconnect or end-of-stream behavior, and client cleanup.
5. Discover and exercise both the source-tree path and the user-facing installed path when they differ.
6. Verify the actual process identity, selected data root, bound loopback address, and assigned port.
7. In a real browser, inspect rendered state, asynchronous updates, console failures, and network responses.

**Verification:** Combine data/API assertions with a browser smoke and, when applicable, installed-surface proof. Confirm the store remains unchanged and the process and port terminate cleanly.

**Cleanup/rollback:** Stop only the task-owned process, close browser sessions, release the selected port, and remove the isolated store copy. Never clean a shared data root.

## PAT-08 — Dashboard data lineage

**Applies when:** A dashboard appears to omit records, layers, history, or status even though storage activity exists.

**Do not use when:** The defect is purely visual and the API already returns the correct, complete model.

**Risk class:** READ_ONLY when tracing existing code and state; any diagnostic data generation inherits its actual risk.

**Canonical source:** UI query code, API response schema, query or repository implementation, storage migrations, and record ownership documentation.

**Pattern:**

1. Trace UI selection to request parameters, API handler, query, and backing table or collection.
2. Distinguish current canonical records from raw events, history, cache, and derived summaries.
3. Validate identifiers and join keys at every layer.
4. Expose explicit zero states for requested categories rather than silently falling back to a different dataset.
5. Add separate views or endpoints when current and historical data have different semantics; do not merge them only to increase visible counts.
6. Confirm the running process uses the inspected schema and data root.

**Verification:** Use a small fixture with one current record, one historical or raw event, and one absent category. Assert each appears only in its intended surface and the absent category reports zero explicitly.

**Cleanup/rollback:** Use an isolated fixture store. Remove only task-owned records or copies after the lineage assertions complete.

## PAT-09 — Protocol and tool stress testing

**Applies when:** A protocol server, tool bridge, or agent-facing interface needs coverage beyond a happy-path unit test.

**Do not use when:** The protocol or tool contract is undefined, or the requested probe would invoke unapproved stateful capabilities.

**Risk class:** Derive per capability. Build the matrix before execution and run only actions allowed by the authority owner.

**Canonical source:** The advertised capability list, protocol specification, tool schemas, error model, timeout contract, and installed/public entrypoint.

**Pattern:**

1. Capture a baseline capability inventory and protocol handshake.
2. Build a matrix of positive, negative, boundary, malformed, timeout, cancellation, and budget cases.
3. Mark each capability by side effects and substitute isolated state or a controlled double where appropriate.
4. Use per-probe timeouts and a bounded total budget.
5. Save machine-readable request, response, error class, duration, and cleanup status without secrets.
6. Classify failures as product defect, contract mismatch, stale probe, expected fail-closed result, harness gap, environment unavailable, or permission denied.
7. Re-run corrected positive smokes after fixing a stale or invalid probe.

**Verification:** Prove public handshake and capability discovery, representative positive behavior, negative error semantics, timeout handling, and installed-surface routing when applicable. Do not infer protocol health from direct library calls alone.

**Cleanup/rollback:** Terminate only task-owned processes, remove isolated state, and confirm no timed-out child or port remains.

## PAT-10 — Native rewrite parity

**Applies when:** An implementation is being replaced by a different runtime or native implementation while preserving a public contract.

**Do not use when:** The approved goal intentionally changes the public behavior without a compatibility requirement.

**Risk class:** Usually LOCAL_REVERSIBLE during isolated development; packaging or deployment inherits its actual class.

**Canonical source:** A versioned inventory of the old public surface, approved differences, representative fixtures, and resource constraints.

**Pattern:**

1. Baseline commands, API or protocol endpoints, validation, errors, cache behavior, budgets, persistence, and evaluation fixtures.
2. Record allowed differences before implementation.
3. Add parity REDs one behavior group at a time.
4. Exercise the new runtime directly; do not call back into the old runtime when the goal requires independence.
5. Preserve deterministic hot paths and explicitly compare nondeterministic tolerances.
6. Include dormant surfaces such as help, subcommands, tool lists, low-budget paths, cache invalidation, and malformed input.
7. Measure performance and resource use when they are part of the rewrite goal, without weakening result equivalence.

**Verification:** Run new-runtime focused proof, cross-implementation fixture comparison, affected public-surface smokes, and the compatibility gate selected by the verification owner. Report allowed differences separately from regressions.

**Cleanup/rollback:** Keep a bounded rollback path until parity is established. Remove task-owned build artifacts and caches without touching user data.

## PAT-11 — Retrieval fixture curation

**Applies when:** Expanding or repairing evaluation data for retrieval, ranking, routing, or recommendation behavior.

**Do not use when:** Labels have no defensible oracle, or the same unreviewed model would generate, filter, and judge every case.

**Risk class:** Usually LOCAL_REVERSIBLE; external model calls, hosted evaluation, or uploaded datasets inherit their actual class.

**Canonical source:** Versioned case schema, evaluator implementation, metric definitions, source provenance, and human or domain judgment policy.

**Pattern:**

1. Normalize case IDs, prompts, gold targets, exclusions, categories, language, provenance, and evaluator version.
2. Separate exploratory top-k usefulness from top-choice precision.
3. Evaluate with the real retrieval path, not a hand-written proxy.
4. Measure task metrics and diversity, including category balance, normalized entropy, near-duplicate similarity, and novelty.
5. Use held-out cases and human adjudication for ambiguous or high-impact gold changes.
6. Record seed, generator version, filtering rules, removed cases, and refill decisions.
7. Prevent circular approval by separating candidate generation from final judgment where practical.
8. Reproduce path- or budget-sensitive flakes in a controlled short environment before changing scoring or gold labels.

**Verification:** Report saved case count, schema validation, retrieval metrics, diversity diagnostics, held-out results, and adjudication status. A requested target is complete only when that many accepted cases are durably saved and re-read.

**Cleanup/rollback:** Keep candidate and rejected data outside the canonical fixture until accepted. If a reviewed update degrades held-out behavior, revert only the manifest- and revision-bound delta created by this task. Before applying that inverse delta, verify that the canonical fixture still matches the recorded post-update revision; if it changed, re-read and reconcile the concurrent work instead of overwriting it with a prior snapshot.

## PAT-12 — Semantic contract upgrade

**Applies when:** Retiring an old name, payload, schema, alias, state identity, or public behavior across multiple surfaces.

**Do not use when:** The change is a local rename with no semantic or compatibility effect.

**Risk class:** Usually LOCAL_REVERSIBLE in source; migration, publication, or shared-state updates inherit their actual class.

**Canonical source:** The approved new contract, compatibility decision, consumer inventory, generated surfaces, and migration plan.

**Pattern:**

1. Add targeted REDs for the new contract and explicit old-contract rejection or compatibility behavior.
2. Reach targeted GREEN before broad cleanup.
3. Run broader proof and classify failures as stale old-contract tests, residual old behavior, genuine regression, harness gap, environment unavailable, or permission denied.
4. Search code, tests, fixtures, schemas, docs, generated assets, examples, and dormant entrypoints for retired symbols.
5. Treat text scans as candidate discovery, not semantic proof; inspect call paths and structured contracts.
6. Exercise public and installed surfaces that can preserve stale generated or packaged content.
7. Remove dead helpers only after consumers and rollback requirements are accounted for.

**Verification:** Combine targeted new-contract tests, affected gates, structured residual checks, public-surface proof, and installed-surface proof when packaging is part of the contract.

**Cleanup/rollback:** Retain the approved migration or rollback path until consumers are verified. Remove only confirmed dead compatibility artifacts.

## PAT-13 — Benchmark fixture curation

**Applies when:** An evaluation or benchmark corpus must gain an exact number of accepted cases, broader coverage, or a new contract stratum.

**Do not use when:** The request is only to preserve raw run output or create disposable diagnostic input.

**Canonical source:** A revision-bound manifest, fixture schema, acceptance oracle, target strata/count, duplicate rule, and held-out evaluation policy.

**Pattern:** Inventory accepted cases first; define the missing strata and exact target; keep candidates/rejections outside the canonical fixture; validate schema, provenance, privacy/licensing, deduplication, and oracle quality; compare held-out or parity behavior; apply only the reviewed manifest delta; then re-read the canonical fixture and count accepted cases from disk.

**Verification:** Report accepted delta/count, manifest revision/hash, schema and duplicate checks, coverage/diversity diagnostics, held-out outcome, and unresolved adjudication. A generated case is not accepted merely because it parses.

**Cleanup/rollback:** Compact durable selection evidence before deleting scratch. Revert only the task-owned manifest delta after confirming the canonical revision has not drifted.

## PAT-14 — Legacy manifest comparison

**Applies when:** A legacy and current manifest encode equivalent identity with different optional fields, and the current diff path would schedule unnecessary near-full refresh or rewrite.

**Do not use when:** The schema difference represents an intentional semantic, compatibility, or provenance change.

**Canonical source:** Versioned legacy/current fixtures, the comparison owner's identity contract, and the current refresh threshold or scheduling rule.

**Pattern:** Characterize equivalent old/current fixtures; distinguish required identity fields from optional/current metadata; normalize only at the comparison owner seam without rewriting the source manifest; exercise the real diff/scheduling path; preserve true additions/removals/changes; keep current-schema behavior unchanged; and obtain separate authority before any migration write.

**Verification:** A focused legacy fixture is RED for the intended false-diff before repair and GREEN after; an intentional semantic delta still schedules work; the current-format fixture and threshold behavior remain unchanged; any source write or migration is tested separately.

**Cleanup/rollback:** Remove temporary comparison fixtures only after the behavior is represented in canonical tests. Roll back the owner-seam normalization rather than mutating stored legacy evidence.

## Cross-pattern closeout

For any pattern, report the selected contract source, risk decision, focused behavior evidence, applicable public or installed surface, cleanup status, and unresolved limits. Do not convert a pattern-specific proof into a universal completion rule; the verification owner remains authoritative.
