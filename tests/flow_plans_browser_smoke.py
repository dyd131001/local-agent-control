"""Browser path for project preview and editing an unpublished flow draft."""
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_phase1 import Phase1Tests, WORKSPACES
from flow_plans_smoke import PlanningGateway
from app import main
from playwright.sync_api import expect, sync_playwright


def run():
    Phase1Tests.setUpClass()
    client=Phase1Tests.client
    main.runner.gateway=PlanningGateway()
    errors=[]
    try:
        category=client.post('/api/categories',json={'name':'Flow plan UI'}).json()
        folder=Path(WORKSPACES.name)/'flow-plan-ui';folder.mkdir()
        (folder/'report.md').write_text('Collect facts and write a report with cited evidence.\n',encoding='utf-8')
        (folder/'src').mkdir();(folder/'src'/'demo.py').write_text('print("hello")\n',encoding='utf-8')
        created=client.post('/api/works',json={'name':'Plan Work','category_id':category['id'],
            'workspace_mode':'LINKED','workspace_path':str(folder)})
        assert created.status_code==201,created.text
        work=created.json()
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,channel='chromium')
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.on('pageerror',lambda error:errors.append(str(error)))
            def route(request):
                parsed=urlsplit(request.request.url)
                path=parsed.path+('?' + parsed.query if parsed.query else '')
                if parsed.path.endswith('/events'):
                    request.fulfill(status=200,content_type='text/event-stream',body=': heartbeat\n\n');return
                headers={k:v for k,v in request.request.headers.items() if k.lower() not in {'host','cookie','content-length','origin'}}
                if request.request.method not in {'GET','HEAD'}:headers['Origin']='http://testserver'
                response=client.request(request.request.method,path,headers=headers,content=request.request.post_data_buffer)
                forwarded={k:v for k,v in response.headers.items() if k not in {'content-length','content-encoding','transfer-encoding'}}
                request.fulfill(status=response.status_code,headers=forwarded,body=response.content)
            page.route('**/*',route)
            page.goto('http://localhost/')
            page.wait_for_function('() => state.models.length > 0 && window.flowPlans')
            page.evaluate('(id) => selectWork(id)',work['id'])
            before=len(client.get('/api/works/'+work['id']).json()['sources'])
            page.locator('#tab-button-materials').click()
            page.locator('#project-path-open').click()
            expect(page.locator('#project-picker-read')).to_contain_text('프로젝트 전체')
            page.locator('#project-picker-read').get_by_role('button',name='제거').click()
            page.locator('#project-picker-search').get_by_role('button',name='제거').click()
            page.locator('#project-picker-list [data-project-path="src"] input').check()
            page.locator('#project-picker-mode').select_option('search_paths')
            page.locator('#project-picker-list [data-project-path="src"] input').check()
            page.locator('#project-picker-preview').click()
            expect(page.locator('#project-picker-count')).to_contain_text('읽기 포함 1개 · 탐색 후보 1개')
            expect(page.locator('#project-picker-preview-list')).to_contain_text('src/demo.py')
            page.locator('#project-picker-apply').click()
            assert len(client.get('/api/works/'+work['id']).json()['sources'])==before
            page.locator('#tab-button-flow-plans').click()
            page.locator('#flow-plan-goal').fill('Collect facts and write a report next week')
            page.locator('#flow-plan-generate').click()
            expect(page.locator('#flow-plan-status')).to_contain_text('초안',timeout=15000)
            expect(page.locator('#flow-plan-evidence-list')).to_contain_text('Report evidence')
            expect(page.locator('#flow-plan-graph')).to_contain_text('Collect')
            plan=client.get('/api/works/'+work['id']+'/flow-plans').json()[0]
            detail=client.get('/api/flow-plans/'+plan['id']).json();draft=detail['plan']
            draft['workflow']['unresolved_bindings']=[
                {'task_id':'collect','kind':'SOURCE','title':'project source','reference_path':str(folder)},
                {'task_id':'write','name':'other binding','binding':{'input_key':'other'}}]
            saved=client.put('/api/flow-plans/'+plan['id'],json={'expected_revision':detail['revision'],'plan':draft})
            assert saved.status_code==200,saved.text
            page.locator('#flow-plan-refresh').click()
            page.locator('#flow-plan-open-workflow').click()
            expect(page.locator('#workflow-editor')).to_be_visible()
            expect(page.locator('#wf-draft-meta')).to_contain_text('승인 전 초안')
            expect(page.locator('#wf-editor-order')).to_contain_text('Collect')
            expect(page.locator('#wf-task-unresolved')).to_contain_text('project source')
            page.locator('#task-tabs [data-task-tab="input"]').click()
            page.locator('#wf-use-preview-paths').click()
            expect(page.locator('#wf-task-scope-summary')).to_contain_text('읽기 권한 범위: src')
            expect(page.locator('#wf-task-scope-summary')).to_contain_text('탐색 범위: src')
            page.locator('#wf-open-project-picker').click()
            expect(page.locator('#project-picker-list [data-project-path="src"] input')).to_be_checked()
            page.locator('#project-picker-close').click()
            page.locator('#wf-task-unresolved').get_by_role('button',name='경로 입력으로 해결').click()
            page.locator('#wf-editor-name').fill('Edited browser flow')
            page.locator('#wf-save').click()
            expect(page.locator('#wf-draft-meta')).to_contain_text('revision')
            expect(page.locator('#wf-draft-approve')).to_be_disabled()
            assert client.get(f"/api/works/{work['id']}/workflows").json()==[]
            revised=client.get('/api/flow-plans/'+plan['id']).json()
            assert revised['status']=='DRAFT' and revised['revision']>saved.json()['revision']
            assert revised['plan']['workflow']['tasks'][0]['context_rule']['read_paths']==['src']
            assert revised['plan']['workflow']['tasks'][0]['context_rule']['search_paths']==['src']
            assert len(revised['plan']['workflow']['unresolved_bindings'])==1
            page.locator('#wf-editor-close').click()
            page.locator('#workflow-draft-list').get_by_role('button',name='초안 검토·편집').click()
            expect(page.locator('#wf-editor-name')).to_have_value('Edited browser flow')
            expect(page.locator('#wf-draft-meta')).to_contain_text(f"revision {revised['revision']}")
            page.locator('#wf-editor-close').click()
            assert not errors,errors
            browser.close()
    finally:
        Phase1Tests.tearDownClass()


if __name__=='__main__':run()
