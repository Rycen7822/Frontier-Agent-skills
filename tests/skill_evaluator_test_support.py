from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import jsonschema
except ImportError:  # Optional: only the schema conformance test needs it.
    jsonschema = None

ROOT = Path(__file__).resolve().parents[1] / 'skill-evaluator'
READY_HOLDOUT_CONTROL = {
    'payload_separated': True,
    'manifest_file': 'holdout-manifest.json',
    'payload_file': 'holdout-cases.jsonl',
    'manifest_hash': 'sha256:' + '1' * 64,
    'payload_hash': 'sha256:' + '2' * 64,
    'custodian': 'independent-evaluation-owner',
    'exposure_status': 'sealed',
    'last_exposure_at': None,
    'refresh_required': False,
}

HASHES = {
    name: 'sha256:' + digit * 64
    for name, digit in {
        'candidate': '1', 'package': '2', 'catalog': '3', 'treatment': '4',
        'system': '5', 'tools': '6', 'skills': '7', 'source': '8',
        'plugin': '9', 'cases': 'a', 'contracts': 'b', 'fixtures': 'c', 'batch': 'd',
    }.items()
}
RECEIPT_PACKAGE_SKILL = (
    '---\nname: target-skill\ndescription: Test receipt package.\n---\n\n# Target Skill\n'
)
RECEIPT_PACKAGE_HASH = 'sha256:4a8516b5da3eb512d500b2557953072e780d9b43e7b20f4a3909e6a9456a8c78'


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode('utf-8')
    return 'sha256:' + hashlib.sha256(payload).hexdigest()


def treatment_contract_hash(variants: list[dict]) -> str:
    return canonical_hash([
        {
            field: variant[field]
            for field in (
                'id', 'role', 'mode', 'package_hash', 'catalog_hash',
                'treatment_hash',
            )
        }
        for variant in sorted(variants, key=lambda item: item['id'])
    ])


def receipt_local_treatment_hash(case: dict, variant: dict) -> str:
    mode = variant['mode']
    return canonical_hash({
        'variant_id': variant['id'],
        'role': variant['role'],
        'mode': mode,
        'package_hash': variant['package_hash'],
        'catalog_hash': variant['catalog_hash'],
        'variant_treatment_hash': variant['treatment_hash'],
        'case_content_hash': canonical_hash(case),
        'task_text_content_hash': (
            'sha256:' + hashlib.sha256(case['prompt'].encode('utf-8')).hexdigest()
        ),
        'input_shape': {
            'native_skill_input_count': int(mode == 'force_loaded'),
            'task_text_input_count': 1,
            'manual_skill_body_copy_count': 0,
            'catalog_registered': mode != 'skill_disabled',
        },
    })


def bind_suite_hashes(spec: dict, rows: list[dict]) -> None:
    spec['suite'].update({
        'cases_content_hash': canonical_hash(rows),
        'case_contracts_content_hash': canonical_hash([
            {'case_id': row['case_id'], 'requirements': row['requirements']} for row in rows
        ]),
        'fixture_manifest_set_hash': canonical_hash([
            {'case_id': row['case_id'], 'fixture': row['fixture']} for row in rows
        ]),
        'grader_batch_schedule_hash': canonical_hash([
            {
                'case_id': row['case_id'],
                'grader_ids': sorted({item['grader_id'] for item in row['requirements']}),
            }
            for row in rows
        ]),
        'treatment_contract_hash': treatment_contract_hash(spec['variants']),
    })


