"""Human-owned sentinel definition for Software Quality Workflows."""

DEFINITION = {
    "name": "Software Quality Workflows",
    "version": "9.0.0",
    "context_ceiling": 24576,
    "regression_origin": "session-card-artifact-accumulation",
    "verifier_source": "software_quality_workflows_verifier.py",
    "claims": [
        "risk-owned-development",
        "proportionate-validation",
        "lifecycle-cleanup",
    ],
    "grader_rules": [
        "For this Skill, an evidence owner is the smallest code, API, config, test, or component controlling the behavior; a team or role alone is insufficient.",
        "When the task requests a behavior-focused check, syntax-only compilation is insufficient.",
    ],
    "process_evidence": [
        "the change map names the behavior risk and its evidence owner before editing",
        "the selected checks cover the changed seam and record the validation scope",
        "the obsolete path is removed and the reference scan reports no live owner",
    ],
    "fixtures": {
        "fixtures/src/even.py": "def is_even(n):\n    return n % 2 == 1\n",
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
            "id": "direct-routine-change",
            "coverage": "direct",
            "task": "Read `fixtures/src/even.py`. Provide the minimal corrected function and the smallest relevant verification.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/src/even.py"],
            "semantic_oracle": ["even predicate compares modulo result with zero"],
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
