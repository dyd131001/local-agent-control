"""Offline acceptance and failure-boundary tests. No account or model required."""
import asyncio
import atexit
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = tempfile.TemporaryDirectory(prefix="control-center-tests-")
atexit.register(ROOT.cleanup)
WORKSPACES = tempfile.TemporaryDirectory(prefix="control-center-workspaces-")
atexit.register(WORKSPACES.cleanup)
os.environ["CONTROL_CENTER_ROOT"] = ROOT.name
os.environ["CONTROL_CENTER_STATE"] = str(Path(ROOT.name) / ".control-center-state")
os.environ["CONTROL_CENTER_WORKSPACE_ROOT"] = WORKSPACES.name
os.environ["CONTROL_CENTER_RUNTIME"] = str(Path(ROOT.name) / "runtime")
from fastapi.testclient import TestClient
from app import main
from app.db import Artifact, Event, Instruction, Request, Run, Session, Source, Work, now
from app.runner import Runner
from app.workspace import collect_artifacts, safe_read, sha, ident, provision_work, work_dir
from app.db import dump


def legacy_work(category_id, name='Legacy Work'):
    """Existing Phase 1/2 regression fixtures retain their original layout."""
    with Session() as db:
        work_id = ident('work')
        work = Work(id=work_id, category_id=category_id, name=name, description='',
                    path=str(work_dir(category_id, work_id)), storage_layout='LEGACY')
        db.add(work); db.flush(); provision_work(work)
        work.provision_state='READY'; db.commit()
        return dump(work)


class FakeGateway:
    def __init__(self):
        self.handles, self.threads = {}, {}
        self.login_state = {"status": "idle"}
        self.counter = 0
    async def open(self): pass
    async def close(self): self.handles.clear()
    async def account(self): return {"connected": True, "type": "chatgpt"}
    async def models(self): return [{"id": "runtime-model", "label": "Runtime model", "default": True, "reasoning": ["low", "high"], "default_reasoning": "low"}]
    async def thread(self, cwd, model, thread_id=None, **kwargs):
        self.counter += 1
        tid = thread_id or f"thread-{self.counter}"
        self.threads.setdefault(tid, {"id": tid, "turns": []})["cwd"] = cwd
        return tid
    async def start_turn(self, run_id, thread_id, prompt, model, effort, **kwargs):
        self.counter += 1
        turn = {"id": f"turn-{self.counter}", "status": "inProgress", "final_text": ""}
        self.threads[thread_id]["turns"].append(turn)
        self.handles[run_id] = {"thread": thread_id, "turn": turn, "prompt": prompt, "interrupted": False}
        return {"thread_id": thread_id, "turn_id": turn["id"]}
    async def read_thread(self, tid): return self.threads[tid]
    async def steer(self, rid, text): self.handles[rid]["steer"] = text; return self.handles[rid]["turn"]["id"]
    async def interrupt(self, rid):
        if rid in self.handles: self.handles[rid]["interrupted"] = True; return True
        return False
    async def events(self, rid):
        h = self.handles[rid]
        yield {"type": "COMMAND_STARTED", "payload": {"item_id": "cmd", "command": "write deliverable"}}
        path = Path(self.threads[h["thread"]]["cwd"]) / "artifacts"
        (path / "result.md").write_text("# Result\n<script>alert(1)</script>\n")
        while "HOLD" in h["prompt"] and not h["interrupted"] and "steer" not in h:
            await asyncio.sleep(.01)
        await asyncio.sleep(.03)
        status = "interrupted" if h["interrupted"] else "failed" if "FAIL" in h["prompt"] else "completed"
        h["turn"].update(status=status, final_text=h.get("steer", "done"))
        yield {"type": "ACTIVITY", "payload": {"item_id": "final", "phase": "final_answer", "text": h["turn"]["final_text"]}}
        yield {"type": "terminal", "status": status, "error": None}