def make_minimal_spec(level: str) -> dict:
    spec = {
        'schema_version': 4,
        'evaluation_id': f'minimal-{level.lower()}',
        'decision': 'audit package' if level == 'L0' else 'diagnose skill behavior',
        'claim_scope': 'bounded test fixture',
        'level': level,
        'risk_tier': 'standard',
        'target': {'name': 'target-skill', 'candidate_path': '/tmp/target-skill'},
        'authority': {'allow_file_writes': False, 'allow_network_read': False},
        'artifacts': {
            'root': 'artifacts',
            'retain_raw_traces': True,
            'redact_secrets': True,
            'manifest_required': True,
        },
    }
    if level == 'L0':
        return spec

    spec['target'].update({
        'candidate_revision': 'candidate-revision-test',
        'candidate_source_tree_hash': HASHES['source'],
        'candidate_plugin_tree_hash': HASHES['plugin'],
    })
    spec['target']['candidate_hash'] = HASHES['candidate']
    spec['environment'] = {
        'agent': 'test-agent',
        'model': 'test-model',
        'harness': 'test-harness',
        'timeout_seconds': 60,
        'random_seed': None,
        'network_policy': 'disabled',
        'credentials_policy': 'none',
    }
    spec['suite'] = {
        'cases_file': 'cases.jsonl',
        'cases_content_hash': HASHES['cases'],
        'case_contracts_content_hash': HASHES['contracts'],
        'fixture_manifest_set_hash': HASHES['fixtures'],
        'grader_batch_schedule_hash': HASHES['batch'],
        'repeats': 1,
        'reset_strategy': 'fresh_workspace',
        'retry_policy': 'no_retry',
        'run_order': 'case_order',
    }
    spec['variants'] = [{
        'id': 'candidate_natural',
        'role': 'candidate',
        'mode': 'natural_routing',
        'package_hash': HASHES['candidate'],
        'catalog_hash': HASHES['catalog'],
        'treatment_hash': HASHES['treatment'],
    }]
    spec['graders'] = [{
        'id': 'focused-check',
        'type': 'deterministic',
        'hard_gate': False,
        'version': '2',
        'checks': [{
            'id': 'task-complete',
            'pass_condition': 'The requested task is complete.',
        }],
        'verifier': {
            'path': 'graders/focused-check.py',
            'sha256': 'sha256:replace-before-scored-run',
            'argv': ['python3', 'graders/focused-check.py'],
            'pass_exit_codes': [0],
        },
    }]
    spec['ready_for_scored_run'] = False
    spec['suite']['treatment_contract_hash'] = treatment_contract_hash(spec['variants'])
    if level == 'L1':
        return spec

    spec['decision'] = 'compare candidate against no-skill baseline'
    spec['environment'].update({
        'system_config_hash': HASHES['system'],
        'tool_catalog_hash': HASHES['tools'],
        'skill_catalog_hash': HASHES['skills'],
        'os_or_image': 'test-image@sha256:' + '8' * 64,
        'random_seed': 17,
    })
    spec['variants'].insert(0, {
        'id': 'baseline',
        'role': 'baseline',
        'mode': 'skill_disabled',
        'package_hash': HASHES['package'],
        'catalog_hash': HASHES['catalog'],
        'treatment_hash': HASHES['treatment'],
    })
    spec['suite']['treatment_contract_hash'] = treatment_contract_hash(spec['variants'])
    spec['analysis'] = {
        'confidence_level': 0.95,
        'paired_bootstrap_iterations': 100,
        'primary_benefit': {
            'metric': 'task_pass_rate',
            'comparator': 'baseline',
            'direction': 'higher_is_better',
            'effect': 'absolute',
            'minimum_benefit': 0.1,
        },
        'context_budget_gate_id': 'replace-before-scored-run',
        'context_budget_authority': {
            'reference': 'replace-before-scored-run',
            'unit': 'replace-before-scored-run',
            'threshold': 'replace-before-scored-run',
        },
    }
    spec['metrics'] = ['task_pass_rate']
    spec['hard_gates'] = [
        {
            'id': 'minimum-pass-rate',
            'metric': 'candidate_natural.task_pass_rate',
            'operator': '>=',
            'value': 0.5,
        },
        {
            'id': 'protected-outcomes',
            'metric': 'protected_outcome_failures',
            'operator': '==',
            'value': 0,
        },
    ]
    return spec


