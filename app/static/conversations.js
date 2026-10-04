'use strict';
// Small controls around the existing Work composer and Run viewer.
window.conversations = (() => {
  let selected = null, workId = null, generation = 0, pendingAction = 'NEW', command = null, threads = [], discoveryCursor = null;
  const panel = document.createElement('section'); panel.className = 'panel'; panel.id = 'conversation-panel';
  panel.innerHTML = `<div class="panel-heading"><h2>대화 이력</h2><button id="conversation-refresh" type="button">목록 갱신</button></div><div class="conversation-browser"><section class="thread-list-pane"><label class="thread-search">대화 찾기<input id="conversation-search" type="search" placeholder="제목 · 최근 요청으로 찾기"></label><div id="conversation-list" role="group" aria-label="Work의 기존 대화"></div><p id="conversation-empty" class="empty" hidden>저장된 대화가 없습니다. 아래에서 새 요청을 시작하세요.</p></section><section class="thread-detail-pane"><div id="conversation-selected" class="thread-selection-heading">이력을 볼 대화를 선택하세요.</div><dl id="conversation-thread-meta" class="thread-metadata"></dl><div id="conversation-thread-actions" class="actions" aria-label="선택한 대화의 동작"></div><p id="conversation-action-help" class="info-note">왼쪽에서 대화를 선택하면 이어하기·질문·분기 등의 동작을 사용할 수 있습니다.</p><div id="conversation-history" class="thread-history"></div><details id="conversation-management" hidden><summary>대화 관리 · 고급 정보</summary><div class="actions"><button id="conversation-archive" type="button">대화 보관</button><button id="conversation-close" type="button">대화 종료</button><button id="conversation-compact-reconcile" type="button">불확정 압축 상태 확인</button></div><dl id="conversation-ids" class="metadata-grid"></dl></details></section></div><details id="conversation-discovery" hidden><summary>현재 Workspace의 기존 Codex 대화 연결</summary><p class="info-note">같은 Workspace 경로의 대화를 조회합니다. 완료된 대화를 선택하여 이 Work에 연결한 뒤 이어서 사용할 수 있습니다.</p><button id="conversation-discover" type="button">Codex 대화 찾기</button><div id="conversation-discovered"></div><button id="conversation-discover-more" type="button" hidden>더 보기</button></details><div id="conversation-query-options" hidden><label><input id="query-write" type="checkbox">질문에서 쓰기 허용</label><label><input id="query-artifacts" type="checkbox">질문 결과물 수집 (쓰기 허용 필요)</label><p>기본: 읽기 전용 · 결과물 생성 없음 · 선택한 자료만 전달. 저장하지 않은 답변은 24시간 후 폐기됩니다.</p></div><p id="conversation-mode" class="muted"></p><details><summary>임시 질문 결과</summary><div id="conversation-queries"></div></details>`;
  $('execution-conversations').append(panel);
  $('execution-actions').innerHTML='<button type="button" data-conversation-action="NEW">+ 새 대화에서 요청</button>';
  $('conversation-thread-actions').innerHTML=[['CONTINUE','기존 대화 계속'],['QUERY','질문하기'],['FORK','분기'],['COMPACT','Compact'],['HANDOFF','새 대화로 넘기기']].map(([a,t])=>`<button type="button" data-conversation-action="${a}" disabled>${t}</button>`).join('');
  $('material-context-packs').insertAdjacentHTML('beforeend',`<div class="actions"><button id="pack-build" type="button">Context Pack 만들기</button><button id="pack-view" type="button">선택 Pack 미리보기</button></div><label>검토한 Pack<select id="conversation-pack"><option value="">선택 안 함</option></select></label><label>자료 예산 (예상 Token)<input id="conversation-budget" type="number" value="40000" min="100" max="1000000"></label><label><input id="conversation-over-budget" type="checkbox">경고를 확인하고 예산 초과 실행 허용</label>`);
  $('material-resources').insertAdjacentHTML('beforeend',`<button id="resource-promote-run" type="button">선택 실행에서 자료 저장</button><div id="conversation-resources"></div>`);
  const inspector = document.createElement('details'); inspector.innerHTML='<summary>현재 실행의 Context</summary><div id="context-inspector"></div>';
  $('run-meta').after(inspector);
  const dialog = document.createElement('dialog'); dialog.id='pack-dialog'; dialog.className='workflow-dialog';
  dialog.innerHTML=`<h2>새 대화에 전달할 상태</h2><p id="pack-candidates-note"></p><label>이름<input id="pack-name" value="작업 상태"></label>
    ${[['goal','목표'],['current','현재 작업'],['completed','완료된 작업'],['pending','남은 작업'],['decisions','주요 결정'],['blockers','Blocker'],['next_instruction','다음 지시']].map(([key,title])=>`<label>${title}<textarea id="pack-${key}" rows="2"></textarea></label>`).join('')}
    <div id="pack-candidates"></div><label>기존 Pack의 새 버전<select id="pack-previous"><option value="">새 Pack</option></select></label>
    <div class="actions"><button id="pack-preview" type="button">선택 내용 미리보기</button><button id="pack-dialog-close" type="button">닫기</button></div><div id="pack-preview-readable"></div><details><summary>고급 정보 · Pack Snapshot</summary><pre id="pack-preview-text"></pre></details><button id="pack-confirm" type="button" hidden>전달 내용 확인 · Pack 저장</button>`;
  document.body.append(dialog);
  const promotion = document.createElement('dialog'); promotion.id='promotion-dialog';
  promotion.innerHTML=`<h2>선택한 결론을 자료로 저장</h2><label>이름<input id="promotion-title"></label><label>종류<select id="promotion-kind">${['DECISION','KNOWLEDGE','POLICY','ARTIFACT','TEMPLATE','NOTE','SUMMARY'].map(x=>`<option>${x}</option>`).join('')}</select></label><label>범위<select id="promotion-scope">${['WORK','THREAD','CATEGORY','GLOBAL'].map(x=>`<option>${x}</option>`).join('')}</select></label><label>저장할 내용<textarea id="promotion-content" rows="8"></textarea></label><label><input id="promotion-default" type="checkbox">다음 실행에 기본 포함</label><button id="promotion-save" type="button">선택 내용 저장</button><button id="promotion-close" type="button">닫기</button>`;
  document.body.append(promotion);
  let draftPack = null, promoteSource = null, queryDecision = false;
  const guard = fn => async () => { try { notice(''); await fn(); } catch(e) { notice(e.message); } };
  const threadKey=t=>t?.id||t?.legacy_run_id||'';
  const threadStatus=value=>({ACTIVE:'진행 중',IDLE:'대기',ARCHIVED:'보관됨',CLOSED:'종료됨',SUPERSEDED:'새 대화로 전환됨'}[value]||value);
  const requestFor=run=>state.workDetail?.requests.find(r=>r.id===run?.request_id)?.instruction||'';
  const runTime=run=>run?.operation==='import'?run.started_at||run.completed_at?date(run.started_at||run.completed_at):'원본 시각 미제공':date(run?.created_at);
  function enrich(t){
    const data=state.workDetail;
    let runtimeSync={};try{runtimeSync=JSON.parse(t.usage||'{}').runtime_sync||{};}catch{}
    const runtimeId=t.codex_thread_id||data?.runs.find(r=>r.id===t.legacy_run_id||(t.id&&r.conversation_id===t.id))?.thread_id||t.runtimeId;
    const runs=(data?.runs||[]).filter(r=>(t.id&&r.conversation_id===t.id)||(runtimeId&&r.thread_id===runtimeId)||r.id===t.legacy_run_id).sort((a,b)=>a.created_at.localeCompare(b.created_at));
    const last=runs.at(-1),first=requestFor(runs[0]);
    const status=['ARCHIVED','CLOSED','SUPERSEDED'].includes(t.status)?t.status:runtimeSync.active||runs.some(r=>['CREATED','RUNNING'].includes(r.status))?'ACTIVE':t.status==='ACTIVE'&&last?'IDLE':t.status;
    return {...t,runtimeId,runs,last,runtimeSync,lastRequest:runtimeSync.last_instruction||requestFor(last),status,title:t.title==='기존 대화'&&first?first.slice(0,160):t.title};
  }
  function remember(){try{const key='control-center-thread:'+workId;if(selected)localStorage.setItem(key,JSON.stringify({id:selected.id,legacy_run_id:selected.legacy_run_id,runtimeId:selected.runtimeId}));else localStorage.removeItem(key);}catch{}}
  function renderThreads(){
    $('conversation-list').replaceChildren();
    for(const t of threads){
      const active=threadKey(t)===threadKey(selected),button=document.createElement('button');button.type='button';button.className='thread-choice';button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));button.dataset.threadKey=threadKey(t);button.dataset.search=(t.title+' '+t.lastRequest).toLowerCase();
      button.innerHTML=`<span class="thread-choice-title">${escape(t.title)}${active?'<span class="thread-selected-mark">✓ 선택됨</span>':''}</span><span class="thread-preview">${escape(t.lastRequest||'요청 이력 없음')}</span><span class="thread-choice-meta"><span>${escape(threadStatus(t.status))}</span><span>${t.runs.length} Run · ${t.runs.filter(r=>r.turn_id).length} Turn</span><span>${runTime(t.last)}</span></span>`;
      button.onclick=guard(()=>chooseThread(t));$('conversation-list').append(button);
    }
    $('conversation-empty').hidden=threads.length>0;filterThreads();
  }
  function filterThreads(){const q=$('conversation-search').value.trim().toLowerCase();for(const button of $('conversation-list').children)button.hidden=!button.dataset.search.includes(q);}
  function renderSelected(){
    const box=$('conversation-history'),same=box.dataset.threadKey===threadKey(selected),expanded=same?new Map([...box.children].filter(e=>e.dataset.runId).map(e=>[e.dataset.runId,e.open])):new Map(),position=box.scrollTop,pinned=box.scrollHeight-box.scrollTop-box.clientHeight<40;
    box.replaceChildren();box.dataset.threadKey=threadKey(selected);
    $('conversation-management').hidden=!selected;
    for(const id of ['conversation-archive','conversation-close','conversation-compact-reconcile'])$(id).disabled=!selected?.id;
    if(!selected){$('conversation-selected').textContent='새 대화';$('conversation-thread-meta').replaceChildren();$('conversation-ids').replaceChildren();$('conversation-action-help').textContent='왼쪽에서 대화를 선택하면 이어하기·질문·분기 등의 동작을 사용할 수 있습니다.';return;}
    $('conversation-selected').innerHTML=`<h3>${escape(selected.title)}</h3>${UI.statusHTML(selected.status,threadStatus(selected.status))}`;
    $('conversation-thread-meta').innerHTML=[['최근 요청',selected.lastRequest||'아직 요청이 없습니다.'],['최근 실행',selected.runtimeSync?.updated_at?date(new Date(selected.runtimeSync.updated_at*1000).toISOString()):runTime(selected.last)],['최근 상태',selected.runtimeSync?.active?'터미널 Codex 실행 중':window.controlCenter?.status(selected.last?.status)||'실행 없음'],['Turn / Run',`${selected.turn_count||selected.runs.filter(r=>r.turn_id).length} Turn · ${selected.runs.length} Run`]].map(([name,value])=>`<div><dt>${name}</dt><dd>${escape(value)}</dd></div>`).join('');
    $('conversation-action-help').textContent='이 대화를 기준으로 동작을 선택한 뒤 아래에 지시를 입력하세요. 계속·분기·Compact는 최신 완료 이력을 기준으로 합니다.';
    $('conversation-ids').innerHTML=[['앱 Thread ID',selected.id],['Codex Thread ID',selected.runtimeId]].map(([name,value])=>`<div><dt>${name}</dt><dd>${escape(value||'아직 없음')}</dd></div>`).join('');
    for(const [index,run] of selected.runs.entries()){
      const entry=document.createElement('details');entry.className='history-turn';entry.dataset.runId=run.id;entry.open=expanded.has(run.id)?expanded.get(run.id):index===selected.runs.length-1;
      const request=requestFor(run),answer=run.final_text||(state.run?.id===run.id?[...(state.liveMessages?.values()||[])].join('\n\n'):'')||(['CREATED','RUNNING'].includes(run.status)?'실행 중입니다. 응답을 기다리고 있습니다.':'저장된 응답이 없습니다.');
      entry.innerHTML=`<summary><span><strong>${escape(request.slice(0,80)||'요청')}</strong><small>${runTime(run)} · ${run.operation==='import'?'연결한 Codex 이력':'Run '+(index+1)}</small></span><span class="badge" data-status="${escape(run.status)}">${escape(window.controlCenter?.status(run.status)||run.status)}</span></summary><div class="history-turn-body"><span class="message-role">내 요청</span><div class="history-question">${escape(request)}</div><span class="message-role">AI 응답</span><div class="history-answer" id="conversation-answer-${escape(run.id)}">${escape(answer)}</div><button type="button" data-open-run>실행 상세 보기</button><details class="history-ids"><summary>고급 정보 · Run / Turn ID</summary><dl class="metadata-grid">${[['Run ID',run.id],['Turn ID',run.turn_id]].map(([label,id])=>`<div><dt>${label}</dt><dd>${escape(id||'아직 없음')}</dd></div>`).join('')}</dl></details></div>`;
      entry.querySelector('[data-open-run]').onclick=guard(()=>selectRun(run.id));box.append(entry);
    }
    if(!selected.runs.length)box.innerHTML='<p class="empty">아직 실행 이력이 없습니다. 새 요청으로 대화를 시작하세요.</p>';
    box.scrollTop=!same||pinned?box.scrollHeight:position;
  }
  async function chooseThread(t){
    selected=t;pendingAction='CONTINUE';state.resume=null;$('resume-label').hidden=true;$('clear-resume').hidden=true;remember();await load(workId,true);window.controlCenter?.tab('execution');
    if(selected?.last)await selectRun(selected.last.id);
    window.uiPresentation?.threadChosen();
  }
  $('conversation-search').oninput=filterThreads;$('conversation-refresh').onclick=guard(()=>selectWork(workId,true));
  async function discover(more=false){
    const id=workId;$('conversation-discover').disabled=true;$('conversation-discover-more').disabled=true;
    try{
      const data=await api(`/works/${id}/runtime-conversations`+(more&&discoveryCursor?'?cursor='+encodeURIComponent(discoveryCursor):''));
      if(state.work?.id!==id||workId!==id)return;
      const box=$('conversation-discovered');if(!more)box.replaceChildren();
      for(const t of data.threads){
        const row=document.createElement('div');row.className='discovered-thread';const type=t.status?.type||t.status,active=type==='active';row.innerHTML=`<span><strong>${escape(t.title.slice(0,160))}</strong><small>${t.updated_at?date(new Date(t.updated_at*1000).toISOString()):'갱신 시각 미제공'} · ${active?'실행 중':t.other_work?'다른 Work에 연결됨':t.connected?'연결됨':'연결 가능'}</small></span>`;
        const button=document.createElement('button');button.type='button';button.textContent=t.connected?'연결된 대화 선택':'이 Work에 연결';button.disabled=t.other_work||active;
        button.onclick=guard(async()=>{if(state.work?.id!==id)return;button.disabled=true;try{if(t.connected){const thread=threads.find(item=>item.runtimeId===t.id);if(thread)await chooseThread(thread);else throw new Error('대화 목록을 갱신하고 다시 선택하세요.');}else{const thread=await api(`/works/${id}/runtime-conversations/import`,{method:'POST',body:{runtime_thread_id:t.id}});if(state.work?.id!==id)return;await selectWork(id,true);await selectThread(thread.id);}}finally{button.disabled=t.other_work||active;}});row.append(button);box.append(row);
      }
      if(!box.children.length)box.innerHTML='<p class="empty">이 Workspace 경로의 기존 Codex 대화가 없습니다.</p>';
      discoveryCursor=data.next_cursor;$('conversation-discover-more').hidden=!discoveryCursor;
    }catch(error){if(state.work?.id===id){$('conversation-discovered').textContent=error.message;$('conversation-discover-more').hidden=true;}}
    finally{$('conversation-discover').disabled=false;$('conversation-discover-more').disabled=false;}
  }
  $('conversation-discover').onclick=guard(()=>discover());$('conversation-discover-more').onclick=guard(()=>discover(true));
  const resourceSelection = () => ({resource_ids:[...$('conversation-resources').querySelectorAll('input[data-resource]:checked')].map(i=>i.dataset.resource),
    exclude_resource_ids:[...$('conversation-resources').querySelectorAll('input[data-resource]:not(:checked)')].map(i=>i.dataset.resource),
    pack_id:$('conversation-pack').value || null,budget:Number($('conversation-budget').value),allow_over_budget:$('conversation-over-budget').checked});
  async function load(work, preserve=false) {
    const epoch=++generation;workId=work;
    if (!preserve) {selected=null;pendingAction='NEW';command=null;$('conversation-over-budget').checked=false;}
    const oldPack=preserve?$('conversation-pack').value:'';
    const prior=new Map([...$('conversation-resources').querySelectorAll('input[data-resource]')].map(i=>[i.dataset.resource,i.checked]));
    const [data,capabilities]=await Promise.all([api(`/works/${work}/conversations`),api('/conversation-capabilities').catch(()=>({discovery:false,resume:false}))]);
    if(epoch!==generation || state.work?.id!==work)return;
    threads=data.threads.filter(t=>t.status!=='EPHEMERAL' && t.relation_type!=='QUERY_FROM').map(enrich);
    if(!preserve){try{selected=JSON.parse(localStorage.getItem('control-center-thread:'+work)||'null');}catch{}$('conversation-search').value='';$('conversation-discovered').replaceChildren();discoveryCursor=null;$('conversation-discover-more').hidden=true;}
    selected=selected?threads.find(t=>(selected.id&&t.id===selected.id)||(selected.legacy_run_id&&t.legacy_run_id===selected.legacy_run_id)||(selected.runtimeId&&t.runtimeId===selected.runtimeId))||null:null;
    if(!preserve&&selected)pendingAction='CONTINUE';
    if(!selected&&pendingAction!=='NEW')pendingAction='NEW';
    $('conversation-discovery').hidden=!capabilities.discovery||!capabilities.resume;
    renderThreads();renderSelected();remember();
    const packSelect=$('conversation-pack'), previous=$('pack-previous');packSelect.innerHTML='<option value="">선택 안 함</option>';previous.innerHTML='<option value="">새 Pack</option>';
    for(const p of data.packs){
      const o=document.createElement('option');o.value=p.id;o.textContent=`${p.name} v${p.version} · ${p.status} · ${p.freshness.state} · ~${p.estimated_size} / ${p.budget}`;
      previous.append(o.cloneNode(true));if(p.status==='REVIEWED')packSelect.append(o);
    }
    packSelect.value=oldPack;
    const rs=await api(`/works/${work}/resources`+(selected?.id?'?thread_id='+encodeURIComponent(selected.id):''));
    if(epoch!==generation || state.work?.id!==work)return;
    $('conversation-resources').replaceChildren();
    for(const r of rs){
      const toggle=wfButton(`기본 포함 ${r.default_include?'해제':'설정'}`,async()=>{await api('/resources/'+r.id,{method:'PATCH',body:{default_include:!r.default_include}});await load(work,true);});
      const label=UI.selectable({title:r.title,value:r.id,selected:preserve&&prior.has(r.id)?prior.get(r.id):pendingAction==='QUERY'?false:r.default_include,
        metadata:[['종류',r.kind],['공개 범위',r.scope],['버전',r.version],['기본 포함',r.default_include?'사용':'미사용']],actions:[toggle]});label.querySelector('input').dataset.resource=r.id;
      $('conversation-resources').append(label);
    }
    if(!rs.length)$('conversation-resources').append(UI.empty('저장된 Resource가 없습니다.','실행 결과에서 결정·지식·메모를 저장해 다음 요청에 사용할 수 있습니다.'));
    $('conversation-queries').replaceChildren();
    for(const q of data.queries){
      const area=UI.detail('임시 질문',{status:UI.status(q.status)});area.classList.add('panel');area.insertAdjacentHTML('beforeend',`<pre>${escape(q.result)}</pre><div class="actions"><button data-show>실행 보기</button><button data-discard data-action="danger">폐기</button><button data-conclusion>현재 작업에 결론 전달</button><button data-promote>자료로 저장</button></div>`);UI.enhance(area);
      area.querySelector('[data-show]').onclick=guard(()=>selectRun(q.run_id));
      area.querySelector('[data-discard]').onclick=guard(async()=>{await api('/queries/'+q.id+'/decision',{method:'POST',body:{action:'DISCARD'}});await load(work,true);});
      area.querySelector('[data-promote]').onclick=()=>openPromotion(q.run_id,q.result,q.id);
      area.querySelector('[data-conclusion]').onclick=guard(async()=>{const summary=window.prompt('메인 대화에 전달할 짧은 결론 (최대 4,000자)');if(!summary)return;const result=await api('/queries/'+q.id+'/decision',{method:'POST',body:{action:'HANDOFF',summary,execution_profile:window.executionSettings.read('')}});await load(work,true);await selectRun(result.result.id);});
      $('conversation-queries').append(area);
    }
    updateMode();
    UI.enhance(panel);
  }
  function updateMode(){
    $('conversation-query-options').hidden=pendingAction!=='QUERY';
    const names={NEW:'새 대화',CONTINUE:'같은 대화 계속',RESUME:'기존 대화 재개',COMPACT:'Runtime 압축 완료 후 같은 대화 계속',QUERY:'새 임시 질문 · 읽기 전용 기본',FORK:'마지막 완료 시점의 정확한 분기',HANDOFF:'검토한 Pack으로 새 대화'};
    $('conversation-mode').textContent=names[pendingAction]+' · 작업 지시 입력 후 실행';
    const busy=selected?.runtimeSync?.active||selected?.runs.some(r=>['CREATED','RUNNING'].includes(r.status)||r.safety_block),canResume=selected?.runtimeId&&selected.runs.some(r=>r.turn_id)&&!busy;
    for(const b of document.querySelectorAll('[data-conversation-action]')){const a=b.dataset.conversationAction;b.classList.toggle('active',a===pendingAction);b.setAttribute('aria-pressed',String(a===pendingAction));b.disabled=a==='NEW'?false:!selected||(['CONTINUE','COMPACT','FORK'].includes(a)&&!canResume)||(['CONTINUE','COMPACT'].includes(a)&&(['CLOSED','SUPERSEDED'].includes(selected.status)||['RUNNING','UNKNOWN'].includes(selected.compact_state)));b.title=b.disabled?'대화를 선택하고 진행 중인 실행이 완료된 뒤 사용할 수 있습니다.':'';}
    $('composer-title').textContent={NEW:'새 요청',CONTINUE:'기존 대화 계속',QUERY:'질문하기',FORK:'분기',COMPACT:'Compact',HANDOFF:'새 대화로 넘기기'}[pendingAction]||'실행';
    $('execution-mode-note').textContent={NEW:'새 대화에서 요청을 실행합니다.',CONTINUE:'선택한 대화의 이력을 이어서 새 실행을 만듭니다.',QUERY:'별도 임시 대화에서 질문합니다. 기본 권한은 읽기 전용입니다.',FORK:'마지막 완료 지점의 대화 이력을 복사하여 분기합니다.',COMPACT:'Runtime 압축 완료를 확인한 뒤 같은 대화를 계속합니다.',HANDOFF:'검토한 Context Pack을 새 대화로 전달합니다.'}[pendingAction]||'';
  }
  for(const button of document.querySelectorAll('[data-conversation-action]'))button.onclick=guard(async()=>{
    pendingAction=button.dataset.conversationAction;state.resume=null;$('resume-label').hidden=true;$('clear-resume').hidden=true;
    if(pendingAction==='NEW')selected=null;
    if(!selected&&pendingAction!=='NEW')throw new Error('이력을 확인할 대화를 먼저 선택하세요.');
    if(pendingAction==='QUERY'){
      for(const checkbox of $('context-list').querySelectorAll('input'))checkbox.checked=false;
      for(const checkbox of $('library-context-list').querySelectorAll('input'))checkbox.checked=false;
      for(const checkbox of $('conversation-resources').querySelectorAll('input'))checkbox.checked=false;
      $('conversation-pack').value='';$('query-write').checked=false;$('query-artifacts').checked=false;
    }
    renderThreads();renderSelected();remember();updateMode();
    if(pendingAction==='HANDOFF' && !$('conversation-pack').value)await openPack();
    window.controlCenter?.tab('execution');$('instruction').focus();
  });
  async function execute(body){
    const context=resourceSelection();
    const payload={...context,action:state.resume?'CONTINUE':pendingAction,instruction:body.instruction,source_ids:body.context_ids,
      artifact_ids:body.artifact_ids,execution_profile:body.execution_profile,include_defaults:pendingAction==='QUERY' || pendingAction==='HANDOFF'?false:true};
    if(state.resume)payload.from_run_id=state.resume;
    else if(selected){if(selected.id)payload.thread_id=selected.id;else payload.from_run_id=selected.legacy_run_id;}
    if(payload.action==='QUERY'){
      payload.write_query=$('query-write').checked;payload.artifact_creation=$('query-artifacts').checked;
      payload.execution_profile={...body.execution_profile,permission:payload.write_query?'workspace-write':'read-only'};
    }
    if(payload.action==='HANDOFF'){
      if(!payload.pack_id)throw new Error('Context Pack을 만들고 내용을 확인하세요');
      const preview=await api('/context-packs/'+payload.pack_id);
      if(!window.confirm(`${preview.name} v${preview.version}\n${JSON.stringify(preview.summary,null,2)}\n${preview.items.map(i=>i.snapshot.name).join('\n')}\n예상 ${preview.estimated_size} / ${preview.budget} · ${preview.freshness.state}\n선택한 내용을 새 대화로 전달할까요?`))return null;
      payload.confirmed=true;payload.supersede_parent=true;
    }
    if(payload.action!=='NEW' && payload.action!=='QUERY' && !payload.thread_id && !payload.from_run_id)throw new Error('대화를 선택하세요');
    const signature=JSON.stringify(payload);if(command?.signature!==signature)command={signature,key:crypto.randomUUID()};
    const run=await api('/works/'+state.work.id+'/conversations',{method:'POST',body:payload,headers:{'Idempotency-Key':command.key}});
    command=null;if(!run.is_query){selected={id:run.conversation_id,title:payload.instruction.slice(0,160)};pendingAction='CONTINUE';remember();}return run;
  }
  async function openPack(){
    draftPack=null;$('pack-preview-text').textContent='';$('pack-preview-readable').replaceChildren();$('pack-confirm').hidden=true;
    const data=await api(`/works/${workId}/context-candidates`+(selected?.id?'?thread_id='+encodeURIComponent(selected.id):''));
    $('pack-candidates-note').textContent=data.note;
    for(const key of ['goal','current','completed','pending','decisions','blockers','next_instruction'])$('pack-'+key).value=data[key] || '';
    $('pack-candidates').replaceChildren();
    const chosen=resourceSelection();
    for(const [kind,items] of [['SOURCE',data.sources],['ARTIFACT',data.artifacts],['RESOURCE',data.resources]]){
      const h=document.createElement('h3');h.textContent={SOURCE:'Workspace 파일',ARTIFACT:'이전 결과물 · Library',RESOURCE:'결정 · 공유 자료'}[kind];$('pack-candidates').append(h);
      for(const item of items){const label=document.createElement('label');label.className='context-item';label.innerHTML=`<input type="checkbox" data-kind="${kind}" value="${escape(item.id)}">${escape(item.name || item.title)}`;label.querySelector('input').checked=kind==='SOURCE'?selectedContext().includes(item.id):kind==='RESOURCE'?chosen.resource_ids.includes(item.id):false;$('pack-candidates').append(label);}
    }
    $('pack-previous').value='';$('pack-dialog').showModal();
  }
  function renderPack(pack){
    const box=$('pack-preview-readable'),detail=UI.detail(pack.name,{status:UI.status(pack.freshness?.state||pack.status)});box.replaceChildren(detail);
    detail.append(UI.metadata([['버전',pack.version],['예상 Token',pack.estimated_size],['자료 예산',pack.budget]]));
    const names={goal:'목표',current:'현재 작업',completed:'완료한 작업',pending:'남은 작업',decisions:'주요 결정',blockers:'Blocker',next_instruction:'다음 지시'};
    detail.append(UI.metadata(Object.entries(pack.summary||{}).filter(([,value])=>value).map(([key,value])=>[names[key]||key,Array.isArray(value)?value.join(', '):value])));
    for(const item of pack.items||[])detail.append(UI.metadata([['선택 자료',item.snapshot.name||item.snapshot.title||'자료'],['종류',item.source_type]],{compact:true}));
    if(pack.freshness&&pack.freshness.state!=='CURRENT')detail.append(UI.warning('원본 자료가 변경되었거나 Pack이 오래되었습니다. 자료를 다시 확인하고 새 버전을 만들어 실행하세요.','Pack 내용 확인 필요'));
    if(pack.estimated_size>pack.budget)detail.append(UI.warning('예상 자료 크기가 설정한 예산을 초과합니다. 자료를 줄이거나 예산 초과 실행을 명시적으로 허용하세요.','자료 예산 초과'));
  }
  async function previewPack(id){if(!id)throw new Error('Pack을 선택하세요.');const pack=await api('/context-packs/'+id);await openPack();$('pack-name').value=pack.name;$('pack-previous').value=pack.id;for(const key of ['goal','current','completed','pending','decisions','blockers','next_instruction']){const value=pack.summary?.[key];$('pack-'+key).value=Array.isArray(value)?value.join('\n'):value||'';}for(const box of $('pack-candidates').querySelectorAll('input'))box.checked=(pack.items||[]).some(item=>item.source_type===box.dataset.kind&&item.source_id===box.value);draftPack=pack;renderPack(pack);$('pack-preview-text').textContent=JSON.stringify(pack,null,2);$('pack-confirm').hidden=pack.status==='REVIEWED';}
  $('pack-view').onclick=guard(()=>previewPack($('conversation-pack').value));
  $('pack-build').onclick=guard(openPack);
  $('pack-preview').onclick=guard(async()=>{
    const body={name:$('pack-name').value,budget:Number($('conversation-budget').value),thread_id:selected?.id || null};
    for(const key of ['goal','current','completed','pending','decisions','blockers','next_instruction'])body[key]=$('pack-'+key).value;
    for(const [kind,key] of [['SOURCE','source_ids'],['ARTIFACT','artifact_ids'],['RESOURCE','resource_ids']])body[key]=[...$('pack-candidates').querySelectorAll(`input[data-kind="${kind}"]:checked`)].map(i=>i.value);
    const old=$('pack-previous').value;
    draftPack=await api(old?'/context-packs/'+old+'/versions':'/works/'+workId+'/context-packs',{method:'POST',body});
    $('pack-preview-text').textContent=JSON.stringify({name:draftPack.name,version:draftPack.version,summary:draftPack.summary,items:draftPack.items.map(i=>i.snapshot),estimate:draftPack.estimated_size,budget:draftPack.budget,warnings:draftPack.warnings},null,2);$('pack-confirm').hidden=false;renderPack(draftPack);
  });
  $('pack-confirm').onclick=guard(async()=>{if(!draftPack)throw new Error('미리보기를 먼저 생성하세요');await api('/context-packs/'+draftPack.id+'/confirm',{method:'POST',body:{confirmed:true}});$('pack-dialog').close();await load(workId,true);$('conversation-pack').value=draftPack.id;window.controlCenter?.selectionSummary();});
  // Editing after preview requires a new reviewed reference bundle.
  $('pack-dialog').addEventListener('input',()=>{draftPack=null;$('pack-confirm').hidden=true;});
  $('pack-dialog-close').onclick=()=>$('pack-dialog').close();
  function openPromotion(runId,text,queryId=null){promoteSource=runId;queryDecision=queryId;$('promotion-title').value='중요한 결론';$('promotion-content').value=text;$('promotion-kind').value='DECISION';$('promotion-scope').value='WORK';$('promotion-default').checked=false;$('promotion-dialog').showModal();}
  $('resource-promote-run').onclick=guard(async()=>{if(!state.run)throw new Error('완료된 Run을 선택하세요');openPromotion(state.run.id,$('final-answer').textContent);});
  $('promotion-save').onclick=guard(async()=>{
    const promotion={title:$('promotion-title').value,content:$('promotion-content').value,kind:$('promotion-kind').value,scope:$('promotion-scope').value,default_include:$('promotion-default').checked};
    await api(queryDecision?'/queries/'+queryDecision+'/decision':'/runs/'+promoteSource+'/promotions',{method:'POST',body:queryDecision?{action:'PROMOTE',promotion}:promotion});$('promotion-dialog').close();await load(workId,true);
  });
  $('promotion-close').onclick=()=>$('promotion-dialog').close();
  for(const [id,status] of [['conversation-archive','ARCHIVED'],['conversation-close','CLOSED']])$(id).onclick=guard(async()=>{if(!selected?.id)throw new Error('대화를 선택하세요');await api('/conversations/'+selected.id,{method:'PATCH',body:{status}});await load(workId,true);});
  $('conversation-compact-reconcile').onclick=guard(async()=>{if(!selected?.id)throw new Error('대화를 선택하세요');await api('/conversations/'+selected.id+'/compact/reconcile',{method:'POST'});await load(workId,true);});
  async function inspect(run){
    const id=run.id,c=await api('/runs/'+id+'/context');if(state.run?.id!==id)return;
    const strategies={CONTINUE_THREAD:'기존 대화 계속',FORK_THREAD:'기존 대화에서 분기',FRESH_CONTEXT:'새 대화 · 선택 자료',CONTEXT_PACK:'검토한 Context Pack',EPHEMERAL_QUERY:'임시 질문'};
    const box=$('context-inspector');box.replaceChildren(UI.metadata([['Work',c.work],['참고 방식',strategies[c.strategy]||c.strategy],['예상 Token',c.budget.estimate??'미제공'],['자료 예산',c.budget.target??'미제공'],...(c.pack_id?[['Context Pack 버전',c.pack_version]]:[])]));
    for(const item of c.inputs)box.append(UI.metadata([['전달 자료',item.name||'자료'],['범위',item.scope||item.source_type||'미제공'],['Context 정책',item.include_mode||'REFERENCE'],['요약',item.summary||'—']],{compact:true}));
    if(c.budget.warnings?.length)box.append(UI.warning('Context 경고가 있습니다. 자료 예산과 선택한 항목을 확인하세요. 상세 경고는 고급 정보에 표시합니다.','전달 자료 확인 필요'));
    if(c.history_note)box.append(UI.help(c.history_note,'대화 참고 방식'));
    const raw=document.createElement('pre');raw.textContent=JSON.stringify(c,null,2);box.append(UI.advanced('고급 정보 · Context 상세',raw));
  }
  async function selectThread(id){await load(state.work.id,true);const thread=threads.find(t=>t.id===id||t.legacy_run_id===id);if(!thread)throw new Error('대화 목록에서 다시 선택하세요.');await chooseThread(thread);}
  async function syncRun(run){
    if(run.is_query||run.task_run_id||!run.thread_id)return;
    const thread=threads.find(t=>(run.conversation_id&&t.id===run.conversation_id)||t.runtimeId===run.thread_id);
    if(!thread)return;
    if(selected&&threadKey(selected)===threadKey(thread))return;
    selected=thread;pendingAction='CONTINUE';remember();renderThreads();renderSelected();updateMode();
  }
  function runUpdated(detail){
    if(state.work?.id!==detail.run.work_id)return;
    const data=state.workDetail;if(data){const index=data.runs.findIndex(r=>r.id===detail.run.id);if(index>=0)data.runs[index]=detail.run;if(!data.requests.some(r=>r.id===detail.request.id))data.requests.push(detail.request);}
    threads=threads.map(enrich);if(selected)selected=threads.find(t=>threadKey(t)===threadKey(selected))||selected;
    renderThreads();renderSelected();updateMode();
  }
  function liveAnswer(text){const box=$('conversation-answer-'+state.run?.id);if(box)box.textContent=text;}
  $('clear-resume').addEventListener('click',()=>{selected=null;pendingAction='NEW';remember();renderThreads();renderSelected();updateMode();});
  $('resume').addEventListener('click',guard(async()=>{await syncRun(state.run);pendingAction='CONTINUE';updateMode();}));
  return {load,execute,inspect,previewPack,selectThread,syncRun,runUpdated,liveAnswer,queueContext:()=>({...resourceSelection(),context_thread_id:selected?.id||null})};
})();
