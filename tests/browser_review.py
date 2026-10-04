"""Offline Chromium smoke against the real API with a FakeGateway.
Run: .venv/bin/python tests/browser_review.py
No sockets, account access or model calls: Playwright routes HTTP to TestClient.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_phase2 import Phase2Tests
from app import main
from playwright.sync_api import sync_playwright, expect


def run():
    Phase2Tests.setUpClass()
    fixture = Phase2Tests('test_cycle_validation_and_definition_crud')
    fixture.setUp()
    client = fixture.client
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, channel='chromium')
            page = browser.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route(request):
                parsed = urlsplit(request.request.url)
                path = parsed.path + ('?' + parsed.query if parsed.query else '')
                if parsed.path.endswith('/events'):
                    # SSE transport is tested separately against DB replay. Keep
                    # browser streams alive without blocking the sync route handler.
                    request.fulfill(status=200, content_type='text/event-stream', body=': heartbeat\n\n')
                    return
                headers = {k:v for k,v in request.request.headers.items() if k.lower() not in {'host','cookie','content-length','origin'}}
                if request.request.method not in {'GET','HEAD'}:
                    headers['Origin'] = 'http://testserver'
                response = client.request(request.request.method, path, headers=headers, content=request.request.post_data_buffer)
                forwarded = {k:v for k,v in response.headers.items() if k not in {'content-length','content-encoding','transfer-encoding'}}
                request.fulfill(status=response.status_code, headers=forwarded, body=response.content)
            page.route('**/*', route)
            page.goto('http://localhost/')
            page.wait_for_function('() => state.models.length > 0')
            page.evaluate('(id) => selectWork(id)', fixture.work['id'])
            page.locator('#tab-button-workflow').click()
            page.locator('#workflow-new').click()
            page.locator('#wf-editor-name').fill('Browser reviewed workflow')
            page.locator('#wf-task-name').fill('Browser task')
            page.locator('#wf-task-instruction').fill('write')
            page.locator('#wf-save').click()
            page.wait_for_timeout(100)
            assert not page.locator('#notice').inner_text(), page.locator('#notice').inner_text()
            assert not errors, errors
            expect(page.locator('#workflow-editor')).not_to_be_visible()
            expect(page.locator('#workflow-name')).to_have_text('Browser reviewed workflow')
            page.locator('#workflow-start').click()
            page.wait_for_function("() => wfState.run?.workflow_run.status === 'COMPLETED'")
            expect(page.locator('#workflow-tasks')).to_contain_text('완료')
            page.locator('#workflow-tasks').get_by_role('button',name='실행 기록 보기').click()
            expect(page.locator('#run-status')).to_contain_text('완료')
            expect(page.locator('#resume')).to_be_disabled()
            page.locator('#tab-button-workflow').click()
            page.locator('#workflow-tasks .task-more-actions summary').click()
            page.locator('#workflow-tasks').get_by_role('button',name='이 결과로 분기').click()
            page.locator('#branch-instruction').fill('branch output')
            page.locator('#branch-outputs input[type=text]').fill('branched.md')
            page.locator('#branch-execute').click()
            page.wait_for_function("() => wfState.run?.workflow_run.parent_workflow_run_id && wfState.run.workflow_run.status === 'COMPLETED'")
            expect(page.locator('#workflow-tasks')).to_contain_text('branched.md')
            # Preserve an in-progress editor during the ordinary Work refresh.
            page.locator('#workflow-edit').click()
            page.locator('#wf-task-instruction').fill('unsaved editor content')
            page.evaluate('(id) => selectWork(id,true)',fixture.work['id'])
            expect(page.locator('#wf-task-instruction')).to_have_value('unsaved editor content')
            page.locator('#wf-editor-close').click()
            # Exercise the two independent stream owners with a held task.
            completed_run_id = page.evaluate('state.run.id')
            fixture.barrier()
            definition = fixture.define([fixture.task('Held',instruction='BARRIER')])
            rid = fixture.start(definition)
            held = fixture.wait(rid, lambda d:any(t['status']=='RUNNING' for t in d['task_runs']))
            page.evaluate('(id) => wfSelectRun(id)',rid)
            page.evaluate('(id) => selectRun(id)',held['task_runs'][0]['run_id'])
            assert page.evaluate('!!wfState.stream && !!state.stream')
            fixture.release()
            fixture.wait(rid)
            # Selection responses deliberately resolve in reverse order.
            page.evaluate("""async ids => {
                wfClose(); closeStream();
                const real=api; const pending={};
                api=path=>new Promise(resolve=>pending[path]=resolve);
                const first=selectRun(ids[0]), second=selectRun(ids[1]);
                const b=await real('/runs/'+ids[1]);pending['/runs/'+ids[1]](b);await second;
                const a=await real('/runs/'+ids[0]);pending['/runs/'+ids[0]](a);await first;
                api=real;
                if(state.run.id!==ids[1])throw new Error('Stale Run response won');
            }""", [held['task_runs'][0]['run_id'], completed_run_id])
            # Template unresolved bindings remain visible until individually handled.
            source = client.post('/api/works/'+fixture.work['id']+'/sources',files={'file':('source.md',b'context','text/markdown')}).json()
            task = fixture.task('Template'); task['context_rule']={'source_ids':[source['id']]}
            definition = fixture.define([task])
            template=client.post('/api/workflows/'+definition['id']+'/templates',json={}).json()
            target=client.post('/api/works',json={'category_id':fixture.work['category_id'],'name':'Template target'}).json()
            clone=client.post('/api/workflow-templates/'+template['id']+'/clone',json={'target_work_id':target['id']}).json()
            page.evaluate('(id) => selectWork(id)',target['id'])
            page.evaluate('(data) => wfOpenEditor(data)',clone)
            expect(page.locator('#wf-unresolved')).to_contain_text('source.md')
            page.locator('#wf-unresolved').get_by_role('button',name='이 항목 제외').click()
            page.locator('#wf-editor-enabled').check()
            page.locator('#wf-save').click()
            expect(page.locator('#workflow-editor')).not_to_be_visible()
            page.reload();page.wait_for_function('() => state.models.length > 0')
            page.evaluate('(id) => selectWork(id)',target['id'])
            page.evaluate('(id) => wfSelectDefinition(id)',clone['id'])
            expect(page.locator('#workflow-start')).to_be_enabled()
            assert not errors, errors
            browser.close()
        print(json.dumps({'status':'PASS','checks':['definition editor/save/start','task Run controls','branch output editing', 'editor preserved on refresh','independent Run/Workflow streams','stale Run response ignored','individual Template exclusion and reload'], 'page_errors':errors},ensure_ascii=False))
    finally:
        fixture.tearDown()
        Phase2Tests.tearDownClass()


if __name__ == '__main__':
    run()