def make_minimal_cases(*, comparative: bool = False) -> list[dict]:
    profiles = ['candidate/natural_routing']
    if comparative:
        profiles.insert(0, 'baseline/skill_disabled')
    definitions = [
        ('explicit', True, 'routing-explicit'),
        ('implicit', True, 'routing-implicit'),
        ('negative', False, 'routing-negative'),
    ]
    return [
        {
            'case_id': f'case-{name}',
            'split': 'dev',
            'tags': [tag],
            'prompt': f'{name} evaluation prompt',
            'should_trigger': should_trigger,
            'allowed_skills': ['target-skill'] if should_trigger else [],
            'fixture': {
                'manifest': 'fixtures/replace-before-scored-run.manifest.json',
                'sha256': 'sha256:replace-before-scored-run',
            },
            'requirements': [{
                'id': 'task-complete',
                'dimension': 'outcome',
                'required': True,
                'owner': 'deterministic',
                'grader_id': 'focused-check',
                'check_id': 'task-complete',
            }],
            'timeout_seconds': 60,
            'risk': 'standard',
            'applicable_variant_profiles': profiles,
            'attribution_evaluable': comparative,
        }
        for index, (name, should_trigger, tag) in enumerate(definitions, 1)
    ]


def make_scored_spec_concrete(spec: dict) -> None:
    spec['target']['candidate_hash'] = 'sha256:' + '3' * 64
    spec['target']['prior_hash'] = 'sha256:' + '9' * 64
    environment = spec['environment']
    environment.update({
        'agent': 'validated-agent-v1',
        'model': 'validated-model-v1',
        'harness': 'validated-harness-v1',
        'system_config_hash': 'sha256:' + '4' * 64,
        'tool_catalog_hash': 'sha256:' + '5' * 64,
        'skill_catalog_hash': 'sha256:' + '6' * 64,
        'sampling_config_hash': 'sha256:' + '7' * 64,
        'os_or_image': 'validated-image@sha256:' + '8' * 64,
    })
    for index, variant in enumerate(spec['variants'], start=1):
        if variant['role'] == 'candidate':
            variant['package_hash'] = spec['target']['candidate_hash']
        elif variant['role'] == 'prior':
            variant['package_hash'] = spec['target']['prior_hash']
        else:
            variant['package_hash'] = 'sha256:' + format(index, '064x')
        variant['catalog_hash'] = 'sha256:' + format(index + 10, '064x')
        variant['treatment_hash'] = 'sha256:' + format(index + 20, '064x')


def write_case_bundle(rows: list[dict], directory: Path, spec: dict) -> Path:
    public = [row for row in rows if row['split'] != 'heldout']
    holdout = [row for row in rows if row['split'] == 'heldout']
    public_path = directory / 'cases.jsonl'
    payload_path = directory / 'holdout-cases.jsonl'
    manifest_path = directory / 'holdout-manifest.json'
    public_path.write_text('\n'.join(json.dumps(row, separators=(',', ':')) for row in public) + '\n', encoding='utf-8')
    payload_path.write_text('\n'.join(json.dumps(row, separators=(',', ':')) for row in holdout) + ('\n' if holdout else ''), encoding='utf-8')
    file_hash = lambda path: 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        'schema_version': 1,
        'payload_file': payload_path.name,
        'payload_sha256': file_hash(payload_path),
        'case_count': len(holdout),
        'case_ids': [row['case_id'] for row in holdout],
        'cases': [{'case_id': row['case_id'], 'tags': row['tags'], 'case_sha256': canonical_hash(row)} for row in holdout],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    spec['suite']['cases_file'] = public_path.name
    spec['suite']['holdout_control'].update({
        'manifest_file': manifest_path.name,
        'payload_file': payload_path.name,
        'manifest_hash': file_hash(manifest_path),
        'payload_hash': file_hash(payload_path),
    })
    bind_suite_hashes(spec, rows)
    return public_path


def make_cases_concrete(rows: list[dict]) -> list[dict]:
    def replace_placeholders(value, token: str):
        if isinstance(value, str):
            return value.replace('replace-with-fixture-hash', token).replace('sha256:replace', 'sha256:' + token)
        if isinstance(value, list):
            return [replace_placeholders(item, token) for item in value]
        if isinstance(value, dict):
            return {key: replace_placeholders(item, token) for key, item in value.items()}
        return value

    concrete = []
    for index, row in enumerate(rows, start=1):
        token = format(index, '064x')
        concrete.append(replace_placeholders(json.loads(json.dumps(row)), token))
    return concrete


