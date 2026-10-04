"""Two offline acceptance flows through the existing Scheduler / Request / Run path."""
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_phase1 import Phase1Tests
from app import main
from app.db import RequestQueue, Resource, Session, now
from app.workspace import safe_read, sha


def run():
    Phase1Tests.setUpClass()
    client = Phase1Tests.client
    try:
        def post(path, body):
            response = client.post(path, json=body)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        def wait(probe, timeout=10):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                value = probe()
                if value:
                    return value
                time.sleep(.03)
            raise AssertionError('Scheduler acceptance flow timed out')

        category = post('/api/categories', {'name': 'Queue acceptance'})
        work = post('/api/works', {'name': 'Queue acceptance', 'category_id': category['id']})
        prefix = '/api/works/' + work['id']
        upload = client.post(prefix + '/sources', files={'file': ('reference.md', b'ORIGINAL INPUT', 'text/markdown')})
        assert upload.status_code == 201, upload.text
        source = upload.json()
        with Session() as db:
            db.add(Resource(id='queue-resource', work_id=work['id'], category_id=category['id'],
                kind='NOTE', scope='WORK', title='Captured Resource', content='ORIGINAL RESOURCE',
                sha256=sha(b'ORIGINAL RESOURCE'), default_include=True))
            db.commit()
        first = post(prefix + '/runs', {'instruction': 'Run A HOLD', 'context_ids': []})
        wait(lambda: main.runner.gateway.handles.get(first['id']))
        queued = post(prefix + '/request-queue', {'instruction': 'Run B after success',
            'condition': 'AFTER_RUN_SUCCEEDED', 'predecessor_run_id': first['id'],
            'context_ids': [source['id']]})
        assert queued['status'] == 'PENDING' and queued['run_id'] is None
        assert queued['execution_profile']['reasoning'] == 'low'
        assert all('data' not in s for s in queued['context_config']['snapshots'])
        # Settings are frozen; selected input references are hash-checked at dispatch.
        updated = client.put('/api/execution-settings/defaults/WORK/' + work['id'], json={'reasoning': 'high'})
        assert updated.status_code == 200, updated.text
        scheduled = post(prefix + '/request-queue', {'instruction': 'Scheduled ordinary Request',
            'condition': 'AT_TIME', 'due_at': (now() + timedelta(seconds=1)).isoformat()})
        assert scheduled['status'] == 'PENDING' and scheduled['run_id'] is None
        dashboard = client.get('/api/operations/dashboard?work_id=' + work['id']).json()
        assert {queued['id'], scheduled['id']}.issubset({q['id'] for q in dashboard['scheduled']['items'] if q['entity_type'] == 'REQUEST_QUEUE'})
        main.runner.gateway.handles[first['id']]['steer'] = 'Finish A'

        def triggered(key):
            job = next(q for q in client.get(prefix + '/request-queue').json() if q['id'] == key)
            return job if job['run_id'] else None

        second = wait(lambda: triggered(queued['id']))
        detail = wait(lambda: (d if (d := client.get('/api/runs/' + second['run_id']).json())['run']['status'] == 'COMPLETED' else None))
        first_detail = client.get('/api/runs/' + first['id']).json()
        assert first_detail['run']['status'] == 'COMPLETED'
        assert detail['run']['started_at'] >= first_detail['run']['completed_at']
        assert detail['request']['instruction'] == 'Run B after success'
        assert detail['run']['execution_profile']['reasoning'] == 'low'
        files = json.loads(detail['run']['manifest'])['files']
        captured = {f['source_type']: safe_read(Path(f['snapshot_root']), f['snapshot_path']) for f in files}
        assert captured['SOURCE'] == b'ORIGINAL INPUT'
        assert captured['RESOURCE'] == b'ORIGINAL RESOURCE'
        assert len(client.get('/api/requests/' + queued['request_id']).json()['runs']) == 1
        print('PASS: Run A -> AFTER_RUN_SUCCEEDED B -> A completes -> B automatically starts with captured inputs/settings', flush=True)

        timed = wait(lambda: triggered(scheduled['id']))
        final = wait(lambda: (d if (d := client.get('/api/runs/' + timed['run_id']).json())['run']['status'] == 'COMPLETED' else None))
        assert final['run']['started_at'] >= scheduled['due_at']
        assert final['request']['instruction'] == 'Scheduled ordinary Request'
        with Session() as db:
            assert db.get(RequestQueue, scheduled['id']).status == 'TRIGGERED'
        assert len(client.get('/api/requests/' + scheduled['request_id']).json()['runs']) == 1
        print('PASS: one AT_TIME ordinary Request starts automatically at its scheduled time', flush=True)
    finally:
        Phase1Tests.tearDownClass()


if __name__ == '__main__':
    run()
