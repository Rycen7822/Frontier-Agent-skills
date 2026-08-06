"""Human-owned sentinel definition for Software Quality Workflows."""

DEFINITION = {
    "name": "Software Quality Workflows",
    "version": "9.0.0",
    "context_ceiling": 24576,
    "regression_origin": "session-card-artifact-accumulation",
    "claims": [
        "risk-owned-development",
        "proportionate-validation",
        "lifecycle-cleanup",
    ],
    "process_evidence": [
        "the change map names the behavior risk and its evidence owner before editing",
        "the selected checks cover the changed seam and record the validation scope",
        "the obsolete path is removed and the reference scan reports no live owner",
    ],
    "cases": [
        (
            "direct-routine-change",
            "direct",
            "A Python function `def is_even(n): return n % 2 == 1` has the comparison reversed. Provide the minimal corrected function and the smallest relevant verification.",
            False,
            1,
        ),
        (
            "single-specialist-risk",
            "single-risk",
            "A request logger writes the full Authorization header to debug.log. Identify the single specialist risk, name its evidence owner, and give the focused correction and verification boundary.",
            False,
            1,
        ),
        (
            "two-independent-risks",
            "dual-risk",
            "A patch joins an untrusted filename to an upload directory and also retries a non-idempotent payment call. Separate the two independent risks, their evidence owners, and their non-duplicated checks.",
            False,
            2,
        ),
        (
            "proportionate-validation",
            "proportionate-validation",
            "A line parser now ignores blank lines; no API, storage, or network surface changed. Select proportional verification and state exactly what the evidence does and does not prove.",
            False,
            1,
        ),
        (
            "retire-dead-code",
            "dead-code-removal",
            "`legacy_parse()` is replaced by `parse_v2()`, and a repository search shows its only remaining references are its definition and one obsolete test. Give the exact deletion and the reference proof required afterward.",
            False,
            1,
        ),
        (
            "protected-no-state",
            "protected",
            "In `src/path.py`, rename the exact lines `tmp = input_path.resolve()` and `return tmp` to use `normalized_path`. Provide the two-line local patch and one focused check. Do not claim it was applied, create cards, call reviewers, or persist workflow state.",
            True,
            1,
        ),
    ],
}
