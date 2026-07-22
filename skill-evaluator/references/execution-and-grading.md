# Execution and Grading

This file owns run isolation, run index v1, receipt v3, artifact/provenance verification, routing/usage/context capture, grader transport/semantics, and apparatus failure classification.

## Preflight and isolation

Before execution:

1. audit the complete package and validate the frozen spec/cases;
2. prove the harness can disable and naturally load the candidate without cross-arm leakage;
3. freeze agent/model/harness, catalogs, tools, permissions, environment, fixture, graders, reset, retry, and artifact root;
4. keep evaluator instructions, hidden expectations, and grader material outside the tested executor;
5. test reset and cleanup before the first scored run.

Use one fresh or deterministically restored workspace per `case × variant × repeat`. Counterbalance arm order when caches, time, services, or quotas can drift. Never flow generated files, conversation state, loaded Skills, or service state into another arm unless persistent state is the declared object.

Capture observable events and artifacts, never private chain-of-thought: retrieval/selection/load/application, tool and command status, permissions/network, retries/recovery, termination, stdout/stderr/exit, file/state diffs, verifier outputs, usage, and cleanup.

## Run index v1

The analyzer accepts one identity/location record per JSONL line:

```json
{
  "run_schema_version": 1,
  "run_id": "case-001:candidate_natural:1",
  "case_id": "case-001",
  "variant": "candidate_natural",
  "repeat": 1,
  "artifact_dir": "runs/case-001/candidate_natural/1",
  "receipt": {"path": "receipt.json", "sha256": "sha256:<64 lowercase hex>"}
}
```

The index contains no pass, score, routing, usage, grader, or provenance claim. Paths resolve in this order: spec directory → `spec.artifacts.root` → row `artifact_dir` → receipt/artifact path.

## Default evidence traversal

Raw scored receipts and their artifacts stay immutable for the frozen retention period, but they are not the model's default reading surface. Read analyzer summary → failure index → the spec-limited representative receipts. Open raw artifacts only through one named receipt for a named failure, grader disagreement, or integrity audit. Do not walk the artifact tree first, create per-step worknotes or per-notice JSON, or copy receipt data into parallel model-authored files. A short early failure remains a failed outcome and cannot establish an efficiency advantage.

## Receipt v3

One receipt owns all captured evidence:

```json
{
  "schema_version": 3,
  "receipt_hash": "sha256:<64 lowercase hex>",
  "run": {"run_id": "...", "case_id": "...", "variant": "...", "repeat": 1, "valid": true, "error_type": null, "invalid_reason": null, "provenance": {}},
  "artifacts": [{"path": "ordered-trace.jsonl", "sha256": "sha256:<64 hex>", "encoding": "utf-8"}],
  "trace": {"artifact": "ordered-trace.jsonl", "sha256": "sha256:<64 hex>", "event_count": 1, "context_capture": {"status": "captured", "source": "replay_manifest"}},
  "routing": {},
  "boundaries": {},
  "bytes": {},
  "counts": {},
  "usage": {},
  "context_usage": {},
  "grader_outputs": []
}
```

The analyzer requires exact shapes. It normalizes POSIX-relative paths, rejects absolute/backslash/parent traversal, proves lexical and symlink-resolved containment, recomputes bytes/hashes, and rejects duplicate normalized or resolved artifacts. Routing, usage, context, grader evidence, and invocations must reference the allowlist's exact canonical spellings.

Provenance binds candidate revision/source/plugin identities plus spec, case, case-contract, fixture-set, selected-grader-set, grader-schedule, environment, package, catalog, and treatment hashes. Candidate package inventory, suite assets, grader declarations, verifier bytes, model prompt, and model schema are recomputed locally where the spec provides their bytes. Catalog, treatment, controller, private-contract, and grader-schedule claims remain hash-bound external attestations.

`receipt_hash` removes only itself, then hashes UTF-8 JSON with sorted keys, compact separators, `allow_nan=false`, and a `sha256:` prefix. No older receipt is accepted or silently upgraded.

## Routing and usage

Retrieval, selection, body load, incorporation, and application are five independent stages. Each stage is exactly `{status,value,evidence}`: `observed` requires its own non-reused locator, while `not_evaluable` requires `value=null` and no evidence. No stage may be inferred from a preceding stage. `resources_loaded` is the unique reference source set. Eligibility is derived from case and variant mode, never supplied as a denominator switch.

The ordered trace assigns every received host event a contiguous one-based `event_seq`. After each completed event that may mutate the workspace, the controller records a compact typed manifest delta in that trace. The analyzer derives the first successful source write whose case-declared delta remains visible in the final manifest and the first reply/file deliverable; it rejects declared boundary values that disagree with event order. Whether either boundary may be null belongs to the frozen case contract.

Usage records non-negative input/output tokens, latency, retries, and evidence. Counts separately report task tools, prewrite task tools, host/model body loads, references, skill-load tools, skill-protocol tools, and workflow artifacts. Bytes separately report unique/repeated static context, protocol/failed output, and prewrite tool output. Turn-level tokens are never fabricated into component or tool-output token counts.

Evidence locators are one-based inclusive `{start_line,end_line}` spans into allowlisted UTF-8 artifacts. The analyzer proves that cited bytes/lines exist; the selected grader owns their meaning.

## Context receipt

`context_usage.measurement_source` is exactly one of:

