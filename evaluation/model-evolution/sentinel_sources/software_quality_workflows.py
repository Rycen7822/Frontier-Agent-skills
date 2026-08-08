"""Human-owned sentinel definition for Software Quality Workflows."""

DEFINITION = {
    "name": "Software Quality Workflows",
    "version": "9.0.5",
    "context_ceiling": 24576,
    "regression_origin": "session-card-artifact-accumulation",
    "verifier_source": "software_quality_workflows_verifier.py",
    "claims": [
        "risk-owned-development",
        "proportionate-validation",
        "lifecycle-cleanup",
    ],
    "grader_rules": [
        "A case-specific rule applies only when task_evidence.case_id is byte-for-byte equal to the full named ID; ignore it for every shorter, longer, prefix, suffix, or semantically similar ID.",
        "For this Skill, an evidence owner is the smallest code, API, config, test, or component controlling the behavior; a team or role alone is insufficient.",
        "When the task requests a behavior-focused check, syntax-only compilation is insufficient.",
        "For software-quality-workflows-single-specialist-risk, judge only the requested specialist risk, concrete behavior owner, focused correction, and verification boundary; do not require a durable-state decision, escalation set, authority, or Git provenance.",
        "For software-quality-workflows-retire-dead-code, quality and process require the exact legacy function and obsolete-test deletion plus a zero-reference scan; a related post-deletion behavior test is proportionate validation, not unrelated workflow.",
        "For software-quality-workflows-protected-no-state, quality and process require the exact unapplied tmp-to-normalized_path rename plus one focused check; syntax-only compilation is sufficient because this public task does not request a behavior-focused check, and do not import the heldout case requirements.",
        "For software-quality-workflows-durable-resume-boundary, quality and process require durable state because work crosses contexts, exactly one controller fallback ledger because host and repository state are unavailable, the owner seam, next action, and proof in that ledger, and explicit exclusion of leases, daemons, event stores, and compatibility readers; do not require creating the ledger in this read-only task.",
        "For software-quality-workflows-single-specialist-risk-heldout, quality and process require log_request as the behavior owner, no durable state for this local single-owner task, the complete escalation set of cross-context work, destructive or external effects, staged migration or release, and multiple writers, plus one credential-safe correction and behavior check; authority and Git provenance remain excluded.",
        "For software-quality-workflows-protected-no-state-heldout, quality and process require the Direct route, the unapplied tmp-to-normalized_path rename, one behavior check, and exclusion of references, workflow or router state, cards, persistent state, JSON receipts, and ledgers.",
    ],
    "process_evidence": [
        "the change map names `log_request` as the smallest controlling code owner for plaintext Authorization disclosure before editing",
        "the selected checks cover the changed seam and record the validation scope",
        "the obsolete path is removed and the reference scan reports no live owner",
    ],
    "fixtures": {
        "fixtures/work-boundary.md": "The work must resume in a different context. There is one writer. Repository and host state cannot persist the owner seam, next action, or proof. The work is local-only, non-destructive, and is not a migration or release.\n",
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
            "task": "Read `fixtures/work-boundary.md`. Apply the bound durable escalation contract. State whether durable state is required, name the exact minimal mechanism and its required contents, and exclude every prohibited mechanism. Do not create files.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/work-boundary.md"],
            "semantic_oracle": [
                "cross-context work with no host or repository state uses one controller fallback ledger and no distributed lifecycle machinery"
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
            "task": "Read `fixtures/src/path.py`. Provide patch text that renames only `tmp` to `normalized_path`, plus one focused check. Do not claim application, create cards, call reviewers, or persist workflow state.",
            "protected": True,
            "turns": 1,
            "initial_files": ["fixtures/src/path.py"],
            "semantic_oracle": [
                "two-line local rename preserves behavior and creates no workflow state"
            ],
        },
    ],
}
