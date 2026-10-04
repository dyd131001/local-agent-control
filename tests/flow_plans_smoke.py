"""Offline goal → draft → human edit → approval → existing Workflow/Schedule acceptance."""
import asyncio
import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_phase1 import FakeGateway, legacy_work
from app import main
from fastapi.testclient import TestClient


class PlanningGateway(FakeGateway):
    def __init__(self):
        super().__init__();self.counter=time.time_ns()%1000000000;self.research_path='report.md';self.bad_quote=False;self.prompts=[];self.web=False;self.web_many=False;self.thread_settings=[];self.pending=False
    async def research_capabilities(self,cwd=None):
        return {'web_search':self.web,'reason':'Offline test Runtime has no web search'}
    async def thread(self,cwd,model,thread_id=None,**kwargs):
        self.thread_settings.append(kwargs.get('settings') or {})
        return await super().thread(cwd,model,thread_id,**kwargs)
    async def events(self, rid):
        handle = self.handles[rid]
        self.prompts.append(handle['prompt'])
        if 'Research a goal before building' in handle['prompt']:
            result={'findings':[{'kind':'WEB' if self.web else 'WORKSPACE','title':'Report evidence',
                **({'url':'https://example.org/research'} if self.web else {'path':self.research_path}),
                'excerpt':'Public report evidence confirms the requested research.' if self.web else 'This quotation does not exist' if self.bad_quote else 'Collect facts and write a report with cited evidence.',
                'summary':'The source contains report evidence','rationale':'The source directly describes the report goal'}],
                'candidates':[{'title':'More evidence','path':'next-report.md','snippet':'Unreviewed related material','relevance':0.7}] if self.pending else [],
                'reason':''}
            if self.web_many:
                result['findings']=[{**result['findings'][0],'title':f'PDF evidence {index}',
                                     'url':f'https://example.org/research-{index}.pdf'} for index in range(4)]
        else:result = {
            "summary": "Collect evidence and write the final report",
            "workflow": {"name": "Report flow", "description": "Draft plan", "enabled": True, "tasks": [
                {"id": "collect", "name": "Collect", "instruction": "Collect facts", "depends_on": []},
                {"id": "write", "name": "Write", "instruction": "Write report", "depends_on": ["collect"]}]},
            "schedule": {"kind": "ONE_TIME", "start_at": (datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}}
        text = json.dumps(result)
        await asyncio.sleep(.02)
        handle["turn"].update(status="completed", final_text=text)
        yield {"type": "ACTIVITY", "payload": {"item_id": "final", "phase": "final_answer", "text": text}}
        yield {"type": "terminal", "status": "completed", "error": None}


class FlowPlanSmoke(unittest.TestCase):
    def test_gateway_research_policy_is_read_only_with_network(self):
        from app.gateway import CodexGateway
        class Client:
            async def start(self):pass
            async def initialize(self):pass
            async def close(self):pass
            async def thread_start(self,params):self.thread_params=params;return SimpleNamespace(thread=SimpleNamespace(id='research-thread'))
            async def turn_start(self,thread_id,prompt,params):self.turn_params=params;return SimpleNamespace(turn=SimpleNamespace(id='research-turn'))
        client=Client();gateway=CodexGateway()
        async def check():
            with patch('app.gateway.AsyncCodexClient',return_value=client):
                thread=await gateway.thread('/tmp','gpt-5',settings={'web_search':'live'},
                                            execution_profile={'permission':'read-only'},research_read_network=True)
                await gateway.start_turn('run',thread,'Read public research','gpt-5','medium',
                                         execution_profile={'permission':'read-only'})
                self.assertEqual(client.thread_params.sandbox.value,'read-only')
                policy=client.turn_params.sandbox_policy.model_dump(mode='json',by_alias=True,exclude_none=True)
                self.assertEqual(policy,{'networkAccess':True,'type':'readOnly'})
                await gateway.release_research(thread)
        asyncio.run(check())

    def test_goal_to_approved_workflow_and_schedule(self):
        fake=PlanningGateway();main.runner.gateway = fake
        with TestClient(main.app) as client:
            client.get('/')
            client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
            catalog=client.get('/api/flow-plans/catalog')
            self.assertEqual(catalog.status_code,200,catalog.text)
            self.assertIn('TaskBody',catalog.json()['schemas'])
            category=client.post('/api/categories',json={'name':'Flow plan smoke'}).json()
            work=legacy_work(category['id'],'Flow plan smoke')
            Path(work['path'],'report.md').write_text('Collect facts and write a report with cited evidence.\n',encoding='utf-8')
            started=client.post(f"/api/works/{work['id']}/flow-plans",json={'goal':'Collect facts and write a report next week'})
            self.assertEqual(started.status_code,202,started.text)
            plan=started.json()
            for _ in range(200):
                plan=client.get('/api/flow-plans/'+plan['id']).json()
                if plan['status'] in {'DRAFT','NO_SOURCES','FAILED','INVALID'}:break
                time.sleep(.02)
            self.assertEqual(plan['status'],'DRAFT',plan.get('error'))
            self.assertEqual(plan['research_run']['execution_profile']['permission'],'read-only')
            self.assertEqual(plan['generation_run']['execution_profile']['permission'],'read-only')
            self.assertEqual(json.loads(plan['generation_run']['manifest'])['files'],[])
            self.assertEqual(len(plan['evidence']),1)
            self.assertEqual(plan['evidence'][0]['material_type'],'SOURCE')
            self.assertEqual(plan['material_ids']['source_ids'],[plan['evidence'][0]['material_id']])
            self.assertTrue(any(plan['evidence'][0]['material_id'] in prompt for prompt in fake.prompts))
            self.assertEqual(len(plan['plan']['workflow']['tasks']),2)
            self.assertEqual(plan['plan']['workflow']['tasks'][1]['depends_on'],['collect'])
            self.assertEqual(client.get(f"/api/works/{work['id']}/workflows").json(),[])
            changed=client.patch(f"/api/flow-plans/{plan['id']}/evidence/0",json={
                'expected_revision':plan['revision'],'title':'Reviewed evidence',
                'summary':'Reviewed report context','rationale':'Verified against the Workspace file'})
            self.assertEqual(changed.status_code,200,changed.text)
            self.assertEqual(changed.json()['status'],'NEEDS_REPLAN')
            self.assertEqual(client.post('/api/flow-plans/'+plan['id']+'/approve',json={'expected_revision':changed.json()['revision']}).status_code,409)
            regenerated=client.post('/api/flow-plans/'+plan['id']+'/regenerate')
            self.assertEqual(regenerated.status_code,202,regenerated.text)
            for _ in range(200):
                plan=client.get('/api/flow-plans/'+plan['id']).json()
                if plan['status']=='DRAFT':break
                time.sleep(.02)
            self.assertEqual(plan['status'],'DRAFT',plan.get('error'))
            self.assertTrue(any('Reviewed report context' in prompt for prompt in fake.prompts))
            edited=plan['plan'];edited['workflow']['name']='Edited report flow'
            saved=client.put('/api/flow-plans/'+plan['id'],json={'expected_revision':plan['revision'],'plan':edited})
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertEqual(client.post('/api/flow-plans/'+plan['id']+'/approve',json={'expected_revision':plan['revision']}).status_code,409)
            approved=client.post('/api/flow-plans/'+plan['id']+'/approve',json={'expected_revision':saved.json()['revision']})
            self.assertEqual(approved.status_code,200,approved.text)
            result=approved.json();self.assertEqual(result['status'],'APPROVED')
            workflow=client.get('/api/workflows/'+result['workflow_definition_id']).json()
            self.assertEqual(workflow['name'],'Edited report flow')
            tasks={task['name']:task for task in workflow['tasks']}
            self.assertEqual(tasks['Write']['depends_on'],[tasks['Collect']['id']])
            schedule=client.get('/api/schedules/'+result['schedule_id']).json()['schedule']
            self.assertEqual(schedule['workflow_definition_id'],workflow['id'])
            updated=client.patch('/api/schedules/'+schedule['id'],json={'enabled':True,'kind':'RECURRING','interval_minutes':120})
            self.assertEqual(updated.status_code,200,updated.text)
            self.assertEqual(updated.json()['interval_seconds'],7200)
            self.assertEqual(client.post('/api/flow-plans/'+plan['id']+'/approve',json={'expected_revision':saved.json()['revision']}).json()['workflow_definition_id'],workflow['id'])
            again=client.post(f"/api/works/{work['id']}/flow-plans",json={'goal':'Collect facts and write another report next month'})
            self.assertEqual(again.status_code,202,again.text)
            second=again.json()
            for _ in range(200):
                second=client.get('/api/flow-plans/'+second['id']).json()
                if second['status'] in {'DRAFT','NO_SOURCES','FAILED','INVALID'}:break
                time.sleep(.02)
            self.assertEqual(second['status'],'DRAFT',second.get('error'))
            repeated=client.post('/api/flow-plans/'+second['id']+'/approve',json={'expected_revision':second['revision']})
            self.assertEqual(repeated.status_code,200,repeated.text)
            self.assertNotEqual(repeated.json()['workflow_definition_id'],workflow['id'])

    def test_unverified_evidence_does_not_become_material(self):
        fake=PlanningGateway();fake.bad_quote=True;main.runner.gateway=fake
        with TestClient(main.app) as client:
            client.get('/');client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
            category=client.post('/api/categories',json={'name':'Flow plan no sources'}).json()
            work=legacy_work(category['id'],'No verified source')
            Path(work['path'],'report.md').write_text('Collect facts and write a report with cited evidence.\n',encoding='utf-8')
            started=client.post(f"/api/works/{work['id']}/flow-plans",json={'goal':'Collect facts and write a report next week'})
            self.assertEqual(started.status_code,202,started.text)
            plan=started.json()
            for _ in range(200):
                plan=client.get('/api/flow-plans/'+plan['id']).json()
                if plan['status']=='NO_SOURCES':break
                time.sleep(.02)
            self.assertEqual(plan['status'],'NO_SOURCES',plan.get('error'))
            self.assertIn('Quoted text',plan['error'])
            self.assertEqual(plan['evidence'],[])
            self.assertEqual(client.get(f"/api/works/{work['id']}").json()['sources'],[])
            fake.bad_quote=False
            retried=client.post('/api/flow-plans/'+plan['id']+'/retry-research')
            self.assertEqual(retried.status_code,202,retried.text)
            for _ in range(200):
                plan=client.get('/api/flow-plans/'+plan['id']).json()
                if plan['status']=='DRAFT':break
                time.sleep(.02)
            self.assertEqual(plan['status'],'DRAFT',plan.get('error'))
            self.assertEqual(len(plan['evidence']),1)

    def test_web_search_is_restricted_to_research_run(self):
        fake=PlanningGateway();fake.web=True;main.runner.gateway=fake
        with (patch('app.flow_research.verified_url',return_value=('https://example.org/research','93.184.216.34')),
              patch('app.flow_research.fetch_public_document',return_value=('https://example.org/research','Public report evidence confirms the requested research.',{'kind':'text/html','bytes':68,'downloaded':False}))):
            with TestClient(main.app) as client:
                client.get('/');client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
                category=client.post('/api/categories',json={'name':'Flow web research'}).json()
                work=legacy_work(category['id'],'Web evidence')
                started=client.post(f"/api/works/{work['id']}/flow-plans",json={'goal':'Find current public research evidence for a report'})
                self.assertEqual(started.status_code,202,started.text)
                plan=started.json()
                for _ in range(200):
                    plan=client.get('/api/flow-plans/'+plan['id']).json()
                    if plan['status'] in {'DRAFT','NO_SOURCES','FAILED','INVALID'}:break
                    time.sleep(.02)
                self.assertEqual(plan['status'],'DRAFT',plan.get('error'))
                self.assertEqual(plan['evidence'][0]['material_type'],'RESOURCE')
                self.assertEqual(plan['evidence'][0]['url'],'https://example.org/research')
                self.assertEqual(fake.thread_settings[0].get('web_search'),'live')
                self.assertNotIn('web_search',fake.thread_settings[1])
                self.assertEqual(plan['research_run']['execution_profile']['permission'],'read-only')
                self.assertEqual(plan['generation_run']['execution_profile']['permission'],'read-only')

    def test_budget_review_can_continue_or_extend_only_on_request(self):
        fake=PlanningGateway();fake.pending=True;main.runner.gateway=fake
        with TestClient(main.app) as client:
            client.get('/');client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
            category=client.post('/api/categories',json={'name':'Research review'}).json()
            work=legacy_work(category['id'],'Research review')
            Path(work['path'],'report.md').write_text('Collect facts and write a report with cited evidence.\n',encoding='utf-8')
            def wait(plan_id,expected):
                for _ in range(200):
                    result=client.get('/api/flow-plans/'+plan_id).json()
                    if result['status'] in expected:return result
                    time.sleep(.02)
                self.fail('Research did not reach '+str(expected))
            first=client.post(f"/api/works/{work['id']}/flow-plans",json={'goal':'Collect facts and write a report next week'}).json()
            held=wait(first['id'],{'REVIEW_LIMIT','FAILED','NO_SOURCES'})
            self.assertEqual(held['status'],'REVIEW_LIMIT',held.get('error'))
            self.assertEqual(len(held['evidence']),1)
            self.assertEqual(held['research_budget']['pending_count'],1)
            self.assertEqual(len(fake.prompts),1)
            continued=client.post('/api/flow-plans/'+first['id']+'/continue-research')
            self.assertEqual(continued.status_code,202,continued.text)
            drafted=wait(first['id'],{'DRAFT','FAILED','INVALID'})
            self.assertEqual(drafted['status'],'DRAFT',drafted.get('error'))
            second=client.post(f"/api/works/{work['id']}/flow-plans",json={'goal':'Collect facts and write a report next month'}).json()
            held=wait(second['id'],{'REVIEW_LIMIT','FAILED','NO_SOURCES'})
            fake.pending=False
            extended=client.post('/api/flow-plans/'+second['id']+'/extend-research')
            self.assertEqual(extended.status_code,202,extended.text)
            drafted=wait(second['id'],{'DRAFT','FAILED','INVALID','REVIEW_LIMIT'})
            self.assertEqual(drafted['status'],'DRAFT',drafted.get('error'))
            self.assertEqual(drafted['research_budget_level'],1)

    def test_file_download_budget_stops_at_three(self):
        fake=PlanningGateway();fake.web=True;fake.web_many=True;main.runner.gateway=fake
        def canonical(url):return url,'93.184.216.34'
        def fetched(url,**kwargs):return url,'Public report evidence confirms the requested research.',{'kind':'application/pdf','bytes':5*1024*1024,'downloaded':True}
        with (patch('app.flow_research.verified_url',side_effect=canonical),
              patch('app.flow_research.fetch_public_document',side_effect=fetched) as fetch):
            with TestClient(main.app) as client:
                client.get('/');client.headers.update({'Origin':'http://testserver','X-Control-Token':main.ensure_token()})
                category=client.post('/api/categories',json={'name':'PDF budget'}).json()
                work=legacy_work(category['id'],'PDF budget')
                plan=client.post(f"/api/works/{work['id']}/flow-plans",json={'goal':'Find public PDF evidence for a report'}).json()
                for _ in range(200):
                    plan=client.get('/api/flow-plans/'+plan['id']).json()
                    if plan['status'] in {'REVIEW_LIMIT','NO_SOURCES','FAILED'}:break
                    time.sleep(.02)
                self.assertEqual(plan['status'],'REVIEW_LIMIT',plan.get('error'))
                self.assertEqual(len(plan['evidence']),3)
                self.assertEqual(plan['research_budget']['downloaded_files'],3)
                self.assertEqual(plan['research_budget']['downloaded_bytes'],15*1024*1024)
                self.assertEqual(plan['research_budget']['pending_count'],1)
                self.assertEqual(fetch.call_count,3)


if __name__=='__main__':unittest.main()
