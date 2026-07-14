# Context and output economy plans

Use this reference when a plan must reduce LLM-visible context, prompt replay, or agent-facing tool output size without losing durable progress, retrieval quality, or verification quality.

This is a result-preserving planning pattern, not a pure minimization pattern. The goal is to move bulky state out of transient chat/tool envelopes while preserving the anchors and diagnostics needed for safe continuation.

## Core stance

A good economy plan protects behavior first and saves tokens second. It must distinguish:

- **Action-critical anchors** that must remain visible in compact/default output.
- **Bulky diagnostic state** that can move to debug/full output, persisted artifacts, logs, indexes, or local project docs.
- **Stable long-term state** that belongs in versioned files or durable project state, not repeated chat context.
- **Runtime evidence** that belongs in artifacts or log digests with paths/hashes/sizes, not pasted in full by default.
- **Unverified stability claims** that need soak, benchmark, or regression gates before being stated as achieved.

Do not frame success as “shorter at any cost.” Success means the compact path is smaller while still actionable, honest about coverage, and backed by tests or measured representative cases.

## When to apply

Use this pattern for plans involving any of these goals:

- Reducing repeated context loading for long-running agent or automation workflows.
- Designing resume/checkpoint/delta/log-digest/artifact-index mechanisms.
- Compacting agent-facing tool result envelopes or default summaries.
- Splitting compact/default output from debug/full diagnostic output.
- Reducing prompt/tool-output cost while preserving ranking, retrieval, verification, warnings, and required next actions.
- Optimizing cache/IO/output pathways where observable results must remain equivalent.

Do not place project-specific benchmarks, worknote paths, tool names, issue histories, or one-off implementation logs inside this reference. Keep those in the target repository's own planning/worknotes area.

## Required baseline

Before writing the plan, collect current evidence instead of relying on memory:

1. Representative current outputs or context packs.
2. Current tests/smokes that define behavior.
3. Current size data: serialized characters/bytes and, when available, tokenizer counts.
4. Known token sinks: duplicated prose, repeated traces, large raw matches, unbounded evidence blocks, copied stale plan text, redundant schema/context fields, and repeated logs.
5. Quality-critical fields that users or downstream agents actually need for the next action.

Record the source path, command, timestamp, or artifact identifier for every measured baseline. If exact tokenization requires extra packages, keep that benchmark external to product/runtime code unless the dependency is already justified.

## Classify fields before designing output

Separate fields into four groups:

1. **Always-visible anchors** — goal, user constraints, current phase/run, latest checkpoint, validation result, next action, blockers, risk flags, required actions, warnings, authority/budget state, and source/artifact refs.
2. **Compact evidence** — bounded snippets, top-ranked spans, counts, hashes, paths, coverage state, and enough rationale to explain why the next action is valid.
3. **Debug/full evidence** — raw traces, full candidate lists, complete provenance chains, large logs, internal scoring details, and diagnostic payloads.
4. **Persisted state** — artifacts, log digests, checkpoint files, local indexes, manifests, and versioned docs that can be loaded on demand instead of pasted into every response.

The compact/default path must never hide warnings, coverage gaps, required actions, source refs, or validation failures merely to save tokens.

## Design pattern

A complete plan usually defines:

- **Profiles or modes:** compact/default, standard, debug/full, and any machine-readable export mode.
- **Protected anchors:** the small set of fields that always survive compaction.
- **Lazy loading:** explicit follow-up read/debug paths for details omitted from compact output.
- **Resume material:** checkpoint, delta pack, log digest, artifact index, and next-action summary.
- **Staleness control:** remove copied-plan residue and stale literals instead of preserving them as examples future agents may reuse.
- **Budget policy:** bounded ranges for normal use, larger budgets for incident/debug/final audit modes, and a rule that tiny budgets are smoke tests only.
- **Compatibility gates:** existing behavior tests stay green unless the contract is deliberately changed.
- **Measured gates:** compare serialized output size and quality-critical fields on representative cases.

Derive budgets from representative measured envelopes and the task's protected anchors. `render_context_capsule.py` reports actual characters plus included/omitted IDs; tiny budgets are smoke tests, not production defaults. Do not encode universal character thresholds in the canonical plan.

## Typed-state projection contract

For Handoff/Program plans, full state remains external. Project only the current node objective and completion criterion, global invariants, fresh dependency outputs, scope/effect/approval, verifier and false-green risk, and related decisions/evidence/gaps. Never project full history, unrelated future nodes, raw chat, or sensitive payloads. Sensitive objects render as their stable ID plus `[REDACTED]`; omitted optional refs remain explicit on-demand pointers. A projection carries plan/source/scope hashes so freshness can be checked before use.

For autonomous closure, mandatory anchors also include the frozen contract hash, epoch, relevant hard/corner/verifier IDs, authority ceiling, and protected paths. The only admitted actual-state summary is a bounded SQW projection of incumbent identity, hard failures, and budget state. Candidate history, raw logs, portfolios, and the full contract stay behind stable on-demand references; shrinking the context budget may omit optional explanation but never these safety anchors.

## Test and verification gates

Add tests before implementation when possible:

1. Compact/default output contains all action-critical anchors.
2. Debug/full output still contains diagnostic details removed from compact output.
3. Existing tests that validate behavior or retrieval quality remain green.
4. Representative serialized output size decreases, or any exception is documented with a quality reason.
5. Final size accounting measures the actual high-level envelope that will be shown to the agent, not only an inner helper's partial payload.
6. Coverage/warning/required-action fields cannot silently disappear from compact mode.
7. Stored artifact/log/checkpoint references resolve to real files or retrievable records.

For result-preserving optimizations, keep old outputs as golden artifacts when practical and compare counts, keys, ordering/ranking guarantees, and required fields before claiming parity.

## Plan skeleton

A concise plan can use these sections:

1. Goal and non-goals.
2. Current baseline and measured token/size sinks.
3. Protected anchors and field classification.
4. Proposed output/context profiles.
5. Storage, artifact, checkpoint, or lazy-load design.
6. Compatibility and quality gates.
7. Size benchmark method.
8. Phased implementation order.
9. Rollback plan.
10. Risks, remaining uncertainty, and validation boundary.

## Pitfalls

- Do not save tokens by deleting warnings, required actions, coverage state, source refs, or validation failures.
- Do not weaken tests from full evidence to no evidence; make full-evidence tests request debug/full mode.
- Do not add tokenizer dependencies to product/runtime code just for a benchmark when serialized-size checks are sufficient there.
- Do not claim long-run stability before soak or representative wall-clock validation.
- Do not leave stale copied facts inside a “things to remove” list if those literals could later be mistaken for current facts.
- Do not use project-specific paths, names, benchmark artifacts, or issue histories in this reusable reference.
