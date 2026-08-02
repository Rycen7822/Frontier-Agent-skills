from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile

from skill_evaluator_comparison_support import ComparisonTestCase


class TestExtendedEvalTransition(ComparisonTestCase):
    def _run_transition(
        self,
        root: Path,
        baseline: dict,
        output_root: str,
        expected: str,
    ) -> dict:
        plan = copy.deepcopy(baseline)
        plan['output']['root'] = output_root
        plan_path = root / f'{output_root}.plan.json'
        self._rewrite_plan(plan_path, plan)
        result = self.call_cli('scripts/compare_cycles.py', str(plan_path))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        report = json.loads(
            (root / output_root / plan['output']['report']).read_text(
                encoding='utf-8',
            ),
        )
        self.assertEqual(expected, report['result']['classification'], report)
        return report

    @staticmethod
    def _gain_rule() -> dict:
        return {
            'purpose': 'gain_retention',
            'metric_id': 'task-benefit',
            'direction': 'higher_is_better',
            'threshold': 0.8,
        }

    def _set_observation_scale(
        self,
        paths: dict[str, Path],
        metric_id: str,
        unit: str,
    ) -> None:
        observations = json.loads(
            paths['observations'].read_text(encoding='utf-8'),
        )
        metric = [
            item for item in observations['metrics']
            if item['metric_id'] == metric_id
        ][0]
        metric['scale'] = {
            'raw': unit,
            'reported': unit,
            'normalization': f'per_{unit}',
        }
        self._write_self_hashed(
            paths['observations'],
            observations,
            'comparison_observations_hash',
        )

    def test_direct_terminal_classifications_and_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._transition_fixture(root)
            target = self._bound_cycle_paths(root, baseline, 'C')

            retained = self._run_transition(
                root,
                baseline,
                'retained',
                'retained_specialized_value',
            )
            self.assertEqual('blocked', retained['authority_eligibility'])

            registered = copy.deepcopy(baseline)
            registered['registration']['mode'] = 'pre_registered'
            eligible = self._run_transition(
                root,
                registered,
                'eligible',
                'retained_specialized_value',
            )
            self.assertEqual('eligible', eligible['authority_eligibility'])

            self._set_transition_evidence(
                target,
                task_benefit=0.2,
                native_value=0.45,
            )
            self._run_transition(
                root,
                baseline,
                'absorption',
                'native_capability_absorption_candidate',
            )

            interference = copy.deepcopy(baseline)
            interference['decision_policy']['metric_rules'] = [
                self._gain_rule(),
                {
                    'purpose': 'interference',
                    'metric_id': 'safety-benefit',
                    'direction': 'higher_is_better',
                    'threshold': 0.1,
                },
            ]
            self._set_metric_evidence(target, {'safety-benefit': 0.0})
            self._run_transition(
                root,
                interference,
                'interference',
                'skill_interference',
            )

            specialization = copy.deepcopy(baseline)
            specialization['decision_policy']['metric_rules'] = [
                self._gain_rule(),
                {
                    'purpose': 'specialization',
                    'metric_id': 'task-benefit',
                    'direction': 'higher_is_better',
                    'threshold': 0.3,
                },
            ]
            self._run_transition(
                root,
                specialization,
                'specialization',
                'insufficient_specialization',
            )

            stable = copy.deepcopy(baseline)
            stable['decision_policy']['metric_rules'] = [self._gain_rule()]
            self._run_transition(
                root,
                stable,
                'stable',
                'stable_no_incremental_value',
            )

    def test_stage_precedence_and_underpowered_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._transition_fixture(root)
            target = self._bound_cycle_paths(root, baseline, 'C')
            for stage, expected in (
                ('retrieved', 'routing_loss'),
                ('loaded', 'loading_loss'),
                ('applied', 'application_loss'),
            ):
                self._set_transition_evidence(
                    target,
                    task_benefit=0.45,
                    native_value=0.45,
                    stage_passed={stage: 1},
                )
                self._run_transition(root, baseline, stage, expected)

            self._set_transition_evidence(
                target,
                task_benefit=0.45,
                native_value=0.45,
            )
            underpowered = copy.deepcopy(baseline)
            underpowered['decision_policy']['minimum_distinct_cases'] = 3
            report = self._run_transition(
                root,
                underpowered,
                'underpowered',
                'mixed_or_underpowered',
            )
            self.assertEqual('blocked', report['authority_eligibility'])

    def test_gate_and_identity_fail_closed_before_soft_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._transition_fixture(root)
            target = self._bound_cycle_paths(root, baseline, 'C')
            protected = copy.deepcopy(baseline)
            protected['decision_policy']['metric_rules'].append({
                'purpose': 'protected_noninferiority',
                'metric_id': 'safety-benefit',
                'direction': 'higher_is_better',
                'threshold': 0.1,
            })
            self._set_metric_evidence(target, {'safety-benefit': 0.0})
            self._run_transition(
                root,
                protected,
                'protected-failure',
                'safety_or_protected_interference',
            )

            self._set_transition_evidence(
                target,
                task_benefit=0.45,
                native_value=0.45,
            )
            failure = self._revision_failure(target)
            failure.update({
                'family': 'gate',
                'code': 'gate.failed',
                'gate_id': 'safety-gate',
                'reason_key': 'required_gate_failed',
            })
            self._set_failures(target, [failure])
            self._run_transition(
                root,
                baseline,
                'gate-failure',
                'safety_or_protected_interference',
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, drift = self._transition_fixture(
                root,
                target_execution_updates={'prompt_hash': 'sha256:' + '7' * 64},
            )
            self._run_transition(
                root,
                drift,
                'identity-drift',
                'apparatus_inconclusive',
            )

    def test_tokenizer_and_judge_comparability(self) -> None:
        tokenizer_updates = {
            'tokenizer_id': 'target-tokenizer',
            'pricing_id': 'target-pricing',
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._transition_fixture(
                root,
                target_execution_updates=tokenizer_updates,
            )
            self._run_transition(
                root,
                baseline,
                'same-tokenizer-required',
                'apparatus_inconclusive',
            )

            bytes_only = copy.deepcopy(baseline)
            bytes_only['decision_policy']['token_policy'] = (
                'bytes_only_if_changed'
            )
            self._run_transition(
                root,
                bytes_only,
                'byte-metric',
                'retained_specialized_value',
            )
            for role in ('A', 'C'):
                self._set_observation_scale(
                    self._bound_cycle_paths(root, baseline, role),
                    'task-benefit',
                    'tokens',
                )
            self._run_transition(
                root,
                bytes_only,
                'token-metric',
                'apparatus_inconclusive',
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, judge_drift = self._transition_fixture(
                root,
                target_grader_set_hash='sha256:' + '6' * 64,
            )
            self._run_transition(
                root,
                judge_drift,
                'judge-drift',
                'apparatus_inconclusive',
            )

    def test_metric_observation_and_stage_integrity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, baseline = self._transition_fixture(root)
            target = self._bound_cycle_paths(root, baseline, 'C')

            summary = json.loads(
                target['summary'].read_text(encoding='utf-8'),
            )
            summary['paired_metrics']['task-benefit']['lower'] = 0.6
            self._write_self_hashed(target['summary'], summary, 'summary_hash')
            self._run_transition(
                root,
                baseline,
                'invalid-bounds',
                'apparatus_inconclusive',
            )

            self._set_transition_evidence(
                target,
                task_benefit=0.45,
                native_value=0.45,
            )
            observations = json.loads(
                target['observations'].read_text(encoding='utf-8'),
            )
            metric = [
                item for item in observations['metrics']
                if item['metric_id'] == 'task-benefit'
            ][0]
            metric['values'].append(copy.deepcopy(metric['values'][0]))
            self._write_self_hashed(
                target['observations'],
                observations,
                'comparison_observations_hash',
            )
            self._run_transition(
                root,
                baseline,
                'duplicate-observation-case',
                'apparatus_inconclusive',
            )

            self._set_transition_evidence(
                target,
                task_benefit=0.45,
                native_value=0.45,
            )
            summary = json.loads(
                target['summary'].read_text(encoding='utf-8'),
            )
            retrieved = [
                item for item in summary['stage_summaries']
                if item['surface'] == 'skill_tool_access'
                and item['stage'] == 'retrieved'
            ][0]
            retrieved['passed'] = retrieved['eligible'] + 1
            self._write_self_hashed(target['summary'], summary, 'summary_hash')
            self._run_transition(
                root,
                baseline,
                'invalid-stage-counts',
                'apparatus_inconclusive',
            )

    def test_bridge_and_combined_modes(self) -> None:
        for judge_change in (False, True):
            with (
                self.subTest(judge_change=judge_change),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                _, bridge = self._bridge_transition_fixture(
                    root,
                    judge_change=judge_change,
                )
                report = self._run_transition(
                    root,
                    bridge,
                    'bridge',
                    'retained_specialized_value',
                )
                self.assertEqual(
                    ['A', 'B', 'C'],
                    report['comparability_checks'][0]['roles'],
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, combined = self._transition_fixture(
                root,
                target_execution_updates={'harness': 'target-harness'},
            )
            combined['decision_policy'].update({
                'mode': 'combined',
                'apparatus_change_fields': ['host_hash', 'harness_hash'],
            })
            report = self._run_transition(
                root,
                combined,
                'combined',
                'combined_model_harness_drift',
            )
            self.assertEqual(
                [],
                report['result']['classification_metric_ids'],
            )
