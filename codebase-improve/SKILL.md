---
name: codebase-improve
description: Review and improve a codebase's architecture, responsibility boundaries, layering and abstraction granularity.
disable-model-invocation: true
license: MIT
metadata:
  version: 1.0.0
  author: Frontier Agent Skills
  hosts: [codex, pi, hermes-agent]
---

# Codebase Improve

Use only after the user explicitly invokes `codebase-improve`. A general architecture request or another skill selecting it is not an invocation. Follow the user's scope: an audit stays read-only; requested improvements continue through implementation and verification within existing authorization. Do not add a mandatory candidate-selection or approval phase.

## Understand the actual architecture

Establish the selected component, change or whole-repository scope and current source state. Read relevant project constraints, entrypoints, consumers and design decisions. With no named scope, actual maintenance friction and recent change hotspots can guide exploration; they do not replace an explicitly requested full audit.

Identify who owns each relevant concept, policy, representation, identity and lifecycle, and which direction dependencies should follow. Treat architecture documents as claims to check against implementation. Distinguish current mechanism from historical motivation; consult history when a protection or boundary's purpose would change the decision. Use the project's domain language without imposing a fixed layered directory scheme.

Read implementation and consumers manually. Search, AST tools, graphs and statistics locate evidence; they do not establish understanding. Record useful observations, counterevidence and unresolved scope in the project's temporary area as work progresses. Small tasks need no separate ledger. For an explicitly requested whole-repository manual audit or authorized coordinated review, read [audit and collaboration](references/audit-and-collaboration.md).

## Judge responsibility and abstraction

For a structural candidate, answer the questions its role makes consequential:

- **Does it earn its responsibility?** Identify actual consumers, policy, protocol or lifetime it encapsulates. Thin code and a single caller can still own a useful boundary.
- **Does it belong here?** Check domain versus provider, policy versus mechanism, presentation versus fact, persistence versus application, and host adaptation versus domain state. A useful, reused abstraction can still live in the wrong layer.
- **Should it be independent?** Consider what callers must know: invariants, ordering, errors, configuration, resource handling and performance, as well as signatures. Removing it should eliminate unnecessary knowledge rather than distribute its implementation across callers.
- **Should responsibilities be separated?** Look for different lifetimes or reasons for change, multiple writers interpreting the same state, repeated decision tables, false business objects used for reuse, and control flow that crosses an owner invisibly.

Trace an implicated path through its consumer, state transitions, publication and failure or cancellation behavior. Check where shared state is actually necessary before adding locks or splitting an invariant. Parse external data at its real trust boundary; internal typing does not settle freshness across an `await`, a cache or mutable aliases.

Connect each finding to source, a responsibility conflict and a concrete maintenance or behavior consequence. Structural debt can be actionable without a reproduced runtime bug. Keep defect, structural judgment, taste observation and unproven risk distinct. Code smells are prompts to investigate, not automatic transformations. Describe AI slop as specific redundant or misleading code shapes; do not infer authorship. For examples that distinguish useful changes from overcorrection, read [architecture judgment](references/architecture-judgment.md).

Compare retaining the current design with the smallest useful change. Alternatives or prototypes are warranted only for a real unsettled decision. Preserve useful boundaries and record decisive counterevidence or withdrawn claims. Do not require deeper modules, more interfaces, fewer files, smaller line counts or a fixed number of findings.

## Improve a complete responsibility slice

When implementation is authorized, give the affected rule or state a clear owner, migrate necessary consumers and remove genuinely retired machinery in the same coherent slice. Follow participating registrations, generated consumers, configuration, persisted formats and delivery surfaces when relevant. Internal callers alone do not justify indefinite compatibility layers; actual external or stored-data obligations can.

Keep distinct policies, resource lifetimes and failure semantics even when syntax looks similar. Strengthen types where a real invalid combination or identity confusion appears, using authoritative schemas and existing representations. Avoid a replacement framework, general parameter bag or extra wrapper that merely relocates the burden.

Verify the decisive premise and affected consumer with the least costly sufficient existing evidence. Apply Test Behavior before authoring or modifying any check, including inline probes, temporary scripts and fixtures, and when behavior or compatibility obligations end. If that skill is unavailable, settle necessity, independent expectations and temporary versus permanent lifetime before writing. Source inspection does not automatically require a new test; a higher-level test does not automatically retire lower-level protection.

After a coherent change, recheck ownership, dependency direction, caller obligations and implicated timing or failure paths. Use existing design, simplification, review or runtime methods when their distinct work helps; do not load a fixed pipeline. Delegate only when authorized and worthwhile. Commit, publish or install only within the user's authorization.

## Finish with an accountable result

Combine findings sharing one root cause; resolve contradictions against source and fresh evidence. Report useful improvements or proposals, retained boundaries, unresolved concerns and material coverage or verification limits. A worker's completion message, a hash, a clean graph or passing tests does not prove the entire architecture is sound.

Stop when the requested scope is handled and further changes would be style churn, unsupported deletion or speculative generalization. For a full audit, reconcile actual unread scope before claiming completion. For an implemented change, distinguish behavior preserved, behavior intentionally changed, verification observed and remaining obligations.
