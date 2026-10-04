"""Offline review evidence. Every model execution uses a deterministic FakeGateway."""
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from alembic import command as alembic_command
from alembic.config import Config
from test_phase1 import ROOT, FakeGateway, legacy_work
from app import main
from app.db import (Artifact, ArtifactRelation, Event, Run, Session, TaskRun, TaskRunOutput, WorkflowRun, Work)
from app.workflow import COMMAND_LOCK, validate_graph
from app.workspace import sha
from app.git_workspace import git


class WorkflowFake(FakeGateway):
    def __init__(self):
        super().__init__()
        self.counter = 10000  # Distinct from Phase 1 fake Runtime IDs in the shared fixture DB.
        self.started, self.active, self.peak, self.calls, self.failed_once = [], set(), 0, {}, set()
        self.release = None
    async def models(self):
        return [{"id": m, "label": m, "default": m == "runtime-model", "reasoning": ["low", "high"], "default_reasoning": "low"}
                for m in ("runtime-model", "mock-astra", "mock-luna")]
    async def thread(self, cwd, model, thread_id=None, **kwargs):
        return await super().thread(cwd, model, thread_id)
    async def fork_thread(self, source, cwd, model, settings, rules, **kwargs):
        tid = await self.thread(cwd, model)
        self.threads[tid]["turns"] = [dict(t) for t in self.threads[source]["turns"]]
        self.threads[tid]["forked_from"] = source
        return tid
    async def start_turn(self, rid, tid, prompt, model, effort, **kwargs):
        result = await super().start_turn(rid, tid, prompt, model, effort)
        self.started.append(rid)
        self.active.add(rid)
        self.peak = max(self.peak, len(self.active))
        self.calls[rid] = {"thread_id": tid, "prompt": prompt, "model": model, "effort": effort}
        return result
    async def events(self, rid):
        h = self.handles[rid]
        with Session() as db:
            run = db.get(Run, rid)
            manifest = json.loads(run.manifest)
            task = db.query(TaskRun).filter_by(run_id=rid).first()
        text = manifest["instruction"]
        if self.release and "BARRIER" in text:
            await self.release.wait()
        while "HOLD" in text and not h["interrupted"]:
            await asyncio.sleep(.01)
        root = Path(manifest["output_root"])
        if "OMIT" not in text:
            for o in manifest.get("output_rule", [{"path": "result.md"}]):
                if o.get("system"):
                    continue
                target = root / o["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"Output {rid}\n")
        if manifest.get("workspace_mode") == "GIT_WORKTREE":
            (Path(manifest["cwd"]) / "code.txt").write_text(f"changed {rid}\n")
            (Path(manifest["cwd"]) / "new.txt").write_text("new file\n")
        status = "interrupted" if h["interrupted"] else "completed"
        if "FAIL_ONCE" in text and task.task_definition_id not in self.failed_once:
            self.failed_once.add(task.task_definition_id)
            status = "failed"
        if text == "FAIL":
            status = "failed"
        await asyncio.sleep(.01)
        self.active.discard(rid)
        h["turn"].update(status=status, final_text="DONE_PRIVATE_CONVERSATION")
        yield {"type": "ACTIVITY", "payload": {"item_id": "answer", "phase": "final_answer", "text": "DONE_PRIVATE_CONVERSATION"}}
        yield {"type": "terminal", "status": status, "error": None}


class Phase2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = WorkflowFake()
        main.runner.gateway = cls.fake
        cls.client = TestClient(main.app)
        cls.client.__enter__()
        cls.client.get('/')
        cls.client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None,None,None)
    def setUp(self):
        c = self.client.post('/api/categories', json={'name':self.id()[-70:]}).json()
        self.work = legacy_work(c['id'], 'Review')
        main.runner.max_parallel_tasks = 3
        self.fake.peak = 0
    def tearDown(self):
        self.fake.release = None
        for wr in self.client.get(f"/api/works/{self.work['id']}/workflow-runs").json():
            if wr['status'] in {'CREATED','RUNNING'}:
                self.client.post('/api/workflow-runs/'+wr['id']+'/cancel')
                self.wait(wr['id'])
        with Session() as db:
            for run in db.query(Run).filter_by(safety_block=True):
                run.safety_block = False
            db.commit()
    def task(self, key, parents=(), instruction='write', model='mock-luna', path=None):
        return {'id':self.work['id']+'_'+key,'name':key,'instruction':instruction,'model':model,'reasoning':'high',
                'depends_on':[self.work['id']+'_'+p for p in parents],
                'output_rule':[{'output_key':'result','path':path or key+'.md','required':True}]}
    def chain(self, instructions=None):
        ins = instructions or {}
        tasks = [self.task('A', instruction=ins.get('A','write'), model='mock-astra'),
                 self.task('B',['A'],ins.get('B','write')), self.task('C',['A'],ins.get('C','write')),
                 self.task('D',['B','C'],ins.get('D','write'))]
        for t in tasks[1:]:
            t['input_rule'] = [{'input_key':'from_'+p.rsplit('_',1)[1], 'task_definition_id':p, 'output_key':'result'} for p in t['depends_on']]
        return tasks
    def define(self, tasks=None):
        response = self.client.post(f"/api/works/{self.work['id']}/workflows",json={'name':'Review Workflow','tasks':tasks or self.chain()})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()
    def start(self,wf,**body):
        response = self.client.post(f"/api/workflows/{wf['id']}/runs",json={'expected_revision':wf['revision'],**body})
        self.assertEqual(response.status_code,202,response.text)
        return response.json()['workflow_run']['id']
    def wait(self,rid,predicate=None):
        for _ in range(700):
            data=self.client.get('/api/workflow-runs/'+rid).json()
            if (predicate and predicate(data)) or (not predicate and data['workflow_run']['status'] not in {'CREATED','RUNNING'}):
                return data
            time.sleep(.01)
        self.fail('Workflow did not reach expected state: '+json.dumps(data))
    def current(self,data):
        return {t['task_definition_id'].rsplit('_',1)[1]:t for t in data['task_runs'] if t['is_current']}
    def barrier(self):
        async def set_release():
            self.fake.release=asyncio.Event()
        self.client.portal.call(set_release)
    def release(self):
        async def release(): self.fake.release.set()
        self.client.portal.call(release)

    def test_cycle_validation_and_definition_crud(self):
        tasks=self.chain()
        tasks[0]['depends_on']=[tasks[-1]['id']]
        response=self.client.post(f"/api/works/{self.work['id']}/workflows",json={'name':'Cycle','tasks':tasks})
        self.assertEqual(response.status_code,422)
        wf=self.define()
        response=self.client.put('/api/workflows/'+wf['id'],json={'name':'Updated','tasks':wf['tasks'],'expected_revision':wf['revision']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['revision'],2)
        stale=self.client.put('/api/workflows/'+wf['id'],json={'name':'Stale','tasks':wf['tasks'],'expected_revision':1})
        self.assertEqual(stale.status_code,409)
        self.assertEqual(self.client.delete('/api/workflows/'+wf['id']).status_code,200)
        self.assertEqual(self.client.post('/api/workflows/'+wf['id']+'/runs',json={}).status_code,409)

    def test_handoff_lineage_model_selection_and_parallel_barrier(self):
        self.barrier()
        wf=self.define(self.chain({'B':'BARRIER','C':'BARRIER'}));rid=self.start(wf)
        held=self.wait(rid,lambda d:sum(t['status']=='RUNNING' for t in d['task_runs'])==2)
        cur=self.current(held)
        self.assertEqual(cur['A']['status'],'COMPLETED')
        self.assertEqual(cur['D']['status'],'BLOCKED')
        self.assertEqual(self.fake.peak,2)
        self.release();done=self.wait(rid);cur=self.current(done)
        self.assertEqual(done['workflow_run']['status'],'COMPLETED',done)
        for name in ['A','B','C','D']:
            call=self.fake.calls[cur[name]['run_id']]
            self.assertEqual(call['model'],'mock-astra' if name=='A' else 'mock-luna')
            self.assertEqual(call['effort'],'high')
            self.assertNotIn('DONE_PRIVATE_CONVERSATION',call['prompt'])
        self.assertEqual(len({t['run']['thread_id'] for t in cur.values()}),4)
        self.assertEqual(len(cur['D']['inputs']),2)
        manifest=json.loads(cur['D']['run']['manifest'])
        for f in manifest['files']:
            if f.get('artifact_id'):
                self.assertEqual(sha((Path(self.work['path'])/f['snapshot_path']).read_bytes()),f['sha256'])
                self.assertIn(str(Path(self.work['path'])/f['snapshot_path']),manifest['prompt'])
        lineage=self.client.get('/api/artifacts/'+cur['A']['outputs'][0]['artifact']['id']+'/lineage').json()
        self.assertEqual(sum(r['kind']=='INPUT' for r in lineage),2)
        self.assertEqual(sum(r['kind']=='DERIVED_FROM' for r in lineage),2)
        self.assertTrue({'WORKFLOW_STARTED','TASK_READY','TASK_COMPLETED','ARTIFACT_HANDOFF','ARTIFACT_CREATED','WORKFLOW_COMPLETED'}.issubset({e['type'] for e in done['events']}))

    def test_limit_one_keeps_other_ready_task_queued(self):
        main.runner.max_parallel_tasks=1;self.barrier()
        wf=self.define([self.task('A',instruction='BARRIER'),self.task('B',instruction='BARRIER')]);rid=self.start(wf)
        held=self.wait(rid,lambda d:any(t['status']=='RUNNING' for t in d['task_runs']))
        self.assertEqual(sum(t['status']=='RUNNING' for t in held['task_runs']),1)
        self.assertEqual(sum(t['status']=='QUEUED' for t in held['task_runs']),1)
        self.assertEqual(self.fake.peak,1)
        self.release();self.assertEqual(self.wait(rid)['workflow_run']['status'],'COMPLETED')

    def test_missing_contract_blocks_downstream(self):
        wf=self.define(self.chain({'A':'OMIT'}));done=self.wait(self.start(wf));cur=self.current(done)
        self.assertEqual(cur['A']['status'],'FAILED')
        self.assertEqual(cur['A']['run']['runtime_status'],'completed')
        self.assertEqual(json.loads(cur['A']['error'])['code'],'OUTPUT_CONTRACT_FAILED')
        self.assertTrue(all(cur[k]['status']=='BLOCKED' and cur[k]['run_id'] is None for k in ['B','C','D']))

    def test_retry_preserves_attempts_and_reopens_workflow(self):
        wf=self.define(self.chain({'B':'FAIL_ONCE'}));rid=self.start(wf);failed=self.wait(rid);cur=self.current(failed)
        self.assertEqual(failed['workflow_run']['status'],'PARTIAL')
        old=cur['B'];headers={'Idempotency-Key':'retry-once'}
        response=self.client.post('/api/task-runs/'+old['id']+'/retry',headers=headers)
        self.assertEqual(response.status_code,202,response.text)
        replay=self.client.post('/api/task-runs/'+old['id']+'/retry',headers=headers)
        self.assertEqual(replay.json()['id'],response.json()['id'])
        done=self.wait(rid);new=self.current(done)['B']
        self.assertEqual(done['workflow_run']['status'],'COMPLETED',done)
        self.assertEqual(new['attempt_number'],2)
        self.assertNotEqual(new['run_id'],old['run_id'])
        self.assertNotEqual(new['run']['thread_id'],old['run']['thread_id'])
        prior=next(t for t in done['task_runs'] if t['id']==old['id']);self.assertEqual(prior['status'],'FAILED')
        self.assertEqual(new['inputs'][0]['source_artifact_id'],old['inputs'][0]['source_artifact_id'])

    def test_branch_preserves_original_and_records_revision(self):
        wf=self.define([self.task('A')]);rid=self.start(wf);original=self.wait(rid);source=self.current(original)['A'];artifact=source['outputs'][0]['artifact']
        body={'instruction':'different direction','model':'mock-astra','source_output_keys':['result'],'revision_of':{'result':artifact['id']}}
        result=self.client.post('/api/task-runs/'+source['id']+'/branch',json=body)
        self.assertEqual(result.status_code,202,result.text)
        branched=self.wait(result.json()['workflow_run']['id']);new=self.current(branched)['A']
        self.assertEqual(branched['workflow_run']['status'],'COMPLETED',branched)
        self.assertNotEqual(source['run_id'],new['run_id'])
        self.assertNotEqual(source['outputs'][0]['artifact']['id'],new['outputs'][0]['artifact']['id'])
        again=self.client.get('/api/workflow-runs/'+rid).json()
        self.assertEqual(again['task_runs'],original['task_runs'])
        relations=self.client.get('/api/artifacts/'+artifact['id']+'/lineage').json()
        self.assertTrue(any(r['kind']=='REVISION_OF' for r in relations))

    def test_fork_adapter_new_thread(self):
        wf=self.define([self.task('A')]);source=self.current(self.wait(self.start(wf)))['A']
        response=self.client.post('/api/task-runs/'+source['id']+'/branch',json={'instruction':'alternative','history_mode':'FORK'})
        self.assertEqual(response.status_code,202,response.text)
        done=self.wait(response.json()['workflow_run']['id']);new=self.current(done)['A']
        self.assertEqual(done['workflow_run']['status'],'COMPLETED',done)
        self.assertEqual(self.fake.threads[new['run']['thread_id']]['forked_from'],source['run']['thread_id'])

    def test_library_and_template_cross_work(self):
        wf=self.define([self.task('A')]);source=self.current(self.wait(self.start(wf)))['A'];artifact=source['outputs'][0]['artifact']
        other=self.client.post('/api/works',json={'category_id':self.work['category_id'],'name':'Other'}).json()
        self.assertEqual(self.client.get('/api/library?work_id='+other['id']).json(),[])
        for scope in ['WORK','CATEGORY','GLOBAL']:
            response=self.client.post('/api/artifacts/'+artifact['id']+'/publish',json={'scope':scope})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(bool(self.client.get('/api/library?work_id='+other['id']).json()),scope!='WORK')
        response=self.client.post('/api/works/'+other['id']+'/runs',json={'instruction':'reuse explicit Library input','artifact_ids':[artifact['id']]})
        self.assertEqual(response.status_code,202,response.text)
        for _ in range(700):
            consumed=self.client.get('/api/runs/'+response.json()['id']).json()['run']
            if consumed['status'] not in {'CREATED','RUNNING'}:
                break
            time.sleep(.01)
        self.assertEqual(consumed['status'],'COMPLETED')
        provided=json.loads(consumed['manifest'])['files']
        self.assertEqual([f['artifact_id'] for f in provided],[artifact['id']])
        self.assertEqual(sha((Path(provided[0]['snapshot_root'])/provided[0]['snapshot_path']).read_bytes()),artifact['sha256'])
        template=self.client.post('/api/workflows/'+wf['id']+'/templates',json={}).json()
        cloned=self.client.post('/api/workflow-templates/'+template['id']+'/clone',json={'target_work_id':other['id']})
        self.assertEqual(cloned.status_code,201,cloned.text)
        self.assertNotEqual(cloned.json()['tasks'][0]['id'],wf['tasks'][0]['id'])
        self.assertEqual(cloned.json()['work_id'],other['id'])

    def test_cancel_workflow_and_task_owned_api_guards(self):
        wf=self.define([self.task('A',instruction='HOLD'),self.task('B',instruction='HOLD')]);rid=self.start(wf)
        held=self.wait(rid,lambda d:sum(t['status']=='RUNNING' for t in d['task_runs'])==2)
        source=held['task_runs'][0]
        self.assertEqual(self.client.post('/api/requests/'+source['run']['request_id']+'/retry',json={}).status_code,409)
        self.assertEqual(self.client.post('/api/runs/'+source['run_id']+'/resume',json={'instruction':'continue'}).status_code,409)
        self.client.post('/api/workflow-runs/'+rid+'/cancel')
        done=self.wait(rid);self.assertEqual(done['workflow_run']['status'],'CANCELLED',done)
        self.assertTrue(all(t['status']=='CANCELLED' for t in done['task_runs']))

    def test_workflow_sse_replay(self):
        wf=self.define([self.task('A')]);rid=self.start(wf);done=self.wait(rid)
        cursor=done['events'][1]['id']
        text=self.client.get('/api/workflow-runs/'+rid+'/events',headers={'Last-Event-ID':str(cursor)}).text
        ids=[int(x) for x in re.findall(r'^id: (\d+)$',text,re.M)]
        self.assertTrue(ids and all(i>cursor for i in ids));self.assertEqual(ids,sorted(set(ids)))

    def test_retry_completes_all_inputs_after_partial_binding_failure(self):
        producer = self.task('Producer')
        producer['output_rule'] = [{'output_key':'one','path':'one.md'}, {'output_key':'two','path':'two.md'}]
        original = self.current(self.wait(self.start(self.define([producer]))))['Producer']
        artifacts = {o['output_key']:o['artifact'] for o in original['outputs']}
        lost = artifacts['two']; path = Path(self.work['path']) / lost['relative_path']; saved = path.read_bytes()
        self.barrier()
        root, consumer = self.task('Root',instruction='BARRIER'), self.task('Consumer',['Root'])
        consumer['input_rule'] = [{'input_key':key,'artifact_id':artifacts[key]['id']} for key in ['one','two']]
        rid = self.start(self.define([root,consumer]))
        self.wait(rid,lambda d:any(t['status']=='RUNNING' for t in d['task_runs']))
        path.unlink();self.client.get('/api/artifacts/'+lost['id'])
        self.release();failed=self.wait(rid);old=self.current(failed)['Consumer']
        self.assertEqual(old['status'],'FAILED');self.assertEqual(len(old['inputs']),1)
        path.write_bytes(saved);self.client.get('/api/artifacts/'+lost['id'])
        response=self.client.post('/api/task-runs/'+old['id']+'/retry');self.assertEqual(response.status_code,202,response.text)
        done=self.wait(rid);new=self.current(done)['Consumer']
        self.assertEqual(done['workflow_run']['status'],'COMPLETED',done)
        self.assertEqual({r['input_key'] for r in new['inputs']},{'one','two'})

    def test_completed_run_cannot_bypass_missing_contract_on_recovery(self):
        wf=self.define([self.task('A',instruction='OMIT')]);rid=self.start(wf);failed=self.wait(rid);task=self.current(failed)['A']
        with COMMAND_LOCK, Session() as db:
            run=db.get(Run,task['run_id']);attempt=db.get(TaskRun,task['id'])
            run.status,run.phase,run.runtime_status='COMPLETED','COMPLETED','completed'
            attempt.status,attempt.contract_report='QUEUED',None
            db.commit()
        from app.scheduler import tick
        tick()
        with Session() as db:
            self.assertNotEqual(db.get(TaskRun,task['id']).status,'COMPLETED')
        self.client.portal.call(main.runner.recover)
        recovered=self.wait(rid);self.assertEqual(self.current(recovered)['A']['status'],'FAILED')
        self.assertEqual(json.loads(self.current(recovered)['A']['error'])['code'],'OUTPUT_CONTRACT_FAILED')

    def test_completed_workflow_and_old_attempt_cannot_be_cancelled(self):
        wf=self.define([self.task('A',instruction='FAIL_ONCE')]);rid=self.start(wf);failed=self.wait(rid);old=self.current(failed)['A']
        self.client.post('/api/task-runs/'+old['id']+'/retry');done=self.wait(rid)
        self.assertEqual(done['workflow_run']['status'],'COMPLETED')
        self.assertEqual(self.client.post('/api/task-runs/'+old['id']+'/cancel').status_code,409)
        self.assertEqual(self.client.post('/api/workflow-runs/'+rid+'/cancel').status_code,409)
        self.assertEqual(self.client.get('/api/workflow-runs/'+rid).json()['workflow_run']['status'],'COMPLETED')

    def test_branch_rejects_duplicate_slots_and_markdown_contract_works(self):
        task=self.task('A');task['output_rule'][0]['media_type']='text/markdown'
        wf=self.define([task]);done=self.wait(self.start(wf));self.assertEqual(done['workflow_run']['status'],'COMPLETED',done)
        source=self.current(done)['A']
        body={'instruction':'branch','output_rule':[{'output_key':'same','path':'one.md'},{'output_key':'same','path':'two.md'}]}
        self.assertEqual(self.client.post('/api/task-runs/'+source['id']+'/branch',json=body).status_code,422)

    def test_git_output_copy_interruption_can_recover_without_new_turn(self):
        project=Path(ROOT.name)/('git-recovery-'+self.work['id']);project.mkdir()
        git(['init',str(project)])
        git(['-C',str(project),'-c','user.name=Review','-c','user.email=review@example.invalid','commit','--allow-empty','-m','initial'])
        linked=self.client.post('/api/works',json={'category_id':self.work['category_id'],'name':'Git recovery','workspace_kind':'LINKED','linked_workspace_path':str(project)}).json()
        old=self.work;self.work=linked
        try:
            task=self.task('A');task['workspace_mode']='GIT_WORKTREE';wf=self.define([task])
            from app.git_workspace import collect_changes
            def interrupted_copy(*args):
                collect_changes(*args)
                raise OSError('Injected interruption after reserved output writes')
            with patch('app.git_workspace.collect_changes',side_effect=interrupted_copy):
                rid=self.start(wf);failed=self.wait(rid)
            attempt=self.current(failed)['A'];self.assertEqual(attempt['status'],'FAILED')
            manifest=json.loads(attempt['run']['manifest'])
            self.assertTrue(manifest.get('git_outputs_prepared'))
            self.assertTrue((Path(manifest['output_root'])/'system/git/changes.json').exists())
            started=len(self.fake.started)
            # Reproduce persisted Runtime terminal with finalization interrupted.
            with COMMAND_LOCK, Session() as db:
                run=db.get(Run,attempt['run_id']);tr=db.get(TaskRun,attempt['id'])
                run.status,run.phase='RUNNING','FINALIZING';tr.status='RUNNING';db.commit()
            self.client.portal.call(main.runner.recover)
            done=self.wait(rid);self.assertEqual(done['workflow_run']['status'],'COMPLETED',done)
            self.assertEqual(len(self.fake.started),started)
        finally:self.work=old

    def test_git_worktrees_are_isolated_and_original_clean(self):
        project=Path(ROOT.name)/('linked-'+self.work['id']);project.mkdir()
        git(['init',str(project)]);git(['-C',str(project),'-c','user.name=Review','-c','user.email=review@example.invalid','commit','--allow-empty','-m','initial'])
        (project/'code.txt').write_text('original\n');git(['-C',str(project),'add','code.txt']);git(['-C',str(project),'-c','user.name=Review','-c','user.email=review@example.invalid','commit','-m','code'])
        before={str(p.relative_to(project)):sha(p.read_bytes()) for p in project.rglob('*') if p.is_file()}
        linked=self.client.post('/api/works',json={'category_id':self.work['category_id'],'name':'Linked','workspace_kind':'LINKED','linked_workspace_path':str(project)})
        self.assertEqual(linked.status_code,201,linked.text)
        old=self.work;self.work=linked.json()
        try:
            tasks=[self.task('A'),self.task('B')]
            for t in tasks:t['workspace_mode']='GIT_WORKTREE'
            wf=self.define(tasks);done=self.wait(self.start(wf))
            self.assertEqual(done['workflow_run']['status'],'COMPLETED',done)
            cur=self.current(done);self.assertNotEqual(json.loads(cur['A']['run']['manifest'])['cwd'],json.loads(cur['B']['run']['manifest'])['cwd'])
            for t in cur.values():
                self.assertEqual({o['output_key'] for o in t['outputs']},{'result','git_patch','git_changes','git_new_files'})
                m=json.loads(t['run']['manifest']);self.assertEqual(m['sandbox']['sandbox_workspace_write']['writable_roots'],[m['output_root']])
                self.assertNotIn(str(project),m['sandbox']['sandbox_workspace_write']['writable_roots'])
            after={str(p.relative_to(project)):sha(p.read_bytes()) for p in project.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
        finally:self.work=old

    def test_branch_keeps_frozen_revision_after_definition_edit(self):
        wf = self.define([self.task('A')])
        original = self.current(self.wait(self.start(wf)))['A']
        edited = self.client.put('/api/workflows/'+wf['id'], json={
            'name':'Edited', 'tasks':wf['tasks'], 'expected_revision':1})
        self.assertEqual(edited.status_code, 200)
        response = self.client.post('/api/task-runs/'+original['id']+'/branch', json={'instruction':'new direction'})
        self.assertEqual(response.status_code, 202, response.text)
        done = self.wait(response.json()['workflow_run']['id'])
        self.assertEqual(done['workflow_run']['definition_revision'], 1)
        self.assertEqual(done['workflow_run']['status'], 'COMPLETED')

    def test_library_filters_unavailable_and_unmapped_task_outputs(self):
        task = self.current(self.wait(self.start(self.define([self.task('A')]))))['A']
        artifact = task['outputs'][0]['artifact']
        aid = artifact['id']
        self.assertEqual(self.client.post('/api/artifacts/'+aid+'/publish', json={'scope':'GLOBAL'}).status_code, 200)
        path = Path(self.work['path']) / artifact['relative_path']
        saved = path.read_bytes(); path.unlink()
        self.client.get('/api/artifacts/'+aid)
        self.assertNotIn(aid, [a['id'] for a in self.client.get('/api/library?work_id='+self.work['id']).json()])
        path.write_bytes(saved); self.client.get('/api/artifacts/'+aid)
        with COMMAND_LOCK, Session() as db:
            db.query(TaskRunOutput).filter_by(task_run_id=task['id']).delete()
            db.commit()
        self.assertEqual(self.client.post('/api/artifacts/'+aid+'/publish', json={'scope':'GLOBAL'}).status_code, 409)
        self.assertNotIn(aid, [a['id'] for a in self.client.get('/api/library?work_id='+self.work['id']).json()])

    def test_retry_uses_snapshot_after_library_scope_change_and_original_loss(self):
        producer = self.current(self.wait(self.start(self.define([self.task('Producer')]))))['Producer']
        artifact = producer['outputs'][0]['artifact']; aid = artifact['id']
        self.client.post('/api/artifacts/'+aid+'/publish', json={'scope':'CATEGORY'})
        owner = self.work
        self.work = self.client.post('/api/works',json={'category_id':owner['category_id'],'name':'Consumer'}).json()
        try:
            consumer = self.task('Consumer',instruction='FAIL_ONCE')
            consumer['input_rule'] = [{'input_key':'reference','artifact_id':aid}]
            rid = self.start(self.define([consumer])); failed = self.wait(rid)
            attempt = self.current(failed)['Consumer']
            self.assertEqual(attempt['status'], 'FAILED')
            self.client.post('/api/artifacts/'+aid+'/publish',json={'scope':'WORK'})
            (Path(owner['path']) / artifact['relative_path']).unlink()
            self.client.get('/api/artifacts/'+aid)
            response = self.client.post('/api/task-runs/'+attempt['id']+'/retry')
            self.assertEqual(response.status_code, 202, response.text)
            done = self.wait(rid)
            self.assertEqual(done['workflow_run']['status'], 'COMPLETED', done)
            new = self.current(done)['Consumer']
            manifest = json.loads(new['run']['manifest'])
            self.assertEqual(sha((Path(manifest['files'][0]['snapshot_root']) / manifest['files'][0]['snapshot_path']).read_bytes()),artifact['sha256'])
        finally:
            self.work = owner

    def test_template_unresolved_survives_save_reclone_and_reload(self):
        source = self.client.post('/api/works/'+self.work['id']+'/sources',files={'file':('reference.md',b'reference','text/markdown')}).json()
        spec = self.task('A'); spec['context_rule'] = {'source_ids':[source['id']]}
        wf = self.define([spec])
        template = self.client.post('/api/workflows/'+wf['id']+'/templates',json={}).json()
        other = self.client.post('/api/works',json={'category_id':self.work['category_id'],'name':'Target'}).json()
        cloned = self.client.post('/api/workflow-templates/'+template['id']+'/clone',json={'target_work_id':other['id']}).json()
        self.assertFalse(cloned['enabled']); self.assertEqual(len(cloned['unresolved_bindings']),1)
        self.assertEqual(cloned['unresolved_bindings'][0]['name'],'reference.md')
        self.assertEqual(self.client.get('/api/workflows/'+cloned['id']).json()['unresolved_bindings'],cloned['unresolved_bindings'])
        second_template = self.client.post('/api/workflows/'+cloned['id']+'/templates',json={}).json()
        second = self.client.post('/api/workflow-templates/'+second_template['id']+'/clone',json={'target_work_id':other['id']}).json()
        self.assertFalse(second['enabled'])
        self.assertEqual(second['unresolved_bindings'][0]['task_id'],second['tasks'][0]['id'])
        self.assertNotEqual(second['tasks'][0]['id'],cloned['tasks'][0]['id'])

    def test_shared_slots_and_standalone_lane(self):
        main.runner.max_parallel_tasks = 2
        self.barrier()
        ids = [self.start(self.define([self.task(k,instruction='BARRIER')])) for k in ['A','B','C']]
        held = self.wait(ids[1], lambda d:any(t['status']=='RUNNING' for t in d['task_runs']))
        third = self.client.get('/api/workflow-runs/'+ids[2]).json()
        self.assertEqual(third['task_runs'][0]['status'],'QUEUED')
        self.assertEqual(self.fake.peak,2)
        self.release()
        for rid in ids:
            self.assertEqual(self.wait(rid)['workflow_run']['status'],'COMPLETED')
        self.barrier()
        standalone=[]
        for _ in range(2):
            response=self.client.post('/api/works/'+self.work['id']+'/runs',json={'instruction':'BARRIER'})
            self.assertEqual(response.status_code,202,response.text);standalone.append(response.json()['id'])
        rid=self.start(self.define([self.task('Alongside',instruction='BARRIER')]))
        self.wait(rid,lambda d:any(t['status']=='RUNNING' for t in d['task_runs']))
        statuses=[self.client.get('/api/runs/'+r).json()['run']['status'] for r in standalone]
        self.assertEqual(statuses,['RUNNING','CREATED'])
        self.release();self.wait(rid)
        for run_id in standalone:
            for _ in range(700):
                state=self.client.get('/api/runs/'+run_id).json()['run']['status']
                if state not in {'CREATED','RUNNING'}:break
                time.sleep(.01)
            self.assertEqual(state,'COMPLETED')



class MigrationReviewTests(unittest.TestCase):
    def test_existing_clone_can_prepare_frozen_detached_commit(self):
        from types import SimpleNamespace
        from app.git_workspace import baseline, prepare
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'project'; source.mkdir()
            git(['init', str(source)])
            git(['-C', str(source), 'config', 'user.email', 'test@example.invalid'])
            git(['-C', str(source), 'config', 'user.name', 'Offline test'])
            (source / 'code.txt').write_text('first')
            git(['-C', str(source), 'add', 'code.txt'])
            git(['-C', str(source), 'commit', '-m', 'first'])
            work = SimpleNamespace(path=str(root / 'managed'), linked_workspace_path=str(source))
            first = baseline(work)
            prepare(work, 'first', first)
            git(['-C', str(source), 'checkout', '--detach'])
            (source / 'code.txt').write_text('detached')
            git(['-C', str(source), 'commit', '-am', 'detached'])
            second = baseline(work)
            manifest = prepare(work, 'second', second)
            self.assertEqual((Path(manifest['cwd']) / 'code.txt').read_text(), 'detached')
            self.assertEqual(baseline(work), second)

    def test_upgrade_creates_consistent_backup_before_migration(self):
        from app import db as database
        with tempfile.TemporaryDirectory() as directory:
            dbpath = Path(directory) / 'control.db'
            engine = create_engine('sqlite:///'+str(dbpath))
            cfg = Config(); cfg.set_main_option('script_location', str(Path('app/migrations').resolve()))
            with engine.begin() as connection:
                cfg.attributes['connection'] = connection
                alembic_command.upgrade(cfg, '0001')
                connection.exec_driver_sql("INSERT INTO categories VALUES ('kept','Category',1,'2026-09-29')")
            with patch.object(database, 'DB_PATH', dbpath), patch.object(database, 'engine', engine):
                database.migrate()
                backups = list(Path(directory).glob('control.before-0001-*.db'))
                self.assertEqual(len(backups), 1)
                with sqlite3.connect(backups[0]) as backup:
                    self.assertEqual(backup.execute('SELECT version_num FROM alembic_version').fetchone()[0], '0001')
                    self.assertEqual(backup.execute('SELECT id FROM categories').fetchone()[0], 'kept')
                    self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                database.migrate()
                self.assertEqual(len(list(Path(directory).glob('control.before-*.db'))), 1)
            engine.dispose()

    def test_reserved_output_paths(self):
        from app.workflow import OutputRule
        for path in ['system', 'system/git/changes.patch', '.git/config', 'nested/.git/config', '../x', 'a//b']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                OutputRule(output_key='result', path=path)

    def test_scheduler_recovers_after_storage_failure(self):
        from app.runner import Runner
        local = Runner()
        calls = []
        async def exercise():
            def tick_once():
                calls.append(1)
                if len(calls) == 1:
                    raise OSError("injected scheduler storage failure")
                local.stop.set()
            with patch('app.runner.tick', side_effect=tick_once):
                with self.assertLogs('app.runner', level='ERROR'):
                    await asyncio.wait_for(local.dispatch(), 3)
            self.assertEqual(len(calls), 2)
            self.assertIsNone(local.dispatch_error)
        asyncio.run(exercise())

    def test_upgrade_preserves_phase1_rows_event_ids_and_fk(self):
        with tempfile.TemporaryDirectory() as directory:
            dbpath=Path(directory)/'control.db'
            engine=create_engine('sqlite:///'+str(dbpath))
            cfg=Config();cfg.set_main_option('script_location',str(Path('app/migrations').resolve()))
            with engine.begin() as c:
                c.exec_driver_sql('PRAGMA foreign_keys=ON');cfg.attributes['connection']=c;alembic_command.upgrade(cfg,'0001')
                date='2026-09-29'
                c.exec_driver_sql("INSERT INTO categories VALUES ('cat','Category',1,?)",(date,))
                c.exec_driver_sql("INSERT INTO works VALUES ('work','cat','Work','desc','/managed/work','READY',0,?)",(date,))
                c.exec_driver_sql("INSERT INTO requests VALUES ('req','work','instruction','[]',?)",(date,))
                c.exec_driver_sql("INSERT INTO runs (id,request_id,work_id,operation,model,reasoning,status,phase,artifact_state,safety_block,manifest,final_text,cancel_requested,created_at) VALUES ('run','req','work','new','model','low','COMPLETED','COMPLETED','READY',0,'{}','done',0,?)",(date,))
                c.exec_driver_sql("INSERT INTO artifacts VALUES ('art','work','run','result.md','result.md','artifacts/result.md','text/markdown',1,'hash',0,'AVAILABLE',?)",(date,))
                c.exec_driver_sql("INSERT INTO events VALUES (42,'run','RUN_COMPLETED','{}',?)",(date,))
                alembic_command.upgrade(cfg,'head')
                self.assertEqual(c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar(),'0007')
                self.assertEqual(c.exec_driver_sql('SELECT workspace_kind,linked_workspace_path,path FROM works').one(),('MANAGED',None,'/managed/work'))
                self.assertEqual(c.exec_driver_sql('SELECT id,run_id,payload FROM events').one(),(42,'run','{}'))
                self.assertEqual(c.exec_driver_sql('SELECT artifact_ids FROM requests').scalar(),'[]')
                self.assertEqual(c.exec_driver_sql('SELECT sha256 FROM artifacts').scalar(),'hash')
                self.assertEqual(c.exec_driver_sql('PRAGMA foreign_key_check').all(),[])
                indexes={r[0] for r in c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='index'")}
                self.assertTrue({'ix_events_workflow_cursor','ix_workflow_runs_work_created','ix_dependencies_producer'}.issubset(indexes))
                c.exec_driver_sql("INSERT INTO events(run_id,type,payload,created_at) VALUES ('run','NEW','{}',?)",(date,))
                self.assertEqual(c.exec_driver_sql('SELECT max(id) FROM events').scalar(),43)
                alembic_command.upgrade(cfg,'head')
            engine.dispose()

    def test_static_scripts_and_dom_ids(self):
        from html.parser import HTMLParser
        class IDs(HTMLParser):
            def __init__(self):super().__init__();self.ids=[]
            def handle_starttag(self,tag,attrs):
                for k,v in attrs:
                    if k=='id':self.ids.append(v)
        parser=IDs();parser.feed(Path('app/static/index.html').read_text())
        self.assertEqual(len(parser.ids),len(set(parser.ids)))
        used=set()
        for name in ['app.js','workflows.js','storage.js']:
            used.update(re.findall(r"\$\('([^']+)'\)",Path('app/static',name).read_text()))
        self.assertFalse(used-set(parser.ids),used-set(parser.ids))
