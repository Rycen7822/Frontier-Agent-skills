"""Human-owned sentinel definition for Software Quality Workflows."""

DEFINITION = {
    "name": "Software Quality Workflows",
    "version": "10.0.0",
    "context_ceiling": 24576,
    "regression_origin": "session-card-artifact-accumulation",
    "verifier_source": "software_quality_workflows_verifier.py",
    "claims": [
        "risk-owned-development",
        "proportionate-validation",
        "lifecycle-cleanup",
    ],
    "grader_rules": [
        "Apply a case-specific rule only when task_evidence.case_id exactly equals its full named ID.",
        "For this Skill, the evidence owner answer names the smallest code, API, config, test, or component controlling the behavior.",
        "A requested behavior-focused check passes with behavioral evidence at the changed seam.",
        "For software-quality-workflows-single-specialist-risk, the complete result contains the requested specialist risk, concrete behavior owner, focused correction, and verification boundary.",
        "For software-quality-workflows-retire-dead-code, quality and process require the exact legacy function and obsolete-test deletion plus a zero-reference scan; a related post-deletion behavior test counts as proportionate validation.",
        "For software-quality-workflows-protected-no-state, the exact unapplied tmp-to-normalized_path rename plus one syntax check is the complete Direct result.",
        (
            "For software-quality-workflows-durable-resume-boundary, quality and "
            "process require durable state because work crosses contexts, exactly one "
            "controller fallback ledger because host and repository state are "
            "unavailable, a machine-only TASK_KEY used only to locate that ledger, a "
            "readable evidence index with coverage, producer, command/status, oracle "
            "authority, freshness, limitations, changed/preserved facts, required "
            "recheck and raw refs, retention of the named non-replayable artifact with "
            "one digest, and an empty invalidation set because the changed helper has "
            "zero consumers. The response reports this disposition directly while the "
            "TASK_KEY and digest remain machine-side."
        ),
        "For software-quality-workflows-single-specialist-risk-heldout, quality and process identify log_request as the behavior owner, classify the local single-owner task as Direct, state the durable-escalation conditions, and provide one credential-safe correction and behavior check.",
        "For software-quality-workflows-protected-no-state-heldout, the complete Direct result is the unapplied tmp-to-normalized_path rename plus one behavior check.",
    ],
    "process_evidence": [
        "the change map names `log_request` as the smallest controlling code owner for plaintext Authorization disclosure before editing",
        "the selected checks cover the changed seam and record the validation scope",
        "the obsolete path is removed and the reference scan reports no live owner",
    ],
    "fixtures": {
        "fixtures/work-boundary.md": "Scope: local-only, non-destructive, single-writer continuity across contexts. Repository and host state are unavailable for the owner seam, next action, and proof. A captured external response at `evidence/provider-output.json` is non-replayable and already has one canonical digest binding. The changed helper has zero named consumers.\n",
        "fixtures/src/logger.py": "def log_request(request, debug):\n    debug.write(request.headers['Authorization'])\n",
        "fixtures/src/upload.py": "def target(root, filename):\n    return root / filename\n",
        "fixtures/src/payment.py": "def charge(client, payment):\n    return client.retry(lambda: client.post('/charge', payment))\n",
        "fixtures/src/parser.py": "def parse(lines):\n    return [line for line in lines if line.strip()]\n",
        "fixtures/src/legacy.py": "def legacy_parse(text):\n    return text.split(',')\n\ndef parse_v2(text):\n    return [item.strip() for item in text.split(',')]\n",
        "fixtures/tests/test_legacy.py": "from src.legacy import legacy_parse\n\ndef test_legacy():\n    assert legacy_parse('a,b') == ['a', 'b']\n",
        "fixtures/src/path.py": "def normalize(input_path):\n    tmp = input_path.resolve()\n    return tmp\n",
    },
    "cases": [
        {
            "id": "durable-resume-boundary",
            "coverage": "durable-state",
            "task": "Read `fixtures/work-boundary.md`. Return the durable-state disposition, locator category, single minimal mechanism, readable evidence fields, raw-artifact retention, and consumer-local invalidation. Keep machine-side locator and digest values internal.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/work-boundary.md"],
            "semantic_oracle": [
                "cross-context work uses one controller fallback ledger with readable evidence and one binding for non-replayable raw bytes without global hash invalidation"
            ],
        },
        {
            "id": "single-specialist-risk",
            "coverage": "single-risk",
            "task": "Read `fixtures/src/logger.py`. Identify the single specialist risk, name its evidence owner, and give the focused correction and verification boundary.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/src/logger.py"],
            "semantic_oracle": [
                "authorization value must not be written to the debug log"
            ],
        },
        {
            "id": "two-independent-risks",
            "coverage": "dual-risk",
            "task": "Read `fixtures/src/upload.py` and `fixtures/src/payment.py`. Separate the two independent risks, their evidence owners, and their non-duplicated checks.",
            "protected": False,
            "turns": 2,
            "initial_files": ["fixtures/src/upload.py", "fixtures/src/payment.py"],
            "semantic_oracle": [
                "path containment and payment idempotency require separate owners"
            ],
        },
        {
            "id": "proportionate-validation",
            "coverage": "proportionate-validation",
            "task": "Read `fixtures/src/parser.py`. The only intended behavior is ignoring blank lines. Select proportional verification and state exactly what the evidence proves and does not prove.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/src/parser.py"],
            "semantic_oracle": [
                "focused parser examples do not prove unrelated API or network behavior"
            ],
        },
        {
            "id": "retire-dead-code",
            "coverage": "dead-code-removal",
            "task": "Read `fixtures/src/legacy.py` and `fixtures/tests/test_legacy.py`. `parse_v2()` replaces `legacy_parse()`. State the exact deletion and the reference proof required afterward.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/src/legacy.py",
                "fixtures/tests/test_legacy.py",
            ],
            "semantic_oracle": [
                "legacy function and its obsolete test are removed before a zero-reference scan"
            ],
        },
        {
            "id": "protected-no-state",
            "coverage": "protected",
            "task": "Read `fixtures/src/path.py`. Return an unapplied patch that renames only `tmp` to `normalized_path`, plus one focused check, as the complete Direct result.",
            "protected": True,
            "turns": 1,
            "initial_files": ["fixtures/src/path.py"],
            "semantic_oracle": [
                "two-line local rename preserves behavior as one Direct response"
            ],
        },
    ],
}
