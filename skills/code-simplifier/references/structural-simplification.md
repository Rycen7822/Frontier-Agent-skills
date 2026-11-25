# Structural simplification

Use this reference for a concrete structural candidate or an explicitly requested broad audit. It is not a repository-wide checklist for every edit.

## Establish a current burden

Start from an actual reading or change difficulty: tracing a forwarding chain, synchronizing two representations, repeating the same conversion, or coordinating an invariant across owners. Recent changes and the user's next requirement can reveal this pressure. A name, length threshold, single caller, or pattern match alone does not establish unnecessary complexity.

For a nontrivial candidate, connect the burden to the implementation and consumers you actually inspected. State what remains after the change and what observation would disprove its safety or value. Keep this brief in the working context; record it durably only when a real handoff or recovery need exists. Cite symbols and relevant locations rather than claiming exhaustive review from a sample.

Compare the proposed change with leaving the code alone and with a smaller local edit. Do not generate several designs by default. Retain an abstraction that encapsulates a real policy, lifetime, testing seam or platform boundary even when it currently has one caller.

## Verify consumers and authority

Trace the candidate through the consumer kinds its role permits: direct calls/imports, exports and public contracts, string registries or reflection, configuration, generated declarations and their generators, serialization, and operational entrypoints. Follow relevant evidence rather than scanning every category indiscriminately.

A search with no matches proves only that the chosen search found none. Dynamic dispatch, another supported build target, external users, and operational tooling can defeat that inference. For internal code, account for the relevant consumers; for exported or externally configured behavior, establish the support boundary. Missing consumers remain uncertainty, not a deletion certificate.

Retiring a supported external API, command, configuration value, persisted format or failure behavior requires authority for that behavior change. Authorization to simplify implementation is not that authority. Internal APIs can change within the authorized scope when relevant consumers migrate and external contracts remain intact. Where behavior removal is explicitly requested, name that delta separately from behavior-preserving edits and retain unrelated guarantees.

## Check where complexity goes

Compare both sides of the boundary, not only the edited function. After deletion, do callers need additional sequencing, options, conversions, retries, error knowledge, mocks, locks or synchronization? Does one invariant gain a clear owner, or must more sites reproduce it? A smaller local diff that spreads these obligations can be worse than retaining the abstraction.

Similar syntax is not necessarily the same policy. Keep independent cases separate when merging them introduces modes, boolean switches or coupled evolution. Conversely, a named intermediate value or a larger cohesive function can lower reader load; single-use expressions do not have to be inlined.

For repeated representations, identify which is authoritative and why another exists. Cached, normalized, serialized and presentation forms can have distinct lifetime, latency or compatibility roles. Remove one only when its role is redundant under the relevant workload and contracts, not merely because values match in the happy path.

## Preserve temporal and failure distinctions

Before merging mutable state, identify its owner, writers, readers, transitions and failure windows. Equality at a sampled instant does not establish interchangeability across time. Check only the properties implicated by the candidate: cancellation versus completion, initialization versus readiness, partial success, late callbacks, reentrancy, cleanup, resource release, and retry or publication order.

For example, a cancellation request may precede worker termination. Replacing `cancel_requested` and `finished` with one `done` flag can lose the interval in which work must stop publishing but still owns resources. A proof that both fields usually match does not settle this case.

A forwarding helper can also own a transaction, lock, exception translation, rate limit or resource lifetime. Inspect that role before inlining it. Deleting duplicate validation is safe only when the authoritative validation covers every relevant path with the same contract; do not silently broaden the trusted input domain.

## Finish a coherent removal

The change unit is the smallest complete slice: the relevant declaration, implementation, registrations, callers, configuration, generator and generated output, tests, documentation and newly unused dependency. Touch only participating parts; do not manufacture work in every category. Use the repository's generation procedure instead of editing disposable output alone.

Inspection may extend beyond the user's edit scope. Editing may not. If a necessary consumer lies outside that scope, keep the current contract intact and explain the additional scope needed; continue other independent candidates. A compatible internal cleanup can still be useful, but do not describe a preserved compatibility path as removed.

Sequence dependent changes in reversible units. Remove legacy machinery after its relevant consumers are migrated and its support obligations are resolved. Reinspect affected edges after the change, including registration and generation paths that may not have direct type checks. Update only documentation and tests whose contracts or locations actually changed.

## Bound a broad audit

When a broad audit is explicitly requested, define the selected components, entrypoints or change surfaces before investigating. Prioritize real maintenance pressure. Use bounded work units; delegate only when the host supports it and independent work justifies the cost. Investigators can remain read-only while one owner coordinates edits.

Combine duplicate findings and retain concise reasons for rejected, blocked or still-unknown candidates so they are not rediscovered. A shard completing its assigned files does not prove the selector covered every relevant consumer. Report the inspected scope and unresolved coverage. Do not force findings, automatic repairs, multiple reviewers or a persistent candidate system.