def write_spec_bundle(root: Path, spec: dict, rows: list[dict], *, ready: bool = False) -> tuple[Path, Path]:
    spec = json.loads(json.dumps(spec))
    rows = json.loads(json.dumps(rows))
    spec['suite']['cases_file'] = 'cases.jsonl'
    spec['ready_for_scored_run'] = ready

    if ready:
        graders_dir = root / 'graders'
        graders_dir.mkdir()
        for grader in spec['graders']:
            if grader['type'] != 'deterministic' or 'verifier' not in grader:
                continue
            verifier_path = graders_dir / f"{grader['id']}.py"
            verifier_path.write_text('raise SystemExit(0)\n', encoding='utf-8')
            relative = verifier_path.relative_to(root).as_posix()
            grader['verifier'] = {
                'path': relative,
                'sha256': 'sha256:' + hashlib.sha256(verifier_path.read_bytes()).hexdigest(),
                'argv': ['python3', relative],
                'pass_exit_codes': [0],
            }

        fixtures_dir = root / spec['artifacts']['root'] / 'fixtures'
        fixtures_dir.mkdir(parents=True)
        for row in rows:
            input_path = fixtures_dir / f"{row['case_id']}.txt"
            input_path.write_text(f"fixture for {row['case_id']}\n", encoding='utf-8')
            manifest_path = fixtures_dir / f"{row['case_id']}.manifest.json"
            manifest = {
                'artifacts': [{
                    'path': input_path.name,
                    'sha256': 'sha256:' + hashlib.sha256(input_path.read_bytes()).hexdigest(),
                    'encoding': 'utf-8',
                }],
            }
            manifest_path.write_text(json.dumps(manifest, separators=(',', ':')) + '\n', encoding='utf-8')
            row['fixture'] = {
                'manifest': manifest_path.relative_to(root / spec['artifacts']['root']).as_posix(),
                'sha256': 'sha256:' + hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            }

    bind_suite_hashes(spec, rows)
    spec_path = root / 'spec.json'
    cases_path = root / 'cases.jsonl'
    spec_path.write_text(json.dumps(spec), encoding='utf-8')
    cases_path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n', encoding='utf-8')
    return spec_path, cases_path


