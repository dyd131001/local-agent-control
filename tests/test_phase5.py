"""One offline Dashboard / Git Diff / Review flow. No actual Codex calls.
Run: .venv/bin/python -m unittest discover -s tests -p test_phase5.py -v
"""
import asyncio
import base64
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

class OperationsFlow(unittest.TestCase):
    def test_dashboard_diff_review(self):
        if 'app.main' in sys.modules:self.skipTest('Run independently in an isolated process')
        with tempfile.TemporaryDirectory(prefix='phase5-') as directory:
            root=Path(directory)
            for name in ('application','state','Developer'):(root/name).mkdir()
            env={'CONTROL_CENTER_ROOT':str(root/'application'),'CONTROL_CENTER_STATE':str(root/'state'),
                 'CONTROL_CENTER_DATA':str(root/'data'),'CONTROL_CENTER_WORKSPACE_ROOT':str(root/'Developer'),
                 'CONTROL_CENTER_RUNTIME':str(root/'runtime')}
            with patch.dict(os.environ,env):
                from app import main
                from app.db import (Approval,DelayedResume,Event,Run,Session,TaskRun,ThreadRecord,WorkflowCheckpoint,
                                    WorkflowRun,WorkflowSchedule,now)
                from app.run_service import create_run
                from app.conversation import finish_conversation
                from app.git_workspace import git
                from app.gateway import CodexGateway
                from app.workflow import COMMAND_LOCK
                from fastapi.testclient import TestClient
                class Fake:
                    def __init__(self):self.handles={};self.login_state={'status':'idle'};self.started=[];self.release=False
                    async def open(self):pass
                    async def close(self):self.handles.clear()
                    async def account(self):return {'connected':True,'type':'fake'}
                    async def models(self):return [{'id':'fake','label':'Fake','default':True,'reasoning':['low'],'default_reasoning':'low'}]
                    async def runtime_status(self):return {'connection':'CONNECTED','observed_at':now().isoformat(),'account':{'connected':True},'rate_limits':{'status':'AVAILABLE','data':{'ordinary_usage_allowed':None,'primary':None,'buckets':{}},'observed_at':now().isoformat()}}
                    async def thread(self,cwd,model,thread_id=None,**kw):return thread_id or 'review-thread'
                    async def start_turn(self,rid,tid,prompt,model,effort,**kw):
                        self.started.append((rid,kw));self.handles[rid]=True;return {'thread_id':tid,'turn_id':'review-turn'}
                    async def interrupt(self,rid):self.release=True;return True
                    async def events(self,rid):
                        yield {'type':'CONTEXT_USAGE','payload':{'last':{'inputTokens':120,'outputTokens':80,'totalTokens':200},'total':{'totalTokens':200},'model_context_window':10000}}
                        while not self.release:await asyncio.sleep(.01)
                        yield {'type':'ACTIVITY','payload':{'phase':'final_answer','text':'Review finding: a.py changes the returned value. Confirm caller expectations.'}}
                        yield {'type':'terminal','status':'completed','error':None}
                fake=Fake();main.runner.gateway=fake
                repo=root/'Developer'/'repo';repo.mkdir()
                git(['init','-b','main',str(repo)])
                def g(*args):return git(['-C',str(repo),*args])
                g('config','user.email','fixture@example.invalid');g('config','user.name','Fixture')
                (repo/'a.py').write_text('def value():\n    return 1\n');(repo/'delete.txt').write_text('old\n');(repo/'rename.txt').write_text('rename\n');(repo/'binary.dat').write_bytes(b'\x00\x01')
                g('add','--','a.py','delete.txt','rename.txt','binary.dat');g('commit','-m','base')
                g('checkout','-b','feature');(repo/'a.py').write_text('def value():\n    return 2\n');g('add','a.py');g('commit','-m','feature');g('checkout','main')
                (repo/'a.py').write_text('def value():\n    return 3\n');g('add','a.py');(repo/'a.py').write_text('def value():\n    return 4\n')
                (repo/'delete.txt').unlink();g('mv','rename.txt','renamed.txt');(repo/'binary.dat').write_bytes(b'\x00\x02');(repo/'new.txt').write_text('fresh\n')
                with TestClient(main.app) as client:
                    client.get('/');client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
                    def post(path,body=None,**kw):
                        response=client.post('/api'+path,json=body,**kw);self.assertLess(response.status_code,300,response.text);return response.json()
                    def get(path):
                        response=client.get('/api'+path);self.assertEqual(response.status_code,200,response.text);return response.json()
                    def wait(fn):
                        deadline=time.monotonic()+8
                        while time.monotonic()<deadline:
                            result=fn()
                            if result:return result
                            time.sleep(.02)
                        self.fail('Fake state transition timed out')
                    category=post('/categories',{'name':'Phase5'})
                    work=post('/works',{'name':'repo','category_id':category['id'],'workspace_kind':'LINKED','workspace_path':str(repo)});wid=work['id']
                    original_status=g('status','--porcelain=v1','-z');original_index=(repo/'.git'/'index').read_bytes()
                    preview=post('/works/'+wid+'/tools/diff',{})
                    self.assertTrue(preview['available']);self.assertFalse(preview['ai_run_created'])
                    paths={f['path']:f for f in preview['files']}
                    self.assertEqual(set(paths),{'a.py','delete.txt','renamed.txt','binary.dat','new.txt'})
                    self.assertTrue(paths['renamed.txt']['status'].startswith('R'));self.assertEqual(paths['new.txt']['additions'],1)
                    self.assertTrue(paths['binary.dat']['binary']);self.assertIsNone(paths['binary.dat']['additions'])
                    self.assertIn('return 4',preview['patch']);self.assertEqual(g('status','--porcelain=v1','-z'),original_status);self.assertEqual((repo/'.git'/'index').read_bytes(),original_index)
                    branch=post('/works/'+wid+'/tools/diff',{'scope':'BRANCH','base_ref':'main','target_ref':'feature'})
                    self.assertIn('return 2',branch['patch']);self.assertEqual(branch['summary']['changed_files'],1)
                    self.assertEqual(client.post('/api/works/'+wid+'/tools/diff',json={'scope':'FILES','paths':['../outside']}).status_code,422)
                    with Session() as db:self.assertEqual(db.query(Run).count(),0)
                    review_body={'expected_diff_sha256':preview['diff_sha256']}
                    review=post('/works/'+wid+'/tools/reviews',review_body,headers={'Idempotency-Key':'review-once'})
                    (repo/'a.py').write_text('def value():\n    return 5\n')
                    wait(lambda:bool(fake.started));wait(lambda:get('/runs/'+review['id'])['run']['status']=='RUNNING')
                    self.assertEqual(fake.started[0][1]['execution_profile']['permission'],'read-only')
                    with Session() as db:
                        run=db.get(Run,review['id']);config=json.loads(run.context_config)
                        snapshot=next(s for s in config['snapshots'] if s['name']=='a.py')
                        self.assertIn(b'return 4',base64.b64decode(snapshot['data']));self.assertNotIn(b'return 5',base64.b64decode(snapshot['data']))
                    self.assertEqual(post('/works/'+wid+'/tools/reviews',review_body,headers={'Idempotency-Key':'review-once'})['id'],review['id'])
                    self.assertEqual(client.post('/api/works/'+wid+'/tools/reviews',json=review_body).status_code,409)
                    wf=post('/works/'+wid+'/workflows',{'name':'Dashboard state fixture','tasks':[
                        {'id':'seed-review','name':'review','instruction':'fixture','review_policy':'APPROVAL_REQUIRED'},
                        {'id':'seed-auto','name':'auto','instruction':'fixture'}]})
                    snapshot=json.dumps({'tasks':wf['tasks']})
                    review_spec=next(t for t in wf['tasks'] if t['id']=='seed-review')
                    with COMMAND_LOCK,Session() as db:
                        # Seed existing operation records without starting extra model executions.
                        failed=create_run(db,wid,'failed fixture',[],[],'fake','low');failed.status=failed.phase='FAILED';failed.completed_at=now();finish_conversation(db,failed)
                        recovery=create_run(db,wid,'recovery fixture',[],[],'fake','low');recovery.status='FAILED';recovery.phase='RECOVERING';recovery.safety_block=True
                        gate_run=WorkflowRun(id='fixture-gate',workflow_definition_id=wf['id'],work_id=wid,definition_revision=1,definition_snapshot=snapshot,status='WAITING_APPROVAL')
                        paused=WorkflowRun(id='fixture-paused',workflow_definition_id=wf['id'],work_id=wid,definition_revision=1,definition_snapshot=json.dumps({'tasks':[review_spec]}),status='PAUSED',paused=True)
                        bad=WorkflowRun(id='fixture-failed',workflow_definition_id=wf['id'],work_id=wid,definition_revision=1,definition_snapshot=json.dumps({'tasks':[review_spec]}),status='FAILED')
                        db.add_all([gate_run,paused,bad]);db.flush()
                        a=TaskRun(id='fixture-approval-task',workflow_run_id=gate_run.id,task_definition_id='seed-review',status='COMPLETED')
                        b=TaskRun(id='fixture-delay-source',workflow_run_id=gate_run.id,task_definition_id='seed-auto',status='COMPLETED')
                        queued=create_run(db,wid,'queued fixture',[],[],'fake','low')
                        q=TaskRun(id='fixture-queued-task',workflow_run_id=paused.id,task_definition_id='seed-review',status='QUEUED',run_id=queued.id)
                        failtask=TaskRun(id='fixture-failed-task',workflow_run_id=bad.id,task_definition_id='seed-review',status='FAILED')
                        db.add_all([a,b,q,failtask]);db.flush()
                        db.add(Approval(id='fixture-approval',task_run_id=a.id,policy='APPROVAL_REQUIRED',status='WAITING'))
                        db.add(WorkflowSchedule(id='fixture-schedule',workflow_definition_id=wf['id'],kind='ONE_TIME',enabled=True,next_fire_at=now()+timedelta(hours=1)))
                        checkpoint=WorkflowCheckpoint(id='fixture-checkpoint',workflow_run_id=gate_run.id,reason='fixture',snapshot='{}');db.add(checkpoint);db.flush()
                        db.add(DelayedResume(id='fixture-delay',checkpoint_id=checkpoint.id,source_task_run_id=b.id,due_at=now()+timedelta(hours=2),status='PENDING',instruction='fixture'))
                        thread=db.get(ThreadRecord,review['conversation_id']);thread.turn_count=21
                        db.commit()
                    dashboard=get('/operations/dashboard?limit=1')
                    for state in ('RUNNING','QUEUED','FAILED','WAITING_APPROVAL','PAUSED','SCHEDULED','RECOVERY_REQUIRED','CONTEXT_WARNING'):
                        self.assertGreater(dashboard['summary'][state]['total'],0,state)
                    self.assertEqual(dashboard['summary']['WAITING_APPROVAL']['total'],1)
                    self.assertEqual(dashboard['summary']['SCHEDULED']['total'],2)
                    self.assertTrue(dashboard['states']['FAILED']['has_more']);self.assertNotIn('"snapshots":',json.dumps(dashboard))
                    self.assertEqual(dashboard['runtime']['executions'][0]['execution_settings']['permission'],'read-only')
                    usage=next(u for u in get('/runtime/status')['usage']['items'] if u['run_id']==review['id'])
                    self.assertEqual(usage['last_turn']['totalTokens'],200);self.assertTrue(dashboard['global_execution_block']['blocked'])
                    gate=next(w for w in get('/operations/dashboard')['workflows']['items'] if w['id']=='fixture-gate')
                    self.assertEqual(gate['progress']['completion_percent'],100);self.assertEqual(gate['progress']['blocking_approvals'],1)
                    othercategory=post('/categories',{'name':'Other'});otherwork=post('/works',{'name':'other','category_id':othercategory['id']})
                    scoped=get('/operations/dashboard?work_id='+otherwork['id']);self.assertTrue(all(s['total']==0 for s in scoped['summary'].values()))
                    self.assertTrue(scoped['global_execution_block']['blocked']);self.assertIsNone(get('/runtime/status?work_id='+otherwork['id'])['provider']['rate_limits']['data']['ordinary_usage_allowed'])
                    self.assertTrue(all(key in get('/dashboard') for key in ('categories','works','runs','artifacts','monitoring','operations')))
                    unavailable=get('/works/'+otherwork['id']+'/tools/diff');self.assertFalse(unavailable['available'])
                    fake.release=True
                    wait(lambda:get('/runs/'+review['id'])['run']['status']=='COMPLETED')
                    result=get('/work-tools/reviews/'+review['id']);self.assertIn('Review finding',result['result']['text'])
                    saved=post('/work-tools/reviews/'+review['id']+'/save',{})
                    self.assertEqual(post('/work-tools/reviews/'+review['id']+'/save',{})['id'],saved['id'])
                    self.assertIn('Review finding',client.get('/api/artifacts/'+saved['id']+'/download').text)
                    self.assertTrue(any(a['id']==saved['id'] for a in get('/operations/dashboard')['recent_artifacts']['items']))
                    self.assertEqual(len(fake.started),1)
                    self.assertIn('return 5',(repo/'a.py').read_text())
                # Public SDK metadata spy: rate limits / cache / unknown values without Runtime.
                async def status_contract():
                    gateway=CodexGateway();gateway.codex=SimpleNamespace(account=AsyncMock(return_value={'account':{'type':'fake'}}),metadata={})
                    transport=SimpleNamespace(initialize=AsyncMock(),request=AsyncMock(return_value={'rateLimits':{'primary':{'usedPercent':25,'windowDurationMins':300,'resetsAt':1000}},'ordinaryUsageAllowed':None}))
                    class Client:
                        async def __aenter__(self):return transport
                        async def __aexit__(self,*args):pass
                    with patch('app.gateway.AsyncCodexClient',return_value=Client()):
                        first=await gateway.runtime_status();second=await gateway.runtime_status()
                    self.assertEqual(transport.request.await_count,1);self.assertEqual(transport.request.call_args.args[0],'account/rateLimits/read')
                    self.assertEqual(first,second);self.assertEqual(first['rate_limits']['data']['primary']['primary']['used_percent'],25)
                    self.assertIsNone(first['rate_limits']['data']['ordinary_usage_allowed'])
                    gateway._status_at=0
                    transport.request.side_effect=RuntimeError('unavailable')
                    with patch('app.gateway.AsyncCodexClient',return_value=Client()):third=await gateway.runtime_status()
                    self.assertEqual(third['rate_limits']['status'],'STALE');self.assertEqual(third['rate_limits']['observed_at'],first['rate_limits']['observed_at'])
                asyncio.run(status_contract())
