'use strict';
const wfState = {workId:null, definitions:[], definition:null, run:null, stream:null, cursor:0, editing:null, taskIndex:0, library:[], sources:[], saving:false, command:null, runSelection:0, definitionSelection:0, loadSelection:0};
const wfEscape = escape;
function wfDecode(value){try{return JSON.parse(value);}catch{return {code:'LEGACY_ERROR',message:String(value??'알 수 없는 오류')}};}
const taskStatus = {BLOCKED:'대기 중',READY:'바로 실행 가능',QUEUED:'실행 대기',RUNNING:'실행 중',COMPLETED:'완료',FAILED:'실패',CANCELLED:'취소',SKIPPED:'실행 생략'};
function wfNotice(error) { notice(error?.message || error); }
function wfClose() { wfState.runSelection++; wfState.stream?.close(); wfState.stream=null; }
function wfLeave() { wfClose(); wfState.workId=null; wfState.definitionSelection++; wfState.loadSelection++; }
function selectedLibrary() { return [...$('library-context-list').querySelectorAll('input:checked')].map(i=>i.value); }
function wfOptions(select, entries, value) { select.replaceChildren(); for(const [id,label] of entries) { const option=document.createElement('option'); option.value=id; option.textContent=label; select.append(option); } if(value!==undefined) select.value=value; }
function wfButton(label, fn, disabled=false, kind='secondary') { return UI.action(label,fn,{disabled,kind}); }
function wfLevels(tasks) {
  const remaining=new Map(tasks.map(t=>[t.id,t])); const seen=new Set(), levels=[];
  while(remaining.size) { const ready=[...remaining.values()].filter(t=>t.depends_on.every(p=>seen.has(p))); if(!ready.length) return [];
    levels.push(ready); for(const t of ready) { seen.add(t.id); remaining.delete(t.id); }
  } return levels;
}
function wfAncestors(tasks, id, visited=new Set()) {
  const task=tasks.find(t=>t.id===id); for(const parent of task?.depends_on || []) { if(!visited.has(parent)) { visited.add(parent); wfAncestors(tasks,parent,visited); } } return visited;
}
function wfOrderText(task,tasks) {
  if(!task.depends_on.length) return '바로 실행 가능';
  const names=task.depends_on.map(p=>tasks.find(t=>t.id===p)?.name||p);
  const siblings=tasks.filter(t=>t.id!==task.id && JSON.stringify([...t.depends_on].sort())===JSON.stringify([...task.depends_on].sort()));
  return `${names.join(', ')} ${names.length>1?'모두 ':''}완료 후 실행`+(siblings.length?` · ${siblings.map(t=>t.name).join(', ')}와 동시에 실행 가능`:'');
}
function wfDiagram(container,tasks,current={}) {
  container.replaceChildren(); const levels=wfLevels(tasks);container.style.minWidth=Math.max(210,...levels.map(level=>level.length*174+(level.length-1)*12))+'px';
  if(!levels.length) { container.textContent='실행 순서를 저장할 때 확인합니다. 순환 연결을 수정하세요.'; return; }
  for(let i=0;i<levels.length;i++) {
    if(i) { const gap=document.createElement('div');gap.className='flow-gap';container.append(gap); }
    const group=document.createElement('div'); group.className='flow-level';
    for(const task of levels[i]) {
      const run=current[task.id], card=document.createElement('article'); card.className='flow-task '+(run?.status?.toLowerCase()||'');
      const inputLabels=task.input_rule.map(b=>b.artifact_id ? `선택 결과물 ${wfState.library.find(a=>a.id===b.artifact_id)?.name||'기존 결과물'}` : `${tasks.find(t=>t.id===b.task_definition_id)?.name||'선행 작업'} → ${tasks.find(t=>t.id===b.task_definition_id)?.output_rule.find(o=>o.output_key===b.output_key)?.path||b.output_key}`);
      const outputs=task.output_rule.map(o=>o.path+(o.required?' (필수)':''));
      const symbol={RUNNING:'●',COMPLETED:'✓',FAILED:'!',CANCELLED:'−',SKIPPED:'−',BLOCKED:'○',READY:'○',QUEUED:'◷'}[run?.status]||'○';
      card.innerHTML=`<div class="node-heading"><span class="node-status">${symbol}</span><strong>${wfEscape(task.name)}</strong></div><small>${run?wfEscape(taskStatus[run.status]||run.status):wfEscape(task.model||'기본 모델')}</small>${run?.approval?.status==='WAITING'?'<span class="badge" data-status="WAITING_APPROVAL">승인 대기</span>':''}<span class="node-output">${outputs.length?`${outputs.length}개 결과물`:'텍스트 응답'}</span>`;
      card.title=`${wfOrderText(task,tasks)}\n입력: ${inputLabels.join(' · ')||'선택한 참고 자료'}\n출력: ${outputs.join(' · ')||'텍스트 응답'}`;
      card.dataset.taskId=task.id;
      if(container.id==='wf-editor-order'){
        const index=tasks.findIndex(t=>t.id===task.id);card.classList.toggle('selected',index===wfState.taskIndex);card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label',task.name+' 설정');
        const select=()=>{wfSaveTaskForm();wfTaskForm(index);};card.onclick=select;card.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};
      }
      if(container.id==='workflow-live-order'){
        card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label',task.name+' 실행 상세');
        const select=()=>{for(const panel of $('workflow-tasks').children)panel.hidden=panel.dataset.taskId!==task.id;for(const node of container.querySelectorAll('.flow-task'))node.classList.toggle('selected',node.dataset.taskId===task.id);wfState.selectedTask=task.id;};card.onclick=select;card.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};
      }
      group.append(card);
    } container.append(group);
  }
  window.uiPresentation?.graphRendered(container);
  wfConnect(container,tasks);
}
// Edges use the actual dependency IDs, including joins and parallel branches.
const wfGraphObservers=new Map();
function wfConnect(container,tasks){
  wfGraphObservers.get(container)?.disconnect();
  const draw=()=>{
    container.querySelector('.flow-edges')?.remove();
    if(!container.getBoundingClientRect().width)return;
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.classList.add('flow-edges');svg.setAttribute('aria-hidden','true');
    const bounds=container.getBoundingClientRect(),scale=bounds.width/container.offsetWidth||1;svg.setAttribute('width',container.clientWidth);svg.setAttribute('height',container.scrollHeight);
    const markerId='arrow-'+container.id;svg.innerHTML=`<defs><marker id="${markerId}" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="#808080"/></marker></defs>`;
    for(const task of tasks){const target=container.querySelector(`[data-task-id="${CSS.escape(task.id)}"]`);if(!target)continue;const to=target.getBoundingClientRect();
      for(const id of task.depends_on){const source=container.querySelector(`[data-task-id="${CSS.escape(id)}"]`);if(!source)continue;const from=source.getBoundingClientRect();const x1=(from.left+from.width/2-bounds.left)/scale,y1=(from.bottom-bounds.top)/scale,x2=(to.left+to.width/2-bounds.left)/scale,y2=(to.top-bounds.top)/scale;
        const path=document.createElementNS(ns,'path');path.setAttribute('d',`M${x1},${y1} C${x1},${y1+18} ${x2},${y2-18} ${x2},${y2-3}`);path.setAttribute('fill','none');path.setAttribute('stroke','#808080');path.setAttribute('stroke-width','1.5');path.setAttribute('marker-end',`url(#${markerId})`);if(target.classList.contains('running'))path.classList.add('edge-running');svg.append(path);
      }
    }container.prepend(svg);
  };
  container.classList.add('dag-flow');const observer=new ResizeObserver(draw);observer.observe(container);wfGraphObservers.set(container,observer);if(container.graphZoomListener)container.removeEventListener('graphzoom',container.graphZoomListener);container.graphZoomListener=draw;container.addEventListener('graphzoom',draw);requestAnimationFrame(draw);
}
async function wfLoadWork(id,preserve=false) {
  if(wfState.workId!==id) { wfClose(); wfState.run=null; wfState.definition=null; wfState.cursor=0; $('workflow-run-panel').hidden=true; $('workflow-definition-panel').hidden=true; }
  const checked=preserve?selectedLibrary():[]; wfState.workId=id; const selection=++wfState.loadSelection;
  const [defs,runs,lib,detail]=await Promise.all([api(`/works/${id}/workflows`),api(`/works/${id}/workflow-runs`),api(`/library?work_id=${encodeURIComponent(id)}`),api(`/works/${id}`)]);
  if(wfState.workId!==id || selection!==wfState.loadSelection || state.work?.id!==id) return;
  wfState.definitions=defs; wfState.library=[...(detail.artifact_candidates||[]).map(a=>({...a,selection_scope:lib.find(p=>p.id===a.id)?.publication.scope||'WORK'})),...lib.filter(a=>a.work_id!==id).map(a=>({...a,selection_scope:a.publication.scope}))]; wfState.sources=detail.sources;
  $('workflow-list').replaceChildren();
  for(const d of defs) { const div=document.createElement('div'); div.className='ui-collection';div.dataset.definitionId=d.id;const choice=wfButton('',()=>wfSelectDefinition(d.id));choice.classList.add('ui-collection-trigger');choice.setAttribute('aria-pressed',String(wfState.definition?.id===d.id));choice.innerHTML=`<strong>${wfEscape(d.name)}</strong><small>${wfEscape(d.description?.slice(0,80)||'선택하여 Flow와 상세 확인')}</small>`;div.append(choice,UI.status(d.enabled?'ACTIVE':'DISABLED'));$('workflow-list').append(div); }
  if(!defs.length) $('workflow-list').append(UI.empty('아직 Workflow가 없습니다.','새 Workflow나 템플릿으로 연결된 작업을 구성하세요.'));
  if($('workflow-view-summary'))$('workflow-view-summary').textContent=`Workflow ${defs.length}개 · 실행 이력 ${runs.length}개`;
  $('workflow-history').replaceChildren();
  for(const r of runs) { const div=document.createElement('div'); div.className='ui-collection';const choice=wfButton('',()=>wfSelectRun(r.id));choice.classList.add('ui-collection-trigger');choice.innerHTML=`<strong>${wfEscape(defs.find(d=>d.id===r.workflow_definition_id)?.name||'Workflow')}${r.parent_workflow_run_id?' · 분기':''}</strong><small>${date(r.created_at)}</small>`;div.append(choice,UI.status(r.status));$('workflow-history').append(div); }
  if(!runs.length)$('workflow-history').append(UI.empty('아직 Workflow 실행 이력이 없습니다.'));
  $('library-context-list').replaceChildren();
  for(const a of wfState.library) { const label=UI.selectable({title:a.name,value:a.id,selected:checked.includes(a.id),metadata:[['출처',a.location_type==='SHARED'?'Shared':'이전 결과물'],['공개 범위',a.selection_scope||a.publication?.scope||'WORK'],['크기',UI.fileSize(a.size)],['실행 Context',defaultContextPolicy(a,'ARTIFACT')]]});label.dataset.sourceGroup=a.location_type==='SHARED'?'SHARED':'PREVIOUS';$('library-context-list').append(label); }
  if(!wfState.library.length) $('library-context-list').replaceChildren(UI.empty('선택할 이전 결과물이 없습니다.','Work 결과물이나 Shared Library의 자료를 사용할 수 있습니다.'));
  window.controlCenter?.groupMaterials();
  await window.workflowOperations?.loadWork(id);
}
async function wfSelectDefinition(id) {
  const selection=++wfState.definitionSelection;
  const data=await api(`/workflows/${id}`); if(data.work_id!==wfState.workId || selection!==wfState.definitionSelection) return;
  window.controlCenter?.tab('workflow');
  wfState.definition=data; $('workflow-definition-panel').hidden=false; $('workflow-name').textContent=data.name;
  for(const row of $('workflow-list').children)row.querySelector('button')?.setAttribute('aria-pressed',String(row.dataset.definitionId===id));
  $('workflow-description').textContent=data.description;
  const descriptionDetails=$('workflow-description').closest('details');if(descriptionDetails)descriptionDetails.hidden=!data.description;
  $('workflow-start').disabled=!data.enabled || state.work.archived;
  wfDiagram($('workflow-order'),data.tasks);
}
async function wfStart() {
  const d=wfState.definition;
  const body={expected_revision:d.revision,source_ids:selectedContext(),artifact_ids:selectedLibrary()};
  const signature=JSON.stringify([d.id,body]); if(wfState.command?.signature!==signature) wfState.command={signature,key:crypto.randomUUID()};
  const result=await api(`/workflows/${d.id}/runs`,{method:'POST',body,headers:{'Idempotency-Key':wfState.command.key}});
  wfState.command=null; await wfSelectRun(result.workflow_run.id); await wfLoadWork(wfState.workId,true);
}
function wfCurrent(detail) { return Object.fromEntries(detail.task_runs.filter(t=>t.is_current).map(t=>[t.task_definition_id,t])); }
function wfArtifactLink(a) { return wfButton(a.name,()=>preview(a)); }
function wfRenderRun(detail) {
  wfState.run=detail; const wr=detail.workflow_run; $('workflow-run-panel').hidden=false;
  $('workflow-run-status').textContent=wr.parent_workflow_run_id?'분기 Workflow':'Workflow 진행 상황';$('workflow-run-status').title=`동시 실행 ${detail.max_parallel_tasks}개${detail.snapshot.git_base_commit?' · 기준 commit '+detail.snapshot.git_base_commit:''}`;
  $('workflow-cancel').disabled=['COMPLETED','CANCELLED'].includes(wr.status);
  const current=wfCurrent(detail);
  const completed=Object.values(current).filter(t=>t.status==='COMPLETED').length,total=detail.snapshot.tasks.length;
  $('workflow-progress').innerHTML=`<div class="workflow-progress-heading"><strong>${completed} / ${total} Task 완료</strong><span class="badge" data-status="${wfEscape(wr.status)}">${wfEscape(window.controlCenter?.status(wr.status)||wr.status)}</span></div><div class="progress-track"><span style="width:${total?completed/total*100:0}%"></span></div>`;
  wfDiagram($('workflow-live-order'),detail.snapshot.tasks,current);
  $('workflow-tasks').replaceChildren();
  for(const spec of detail.snapshot.tasks) {
    const t=current[spec.id]; const panel=document.createElement('article'); panel.className='task-detail';panel.dataset.taskId=spec.id;
    const attempts=detail.task_runs.filter(a=>a.task_definition_id===spec.id);
    const heading=document.createElement('div');heading.className='ui-detail-heading';const title=document.createElement('h3');title.textContent=spec.name;heading.append(title,UI.status(t.status,taskStatus[t.status]||t.status));panel.append(heading,UI.metadata([['모델',spec.model],['Reasoning',spec.reasoning],['실행 조건',wfOrderText(spec,detail.snapshot.tasks)]],{compact:true}));
    if(t.blocked_reason) { const reason=wfDecode(t.blocked_reason); const waits=(reason.task_run_ids||reason.task_ids||[]).map(id=>{const a=detail.task_runs.find(x=>x.id===id);return detail.snapshot.tasks.find(s=>s.id===a?.task_definition_id)?.name||id;});panel.append(UI.warning(reason.code==='DEPENDENCY_FAILED'?`선행 작업 실패: ${waits.join(', ')}. 재시도 결과를 기다립니다.`:reason.message||`기다리는 작업: ${waits.join(', ')||'선행 작업 완료'}`,'실행 대기 사유')); }
    const selector=document.createElement('select'); wfOptions(selector,attempts.map(a=>[a.id,`시도 ${a.attempt_number} · ${taskStatus[a.status]||a.status}`]),t.id); selector.setAttribute('aria-label',spec.name+' 실행 시도');const attemptsDetails=document.createElement('details');attemptsDetails.innerHTML='<summary>실행 시도 선택</summary>';attemptsDetails.append(selector);panel.append(attemptsDetails);
    const content=document.createElement('div');panel.append(content);
    const renderAttempt=()=>{ const a=attempts.find(x=>x.id===selector.value); content.replaceChildren();if(a.approval){const review=document.createElement('p');review.textContent='검토: '+({WAITING:'승인 대기',APPROVED:'승인됨',REJECTED:'반려',REVISION_REQUESTED:'수정 요청',CANCELLED:'취소'}[a.approval.status]||a.approval.status);if(a.approval.status==='WAITING')review.append(wfButton('검토 열기',()=>window.controlCenter.tab('review')));content.append(review);}
      const input=document.createElement('p');input.textContent='받은 결과물: '; for(const r of a.inputs) input.append(wfArtifactLink(r.artifact),' '); if(!a.inputs.length) input.append('없음'); content.append(input);
      const output=document.createElement('p');output.textContent='만든 결과물: '; for(const r of a.outputs) output.append(wfArtifactLink(r.artifact),' '); if(!a.outputs.length) output.append('아직 없음'); content.append(output);
      if(a.error) { const p=document.createElement('p');p.className='task-error';const e=wfDecode(a.error);p.textContent=`${e.code==='OUTPUT_CONTRACT_FAILED'?'필수 결과물 누락 또는 형식 불일치':e.code||'오류'}: ${e.message||JSON.stringify(e.report||{})}`;content.append(p); }
      const actions=document.createElement('div');actions.className='actions';actions.append(wfButton('새 Markdown',()=>window.storageUI.open('MARKDOWN',spec.output_rule[0]?.path)));
      if(a.run_id) actions.append(wfButton('실행 기록 보기',()=>selectRun(a.run_id)));
      actions.append(wfButton('재시도',async()=>{await api(`/task-runs/${a.id}/retry`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()}});await wfSelectRun(wr.id);},!a.is_current||a.status!=='FAILED'||wr.cancel_requested||a.run?.safety_block));
      actions.append(wfButton(a.status==='FAILED'?'이 경로 포기':'작업 취소',async()=>{await api(`/task-runs/${a.id}/cancel`,{method:'POST'});await wfSelectRun(wr.id);},!a.is_current||!['BLOCKED','READY','QUEUED','RUNNING','FAILED'].includes(a.status)));
      if(a.status==='COMPLETED')actions.append(wfButton('시간 후 이어하기',()=>window.workflowOperations.openDelay(a)));
      actions.append(wfButton('이 결과로 분기',()=>wfOpenBranch(a,spec),a.status!=='COMPLETED'||!a.outputs.length));const controls=document.createElement('details');controls.className='task-more-actions';controls.innerHTML='<summary>재시도 · 분기 · 예약</summary>';const runButton=[...actions.children].find(b=>b.textContent==='실행 기록 보기');if(runButton)content.append(runButton);controls.append(actions);content.append(controls);
      if(a.run?.safety_block) content.append(wfButton('실행 상태 다시 확인',async()=>{await api(`/runs/${a.run_id}/reconcile`,{method:'POST'});await wfSelectRun(wr.id);}));
    };selector.onchange=renderAttempt;renderAttempt();$('workflow-tasks').append(panel);
  }
  const selected=detail.snapshot.tasks.find(t=>t.id===wfState.selectedTask)||detail.snapshot.tasks.find(t=>current[t.id]?.status==='RUNNING'||current[t.id]?.approval?.status==='WAITING')||detail.snapshot.tasks[0];
  if(selected)$('workflow-live-order').querySelector(`[data-task-id="${CSS.escape(selected.id)}"]`)?.click();
  window.workflowOperations?.renderRun(detail);
  $('workflow-events').textContent=detail.events.slice(-100).map(e=>`[${e.type}] ${JSON.stringify(e.payload)}`).join('\n');
  $('workflow-branches').replaceChildren(); for(const b of detail.branches) $('workflow-branches').append(wfButton(`분기: ${b.status}`,()=>wfSelectRun(b.id)));
  UI.enhance($('workflow-run-panel'));
}
async function wfSelectRun(id) {
  wfClose(); const selection=wfState.runSelection; const detail=await api(`/workflow-runs/${id}`); if(detail.workflow_run.work_id!==wfState.workId || selection!==wfState.runSelection) return;
  window.controlCenter?.workflowSelected(id);
  wfState.cursor=detail.last_event_id;wfRenderRun(detail);
  if(!['CREATED','RUNNING','WAITING_APPROVAL','PAUSED'].includes(detail.workflow_run.status)) return;
  const source=new EventSource(`/api/workflow-runs/${id}/events?after=${wfState.cursor}`);wfState.stream=source;
  let refreshing=false,again=false;
  const refresh=async()=>{if(refreshing){again=true;return;}refreshing=true;try{do{again=false;const next=await api(`/workflow-runs/${id}`);if(selection!==wfState.runSelection||wfState.run?.workflow_run.id!==id)return;wfState.cursor=Math.max(wfState.cursor,next.last_event_id);wfRenderRun(next);await dashboard();if(selection!==wfState.runSelection||wfState.run?.workflow_run.id!==id)return;if(!['CREATED','RUNNING','WAITING_APPROVAL','PAUSED'].includes(next.workflow_run.status)){wfClose();await wfLoadWork(wfState.workId,true);break;}}while(again);}catch(e){wfNotice(e);}finally{refreshing=false;}};
  for(const type of ['WORKFLOW_STARTED','WORKFLOW_COMPLETED','WORKFLOW_FAILED','WORKFLOW_PARTIAL','WORKFLOW_CANCELLED','TASK_BLOCKED','TASK_READY','TASK_QUEUED','TASK_STARTED','TASK_COMPLETED','TASK_FAILED','TASK_CANCELLED','TASK_SKIPPED','TASK_RECONCILED','ARTIFACT_HANDOFF','ARTIFACT_CREATED','RETRY_CREATED','BRANCH_CREATED','APPROVAL_REQUESTED','APPROVAL_APPROVED','APPROVAL_REJECTED','APPROVAL_REVISION_REQUESTED','REVISION_CREATED','WORKFLOW_WAITING_APPROVAL','WORKFLOW_PAUSED','WORKFLOW_RESUMED','WORKFLOW_REJECTED','CHECKPOINT_CREATED','DELAYED_RESUME_TRIGGERED']) source.addEventListener(type,e=>{if(selection!==wfState.runSelection||wfState.run?.workflow_run.id!==id||Number(e.lastEventId)<=wfState.cursor)return;wfState.cursor=Number(e.lastEventId);refresh();});
  source.onerror=refresh;
}
function wfDefaultTask() {const m=state.models.find(m=>m.default)||state.models[0];return {id:'task_'+crypto.randomUUID().replaceAll('-',''),name:`작업 ${(wfState.editing?.tasks.length||0)+1}`,instruction:'',runtime:'CODEX',model:null,reasoning:null,execution_profile:{},context_rule:{inherit_workflow_context:true,source_ids:[],artifact_ids:[]},input_rule:[],output_rule:[{output_key:'result',path:'result.md',required:true,media_type:null}],workspace_mode:'ARTIFACT_ONLY',display_order:wfState.editing?.tasks.length||0,depends_on:[]};}
function wfSaveTaskForm() {
  const task=wfState.editing?.tasks[wfState.taskIndex];if(!task)return;
  task.name=$('wf-task-name').value;task.instruction=$('wf-task-instruction').value;task.execution_profile=window.executionSettings.read('wf-task-');task.model=task.execution_profile.model||null;task.reasoning=task.execution_profile.reasoning||null;task.workspace_mode=$('wf-task-mode').value;task.review_policy=$('wf-task-review').value;
  task.depends_on=[...$('wf-task-dependencies').querySelectorAll('input:checked')].map(i=>i.value);
  task.context_rule={inherit_workflow_context:$('wf-inherit-context').checked,source_ids:[...$('wf-task-context').querySelectorAll('input[data-kind="source"]:checked')].map(i=>i.value),artifact_ids:[...$('wf-task-context').querySelectorAll('input[data-kind="artifact"]:checked')].map(i=>i.value)};
  task.input_rule=[...$('wf-task-inputs').querySelectorAll('input:checked')].map(i=>JSON.parse(i.dataset.binding));
  const old=task.output_rule;task.output_rule=[...$('wf-task-outputs').querySelectorAll('.output-editor-row')].map((div,i)=>({output_key:div.dataset.key||`output${i+1}`,path:div.querySelector('input[type="text"]').value,required:div.querySelector('input[type="checkbox"]').checked,media_type:old.find(o=>o.output_key===div.dataset.key)?.media_type||null}));
}
function wfCheckbox(container,label,value,checked,data={}) {const el=document.createElement('label');el.className='context-item';const input=document.createElement('input');input.type='checkbox';input.value=value;input.checked=checked;Object.assign(input.dataset,data);el.append(input,document.createTextNode(label));container.append(el);return input;}
function wfOutputRow(rule={output_key:'output_'+crypto.randomUUID().slice(0,8),path:'',required:true},container=$('wf-task-outputs')) {const div=document.createElement('div');div.className='output-editor-row';div.dataset.key=rule.output_key;const path=document.createElement('input');path.type='text';path.placeholder='결과물 파일명 (예: design.md)';path.value=rule.path;const required=document.createElement('input');required.type='checkbox';required.checked=rule.required;const label=document.createElement('label');label.append(required,' 필수');div.append(path,label,wfButton('삭제',()=>div.remove()));container.append(div);}
function wfTaskForm(index) {
  wfState.taskIndex=index;const task=wfState.editing.tasks[index]; $('wf-task-form').hidden=!task; if(!task)return;
  $('wf-selected-title').textContent=task.name || 'Task Detail';$('wf-task-name').value=task.name;$('wf-task-instruction').value=task.instruction;$('wf-task-mode').value=task.workspace_mode;$('wf-task-review').value=task.review_policy||'AUTO';
  window.executionSettings.populate('wf-task-',task.execution_profile||{model:task.model,reasoning:task.reasoning});
  $('wf-task-dependencies').replaceChildren();for(const other of wfState.editing.tasks)if(other.id!==task.id)wfCheckbox($('wf-task-dependencies'),`${other.name} 완료 후`,other.id,task.depends_on.includes(other.id));
  $('wf-inherit-context').checked=task.context_rule.inherit_workflow_context;
  $('wf-task-context').replaceChildren();for(const s of wfState.sources)wfCheckbox($('wf-task-context'),s.name,s.id,task.context_rule.source_ids.includes(s.id),{kind:'source'});for(const a of wfState.library)wfCheckbox($('wf-task-context'),`${a.name} · ${a.selection_scope||a.publication.scope}`,a.id,task.context_rule.artifact_ids.includes(a.id),{kind:'artifact'});
  for(const id of task.context_rule.artifact_ids.filter(id=>!wfState.library.some(a=>a.id===id))) wfCheckbox($('wf-task-context'),'기존 선택 결과물 · 현재 사용 가능 여부를 확인하세요',id,true,{kind:'artifact'});
  $('wf-task-inputs').replaceChildren();const selected=task.input_rule;
  for(const other of wfState.editing.tasks)if(other.id!==task.id)for(const o of [...other.output_rule,...(other.workspace_mode==='GIT_WORKTREE'?[{output_key:'git_patch',path:'changes.patch'},{output_key:'git_changes',path:'changes.json'},{output_key:'git_new_files',path:'new-files.zip'}]:[])]) {
    const prior=selected.find(b=>b.task_definition_id===other.id&&b.output_key===o.output_key);const b=prior||{input_key:'input_'+other.id.slice(-8)+'_'+o.output_key,task_definition_id:other.id,output_key:o.output_key};wfCheckbox($('wf-task-inputs'),`${other.name} → ${o.path}`,JSON.stringify(b),!!prior,{binding:JSON.stringify(b)});
  }
  for(const a of wfState.library){const prior=selected.find(b=>b.artifact_id===a.id);const b=prior||{input_key:'library_'+a.id.slice(-8),artifact_id:a.id};wfCheckbox($('wf-task-inputs'),`Library → ${a.name}`,JSON.stringify(b),!!prior,{binding:JSON.stringify(b)});}
  // Retain fixed artifacts unavailable in Library lists (same-Work direct bindings).
  for(const b of selected.filter(b=>b.artifact_id&&!wfState.library.some(a=>a.id===b.artifact_id)))wfCheckbox($('wf-task-inputs'),'기존 선택 결과물',JSON.stringify(b),true,{binding:JSON.stringify(b)});
  $('wf-task-outputs').replaceChildren();for(const o of task.output_rule)wfOutputRow(o);
  wfRenderEditorList();
}
function wfTaskReasoning(value) {window.executionSettings.reasoning('wf-task-',value);}
function wfRenderUnresolved() {
  const container=$('wf-unresolved');container.replaceChildren();
  for(const binding of wfState.editing.unresolved_bindings) {
    const task=wfState.editing.tasks.find(t=>t.id===binding.task_id);
    const row=document.createElement('div');row.className='row';
    const label=document.createElement('span');
    label.textContent=`${task?.name||'작업'} · ${binding.name||binding.binding?.input_key||binding.workspace_mode||binding.source_id||'참고 자료'}: 다시 선택하거나 제외하세요.`;
    const select=document.createElement('select');
    const candidates=binding.source_id?wfState.sources:wfState.library;
    wfOptions(select,[['','자료 선택'],...candidates.map(a=>[a.id,a.name])],'');
    const resolve=(exclude)=>{
      wfSaveTaskForm();
      if(!exclude) {
        if(binding.workspace_mode) { if(!state.work.linked_workspace_path) throw new Error('연결 프로젝트가 필요합니다.'); task.workspace_mode=binding.workspace_mode; }
        else {
          if(!select.value) throw new Error('대체 자료를 선택하세요.');
          if(binding.source_id) task.context_rule.source_ids=[...new Set([...task.context_rule.source_ids,select.value])];
          else if(typeof binding.binding==='object') {task.input_rule=task.input_rule.filter(b=>b.input_key!==binding.binding.input_key);task.input_rule.push({input_key:binding.binding.input_key,artifact_id:select.value});}
          else task.context_rule.artifact_ids=[...new Set([...task.context_rule.artifact_ids,select.value])];
        }
      }
      wfState.editing.unresolved_bindings=wfState.editing.unresolved_bindings.filter(b=>b!==binding);
      wfTaskForm(wfState.taskIndex);wfRenderUnresolved();
    };
    row.append(label);if(!binding.workspace_mode)row.append(select);
    row.append(wfButton('다시 선택',()=>resolve(false)),wfButton('이 항목 제외',()=>resolve(true)));container.append(row);
  }
}
function wfRenderEditorList() {$('wf-editor-tasks').replaceChildren();wfState.editing.tasks.forEach((t,i)=>$('wf-editor-tasks').append(wfButton(`${i+1}. ${t.name}`,()=>{wfSaveTaskForm();wfTaskForm(i);})));wfDiagram($('wf-editor-order'),wfState.editing.tasks);}
function wfOpenEditor(data=null) {wfState.editing=data?structuredClone(data):{name:'새 Workflow',description:'',enabled:true,tasks:[],unresolved_bindings:[]};if(!wfState.editing.tasks.length)wfState.editing.tasks.push(wfDefaultTask());window.controlCenter?.taskTab('basic');$('wf-editor-name').value=wfState.editing.name;$('wf-editor-description').value=wfState.editing.description;$('wf-editor-enabled').checked=wfState.editing.enabled;wfRenderUnresolved();wfTaskForm(0);$('workflow-editor').showModal();}
async function wfSaveDefinition(){wfSaveTaskForm();const d=wfState.editing;const body={name:$('wf-editor-name').value,description:$('wf-editor-description').value,enabled:$('wf-editor-enabled').checked,expected_revision:d.id?d.revision:null,tasks:d.tasks,unresolved_bindings:d.unresolved_bindings};const result=await api(d.id?`/workflows/${d.id}`:`/works/${wfState.workId}/workflows`,{method:d.id?'PUT':'POST',body});$('workflow-editor').close();await wfLoadWork(wfState.workId,true);await wfSelectDefinition(result.id);}
async function wfOpenTemplates(){const list=await api('/workflow-templates');$('template-list').replaceChildren();for(const t of list)$('template-list').append(wfButton(`${t.name} · 복제`,async()=>{const result=await api(`/workflow-templates/${t.id}/clone`,{method:'POST',body:{target_work_id:wfState.workId}});$('workflow-templates').close();await wfLoadWork(wfState.workId,true);wfOpenEditor(result);}));if(!list.length)$('template-list').textContent='저장된 템플릿이 없습니다.';$('workflow-templates').showModal();}
function wfOpenBranch(task,spec) {wfState.branch={task,spec};$('branch-instruction').value=spec.instruction;window.executionSettings.populate('branch-',spec.execution_profile||{model:spec.model,reasoning:spec.reasoning});$('branch-history').value='ARTIFACT';$('branch-inputs').replaceChildren();for(const o of task.outputs)wfCheckbox($('branch-inputs'),o.artifact.name,o.output_key,true);$('branch-outputs').replaceChildren();for(const o of spec.output_rule)wfOutputRow(o,$('branch-outputs'));$('branch-revision').checked=false;$('workflow-branch').showModal();}
function wfBranchReasoning(value){window.executionSettings.reasoning('branch-',value);}
async function wfBranch(){const {task,spec}=wfState.branch;const output_rule=[...$('branch-outputs').querySelectorAll('.output-editor-row')].map(div=>({output_key:div.dataset.key,path:div.querySelector('input[type=text]').value,required:div.querySelector('input[type=checkbox]').checked,media_type:spec.output_rule.find(o=>o.output_key===div.dataset.key)?.media_type||null}));const keys=[...$('branch-inputs').querySelectorAll('input:checked')].map(i=>i.value);const revision={};if($('branch-revision').checked)for(const o of task.outputs)if(keys.includes(o.output_key))revision[o.output_key]=o.artifact.id;const result=await api(`/task-runs/${task.id}/branch`,{method:'POST',body:{instruction:$('branch-instruction').value,execution_profile:window.executionSettings.read('branch-'),source_output_keys:keys,output_rule,history_mode:$('branch-history').value,revision_of:revision},headers:{'Idempotency-Key':crypto.randomUUID()}});$('workflow-branch').close();await wfSelectRun(result.workflow_run.id);await wfLoadWork(wfState.workId,true);}
function wfBind(id,fn){action(id,fn);}
wfBind('workflow-new',()=>wfOpenEditor());wfBind('workflow-edit',()=>wfOpenEditor(wfState.definition));wfBind('workflow-start',wfStart);
wfBind('workflow-disable',async()=>{await api(`/workflows/${wfState.definition.id}`,{method:'DELETE'});await wfLoadWork(wfState.workId,true);await wfSelectDefinition(wfState.definition.id);});
wfBind('workflow-save-template',async()=>{await api(`/workflows/${wfState.definition.id}/templates`,{method:'POST',body:{}});notice('템플릿으로 저장했습니다.');});wfBind('workflow-templates-open',wfOpenTemplates);wfBind('templates-close',()=>$('workflow-templates').close());
wfBind('workflow-cancel',async()=>{await api(`/workflow-runs/${wfState.run.workflow_run.id}/cancel`,{method:'POST'});await wfSelectRun(wfState.run.workflow_run.id);});
wfBind('wf-add-task',()=>{wfSaveTaskForm();wfState.editing.tasks.push(wfDefaultTask());wfTaskForm(wfState.editing.tasks.length-1);});
wfBind('wf-remove-task',()=>{const id=wfState.editing.tasks[wfState.taskIndex].id;wfState.editing.tasks.splice(wfState.taskIndex,1);for(const t of wfState.editing.tasks){t.depends_on=t.depends_on.filter(p=>p!==id);t.input_rule=t.input_rule.filter(b=>b.task_definition_id!==id);}if(!wfState.editing.tasks.length)wfState.editing.tasks.push(wfDefaultTask());wfTaskForm(0);});
wfBind('wf-add-output',()=>wfOutputRow());wfBind('wf-update-preview',()=>{wfSaveTaskForm();wfRenderEditorList();});wfBind('wf-save',wfSaveDefinition);wfBind('wf-editor-close',()=>$('workflow-editor').close());
$('wf-task-model').onchange=()=>wfTaskReasoning();$('branch-model').onchange=()=>wfBranchReasoning();wfBind('branch-add-output',()=>wfOutputRow(undefined,$('branch-outputs')));wfBind('branch-execute',wfBranch);wfBind('branch-close',()=>$('workflow-branch').close());
wfBind('artifact-publish',async()=>{await api(`/artifacts/${$('artifact-publish').dataset.id}/publish`,{method:'POST',body:{scope:$('artifact-scope').value}});notice('Library에 등록했습니다.');if(wfState.workId)await wfLoadWork(wfState.workId,true);});
window.workflows={loadWork:wfLoadWork,close:wfClose,leave:wfLeave,selectedLibrary};
