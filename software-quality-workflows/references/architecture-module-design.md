# Architecture and Module Design

Use this reference when a change creates, splits, merges, or reshapes internal modules, dependency boundaries, adapters, extension points, or other implementation seams. It owns internal architecture and seam placement. It does not widen authority or replace the owners of public contracts, security, testing, performance, or completion evidence.

## Contents

- [Owner boundaries](#owner-boundaries)
- [Design contract](#design-contract)
- [Interfaces are caller knowledge](#interfaces-are-caller-knowledge)
- [Module depth is leverage and locality](#module-depth-is-leverage-and-locality)
- [Seam placement](#seam-placement)
- [Dependency classification](#dependency-classification)
- [Compare materially different designs](#compare-materially-different-designs)
- [Domain language and durable decisions](#domain-language-and-durable-decisions)
- [Implementation, migration, and rollback](#implementation-migration-and-rollback)
- [Verification and completion record](#verification-and-completion-record)
- [Red flags](#red-flags)

## Owner boundaries

- Follow [Authority and Scope](authority-and-scope.md) for request mode, edit scope, risk, side effects, dirty-worktree ownership, and stop conditions. Once a safe change is authorized, choose the best-supported design without a routine approval question.
- Route contracts consumed outside the owning module to [API and Interface Design](api-interface-design.md). An internal boundary that becomes cross-package, cross-team, or externally consumed is no longer owned only here.
- Route RED/GREEN/REFACTOR and test shape to [Safe Test-Driven Development](test-driven-development.md), and test provenance or retirement to [Test Lifecycle Management](test-lifecycle-management.md). Do not delete an existing test merely to manufacture an ideal TDD history.
- Route trust-boundary threats and controls to [Security Hardening](security-hardening.md).
- Route performance claims and trade-offs to [Performance Optimization](performance-optimization.md).
- Route gate selection and completion claims to [Verification Discipline](verification-discipline.md).

This reference may require evidence from those owners, but it does not restate or weaken their policy.

## Design contract

Before changing a boundary, record a proportionate design contract:

| Question | Evidence to capture |
|---|---|
| Outcome | The behavior, change pressure, or ownership problem the design must improve. |
| Current ownership | The module that owns each policy, invariant, side effect, and dependency today. |
| Callers | Direct callers plus code coupled through errors, ordering, configuration, lifecycle, shared state, or operational assumptions. |
| Pressure | Observed changes, defects, duplicated policy, trust crossings, process failures, or migration needs that justify work now. |
| Constraints | Compatibility, latency, throughput, security, deployment, generated artifacts, and repository conventions. |
| Alternatives | For a high-cost or hard-to-reverse boundary, at least two materially different designs and the status quo. |
| Proof | The smallest caller-observable tests and affected-area gates that can distinguish success from rearrangement. |
| Transition | Migration order, coexistence period if any, rollback boundary, and removal condition for temporary paths. |

Do not start from a preferred pattern and search for a justification. Start from repository evidence and a concrete pressure the current design handles poorly.

## Interfaces are caller knowledge

An interface is everything a caller must know to use a module correctly, not only an exported signature or language-level protocol. Inventory:

- names, types, units, defaults, accepted values, and invariants;
- errors, retryability, partial success, cancellation, and cleanup obligations;
- ordering, idempotency, concurrency, reentrancy, and state-transition rules;
- configuration, construction, lifecycle, ownership, and disposal;
- side effects, persistence, network or process behavior, and trust assumptions;
- material latency, memory, throughput, or batching characteristics on which callers depend.

If callers must know an implementation detail, that detail is part of the effective interface even when it is private in syntax. Either make the knowledge explicit and owned, or redesign the module so callers no longer need it. Do not claim encapsulation while tests, configuration, or call sites encode hidden internals.

## Module depth is leverage and locality

A deep module hides many decisions and failure details behind a small, coherent concept. Evaluate depth as leverage and change locality, not as an interface-lines to implementation-lines ratio.

- **Leverage:** how much useful policy, coordination, validation, or external complexity the caller receives for the knowledge it supplies.
- **Locality:** whether one conceptual change can be made and proved at one owner instead of being distributed across callers.
- **Coherence:** whether the hidden decisions belong together and change for related reasons.

A short adapter can be deep when it absorbs a real vendor, trust, or process boundary. A large class can be shallow when callers still coordinate its steps or understand its internal states.

Use two diagnostic tests:

1. **Deletion test:** if the module or wrapper disappeared and callers invoked its dependency directly, what meaningful policy, volatility, invariant, failure handling, or boundary knowledge would be lost? If the answer is nothing, the layer is probably pass-through indirection.
2. **Distribution test:** for a representative policy change, where would edits and proof be required? A useful boundary localizes the change. If callers must change together, the effective interface is too wide, the ownership is misplaced, or the abstraction leaks.

These are reasoning tests, not numerical targets. Do not optimize file count, line count, or dependency count while making ownership less clear.

## Seam placement

Create or preserve a seam only when repository evidence identifies an independent boundary, such as:

- observed implementations or policies that change independently for a current requirement;
- a real external service, SDK, filesystem, clock, randomness source, device, or provider boundary;
- a trust boundary requiring centralized validation, authorization, or redaction;
- a process, network, queue, transaction, persistence, or lifecycle boundary with distinct failures;
- a stable ownership boundary whose consumers must not coordinate internal decisions.

Do not create a seam solely because a future implementation is imaginable, a mocking framework prefers it, or a unit test wants access to a private detail. Prefer proof through the highest stable owned interface. A single current implementation does not invalidate a seam when it represents a real external, trust, process, or ownership boundary.

Keep seams narrow around the policy or boundary they own. Do not expose vendor objects, incidental orchestration steps, or test controls unless they are part of the real contract. Name temporary adapters, their owner, expiry condition, and removal proof.

## Dependency classification

Classify each dependency before introducing inversion, injection, or an adapter:

| Dependency class | Default design response |
|---|---|
| Same-owner stable implementation detail | Keep it concrete and private; direct calls are usually clearer. |
| Observed independently changing policy | Isolate the smallest stable policy contract; keep selection and defaults at one owner. |
| External provider or platform | Adapt at the integration boundary when doing so hides provider-specific shape, failure, or lifecycle knowledge. Preserve material semantics rather than inventing false portability. |
| Trust boundary | Place parsing, validation, authorization, and safe failure at the boundary; apply the security owner. |
| Process, network, queue, or persistence boundary | Make timeout, cancellation, retry, idempotency, partial failure, recovery, and ownership explicit. |
| Cross-package, cross-team, plugin, or external consumer | Treat the surface as public or semi-public and apply the API owner. |

Dependency direction should follow policy ownership and volatility, not a ritual that every concrete type needs an interface. Reclassify when evidence changes; do not preserve accidental abstraction merely because it already exists.

## Compare materially different designs

For a high-cost, cross-cutting, or hard-to-reverse boundary, compare the status quo and at least two materially different designs before implementation. Renaming the same layers or moving the same interface between files is not a distinct design.

Useful differences include direct composition versus an owned facade, synchronous coordination versus an explicit message boundary, or one policy owner versus distributed caller policy. Compare each option on:

- caller knowledge and change distribution;
- ownership of policy, state, failures, and lifecycle;
- compatibility and migration cost;
- trust-boundary and operational consequences;
- measurable performance consequences;
- testability through real contracts rather than test-only hooks;
- reversibility, temporary machinery, and deletion path.

Choose the smallest design that satisfies the current evidence. Record why the rejected alternative would be materially worse under the same constraints; avoid generic pattern preferences.

## Domain language and durable decisions

Discover language from the repository before naming modules or interfaces. Inspect existing types, schemas, commands, tests, documentation, and call sites. Separate domain concepts from transport, framework, persistence, and UI implementation details.

Stress ambiguous terms with concrete scenarios: identify actors, starting state, event, invariant, outcome, and failure. Compare every claimed rule with current code and tests. Resolve synonyms, overloaded names, and concepts with incompatible lifecycles before turning them into module boundaries. Preserve established terms when they are accurate; change them only with migration proof when they are observable contracts.

Do not require a `CONTEXT.md`, ADR directory, or any fixed documentation path. Follow the repository's existing convention. Create a durable decision record only when all three conditions hold:

1. the choice is costly or hard to reverse;
2. the result would be surprising without its context;
3. real alternatives have a material trade-off.

Record only the needed context, considered alternatives, decision, consequences, validation, and reversal trigger. Keep routine, easily reversible choices in the code, test, plan, or change record rather than producing ceremony.

## Implementation, migration, and rollback

1. Capture characterization or contract evidence at the highest stable owned interface.
2. Make the target owner and dependency direction explicit before moving behavior.
3. For a wide change, prefer an expand-migrate-contract sequence: add the compatible owner, migrate callers in bounded slices, prove each slice, then remove the old path only after remaining consumers are absent.
4. Keep one authoritative policy during coexistence. If dual writes or reads are unavoidable, define precedence, divergence detection, reconciliation, and rollback.
5. Update callers, tests, configuration, generated artifacts, observability, and documentation that encode the old boundary.
6. Remove temporary adapters only when their declared removal proof passes. Test deletion follows the test lifecycle owner; architecture cleanup is not permission to discard coverage.
7. Keep rollback semantic: identify the last compatible state, data or protocol constraints, and how to restore ownership without destructive version-control operations.

Do not lift exploratory code into the production path without applying the normal plan, TDD, security, compatibility, and verification gates.

## Verification and completion record

Architecture proof must show changed ownership or locality, not only passing compilation after files moved.

- Prove representative callers through the real interface, including material errors and lifecycle behavior.
- Rerun affected tests, static checks, dependency or layering checks, and public-surface proof where applicable.
- Exercise the distribution test against at least one expected future change and state which edits are now localized.
- Verify temporary paths have owners and retirement conditions, and stale callers or generated artifacts were scanned.
- Measure performance when the design changes process, I/O, allocation, batching, or call frequency; do not infer improvement from shape alone.
- Apply security evidence at every changed trust boundary.
- Record the chosen design, alternatives, migration state, rollback boundary, proof run, and residual uncertainty.

A diagram, ADR, interface type, mock, or green unit test is not completion evidence by itself.

## Red flags

- Callers must understand internal sequencing, vendor objects, hidden state, or cleanup to use the module safely.
- A wrapper forwards calls without owning policy, translation, invariants, failure handling, or volatility.
- An interface exists only for tests or for a hypothetical future implementation.
- One conceptual change still requires coordinated edits across unrelated callers.
- Dependency injection moves construction everywhere instead of centralizing policy ownership.
- Domain terms were invented from implementation names without scenario and code validation.
- A fixed `CONTEXT.md` or ADR layout is imposed despite different repository conventions.
- A high-cost boundary was selected without materially different alternatives.
- A migration has two sources of truth, no compatibility window, or no rollback boundary.
- Tests are deleted to simplify the architecture or to recreate TDD history.
- Performance, security, or completion claims are made without their owning evidence.
