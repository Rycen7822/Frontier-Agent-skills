from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
from unittest import mock

from skill_evaluator_comparison_support import *  # noqa: F403


class TestExtendedEvalComparison(ComparisonTestCase):  # noqa: F405
    def test_comparison_templates_are_valid_without_self_hashes(self) -> None:
        validator = load_validator_module()  # noqa: F405
        registry = validator.load_epoch6_schema_registry()
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
                self.assertEqual([], validator.validate_epoch6_schema(
                    value,
                    'comparison-plan-v2.schema.json',
                    registry,
                ))
                self.assertNotIn('comparison_plan_hash', value)

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
                registry = validator.load_epoch6_schema_registry()
                self.assertEqual([], validator.validate_epoch6_schema(
                    report,
                    'comparison-report-v2.schema.json',
                    registry,
                ))
                self.assertEqual([], validator.validate_epoch6_schema(
                    index,
                    'comparison-diagnostic-index-v2.schema.json',
                    registry,
                ))
                self.assertEqual(
                    index_path.name,
                    report['diagnostic_index_path'],
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
            plan['input_bindings']['prior']['capsule']['digest'] = (
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
            self.assertIn('[input.digest]', result.stderr)
            self.assertFalse((root / plan['output']['root']).exists())

    def test_plan_and_path_boundaries_fail_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._revision_fixture(root)
            (root / 'directory-input').mkdir()
            cases = (
                ('extra-key', 'extra', True, '[contract.schema]'),
                ('missing-key', 'delete', 'output', '[contract.schema]'),
                ('wrong-kind', 'kind', 'unknown', '[contract.schema]'),
                ('wrong-enum', 'registration', 'later', '[contract.schema]'),
                (
                    'traversal', 'capsule_path', '../outside.json',
                    '[contract.schema]',
                ),
                (
                    'absolute', 'capsule_path', '/tmp/outside.json',
                    '[contract.schema]',
                ),
                (
                    'backslash', 'capsule_path', 'cycles\\prior.json',
                    '[contract.schema]',
                ),
                ('bad-capsule-digest', 'capsule_digest', None, '[input.digest]'),
                ('missing-file', 'capsule_path', 'missing.json', '[input.path]'),
                (
                    'directory', 'capsule_path', 'directory-input',
                    '[input.path]',
                ),
            )
            for index, (name, field, value, expected) in enumerate(cases):
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
                    elif field == 'capsule_path':
                        plan['input_bindings']['prior']['capsule']['path'] = value
                    elif field == 'capsule_digest':
                        plan['input_bindings']['prior']['capsule']['digest'] = (
                            'sha256:' + '0' * 64
                        )
                    plan_path = root / f'{name}.json'
                    self._rewrite_plan(plan_path, plan)
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
            capsule_path = (
                root / plan['input_bindings']['prior']['capsule']['path']
            )
            linked_capsule = root / 'linked-capsule.json'
            linked_capsule.symlink_to(capsule_path)
            plan['input_bindings']['prior']['capsule']['path'] = (
                linked_capsule.name
            )
            self._rewrite_plan(plan_path, plan)
            linked = self.call_cli('scripts/compare_cycles.py', str(plan_path))
            self.assertEqual(2, linked.returncode, linked.stdout + linked.stderr)
            self.assertIn('[contract.symlink]', linked.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = self._revision_fixture(root)
            summary_path = self._bound_cycle_paths(
                root, plan, 'prior',
            )['summary']
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            summary['plan_id'] = 'plan-cross-reference-tamper'
            evidence = load_evidence_io_module()  # noqa: F405
            summary_path.write_bytes(evidence.canonical_json_bytes(summary))
            self._refresh_cycle_binding(root, plan, 'prior')
            self._rewrite_plan(plan_path, plan)
            result = self.call_cli('scripts/compare_cycles.py', str(plan_path))
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertIn('[input.identity]', result.stderr)
            self.assertFalse((root / plan['output']['root']).exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = self._transition_fixture(root)
            bound = self._bound_cycle_paths(root, plan, 'A')
            observations_path = bound['observations']
            observations = json.loads(
                observations_path.read_text(encoding='utf-8'),
            )
            observations['plan_id'] = 'plan-observations-cross-reference-tamper'
            evidence = load_evidence_io_module()  # noqa: F405
            observations_path.write_bytes(
                evidence.canonical_json_bytes(observations),
            )
            self._refresh_cycle_binding(root, plan, 'A')
            self._rewrite_plan(plan_path, plan)
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
            summary['output_manifest']['failure_index']['path'] = 'other.json'
            self._write_document(candidate['summary'], summary)
            self._refresh_cycle_binding(root, plan, 'candidate')
            self._rewrite_plan(plan_path, plan)
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