def write_receipt_bundle(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    spec = make_minimal_spec('L1')
    spec['artifacts']['root'] = 'artifacts'
    spec['variants'][0].update({
        'id': 'candidate_forced',
        'mode': 'force_loaded',
    })
    row = make_minimal_cases()[0]
    row['applicable_variant_profiles'] = ['candidate/force_loaded']
    spec_path, cases_path = write_spec_bundle(root, spec, [row], ready=True)

    package_root = root / 'target-skill'
    package_root.mkdir()
    (package_root / 'SKILL.md').write_text(
        RECEIPT_PACKAGE_SKILL, encoding='utf-8',
    )

    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    spec['target']['candidate_path'] = str(package_root)
    spec['target']['candidate_hash'] = RECEIPT_PACKAGE_HASH
    spec['variants'][0]['package_hash'] = RECEIPT_PACKAGE_HASH
    spec['suite']['treatment_contract_hash'] = treatment_contract_hash(spec['variants'])
    spec_path.write_text(json.dumps(spec), encoding='utf-8')
    case = json.loads(cases_path.read_text(encoding='utf-8').strip())

    file_hash = lambda path: 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
    grader = spec['graders'][0]
    grader_digest = canonical_hash({'declaration': grader})
    grader_set_digest = canonical_hash([{'id': grader['id'], 'sha256': grader_digest}])

    artifact_dir = root / spec['artifacts']['root'] / 'runs' / case['case_id'] / 'candidate_forced' / '1'
    verifier_dir = artifact_dir / 'verifier'
    verifier_dir.mkdir(parents=True)
    trace_path = artifact_dir / 'trace.jsonl'
    trace_events = [
        {'event_seq': 1, 'event': 'skill_retrieved'},
        {'event_seq': 2, 'event': 'skill_selected'},
        {'event_seq': 3, 'event': 'host_body_injected'},
        {'event_seq': 4, 'event': 'skill_incorporated'},
        {'event_seq': 5, 'event': 'assistant_deliverable'},
    ]
    trace_path.write_text(
        ''.join(json.dumps(item, separators=(',', ':')) + '\n' for item in trace_events),
        encoding='utf-8',
    )
    body_path = artifact_dir / 'context' / 'body.txt'
    body_path.parent.mkdir()
    body_path.write_text((package_root / 'SKILL.md').read_text(encoding='utf-8'), encoding='utf-8')
    stdout_path = verifier_dir / 'stdout.json'
    stdout = {
        'overall_pass': True,
        'score': 100,
        'checks': [{
            'id': 'task-complete',
            'pass': True,
            'evidence': [{
                'artifact': 'trace.jsonl',
                'locator': {'start_line': 1, 'end_line': 1},
                'observation': 'The task-complete event is present.',
            }],
            'notes': 'verified',
            'uncertainty': 'none',
        }],
        'missing_evidence': [],
        'grader_failure': False,
        'grader_failure_reason': None,
    }
    stdout_path.write_text(json.dumps(stdout, separators=(',', ':')) + '\n', encoding='utf-8')
    stderr_path = verifier_dir / 'stderr.bin'
    stderr_path.write_bytes(b'')
    artifacts = [
        {'path': 'trace.jsonl', 'sha256': file_hash(trace_path), 'encoding': 'utf-8'},
        {'path': 'context/body.txt', 'sha256': file_hash(body_path), 'encoding': 'utf-8'},
        {'path': 'verifier/stdout.json', 'sha256': file_hash(stdout_path), 'encoding': 'utf-8'},
        {'path': 'verifier/stderr.bin', 'sha256': file_hash(stderr_path), 'encoding': 'binary'},
    ]
    artifact_root = artifact_dir.relative_to(root).as_posix()

    def routing_stage(value: object, line: int) -> dict:
        return {
            'status': 'observed',
            'value': value,
            'evidence': [{
                'artifact': 'trace.jsonl',
                'locator': {'start_line': line, 'end_line': line},
                'observation': f'Frozen event {line} owns this routing stage.',
            }],
        }

    receipt = {
        'schema_version': 3,
        'receipt_hash': None,
        'run': {
            'run_id': f"{case['case_id']}:candidate_forced:1",
            'case_id': case['case_id'],
            'variant': 'candidate_forced',
            'repeat': 1,
            'valid': True,
            'error_type': None,
            'invalid_reason': None,
            'provenance': {
                'candidate_revision': spec['target']['candidate_revision'],
                'candidate_source_tree_hash': spec['target']['candidate_source_tree_hash'],
                'candidate_plugin_tree_hash': spec['target']['candidate_plugin_tree_hash'],
                'spec_content_hash': file_hash(spec_path),
                'case_content_hash': canonical_hash(case),
                'case_contracts_content_hash': spec['suite']['case_contracts_content_hash'],
                'fixture_manifest_set_hash': spec['suite']['fixture_manifest_set_hash'],
                'grader_set_hash': grader_set_digest,
                'grader_batch_schedule_hash': spec['suite']['grader_batch_schedule_hash'],
                'environment_hash': canonical_hash(spec['environment']),
                'package_hash': RECEIPT_PACKAGE_HASH,
                'catalog_hash': spec['variants'][0]['catalog_hash'],
                'treatment_hash': receipt_local_treatment_hash(case, spec['variants'][0]),
            },
        },
        'artifacts': artifacts,
        'trace': {
            'artifact': 'trace.jsonl',
            'sha256': file_hash(trace_path),
            'event_count': len(trace_events),
            'context_capture': {'status': 'captured', 'source': 'replay_manifest'},
            'command_projection_classification_hash': canonical_hash([]),
            'private_skill_access_count': 0,
            'task_evidence_visible_count': 0,
        },
        'routing': {
            'retrieved': routing_stage(['target-skill'], 1),
            'selected': routing_stage('target-skill', 2),
            'body_loaded': routing_stage(True, 3),
            'incorporated': routing_stage(True, 4),
            'applied': routing_stage(True, 5),
            'resources_loaded': [],
        },
        'boundaries': {
            'first_successful_source_write_seq': None,
            'first_deliverable_seq': 5,
        },
        'bytes': {
            'unique_static_content_bytes': body_path.stat().st_size,
            'repeated_static_content_bytes': 0,
            'protocol_output_bytes': 0,
            'failed_command_output_bytes': 0,
            'executor_prewrite_tool_output_bytes': 0,
            'host_preflight_tool_output_bytes': 0,
        },
        'counts': {
            'host_injected_body_count': 1,
            'model_initiated_body_read_count': 0,
            'body_load_count': 1,
            'reference_load_count': 0,
            'skill_load_tool_calls': 0,
            'skill_protocol_tool_calls': 0,
            'executor_prewrite_task_tool_calls': 0,
            'task_tool_calls': 0,
            'workflow_artifact_count': 0,
        },
        'usage': {
            'tokens_in': 10,
            'tokens_out': 5,
            'latency_ms': 20,
            'retries': 0,
            'evidence': [{
                'artifact': 'trace.jsonl',
                'locator': {'start_line': 1, 'end_line': 1},
                'observation': 'The trace is the frozen usage evidence.',
            }],
        },
        'context_usage': {
            'measurement_source': 'replay_manifest',
            'components': [{
                'kind': 'body',
                'source_path': 'SKILL.md',
                'artifact': 'context/body.txt',
                'tokens': None,
            }],
        },
        'grader_outputs': [{
            'grader_id': grader['id'],
            'invocation': {
                'grader_sha256': grader_digest,
                'selected_check_ids': ['task-complete'],
                'artifact_root': artifact_root,
                'input_artifacts': [
                    {'path': 'context/body.txt', 'sha256': file_hash(body_path)},
                    {'path': 'trace.jsonl', 'sha256': file_hash(trace_path)},
                ],
                'stdout_artifact': 'verifier/stdout.json',
                'stderr_artifact': 'verifier/stderr.bin',
                'exit_code': 0,
            },
        }],
    }
    receipt['receipt_hash'] = canonical_hash({
        key: value for key, value in receipt.items() if key != 'receipt_hash'
    })
    receipt_path = artifact_dir / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt, separators=(',', ':')) + '\n', encoding='utf-8')
    index = {
        'run_schema_version': 1,
        'run_id': receipt['run']['run_id'],
        'case_id': case['case_id'],
        'variant': 'candidate_forced',
        'repeat': 1,
        'artifact_dir': artifact_dir.relative_to(root / spec['artifacts']['root']).as_posix(),
        'receipt': {'path': 'receipt.json', 'sha256': file_hash(receipt_path)},
    }
    index_path = root / 'runs.jsonl'
    index_path.write_text(json.dumps(index, separators=(',', ':')) + '\n', encoding='utf-8')
    return {
        'spec': spec_path,
        'cases': cases_path,
        'index': index_path,
        'receipt': receipt_path,
        'artifact_dir': artifact_dir,
        'summary': root / 'summary.json',
    }


