"""Minimal browser path for goal generation, edit, approval and linked editors."""
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
            page.locator('#tab-button-flow-plans').click()
            page.locator('#flow-plan-goal').fill('Collect facts and write a report next week')
            page.locator('#flow-plan-generate').click()
            expect(page.locator('#flow-plan-status')).to_contain_text('초안',timeout=15000)
            expect(page.locator('#flow-plan-evidence-list')).to_contain_text('Report evidence')
            expect(page.locator('#flow-plan-graph')).to_contain_text('Collect')
            page.locator('#flow-plan-editor > summary').click()
            page.locator('#flow-plan-edit-name').fill('Edited browser flow')
            page.locator('#flow-plan-save').click()
            expect(page.locator('#flow-plan-title')).to_have_text('Edited browser flow')
            page.locator('#flow-plan-approve').click()
            expect(page.locator('#flow-plan-status')).to_contain_text('승인됨')
            page.locator('#flow-plan-open-workflow').click()
            expect(page.locator('#workflow-editor')).to_be_visible()
            page.locator('#wf-editor-close').click()
            page.locator('#tab-button-flow-plans').click()
            page.locator('#flow-plan-open-schedule').click()
            expect(page.locator('#schedule-editor')).to_be_visible()
            expect(page.locator('#schedule-editor h2')).to_have_text('Workflow 예약 편집')
            page.locator('#schedule-close').click()
            assert not errors,errors
            browser.close()
    finally:
        Phase1Tests.tearDownClass()


if __name__=='__main__':run()
