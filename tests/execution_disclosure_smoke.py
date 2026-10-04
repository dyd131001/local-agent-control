"""One offline execution flow against the real API with an isolated FakeGateway."""
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conversation_ux_smoke import ConversationFake
from test_phase1 import Phase1Tests, WORKSPACES
from app import main
from playwright.sync_api import expect, sync_playwright


def run():
    Phase1Tests.setUpClass()
    client = Phase1Tests.client
    root = Path(WORKSPACES.name).resolve() / 'execution-disclosure'
    root.mkdir()
    fake = ConversationFake(root)
    main.runner.gateway = fake
    errors = []
    try:
        category = client.post('/api/categories', json={'name': 'Execution UX'}).json()
        work = client.post('/api/works', json={'name': 'Execution UX', 'category_id': category['id'],
            'workspace_mode': 'LINKED', 'workspace_path': str(root)}).json()
        uploaded = client.post('/api/works/' + work['id'] + '/sources',
            files={'file': ('notes.md', b'# Selected reference')}, data={'context': 'true'})
        assert uploaded.status_code == 201, uploaded.text
        source = uploaded.json()
        seeded = client.post('/api/works/' + work['id'] + '/conversations',
            json={'instruction': 'Earlier request'})
        assert seeded.status_code == 202, seeded.text
        first = seeded.json()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if client.get('/api/runs/' + first['id']).json()['run']['status'] == 'COMPLETED':
                break
            time.sleep(.02)
        else:
            raise AssertionError('Seed Run timed out')
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
            page.evaluate('(id) => selectWork(id)', work['id'])
            page.locator('#tab-button-execution').click()
            expect(page.locator('#request-queue-panel')).not_to_be_visible()
            for selector in ['#execution-settings-disclosure', '#conversation-browser-disclosure',
                             '#run-context-disclosure', '#run-debug-disclosure', '#execution-history-disclosure']:
                assert not page.locator(selector).evaluate('(el) => el.open'), selector
            assert page.locator('#execute').evaluate('(el) => el.form.id') == 'request-form'
            page.locator('#execution-thread-picker').click()
            page.locator(f'.thread-choice[data-thread-key="{first["conversation_id"]}"]').click()
            expect(page.locator('#conversation-selected')).to_contain_text('Earlier request')
            expect(page.locator('#composer-title')).to_have_text('기존 대화 계속')
            expect(page.locator('#conversation-panel')).not_to_be_visible()
            instruction = 'NEW_STREAM: continue the selected conversation with notes'
            page.locator('#instruction').fill(instruction)
            expect(page.locator('#selected-materials-summary')).to_contain_text('선택 자료 1')
            expect(page.locator('#execution-inheritance')).to_contain_text('runtime-model')
            page.locator('.selection-summary [data-tab="materials"]').click()
            expect(page.locator(f'#context-list input[value="{source["id"]}"]')).to_be_checked()
            page.locator('#tab-materials .view-toolbar [data-tab="execution"]').click()
            expect(page.locator('#instruction')).to_have_value(instruction)
            page.locator('#execute').click()
            expect(page.locator('#run-instruction')).to_have_text(instruction)
            expect(page.locator('#final-answer')).to_have_text('이번에는 실제', timeout=12000)
            expect(page.locator('#run-status')).to_contain_text('실행 중')
            expect(page.locator('#events')).not_to_be_visible()
            expect(page.locator('#manifest')).not_to_be_visible()
            assert '[ACTIVITY]' not in page.locator('#final-answer').inner_text()
            assert page.evaluate("!!(document.querySelector('#final-answer').compareDocumentPosition(document.querySelector('#run-debug-disclosure')) & Node.DOCUMENT_POSITION_FOLLOWING)")
            running_id = page.evaluate('state.run.id')
            page.locator('#request-condition').select_option('AFTER_RUN_SUCCEEDED')
            expect(page.locator('#request-predecessor')).to_have_value(running_id)
            page.locator('#instruction').fill('Follow up after the current Run succeeds')
            page.locator('#execute').click()
            expect(page.locator('#request-queue-summary')).to_have_text('후속 작업 1개', timeout=12000)
            expect(page.locator('#request-queue-list')).not_to_be_visible()
            page.locator('#request-queue-panel > summary').click()
            expect(page.locator('#request-queue-list')).to_contain_text('Follow up after the current Run succeeds')
            expect(page.locator('#request-queue-list')).to_contain_text('Run 성공 후')
            page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
            assert page.locator('#execute').evaluate('(el) => {const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}'), 'Sticky action is out of view'
            assert page.locator('#run-status').evaluate('(el) => {const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}'), 'Sticky status is out of view'
            fake.hold_stream = False
            page.wait_for_function("() => state.run?.id === '" + running_id + "' && state.run.status === 'COMPLETED'", timeout=15000)
            expect(page.locator('#final-answer')).to_have_text('이번에는 실제 앱입니다.')
            assert not errors, errors
            browser.close()
        print('PASS: Thread → instruction → selected materials → execute → visible request / accumulated response → compact expandable Queue; sticky action / status. Isolated data, FakeGateway, no real model calls.')
    finally:
        fake.hold_stream = False
        Phase1Tests.tearDownClass()


if __name__ == '__main__':
    run()
