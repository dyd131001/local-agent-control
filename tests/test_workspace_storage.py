"""One representative storage flow, using temporary paths and a FakeGateway only.
Run: .venv/bin/python -m unittest discover -s tests -p test_workspace_storage.py -v
"""
import asyncio
import json
import os
import tempfile
import time
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class StorageFlow(unittest.TestCase):
    def test_workspace_storage_end_to_end_and_legacy_compatibility(self):
        if 'app.main' in sys.modules:
            self.skipTest('Run the storage flow in its documented isolated process')
        with tempfile.TemporaryDirectory(prefix='workspace-storage-') as directory:
            root = Path(directory).resolve()
            app_root = root / 'application'; app_root.mkdir()
            state = root / 'state'; state.mkdir()
            data = app_root / 'data'
            developer = root / 'Developer'; developer.mkdir()
            runtime = root / 'runtime'
            env = {'CONTROL_CENTER_ROOT':str(app_root),'CONTROL_CENTER_STATE':str(state),
                   'CONTROL_CENTER_DATA':str(data),'CONTROL_CENTER_WORKSPACE_ROOT':str(developer),
                   'CONTROL_CENTER_RUNTIME':str(runtime)}
            with patch.dict(os.environ, env):
                from sqlalchemy import create_engine
                from alembic.config import Config
                from alembic import command
                dbpath = state / 'control.db'
                engine = create_engine('sqlite:///'+str(dbpath))
                cfg=Config();cfg.set_main_option('script_location',str(Path('app/migrations').resolve()))
                legacy = data / 'categories/legacy/works/old'; legacy.mkdir(parents=True)
                (legacy / 'reference.md').write_text('old reference')
                (legacy / 'result.md').write_text('old result')
                import hashlib
                digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
                with engine.begin() as connection:
                    cfg.attributes['connection']=connection;command.upgrade(cfg,'0003')
                    connection.exec_driver_sql("INSERT INTO categories VALUES ('legacy','Legacy',1,'2026-09-29')")
                    connection.exec_driver_sql("INSERT INTO works(id,category_id,name,description,path,provision_state,archived,created_at) VALUES ('old','legacy','Old','','%s','READY',0,'2026-09-29')" % legacy)
                    connection.exec_driver_sql("INSERT INTO sources VALUES ('old-source','old','reference.md','reference.md','text/markdown',13,?,1,'2026-09-29')",(digest(legacy/'reference.md'),))
                    connection.exec_driver_sql("INSERT INTO requests VALUES ('old-request','old','old','[]','2026-09-29','[]')")
                    connection.exec_driver_sql("INSERT INTO runs(id,request_id,work_id,operation,model,reasoning,status,phase,artifact_state,safety_block,manifest,final_text,cancel_requested,created_at) VALUES ('old-run','old-request','old','new','old','low','COMPLETED','COMPLETED','READY',0,'{}','',0,'2026-09-29')")
                    connection.exec_driver_sql("INSERT INTO artifacts VALUES ('old-artifact','old','old-run','result.md','result.md','result.md','text/markdown',10,?,0,'AVAILABLE','2026-09-29')",(digest(legacy/'result.md'),))
                engine.dispose()
                before={str(p.relative_to(legacy)):p.read_bytes() for p in legacy.rglob('*') if p.is_file()}
                from app import main
                from app.db import Run, Session
                class Fake:
                    def __init__(self): self.handles={};self.threads={};self.counter=0;self.inputs=[];self.login_state={'status':'idle'}
                    async def open(self): pass
                    async def close(self): self.handles.clear()
                    async def account(self): return {'connected':True,'type':'fake'}
                    async def models(self): return [{'id':'fake','label':'Fake','default':True,'reasoning':['low'],'default_reasoning':'low'}]
                    async def thread(self,cwd,model,thread_id=None,**kwargs):
                        self.counter+=1;tid=thread_id or 'thread-'+str(self.counter);self.threads.setdefault(tid,{'turns':[]});return tid
                    async def start_turn(self,rid,tid,prompt,model,effort,**kwargs):
                        turn={'id':'turn-'+str(self.counter),'status':'inProgress','input_hashes':[]};self.threads[tid]['turns'].append(turn);self.handles[rid]=turn;return {'thread_id':tid,'turn_id':turn['id']}
                    async def interrupt(self,rid): return False
                    async def read_thread(self,tid): return self.threads[tid]
                    async def events(self,rid):
                        with Session() as db: manifest=json.loads(db.get(Run,rid).manifest)
                        self.inputs.append([Path(f['snapshot_root'],f['snapshot_path']).read_bytes() for f in manifest['files']])
                        out=Path(manifest['output_root'])
                        for rule in manifest.get('output_rule',[{'path':'result.md'}]):
                            if rule.get('system'):continue
                            target=out/rule['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_text('result from '+rid)
                        self.handles[rid]['status']='completed'
                        yield {'type':'terminal','status':'completed','error':None}
                fake=Fake();main.runner.gateway=fake
                from fastapi.testclient import TestClient
                with TestClient(main.app) as client:
                    client.get('/');client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
                    def post(path,body):
                        response=client.post(path,json=body);self.assertLess(response.status_code,300,response.text);return response.json()
                    def wait_run(rid):
                        for _ in range(300):
                            value=client.get('/api/runs/'+rid).json()
                            if value['run']['status'] not in {'CREATED','RUNNING'}:return value
                            time.sleep(.01)
                        self.fail('Run timeout')
                    self.assertEqual(client.get('/api/storage/settings').json()['workspace_root'],str(developer))
                    with Session() as db:
                        self.assertEqual(db.connection().exec_driver_sql('SELECT version_num FROM alembic_version').scalar(),'0007')
                    self.assertEqual(client.get('/api/sources/old-source/download').text,'old reference')
                    self.assertEqual(client.get('/api/artifacts/old-artifact/download').text,'old result')
                    work=post('/api/works',{'name':'new-project','category_id':'legacy'})
                    self.assertEqual(work['workspace_path'],str(developer/'new-project'))
                    self.assertEqual(list(Path(work['workspace_path']).iterdir()),[])
                    document=post('/api/works/'+work['id']+'/documents',{'relative_path':'docs/plan.md','usage_type':'IMPLEMENTATION_PLAN','content':'workspace context'})
                    self.assertEqual(document['relative_path'],'docs/plan.md');self.assertEqual(document['location_type'],'WORKSPACE')
                    self.assertFalse((Path(work['workspace_path'])/'AGENTS.md').exists())
                    self.assertEqual(client.post('/api/works/'+work['id']+'/documents',json={'relative_path':'docs/plan.md','content':'overwrite'}).status_code,409)
                    external=root/'external.md';external.write_text('external reference')
                    source=post('/api/works/'+work['id']+'/sources/external',{'path':str(external)})
                    self.assertEqual(source['location_type'],'EXTERNAL')
                    standalone=post('/api/works/'+work['id']+'/runs',{'instruction':'write','context_ids':[document['id'],source['id']]})
                    done=wait_run(standalone['id']);self.assertEqual(done['run']['status'],'COMPLETED',done)
                    artifact=done['artifacts'][0];self.assertEqual(artifact['location_type'],'WORKSPACE')
                    self.assertTrue((Path(work['workspace_path'])/artifact['relative_path']).is_file())
                    self.assertFalse((data/'shared').exists())
                    self.assertIn(b'workspace context',fake.inputs[0]);self.assertIn(b'external reference',fake.inputs[0])
                    staging=Path(artifact['staging_path']);self.assertTrue(staging.exists())
                    post('/api/artifacts/'+artifact['id']+'/publish',{'scope':'GLOBAL'})
                    published=client.get('/api/artifacts/'+artifact['id']).json();self.assertEqual(published['location_type'],'SHARED')
                    self.assertTrue(Path(published['local_path']).is_file());self.assertFalse(staging.exists())
                    self.assertTrue((Path(work['workspace_path'])/artifact['relative_path']).is_file())
                    project=developer/'existing-project';project.mkdir();(project/'code.py').write_text('print(1)')
                    original={p.name:p.read_bytes() for p in project.iterdir()}
                    linked=post('/api/works',{'name':'existing-project','category_id':'legacy','workspace_mode':'LINKED','workspace_path':str(project)})
                    self.assertEqual({p.name:p.read_bytes() for p in project.iterdir()},original)
                    references=post('/api/works/'+linked['id']+'/sources/import',{'paths':['code.py']})
                    self.assertEqual(references[0]['relative_path'],'code.py');self.assertEqual({p.name:p.read_bytes() for p in project.iterdir()},original)
                    library=client.get('/api/library?work_id='+linked['id']).json();self.assertIn(artifact['id'],[a['id'] for a in library])
                    workflow=post('/api/works/'+linked['id']+'/workflows',{'name':'A to B','tasks':[
                        {'id':'task-a','name':'A','instruction':'write','model':'fake','reasoning':'low','input_rule':[{'input_key':'shared','artifact_id':artifact['id']}],'output_rule':[{'output_key':'result','path':'a.md'}]},
                        {'id':'task-b','name':'B','instruction':'write','model':'fake','reasoning':'low','depends_on':['task-a'],'input_rule':[{'input_key':'previous','task_definition_id':'task-a','output_key':'result'}],'output_rule':[{'output_key':'result','path':'b.md'}]}]})
                    execution=post('/api/workflows/'+workflow['id']+'/runs',{'expected_revision':1})['workflow_run']['id']
                    for _ in range(300):
                        detail=client.get('/api/workflow-runs/'+execution).json()
                        if detail['workflow_run']['status'] not in {'CREATED','RUNNING'}:break
                        time.sleep(.01)
                    self.assertEqual(detail['workflow_run']['status'],'COMPLETED',detail)
                    self.assertTrue(all(t['outputs'][0]['artifact']['location_type']=='WORKSPACE' for t in detail['task_runs']))
                    self.assertEqual(fake.counter,3)
                    converted=developer/'converted';converted.mkdir()
                    response=client.put('/api/works/old/workspace',json={'workspace_path':str(converted)})
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertEqual(response.json()['path'],str(legacy));self.assertEqual(list(converted.iterdir()),[])
                    self.assertEqual(client.get('/api/sources/old-source/download').text,'old reference')
                    self.assertEqual(client.get('/api/artifacts/old-artifact/download').text,'old result')
                    with patch('app.storage_api.subprocess.run',return_value=SimpleNamespace(returncode=0)) as opened:
                        self.assertEqual(client.post('/api/works/'+work['id']+'/workspace/open').status_code,200)
                        self.assertEqual(opened.call_args.args[0][-1],work['workspace_path'])
                    self.assertEqual({str(p.relative_to(legacy)):p.read_bytes() for p in legacy.rglob('*') if p.is_file()},before)
                    self.assertEqual(external.read_text(),'external reference')
                    self.assertEqual(client.post('/api/works/'+work['id']+'/documents',json={'relative_path':'../escape.md','content':'bad'}).status_code,422)
                    # Syntax/DOM check is part of this one flow; no second execution.
                    from html.parser import HTMLParser
                    class IDs(HTMLParser):
                        def __init__(self):super().__init__();self.ids=[]
                        def handle_starttag(self,tag,attrs):self.ids.extend(v for k,v in attrs if k=='id')
                    parser=IDs();parser.feed(Path('app/static/index.html').read_text());self.assertEqual(len(parser.ids),len(set(parser.ids)))
