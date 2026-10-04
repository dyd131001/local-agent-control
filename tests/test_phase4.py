"""One offline conversation flow. No real Runtime / model calls.
Run independently: .venv/bin/python -m unittest discover -s tests -p test_phase4.py -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

class ConversationFlow(unittest.TestCase):
    def test_conversation_context(self):
        if 'app.main' in sys.modules:self.skipTest('Run in an isolated process')
        with tempfile.TemporaryDirectory(prefix='phase4-') as directory:
            root=Path(directory)
            for name in ('application','state','Developer'):(root/name).mkdir()
            env={'CONTROL_CENTER_ROOT':str(root/'application'),'CONTROL_CENTER_STATE':str(root/'state'),
                 'CONTROL_CENTER_DATA':str(root/'data'),'CONTROL_CENTER_WORKSPACE_ROOT':str(root/'Developer'),
                 'CONTROL_CENTER_RUNTIME':str(root/'runtime')}
            with patch.dict(os.environ,env):
                from app import main
                from app.db import Session,Run,Request,ContextPack,ContextPackItem,ThreadRecord,Resource,EphemeralQuery,Handoff,Promotion,Artifact
                from fastapi.testclient import TestClient
                class Fake:
                    def __init__(self):self.handles={};self.login_state={'status':'idle'};self.threads={};self.options=[];self.started=[];self.compacted=[];self.forks=[];self.count=0
                    async def open(self):pass
                    async def close(self):self.handles.clear()
                    async def account(self):return {'connected':True,'type':'fake'}
                    async def models(self):return [{'id':'fake','label':'Fake','default':True,'reasoning':['low'],'default_reasoning':'low'}]
                    async def thread(self,cwd,model,thread_id=None,**options):
                        self.options.append(options);self.count+=1
                        tid=thread_id or 'thread-'+str(self.count);self.threads.setdefault(tid,[]);return tid
                    async def fork_thread(self,source,cwd,model,settings,rules,**options):
                        self.count+=1;tid='fork-'+str(self.count);self.threads[tid]=list(self.threads[source]);self.forks.append((source,tid));return tid
                    async def compact_thread(self,tid,*args,**kwargs):self.compacted.append(tid);return {'status':'COMPLETED'}
                    async def start_turn(self,rid,tid,prompt,model,effort,**options):
                        turn='turn-'+str(len(self.started)+1);self.started.append((rid,tid,prompt));self.handles[rid]=(tid,turn);return {'thread_id':tid,'turn_id':turn}
                    async def read_thread(self,tid):return {'id':tid,'turns':self.threads[tid]}
                    async def interrupt(self,rid):return False
                    async def events(self,rid):
                        tid,turn=self.handles[rid];self.threads[tid].append({'id':turn,'status':'completed','final_text':'answer'})
                        yield {'type':'ACTIVITY','payload':{'phase':'final_answer','text':'Temporary answer '+rid}}
                        yield {'type':'CONTEXT_USAGE','payload':{'last':{'totalTokens':500},'total':{'totalTokens':900},'model_context_window':10000}}
                        yield {'type':'terminal','status':'completed','error':None}
                fake=Fake();main.runner.gateway=fake
                with TestClient(main.app) as client:
                    client.get('/');client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
                    def post(path,body=None,**kw):
                        response=client.post('/api'+path,json=body,**kw);self.assertLess(response.status_code,300,response.text);return response.json()
                    def get(path):
                        response=client.get('/api'+path);self.assertEqual(response.status_code,200,response.text);return response.json()
                    def run(body,work=None):
                        value=post('/works/'+(work or wid)+'/conversations',body)
                        deadline=time.monotonic()+8
                        while time.monotonic()<deadline:
                            detail=get('/runs/'+value['id'])['run']
                            if detail['status'] in {'FAILED','CANCELLED','COMPLETED'}:
                                self.assertEqual(detail['status'],'COMPLETED',detail['error']);return detail
                            time.sleep(.02)
                        self.fail('Fake flow timed out')
                    category=post('/categories',{'name':'Phase4'});work=post('/works',{'name':'conversation-a','category_id':category['id']});wid=work['id']
                    other=post('/works',{'name':'conversation-b','category_id':category['id']})
                    a=run({'instruction':'start'});tid=a['conversation_id'];runtime=a['thread_id']
                    continue_body={'action':'CONTINUE','thread_id':tid,'instruction':'continue'}
                    continued=post('/works/'+wid+'/conversations',continue_body,headers={'Idempotency-Key':'continue-once'})
                    deadline=time.monotonic()+8
                    while time.monotonic()<deadline and get('/runs/'+continued['id'])['run']['status']!='COMPLETED':time.sleep(.02)
                    continued=get('/runs/'+continued['id'])['run'];self.assertEqual(continued['status'],'COMPLETED')
                    self.assertEqual(post('/works/'+wid+'/conversations',continue_body,headers={'Idempotency-Key':'continue-once'})['id'],continued['id'])
                    self.assertEqual(continued['thread_id'],runtime)
                    branch=run({'action':'FORK','thread_id':tid,'from_run_id':continued['id'],'instruction':'alternative'})
                    self.assertNotEqual(branch['thread_id'],runtime);self.assertEqual(fake.forks[0][0],runtime)
                    query=run({'action':'QUERY','thread_id':tid,'instruction':'Temporary question only'})
                    self.assertTrue(fake.options[-1]['ephemeral']);self.assertEqual(query['execution_profile']['permission'],'read-only')
                    self.assertNotEqual(query['thread_id'],runtime)
                    self.assertFalse(any(r['id']==query['id'] for r in get('/works/'+wid)['runs']))
                    q=get('/works/'+wid+'/conversations')['queries'][0]
                    promoted=post('/runs/'+query['id']+'/promotions',{'title':'Shared decision','content':'durable conclusion','scope':'CATEGORY','default_include':True})
                    artifact=post('/runs/'+query['id']+'/promotions',{'title':'Saved answer','kind':'ARTIFACT','content':'explicit saved result','scope':'WORK'})
                    self.assertEqual(get('/artifacts/'+artifact['id'])['availability'],'AVAILABLE')
                    pack=post('/works/'+other['id']+'/context-packs',{'name':'selected state','resource_ids':[promoted['id']],'goal':'new objective','pending':'one next step'})
                    self.assertEqual(pack['status'],'DRAFT');self.assertEqual(pack['freshness']['state'],'CURRENT')
                    self.assertEqual(client.post('/api/works/'+other['id']+'/conversations',json={'instruction':'no confirmation','pack_id':pack['id']}).status_code,409)
                    post('/context-packs/'+pack['id']+'/confirm',{'confirmed':True})
                    version=post('/context-packs/'+pack['id']+'/versions',{'name':'updated','resource_ids':[promoted['id']],'goal':'newer goal'})
                    self.assertEqual(version['version'],2);self.assertEqual(get('/context-packs/'+pack['id'])['summary']['goal'],'new objective')
                    changed=client.patch('/api/resources/'+promoted['id'],json={'content':'changed current conclusion'});self.assertEqual(changed.status_code,200,changed.text)
                    self.assertEqual(get('/context-packs/'+pack['id'])['freshness']['state'],'CHANGED')
                    # Packs hold references. A changed Resource requires a new reviewed version.
                    self.assertEqual(client.post('/api/works/'+other['id']+'/conversations',json={'instruction':'stale','pack_id':pack['id']}).status_code,409)
                    refreshed=post('/context-packs/'+pack['id']+'/versions',{'name':'refreshed','resource_ids':[promoted['id']],'goal':'new objective'})
                    post('/context-packs/'+refreshed['id']+'/confirm',{'confirmed':True})
                    fresh=run({'instruction':'consume selected shared resource','pack_id':refreshed['id'],'include_defaults':False},other['id'])
                    self.assertIn('changed current conclusion',json.loads(fresh['manifest'])['context_references'][0]['summary'])
                    handpack=post('/works/'+wid+'/context-packs',{'name':'handoff','thread_id':tid,'resource_ids':[promoted['id']],'goal':'continue objective','next_instruction':'finish'})
                    post('/context-packs/'+handpack['id']+'/confirm',{'confirmed':True})
                    handed=run({'action':'HANDOFF','thread_id':tid,'instruction':'continue with selected state','pack_id':handpack['id'],'confirmed':True,'supersede_parent':True,'resource_ids':[promoted['id']]})
                    self.assertNotEqual(handed['thread_id'],runtime);self.assertNotIn('Temporary question only',json.loads(handed['manifest'])['prompt'])
                    self.assertEqual(len(json.loads(handed['manifest'])['files']),1)
                    self.assertTrue(get('/runs/'+handed['id']+'/context')['aliases'])
                    compact=run({'action':'COMPACT','thread_id':handed['conversation_id'],'instruction':'compact then continue','include_defaults':False})
                    self.assertEqual(compact['thread_id'],handed['thread_id']);self.assertEqual(fake.compacted,[handed['thread_id']])
                    # Query conclusion goes to the original conversation with a short instruction only.
                    q2run=run({'action':'QUERY','thread_id':handed['conversation_id'],'instruction':'second temporary question'})
                    q2=next(q for q in get('/works/'+wid+'/conversations')['queries'] if q['run_id']==q2run['id'])
                    result=post('/queries/'+q2['id']+'/decision',{'action':'HANDOFF','summary':'short selected conclusion'})
                    delivered=result['result'];deadline=time.monotonic()+8
                    while time.monotonic()<deadline and get('/runs/'+delivered['id'])['run']['status']!='COMPLETED':time.sleep(.02)
                    self.assertEqual(get('/runs/'+delivered['id'])['run']['status'],'COMPLETED')
                    prompt=next(p for r,t,p in fake.started if r==delivered['id'])
                    self.assertIn('short selected conclusion',prompt);self.assertNotIn('second temporary question',prompt)
                    post('/queries/'+q['id']+'/decision',{'action':'DISCARD'})
                    cached=(root/'state'/'manifests'/(query['id']+'.json')).read_text()
                    self.assertNotIn('Temporary question only',cached)
                    self.assertEqual(client.post('/api/runs/'+query['id']+'/resume',json={'instruction':'must not persist query'}).status_code,409)
                    with Session() as db:
                        self.assertEqual(db.get(EphemeralQuery,q['id']).result,'');self.assertEqual(db.get(Request,query['request_id']).instruction,'[임시 질문 폐기]')
                        self.assertEqual(db.get(ThreadRecord,tid).status,'SUPERSEDED');self.assertEqual(db.get(ContextPack,pack['id']).version,1)
                        self.assertEqual(db.query(Artifact).filter_by(run_id=query['id']).count(),0)
                        self.assertEqual(db.query(Promotion).count(),2);self.assertEqual(db.query(Handoff).count(),2)
                    # Budget and isolation failures happen before any Runtime turn.
                    large=post('/runs/'+a['id']+'/promotions',{'title':'Too large','content':'x'*5000})
                    too_big=client.post('/api/works/'+wid+'/conversations',json={'instruction':'budget','resource_ids':[large['id']],'budget':100})
                    self.assertEqual(too_big.status_code,409);self.assertIn('CONTEXT_OVER_BUDGET',too_big.text)
                    self.assertEqual(client.post('/api/works/'+other['id']+'/context-packs',json={'name':'wrong scope','resource_ids':[large['id']]}).status_code,403)
                    self.assertEqual(client.post('/api/works/'+wid+'/conversations',json={'action':'FORK','from_run_id':a['id'],'instruction':'older turn'}).status_code,409)
                    self.assertEqual(get('/runs/'+fresh['id']+'/context')['pack_version'],3)
                    self.assertEqual(len(fake.started),9)
                    # One existing Workflow Task also uses the same context compiler and Run engine.
                    workflow=post('/works/'+other['id']+'/workflows',{'name':'Reuse existing Task engine','tasks':[{'id':'phase4-task','name':'text only','instruction':'use scoped default resource'}]})
                    wr=post('/workflows/'+workflow['id']+'/runs',{})['workflow_run']['id']
                    deadline=time.monotonic()+8
                    while time.monotonic()<deadline:
                        detail=get('/workflow-runs/'+wr)
                        if detail['workflow_run']['status'] in {'COMPLETED','FAILED'}:break
                        time.sleep(.02)
                    self.assertEqual(detail['workflow_run']['status'],'COMPLETED',detail)
                    task_run=detail['task_runs'][0]['run_id']
                    self.assertEqual(get('/runs/'+task_run+'/context')['inputs'][0]['source_id'],promoted['id'])
                    self.assertEqual(len(fake.started),10)
                    # Contract spy: public Gateway flags reach the SDK without opening Runtime.
                    import asyncio
                    from types import SimpleNamespace
                    from unittest.mock import AsyncMock
                    from app.gateway import CodexGateway
                    gateway=CodexGateway();gateway.codex=SimpleNamespace(thread_start=AsyncMock(return_value=SimpleNamespace(id='spy-thread')))
                    asyncio.run(gateway.thread('/temporary','fake',ephemeral=True,execution_profile={'permission':'read-only'}))
                    args=gateway.codex.thread_start.call_args.kwargs
                    self.assertTrue(args['ephemeral']);self.assertEqual(args['sandbox'].value,'read-only')