def rewrite_bound_receipt(bundle: dict[str, Path], receipt: dict) -> None:
    receipt_path = bundle['receipt']
    if receipt.get('schema_version') == 3 and 'receipt_hash' in receipt:
        receipt['receipt_hash'] = 'sha256:' + hashlib.sha256(
            json.dumps(
                {key: value for key, value in receipt.items() if key != 'receipt_hash'},
                sort_keys=True,
                separators=(',', ':'),
                ensure_ascii=False,
                allow_nan=False,
            ).encode('utf-8')
        ).hexdigest()
    receipt_path.write_text(json.dumps(receipt, separators=(',', ':')) + '\n', encoding='utf-8')
    index = json.loads(bundle['index'].read_text(encoding='utf-8'))
    index['receipt']['sha256'] = 'sha256:' + hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    bundle['index'].write_text(json.dumps(index, separators=(',', ':')) + '\n', encoding='utf-8')


def add_manual_review_receipt(bundle: dict[str, Path]) -> dict[str, Path | str]:
    file_hash = lambda path: 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
    spec = json.loads(bundle['spec'].read_text(encoding='utf-8'))
    spec['manual_review'] = {
        'required': True,
        'reviewer_role': 'independent-evaluator',
        'required_evidence': ['artifact-review'],
    }
    bundle['spec'].write_text(json.dumps(spec), encoding='utf-8')
    run_receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
    run_receipt['run']['provenance']['spec_content_hash'] = file_hash(bundle['spec'])
    rewrite_bound_receipt(bundle, run_receipt)

    artifacts_root = bundle['spec'].parent / spec['artifacts']['root']
    review_dir = artifacts_root / 'manual-review'
    review_dir.mkdir(parents=True)
    evidence_path = review_dir / 'artifact-review.txt'
    evidence_path.write_text('reviewed frozen artifacts\n', encoding='utf-8')
    review_receipt = {
        'reviewer_role': 'independent-evaluator',
        'evidence': [{
            'type': 'artifact-review',
            'artifact': evidence_path.relative_to(artifacts_root).as_posix(),
            'sha256': file_hash(evidence_path),
        }],
        'decision': 'approve',
        'signature': 'reviewer attestation',
    }
    receipt_path = review_dir / 'receipt.json'
    receipt_path.write_text(json.dumps(review_receipt, separators=(',', ':')) + '\n', encoding='utf-8')
    return {
        'path': receipt_path,
        'reference': receipt_path.relative_to(artifacts_root).as_posix(),
        'evidence': evidence_path,
    }