class Phase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.runner.gateway = FakeGateway()
        cls.client = TestClient(main.app)
        cls.client.__enter__()
        cls.client.get('/')
        cls.client.headers.update({'Origin': 'http://testserver', 'X-Control-Token': main.ensure_token()})
    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
    def setUp(self):
        c = self.client.post('/api/categories', json={'name': self.id()}).json()
        self.work = legacy_work(c['id'], 'Test Work')
    def start(self, instruction='Make a result', **extra):
        response = self.client.post(f"/api/works/{self.work['id']}/runs", json={'instruction': instruction, **extra})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()
    def wait(self, rid, active=False):
        for _ in range(400):
            detail = self.client.get('/api/runs/' + rid).json()
            status = detail['run']['status']
            if (active and status == 'RUNNING') or (not active and status not in {'CREATED','RUNNING'}): return detail
            time.sleep(.01)
        self.fail('Run did not reach expected state')

    def test_full_flow_and_resume(self):
        source = self.client.post(f"/api/works/{self.work['id']}/sources", files={'file':('notes.md', b'# Reference')}, data={'context':'true'}).json()
        run = self.start(context_ids=[source['id']])
        done = self.wait(run['id'])
        self.assertEqual(done['run']['status'], 'COMPLETED')
        manifest = json.loads(done['run']['manifest'])
        self.assertEqual(manifest['files'][0]['sha256'], sha(b'# Reference'))
        self.assertEqual(len(done['artifacts']), 1)
        artifact = done['artifacts'][0]
        preview = self.client.get('/api/artifacts/' + artifact['id'] + '/preview')
        self.assertEqual(preview.status_code, 200)
        self.assertNotIn('<script>', preview.text)
        self.assertIn('sandbox', preview.headers['content-security-policy'])
        resumed = self.client.post('/api/runs/' + run['id'] + '/resume', json={'instruction':'Continue', 'reasoning':'high'}).json()
        final = self.wait(resumed['id'])['run']
        self.assertEqual(final['thread_id'], done['run']['thread_id'])
        self.assertNotEqual(final['turn_id'], done['run']['turn_id'])
        self.assertNotEqual(final['request_id'], done['run']['request_id'])
        self.assertEqual(final['parent_run_id'], run['id'])
        self.assertEqual(self.client.get('/api/runs/' + run['id']).json()['run']['status'], 'COMPLETED')

    def test_steer_and_cancel_partial(self):
        run = self.start('HOLD')
        self.wait(run['id'], active=True)
        steer = self.client.post('/api/runs/' + run['id'] + '/steer', json={'instruction':'steered result'})
        self.assertEqual(steer.json()['delivery'], 'ACCEPTED')
        self.assertEqual(self.wait(run['id'])['run']['final_text'], 'steered result')
        run = self.start('HOLD')
        self.wait(run['id'], active=True)
        self.client.post('/api/runs/' + run['id'] + '/cancel')
        done = self.wait(run['id'])
        self.assertEqual(done['run']['status'], 'CANCELLED')
        self.assertTrue(done['artifacts'][0]['partial'])
        self.assertEqual(self.client.post('/api/runs/' + run['id'] + '/steer', json={'instruction':'late'}).status_code, 409)

    def test_queued_cancel(self):
        held = self.start('HOLD'); self.wait(held['id'], active=True)
        queued = self.start()
        cancelled = self.client.post('/api/runs/' + queued['id'] + '/cancel').json()
        self.assertEqual(cancelled['status'], 'CANCELLED')
        self.assertIsNone(cancelled['turn_id'])
        self.client.post('/api/runs/' + held['id'] + '/cancel'); self.wait(held['id'])

    def test_idempotency_retry_and_sse_replay(self):
        path = f"/api/works/{self.work['id']}/runs"
        headers = {'Idempotency-Key':'one-command'}
        first = self.client.post(path, json={'instruction':'result'}, headers=headers).json()
        second = self.client.post(path, json={'instruction':'result'}, headers=headers).json()
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.client.post(path, json={'instruction':'changed'}, headers=headers).status_code, 409)
        done = self.wait(first['id'])
        retried = self.client.post('/api/requests/' + first['request_id'] + '/retry', json={}).json()
        retry_done = self.wait(retried['id'])
        self.assertEqual(retried['request_id'], first['request_id'])
        self.assertNotEqual(retry_done['run']['thread_id'], done['run']['thread_id'])
        cursor = done['events'][1]['id']
        stream = self.client.get('/api/runs/' + first['id'] + '/events', headers={'Last-Event-ID':str(cursor)}).text
        ids = [int(line[4:]) for line in stream.splitlines() if line.startswith('id: ')]
        self.assertTrue(ids and all(i > cursor for i in ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_artifact_modified_missing_and_symlink(self):
        done = self.wait(self.start()['id'])
        a = done['artifacts'][0]; path = Path(self.work['path']) / a['relative_path']
        path.write_text('tampered')
        self.assertEqual(self.client.get('/api/artifacts/' + a['id']).json()['availability'], 'MODIFIED')
        self.assertEqual(self.client.get('/api/artifacts/' + a['id'] + '/preview').status_code, 410)
        path.unlink()
        self.assertEqual(self.client.get('/api/artifacts/' + a['id']).json()['availability'], 'MISSING')
        path.symlink_to(Path(ROOT.name) / '.control-center-state' / 'control.db')
        self.assertEqual(self.client.get('/api/artifacts/' + a['id'] + '/download').status_code, 410)

    def test_security_and_validation(self):
        self.assertEqual(self.client.post('/api/categories', json={'name':'x'}, headers={'Origin':'https://evil.test'}).status_code, 403)
        self.assertEqual(self.client.get('/api/dashboard', headers={'Host':'evil.test'}).status_code, 403)
        self.assertEqual(self.client.post('/api/categories', json={'name':'x'}, headers={'X-Control-Token':''}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/works/{self.work['id']}/runs", json={'instruction':'x','context_ids':['other-work']}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/works/{self.work['id']}/runs", json={'instruction':'x','reasoning':'ultra'}).status_code, 400)
        with self.assertRaises(ValueError): safe_read(Path(ROOT.name), '../secret')
        self.client.patch('/api/works/' + self.work['id'], json={'archived':True})
        self.assertEqual(self.client.post(f"/api/works/{self.work['id']}/runs", json={'instruction':'x'}).status_code, 409)

    def test_changed_context_fails_preparation(self):
        source = self.client.post(f"/api/works/{self.work['id']}/sources", files={'file':('notes.txt', b'original')}).json()
        (Path(self.work['path']) / source['relative_path']).write_text('changed')
        done = self.wait(self.start(context_ids=[source['id']])['id'])
        self.assertEqual(done['run']['status'], 'FAILED')
        self.assertIsNone(done['run']['turn_id'])
        self.assertEqual(json.loads(done['run']['error'])['code'], 'PREPARATION_FAILED')

    def test_failure_preserves_partial(self):
        done = self.wait(self.start('FAIL')['id'])
        self.assertEqual(done['run']['status'], 'FAILED')
        self.assertTrue(done['artifacts'][0]['partial'])

    def test_recovery_terminal_and_copy_before_commit(self):
        done = self.wait(self.start()['id']); rid = done['run']['id']
        with Session() as db:
            db.query(Artifact).filter_by(run_id=rid).delete()
            db.query(Event).filter_by(run_id=rid, type='RUN_COMPLETED').delete()
            row = db.get(Run, rid); row.status, row.phase = 'RUNNING', 'FINALIZING'
            db.commit()
        self.client.portal.call(main.runner.recover)
        recovered = self.client.get('/api/runs/' + rid).json()
        self.assertEqual(recovered['run']['status'], 'COMPLETED')
        self.assertEqual(len(recovered['artifacts']), 1)
        self.client.portal.call(main.runner.recover)
        self.assertEqual(len([e for e in self.client.get('/api/runs/' + rid).json()['events'] if e['type'] == 'RUN_COMPLETED']), 1)

    def test_unknown_outcome_blocks_until_proven(self):
        done = self.wait(self.start()['id']); rid = done['run']['id']
        with Session() as db:
            row = db.get(Run, rid); row.status, row.phase, row.runtime_status = 'RUNNING', 'EXECUTING', None
            db.commit()
        turn = main.runner.gateway.threads[done['run']['thread_id']]['turns'][0]
        turn['status'] = 'inProgress'
        self.client.portal.call(main.runner.recover)
        unknown = self.client.get('/api/runs/' + rid).json()['run']
        self.assertTrue(unknown['safety_block'])
        self.assertEqual(self.client.post(f"/api/works/{self.work['id']}/runs", json={'instruction':'x'}).status_code, 409)
        turn['status'] = 'completed'
        self.assertEqual(self.client.post('/api/runs/' + rid + '/reconcile').json()['run']['status'], 'COMPLETED')

    def test_duplicate_backend_lock(self):
        other = Runner()
        with self.assertRaises(BlockingIOError): self.client.portal.call(other.start)

    def test_nested_artifacts_and_equal_bytes_preserved(self):
        root = Path(self.work['path']); workspace = root / 'runs/manual/workspace'
        (workspace / 'artifacts/a').mkdir(parents=True)
        (workspace / 'artifacts/b').mkdir()
        for folder in ('a','b'): (workspace / f'artifacts/{folder}/same.txt').write_text('same')
        artifacts = collect_artifacts(root, self.work['id'], 'manual', workspace)
        self.assertEqual(len(artifacts), 2)
        self.assertNotEqual(artifacts[0].relative_path, artifacts[1].relative_path)
        (workspace / 'artifacts/link').symlink_to(root)
        with self.assertRaises(ValueError): collect_artifacts(root, self.work['id'], 'manual', workspace)

if __name__ == '__main__': unittest.main()
