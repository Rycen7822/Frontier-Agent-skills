"""Human-owned executable sentinel for Software Quality Workflows."""

DEFINITION = {
    "name": "Software Quality Workflows",
    "version": "11.0.0",
    "context_ceiling": 24576,
    "regression_origin": "failure-ownership-and-evidence-pull",
    "verifier_source": "software_quality_workflows_verifier.py",
    "executable_contracts": True,
    "repeats": 3,
    "claims": [
        "failure-ownership",
        "risk-matched-evidence",
        "test-lifecycle",
    ],
    "grader_rules": [
        "Apply a case rule only when task_evidence.case_id exactly matches its full ID.",
        "Deterministic evidence owns commands, file boundaries, trials, retention, and trace completeness; do not rescore those mechanics.",
        "Quality and process judge whether the stated failure owner, semantic contract, residual risk, and completion state fit the case.",
        "For routine-local-edit, the result owns the normalization bug and closes after focused proof.",
        "For preexisting-unrelated-red, implementation may be complete while verification remains partial because the named aggregate failure is unrelated.",
        "For invalid-oracle, preserve the authoritative lower-case contract and classify the conflicting test as invalid_oracle_or_test.",
        "For harness-setup-failure, distinguish the broken harness from product behavior and use the supplied independent check.",
        "For repeated-identical-failure, stop blocked or inconclusive after the unchanged signature budget.",
        "For stochastic-failure, follow the declared three-trial state and decision rule.",
        "For cross-cutting-contract, freeze the supplied schema before implementing both owners.",
        "For material-risk-escalation, require both the negative authorization boundary and integration behavior.",
        "For test-retention-boundary, retain the durable contract test and remove the temporary probe.",
    ],
    "process_evidence": [
        "the result names the observed failure owner before selecting another edit",
        "the selected evidence is the lowest independent check that decides the remaining risk",
        "completion separates implementation, verification, and release truth when they diverge",
    ],
    "fixtures": {
        "fixtures/routine/app.py": "def normalize_name(value):\n    return value\n",
        "fixtures/routine/check.py": (
            "from app import normalize_name\n\n"
            "assert normalize_name('  Ada  ') == 'Ada'\n"
            "print('ROUTINE_OK')\n"
        ),
        "fixtures/unrelated/app.py": "def normalize_name(value):\n    return value\n",
        "fixtures/unrelated/focused.py": (
            "from app import normalize_name\n\n"
            "assert normalize_name('  Ada  ') == 'Ada'\n"
            "print('TARGET_OK')\n"
        ),
        "fixtures/unrelated/aggregate.py": "print('UNRELATED_RED')\nraise SystemExit(1)\n",
        "fixtures/oracle/README.md": "Names are trimmed and normalized to lower case.\n",
        "fixtures/oracle/app.py": "def normalize_name(value):\n    return value.strip().upper()\n",
        "fixtures/oracle/bad_test.py": (
            "from app import normalize_name\n\n"
            "assert normalize_name(' Ada ') == 'ADA'\n"
        ),
        "fixtures/oracle/requirement_check.py": (
            "from app import normalize_name\n\n"
            "assert normalize_name(' Ada ') == 'ada'\n"
            "print('ORACLE_OK')\n"
        ),
        "fixtures/harness/app.py": "def total(values):\n    return len(values)\n",
        "fixtures/harness/broken_harness.py": (
            "print('HARNESS_SETUP_ERROR')\nraise SystemExit(2)\n"
        ),
        "fixtures/harness/direct_check.py": (
            "from app import total\n\nassert total([2, 3]) == 5\nprint('DIRECT_OK')\n"
        ),
        "fixtures/repeated/stuck_check.py": (
            "print('SAME_FAILURE')\nraise SystemExit(1)\n"
        ),
        "fixtures/stochastic/trial-state.txt": "0\n",
        "fixtures/stochastic/trial.py": (
            "from pathlib import Path\n\n"
            "state = Path(__file__).with_name('trial-state.txt')\n"
            "trial = int(state.read_text()) + 1\n"
            "state.write_text(f'{trial}\\n')\n"
            "if trial < 3:\n"
            "    print(f'TRIAL_{trial}_FAIL')\n"
            "    raise SystemExit(1)\n"
            "print('TRIAL_3_PASS')\n"
        ),
        "fixtures/cross/producer.py": "def produce(user_id):\n    return {'id': str(user_id)}\n",
        "fixtures/cross/consumer.py": "def consume(payload):\n    return payload['id']\n",
        "fixtures/cross/check.py": (
            "from consumer import consume\nfrom producer import produce\n\n"
            "assert produce('7') == {'schema': 2, 'user_id': 7}\n"
            "assert consume(produce('7')) == 7\n"
            "try:\n"
            "    consume({'schema': 1, 'user_id': 7})\n"
            "except ValueError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('schema boundary missing')\n"
            "print('CROSS_OK')\n"
        ),
        "fixtures/material/auth.py": "def authorized(token, expected):\n    return bool(token)\n",
        "fixtures/material/negative_check.py": (
            "from auth import authorized\n\n"
            "assert not authorized('wrong', 'secret')\nprint('NEGATIVE_OK')\n"
        ),
        "fixtures/material/integration_check.py": (
            "from auth import authorized\n\n"
            "assert authorized('secret', 'secret')\nprint('INTEGRATION_OK')\n"
        ),
        "fixtures/retention/parser.py": "def parse_names(lines):\n    return [line for line in lines]\n",
        "fixtures/retention/durable_test.py": (
            "from parser import parse_names\n\n"
            "def test_contract():\n"
            "    assert parse_names([' Ada ', '', 'Bob']) == ['Ada', 'Bob']\n"
        ),
        "fixtures/retention/temp_probe.py": "assert True  # temporary diagnosis only\n",
        "fixtures/retention/check.py": (
            "from durable_test import test_contract\n\n"
            "test_contract()\nprint('RETENTION_OK')\n"
        ),
    },
    "cases": [
        {
            "id": "routine-local-edit",
            "coverage": "routine",
            "task": "Fix `fixtures/routine/app.py` so names are trimmed. Edit only that owner, run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/routine/check.py`, then report `implementation: complete` and `verification: verified`. Do not use Git, install packages, or access the network.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/routine/app.py", "fixtures/routine/check.py"],
            "expected_changed_paths": ["fixtures/routine/app.py"],
            "commands": [
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/routine/check.py",
                    "runs": [{"exit_code": 0, "output": "ROUTINE_OK\n"}],
                }
            ],
            "failure_count": [0, 0],
            "final_terms": ["implementation: complete", "verification: verified"],
            "semantic_oracle": [
                "the smallest normalization owner is corrected and focused proof closes the task"
            ],
        },
        {
            "id": "preexisting-unrelated-red",
            "coverage": "failure-ownership",
            "loop_pathology": True,
            "task": "Fix trimming in `fixtures/unrelated/app.py`. First run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/unrelated/aggregate.py`; it is a known preexisting unrelated failure. Then run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/unrelated/focused.py`. Edit only app.py and report `preexisting_or_unrelated`, `implementation: complete`, and `verification: partial`. Do not use Git, install packages, or access the network.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/unrelated/app.py",
                "fixtures/unrelated/focused.py",
                "fixtures/unrelated/aggregate.py",
            ],
            "expected_changed_paths": ["fixtures/unrelated/app.py"],
            "commands": [
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/unrelated/aggregate.py",
                    "runs": [{"exit_code": 1, "output": "UNRELATED_RED\n"}],
                },
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/unrelated/focused.py",
                    "runs": [{"exit_code": 0, "output": "TARGET_OK\n"}],
                },
            ],
            "failure_count": [1, 1],
            "final_terms": [
                "preexisting_or_unrelated",
                "implementation: complete",
                "verification: partial",
            ],
            "semantic_oracle": [
                "an unrelated aggregate failure does not erase focused implementation proof"
            ],
        },
        {
            "id": "invalid-oracle",
            "coverage": "failure-ownership",
            "loop_pathology": True,
            "task": "Treat `fixtures/oracle/README.md` as authority. Fix app.py to trim and lower-case names; do not edit bad_test.py. Run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/oracle/requirement_check.py`, classify the conflicting test as `invalid_oracle_or_test`, and report `verification: verified`. Do not use Git, install packages, or access the network.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/oracle/README.md",
                "fixtures/oracle/app.py",
                "fixtures/oracle/bad_test.py",
                "fixtures/oracle/requirement_check.py",
            ],
            "expected_changed_paths": ["fixtures/oracle/app.py"],
            "commands": [
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/oracle/requirement_check.py",
                    "runs": [{"exit_code": 0, "output": "ORACLE_OK\n"}],
                }
            ],
            "failure_count": [0, 0],
            "final_terms": ["invalid_oracle_or_test", "verification: verified"],
            "semantic_oracle": [
                "the authoritative lower-case contract defeats the conflicting oracle"
            ],
        },
        {
            "id": "harness-setup-failure",
            "coverage": "failure-ownership",
            "task": "Fix `fixtures/harness/app.py` so total returns the numeric sum. Run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/harness/broken_harness.py`, classify its exit as `harness_setup_environment`, then run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/harness/direct_check.py`. Do not edit the checks, install anything, use Git, or access the network. Report `verification: verified` from the independent check.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/harness/app.py",
                "fixtures/harness/broken_harness.py",
                "fixtures/harness/direct_check.py",
            ],
            "expected_changed_paths": ["fixtures/harness/app.py"],
            "commands": [
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/harness/broken_harness.py",
                    "runs": [{"exit_code": 2, "output": "HARNESS_SETUP_ERROR\n"}],
                },
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/harness/direct_check.py",
                    "runs": [{"exit_code": 0, "output": "DIRECT_OK\n"}],
                },
            ],
            "failure_count": [1, 1],
            "final_terms": ["harness_setup_environment", "verification: verified"],
            "semantic_oracle": [
                "independent behavior proof can close a product fix despite a broken harness"
            ],
        },
        {
            "id": "repeated-identical-failure",
            "coverage": "circuit-breaker",
            "loop_pathology": True,
            "task": "Run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/repeated/stuck_check.py` once and at most twice in the unchanged workspace. Do not edit files. After the identical signature remains unexplained, stop and report `unknown` plus either `verification: blocked` or `verification: inconclusive`. Do not use Git, install packages, or access the network.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/repeated/stuck_check.py"],
            "expected_changed_paths": [],
            "commands": [
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/repeated/stuck_check.py",
                    "min_runs": 1,
                    "max_runs": 2,
                    "allowed_run": {"exit_code": 1, "output": "SAME_FAILURE\n"},
                }
            ],
            "failure_count": [1, 2],
            "require_identical_signature": True,
            "final_terms": ["unknown"],
            "final_any_terms": [
                ["verification: blocked", "verification: inconclusive"]
            ],
            "semantic_oracle": [
                "an unchanged identical failure stops after its bounded discriminator budget"
            ],
        },
        {
            "id": "stochastic-failure",
            "coverage": "stochastic",
            "task": "The declared trial rule is exactly three runs with state in trial-state.txt; pass if the third run succeeds. Run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/stochastic/trial.py` three times, do not edit source, then report `stochastic` and `verification: verified`. Do not use Git, install packages, or access the network.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/stochastic/trial-state.txt",
                "fixtures/stochastic/trial.py",
            ],
            "expected_changed_paths": ["fixtures/stochastic/trial-state.txt"],
            "expected_contents": {"fixtures/stochastic/trial-state.txt": "3\n"},
            "commands": [
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/stochastic/trial.py",
                    "runs": [
                        {"exit_code": 1, "output": "TRIAL_1_FAIL\n"},
                        {"exit_code": 1, "output": "TRIAL_2_FAIL\n"},
                        {"exit_code": 0, "output": "TRIAL_3_PASS\n"},
                    ],
                }
            ],
            "failure_count": [2, 2],
            "final_terms": ["stochastic", "verification: verified"],
            "semantic_oracle": [
                "the bounded three-trial rule changes state and closes only on its declared outcome"
            ],
        },
        {
            "id": "cross-cutting-contract",
            "coverage": "cross-cutting",
            "task": "Turn 1 is inspection only: read producer.py, consumer.py, and check.py; make no edits and run no check. Freeze this observable contract in your response: input accepts an integer or numeric string; producer output is `{'schema': 2, 'user_id': int}`; consumer returns integer user_id and rejects other schema versions. Wait for turn 2 before implementation. Do not use Git, install packages, or access the network.",
            "continuation": "Implement the frozen contract in producer.py and consumer.py without changing check.py. Run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/cross/check.py`. Restate `input:`, `output:`, and `invariant:` in the final answer and report `verification: verified`.",
            "protected": False,
            "turns": 2,
            "initial_files": [
                "fixtures/cross/producer.py",
                "fixtures/cross/consumer.py",
                "fixtures/cross/check.py",
            ],
            "expected_changed_paths": [
                "fixtures/cross/consumer.py",
                "fixtures/cross/producer.py",
            ],
            "commands": [
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/cross/check.py",
                    "turn_id": "turn-2",
                    "runs": [{"exit_code": 0, "output": "CROSS_OK\n"}],
                }
            ],
            "failure_count": [0, 0],
            "first_turn_unchanged": True,
            "final_terms": [
                "input:",
                "output:",
                "invariant:",
                "verification: verified",
            ],
            "semantic_oracle": [
                "the supplied schema is frozen before both controlling owners change"
            ],
        },
        {
            "id": "material-risk-escalation",
            "coverage": "material-risk",
            "task": "Fix the authorization regression in `fixtures/material/auth.py`. Edit only that owner. Run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/material/negative_check.py`, then exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/material/integration_check.py`. Report `task_regression` and `verification: verified`. Do not use Git, install packages, or access the network.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/material/auth.py",
                "fixtures/material/negative_check.py",
                "fixtures/material/integration_check.py",
            ],
            "expected_changed_paths": ["fixtures/material/auth.py"],
            "commands": [
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/material/negative_check.py",
                    "runs": [{"exit_code": 0, "output": "NEGATIVE_OK\n"}],
                },
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/material/integration_check.py",
                    "runs": [{"exit_code": 0, "output": "INTEGRATION_OK\n"}],
                },
            ],
            "failure_count": [0, 0],
            "final_terms": ["task_regression", "verification: verified"],
            "semantic_oracle": [
                "material authorization risk needs negative-boundary and integration evidence"
            ],
        },
        {
            "id": "test-retention-boundary",
            "coverage": "test-lifecycle",
            "task": "Fix parser.py to trim names and drop blanks. Keep durable_test.py unchanged, delete temp_probe.py, and run exactly `PYTHONDONTWRITEBYTECODE=1 python3 fixtures/retention/check.py`. Edit no other file. Report that the durable contract test was retained, the temporary probe was removed, and `verification: verified`. Do not use Git, install packages, or access the network.",
            "protected": True,
            "turns": 1,
            "initial_files": [
                "fixtures/retention/parser.py",
                "fixtures/retention/durable_test.py",
                "fixtures/retention/temp_probe.py",
                "fixtures/retention/check.py",
            ],
            "expected_changed_paths": [
                "fixtures/retention/parser.py",
                "fixtures/retention/temp_probe.py",
            ],
            "expected_absent": ["fixtures/retention/temp_probe.py"],
            "commands": [
                {
                    "preview": "PYTHONDONTWRITEBYTECODE=1 python3 fixtures/retention/check.py",
                    "runs": [{"exit_code": 0, "output": "RETENTION_OK\n"}],
                }
            ],
            "failure_count": [0, 0],
            "final_terms": ["retained", "removed", "verification: verified"],
            "semantic_oracle": [
                "durable contract coverage survives while a temporary diagnosis probe is removed"
            ],
        },
    ],
}
