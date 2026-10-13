# Architecture judgment

Use for a candidate whose ownership, classification or granularity is uncertain. These examples guide judgment rather than prescribe a universal folder layout.

## Useful abstraction, wrong owner

Shared search results and provider identities defined in one concrete provider make unrelated adapters depend on that implementation's classifications. Put the domain contract in a neutral owner inside the existing feature; keep service-specific authentication, wire format, billing and capabilities with each adapter. Type-only dependencies can establish ownership debt without being runtime cycles.

A response filter coordinates returned results, cited sources and inline content. Moving it out of formatting is useful, but placing the whole operation in a low-level domain-name normalizer still reverses responsibility. Keep normalization and matching below the response policy; formatting consumes the resulting facts.

Check what a normal change forces maintainers to understand or edit. Similar names and a tidier tree are insufficient evidence of corrected dependency direction.

## Reuse the real mechanism

Historical entries and evidence directories can share byte pagination with tool output. They should not pretend to be successful tool calls with invented arguments, error status or execution timestamps. Keep material kinds honest and share the actual byte-source mechanism. Preserve supported cursor and archive formats separately from internal representation cleanup.

Likewise, adapters with similar HTTP calls may enforce different paid opt-ins, failure categories or redirect rules. Share identical policy where it has one owner; retain real protocol differences. A common interface is worthwhile when it reduces actual obligations, not merely because two files contain similar lines.

## Interface cost and locality

An interface includes everything a caller must know to use a capability: ordering, invariants, failure modes, configuration, resource cleanup and performance. Fewer parameters do not help if callers must reconstruct hidden coordination. A deep implementation can be valuable behind a small honest interface; merging unrelated responsibilities into a large opaque module can still make architecture worse.

Imagine removing a suspected wrapper. If an unnecessary transformation or forwarding chain disappears, inlining may help. If transaction, lease or recovery knowledge appears in several callers, the wrapper was earning its responsibility. One caller or adapter can be enough for a real identity, resource or platform boundary; adding a fake second adapter is not evidence.

Recent change hotspots, domain terminology and relevant design records reveal current pressure. Respect settled decisions unless changed requirements or concrete friction justify reopening them. Compare alternatives only when the answer could materially change; include a real caller example and its obligations rather than a menu of speculative frameworks.

## State, identity and lifetime

A process handle can own decoding, byte cursors and termination while its manager owns waits, delivery and retention. Sharing one mutable bag lets lower-level code initialize upper-level policy and makes progression hard to trace. Composition can clarify both owners, with one commit point for each advancing cursor.

Before adding a lock, ask whether the writers need one canonical object. Independent facts can have separate owners and merge at a read boundary. A genuinely atomic invariant needs structural serialization; splitting its fields to avoid a lock can lose correctness.

Distinguish requested cancellation, worker exit, output-stream closure, archive completeness and user-visible completion. Similar values on a happy path do not make states interchangeable. After an `await`, cached authorization or mutable history may need renewed validation even inside the same process.

Types should express real identity and phase distinctions rather than optional fields that admit contradictory states. Parse external input into the authoritative representation. Strengthen at demonstrated confusion or partiality, not every primitive or internal expression; types cannot prove changing runtime facts remain fresh.

## Taste with consequences

Investigate wrappers without current consumers, impossible optional branches, repeated classification tables, transformations immediately undone, names hiding unrelated effects, comments promising an absent fallback and text used as a control protocol. Explain reader burden, change propagation or actual consumer consequences. Do not use "AI-generated" as a diagnosis.

Long functions, short files, defensive branches, global maps and upstream provenance can all have valid reasons. Trace the responsibility and relevant protection before recommending deletion or splitting. Extracting every pure expression for testing can scatter one rule rather than improve it.

## Finish the migration

For an internal API change, account for participating callers, dynamic registrations, generated consumers and operational entrypoints, then migrate and retire the obsolete route coherently. Keep actual public API, stored-data and compatibility obligations. Removing a declaration while retaining a live fallback is not complete retirement.

Inspect directly affected tests when their behavior obligation changes. Preserve or migrate unique protection; retire checks whose sole obligation ended. A new interface test does not automatically subsume an independent cancellation, resource or protocol check. Temporary diagnosis and migration acceptance remain temporary unless continuing protection justifies retention.

## Sources and scope

These examples distill the metis-pi architecture review and its later corrections, FAS structural-simplification guidance, and selected MIT-licensed pstack and mattpocock/skills guidance. Source comparisons used [pstack at 1dcc2bac](https://github.com/cursor/plugins/tree/1dcc2bacde73ddd284803b7af28164d0436198fc/pstack/skills) and [mattpocock/skills at 49dd158](https://github.com/mattpocock/skills/tree/49dd158d1076134a641b33efb035946536778336/skills/engineering). The cases are diagnostic examples, not fixed implementation requirements.