def add_context_component(
    bundle: dict[str, Path], *, measurement_source: str = 'replay_manifest',
    kind: str = 'body', source_path: str = 'SKILL.md', tokens: int | None = None,
    artifact_name: str | None = None, content: str | None = None, append: bool = False,
) -> Path:
    file_hash = lambda path: 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
    artifact = bundle['artifact_dir'] / 'context' / (artifact_name or f'{kind}.txt')
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(content or f'frozen {kind} context\n', encoding='utf-8')
    reference = artifact.relative_to(bundle['artifact_dir']).as_posix()
    artifact_entry = {'path': reference, 'sha256': file_hash(artifact), 'encoding': 'utf-8'}
    existing_artifact = next(
        (item for item in receipt['artifacts'] if item['path'] == reference), None,
    )
    if existing_artifact is None:
        receipt['artifacts'].append(artifact_entry)
    else:
        existing_artifact.update(artifact_entry)
    components = receipt['context_usage']['components'] if append else []
    components.append({
        'kind': kind, 'source_path': source_path,
        'artifact': reference, 'tokens': tokens,
    })
    receipt['context_usage'] = {'measurement_source': measurement_source, 'components': components}
    receipt['trace']['context_capture']['source'] = (
        'host_trace' if measurement_source == 'host_receipt' else 'replay_manifest'
    )
    receipt['routing']['resources_loaded'] = sorted({
        item['source_path'] for item in components if item['kind'] == 'reference'
    })
    body_count = sum(item['kind'] == 'body' for item in components)
    receipt['counts'].update({
        'host_injected_body_count': min(body_count, 1),
        'model_initiated_body_read_count': max(body_count - 1, 0),
        'body_load_count': body_count,
        'reference_load_count': sum(item['kind'] == 'reference' for item in components),
    })
    receipt['routing']['body_loaded']['value'] = body_count > 0

    context_bytes = {field: 0 for field in (
        'unique_static_content_bytes', 'repeated_static_content_bytes',
        'protocol_output_bytes', 'failed_command_output_bytes',
    )}
    static_seen: set[tuple[str, str]] = set()
    for item in components:
        component_path = bundle['artifact_dir'] / item['artifact']
        size = component_path.stat().st_size
        if item['kind'] in {'metadata', 'body', 'reference'}:
            identity = (item['source_path'], file_hash(component_path))
            field = (
                'repeated_static_content_bytes' if identity in static_seen
                else 'unique_static_content_bytes'
            )
            static_seen.add(identity)
        elif item['kind'] == 'protocol_output':
            field = 'protocol_output_bytes'
        else:
            field = 'failed_command_output_bytes'
        context_bytes[field] += size
    receipt['bytes'].update(context_bytes)
    inputs = receipt['grader_outputs'][0]['invocation']['input_artifacts']
    inputs[:] = [item for item in inputs if item['path'] != reference]
    inputs.append({'path': reference, 'sha256': file_hash(artifact)})
    inputs.sort(key=lambda item: item['path'])
    rewrite_bound_receipt(bundle, receipt)
    return artifact


