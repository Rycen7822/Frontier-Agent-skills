from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile

from skill_evaluator_comparison_support import *  # noqa: F403


class TestExtendedEvalRevision(ComparisonTestCase):  # noqa: F405
    def test_revision_exact_margin_closes_without_elevating_exploration(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = self._revision_fixture(root)
            result = self.call_cli('scripts/compare_cycles.py', str(plan_path))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            report_path = (
                root / plan['output']['root'] / plan['output']['report']
            )
            report = json.loads(report_path.read_text(encoding='utf-8'))
            diagnostic_path = (
                root
                / plan['output']['root']
                / plan['output']['diagnostic_index']
            )
            diagnostics = json.loads(
                diagnostic_path.read_text(encoding='utf-8'),
            )
            self.assertEqual(
                'closed',
                report['result']['status'],
                {'report': report, 'diagnostics': diagnostics},
            )
            self.assertEqual('blocked', report['authority_eligibility'])
            self.assertEqual('diagnostic_only', report['claim_ceiling'])
            self.assertEqual('exploratory', report['registration_status'])

    def test_revision_plan_boundaries_have_closed_open_and_unknown_states(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._revision_fixture(root)
            cases = (
                ('below-margin', 'margin', 0.01, 'open', 'blocked'),
                ('underpowered', 'minimum', 3, 'not_evaluable', 'blocked'),
                (
                    'missing-target', 'target', 'sf-' + '2' * 24,
                    'not_evaluable', 'blocked',
                ),
                (
                    'missing-case', 'case', 'case-unknown',
                    'not_evaluable', 'blocked',
                ),
                (
                    'duplicate-metric', 'duplicate', 'task-benefit',
                    'not_evaluable', 'blocked',
                ),
                ('pre-registered', 'registration', None, 'closed', 'eligible'),
            )
            for index, (name, field, value, status, authority) in enumerate(cases):
                with self.subTest(name=name):
                    plan = copy.deepcopy(baseline)
                    plan['output']['root'] = f'revision-boundary-{index}'
                    policy = plan['decision_policy']
                    if field == 'margin':
                        policy['metric_rules'][0]['margin'] = value
                    elif field == 'minimum':
                        policy['minimum_distinct_cases'] = value
                    elif field == 'target':
                        policy['target']['diagnostic_ids'] = [value]
                    elif field == 'case':
                        policy['target']['case_ids'] = [value]
                    elif field == 'duplicate':
                        policy['metric_rules'][1]['metric_id'] = value
                    elif field == 'registration':
                        plan['registration']['mode'] = 'pre_registered'
                    plan_path = root / f'{name}.json'
                    self._rewrite_plan(plan_path, plan)
                    result = self.call_cli(
                        'scripts/compare_cycles.py',
                        str(plan_path),
                    )
                    self.assertEqual(
                        0,
                        result.returncode,
                        result.stdout + result.stderr,
                    )
                    report_path = (
                        root / plan['output']['root'] / plan['output']['report']
                    )
                    report = json.loads(report_path.read_text(encoding='utf-8'))
                    self.assertEqual(status, report['result']['status'], report)
                    self.assertEqual(authority, report['authority_eligibility'])

    def test_revision_residual_metric_and_gate_failures_stay_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._revision_fixture(root)
            candidate = self._bound_cycle_paths(root, baseline, 'candidate')
            prior = self._bound_cycle_paths(root, baseline, 'prior')
            prior_index = json.loads(
                prior['failures'].read_text(encoding='utf-8'),
            )

            residual = copy.deepcopy(prior_index['failures'][0])
            candidate_plan = json.loads(
                candidate['plan'].read_text(encoding='utf-8'),
            )
            candidate_spec = json.loads(
                candidate['spec'].read_text(encoding='utf-8'),
            )
            residual.update({
                'failure_id': 'sf-' + '3' * 24,
                'evaluation_id': candidate_spec['evaluation_id'],
                'plan_id': candidate_plan['plan_id'],
                'entry_id': candidate_plan['entries'][0]['entry_id'],
            })
            self._set_failures(candidate, [residual])
            self._assert_revision_status(
                root,
                baseline,
                'residual-output',
                'open',
            )

            self._set_failures(candidate, [])
            self._set_metric_evidence(candidate, {
                'task-benefit': 1.0,
                'safety-benefit': 0.0,
            })
            self._assert_revision_status(
                root,
                baseline,
                'protected-output',
                'open',
            )

            self._set_metric_evidence(candidate, {
                'task-benefit': 1.0,
                'safety-benefit': 1.0,
            })
            gate_failure = copy.deepcopy(residual)
            gate_failure.update({
                'failure_id': 'sf-' + '4' * 24,
                'family': 'gate',
                'code': 'gate.failed',
                'reason_key': 'required_gate_failed',
                'case_id': None,
                'requirement_id': None,
                'dimension': None,
                'gate_id': 'safety-gate',
            })
            self._set_failures(candidate, [gate_failure])
            self._assert_revision_status(
                root,
                baseline,
                'gate-output',
                'open',
            )

    def test_revision_fixed_identity_and_package_drift_are_not_evaluable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._revision_fixture(root)
            candidate = self._bound_cycle_paths(root, baseline, 'candidate')
            original_plan = json.loads(
                candidate['plan'].read_text(encoding='utf-8'),
            )
            original_summary = json.loads(
                candidate['summary'].read_text(encoding='utf-8'),
            )
            evidence = load_evidence_io_module()  # noqa: F405
            for name in ('model-identity', 'other-package'):
                with self.subTest(name=name):
                    cycle_plan = copy.deepcopy(original_plan)
                    if name == 'model-identity':
                        cycle_plan['execution_identity']['model_hash'] = (
                            'sha256:' + '8' * 64
                        )
                    else:
                        cycle_plan['package_hashes']['unexpected-module'] = (
                            'sha256:' + '7' * 64
                        )
                    self._write_self_hashed(
                        candidate['plan'],
                        cycle_plan,
                        'plan_hash',
                    )
                    summary = copy.deepcopy(original_summary)
                    summary['plan_hash'] = cycle_plan['plan_hash']
                    self._write_self_hashed(
                        candidate['summary'],
                        summary,
                        'summary_hash',
                    )
                    plan = copy.deepcopy(baseline)
                    binding = plan['input_bindings']['candidate']
                    binding['execution_plan']['file_sha256'] = (
                        evidence.file_sha256(candidate['plan'])
                    )
                    binding['expected_identity']['execution_identity'] = (
                        cycle_plan['execution_identity']
                    )
                    plan['output']['root'] = f'{name}-drift-output'
                    plan_path = root / f'{name}.plan.json'
                    self._rewrite_plan(plan_path, plan)
                    result = self.call_cli(
                        'scripts/compare_cycles.py',
                        str(plan_path),
                    )
                    self.assertEqual(
                        0,
                        result.returncode,
                        result.stdout + result.stderr,
                    )
                    report_path = (
                        root / plan['output']['root'] / plan['output']['report']
                    )
                    report = json.loads(
                        report_path.read_text(encoding='utf-8'),
                    )
                    self.assertEqual(
                        'not_evaluable',
                        report['result']['status'],
                        report,
                    )
                    identity_check = next(
                        item
                        for item in report['comparability_checks']
                        if item['check_id'] == 'revision-identity'
                    )
                    self.assertEqual('not_evaluable', identity_check['status'])
