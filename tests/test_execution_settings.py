"""One isolated settings flow: two Fake turns, no live Runtime/model calls.
Run: .venv/bin/python -m unittest discover -s tests -p test_execution_settings.py -v
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class ExecutionSettingsFlow(unittest.TestCase):
    def test_single_and_task_profile_resolution(self):
        if 'app.main' in sys.modules:
            self.skipTest('Run this flow in its documented isolated process')
        with tempfile.TemporaryDirectory(prefix='execution-settings-') as directory:
            root = Path(directory).resolve()
            for name in ('application', 'state', 'Developer'):
                (root / name).mkdir()
            env = {'CONTROL_CENTER_ROOT':str(root/'application'), 'CONTROL_CENTER_STATE':str(root/'state'),
                   'CONTROL_CENTER_DATA':str(root/'data'), 'CONTROL_CENTER_WORKSPACE_ROOT':str(root/'Developer'),
                   'CONTROL_CENTER_RUNTIME':str(root/'runtime'), 'CONTROL_CENTER_MAX_PARALLEL_TASKS':'1'}
            with patch.dict(os.environ, env):
                from alembic import command
                from alembic.config import Config
                from sqlalchemy import create_engine
                engine = create_engine('sqlite:///'+str(root/'state/control.db'))
                cfg = Config(); cfg.set_main_option('script_location', str(Path('app/migrations').resolve()))
                old_path = root/'old-work'; old_path.mkdir(); (old_path/'keep.md').write_text('untouched')
                with engine.begin() as c:
                    cfg.attributes['connection'] = c; command.upgrade(cfg, '0004')
                    c.exec_driver_sql("INSERT INTO categories VALUES ('old-category','Old',1,'2026-09-29')")
                    c.exec_driver_sql("INSERT INTO works(id,category_id,name,description,path,provision_state,archived,created_at) VALUES ('old-work','old-category','Old','',?,'READY',0,'2026-09-29')", (str(old_path),))
                    c.exec_driver_sql("INSERT INTO requests(id,work_id,instruction,context_ids,created_at) VALUES ('old-request','old-work','old','[]','2026-09-29')")
                    c.exec_driver_sql("INSERT INTO runs(id,request_id,work_id,operation,model,reasoning,status,phase,artifact_state,safety_block,manifest,final_text,cancel_requested,created_at) VALUES ('old-run','old-request','old-work','new','historical','high','COMPLETED','COMPLETED','READY',0,'{}','old reply',0,'2026-09-29')")
                    before_run = c.exec_driver_sql("SELECT * FROM runs WHERE id='old-run'").mappings().one()
                engine.dispose()

                from app import main
                from app.db import Run, Session
                from app.execution_settings import run_profile

                catalog = [{'id':m,'label':m,'default':m=='alpha','reasoning':['low','high'],
                            'default_reasoning':'low','service_tiers':[{'id':'priority','name':'Fast','description':'Priority service'}],
                            'default_service_tier':None} for m in ('alpha','beta')]
                class Fake:
                    def __init__(self):
                        self.handles={}; self.login_state={'status':'idle'}; self.started=[]; self.thread_settings=[]
                        self.release=asyncio.Event()
                    async def open(self): pass
                    async def close(self): pass
                    async def account(self): return {'connected':True,'type':'fake'}
                    async def models(self): return catalog
                    async def thread(self,cwd,model,thread_id=None,**kwargs):
                        self.thread_settings.append(kwargs)
                        return 'thread-'+str(len(self.thread_settings))
                    async def start_turn(self,rid,tid,prompt,model,effort,**kwargs):
                        self.started.append((rid,kwargs['execution_profile']))
                        self.handles[rid]=True
                        return {'thread_id':tid,'turn_id':'turn-'+str(len(self.started))}
                    async def interrupt(self,rid): return False
                    async def events(self,rid):
                        if rid==self.started[0][0]: await self.release.wait()
                        yield {'type':'terminal','status':'completed','error':None}
                fake=Fake(); main.runner.gateway=fake
                from fastapi.testclient import TestClient
                with TestClient(main.app) as client:
                    client.get('/'); client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
                    def post(path,body,**kwargs):
                        r=client.post('/api'+path,json=body,**kwargs); self.assertLess(r.status_code,300,r.text); return r.json()
                    def put(scope,owner,body):
                        r=client.put(f'/api/execution-settings/defaults/{scope}/{owner}',json=body)
                        self.assertEqual(r.status_code,200,r.text); return r.json()
                    def until(fn):
                        deadline=time.monotonic()+6
                        while time.monotonic()<deadline:
                            value=fn()
                            if value: return value
                            time.sleep(.01)
                        self.fail('Fake execution timed out')
                    with Session() as db:
                        self.assertEqual(db.connection().exec_driver_sql('SELECT version_num FROM alembic_version').scalar(),'0007')
                        after=db.connection().exec_driver_sql("SELECT * FROM runs WHERE id='old-run'").mappings().one()
                        self.assertEqual({k:after[k] for k in before_run},dict(before_run))
                        self.assertIsNone(after['execution_profile'])
                        self.assertEqual(run_profile(db.get(Run,'old-run'))['model'],'historical')
                    self.assertEqual((old_path/'keep.md').read_text(),'untouched')
                    category=post('/categories',{'name':'Settings'})
                    work=post('/works',{'name':'settings-work','category_id':category['id']})
                    put('GLOBAL','global',{'model':'alpha','reasoning':'low','permission':'workspace-write','speed':'priority'})
                    put('CATEGORY',category['id'],{'reasoning':'high','permission':'read-only'})
                    put('WORK',work['id'],{'permission':'workspace-write'})
                    profile={'model':'alpha','reasoning':'low','personality':None,'permission':'workspace-write','speed':'priority'}
                    body={'instruction':'reply only','execution_profile':{'reasoning':'low'}}
                    standalone=post('/works/'+work['id']+'/runs',body,headers={'Idempotency-Key':'settings-single'})
                    self.assertEqual(standalone['execution_profile'],profile)
                    until(lambda:fake.started)
                    wf=post('/works/'+work['id']+'/workflows',{'name':'Inherited task','tasks':[
                        {'id':'settings-task','name':'Task','instruction':'reply only',
                         'execution_profile':{'permission':'read-only','speed':'default'}}]})
                    self.assertIsNone(wf['tasks'][0]['model'])
                    expected={**profile,'reasoning':'high','permission':'read-only','speed':'default'}
                    wr=post('/workflows/'+wf['id']+'/runs',{})
                    self.assertEqual(wr['snapshot']['tasks'][0]['execution_profile'],expected)
                    # Slot is occupied: settings change before the Task can actually start.
                    put('WORK',work['id'],{'model':'beta','reasoning':'low','permission':'workspace-write','speed':'default'})
                    replay=post('/works/'+work['id']+'/runs',body,headers={'Idempotency-Key':'settings-single'})
                    self.assertEqual(replay['id'],standalone['id']); self.assertEqual(replay['execution_profile'],profile)
                    client.portal.call(fake.release.set)
                    def finished():
                        result=client.get('/api/workflow-runs/'+wr['workflow_run']['id']).json()
                        return result if result['workflow_run']['status'] not in {'CREATED','RUNNING'} else None
                    done=until(finished)
                    self.assertEqual(done['workflow_run']['status'],'COMPLETED',done)
                    task_run=done['task_runs'][0]['run']
                    self.assertEqual(task_run['execution_profile'],expected)
                    self.assertEqual((task_run['model'],task_run['reasoning']),('alpha','high'))
                    single=client.get('/api/runs/'+standalone['id']).json()['run']
                    self.assertEqual(single['status'],'COMPLETED'); self.assertEqual(single['execution_profile'],profile)
                    self.assertEqual(fake.started,[(standalone['id'],profile),(task_run['id'],expected)])
                    self.assertEqual([t['execution_profile'] for t in fake.thread_settings],[profile,expected])
                    self.assertEqual(json.loads(task_run['manifest'])['execution_profile'],expected)
                    self.assertEqual(client.post('/api/execution-settings/resolve',json={'work_id':work['id'],'execution_profile':{'speed':'invented'}}).status_code,422)
                    self.assertEqual(client.post('/api/execution-settings/resolve',json={'work_id':work['id'],'execution_profile':{'personality':'friendly'}}).status_code,422)
                    capabilities=client.get('/api/execution-settings').json()
                    self.assertFalse(capabilities['personality']['supported'])
                    self.assertNotIn('full-access',capabilities['permissions']); self.assertIn('full-access',capabilities['runtime_permissions'])
                    put('WORK',work['id'],{'model':None,'reasoning':None})
                    cleared=post('/execution-settings/resolve',{'work_id':work['id']})
                    self.assertEqual((cleared['model'],cleared['reasoning'],cleared['permission']),('alpha','high','read-only'))

                    # Inspect adapter options without starting an App Server or a third turn.
                    from app.gateway import CodexGateway
                    from openai_codex import Sandbox
                    gateway=CodexGateway()
                    sdk=SimpleNamespace(thread_start=AsyncMock(return_value=SimpleNamespace(id='spy-thread')),
                                        thread_resume=AsyncMock(return_value=SimpleNamespace(id='spy-thread')),
                                        thread_fork=AsyncMock(return_value=SimpleNamespace(id='spy-thread')))
                    gateway.codex=sdk
                    async def inspect_adapter():
                        await gateway.thread('/fake','alpha',settings={'sandbox_workspace_write':{'writable_roots':['/output']}},execution_profile=expected)
                        self.assertEqual(sdk.thread_start.call_args.kwargs['sandbox'],Sandbox.read_only)
                        await gateway.thread('/fake','alpha',thread_id='spy-thread',execution_profile={**expected,'permission':'full-access'})
                        self.assertEqual(sdk.thread_resume.call_args.kwargs['sandbox'],Sandbox.full_access)
                        await gateway.fork_thread('original','/fake','alpha',{},'rules',execution_profile=profile)
                        self.assertEqual(sdk.thread_fork.call_args.kwargs['sandbox'],Sandbox.workspace_write)
                        thread=SimpleNamespace(turn=AsyncMock(return_value=SimpleNamespace(thread_id='spy-thread',id='spy-turn')))
                        with patch('app.gateway.AsyncThread',return_value=thread):
                            await gateway.start_turn('spy-run','spy-thread','prompt','alpha','high',execution_profile=expected)
                            args=thread.turn.call_args.kwargs
                            self.assertEqual(args['turn_service_tier'],'default')
                            self.assertNotIn('sandbox',args)  # Retain extra writable roots from thread policy.
                            self.assertEqual(args['effort'],'high')
                    client.portal.call(inspect_adapter)
                    # Single syntax/DOM check, no browser or additional model execution.
                    from html.parser import HTMLParser
                    class IDs(HTMLParser):
                        def __init__(self): super().__init__(); self.ids=[]
                        def handle_starttag(self,tag,attrs): self.ids.extend(v for k,v in attrs if k=='id')
                    parser=IDs(); parser.feed(Path('app/static/index.html').read_text())
                    self.assertEqual(len(parser.ids),len(set(parser.ids)))