def load_analyzer_module():
    scripts = str(ROOT / 'scripts')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location('skill_evaluator_analyze_runs', ROOT / 'scripts/analyze_runs.py')
    if spec is None or spec.loader is None:
        raise AssertionError('cannot load analyze_runs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_validator_module():
    spec = importlib.util.spec_from_file_location(
        'skill_evaluator_validate_eval_suite',
        ROOT / 'scripts/validate_eval_suite.py',
    )
    if spec is None or spec.loader is None:
        raise AssertionError('cannot load validate_eval_suite.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_auditor_module():
    spec = importlib.util.spec_from_file_location(
        'skill_evaluator_audit_skill_package', ROOT / 'scripts/audit_skill_package.py',
    )
    if spec is None or spec.loader is None:
        raise AssertionError('cannot load audit_skill_package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stamp_provenance(rows: list[dict], spec_path: Path, cases_path: Path) -> list[dict]:
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    cases = {
        row['case_id']: row
        for row in (json.loads(line) for line in cases_path.read_text(encoding='utf-8').splitlines() if line.strip())
    }
    payload_ref = spec['suite'].get('holdout_control', {}).get('payload_file')
    if payload_ref:
        payload_path = spec_path.parent / payload_ref
        if payload_path.is_file():
            cases.update({
                row['case_id']: row
                for row in (json.loads(line) for line in payload_path.read_text(encoding='utf-8').splitlines() if line.strip())
            })

    shared = {
        'evaluation_id': spec['evaluation_id'],
        'spec_sha256': 'sha256:' + hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        'grader_set_sha256': canonical_hash(spec['graders']),
        'environment_sha256': canonical_hash(spec['environment']),
    }
    variants = {variant['id']: variant for variant in spec['variants']}
    stamped = []
    for source in rows:
        row = dict(source)
        case = cases[row['case_id']]
        variant = variants[row['variant']]
        row['provenance'] = {
            **shared,
            'package_hash': variant['package_hash'],
            'catalog_hash': variant['catalog_hash'],
            'treatment_hash': receipt_local_treatment_hash(case, variant),
            'case_sha256': canonical_hash(case),
            'fixture': case['fixture'],
        }
        stamped.append(row)
    return stamped


PYTHON = sys.executable


class SkillEvaluatorTestCase(unittest.TestCase):
    def call_cli(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        script_path = ROOT / script
        scripts = str(script_path.parent)
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        spec = importlib.util.spec_from_file_location(
            f"test_cli_{script_path.stem}_{id(self)}", script_path,
        )
        if spec is None or spec.loader is None:
            raise AssertionError(f"cannot load {script}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stdout = io.StringIO()
        stderr = io.StringIO()
        previous_argv = sys.argv
        previous_cwd = Path.cwd()
        sys.argv = [str(script_path), *args]
        try:
            os.chdir(ROOT)
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    returncode = module.main()
                except SystemExit as exc:
                    returncode = int(exc.code or 0)
        finally:
            os.chdir(previous_cwd)
            sys.argv = previous_argv
        return subprocess.CompletedProcess(
            [PYTHON, str(script_path), *args], returncode,
            stdout.getvalue(), stderr.getvalue(),
        )

    def run_cmd(
        self, *args: str, timeout: float = 30,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [PYTHON, *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )

    def run_receipt_analysis(self, bundle: dict[str, Path]) -> subprocess.CompletedProcess[str]:
        return self.call_cli(
            'scripts/analyze_runs.py', str(bundle['index']),
            '--spec', str(bundle['spec']), '--json', str(bundle['summary']),
        )

    def assert_valid_receipt_bundle(self, bundle: dict[str, Path]) -> dict:
        result = self.run_receipt_analysis(bundle)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(bundle['summary'].read_text(encoding='utf-8'))
        self.assertEqual(report['evidence_status'], 'complete')
        return report
