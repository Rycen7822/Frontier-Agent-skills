# Execution and Grading

This file owns deterministic plan compilation, bounded runner behavior, host protocol, run-index row v2, receipt v4, artifact/provenance verification, grader execution/verification boundaries, resume, and apparatus failure classification.

## Preflight and isolation

Before execution:

1. audit the complete package and validate the frozen spec v5, scenario corpus, host manifest, and required preparation artifacts;
2. prove required host capabilities with bound `pass|unsupported|unknown` probes;
3. freeze execution identity, treatment intervention axes, catalogs, tools, permissions, fixtures, graders, reset, retry, clocks, and artifact root;
4. compile one plan v1 and verify its schema, self-hash, compiler identity, dispositions, counts, authority, and output paths;
5. keep evaluator instructions, hidden expectations, calibration, suite-quality proof, and grader material outside the tested executor.

Use one fresh or deterministically restored workspace per execute entry. Counterbalance treatment order when caches, time, services, or quotas can drift. Never flow generated files, conversation state, loaded Skills, or service state into another entry unless persistent state is the declared object.

Capture observable events and artifacts, never private chain-of-thought: retrieval/selection/load/application, tool and command status, permissions/network, retries/recovery, termination, stdout/stderr/exit, file/state diffs, verifier outputs, usage, and cleanup.

## Compiler and dispositions

`compile_eval_plan.py` is a pure projection. It starts no host, grader, verifier, or subject; reads no prior runtime result; and uses no wall clock, PID, process hash, or temporary path. It validates all bound inputs, rejects non-ready/placeholder contracts and failed preparation gates, expands the exact scenario × treatment × repeat matrix, counterbalances deterministically, derives capability-based dispositions, and writes one schema-valid, self-hashed plan.

Every entry is exactly `execute`, `unsupported`, or `not_evaluable`. Unknown required capability evidence takes precedence over unsupported evidence. Non-execute entries preserve their feasibility facts but receive no workspace, request, attempt, receipt, or index row. Plan and entry IDs are stable locators derived from full bound projections; the complete plan hash remains the collision and integrity authority.

## Runner and host protocol

`run_eval_plan.py` revalidates the plan and every current bound byte before action. For an execute entry it restores the fixture, proves reset, sends one canonical `execute_case` request to the manifest argv with `shell=False`, captures ordered host events and one terminal result, runs selected deterministic graders, sends only blinded bound `model_grade` requests, performs cleanup, validates receipt v4, then appends index v2.

Host stdout is protocol JSONL; stderr is an artifact. Non-UTF-8 output, event-sequence gaps, duplicate/missing terminal results, events after terminal, or request/identity/hash mismatch are apparatus failures. The runner never chooses a treatment, scenario, grader, module, or usefulness result.

Attempts run in task-owned process groups and isolated workspaces. Effective parallelism is the minimum of CLI, spec, and host limits. A single writer commits only the canonical continuous prefix ordered by `(entry_ordinal, attempt)`, so parallel completion and resume do not change final index bytes.

## Run-index row v2

Each JSONL row contains only `schema_version`, plan/entry/run identity, case/treatment/repeat/attempt, artifact directory, and receipt path/hash. It describes execute attempts only and contains no pass, score, routing, usage, grader, feasibility, or provenance claim. The runner requires `--index` to resolve to the plan-declared path under `artifacts.root`.

## Default evidence traversal

Raw scored receipts and their artifacts stay immutable for the frozen retention period, but they are not the model's default reading surface. Read analyzer summary → failure index → the spec-limited representative receipts. Open raw artifacts only through one named receipt for a named failure, grader disagreement, or integrity audit. Do not walk the artifact tree first, create per-step worknotes or per-notice JSON, or copy receipt data into parallel model-authored files. A short early failure remains a failed outcome and cannot establish an efficiency advantage.

## Receipt v4

One receipt owns the complete attempt evidence: run/provenance identity, artifacts, host protocol, routing, principals, handoffs, actions, observations, state, faults, usage, context usage, grader outputs, and cleanup. It binds plan, entry, scenario, host, package, catalog, treatment, fixture, grader, and conditionally calibration/quality identities.

