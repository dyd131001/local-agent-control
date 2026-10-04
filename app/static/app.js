'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="control-token"]').content;
const state = {view:'dashboard',dashboard: null, work: null, run: null, models: [], stream: null, cursor: 0, resume: null, editor: null, category: null, command: null, workSelection: 0, runSelection: 0, storage: null};
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function defaultContextPolicy(item,kind='SOURCE'){const ext=(item.name||'').split('.').pop().toLowerCase(),document=item.content_type==='application/pdf'||['pdf','docx','odt','rtf'].includes(ext),workspaceSource=kind==='SOURCE'&&['WORKSPACE','EXTERNAL'].includes(item.location_type);return document||item.size>8192&&!workspaceSource?'필요 부분만 읽기 · RETRIEVE':'경로 참조 · REFERENCE';}
function notice(message) { $('notice').textContent = message; $('notice').classList.add('ui-help');$('notice').hidden = !message; }
async function api(path, options = {}) {
  const headers = {'X-Control-Token': token, ...options.headers};
  if (options.body && !(options.body instanceof FormData)) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body); }
  const response = await fetch('/api' + path, {...options, headers});
  const raw = await response.text();
  let data;
  try { data = raw ? JSON.parse(raw) : null; }
  catch { data = null; }
  if (!response.ok) {
    const detail = data?.detail ?? data?.error;
    const message = typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : raw.trim().slice(0,500) || response.statusText;
    throw new Error(`${path} · HTTP ${response.status}: ${message}`);
  }
  if (data === null && raw) throw new Error(`${path} · HTTP ${response.status}: 서버 응답이 JSON 형식이 아닙니다 (${raw.trim().slice(0,300)})`);
  return data;
}
function action(id, fn, event = 'click') { $(id).addEventListener(event, async e => { if (event === 'submit') e.preventDefault(); try { notice(''); await fn(e); } catch (error) { notice(error.message); } }); }
function rows(id, items, content, click) {
  $(id).replaceChildren();
  if (!items.length) { const messages={artifacts:['결과물이 없습니다.','실행에서 생성한 결과물이나 등록한 파일이 여기에 표시됩니다.'],'run-history':['실행 이력이 없습니다.','새 요청을 실행하면 상태와 결과를 확인할 수 있습니다.'],'request-history':['저장된 요청이 없습니다.','새 요청이나 예약을 등록하면 이력이 남습니다.'],'tool-saved-artifacts':['저장된 검토 결과물이 없습니다.','검토를 완료한 후 결과물로 저장할 수 있습니다.']};$(id).replaceChildren(UI.empty(...(messages[id]||['아직 항목이 없습니다.']))); return; }
  for (const item of items) {
    const row = document.createElement('div'); row.className = 'row'; row.innerHTML = content(item);
    row.classList.add('ui-list-row');
    row.querySelector('button')?.addEventListener('click', () => Promise.resolve(click(item)).catch(e => notice(e.message)));
    $(id).append(row);
  }
}
const date = value => value ? new Date(value).toLocaleString('ko-KR',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '미정';
function runRow(r) { const names={reference:'기존 결과물 등록',import:'기존 Codex 이력',new:'새 요청',resume:'기존 대화 계속',retry:'같은 요청 다시 실행',fork:'분기'};const instruction=r.instruction||state.workDetail?.requests.find(q=>q.id===r.request_id)?.instruction;return `<button><span class="row-title">${escape((instruction||r.title||names[r.operation]||'실행').slice(0,110))}</span><small>${escape(names[r.operation]||'실행')} · ${escape(r.model || '')} · ${date(r.started_at||r.created_at)}</small></button>${UI.statusHTML(r.status)}`; }
function artifactRow(a) { return `<button class="ui-list-trigger"><span class="ui-list-title">${escape(a.name)}</span><span class="ui-list-description">${escape(a.location_type||'Workspace')}${a.relative_path?` · <code class="ui-path">${escape(a.relative_path)}</code>`:''}</span></button><div class="ui-list-meta"><div class="ui-status-group">${UI.statusHTML(a.availability)}${a.partial?UI.statusHTML('PARTIAL'):''}</div>${UI.metadataHTML([['크기',UI.fileSize(a.size)],['생성',date(a.created_at)]],true)}</div>`; }
let dashboardSelection=0;
async function dashboard() {
  const selection=++dashboardSelection,data = await api('/dashboard');if(selection!==dashboardSelection)return;state.dashboard = data;
  await window.controlCenter?.metadataUpdated();
  window.controlCenter?.navigation();
  if(state.view==='dashboard')await renderOverview();
}
async function renderOverview() {
  await window.controlCenter?.renderDashboard();
}
async function showOverview() {
  window.workflows?.leave();
  state.workSelection++;
  closeStream(); state.work = null; state.run = null;state.view='dashboard';
  $('overview').hidden = false; $('work-view').hidden = true;$('category-view').hidden=true;$('management-view').hidden=true;
  $('page-title').textContent = 'Dashboard';
  window.controlCenter?.showDashboard();
  await dashboard();
}
async function selectWork(id, preserve = false) {
  if (preserve && state.work?.id !== id) return;
  const selection = ++state.workSelection;
  if (!preserve) { state.work = null;state.workspaceAccess=null;state.resolvedProfile=null; closeStream(); window.workflows?.leave(); window.controlCenter?.tab('overview',false); window.workTools?.reset(); }
  const checked = preserve ? selectedContext() : [];
  const detail = await api('/works/' + id);
  if (selection !== state.workSelection) return;
  if(detail.work.archived||detail.category&&!detail.category.active){
    await window.controlCenter?.showCategory(detail.work.category_id,true);
    notice('비활성 항목은 관리 화면에서만 사용할 수 있습니다. 다시 활성화한 뒤 작업에 진입하세요.');return;
  }
  state.view='work';$('category-view').hidden=true;$('management-view').hidden=true;
  if(detail.category&&state.dashboard){const index=state.dashboard.categories.findIndex(c=>c.id===detail.category.id);if(index>=0)state.dashboard.categories[index]=detail.category;}
  state.work = detail.work;
  state.workDetail = detail;
  state.category = detail.work.category_id;
  if (!preserve) $('instruction').value = '';
  $('page-title').textContent = detail.work.name;
  $('work-description').textContent = detail.work.description || '자료를 선택하고 요청을 실행하거나 Workflow를 시작하세요.';
  $('work-paths').textContent = detail.work.workspace_path || detail.work.linked_workspace_path || detail.work.path;
  $('work-storage-details').innerHTML = [['저장 방식',detail.work.storage_layout==='EXTERNAL'?'외부 Workspace 연결':'기존 저장 구조'],['기존 호환 경로',detail.work.path],['내부 상태 · 시스템 관리',state.storage?.state_root],['공용 산출물 · Publish 저장',state.storage?.shared_root]].map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('');
  $('linked-import').hidden = !detail.work.linked_workspace_path;
  $('archive-work').textContent = detail.work.archived ? '보관 해제' : '보관';
  $('overview').hidden = true; $('work-view').hidden = false;
  $('context-list').replaceChildren();
  for (const source of detail.sources) {
    const download=document.createElement('a');download.href='/api/sources/'+encodeURIComponent(source.id)+'/download';download.download='';download.textContent='다운로드';download.setAttribute('aria-label',source.name+' 다운로드');UI.actionStyle(download);
    const label=UI.selectable({title:source.name,value:source.id,selected:preserve?checked.includes(source.id):source.is_context,
      metadata:[['출처',{LEGACY:'기존 자료',WORKSPACE:'Workspace',SHARED:'Shared',EXTERNAL:'External'}[source.location_type]||'기존 자료'],['파일',source.relative_path,'path'],['크기',UI.fileSize(source.size)],['실행 Context',defaultContextPolicy(source)]],actions:[download]});label.dataset.sourceGroup=source.location_type||'LEGACY';
    $('context-list').append(label);
  }
  if (!detail.sources.length) $('context-list').replaceChildren(UI.empty('등록된 자료가 없습니다.','Workspace 자료를 추가한 뒤 실행에 사용할 항목을 선택하세요.'));
  rows('run-history', detail.runs, runRow, r => selectRun(r.id));
  rows('request-history', detail.requests, r => `<button>${escape(r.instruction.slice(0,90))}<small>${date(r.created_at)}</small></button>`, async r => {
    const history = await api('/requests/' + r.id);
    if (history.runs.length) await selectRun(history.runs[history.runs.length - 1].id);
  });
  rows('artifacts', detail.artifacts, artifactRow, preview);
  if (!preserve) {
    closeStream(); state.run = null; state.resume = null; $('resume-label').hidden = true; $('clear-resume').hidden = true;
    $('events').textContent = '실행 기록을 선택하거나 새 요청을 시작하세요.'; $('manifest').textContent = ''; $('final-answer').textContent = ''; $('run-meta').textContent = '';
    $('run-instruction').textContent='실행을 선택하면 보낸 요청이 표시됩니다.';$('run-steer-history').replaceChildren();
    updateRunControls();
  }
  $('execute').disabled = detail.work.archived || !state.models.length;
  await Promise.all([window.executionSettings.refresh(detail.work, preserve),window.storageUI?.access(detail.work)]);
  if (selection !== state.workSelection) return;
  await window.workflows?.loadWork(id, preserve);
  await window.flowPlans?.loadWork(id, preserve);
  if (selection !== state.workSelection) return;
  await window.conversations?.load(id, preserve);
  await window.executionSettings.preview();
  if (selection !== state.workSelection) return;
  await window.controlCenter?.workLoaded(detail, preserve);
  await window.requestQueue?.load(id, !preserve);
}
function selectedContext() { return [...$('context-list').querySelectorAll('input:checked')].map(i => i.value); }
function closeStream() { state.runSelection++; state.stream?.close(); state.stream = null; }
function appendEvent(id, kind, payload) {
  if (id <= state.cursor) return;
  state.cursor = id;
  state.liveMessages ||= new Map();state.eventLines ||= new Map();
  const item=payload.item_id||'message-'+id;
  if(kind==='ACTIVITY'&&(payload.delta!==undefined||payload.text!==undefined)){
    const previous=state.liveMessages.get(item)||'';
    state.liveMessages.set(item,payload.text!==undefined?payload.text:previous+payload.delta);
    state.eventLines.set('agent-'+item,'[ACTIVITY] '+state.liveMessages.get(item));
    if(['CREATED','RUNNING'].includes(state.run?.status)){
      const answer=[...state.liveMessages.values()].join('\n\n');$('final-answer').textContent=answer;window.conversations?.liveAnswer(answer);
    }
  }else if(kind==='ACTIVITY'&&payload.output!==undefined){
    const key='output-'+item;state.eventLines.set(key,(state.eventLines.get(key)||'[COMMAND OUTPUT] ')+payload.output);
  }else{
    state.eventLines.set('event-'+id,`[${kind}] ${payload.command||payload.message||payload.text||JSON.stringify(payload)}`);
    if(kind==='COMMAND_COMPLETED'&&payload.output)state.eventLines.set('output-'+item,'[COMMAND OUTPUT] '+payload.output);
  }
  const pinned=$('events').scrollHeight-$('events').scrollTop-$('events').clientHeight<40;
  $('events').textContent=[...state.eventLines.values()].join('\n\n').slice(-180000);
  const activity={RUN_STARTED:'실행을 시작했습니다.',COMMAND_STARTED:'작업 명령을 실행하고 있습니다.',COMMAND_COMPLETED:'작업 명령을 완료했습니다.',FILE_CHANGED:'파일 변경사항을 정리하고 있습니다.',ACTIVITY:'응답을 생성하고 있습니다.',WARNING:'실행 중 알림이 있습니다. 고급 이벤트에서 확인할 수 있습니다.',RUN_COMPLETED:'실행을 완료했습니다.',RUN_FAILED:'실행에 실패했습니다. 상세 정보를 확인하세요.',RUN_CANCELLED:'실행을 취소했습니다.'};
  if(activity[kind]){$('run-activity').hidden=false;$('run-activity').textContent=activity[kind];}
  if(pinned)$('events').scrollTop=$('events').scrollHeight;
}
function updateRunControls() {
  const run = state.run;
  const phase={QUEUED:'실행 대기',PREPARING:'준비 중',SUBMITTING:'요청 전송 중',EXECUTING:'실행 중',RECOVERING:'상태 복구 중'};
  $('run-status').textContent = run ? phase[run.phase] || window.controlCenter?.status(run.status) || run.status : '선택된 실행 없음';
  if(!run)$('run-activity').hidden=true;
  $('run-status').dataset.status = run?.status || '';
  $('steer').disabled = !run || run.status !== 'RUNNING' || run.phase !== 'EXECUTING';
  $('cancel').disabled = !run || !['CREATED', 'RUNNING'].includes(run.status);
  $('resume').disabled = !run || !!run.task_run_id || !run.thread_id || ['CREATED', 'RUNNING'].includes(run.status) || run.safety_block;
  $('retry').disabled = !run || run.is_query || ['reference','import'].includes(run.operation) || !!run.task_run_id || ['CREATED', 'RUNNING'].includes(run.status) || run.safety_block;
  $('reconcile').hidden = !run?.safety_block;
}
async function selectRun(id) {
  closeStream();
  const selection = state.runSelection, workId = state.work?.id;
  const detail = await api('/runs/' + id);
  if (selection !== state.runSelection || state.work?.id !== workId || detail.run.work_id !== workId) return;
  state.run = detail.run; state.cursor = 0;state.liveMessages=new Map();state.eventLines=new Map();
  window.controlCenter?.tab('execution');
  $('events').textContent = '';
  for (const event of detail.events) appendEvent(event.id, event.type, event.payload);
  renderRunDetail(detail);
  await window.conversations?.syncRun(detail.run);
  if(selection!==state.runSelection||state.run?.id!==id)return;
  if (['CREATED','RUNNING'].includes(detail.run.status)) {
    const source = new EventSource(`/api/runs/${encodeURIComponent(id)}/events?after=${state.cursor}`);
    state.stream = source;
    for (const kind of ['RUN_STARTED','ACTIVITY','COMMAND_STARTED','COMMAND_COMPLETED','FILE_CHANGED','WARNING','RUN_COMPLETED','RUN_FAILED','RUN_CANCELLED']) {
      source.addEventListener(kind, async event => {
        if (state.runSelection !== selection || state.run?.id !== id) return;
        appendEvent(Number(event.lastEventId), kind, JSON.parse(event.data));
        if (kind.startsWith('RUN_')) {
          try {
            const detail = await api('/runs/' + id);
            if (state.runSelection !== selection || state.run?.id !== id) return;
            state.run = detail.run; renderRunDetail(detail);
            if (kind !== 'RUN_STARTED') { closeStream(); await selectWork(state.work.id, true); }
            await dashboard();
          } catch (error) { notice(error.message); }
        }
      });
    }
    source.onerror = async () => {
      try {
        const latest = await api('/runs/' + id);
        if (state.runSelection === selection && state.run?.id === id && !['CREATED','RUNNING'].includes(latest.run.status)) {
          closeStream(); state.run = latest.run; renderRunDetail(latest);
          await selectWork(workId, true);
          await dashboard();
        }
      } catch (error) { notice(error.message); }
    };
  }
}
function renderRunDetail(detail) {
  updateRunControls();
  $('run-meta').replaceChildren(UI.metadata([['모델',detail.run.model],['Reasoning',detail.run.reasoning],['Permission',detail.run.execution_profile?.permission||'원본 설정 미제공'],['Speed',detail.run.execution_profile?.speed||'원본 설정 미제공']],{compact:true}));
  $('run-instruction').textContent=detail.request.instruction;
  $('run-steer-history').innerHTML=(detail.instructions||[]).map(i=>`<details><summary>추가 지시 · ${date(i.created_at)}</summary><p class="request-content">${escape(i.text)}</p></details>`).join('');
  $('manifest').textContent = JSON.stringify({request: detail.request, manifest: JSON.parse(detail.run.manifest), instructions: detail.instructions, error: detail.run.error ? JSON.parse(detail.run.error) : null}, null, 2);
  $('final-answer').textContent = detail.run.final_text || [...(state.liveMessages?.values()||[])].join('\n\n') || (['CREATED','RUNNING'].includes(detail.run.status)?'응답을 기다리고 있습니다. 진행 메시지가 실시간으로 표시됩니다.':'최종 응답이 없습니다.');
  $('run-activity').hidden=false;
  if(!['CREATED','RUNNING'].includes(detail.run.status))$('run-activity').textContent=window.controlCenter?.status(detail.run.status)||detail.run.status;
  window.controlCenter?.runUpdated(detail);
  window.conversations?.runUpdated(detail);
  window.workTools?.runUpdated(detail.run);
  window.requestQueue?.runSelected(detail.run);
  window.conversations?.inspect(detail.run).catch(error => notice(error.message));
}
async function preview(artifact) {
  const detail = await api('/artifacts/' + artifact.id);
  $('artifact-title').textContent = detail.name;
  $('artifact-meta').replaceChildren(UI.metadata([['상태',UI.status(detail.availability)],['크기',UI.fileSize(detail.size)],['출처',detail.location_type||'Workspace'],['생성 시각',date(detail.created_at)],...(detail.relative_path?[['파일',detail.relative_path,'path']]:[])]));
  const warning=detail.availability!=='AVAILABLE'?'원본 파일을 사용할 수 없어 미리보기·다운로드·Library 등록이 제한됩니다.':detail.partial?'실행 중 생성된 일부 결과물입니다. 확정된 결과물로 Library에 등록할 수 없습니다.':'';
  $('artifact-warning').hidden=!warning;$('artifact-warning').replaceChildren(...(warning?[UI.warning(warning,detail.partial?'일부 결과물':'파일 확인 필요')]:[]));
  $('artifact-advanced').textContent = JSON.stringify({id:detail.id, path:detail.local_path,sha256:detail.sha256},null,2);
  $('download').href = `/api/artifacts/${encodeURIComponent(artifact.id)}/download`;
  $('download').hidden = detail.availability !== 'AVAILABLE';
  $('preview-frame').src = detail.availability === 'AVAILABLE' ? `/api/artifacts/${encodeURIComponent(artifact.id)}/preview` : 'about:blank';
  $('artifact-publish').dataset.id = detail.id;
  $('artifact-publish').disabled = detail.partial || detail.availability !== 'AVAILABLE';
  const relations = await api('/artifacts/' + detail.id + '/lineage');
  $('artifact-lineage').replaceChildren();
  for (const relation of relations) {
    const entry = document.createElement('div');entry.className='ui-lineage-row';
    if (relation.kind === 'INPUT') {
      entry.append(UI.metadata([['관계','입력으로 전달'],['시도',relation.consumer.attempt_number],['실행 상태',UI.status(relation.consumer.status)]],{compact:true}));
      entry.append(wfButton('Workflow 보기', async () => { $('preview').close(); const execution=await api(`/workflow-runs/${relation.consumer.workflow_run_id}`); if(state.work?.id!==execution.workflow_run.work_id) await selectWork(execution.workflow_run.work_id); await wfSelectRun(relation.consumer.workflow_run_id); }));
    } else {
      const incoming = relation.target_artifact_id === detail.id;
      const related = incoming ? relation.source : relation.target;
      entry.append(UI.metadata([['관계',relation.kind==='REVISION_OF'?(incoming?'이전 버전':'새 버전'):(incoming?'입력 출처':'파생 결과')],['상태',UI.status(related.availability)]],{compact:true}));
      entry.append(wfButton(related.name, () => preview(related)));
    }
    $('artifact-lineage').append(entry);
  }
  if (!relations.length) $('artifact-lineage').replaceChildren(UI.empty('기록된 전달 관계가 없습니다.'));
  $('preview').showModal();
}
function reasoning() { window.executionSettings.reasoning(''); }
async function loadModels() {
  state.models = await api('/models');
  window.executionSettings.populate('', {});
}

function edit(type, value = null) {
  state.editor = {type, value,view:state.view};
  $('editor-title').textContent = `${type === 'category' ? 'Category' : 'Work'} ${value ? '수정' : '만들기'}`;
  $('editor-name').value = value?.name || '';
  $('editor-description').value = value?.description || '';
  $('editor-description-label').hidden = type === 'category';
  $('editor-workspace-label').hidden = type === 'category' || !!value;
  $('editor-workspace-kind').value = 'NEW';
  $('editor-workspace-root').value = state.storage?.workspace_root || '~/Developer';
  $('editor-workspace-folder').value = '';
  $('editor-linked-path').value = '';
  window.storageUI?.workspaceForm();
  $('deactivate-category').hidden = type !== 'category' || !value?.active;
  $('activate-category').hidden=type!=='category'||!value||value.active;
  $('category-presets').hidden=type!=='category'||!!value;
  $('editor-category-label').hidden = type === 'category' || !!value;
  $('editor-category').innerHTML = state.dashboard.categories.filter(c => c.active).map(c => `<option value="${escape(c.id)}">${escape(c.name)}</option>`).join('');
  if (state.category&&state.dashboard.categories.find(c=>c.id===state.category)?.active) $('editor-category').value = state.category;
  $('editor').showModal();
}
action('editor-form', async () => {
  const {type, value,view} = state.editor;
  const body = {name: $('editor-name').value};
  if (type === 'work') { body.description = $('editor-description').value; if (!value) { body.category_id = $('editor-category').value; body.workspace_mode = $('editor-workspace-kind').value; if (body.workspace_mode === 'LINKED') body.workspace_path = $('editor-linked-path').value; else { body.workspace_root = $('editor-workspace-root').value; body.workspace_folder = $('editor-workspace-folder').value || body.name; } } }
  const row = await api(`/${type === 'category' ? 'categories' : 'works'}${value ? '/' + value.id : ''}`, {method: value ? 'PATCH' : 'POST', body});
  $('editor').close(); await dashboard();
  if(type==='work'&&(!value||view==='work'))await selectWork(row.id,!!value);
  if(type==='category'&&!value)await window.controlCenter?.showCategory(row.id);
}, 'submit');
action('close-editor', () => $('editor').close());
action('deactivate-category', async () => { await api('/categories/' + state.editor.value.id, {method:'DELETE'}); $('editor').close(); await dashboard(); });
action('activate-category',async()=>{await api('/categories/'+state.editor.value.id,{method:'PATCH',body:{active:true}});$('editor').close();await dashboard();});
action('new-category', () => edit('category'));
action('new-work', () => { if (!state.dashboard.categories.some(c => c.active)) { notice('먼저 활성 Category를 만들어 주세요.'); return; } edit('work'); });
action('edit-work', () => edit('work', state.work));
action('archive-work', async () => { await api('/works/' + state.work.id, {method: 'PATCH', body: {archived: !state.work.archived}}); await selectWork(state.work.id, true); await dashboard(); });
action('directory', async () => { await api(`/works/${state.work.id}/workspace/open`, {method:'POST'}); });
action('linked-import-submit', async () => { const id = state.work.id; const paths = $('linked-import-paths').value.split('\n').map(p => p.trim()).filter(Boolean); await api(`/works/${id}/sources/import`, {method:'POST', body:{paths}}); await selectWork(id, true); notice('Workspace 파일을 참고 자료로 연결했습니다.'); });
action('upload-files', async () => { for (const file of $('upload-files').files) { const form = new FormData(); form.append('file', file); form.append('context', $('upload-context').checked); await api('/works/' + state.work.id + '/sources', {method: 'POST', body: form}); } $('upload-files').value = ''; await selectWork(state.work.id, true); notice('파일을 추가했습니다. 자료 탭에서 선택해 실행하세요.'); }, 'change');
action('request-form', async () => {
  await window.storageUI?.beforeExecute();
  const body = {instruction: $('instruction').value, context_ids: selectedContext(), artifact_ids: window.workflows?.selectedLibrary() || [], execution_profile: window.executionSettings.read('')};
  if($('request-condition').value!=='NOW'){
    $('execute').disabled=true;
    try{await window.requestQueue.register(body);}finally{$('execute').disabled=!state.work||state.work.archived||!state.models.length;}
    return;
  }
  const path = state.resume ? `/runs/${state.resume}/resume` : `/works/${state.work.id}/runs`;
  const signature = JSON.stringify([path, body]);
  if (state.command?.signature !== signature) state.command = {signature, key: crypto.randomUUID()};
  $('execute').disabled = true;
  try { const run = window.conversations ? await window.conversations.execute(body) : await api(path, {method: 'POST', body, headers: {'Idempotency-Key': state.command.key}}); if (!run) return; state.command = null; state.resume = null; $('resume-label').hidden = true; $('clear-resume').hidden = true; await selectWork(state.work.id, true); await selectRun(run.id); }
  finally { $('execute').disabled = !state.work || state.work.archived || !state.models.length; }
}, 'submit');
action('steer-form', async () => { const result = await api('/runs/' + state.run.id + '/steer', {method: 'POST', body: {instruction: $('steer-text').value}}); $('steer-text').value = ''; notice(`추가 지시 전송: ${result.delivery}. 반영 결과는 실행 응답에서 확인하세요.`); }, 'submit');
action('cancel', async () => { await api('/runs/' + state.run.id + '/cancel', {method:'POST'}); await selectRun(state.run.id); });
action('resume', () => { state.resume = state.run.id; $('resume-label').textContent = '선택한 실행의 대화를 계속합니다. 새 실행 기록이 생성됩니다.'; $('resume-label').hidden = false; $('clear-resume').hidden = false; $('instruction').focus(); });
action('clear-resume', () => { state.resume = null; $('resume-label').hidden = true; $('clear-resume').hidden = true; });
action('retry', async () => { const run = await api('/requests/' + state.run.request_id + '/retry', {method:'POST', body:{execution_profile:window.executionSettings.read('')}, headers:{'Idempotency-Key':crypto.randomUUID()}}); await selectWork(state.work.id, true); await selectRun(run.id); });
action('reconcile', async () => { await api('/runs/' + state.run.id + '/reconcile', {method:'POST'}); await selectRun(state.run.id); });
action('close-preview', () => { $('preview').close(); $('preview-frame').src = 'about:blank'; });
action('dashboard-button', async () => { state.category = null; await showOverview(); });
async function syncLocalConversations(){
  try{
    const result=await api('/runtime-conversations/sync',{method:'POST'});
    if(result.failed)notice(`로컬 Codex 대화 ${result.failed}개를 업데이트하지 못했습니다. Runtime 연결을 확인하세요.`);
    return result;
  }catch(error){notice('로컬 Codex 대화 업데이트 실패: '+error.message);return null;}
}
action('refresh', async () => { window.controlCenter?.refreshRuntime();await syncLocalConversations();await dashboard(); if (state.work) await selectWork(state.work.id, true); if (state.run) await selectRun(state.run.id); await account(); });
action('model', reasoning, 'change');
async function account() {
  const health = await api('/health');
  if (!health.ok) notice('실행 스케줄러 복구 중: ' + (health.dispatcher_error || '중지됨'));
  $('account').textContent = health.account.connected ? '계정 연결됨' : '계정 연결 필요';
  $('account-dot').classList.toggle('connected', health.account.connected);
  $('login').hidden = health.account.connected;
  $('cancel-login').hidden = health.login.status !== 'pending';
  $('login-link').hidden = health.login.status !== 'pending';
  if (health.login.url) $('login-link').href = health.login.url;
  if (!health.account.connected && health.account.error) notice(health.account.error);
  if (health.account.connected && !state.models.length) await loadModels();
}
action('login', async () => { const login = await api('/login', {method:'POST'}); if (login.url) { $('login-link').href = login.url; $('login-link').hidden = false; notice('Open login to connect your ChatGPT account.'); } await account(); });
action('cancel-login', async () => { await api('/login', {method:'DELETE'}); await account(); });
window.executionSettings.bind();
(async () => { try { state.storage = await api('/storage/settings'); await dashboard(); await account(); if (!state.models.length) await loadModels(); await window.controlCenter?.restoreRoute();
  const sync=await syncLocalConversations();if(sync?.new_turns||sync?.updated||sync?.active){await dashboard();if(state.work)await selectWork(state.work.id,true);if(state.run)await selectRun(state.run.id);}
} catch (error) { notice(error.message); } })();
setInterval(() => { if (!document.hidden) {account().catch(error => notice(error.message));window.controlCenter?.refresh().catch(error => notice(error.message));} }, 15000);
let refreshingRun=false;
async function refreshActiveRun(){
  if(document.hidden||refreshingRun||!state.run||!['CREATED','RUNNING'].includes(state.run.status))return;
  refreshingRun=true;const id=state.run.id,selection=state.runSelection;
  try{
    const detail=await api('/runs/'+id+'?after='+state.cursor);
    if(selection!==state.runSelection||state.run?.id!==id)return;
    for(const event of detail.events)appendEvent(event.id,event.type,event.payload);
    const changed=state.run.status!==detail.run.status||state.run.phase!==detail.run.phase;
    state.run=detail.run;renderRunDetail(detail);
    if(!['CREATED','RUNNING'].includes(detail.run.status)){closeStream();await selectWork(state.work.id,true);}
    if(changed)await dashboard();
  }catch(error){notice(error.message);}finally{refreshingRun=false;}
}
setInterval(refreshActiveRun,4000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden){refreshActiveRun();window.controlCenter?.refresh().catch(e=>notice(e.message));}});
