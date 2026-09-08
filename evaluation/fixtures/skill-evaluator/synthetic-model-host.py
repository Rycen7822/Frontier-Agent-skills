"""Offline semantic Host with complete captured observations and a counted judge."""
import contextlib
from hashlib import sha256
import io
import json
from pathlib import Path
import sys

source = Path(__file__).with_name('synthetic-host.py')
module = {}
exec(compile(source.read_text().rsplit('raise SystemExit(main())', 1)[0], str(source), 'exec'), module)
request = json.load(sys.stdin)
kind = request['envelope']['request_kind']
stream = io.StringIO()
with contextlib.redirect_stdout(stream):
    module['execute' if kind == 'execute_case' else 'probe'](request if kind != 'model_grade' else {**request, 'payload': {'strategy': 'offline'}})
lines = [json.loads(line) for line in stream.getvalue().splitlines()]
result = lines[-1]
if kind == 'execute_case':
    artifacts = {
        'host-observation.json': {'schema_version': 'codex-host-observation/2', 'lifecycle': None, 'terminal_status': 'completed', 'codex_status': 'completed', 'turn_ids': ['turn-1'], 'changed_paths': [], 'command_trace_complete': True, 'command_trace_overflow': False, 'workspace_evidence_complete': True, 'workspace_evidence_overflow': False},
        'workspace-evidence.json': {'schema_version': 'codex-workspace-evidence/1', 'complete': True, 'overflow': False, 'initial': [], 'turn_snapshots': [{'turn_id': 'turn-1', 'files': []}], 'final': [], 'diff': ''},
        'command-trace.json': {'schema_version': 'codex-command-trace/2', 'complete': True, 'overflow': False, 'items': []},
        'turn-answers.json': {'schema_version': 'codex-turn-answers/1', 'items': [{'turn_id': 'turn-1', 'content': 'Complete.'}]},
    }
    result['artifacts'] = [module['artifact'](name, value) for name, value in artifacts.items()]
    answer = b'Complete.'
    Path('final-answer.md').write_bytes(answer)
    result['artifacts'].append({'path': 'workspace/final-answer.md', 'digest': 'sha256:' + sha256(answer).hexdigest(), 'encoding': 'utf-8'})
    result['assertions'] = [{'claim': 'Captured complete offline observations.', 'locally_verifiable': True, 'artifact': result['artifacts'][0]}]
elif kind == 'model_grade':
    batch = request['payload']['blinded_input']
    output = {'batch_id': batch['batch_id'], 'items': [{'item_id': item['item_id'], 'checks': [{'id': check['id'], 'pass': True, 'notes': 'offline fixture', 'uncertainty': 'low'} for check in item['checks']]} for item in batch['items']]}
    result['artifacts'] = [module['artifact']('judgment.json', output)]
    result['assertions'] = []
    result['usage'] = {'pricing_identity': 'fixture-pricing', 'records': [{'principal_id': 'grader-model-grader', 'turn_id': None, 'phase': 'model-grade', 'call_id': 'grade', 'input_tokens': 200, 'output_tokens': 10, 'cache_read_tokens': 0, 'cache_write_tokens': 0, 'queue_ms': 0, 'runtime_ms': 1, 'tool_calls': 0, 'retries': 0, 'rework': 0, 'network_calls': 1, 'residue_count': 0, 'requested_effort': 1, 'effective_effort': 1}]}
if '--roles' in sys.argv:
    records = result['usage']['records']
    result['usage'].pop('pricing_identity', None)
    role = 'judge' if kind == 'model_grade' else 'task'
    result['usage']['principal_identities'] = [{'principal_id': principal, 'role': role, 'model': 'fixture-judge' if role == 'judge' else 'fixture-model', 'pricing_identity': 'judge-price' if role == 'judge' else 'fixture-pricing'} for principal in sorted({record['principal_id'] for record in records})]
for value in lines[:-1]:
    module['emit'](value)
module['emit'](result)
