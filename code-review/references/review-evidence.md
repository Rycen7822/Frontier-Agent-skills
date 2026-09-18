# Review evidence

## When this helper applies

Use the [helper](../scripts/review_support.py) for batched scope accounting, cross-context source capture, or a consumer that requires the [review record](../schemas/review-record.schema.json). An ordinary review can use the host's native tools and return findings directly; it does not require a packet or JSON record.

The helper requires a POSIX environment, Python 3.11 or later, Git 2.41 or later, and the jsonschema package. It does not install dependencies, call a model, fetch Git objects, or publish results. A partial clone is rejected before object access.

## Capture scope

Set REVIEW_SKILL_DIR to the directory containing this skill's SKILL.md, REPO to the target repository, and WORK to a caller-owned temporary directory outside that repository. Each packet output below must not exist yet. Replace COMMIT, BASE, and HEAD with the requested revisions; do not infer an unrelated comparison base.

Commit mode compares a commit with its first parent. Range mode uses the unique merge base of the requested base and head. Workspace mode retains staged, unstaged, and untracked layers separately. Snapshot mode reads a commit; the reserved revision WORKTREE selects the current working-tree snapshot.

    python3 "$REVIEW_SKILL_DIR/scripts/review_support.py" scope --repo "$REPO" --mode commit --commit "$COMMIT" --path src --output "$WORK/packet-commit"
    python3 "$REVIEW_SKILL_DIR/scripts/review_support.py" scope --repo "$REPO" --mode range --base "$BASE" --head "$HEAD" --path . --context-path config/runtime.json --output "$WORK/packet-range"
    python3 "$REVIEW_SKILL_DIR/scripts/review_support.py" scope --repo "$REPO" --mode workspace --path . --output "$WORK/packet-workspace"
    python3 "$REVIEW_SKILL_DIR/scripts/review_support.py" scope --repo "$REPO" --mode snapshot --revision HEAD --path code-review --output "$WORK/packet-snapshot"

Paths are literal repository-relative paths. Context paths add source evidence, not review items. Renames are represented as deletion and addition. Markdown, tests, configuration, and generated files are not excluded by category. Git-ignored untracked files are outside this helper's scope; disclose that limit rather than claiming they were captured.

Use the returned scope digest and item/source identifiers for the record. Read captured source objects for evidence tied to that packet. New context requires a new packet; do not edit a completed scope.json or invent source identifiers. Oversized, binary, or unavailable content stays visible as a limitation.

## Check a record

Use the record schema only when the result has a machine consumer. The record contains coverage declarations, findings, material unresolved concerns, verification observations, and limitations. Coverage names scope item IDs, not just paths. Evidence names captured source IDs, including the correct old-side source for deleted code. Include a verbatim snippet and known coordinates; unknown coordinates are null.

    python3 "$REVIEW_SKILL_DIR/scripts/review_support.py" check --repo "$REPO" --packet "$WORK/packet-workspace" --record "$WORK/review-record.json" --output "$WORK/check-report.json"

Exit 2 reports invalid input, missing dependencies, conflicting output, or failed integrity checks. Exit 4 preserves a valid bounded result with partial coverage, changed or incomplete inputs, unresolved locations, material concerns, or failed verification. Exit 0 means the performed mechanical checks were satisfied; it is not a favorable code verdict. A critical finding does not itself make its record structurally invalid. A not-run test does not require the helper to execute it.

The checker does not rewrite the record. Ambiguous snippets remain ambiguous. A relocation candidate is a location to inspect, not an automatic edit or a reason to discard the finding. Use a new output file after correcting an invalid record. Never delete an item merely to obtain complete coverage.

## Limits

Coverage is a producer declaration, not proof that a model understood every file. Working-tree capture uses bounded double observation, not an atomic whole-repository snapshot. Freshness concerns only captured sources and the selected range; it does not prove that every relevant consumer was found.

The helper does not execute verification text, validate a defect's business meaning, issue merge permission, or replace the host's command evidence. Keep important unverified facts explicit. Unreadable inputs must not become zero findings or fabricated success. Preserve the user's work and existing sessions.
