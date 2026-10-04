"""One isolated Phase 3 state-transition flow; FakeGateway only.
Run: .venv/bin/python -m unittest discover -s tests -p test_phase3.py -v
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch


class Phase3Flow(unittest.TestCase):
    def test_operations_and_recovery(self):
        if 'app.main' in sys.modules:
            self.skipTest('Run this flow in its documented isolated process')
        with tempfile.TemporaryDirectory(prefix='phase3-') as directory:
            root=Path(directory).resolve()
            for name in ('application','state','Developer'):(root/name).mkdir()
            env={'CONTROL_CENTER_ROOT':str(root/'application'),'CONTROL_CENTER_STATE':str(root/'state'),
                 'CONTROL_CENTER_DATA':str(root/'data'),'CONTROL_CENTER_WORKSPACE_ROOT':str(root/'Developer'),
                 'CONTROL_CENTER_RUNTIME':str(root/'runtime'),'CONTROL_CENTER_MAX_PARALLEL_TASKS':'3'}
            with patch.dict(os.environ,env):
                from app import main
                from app.db import (Approval, Artifact, ArtifactRelation, DelayedResume, Run, ScheduleFire,
                                    Session, TaskRun, WorkflowRun, WorkflowSchedule, now)
                from app.workflow import COMMAND_LOCK, latest_attempts, new_execution
                from app.workflow_operations import ensure_review, utc
                from app.workflow_triggers import dispatch_due, process_delays
                from fastapi.testclient import TestClient

                class Fake:
                    def __init__(self):self.handles={};self.login_state={'status':'idle'};self.started=[];self.counter=0
                    async def open(self):pass
                    async def close(self):self.handles.clear()
                    async def account(self):return {'connected':True,'type':'fake'}
                    async def models(self):return [{'id':'fake','label':'Fake','default':True,'reasoning':['low'],'default_reasoning':'low'}]
                    async def thread(self,cwd,model,thread_id=None,**kwargs):
                        self.counter+=1;return thread_id or 'thread-'+str(self.counter)
                    async def start_turn(self,rid,tid,prompt,model,effort,**kwargs):
                        self.started.append(rid);self.handles[rid]=True;return {'thread_id':tid,'turn_id':'turn-'+str(self.counter)}
                    async def interrupt(self,rid):return False
                    async def events(self,rid):
                        with Session() as db:manifest=json.loads(db.get(Run,rid).manifest)
                        output=Path(manifest['output_root'])
                        for rule in manifest.get('output_rule',[{'path':'standalone.md'}]):
                            if rule.get('system'):continue
                            file=output/rule['path'];file.parent.mkdir(parents=True,exist_ok=True);file.write_text('result '+rid)
                        yield {'type':'ACTIVITY','payload':{'phase':'final_answer','text':'answer '+rid}}
                        yield {'type':'terminal','status':'completed','error':None}
                fake=Fake();main.runner.gateway=fake
                client=None
                def connect():
                    c=TestClient(main.app);c.__enter__();c.get('/');c.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()});return c
                def post(path,body=None,**kwargs):
                    r=client.post('/api'+path,json=body,**kwargs);self.assertLess(r.status_code,300,r.text);return r.json()
                def get(path):
                    r=client.get('/api'+path);self.assertEqual(r.status_code,200,r.text);return r.json()
                def wait(fn):
                    until=time.monotonic()+10
                    while time.monotonic()<until:
                        value=fn()
                        if value:return value
                        time.sleep(.02)
                    self.fail('Fake state transition timed out')
                def detail(wrid):return get('/workflow-runs/'+wrid)
                def state_is(wrid,status):
                    d=detail(wrid);return d if d['workflow_run']['status']==status else None
                def current(d):return {t['task_definition_id']:t for t in d['task_runs'] if t['is_current']}
                def choose(action,approval,**kwargs):return post('/approvals/'+approval['id']+'/decision',{'action':action,**kwargs})
                try:
                    client=connect()
                    category=post('/categories',{'name':'Phase3'});work=post('/works',{'name':'phase3-project','category_id':category['id']})
                    # Representative Phase 1 execution, once.
                    single=post('/works/'+work['id']+'/runs',{'instruction':'standalone'})
                    wait(lambda:get('/runs/'+single['id'])['run']['status']=='COMPLETED')
                    def task(key,parents=(),review='AUTO'):
                        return {'id':'phase3-'+key,'name':key,'instruction':'produce '+key,'review_policy':review,
                                'depends_on':['phase3-'+p for p in parents],
                                'input_rule':[{'input_key':p,'task_definition_id':'phase3-'+p,'output_key':'result'} for p in parents],
                                'output_rule':[{'output_key':'result','path':key+'.md'}]}
                    workflow=post('/works/'+work['id']+'/workflows',{'name':'A to B/C to D','tasks':[
                        task('A',review='APPROVAL_REQUIRED'),task('B',['A']),task('C',['A']),task('D',['B','C'],review='REVIEW_AFTER')]})
                    wr=post('/workflows/'+workflow['id']+'/runs',{})['workflow_run']['id']
                    waiting=wait(lambda:state_is(wr,'WAITING_APPROVAL'))
                    a=current(waiting)['phase3-A'];self.assertEqual(a['status'],'COMPLETED')
                    self.assertTrue(all(current(waiting)[key]['run_id'] is None for key in ['phase3-B','phase3-C','phase3-D']))
                    approval=a['approval'];old=a['outputs'][0]['artifact'];old_file=Path(old['location_root'])/old['relative_path'];old_bytes=old_file.read_bytes()
                    self.assertEqual(client.post('/api/artifacts/'+old['id']+'/publish',json={'scope':'WORK'}).status_code,409)
                    self.assertEqual(client.post('/api/works/'+work['id']+'/runs',json={'instruction':'bypass','artifact_ids':[old['id']]}).status_code,400)
                    paused=post('/workflow-runs/'+wr+'/pause');self.assertTrue(paused['paused'])

                    timer=now()+timedelta(hours=1)
                    scheduled_workflow=post('/works/'+work['id']+'/workflows',{'name':'Scheduled text','tasks':[
                        {'id':'scheduled-task','name':'Scheduled','instruction':'text only'}]})
                    one=post('/workflows/'+scheduled_workflow['id']+'/schedules',{'kind':'ONE_TIME','start_at':timer.isoformat()})
                    recurring=post('/workflows/'+scheduled_workflow['id']+'/schedules',{'kind':'RECURRING','start_at':timer.isoformat(),'interval_minutes':60})
                    skipped=post('/workflows/'+scheduled_workflow['id']+'/schedules',{'kind':'ONE_TIME','start_at':timer.isoformat(),'misfire_policy':'SKIP'})
                    disabled=post('/workflows/'+scheduled_workflow['id']+'/schedules',{'kind':'RECURRING','start_at':timer.isoformat(),'interval_minutes':60,'enabled':False})
                    # A claim was committed before a crash; the next pointer is already advanced.
                    with COMMAND_LOCK,Session() as db:
                        schedule=db.get(WorkflowSchedule,recurring['id']);schedule.next_fire_at=timer+timedelta(hours=1)
                        db.add(ScheduleFire(id='recovered-claim',schedule_id=schedule.id,scheduled_for=timer,status='CLAIMED',retry_at=timer))
                        db.commit()
                    client.__exit__(None,None,None);client=None
                    client=connect()
                    recovered=detail(wr);self.assertEqual(recovered['workflow_run']['status'],'PAUSED')
                    self.assertEqual(current(recovered)['phase3-A']['approval']['status'],'WAITING')
                    self.assertEqual(len(fake.started),2)  # single + A, no recovery re-execution
                    self.assertEqual(get('/schedules/'+recurring['id'])['fires'][0]['status'],'CLAIMED')

                    revised=choose('REVISION',approval,instruction='revise A')
                    self.assertNotEqual(revised['revision_task_run_id'],a['id'])
                    time.sleep(.1)
                    self.assertEqual(len(fake.started),2)  # Pause blocks Revision enqueue / dispatch.
                    post('/workflow-runs/'+wr+'/resume')
                    revised_wait=wait(lambda:state_is(wr,'WAITING_APPROVAL'))
                    new_a=current(revised_wait)['phase3-A'];self.assertEqual(new_a['attempt_number'],2)
                    new_artifact=new_a['outputs'][0]['artifact'];self.assertNotEqual(new_artifact['id'],old['id'])
                    self.assertEqual(old_file.read_bytes(),old_bytes)
                    self.assertEqual(new_a['run']['operation'],'revision')
                    with Session() as db:
                        self.assertIsNotNone(db.query(ArtifactRelation).filter_by(kind='REVISION_OF',source_artifact_id=old['id'],target_artifact_id=new_artifact['id']).first())
                    # Two concurrent, identical decisions yield one admitted result and no duplicate consumer.
                    def approve():return client.post('/api/approvals/'+new_a['approval']['id']+'/decision',json={'action':'APPROVE'})
                    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(lambda _:approve(),range(2)))
                    self.assertTrue(all(r.status_code==200 for r in responses),[r.text for r in responses])
                    self.assertTrue(all(r.json()['outputs'][0]['publication'] is None for r in responses))
                    done=wait(lambda:state_is(wr,'COMPLETED'));tasks=current(done)
                    self.assertTrue(all(tasks[key]['status']=='COMPLETED' for key in ['phase3-A','phase3-B','phase3-C','phase3-D']))
                    self.assertEqual(len(done['task_runs']),5)  # A revision + original A + B/C/D
                    self.assertEqual(tasks['phase3-D']['approval']['status'],'WAITING')  # REVIEW_AFTER did not gate.
                    post('/artifacts/'+new_artifact['id']+'/publish',{'scope':'WORK'})
                    self.assertEqual(get('/library?work_id='+work['id'])[0]['id'],new_artifact['id'])

                    delayed=post('/task-runs/'+new_a['id']+'/delayed-resumes',{'instruction':'continue from checkpoint','delay_hours':5},headers={'Idempotency-Key':'delay-once'})
                    replay=post('/task-runs/'+new_a['id']+'/delayed-resumes',{'instruction':'continue from checkpoint','delay_hours':5},headers={'Idempotency-Key':'delay-once'})
                    self.assertEqual(delayed['id'],replay['id'])
                    with Session() as db:
                        due=utc(db.get(DelayedResume,delayed['id']).due_at)
                        self.assertAlmostEqual((due-now()).total_seconds(),5*3600,delta=4)
                    # Clock advancement tests time triggers; scheduled flows stop before model execution.
                    with patch('app.scheduler.enqueue'):
                        client.portal.call(dispatch_due,main.runner,timer+timedelta(minutes=10))
                        for item in [one,recurring]:
                            record=get('/schedules/'+item['id']);fire=record['fires'][0]
                            self.assertEqual(fire['status'],'TRIGGERED',fire);post('/workflow-runs/'+fire['workflow_run_id']+'/pause')
                        self.assertEqual(get('/schedules/'+skipped['id'])['fires'][0]['status'],'SKIPPED')
                        self.assertEqual(get('/schedules/'+disabled['id'])['fires'],[])
                        client.portal.call(dispatch_due,main.runner,timer+timedelta(minutes=10))
                        self.assertEqual(len(get('/schedules/'+one['id'])['fires']),1)
                        self.assertEqual(len(get('/schedules/'+recurring['id'])['fires']),1)
                        # Enable/disable plus a later recurrence, coalescing multiple missed intervals.
                        self.assertEqual(client.patch('/api/schedules/'+disabled['id'],json={'enabled':True}).status_code,200)
                        self.assertEqual(client.patch('/api/schedules/'+disabled['id'],json={'enabled':False}).status_code,200)
                        client.portal.call(dispatch_due,main.runner,timer+timedelta(hours=2,minutes=10))
                        repeated=get('/schedules/'+recurring['id'])['fires']
                        self.assertEqual(len(repeated),2);self.assertEqual(repeated[0]['status'],'TRIGGERED')
                        post('/workflow-runs/'+repeated[0]['workflow_run_id']+'/pause')
                        # REVIEW_AFTER revision branches because consumer history already completed.
                        branch=choose('REVISION',tasks['phase3-D']['approval'],instruction='revise D separately')
                        self.assertNotEqual(branch['revision_workflow_run_id'],wr)
                        post('/workflow-runs/'+branch['revision_workflow_run_id']+'/pause')
                    # Restart again: pending five-hour job and triggered schedules are durable.
                    count=len(fake.started);client.__exit__(None,None,None);client=None;client=connect()
                    self.assertEqual(len(fake.started),count)
                    self.assertEqual(next(d for d in get('/delayed-resumes') if d['id']==delayed['id'])['status'],'PENDING')
                    process_delays(due+timedelta(seconds=1));main.runner.wake.set()
                    job=next(d for d in get('/delayed-resumes') if d['id']==delayed['id'])
                    self.assertEqual(job['status'],'TRIGGERED')
                    continuation=wait(lambda:state_is(job['workflow_run_id'],'WAITING_APPROVAL'))
                    continued=current(continuation)['phase3-A']
                    self.assertNotEqual(continued['run_id'],new_a['run_id'])
                    self.assertEqual(continued['run']['operation'],'delayed_resume')
                    self.assertEqual(continued['run']['parent_run_id'],new_a['run_id'])
                    self.assertEqual(json.loads(continued['run']['manifest'])['checkpoint_id'],delayed['checkpoint_id'])
                    self.assertEqual(len(fake.started),7)  # single, A, revised A, B/C/D, continuation
                    # Reject through the same API preserves completed Task and blocks downstream.
                    rejected=choose('REJECT',continued['approval'],comment='not accepted')
                    self.assertEqual(rejected['status'],'REJECTED');self.assertEqual(rejected['task_status'],'COMPLETED')
                    wait(lambda:state_is(job['workflow_run_id'],'REJECTED'))
                    self.assertEqual(client.post('/api/artifacts/'+continued['outputs'][0]['artifact']['id']+'/publish',json={'scope':'WORK'}).status_code,409)
                    monitoring=get('/dashboard')['monitoring'];self.assertTrue(monitoring['workflows']);self.assertTrue(monitoring['schedules'])
                    self.assertEqual(client.post('/api/works/'+work['id']+'/runs',json={'instruction':'unsafe','execution_profile':{'permission':'full-access'}}).status_code,422)
                    with Session() as db:
                        self.assertEqual(db.connection().exec_driver_sql('SELECT version_num FROM alembic_version').scalar(),'0007')
                        self.assertEqual(db.connection().exec_driver_sql('PRAGMA foreign_key_check').all(),[])
                    from html.parser import HTMLParser
                    class IDs(HTMLParser):
                        def __init__(self):super().__init__();self.ids=[]
                        def handle_starttag(self,tag,attrs):self.ids.extend(v for k,v in attrs if k=='id')
                    parser=IDs();parser.feed(Path('app/static/index.html').read_text());self.assertEqual(len(parser.ids),len(set(parser.ids)))
                finally:
                    if client:client.__exit__(None,None,None)
