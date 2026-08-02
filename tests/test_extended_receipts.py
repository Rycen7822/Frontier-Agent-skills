from __future__ import annotations

from skill_evaluator_test_support import *  # noqa: F403


class TestExtendedReceipts(SkillEvaluatorTestCase):  # noqa: F405
    def _runtime_v4_bundle(self, root: Path) -> dict[str, object]:
        paths = materialize_v5_contract_fixture(root)
        plan_path = root / 'execution-plan.json'
        compiled = self.run_cmd(
            'scripts/compile_eval_plan.py',
            str(paths['spec']),
            str(paths['scenarios']),
            str(paths['host']),
            '--output', str(plan_path),
        )
        self.assertEqual(
            compiled.returncode, 0, compiled.stdout + compiled.stderr,
        )
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        entry = plan['entries'][0]
        index_path = (
            root / plan['artifacts']['root']
            / plan['artifacts']['index_relpath']
        )
        ran = self.run_cmd(
            'scripts/run_eval_plan.py',
            str(plan_path),
            '--index', str(index_path),
            '--entry-id', entry['entry_id'],
            '--new-attempt-budget', '1',
        )
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        row = json.loads(index_path.read_text(encoding='utf-8').strip())
        receipt_path = (
            root / plan['artifacts']['root'] / row['receipt']['path']
        )
        return {
            'paths': paths,
            'plan_path': plan_path,
            'plan': plan,
            'entry': entry,
            'index_path': index_path,
            'row': row,
            'receipt_path': receipt_path,
            'receipt': json.loads(receipt_path.read_text(encoding='utf-8')),
        }

    def test_receipt_v4_schema_allows_empty_protocol_only_for_resume_seal(
        self,
    ) -> None:
        validator = load_validator_module()
        registry = validator.load_v5_schema_registry()
        receipt = make_v5_schema_examples()['receipt-v4.schema.json']
        receipt['usage']['host_safety_review'] = {
            'capture_status': 'captured',
            'host_safety_review_count': 1,
            'host_safety_review_latency_ms': 9,
        }
        self.assertEqual(
            [],
            validator.validate_v5_schema(
                receipt, 'receipt-v4.schema.json', registry,
            ),
        )
        receipt['usage']['host_safety_review'][
            'host_safety_review_count'
        ] = -1
        self.assertIn(
            'schema.minimum',
            {
                item['code']
                for item in validator.validate_v5_schema(
                    receipt, 'receipt-v4.schema.json', registry,
                )
            },
        )
        receipt['usage']['host_safety_review'][
            'host_safety_review_count'
        ] = 1
        receipt['host_protocol']['requests'] = []
        receipt['host_protocol']['results'] = []
        normal = validator.validate_v5_schema(
            receipt, 'receipt-v4.schema.json', registry,
        )
        self.assertIn('schema.minItems', {item['code'] for item in normal})

        receipt['run']['completion_origin'] = 'resume_seal'
        receipt['run']['valid'] = False
        receipt['run']['terminal'] = 'interrupted'
        receipt['run']['error'] = 'apparatus interrupted'
        self.assertEqual(
            [],
            validator.validate_v5_schema(
                receipt, 'receipt-v4.schema.json', registry,
            ),
        )

    def test_runtime_receipt_v4_and_index_v2_bind_exact_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._runtime_v4_bundle(Path(tmp))
            evidence = load_evidence_io_module()
            validator = load_validator_module()
            receipt = bundle['receipt']
            plan = bundle['plan']
            entry = bundle['entry']
            row = bundle['row']
            receipt_path = bundle['receipt_path']

            self.assertEqual(
                [],
                validator.validate_v5_schema(
                    receipt,
                    'receipt-v4.schema.json',
                    validator.load_v5_schema_registry(),
                ),
            )
            self.assertTrue(evidence.verify_self_hash(receipt, 'receipt_hash'))
            self.assertTrue(evidence.verify_self_hash(
                receipt['attempt_start'], 'marker_hash',
            ))
            self.assertEqual(plan['plan_hash'], row['plan_hash'])
            self.assertEqual(entry['entry_id'], row['entry_id'])
            self.assertEqual(
                evidence.file_sha256(receipt_path),
                row['receipt']['sha256'],
            )
            evidence.verify_artifact_records(
                receipt['artifacts'],
                receipt_path.parent,
                label='runtime receipt',
            )
            self.assertEqual(
                plan['host_manifest_hash'],
                receipt['provenance']['host_manifest_hash'],
            )
            self.assertEqual(
                {
                    'capture_status': 'captured',
                    'host_safety_review_count': 1,
                    'host_safety_review_latency_ms': 9.0,
                },
                receipt['usage']['host_safety_review'],
            )
            self.assertEqual(
                entry['treatment_hash'],
                receipt['provenance']['treatment_hash'],
            )
            self.assertTrue({'score', 'pass', 'usage'}.isdisjoint(row))

    def test_resume_rejects_rehashed_v3_protection_tamper(self) -> None:
        mutations = (
            ('package', lambda receipt: receipt['provenance'].__setitem__(
                'package_hash', 'sha256:' + '0' * 64,
            )),
            ('catalog', lambda receipt: receipt['provenance'].__setitem__(
                'catalog_hash', 'sha256:' + '0' * 64,
            )),
            ('treatment', lambda receipt: receipt['provenance'].__setitem__(
                'treatment_hash', 'sha256:' + '0' * 64,
            )),
            ('context', lambda receipt: receipt['context_usage'].__setitem__(
                'controlled_core_bytes', 1,
            )),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                bundle = self._runtime_v4_bundle(Path(tmp))
                evidence = load_evidence_io_module()
                receipt = bundle['receipt']
                mutate(receipt)
                receipt['receipt_hash'] = evidence.canonical_self_hash(
                    receipt, 'receipt_hash',
                )
                receipt_path = bundle['receipt_path']
                receipt_path.write_bytes(evidence.canonical_json_bytes(receipt))
                row = bundle['row']
                row['receipt']['sha256'] = evidence.file_sha256(receipt_path)
                index_path = bundle['index_path']
                index_path.write_bytes(
                    evidence.canonical_json_bytes(row) + b'\n',
                )
                before = (receipt_path.read_bytes(), index_path.read_bytes())

                resumed = self.run_cmd(
                    'scripts/run_eval_plan.py',
                    str(bundle['plan_path']),
                    '--index', str(index_path),
                    '--entry-id', bundle['entry']['entry_id'],
                    '--resume',
                    '--new-attempt-budget', '0',
                )
                self.assertEqual(
                    resumed.returncode, 2,
                    resumed.stdout + resumed.stderr,
                )
                self.assertEqual(before, (
                    receipt_path.read_bytes(), index_path.read_bytes(),
                ))

    def test_shared_evidence_io_hash_path_atomic_and_locator_contracts(
        self,
    ) -> None:
        evidence = load_evidence_io_module()
        analyzer = load_analyzer_module()
        validator = load_validator_module()
        value = {'z': 2, 'é': ['line', None], 'a': 1}
        expected_bytes = '{"a":1,"z":2,"é":["line",null]}'.encode()
        expected_hash = 'sha256:' + hashlib.sha256(expected_bytes).hexdigest()
        self.assertEqual(expected_bytes, evidence.canonical_json_bytes(value))
        self.assertEqual(expected_hash, evidence.canonical_sha256(value))
        self.assertEqual(expected_hash, analyzer.canonical_sha256(value))
        self.assertEqual(expected_hash, validator.canonical_sha256(value))
        with self.assertRaises(ValueError):
            evidence.canonical_json_bytes({'bad': float('nan')})
        for reference in ('/absolute', '../escape', 'a/../escape', r'a\escape'):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                evidence.normalize_relative_path(reference, 'fixture')

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / 'record.json'
            text_path = root / 'trace.txt'
            binary_path = root / 'capture.bin'
            evidence.atomic_write_json(json_path, {'b': 2, 'a': 1})
            with self.assertRaises(FileExistsError):
                evidence.atomic_write_json(json_path, {'a': 2})
            text_path.write_text('alpha\nbeta\n', encoding='utf-8')
            binary_path.write_bytes(b'\x00\x01\x02')
            verified = evidence.verify_artifact_records([
                evidence.artifact_record(
                    text_path, root, encoding='utf-8',
                ),
                evidence.artifact_record(
                    json_path, root, encoding='utf-8',
                ),
                evidence.artifact_record(
                    binary_path, root, encoding='binary',
                ),
            ], root)
            for locator in (
                {
                    'kind': 'text_lines',
                    'artifact': 'trace.txt',
                    'start_line': 1,
                    'end_line': 2,
                },
                {
                    'kind': 'json_pointer',
                    'artifact': 'record.json',
                    'json_pointer': '/a',
                },
                {
                    'kind': 'byte_range',
                    'artifact': 'capture.bin',
                    'start_byte': 1,
                    'end_byte_exclusive': 3,
                },
            ):
                evidence.validate_locator(locator, verified)
            with self.assertRaises(ValueError):
                evidence.validate_locator({
                    'kind': 'byte_range',
                    'artifact': 'capture.bin',
                    'start_byte': 3,
                    'end_byte_exclusive': 4,
                }, verified)

    def test_analyzer_rejects_removed_v3_reader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = write_receipt_bundle(root)
            result = self.call_cli(
                'scripts/analyze_runs.py',
                str(bundle['index']),
                '--spec', str(bundle['spec']),
                '--json', str(root / 'summary-v4.json'),
                '--failure-index', str(root / 'failures-v1.json'),
            )
            self.assertEqual(2, result.returncode)
            self.assertFalse((root / 'summary-v4.json').exists())
            self.assertFalse((root / 'failures-v1.json').exists())
