"""One offline Thread → history → Continue → streaming Run browser flow.
Runtime discovery/import uses a FakeGateway and public SDK adapter spies.
Run: .venv/bin/python tests/conversation_ux_smoke.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_phase1 import Phase1Tests, FakeGateway, WORKSPACES
from app import main, gateway as gateway_module
from playwright.sync_api import expect, sync_playwright


class ConversationFake(FakeGateway):
    def __init__(self, root):
        super().__init__()
        self.root, self.hold_stream, self.supported = root, True, True
        self.threads['external-codex'] = {'id': 'external-codex', 'cwd': str(root), 'name': 'Earlier Codex conversation',
            'model': 'runtime-model', 'reasoning': 'low', 'created_at': 1790000000, 'updated_at': 1790000010,
            'turns': [{'id': 'external-turn', 'status': 'completed', 'instruction': 'Earlier CLI question',
                       'final_text': 'Earlier CLI answer', 'started_at': 1790000000, 'completed_at': 1790000010}]}
        self.threads['foreign-codex'] = {**self.threads['external-codex'], 'id': 'foreign-codex', 'cwd': str(root.parent)}
        self.threads['active-codex'] = {**self.threads['external-codex'], 'id': 'active-codex',
                                      'turns': [{'id': 'busy-turn', 'status': 'inProgress'}]}
    def conversation_capabilities(self):
        return {'discovery': self.supported, 'resume': self.supported}
    async def list_threads(self, cwd, cursor=None):
        return {'threads': [{'id': 'external-codex', 'title': 'Earlier Codex conversation', 'cwd': str(self.root),
                             'updated_at': 1790000010, 'status': {'type': 'notLoaded'}, 'ephemeral': False},
                            {'id': 'foreign-codex', 'title': 'Foreign conversation', 'cwd': str(self.root.parent)}],
                'next_cursor': None}
    async def events(self, rid):
        h = self.handles[rid]
        streaming = 'NEW_STREAM' in h['prompt']
        answer = '이번에는 실제 앱입니다.' if streaming else 'Past answer: ' + h['prompt'].split('\n')[0]
        if streaming:
            for delta in ['이번', '에는 ', '실제']:
                yield {'type': 'ACTIVITY', 'payload': {'item_id': 'reply', 'delta': delta}}
                await asyncio.sleep(.02)
            yield {'type': 'ACTIVITY', 'payload': {'item_id': 'command', 'output': 'COMMAND OUTPUT MUST STAY OUT OF THE ANSWER'}}
            while self.hold_stream:
                await asyncio.sleep(.01)
            yield {'type': 'ACTIVITY', 'payload': {'item_id': 'reply', 'delta': ' 앱입니다.'}}
        (Path(self.threads[h['thread']]['cwd']) / 'artifacts' / 'result.md').write_text('result')
        h['turn'].update(status='completed', final_text=answer)
        yield {'type': 'ACTIVITY', 'payload': {'item_id': 'reply', 'phase': 'final_answer', 'text': answer}}
        yield {'type': 'terminal', 'status': 'completed', 'error': None}


async def adapter_probe(root):
    calls = []
    class SDK:
        async def thread_list(self, **kwargs):
            calls.append(kwargs)
            return {'data': [{'id': 'sdk-thread', 'cwd': str(root), 'name': 'SDK title', 'preview': 'preview',
                              'ephemeral': False, 'updatedAt': 1790000000, 'status': {'type': 'idle'}}], 'nextCursor': 'cursor'}
        async def thread_resume(self, *args, **kwargs):
            raise AssertionError('Metadata probe must not resume a Thread')
    class ReadHandle:
        def __init__(self, *args): pass
        async def read(self, **kwargs):
            assert kwargs == {'include_turns': True}
            return {'thread': {'id': 'sdk-thread', 'cwd': str(root), 'model': 'runtime-model', 'reasoningEffort': 'low',
                'turns': [{'id': 'sdk-turn', 'status': 'completed', 'startedAt': 1790000000, 'completedAt': 1790000010,
                    'items': [{'type': 'userMessage', 'content': [{'type': 'text', 'text': 'SDK question'}]},
                              {'type': 'agentMessage', 'phase': 'final_answer', 'text': 'SDK answer'}]}]}}
    gateway = gateway_module.CodexGateway()
    gateway.codex = SDK()
    assert gateway.conversation_capabilities() == {'discovery': True, 'resume': True}
    listed = await gateway.list_threads(str(root))
    assert listed['threads'][0]['title'] == 'SDK title' and listed['next_cursor'] == 'cursor'
    assert calls[0]['cwd'].root == str(root) and calls[0]['limit'] == 50
    with patch.object(gateway_module, 'AsyncThread', ReadHandle):
        history = await gateway.read_thread('sdk-thread')
    assert history['cwd'] == str(root)
    assert history['turns'][0]['instruction'] == 'SDK question'
    assert history['turns'][0]['final_text'] == 'SDK answer'


def run():
    Phase1Tests.setUpClass()
    client = Phase1Tests.client
    root = Path(WORKSPACES.name).resolve() / 'conversation-ux'
    root.mkdir()
    fake = ConversationFake(root)
    main.runner.gateway = fake
    errors = []
    try:
        asyncio.run(adapter_probe(root))
        category = client.post('/api/categories', json={'name': 'Conversation UX'}).json()
        work = client.post('/api/works', json={'name': 'Conversation UX', 'category_id': category['id'],
            'workspace_mode': 'LINKED', 'workspace_path': str(root)}).json()
        def post(body):
            response = client.post('/api/works/' + work['id'] + '/conversations', json=body)
            assert response.status_code == 202, response.text
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                detail = client.get('/api/runs/' + response.json()['id']).json()
                if detail['run']['status'] not in {'CREATED', 'RUNNING'}:
                    assert detail['run']['status'] == 'COMPLETED', detail
                    return detail['run']
                time.sleep(.02)
            raise AssertionError('Fake Run timed out')
        first = post({'instruction': 'Past request one'})
        second = post({'action': 'CONTINUE', 'thread_id': first['conversation_id'], 'instruction': 'Past request two'})
        post({'instruction': 'Separate recent conversation'})
        fake.supported = False
        assert client.get('/api/conversation-capabilities').json() == {'discovery': False, 'resume': False}
        assert client.get('/api/works/' + work['id'] + '/runtime-conversations').status_code == 501
        fake.supported = True
        route_prefix = '/api/works/' + work['id'] + '/runtime-conversations'
        assert client.post(route_prefix + '/import', json={'runtime_thread_id': 'foreign-codex'}).status_code == 403
        assert client.post(route_prefix + '/import', json={'runtime_thread_id': 'active-codex'}).status_code == 409
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
                headers = {k: v for k, v in request.request.headers.items() if k.lower() not in {'host', 'cookie', 'content-length', 'origin'}}
                if request.request.method not in {'GET', 'HEAD'}: headers['Origin'] = 'http://testserver'
                response = client.request(request.request.method, path, headers=headers, content=request.request.post_data_buffer)
                forwarded = {k: v for k, v in response.headers.items() if k not in {'content-length', 'content-encoding', 'transfer-encoding'}}
                request.fulfill(status=response.status_code, headers=forwarded, body=response.content)
            page.route('**/*', route)
            page.goto('http://localhost/')
            page.wait_for_function('() => state.models.length > 0')
            page.evaluate('(id) => selectWork(id)', work['id'])
            page.locator('#tab-button-execution').click()
            expect(page.locator('.thread-choice')).to_have_count(2)
            for action in ['CONTINUE', 'QUERY', 'FORK', 'COMPACT', 'HANDOFF']:
                expect(page.locator(f'[data-conversation-action="{action}"]')).to_be_disabled()
            page.locator(f'.thread-choice[data-thread-key="{first["conversation_id"]}"]').click()
            expect(page.locator('.thread-choice.selected')).to_have_count(1)
            expect(page.locator('#conversation-thread-meta')).to_contain_text('Past request two')
            expect(page.locator('#conversation-thread-meta')).to_contain_text('2 Turn · 2 Run')
            page.locator('#conversation-history .history-turn').first.locator(':scope > summary').click()
            expect(page.locator('#conversation-history')).to_contain_text('Past request one')
            expect(page.locator('#conversation-history')).to_contain_text('Past answer: Past request one')
            expect(page.locator('#run-instruction')).to_have_text('Past request two')
            expect(page.locator('#manifest')).not_to_be_visible()
            expect(page.locator('#events')).not_to_be_visible()
            for action in ['CONTINUE', 'QUERY', 'FORK', 'COMPACT', 'HANDOFF']:
                expect(page.locator(f'[data-conversation-action="{action}"]')).to_be_enabled()
            page.locator('[data-conversation-action="CONTINUE"]').click()
            page.locator('#instruction').fill('NEW_STREAM: continue the selected conversation')
            page.locator('#execute').click()
            expect(page.locator('#run-instruction')).to_have_text('NEW_STREAM: continue the selected conversation')
            expect(page.locator('#final-answer')).to_have_text('이번에는 실제', timeout=12000)
            assert '[ACTIVITY]' not in page.locator('#final-answer').inner_text()
            fake.hold_stream = False
            page.wait_for_function("() => state.run?.status === 'COMPLETED'", timeout=15000)
            expect(page.locator('#final-answer')).to_have_text('이번에는 실제 앱입니다.')
            continued = client.get('/api/runs/' + page.evaluate('state.run.id')).json()['run']
            assert continued['thread_id'] == first['thread_id'], 'Continue must keep the selected Runtime Thread'
            assert continued['conversation_id'] == first['conversation_id']
            expect(page.locator('#conversation-thread-meta')).to_contain_text('3 Turn · 3 Run')
            page.locator('#conversation-discovery > summary').click()
            page.locator('#conversation-discover').click()
            expect(page.locator('#conversation-discovered .discovered-thread')).to_have_count(1)
            page.locator('#conversation-discovered').get_by_role('button', name='이 Work에 연결', exact=True).click()
            expect(page.locator('#conversation-selected')).to_contain_text('Earlier Codex conversation')
            expect(page.locator('#conversation-history')).to_contain_text('Earlier CLI question')
            expect(page.locator('#conversation-history')).to_contain_text('Earlier CLI answer')
            expect(page.locator('#run-instruction')).to_have_text('Earlier CLI question')
            expect(page.locator('#final-answer')).to_have_text('Earlier CLI answer')
            page.locator('[data-conversation-action="CONTINUE"]').click()
            page.locator('#instruction').fill('Continue the imported conversation')
            page.locator('#execute').click()
            page.wait_for_function("() => state.run?.status === 'COMPLETED' && state.run.thread_id === 'external-codex'", timeout=15000)
            expect(page.locator('#run-instruction')).to_have_text('Continue the imported conversation')
            replay = client.post(route_prefix + '/import', json={'runtime_thread_id': 'external-codex'})
            assert replay.status_code == 201
            assert len(client.get('/api/works/' + work['id'] + '/conversations').json()['threads']) == 3
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow'
            assert not errors, errors
            browser.close()
        print('PASS: selected Thread history → Continue on same Thread → accumulated streaming answer + visible instruction; supported discovery/import/resume and unsupported/foreign/active guards. No real model calls.')
    finally:
        fake.hold_stream = False
        Phase1Tests.tearDownClass()


if __name__ == '__main__':
    run()