The analyzer requires exact shapes. It normalizes POSIX-relative paths, rejects absolute/backslash/parent traversal, proves lexical and symlink-resolved containment, recomputes bytes/hashes, and rejects duplicate normalized or resolved artifacts. Every evidence locator and invocation references the exact artifact allowlist.

`receipt_hash` removes only itself and hashes canonical JSON. `completion_origin=resume_seal` is valid only for the schema-declared recovered-attempt form. No older receipt is accepted or silently upgraded.

## Routing, composition, and usage

For each declared treatment × turn cell, routing records declared, discovered, loaded, model-visible, selected, invoked, and applied Skill IDs, plus full catalog order and the declared composition shape. Every stage has its own evidence; no stage follows from a preceding stage. Exact no-match is evidence, not a failed target load. The runner compares raw host facts to the scenario routing contract, while the analyzer aggregates the same exact cells.

Catalog routing uses the host manifest's ordered base catalog plus the scenario overlay. Natural-routing comparators keep that effective catalog identical and change only the declared target delivery intervention. Composition is limited to one declared unordered pair, ordered sequence, or typed handoff edge; loading multiple Skills cannot establish composition by itself.

Usage preserves input, output, and cache token classes; queue/runtime latency; tool/network calls; retries/rework; requested/effective effort; artifacts/checkpoints/residue; pricing identity; and per-principal/turn/phase/call attribution. `usage.host_safety_review` aggregates only typed host events as `captured|missing`, review count, and elapsed milliseconds; missing capture never becomes a zero review, and raw reasons or session identities stay outside the receipt. Provider cache tokens and application-cache behavior are separate facts. Host preflight is apparatus cost, and failed treatment execution never becomes an efficiency win.

A host-classified model-task timeout or typed provider termination stops before deterministic and model graders. The raw host result remains apparatus evidence, but the attempt does not become a candidate failure or consume grader calls.

Evidence locators are one-based inclusive `{start_line,end_line}` spans into allowlisted UTF-8 artifacts. The analyzer proves that cited bytes/lines exist; the selected grader owns their meaning.

## Context receipt

`context_usage.status` is `captured|missing`. Captured with zero components is valid proof of zero target-Skill context; missing capture invalidates attribution. Receipt totals keep bytes, nullable tokens, controlled bytes, unique reference bytes, and controlled-core bytes separate.

Each component has a stable ID, kind, source path, content hash, allowlisted artifact, bytes, nullable tokens, and occurrence. Kind is `metadata`, `body`, `reference`, `protocol_output`, or `failed_command_output`. Static paths are canonical package-relative POSIX paths; dynamic paths are redacted protocol/failure identities, never command arguments or local machine paths.

Component order is model-visible event order. Failure, timeout, and partial output use `failed_command_output`; other successful helper output uses `protocol_output` unless it exactly equals a bound static file or deterministic continuous byte slice. The controller captures every skill-attributed visible event exactly once and distinguishes host activation from model-initiated reads. `force_loaded` requires exactly one host body injection; zero or multiple injections are apparatus-invalid. A later model reread stays evidence-complete and increments repeated load cost. The analyzer hashes artifact bytes and rejects any run whose components, routing, totals, or controlled-byte projections do not conserve. All projections stay in one receipt and its bound artifacts; parallel event/check sidecars are forbidden.

## Principals, handoffs, and state

When multi-principal coordination is required, every actual principal maps to one plan slot and binds parent, role, model/session/workspace, context mode/proof, Skill/catalog/tool/policy/authority identities, requested/effective budget, and terminal status. Unknown or duplicate principals, parent cycles, and width/depth/budget/authority violations fail closed. The evaluator verifies host-owned coordination; it never spawns, routes, cancels, or synthesizes principals.

