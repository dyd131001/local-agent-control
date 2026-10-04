"""Minimal common UI navigation and Category management flow, using isolated data."""
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_phase1 import Phase1Tests, WORKSPACES
from test_phase2 import WorkflowFake
from app import main
from playwright.sync_api import expect, sync_playwright


def run():
    Phase1Tests.setUpClass()
    client = Phase1Tests.client
    main.runner.gateway = WorkflowFake()
    errors = []
    try:
        category = client.post('/api/categories', json={'name': 'Common UI'}).json()
        works = []
        for name in ['First Work', 'Second Work']:
            folder = Path(WORKSPACES.name) / name
            folder.mkdir()
            created = client.post('/api/works', json={'name': name, 'category_id': category['id'],
                'workspace_mode': 'LINKED', 'workspace_path': str(folder)})
            assert created.status_code == 201, created.text
            works.append(created.json())
        work = works[0]
        source = client.post('/api/works/' + work['id'] + '/sources',
            files={'file': ('reference.md', b'# Reference')}, data={'context': 'true'}).json()
        defined = client.post('/api/works/' + work['id'] + '/workflows', json={
            'name': 'Review flow', 'description': 'A flow for the common UI smoke check', 'tasks': [{
                'id': 'common-task', 'name': 'Create result', 'instruction': 'produce a result',
                'model': 'runtime-model', 'reasoning': 'low', 'review_policy': 'APPROVAL_REQUIRED',
                'output_rule': [{'output_key': 'result', 'path': 'result.md', 'required': True}]}]})
        assert defined.status_code == 201, defined.text
        definition = defined.json()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, channel='chromium')
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))

            def route(request):
                parsed = urlsplit(request.request.url)
                path = parsed.path + ('?' + parsed.query if parsed.query else '')
                if parsed.path.endswith('/events'):
                    request.fulfill(status=200, content_type='text/event-stream', body=': heartbeat\n\n')
                    return
                headers = {k: v for k, v in request.request.headers.items()
                    if k.lower() not in {'host', 'cookie', 'content-length', 'origin'}}
                if request.request.method not in {'GET', 'HEAD'}:
                    headers['Origin'] = 'http://testserver'
                response = client.request(request.request.method, path, headers=headers,
                    content=request.request.post_data_buffer)
                forwarded = {k: v for k, v in response.headers.items()
                    if k not in {'content-length', 'content-encoding', 'transfer-encoding'}}
                request.fulfill(status=response.status_code, headers=forwarded, body=response.content)

            page.route('**/*', route)
            page.goto('http://localhost/')
            page.wait_for_function('() => state.models.length > 0 && window.uiPresentation')
            page.locator('#manage-categories').click()
            row = page.locator(f'[data-category-id="{category["id"]}"]')
            expect(row).to_contain_text('포함 Work')
            page.locator('#category-management-search').fill('absent')
            expect(page.locator('#category-management-list')).to_contain_text('검색 조건에 맞는')
            page.locator('#category-management-search').fill('Common')
            row.get_by_role('button', name='상세 · Work 관리').click()
            expect(page.locator('#category-detail-meta')).to_contain_text('2개')
            page.locator('#category-work-search').fill('First')
            expect(page.locator('#category-work-list .ui-managed-row')).to_have_count(1)
            first = page.locator(f'#category-work-list [data-work-id="{work["id"]}"]')
            expect(first.locator('.ui-path')).not_to_be_visible()
            first.locator('details > summary').click()
            first.get_by_role('button', name='작업 보관').click()
            page.locator('#category-work-filter').select_option('ARCHIVED')
            expect(first.locator('.managed-work-main')).to_be_disabled()
            if not first.locator('details').evaluate('(el) => el.open'):
                first.locator('details > summary').click()
            first.get_by_role('button', name='보관 해제', exact=True).click()
            expect(first.locator('.managed-work-main')).to_be_enabled()
            page.locator('#category-work-search').fill('')
            page.locator('#category-toggle-active').click()
            expect(page.locator('#category-disabled-note')).to_be_visible()
            for item in page.locator('#category-work-list .managed-work-main').all():
                expect(item).to_be_disabled()
            page.locator('#category-toggle-active').click()
            expect(page.locator('#category-disabled-note')).not_to_be_visible()
            page.screenshot(path='/private/tmp/control-center-category-ui.png', full_page=True)
            first.locator('.managed-work-main').click()
            for tab in ['overview', 'execution', 'workflow', 'materials', 'artifacts', 'tools', 'schedule', 'review', 'activity']:
                page.locator('#tab-button-' + tab).click()
                expect(page.locator('#tab-' + tab)).to_be_visible()
                expect(page.locator('#work-tabs .active')).to_have_count(1)
                if tab != 'execution':
                    expect(page.locator('#tab-' + tab + ' .ui-toolbar.ui-sticky').first).to_be_visible()
            page.locator('#tab-button-materials').click()
            expect(page.locator(f'#context-list input[value="{source["id"]}"]')).to_be_checked()
            expect(page.locator('#materials-selection-summary')).to_contain_text('선택 자료 1')
            expect(page.locator('#context-list .ui-path')).not_to_be_visible()
            page.locator('#context-list details > summary').click()
            expect(page.locator('#context-list .ui-path')).to_be_visible()
            expect(page.locator(f'#context-list input[value="{source["id"]}"]')).to_be_checked()
            page.locator('#context-list details > summary').click()
            page.locator('#tab-button-workflow').click()
            page.locator(f'[data-definition-id="{definition["id"]}"] button').click()
            expect(page.locator('#workflow-name')).to_have_text('Review flow')
            expect(page.locator('#workflow-description')).not_to_be_visible()
            page.locator('#workflow-start').click()
            expect(page.locator('#workflow-progress')).to_contain_text('1 / 1 Task 완료', timeout=15000)
            page.locator('#tab-button-review').click()
            expect(page.locator('#review-view-summary')).to_contain_text('1개', timeout=12000)
            expect(page.locator('#approval-inbox .ui-warning')).to_be_visible()
            expect(page.locator('#approval-inbox select')).not_to_be_visible()
            page.locator('#approval-inbox textarea').fill('Keep this review note')
            page.locator('#approval-inbox details > summary').click()
            page.locator('#approval-inbox select').select_option('CATEGORY')
            page.locator('#review-refresh').click()
            expect(page.locator('#approval-inbox textarea')).to_have_value('Keep this review note')
            expect(page.locator('#approval-inbox select')).to_be_visible()
            expect(page.locator('#approval-inbox select')).to_have_value('CATEGORY')
            page.locator('#tab-button-schedule').click()
            page.locator('#schedule-workflow-actions > summary').click()
            page.locator('#schedule-workflow').select_option(definition['id'])
            page.locator('#schedule-create').click()
            expect(page.locator('#schedule-editor')).to_be_visible()
            page.locator('#schedule-close').click()
            page.locator('#tab-button-artifacts').click()
            expect(page.locator('#artifacts .ui-list-row')).to_have_count(1)
            page.locator('#artifacts button').first.click()
            expect(page.locator('#preview')).to_be_visible()
            page.locator('#close-preview').click()
            page.locator('#tab-button-activity').click()
            expect(page.locator('#activity-view-summary')).to_contain_text('실행 이력 1개')
            page.set_viewport_size({'width': 390, 'height': 844})
            for tab in ['overview', 'workflow', 'materials', 'artifacts', 'tools', 'schedule', 'review', 'activity']:
                page.locator('#tab-button-' + tab).click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), tab + ' mobile overflow'
            page.screenshot(path='/private/tmp/control-center-common-ui-mobile.png', full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.locator('#tab-button-materials').click()
            page.screenshot(path='/private/tmp/control-center-common-ui.png', full_page=True)
            assert not errors, errors
            browser.close()
        print('PASS: Category search / filters / archive / reactivation; all tabs; materials → Workflow → review; schedule action / artifact preview; narrow viewport. FakeGateway and isolated data only.')
    finally:
        Phase1Tests.tearDownClass()


if __name__ == '__main__':
    run()
