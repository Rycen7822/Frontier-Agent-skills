from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
from unittest import mock

from skill_evaluator_comparison_support import *  # noqa: F403


class TestExtendedEvalComparison(ComparisonTestCase):  # noqa: F405
    def test_comparison_templates_are_valid_and_self_hashed(self) -> None:
        validator = load_validator_module()  # noqa: F405
        evidence = load_evidence_io_module()  # noqa: F405
        registry = validator.load_v5_schema_registry()
        for name in (
            'comparison-plan.revision.example.json',
            'comparison-plan.model-transition.example.json',
        ):
            with self.subTest(name=name):
                value = json.loads(
                    (ROOT / 'templates' / name).read_text(  # noqa: F405
                        encoding='utf-8',
                    ),
                )
                self.assertEqual([], validator.validate_v5_schema(
                    value,
                    'comparison-plan-v1.schema.json',
                    registry,
                ))
                self.assertTrue(evidence.verify_self_hash(
                    value,
                    'comparison_plan_hash',
                ))

    def test_structural_cli_writes_valid_atomic_outputs_for_both_kinds(
        self,
    ) -> None:
        for kind in ('revision', 'model_transition'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                plan_path, plan = (
                    self._revision_fixture(root)
                    if kind == 'revision'
                    else self._transition_fixture(root)
                )
                result = self.call_cli(
                    'scripts/compare_cycles.py',
                    str(plan_path),
                )
                self.assertEqual(
                    0, result.returncode, result.stdout + result.stderr,
                )
                output_root = root / plan['output']['root']
                report_path = output_root / plan['output']['report']
                index_path = (
                    output_root / plan['output']['diagnostic_index']
                )
                report = json.loads(report_path.read_text(encoding='utf-8'))
                index = json.loads(index_path.read_text(encoding='utf-8'))
                validator = load_validator_module()  # noqa: F405
                evidence = load_evidence_io_module()  # noqa: F405
                registry = validator.load_v5_schema_registry()
                self.assertEqual([], validator.validate_v5_schema(
                    report,
                    'comparison-report-v1.schema.json',
                    registry,
                ))
                self.assertEqual([], validator.validate_v5_schema(
                    index,
                    'comparison-diagnostic-index-v1.schema.json',
                    registry,
                ))
                self.assertTrue(evidence.verify_self_hash(
                    report,
                    'comparison_report_hash',
                ))
                self.assertTrue(evidence.verify_self_hash(
                    index,
                    'comparison_diagnostic_index_hash',
                ))
                self.assertEqual(
                    index['comparison_diagnostic_index_hash'],
                    report['diagnostic_index_hash'],
                )
                self.assertEqual(
                    evidence.canonical_json_bytes(report),
                    report_path.read_bytes(),
                )
                self.assertEqual(
                    evidence.canonical_json_bytes(index),
                    index_path.read_bytes(),
                )
                self.assertNotIn(str(root), result.stdout)
                self.assertLess(len(result.stdout), 640)
                first_bytes = (report_path.read_bytes(), index_path.read_bytes())
                shutil.rmtree(output_root)
                repeated = self.call_cli(
                    'scripts/compare_cycles.py',
                    str(plan_path),
                )
                self.assertEqual(
                    0,
                    repeated.returncode,
                    repeated.stdout + repeated.stderr,
                )
                self.assertEqual(
                    first_bytes,
                    (report_path.read_bytes(), index_path.read_bytes()),
                )

    def test_structural_cli_rejects_tamper_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = self._revision_fixture(root)
            plan['input_bindings']['prior']['spec']['file_sha256'] = (
                'sha256:' + '0' * 64
            )
            self._rewrite_plan(plan_path, plan)
            result = self.call_cli(
                'scripts/compare_cycles.py',
                str(plan_path),
            )
            self.assertEqual(
                2, result.returncode, result.stdout + result.stderr,
            )
            self.assertIn('[input.file_hash]', result.stderr)
            self.assertFalse((root / plan['output']['root']).exists())

    def test_plan_and_path_boundaries_fail_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._revision_fixture(root)
            (root / 'directory-input').mkdir()
            cases = (
                ('extra-key', 'extra', True, '[contract.schema]', True),
                ('missing-key', 'delete', 'output', '[contract.schema]', True),
                ('wrong-kind', 'kind', 'unknown', '[contract.schema]', True),
                ('wrong-enum', 'registration', 'later', '[contract.schema]', True),
                (
                    'traversal', 'spec_path', '../outside.json',
                    '[contract.schema]', True,
                ),
                (
                    'absolute', 'spec_path', '/tmp/outside.json',
                    '[contract.schema]', True,
                ),
                (
                    'backslash', 'spec_path', 'cycles\\prior.json',
                    '[contract.schema]', True,
                ),
                ('bad-self-hash', 'none', None, '[plan.hash]', False),
                ('missing-file', 'spec_path', 'missing.json', '[input.path]', True),
                (
                    'directory', 'spec_path', 'directory-input',
                    '[input.path]', True,
                ),
            )
            for index, (name, field, value, expected, refresh) in enumerate(cases):
                with self.subTest(name=name):
                    plan = copy.deepcopy(baseline)
                    output_name = f'output-{index}'
                    plan['output']['root'] = output_name
                    if field == 'extra':
                        plan['unexpected'] = value
                    elif field == 'delete':
                        del plan[value]
                    elif field == 'kind':
                        plan['kind'] = value
                    elif field == 'registration':
                        plan['registration']['mode'] = value
                    elif field == 'spec_path':
                        plan['input_bindings']['prior']['spec']['path'] = value
                    plan_path = root / f'{name}.json'
                    self._rewrite_plan(
                        plan_path,
                        plan,
                        refresh_hash=refresh,
                    )
                    result = self.call_cli(
                        'scripts/compare_cycles.py',
                        str(plan_path),
                    )
                    self.assertEqual(
                        2,
                        result.returncode,
                        result.stdout + result.stderr,
                    )
                    self.assertIn(expected, result.stderr)
                    self.assertFalse((root / output_name).exists())

    def test_symlink_input_and_cross_reference_tamper_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = self._revision_fixture(root)
            spec_path = root / plan['input_bindings']['prior']['spec']['path']
            linked_spec = root / 'linked-spec.json'
            linked_spec.symlink_to(spec_path)
            plan['input_bindings']['prior']['spec']['path'] = linked_spec.name
            self._rewrite_plan(plan_path, plan)
            linked = self.call_cli('scripts/compare_cycles.py', str(plan_path))
            self.assertEqual(2, linked.returncode, linked.stdout + linked.stderr)
            self.assertIn('[contract.symlink]', linked.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = self._revision_fixture(root)
            summary_path = root / plan['input_bindings']['prior']['summary']['path']
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            summary['plan_id'] = 'plan-cross-reference-tamper'
            evidence = load_evidence_io_module()  # noqa: F405
            summary['summary_hash'] = evidence.canonical_self_hash(
                summary,
                'summary_hash',
            )
            summary_path.write_bytes(evidence.canonical_json_bytes(summary))
            result = self.call_cli('scripts/compare_cycles.py', str(plan_path))
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertIn('[input.identity]', result.stderr)
            self.assertFalse((root / plan['output']['root']).exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = self._transition_fixture(root)
            binding = plan['input_bindings']['A']['observations']
            observations_path = root / binding['path']
            observations = json.loads(
                observations_path.read_text(encoding='utf-8'),
            )
            observations['plan_id'] = 'plan-observations-cross-reference-tamper'
            evidence = load_evidence_io_module()  # noqa: F405
            observations['comparison_observations_hash'] = (
                evidence.canonical_self_hash(
                    observations,
                    'comparison_observations_hash',
                )
            )
            observations_path.write_bytes(
                evidence.canonical_json_bytes(observations),
            )
            result = self.call_cli('scripts/compare_cycles.py', str(plan_path))
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertIn('[input.identity]', result.stderr)
            self.assertFalse((root / plan['output']['root']).exists())

    def test_existing_output_root_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = self._revision_fixture(root)
            output_root = root / plan['output']['root']
            output_root.mkdir()
            sentinel = output_root / 'sentinel.txt'
            sentinel.write_bytes(b'keep')
            result = self.call_cli('scripts/compare_cycles.py', str(plan_path))
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertIn('[output.exists]', result.stderr)
            self.assertEqual(b'keep', sentinel.read_bytes())

    def test_failure_index_manifest_cross_reference_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = self._revision_fixture(root)
            candidate = self._bound_cycle_paths(root, plan, 'candidate')
            summary = json.loads(
                candidate['summary'].read_text(encoding='utf-8'),
            )
            summary['output_manifest']['failure_index']['sha256'] = (
                'sha256:' + '0' * 64
            )
            self._write_self_hashed(
                candidate['summary'],
                summary,
                'summary_hash',
            )
            result = self.call_cli('scripts/compare_cycles.py', str(plan_path))
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertIn('[input.identity]', result.stderr)
            self.assertFalse((root / plan['output']['root']).exists())

    def test_atomic_directory_failure_leaves_no_partial_output(self) -> None:
        evidence = load_evidence_io_module()  # noqa: F405
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'output'
            with mock.patch.object(
                evidence,
                '_rename_no_replace',
                side_effect=OSError('simulated publication failure'),
            ):
                with self.assertRaises(OSError):
                    evidence.atomic_write_directory(
                        output,
                        {'a.json': b'{}', 'b.json': b'{}'},
                    )
            self.assertFalse(output.exists())
            self.assertEqual([], list(root.iterdir()))