Fresh, forked, and scoped-handoff context modes require different evidence. Causal ancestry is reconstructed independently from wall-clock delivery order, so asynchronous return order cannot rewrite dependency order. Every handoff preserves exact payload/schema/hash, scope, success criteria, supplied/omitted context, transferred authority, raw result, status, and any summary/filter/truncation transform. A summary without its raw result cannot support worker-level attribution.

State receipts preserve ordered turns/checkpoints, before/after state, opened/due/closed obligations, transitions, persisted-state identity, terminal state, and cleanup state. Resume must prove the declared durable state instead of relying on hidden conversation context.

## Actions, authorization, observations, and faults

Each effect-capable action uses one stable ID across declared/discovered/loaded/model-visible/selected/invoked, authorization request/resolution, executed input, raw backend result, model delivery, rendering, observed effect, and confirmed effect. Stages may terminate early and never imply a later stage.

Authorization preserves every policy/human/source decision and the deterministic resolution to `allow|deny|allow_with_changes`. Executed input must equal the approved input after any allowed changes. A denial/containment can pass safety prevention while leaving the task effect absent; reported success never substitutes for confirmed effect.

Observations separately close artifact bytes/schema/locator and temporal validity. Raw backend, model-delivered, and rendered content remain distinct, especially for untrusted tool errors. Grounding requires claim correctness, source existence, source support, locator attribution, and freshness.

Fault evidence joins the declared injection, trigger, typed effect, target call, observed response, recovery attempts, terminal resolution, and safety limit. Only plan-declared faults may be activated. Failure to reach a valid trigger because the treatment already failed remains a treatment result; host failure to inject a reached trigger is apparatus-invalid.

## Deterministic grader receipt

Every scenario-selected deterministic grader appears once as `{grader_id,invocation}`. The invocation binds exactly:

- the digest of the full grader declaration and verifier bytes;
- sorted selected check IDs;
- the spec-relative artifact root;
- the complete frozen host/fixture input artifact set and hashes;
- one allowlisted raw stdout JSON artifact, a distinct raw stderr artifact, and integer exit code.

All deterministic stdout/stderr paths are removed globally before computing the input set. Inputs cannot include any grader output or the receipt. The analyzer does not import or execute the verifier; it verifies the frozen invocation, parses the single stdout, and requires exit-code pass semantics to agree with `overall_pass`.

Model rubric output appears once as `{grader_id,batch}`. The batch reference binds the blinded request/item, frozen schedule/order, raw host-protocol batch artifact, and one normalized output artifact. Treatment labels never enter the blinded payload. Deterministic output cannot be supplied inline. Both paths feed the same semantic validator.

## Grader semantic owner

`grader_semantics.py` owns the exact `{view,check:{check_id,pass_condition}}` payload and canonical hash used by formal requests, calibration v2, and optional reviewer packets. Every formal item binds each check to the hash of that item's blinded view; a batch may share check declarations while retaining distinct item payload hashes. Absolute workspace locators and caller-defined forbidden view fields fail at the originating boundary.

The JSON Schema owns transport shape only. The analyzer also enforces:

- exactly the scenario-selected check IDs, each once;
- allowlisted evidence and valid line spans;
- structured missing evidence mapped to selected checks;
- required-only `overall_pass` (optional failures do not change it);
- either all weights or no weights, and `floor(raw_score + 0.5)` recomputation;
- apparatus failure shape: no checks, zero score, false overall, missing item, and non-empty reason.

Every requirement declares one `owner` matching its grader type, and one grader/check binding may occur only once. Commands, exit codes, test counts, file deltas, boundaries, load counts/bytes, protocol output, and source/plugin identity belong only to deterministic evidence. Model rubrics own semantic qualities such as executability, risk coverage, and boundary clarity; they do not rescore deterministic facts. A model/deterministic disagreement is reported without changing the deterministic result. Human/domain review is a separate authority receipt, and no weaker grader erases a deterministic or safety failure.

## Identity and custody matrix

Semantic identity and exact-byte custody are separate contracts. The following mutation boundaries are normative:

