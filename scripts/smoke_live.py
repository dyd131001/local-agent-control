"""Opt-in real Codex + HTTP + browser test. Uses synthetic data in a new temp root.
Runs actual model turns using the existing Codex login; may consume account usage.
Run: .venv/bin/python scripts/smoke_live.py
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

PROJECT = Path(__file__).resolve().parents[1]
PORT = 18765
URL = f'http://127.0.0.1:{PORT}'
root = Path(tempfile.mkdtemp(prefix='control-center-live-'))
evidence = {'test': 'Phase 1 live HTTP/browser/SDK acceptance', 'root': str(root), 'checks': []}
process = None
log = open(root / 'server.log', 'a')
env = {**os.environ, 'CONTROL_CENTER_ROOT': str(root), 'PORT': str(PORT)}
for key in ('CONTROL_CENTER_STATE','CONTROL_CENTER_DATA'):
    env.pop(key, None)
env['CONTROL_CENTER_STATE'] = str(root / '.control-center-state')
env['CONTROL_CENTER_DATA'] = str(root / 'data')
env['CONTROL_CENTER_WORKSPACE_ROOT'] = str(root / 'workspaces')
# Workspaces must be outside the synthetic Application root as well.
env['CONTROL_CENTER_ROOT'] = str(root / 'application')


def check(name, condition=True, **detail):
    if not condition:
        raise AssertionError(name + ': ' + json.dumps(detail))
    evidence['checks'].append({'name': name, 'passed': True, **detail})
    print('PASS', name, flush=True)


def boot():
    global process
    process = subprocess.Popen([sys.executable, '-m', 'app.main'], cwd=PROJECT, env=env, stdout=log, stderr=log)
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Backend exited: ' + (root / 'server.log').read_text()[-3000:])
        try:
            if httpx.get(URL, timeout=1).status_code == 200: return
        except httpx.HTTPError: pass
        time.sleep(.5)
    raise RuntimeError('Backend startup timeout')


def stop():
    global process
    if process and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=30)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
    process = None


@contextmanager
def api_client():
    client = httpx.Client(base_url=URL, timeout=30)
    page = client.get('/')
    token = re.search(r'name="control-token" content="([^"]+)"', page.text)[1]
    client.headers.update({'Origin': URL, 'X-Control-Token': token})
    try:
        yield client
    finally:
        client.close()


def wait_run(client, rid, terminal=True):
    for _ in range(360):
        d = client.get('/api/runs/' + rid).json()
        if terminal and d['run']['status'] not in ('CREATED','RUNNING'): return d
        if not terminal and any(e['type'] == 'COMMAND_STARTED' for e in d['events']): return d
        time.sleep(.5)
    raise AssertionError('Run timed out: ' + rid)


try:
    boot()
    with api_client() as client:
        health = client.get('/api/health').json()
        check('ChatGPT authentication reused', health['account'].get('connected') and health['account'].get('type') == 'chatgpt')
        models = client.get('/api/models').json()
        check('Runtime model/reasoning catalog', isinstance(models, list) and len(models) > 0, count=len(models))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, channel='chrome')
            page = browser.new_page(viewport={'width':1440, 'height':1100})
            errors = []
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            page.goto(URL)
            page.get_by_text('OpenAI Account · Connected', exact=True).wait_for()
            page.locator('#new-category').click()
            page.locator('#editor-name').fill('Acceptance')
            page.locator('#editor-form').get_by_role('button', name='Save', exact=True).click()
            page.locator('#editor').wait_for(state='hidden')
            page.locator('#new-work').click()
            page.locator('#editor-name').fill('Phase 1 browser check')
            page.locator('#editor-description').fill('Synthetic E2E workspace')
            page.locator('#editor-form').get_by_role('button', name='Save', exact=True).click()
            page.locator('#work-view').wait_for(state='visible')
            work = client.get('/api/dashboard').json()['works'][0]
            check('Category and Work created from browser', Path(work['path']).is_dir())
            page.locator('#upload-files').set_input_files({'name':'context.txt', 'mimeType':'text/plain', 'buffer':b'Acceptance token: CEDAR-731. Include this token in your Markdown result.'})
            page.get_by_text('Files added. Select them in Context before running.', exact=True).wait_for()
            page.locator('#context-list input').check()
            page.locator('#instruction').fill('Read the selected context file. Run shell commands to create artifacts/result.md containing its acceptance token, artifacts/result.txt, artifacts/example.py, and artifacts/pixel.png (a valid 1x1 PNG using Python base64). Verify each file. Do not use any external tools or network. Keep your response brief.')
            with page.expect_response(lambda r: '/runs' in r.url and r.request.method == 'POST') as posted:
                page.locator('#execute').click()
            response = posted.value
            check('Browser request returns 202', response.status == 202)
            run = response.json()
            done = wait_run(client, run['id'])
            check('Actual Codex Turn completed', done['run']['status'] == 'COMPLETED', status=done['run']['status'])
            page.wait_for_function("document.getElementById('run-status').textContent.includes('COMPLETED')", timeout=20000)
            check('SSE events shown in browser', 'COMMAND_STARTED' in page.locator('#events').inner_text())
            by_name = {a['name']:a for a in done['artifacts']}
            check('Four actual files detected', {'result.md','result.txt','example.py','pixel.png'}.issubset(by_name), names=list(by_name))
            for name, artifact in by_name.items():
                path = Path(work['path']) / artifact['relative_path']
                check('Verified artifact: ' + name, path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == artifact['sha256'])
                preview = client.get('/api/artifacts/' + artifact['id'] + '/preview')
                check('Preview: ' + name, preview.status_code == 200 and 'sandbox' in preview.headers['content-security-policy'])
            md = by_name['result.md']
            check('Selected context used', 'CEDAR-731' in client.get('/api/artifacts/' + md['id'] + '/download').text)
            page.locator('#artifacts').get_by_role('button', name=re.compile('result.md')).click()
            page.locator('#preview').wait_for(state='visible')
            page.frame_locator('#preview-frame').get_by_text(re.compile('CEDAR-731')).first.wait_for()
            check('Markdown preview displayed in browser')
            page.locator('#close-preview').click()
            manifest = json.loads(done['run']['manifest'])
            check('Context manifest persisted', len(manifest['files']) == 1 and (root / '.control-center-state/manifests' / (run['id'] + '.json')).exists())
            page.screenshot(path=str(root / 'completed.png'), full_page=True)
            page.locator('#resume').click()
            page.locator('#instruction').fill('Continue this conversation. Without reading the original reference file, write the acceptance token you remember into artifacts/resumed.txt. Verify the file. Use shell commands, no external tools.')
            with page.expect_response(lambda r: r.url.endswith('/resume') and r.request.method == 'POST') as posted:
                page.locator('#execute').click()
            resumed = posted.value.json()
            continued = wait_run(client, resumed['id'])
            check('Resume creates new Run on same Thread', continued['run']['status'] == 'COMPLETED' and continued['run']['thread_id'] == done['run']['thread_id'] and continued['run']['turn_id'] != done['run']['turn_id'] and continued['run']['id'] != done['run']['id'])
            check('Original Run and artifacts retained', client.get('/api/runs/' + run['id']).json()['run']['status'] == 'COMPLETED' and client.get('/api/artifacts/' + md['id']).json()['availability'] == 'AVAILABLE')
            check('Browser has no JavaScript errors', not errors, errors=errors)
            browser.close()
        # Time-sensitive controls use HTTP after a real Runtime command starts.
        for action in ('steer','cancel'):
            request = {'instruction':'Use the shell to run sleep 20 now, then write artifacts/late.txt with ORIGINAL. Do not write late.txt before sleep finishes. Keep the final answer brief.'}
            started = client.post('/api/works/' + work['id'] + '/runs', json=request).json()
            wait_run(client, started['id'], terminal=False)
            if action == 'steer':
                reply = client.post('/api/runs/' + started['id'] + '/steer', json={'instruction':'Change the file content to STEERED-917 instead of ORIGINAL and include STEERED-917 in the final answer.'})
                check('Steer accepted for same Turn', reply.status_code == 202 and reply.json()['delivery'] == 'ACCEPTED')
                result = wait_run(client, started['id'])
                check('Steer changes actual result', result['run']['status'] == 'COMPLETED' and 'STEERED-917' in result['run']['final_text'])
            else:
                check('Interrupt requested', client.post('/api/runs/' + started['id'] + '/cancel').status_code == 202)
                result = wait_run(client, started['id'])
                check('Cancel confirmed by Runtime', result['run']['status'] == 'CANCELLED' and result['run']['runtime_status'] == 'interrupted')
                check('Cancelled delayed file absent', not (Path(work['path']) / 'runs' / started['id'] / 'workspace/artifacts/late.txt').exists())
        saved = client.get('/api/works/' + work['id']).json()
    stop(); boot()
    with api_client() as client:
        restored = client.get('/api/works/' + work['id']).json()
        check('Backend restart preserves history and artifacts', len(restored['runs']) == len(saved['runs']) and len(restored['artifacts']) == len(saved['artifacts']))
        cursor = done['events'][1]['id']
        replay = client.get('/api/runs/' + run['id'] + '/events', headers={'Last-Event-ID':str(cursor)}).text
        check('Persisted SSE replay after restart', 'RUN_COMPLETED' in replay and f'id: {cursor}\n' not in replay)
    evidence['passed'] = True
except BaseException as exc:
    evidence['passed'] = False
    evidence['error'] = str(exc)
    raise
finally:
    stop(); log.close()
    destination = PROJECT / 'docs/runtime-evidence/phase1-live.json'
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print('Evidence:', destination, 'Test data:', root, flush=True)
