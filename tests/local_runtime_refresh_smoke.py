"""Local Codex history and Runtime usage refresh through the real browser UI."""
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conversation_ux_smoke import ConversationFake
from test_phase1 import Phase1Tests, WORKSPACES
from app import main
from playwright.sync_api import expect, sync_playwright


class LocalFake(ConversationFake):
    def __init__(self, root):
        super().__init__(root)
        self.percent = 17
        self.invalidations = 0
    def invalidate_runtime_status(self):
        self.invalidations += 1
    async def runtime_status(self):
        return {'connection': 'CONNECTED', 'rate_limits': {'status': 'AVAILABLE',
            'data': {'primary': {'name': 'Account', 'primary': {'used_percent': self.percent}},
                     'buckets': {}, 'ordinary_usage_allowed': True},
            'observed_at': '2026-09-30T00:00:00Z'}}


def run():
    Phase1Tests.setUpClass()
    client = Phase1Tests.client
    root = Path(WORKSPACES.name).resolve() / 'local-runtime-refresh'
    root.mkdir()
    fake = LocalFake(root)
    main.runner.gateway = fake
    errors = []
    try:
        category = client.post('/api/categories', json={'name': 'Local Runtime Refresh'}).json()
        created = client.post('/api/works', json={'name': 'AI Control Center', 'category_id': category['id'],
            'workspace_mode': 'LINKED', 'workspace_path': str(root)})
        assert created.status_code == 201, created.text
        work = created.json()
        imported = client.post(f'/api/works/{work["id"]}/runtime-conversations/import',
            json={'runtime_thread_id': 'external-codex'})
        assert imported.status_code == 201, imported.text
        thread = imported.json()
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
            expect(page.locator('[data-disclosure="dashboard-runtime"] > summary')).to_contain_text('17% 사용')
            page.evaluate('(id) => selectWork(id)', work['id'])
            page.locator('#tab-button-execution').click()
            page.locator('#execution-thread-picker').click()
            page.locator(f'.thread-choice[data-thread-key="{thread["id"]}"]').click()
            expect(page.locator('#conversation-thread-meta')).to_contain_text('Earlier CLI question')
            running = {'id': 'terminal-new-turn', 'status': 'inProgress',
                'instruction': 'Current terminal request', 'final_text': '', 'started_at': int(time.time())}
            fake.threads['external-codex']['turns'].append(running)
            fake.threads['external-codex']['updated_at'] = int(time.time())
            page.reload()
            expect(page.locator('#conversation-thread-meta')).to_contain_text('터미널 Codex 실행 중', timeout=12000)
            expect(page.locator('#conversation-thread-meta')).to_contain_text('Current terminal request')
            active = client.get('/api/operations/dashboard?work_id=' + work['id']).json()
            assert any(item['entity_type'] == 'THREAD' for item in active['states']['RUNNING']['items'])
            running.update(status='completed', final_text='Current terminal answer', completed_at=int(time.time()))
            fake.percent = 42
            page.locator('#refresh').click()
            expect(page.locator('#conversation-thread-meta')).to_contain_text('2 Turn · 2 Run', timeout=12000)
            expect(page.locator('#conversation-history')).to_contain_text('Current terminal answer')
            page.locator('#dashboard-button').click()
            expect(page.locator('[data-disclosure="dashboard-runtime"] > summary')).to_contain_text('42% 사용')
            fake.percent = 55
            page.reload()
            expect(page.locator('[data-disclosure="dashboard-runtime"] > summary')).to_contain_text('55% 사용')
            repeat = client.post('/api/runtime-conversations/sync')
            assert repeat.status_code == 200, repeat.text
            assert repeat.json()['new_turns'] == 0
            assert len(client.get(f'/api/works/{work["id"]}').json()['runs']) == 2
            assert fake.invalidations >= 3
            assert not errors, errors
            browser.close()
        print('PASS: reload reads active local Turn; completed Turn imports once; refresh and reload show fresh Runtime usage. Isolated data, FakeGateway, no real model calls.')
    finally:
        Phase1Tests.tearDownClass()


if __name__ == '__main__':
    run()