| Mutation | Changes | Remains valid or unchanged |
|---|---|---|
| Spec-owned check ID or pass condition | Grader/schedule, plan, formal payload/item/batch | No prior evaluation identity |
| Blinded view for the same check | Runtime payload/item/batch and receipt | Frozen plan |
| Calibration gold, rating, or bound hash | Calibration hash, rebound ready spec and plan | An unbound old spec fails closed |
| Fixture bytes | Fixture/corpus binding, ready spec, plan and entry | An old plan cannot run the new bytes |
| Fixture mode 0444 to 0644 with identical bytes | No content identity | Source mode; workspace is owner-writable and retains execute bits |
| Bound JSON whitespace | Raw custody hash and upstream binding, or rejection of non-canonical output | No byte change is hidden as the same artifact |
| Output item/check order with the same ID sets | Normalized judgment bytes may be canonicalized | Semantic result and batch binding |
| Runner status or lifecycle implementation | Bundle source/version and new test evidence | Compiler plan and existing receipt/index verification |
| Analyzer projection | Analyzer generator and report identity | Plan, receipt and index |
| Release authorization | Authorization hash and distribution eligibility | Evaluation evidence identity |

Frozen input verification always uses exact bytes. Normalization applies only at the declared semantic-output boundary; it never weakens custody of a bound source artifact.

## Process evidence levels

- Skill retrieval proves retrieval only; entry reading proves body loading only; a CLI or card reference proves an attempt only.
- A behavioral process check passes only when bound evidence proves exit 0, a successfully parsed receipt, the expected state transition, and every required owner, delivery, anchor, or cleanup fact. Final prose and task-code success cannot replace these facts.
- A pure routing scenario may use its exact declared load set as the terminal process contract because no workflow transition is required.

## Validity and failure ownership

`valid=false` is reserved for evaluation apparatus failure: provider/controller unavailable before attributable execution, broken fixture/capture, corrupt receipt, or grader failure. It requires a non-empty `run.error`.

Treatment-attributable refusal, timeout, empty output, tool/dependency error, nonzero task process, unsafe action, or malformed artifact remains `valid=true` when the host captured complete evidence. Normal grader requirements make it an outcome/process/safety failure in the denominator. Do not convert a negative treatment result into inconclusive evidence.

Preserve original attempts. Retry only predeclared apparatus failures; never retry until success and discard failures. Missing/tampered receipt evidence is incomplete/invalid, not a candidate hard failure.

## Retry and resume

Attempt numbers, run IDs, start markers, directories, receipts, and index rows follow the plan's deterministic projection. Treatment failures are never retried. A retryable apparatus failure keeps its receipt/index evidence before the next bounded attempt.

Each attempt holds a transient POSIX custody lock from directory creation through receipt/index commit. Every direct host, deterministic-grader, and model-grader child inherits that lock, so parent loss cannot make a live child appear recoverable. `--status` validates frozen inputs and current evidence, reports bounded canonical `runner-status/1` JSON, and never creates a file or lock.

Every run/resume supplies `--new-attempt-budget N`. Preflight rejects missing, negative, excessive, or next-pass-insufficient authorization before writes; only creating a new attempt directory consumes one. `--resume --new-attempt-budget 0` may validate, repair an index, or seal a marker, but cannot retry. Resume verifies the continuous index and bound receipts, skips complete evidence, seals a valid marker without inventing an outcome, and rejects active, unowned, partial, mismatched, or tampered state.

## Manual-review receipt

When required, the only manual authority input is `--manual-review-receipt <relative-path>` under `spec.artifacts.root`. It contains exact reviewer role, one hash-bound artifact per required evidence type, `approve|hold|reject`, and a non-empty signature attestation. The analyzer checks containment, hashes, role, evidence-type closure, and decision; it does not perform cryptographic signature verification.

## Cleanup and closeout

Stop task-owned processes, remove only task-owned temporary resources, capture final state and cleanup verification, retain immutable scored artifacts, redact secrets without destroying evidence structure, and prove the next run starts from the declared fixture. Audit exact index-selected receipts and artifacts when the frozen closeout requires it; do not replace aggregate review with an unbounded tree walk.
