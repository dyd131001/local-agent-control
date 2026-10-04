"""One offline Workspace/Materials/Permission browser flow. No model calls.
Run: .venv/bin/python tests/workspace_ux_smoke.py
Native OS dialogs are mocked; real API registration and Run preparation are used.
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_phase1 import Phase1Tests, ROOT, WORKSPACES
from app import main, storage_api
from playwright.sync_api import expect, sync_playwright


def run():
    Phase1Tests.setUpClass()
    client = Phase1Tests.client
    try:
        folder = Path(WORKSPACES.name).resolve() / 'workspace-ux'
        (folder / 'docs').mkdir(parents=True)
        reference = folder / 'docs' / 'reference.md'
        reference.write_text('selected workspace reference')
        external = Path(WORKSPACES.name).resolve() / 'external.md'
        external.write_text('external reference')
        external2 = Path(WORKSPACES.name).resolve() / 'second.md'
        external2.write_text('second external reference')
        replacement = Path(WORKSPACES.name).resolve() / 'replacement'
        replacement.mkdir()
        category = client.post('/api/categories', json={'name': 'Workspace UX'}).json()
        response = client.post('/api/works', json={'name': 'Workspace UX', 'category_id': category['id'],
                                                 'workspace_mode': 'LINKED', 'workspace_path': str(folder)})
        assert response.status_code == 201, response.text
        work = response.json()
        picker = {'folder': str(replacement), 'files': f'{external}\n{external2}\n', 'deny_write': False}
        calls, errors = [], []
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
                if parsed.path in {'/api/storage/pick-folder', '/api/storage/pick-files'}:
                    result = SimpleNamespace(returncode=0, stdout=picker['files'] if parsed.path.endswith('pick-files') else picker['folder'], stderr='')
                    with patch.object(storage_api.subprocess, 'run', return_value=result) as native:
                        response = client.request(request.request.method, path, headers=headers, content=request.request.post_data_buffer)
                        calls.append((parsed.path, native.call_args.args[0], request.request.post_data))
                elif parsed.path.endswith('/workspace/access') and picker['deny_write']:
                    with patch.object(storage_api.os, 'access', side_effect=lambda p, mode: mode == (os.R_OK | os.X_OK)):
                        response = client.request(request.request.method, path, headers=headers, content=request.request.post_data_buffer)
                else:
                    response = client.request(request.request.method, path, headers=headers, content=request.request.post_data_buffer)
                forwarded = {k: v for k, v in response.headers.items()
                             if k not in {'content-length', 'content-encoding', 'transfer-encoding'}}
                request.fulfill(status=response.status_code, headers=forwarded, body=response.content)

            page.route('**/*', route)
            page.goto('http://localhost/')
            page.wait_for_function('() => state.models.length > 0')
            page.evaluate('(id) => selectWork(id)', work['id'])
            expect(page.locator('#work-paths')).to_have_text(str(folder))
            expect(page.locator('#workspace-file-access')).to_contain_text('읽기 가능')
            expect(page.locator('#workspace-file-access')).to_contain_text('쓰기 · OS 가능')
            expect(page.locator('#workspace-resolved-permission')).to_contain_text('workspace-write')
            expect(page.locator('#work-storage-details')).not_to_be_visible()
            page.locator('#workspace-panel > summary').click()
            expect(page.locator('#work-paths')).not_to_be_visible()
            expect(page.locator('#workspace-compact-state')).to_contain_text('workspace-ux · workspace-write')
            page.wait_for_function("() => localStorage.getItem('control-center-workspace-expanded') === 'false'")
            page.locator('#workspace-panel > summary').click()
            expect(page.locator('#work-paths')).to_be_visible()
            page.locator('#permission').select_option('read-only')
            expect(page.locator('#workspace-resolved-permission')).to_contain_text('read-only')
            expect(page.locator('#workspace-enable-write')).to_be_visible()
            page.locator('#workspace-enable-write').click()
            expect(page.locator('#workspace-resolved-permission')).to_contain_text('workspace-write')
            page.locator('#tab-button-materials').click()
            page.locator('#materials-open').click()
            page.locator('#material-file-list').get_by_role('button', name='▸ docs', exact=True).click()
            page.locator('#material-file-search').fill('reference')
            page.locator('#material-file-list input[value="docs/reference.md"]').check()
            expect(page.locator('#material-selection-summary')).to_contain_text('1개 파일 선택됨')
            page.locator('#material-save').click()
            expect(page.locator('#materials-dialog')).not_to_be_visible()
            page.wait_for_function('() => selectedContext().length === 1')
            page.locator('#external-open').click()
            expect(page.locator('#material-external-path')).not_to_be_visible()
            page.locator('#material-pick-files').click()
            expect(page.locator('#material-picked-files .picked-file')).to_have_count(2)
            page.locator('#material-save').click()
            expect(page.locator('#materials-dialog')).not_to_be_visible()
            page.wait_for_function('() => selectedContext().length === 3')
            sources = client.get('/api/works/' + work['id']).json()['sources']
            assert {s['location_type'] for s in sources} == {'WORKSPACE', 'EXTERNAL'}
            page.locator('#markdown-open').click()
            page.locator('#document-folder-list').get_by_role('button', name='▸ docs', exact=True).click()
            page.locator('#document-use-folder').click()
            page.locator('#material-document-name').fill('picker-note.md')
            page.locator('#material-content').fill('created in chosen folder')
            expect(page.locator('#document-target-preview')).to_have_text('저장 위치: docs/picker-note.md')
            page.locator('#material-save').click()
            expect(page.locator('#materials-dialog')).not_to_be_visible()
            assert (folder / 'docs/picker-note.md').read_text() == 'created in chosen folder'
            page.locator('#tab-button-execution').click()
            expect(page.locator('#execution-inheritance')).to_contain_text('workspace-write')
            picker['deny_write'] = True
            page.locator('#workspace-check-access').click()
            expect(page.locator('#workspace-file-access')).to_contain_text('쓰기 · OS 불가')
            expect(page.locator('#workspace-recover-pick')).to_be_visible()
            page.locator('#workspace-permission-help').click()
            expect(page.locator('#workspace-permission-guide')).to_be_visible()
            page.locator('#instruction').fill('Use the selected references and save a result.')
            before = main.runner.gateway.counter
            page.locator('#execute').click()
            expect(page.locator('#notice')).to_contain_text('Workspace에 결과물을 저장할 수 없습니다')
            assert main.runner.gateway.counter == before, 'Blocked write must not enqueue a Run'
            picker['deny_write'] = False
            page.locator('#workspace-check-access').click()
            expect(page.locator('#workspace-file-access')).to_contain_text('쓰기 · OS 가능')
            page.locator('#execute').click()
            page.wait_for_function("() => state.run?.status === 'COMPLETED'")
            detail = client.get('/api/runs/' + page.evaluate('state.run.id')).json()
            assert detail['run']['execution_profile']['permission'] == 'workspace-write'
            manifest = json.loads(detail['run']['manifest'])
            assert manifest['sandbox']['sandbox_workspace_write']['writable_roots'] == []
            assert Path(manifest['cwd']) != folder, 'Preserve the existing isolated execution scope'
            assert len(detail['artifacts']) == 1
            assert reference.read_text() == 'selected workspace reference'
            page.locator('#workspace-change').click()
            expect(page.locator('#workspace-new-path')).not_to_be_visible()
            page.locator('#workspace-pick-folder').click()
            expect(page.locator('#workspace-new-selection')).to_have_text(str(replacement))
            page.locator('#workspace-save').click()
            expect(page.locator('#workspace-dialog')).not_to_be_visible()
            expect(page.locator('#work-paths')).to_have_text(str(replacement))
            # Container selection may contain internal state; project selection may not.
            picker['folder'] = str(Path(ROOT.name).resolve())
            page.locator('#new-work').click()
            expect(page.locator('#editor-workspace-root')).not_to_be_visible()
            page.locator('#editor-pick-root').click()
            expect(page.locator('#editor-root-selection')).to_have_text(str(Path(ROOT.name).resolve()))
            assert json.loads(calls[-1][2]) == {'purpose': 'PARENT'}
            page.locator('#close-editor').click()
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile page overflow'
            assert not errors, errors
            assert all(call[1][0] == 'osascript' for call in calls)
            assert any('multiple selections allowed' in call[1][2] for call in calls if call[0].endswith('pick-files'))
            browser.close()
        print('PASS: Workspace status → file/folder picker → resolved permission → blocked write recovery → isolated workspace-write Run. Native dialogs mocked; no model calls.')
    finally:
        Phase1Tests.tearDownClass()


if __name__ == '__main__':
    run()