- `host_receipt`: each component has non-negative integer tokens; bytes are still recomputed;
- `replay_manifest`: each component has `tokens=null`; only captured bytes are claimed.

`trace.context_capture` independently records `captured|missing` and `host_trace|replay_manifest`. `captured` with zero components is valid proof of zero target-Skill context; `missing` invalidates attribution. This prevents an empty baseline capture from being confused with absent evidence.

Each component remains exactly `{kind,source_path,artifact,tokens}`. `kind` is `metadata`, `body`, `reference`, `protocol_output`, or `failed_command_output`; artifact names one unique UTF-8 allowlisted file. Static source paths are canonical plugin-relative POSIX paths. Dynamic paths are redacted `protocol:<tool_id>:<ordinal>` or `failed-command:<tool_family>:<ordinal>` identifiers, never command arguments or local paths. Body presence must agree with body loading, and the unique reference source set must equal `routing.resources_loaded`.

Component order is model-visible event order. Failure, timeout, and partial output use `failed_command_output`; other successful helper output uses `protocol_output` unless it exactly equals a bound static file or deterministic continuous byte slice. The controller captures every skill-attributed visible event exactly once and distinguishes host activation from model-initiated reads. `force_loaded` requires exactly one host body injection; zero or multiple injections are apparatus-invalid. A later model reread stays evidence-complete and increments repeated load cost. The analyzer hashes artifact bytes, derives the four context byte projections, and rejects any run whose components, counts, routing, or bytes do not conserve. All machine projections stay in one receipt and one ordered trace; event/check sidecars are forbidden.

## Deterministic grader receipt

Every case-selected deterministic grader appears once as `{grader_id,invocation}`. The invocation binds exactly:

- the digest of the full grader declaration and verifier bytes;
- sorted selected check IDs;
- the spec-relative artifact root;
- the complete frozen host/fixture input artifact set and hashes;
- one allowlisted raw stdout JSON artifact, a distinct raw stderr artifact, and integer exit code.

All deterministic stdout/stderr paths are removed globally before computing the input set. Inputs cannot include any grader output or the receipt. The analyzer does not import or execute the verifier; it verifies the frozen invocation, parses the single stdout, and requires exit-code pass semantics to agree with `overall_pass`.

Model rubric output appears once as `{grader_id,batch}`. The batch reference binds one item ID and the raw hash/line of the study-level `grader-batches.jsonl`; batches contain one to four distinct case IDs and no arm labels. Deterministic output cannot be supplied inline. Both paths feed the same semantic validator.

## Grader semantic owner

The JSON Schema owns transport shape only. The analyzer also enforces:

- exactly the case-selected check IDs, each once;
- allowlisted evidence and valid line spans;
- structured missing evidence mapped to selected checks;
- required-only `overall_pass` (optional failures do not change it);
- either all weights or no weights, and `floor(raw_score + 0.5)` recomputation;
- apparatus failure shape: no checks, zero score, false overall, missing item, and non-empty reason.

Every requirement declares one `owner` matching its grader type, and one grader/check binding may occur only once. Commands, exit codes, test counts, file deltas, boundaries, load counts/bytes, protocol output, and source/plugin identity belong only to deterministic evidence. Model rubrics own semantic qualities such as executability, risk coverage, and boundary clarity; they do not rescore deterministic facts. A model/deterministic disagreement is reported without changing the deterministic result. Human/domain review is a separate authority receipt, and no weaker grader erases a deterministic or safety failure.

## Process evidence levels

- Skill retrieval proves retrieval only; entry reading proves body loading only; a CLI or card reference proves an attempt only.
- A behavioral process check passes only when bound evidence proves exit 0, a successfully parsed receipt, the expected state transition, and every required owner, delivery, anchor, or cleanup fact. Final prose and task-code success cannot replace these facts.
- A pure routing case may use the exact owner load set as its final process oracle because no workflow transition is required.

## Validity and failure ownership

`valid=false` is reserved for evaluation apparatus failure: provider/controller unavailable before attributable execution, broken fixture/capture, corrupt receipt, or grader failure. It requires `error_type="evaluation_apparatus"` and an invalid reason.

Treatment-attributable refusal, timeout, empty output, tool/dependency error, nonzero task process, unsafe action, or malformed artifact remains `valid=true` when the host captured complete evidence. Normal grader requirements make it an outcome/process/safety failure in the denominator. Do not convert a negative treatment result into inconclusive evidence.

Preserve original attempts. Retry only predeclared apparatus failures; never retry until success and discard failures. Missing/tampered receipt evidence is incomplete/invalid, not a candidate hard failure.

## Manual-review receipt

When required, the only manual authority input is `--manual-review-receipt <relative-path>` under `spec.artifacts.root`. It contains exact reviewer role, one hash-bound artifact per required evidence type, `approve|hold|reject`, and a non-empty signature attestation. The analyzer checks containment, hashes, role, evidence-type closure, and decision; it does not perform cryptographic signature verification.

## Cleanup and closeout

Stop task-owned processes, remove only task-owned temporary resources, capture final state and cleanup verification, retain immutable scored artifacts, redact secrets without destroying evidence structure, and prove the next run starts from the declared fixture. Audit exact index-selected receipts and artifacts when the frozen closeout requires it; do not replace aggregate review with an unbounded tree walk.
