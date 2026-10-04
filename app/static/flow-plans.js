'use strict';
window.flowPlans = (() => {
  let workId = null, selected = null, editing = null, timer = null, catalog = null, allPlans = [];
  const title = plan => plan.installed_workflow?.name || plan.plan?.workflow?.name || plan.title || plan.goal.slice(0,72);
  function clearTimer() { if(timer) clearTimeout(timer); timer=null; }
  function schedulePoll() { clearTimer(); if(['RESEARCHING','GENERATING'].includes(selected?.status) && state.work?.id===workId) timer=setTimeout(()=>open(selected.id).catch(e=>notice(e.message)),2500); }
  function renderProgress(plan){
    const phases=[['자료 탐색','Workspace · 필요 시 웹'],['조사 결과·출처 확인','검증 · Work 자료 적재'],['업무계획 초안','자료 ID로 생성'],['사용자 편집·승인','Workflow · 일정 연결']];
    const current=plan.status==='RESEARCHING'?0:['NO_SOURCES','REVIEW_LIMIT'].includes(plan.status)?1:plan.status==='GENERATING'?2:plan.status==='APPROVED'?4:3;
    $('flow-plan-progress').replaceChildren(...phases.map(([name,detail],index)=>{const li=document.createElement('li');li.dataset.state=index<current?'done':index===current?'current':'pending';li.innerHTML=`<strong>${escape(name)}</strong><span>${escape(detail)}</span>`;return li;}));
  }
  function renderEvidence(plan){
    const root=$('flow-plan-evidence-list');root.replaceChildren();
    const items=plan.evidence||[];
    for(const [index,item] of items.entries()){
      const card=document.createElement('article');card.className='flow-plan-evidence-card';
      const heading=document.createElement('div');heading.className='panel-heading';heading.innerHTML=`<h4>${escape(item.title)}</h4>${UI.statusHTML('CURRENT','출처 확인됨')}`;card.append(heading);
      const locator=item.url||item.path||'';
      card.append(UI.metadata([['종류',item.media_type|| (item.kind==='WEB'?'웹 자료':'Workspace 파일')],['출처',locator],['확인 시각',date(item.retrieved_at)],['원문 위치',item.location||'—'],['자료 ID',item.material_id]]));
      if(item.url){const link=document.createElement('a');link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='원문 열기 ↗';card.append(link);}
      const quote=document.createElement('blockquote');quote.textContent=item.excerpt;card.append(quote);
      const summary=document.createElement('p');summary.textContent=item.summary;card.append(summary);
      const rationale=document.createElement('p');rationale.className='ui-help';rationale.textContent='근거 · '+item.rationale;card.append(rationale);
      if(plan.status!=='APPROVED'&&!['RESEARCHING','GENERATING'].includes(plan.status)){
        const details=document.createElement('details');details.innerHTML='<summary>자료 설명 수정</summary>';
        const titleInput=document.createElement('input');titleInput.value=item.title;const summaryInput=document.createElement('textarea');summaryInput.rows=3;summaryInput.value=item.summary;
        const reasonInput=document.createElement('textarea');reasonInput.rows=2;reasonInput.value=item.rationale;
        for(const [label,control] of [['제목',titleInput],['핵심 내용',summaryInput],['근거',reasonInput]]){const field=document.createElement('label');field.textContent=label;field.append(control);details.append(field);}
        details.append(wfButton('자료 수정 저장',async()=>{const changed=await api(`/flow-plans/${plan.id}/evidence/${index}`,{method:'PATCH',body:{expected_revision:plan.revision,title:titleInput.value,summary:summaryInput.value,rationale:reasonInput.value}});render(changed);await loadWork(workId);notice('자료 설명을 저장했습니다. 계획을 다시 생성해 반영하세요.');},false,'primary'));
        card.append(details);
      }
      root.append(card);
    }
    if(!items.length){
      if(!plan.research_run_id)root.append(UI.help(`직접 선택한 자료 ${Object.values(plan.material_ids||{}).flat().length}개를 사용합니다.`, '자료 입력'));
      else root.append(UI.empty(plan.status==='RESEARCHING'?'Workspace와 출처를 조사하고 있습니다.':'확인된 자료가 없습니다.',plan.status==='NO_SOURCES'?'재검색하거나 자료 탭에서 직접 선택하세요.':'출처 문구가 실제 자료와 일치해야 적재됩니다.'));
    }
    $('flow-plan-research-mode').textContent=plan.research_run_id?(plan.research_web?'Workspace → 웹 검색 가능':'Workspace 조사 · 웹 검색 미지원/비활성'):'선택한 자료 사용';
    const pending=plan.research_candidates||[],report=plan.research_budget||{};
    $('flow-plan-candidates').hidden=!pending.length;
    $('flow-plan-candidate-list').replaceChildren(...pending.map(candidate=>{
      const card=UI.detail(candidate.title,{status:UI.status('PENDING','미확인')});
      card.append(UI.metadata([['URL/경로',candidate.url||candidate.path||'—'],['관련성',Math.round((candidate.relevance||0)*100)+'%']]));
      if(candidate.snippet)card.append(UI.help(candidate.snippet));
      return card;
    }));
    $('flow-plan-budget').hidden=plan.status!=='REVIEW_LIMIT';
    $('flow-plan-budget').textContent=plan.status==='REVIEW_LIMIT'?
      `${report.reason||'확인하지 않은 후보가 있습니다.'} 확인된 자료 ${items.length}개 · 미확인 후보 ${pending.length}개 · 이번 조사 파일 ${report.downloaded_files||0}개 / ${Math.round((report.downloaded_bytes||0)/1048576*10)/10}MB · 한도 ${report.limits?.files||3}개 / ${Math.round((report.limits?.total_bytes||15728640)/1048576)}MB`:'';
  }
  function taskCard(task,index,tasks){
    const row=document.createElement('article');row.className='flow-plan-task';row.dataset.index=index;
    const deps=tasks.filter(x=>x.id!==task.id).map(x=>`<label><input type="checkbox" data-dep="${escape(x.id)}" ${task.depends_on.includes(x.id)?'checked':''}>${escape(x.name)}</label>`).join('');
    const profile=task.execution_profile||{};
    const chosenModel=task.model||profile.model||'',chosenReasoning=task.reasoning||profile.reasoning||'';
    const modelInfo=state.models.find(m=>m.id===chosenModel)||state.models.find(m=>m.id===state.resolvedProfile?.model)||state.models.find(m=>m.default);
    const reasonings=[...new Set([...(modelInfo?.reasoning||[]),chosenReasoning].filter(Boolean))];
    const models=state.models.map(m=>`<option value="${escape(m.id)}" ${chosenModel===m.id?'selected':''}>${escape(m.id)}</option>`).join('');
    row.innerHTML=`<div class="panel-heading"><h3>작업 ${index+1}</h3><button type="button" data-remove-task>삭제</button></div>
      <label>이름<input data-field="name" value="${escape(task.name)}"></label>
      <label>실행 지시<textarea data-field="instruction" rows="5">${escape(task.instruction)}</textarea></label>
      <p class="ui-help">프로젝트 읽기·탐색 범위는 Workflow 탭의 파일시스템 탐색기에서 확인하고 수정합니다.</p>
      <div class="flow-plan-task-options"><label>모델<select data-field="model"><option value="">상속</option>${models}</select></label>
      <label>Reasoning<select data-field="reasoning"><option value="">상속</option>${reasonings.map(x=>`<option value="${escape(x)}" ${chosenReasoning===x?'selected':''}>${escape(x)}</option>`).join('')}</select></label>
      <label>권한<select data-field="permission"><option value="">상속</option><option value="read-only" ${profile.permission==='read-only'?'selected':''}>읽기 전용</option><option value="workspace-write" ${profile.permission==='workspace-write'?'selected':''}>Workspace 쓰기</option></select></label>
      <label>속도<select data-field="speed"><option value="">상속</option><option value="default" ${profile.speed==='default'?'selected':''}>Standard</option>${modelInfo?.service_tiers?.filter(t=>t.id!=='default').map(t=>`<option value="${escape(t.id)}" ${profile.speed===t.id?'selected':''}>${escape(t.name)}</option>`).join('')||''}</select></label>
      <label>검토 방식<select data-field="review_policy">${[['AUTO','자동'],['REVIEW_AFTER','실행 후 검토'],['APPROVAL_REQUIRED','다음 작업 전 승인']].map(([v,l])=>`<option value="${v}" ${task.review_policy===v?'selected':''}>${l}</option>`).join('')}</select></label>
      <label>Workspace<select data-field="workspace_mode"><option value="ARTIFACT_ONLY" ${task.workspace_mode==='ARTIFACT_ONLY'?'selected':''}>결과물만</option><option value="GIT_WORKTREE" ${task.workspace_mode==='GIT_WORKTREE'?'selected':''}>Git 작업 공간</option></select></label></div>
      <div class="flow-plan-deps"><strong>선행 작업 · 모두 완료 후 실행</strong><div>${deps||'<span class="ui-help">없음 · 바로 실행 가능</span>'}</div></div>`;
    row.querySelector('[data-remove-task]').onclick=()=>{readEditor();editing.workflow.tasks.splice(index,1);for(const t of editing.workflow.tasks)t.depends_on=t.depends_on.filter(id=>id!==task.id);renderEditor();};
    row.querySelector('[data-field="model"]').onchange=()=>{readEditor();renderEditor();};
    return row;
  }
  function renderEditor(){
    if(!editing)return;
    $('flow-plan-edit-summary').value=editing.summary||'';
    $('flow-plan-edit-name').value=editing.workflow?.name||'';
    $('flow-plan-edit-description').value=editing.workflow?.description||'';
    $('flow-plan-edit-schedule-kind').value=editing.schedule?.kind||'NONE';
    $('flow-plan-edit-start').value=editing.schedule?.start_at?new Date(new Date(editing.schedule.start_at).getTime()-new Date(editing.schedule.start_at).getTimezoneOffset()*60000).toISOString().slice(0,16):'';
    $('flow-plan-edit-interval').value=editing.schedule?.interval_minutes||60;
    $('flow-plan-task-editor').replaceChildren(...(editing.workflow?.tasks||[]).map(taskCard));
    $('flow-plan-json').value=JSON.stringify(editing,null,2);
    renderUnresolved();
  }
  function readEditor(){
    if(!editing)return;
    editing.summary=$('flow-plan-edit-summary').value.trim();
    editing.workflow.name=$('flow-plan-edit-name').value.trim();
    editing.workflow.description=$('flow-plan-edit-description').value;
    for(const row of $('flow-plan-task-editor').querySelectorAll('[data-index]')){
      const task=editing.workflow.tasks[Number(row.dataset.index)];
      for(const field of ['name','instruction','review_policy','workspace_mode'])task[field]=row.querySelector(`[data-field="${field}"]`).value;
      task.model=row.querySelector('[data-field="model"]').value||null;
      task.reasoning=row.querySelector('[data-field="reasoning"]').value||null;
      const permission=row.querySelector('[data-field="permission"]').value||null;
      const speed=row.querySelector('[data-field="speed"]').value||null;
      task.execution_profile=task.model||task.reasoning||permission||speed?{model:task.model,reasoning:task.reasoning,permission,speed}:null;
      task.depends_on=[...row.querySelectorAll('[data-dep]:checked')].map(x=>x.dataset.dep);
      task.context_rule=task.context_rule||{inherit_workflow_context:true,source_ids:[],artifact_ids:[]};
    }
    const kind=$('flow-plan-edit-schedule-kind').value;
    if(kind==='NONE')editing.schedule=null;
    else {
      const when=$('flow-plan-edit-start').value;
      editing.schedule={kind,start_at:when?new Date(when).toISOString():'',
        interval_minutes:kind==='RECURRING'?Number($('flow-plan-edit-interval').value):null,
        enabled:true,misfire_policy:editing.schedule?.misfire_policy||'FIRE_ONCE',
        grace_seconds:editing.schedule?.grace_seconds??300,
        source_ids:editing.schedule?.source_ids||[],artifact_ids:editing.schedule?.artifact_ids||[]};
    }
    return editing;
  }
  function renderUnresolved(){
    const root=$('flow-plan-unresolved'),pending=editing?.workflow?.unresolved_bindings||[];
    root.hidden=!pending.length;root.replaceChildren();
    if(!pending.length)return;
    const heading=document.createElement('strong');heading.textContent=`미해결 연결 ${pending.length}건 · Workflow 탭의 해당 작업에서 해결하거나 제외하세요.`;root.append(heading);
    for(const binding of pending){const p=document.createElement('p');p.textContent=binding.title||binding.name||binding.reference_path||binding.reason||'참고 자료';root.append(p);}
  }
  function renderList(plans){
    const root=$('flow-plan-list');root.replaceChildren();
    const search=$('flow-plan-search').value.trim().toLowerCase();
    plans=search?plans.filter(p=>(p.title+' '+p.goal).toLowerCase().includes(search)):plans;
    for(const plan of plans){
      const row=UI.detail(title(plan),{status:UI.status(plan.status)});
      row.classList.add('flow-plan-list-row');
      row.append(UI.metadata([['생성',date(plan.created_at)],['작업',plan.task_count?`${plan.task_count}개`:'준비 중'],['예약',plan.schedule_at?date(plan.schedule_at):'없음']]));
      row.append(wfButton('계획 열기',()=>open(plan.id),false,selected?.id===plan.id?'primary':'secondary'));
      root.append(row);
    }
    if(!plans.length)root.append(UI.empty(search?'검색 결과가 없습니다.':'저장된 업무 플로우 계획이 없습니다.',search?'다른 검색어를 입력하세요.':'목표를 입력해 첫 초안을 만드세요.'));
  }
  async function loadWork(id){
    if(!id)return;
    if(workId!==id){selected=null;editing=null;clearTimer();$('flow-plan-detail').hidden=true;}
    workId=id;
    const plans=await api(`/works/${id}/flow-plans`);
    if(state.work?.id!==id)return;
    allPlans=plans;renderList(allPlans);
    $('flow-plan-material-summary').textContent=`현재 선택 자료 ${selectedContext().length}개 · 결과물 ${selectedLibrary().length}개`;
    if(selected){const found=plans.find(p=>p.id===selected.id);if(!found){selected=null;$('flow-plan-detail').hidden=true;}else if(found.status==='GENERATING'&&selected.status==='GENERATING')schedulePoll();}
  }
  function render(plan){
    selected=plan;
    $('flow-plan-detail').hidden=false;
    $('flow-plan-title').textContent=title(plan);
    $('flow-plan-status').replaceChildren(UI.status(plan.status));
    renderProgress(plan);renderEvidence(plan);
    $('flow-plan-summary').textContent=plan.plan?.summary||plan.goal;
    $('flow-plan-error').hidden=!plan.error;
    $('flow-plan-error').textContent=plan.error||'';
    $('flow-plan-graph').replaceChildren();
    const tasks=plan.installed_workflow?.tasks||plan.plan?.workflow?.tasks||[];
    $('flow-plan-graph').hidden=!tasks.length;
    if(tasks.length)wfDiagram($('flow-plan-graph'),tasks);
    const sched=plan.installed_schedule||plan.plan?.schedule;
    $('flow-plan-schedule-summary').replaceChildren(UI.metadata([['작업',tasks.length?`${tasks.length}개`:'초안 생성 중'],['예약',sched?`${sched.kind==='RECURRING'?'반복':'한 번'} · ${date(sched.next_fire_at||sched.start_at)}`:'없음'],['상태',plan.status==='APPROVED'?'시스템 연결 완료':'승인 전']]));
    $('flow-plan-schedule-summary').hidden=!plan.plan;
    $('flow-plan-approve').hidden=true;
    $('flow-plan-open-workflow').hidden=!(plan.status==='DRAFT'&&plan.plan)&&!plan.workflow_definition_id;
    $('flow-plan-open-workflow').textContent=plan.workflow_definition_id?'발행된 Workflow 보기':'Workflow 탭에서 초안 검토·편집';
    $('flow-plan-workflow-help').hidden=plan.status!=='DRAFT'||!plan.plan;
    $('flow-plan-open-schedule').hidden=!plan.schedule_id;
    $('flow-plan-open-run').hidden=!plan.generation_run_id;
    $('flow-plan-open-research-run').hidden=!plan.research_run_id;
    $('flow-plan-retry-research').hidden=['RESEARCHING','GENERATING','APPROVED'].includes(plan.status);
    $('flow-plan-select-materials').hidden=!['NO_SOURCES','FAILED','REVIEW_LIMIT'].includes(plan.status);
    $('flow-plan-continue-research').hidden=plan.status!=='REVIEW_LIMIT'||!plan.evidence?.length;
    $('flow-plan-extend-research').hidden=plan.status!=='REVIEW_LIMIT'||plan.research_budget_level>=3;
    $('flow-plan-regenerate').hidden=!plan.evidence?.length||['RESEARCHING','GENERATING','APPROVED','REVIEW_LIMIT'].includes(plan.status);
    $('flow-plan-draft-heading').hidden=['RESEARCHING','NO_SOURCES','REVIEW_LIMIT'].includes(plan.status);
    $('flow-plan-editor').hidden=['DRAFT','APPROVED','RESEARCHING','GENERATING','NO_SOURCES','NEEDS_REPLAN','REVIEW_LIMIT'].includes(plan.status);
    editing=plan.plan?structuredClone(plan.plan):null;
    if(editing)renderEditor();
    else {$('flow-plan-json').value=plan.generation_run?.final_text||'';$('flow-plan-unresolved').hidden=true;}
    if(plan.status==='INVALID'||plan.status==='FAILED')$('flow-plan-editor').open=true;
    schedulePoll();
  }
  async function open(id){const before=selected?.id===id?selected.status:null;const plan=await api(`/flow-plans/${id}`);if(state.work?.id!==plan.work_id)return;render(plan);allPlans=await api(`/works/${plan.work_id}/flow-plans`);renderList(allPlans);if(before==='RESEARCHING'&&plan.status==='GENERATING')await selectWork(plan.work_id,true);}
  async function save(){
    if(!selected)return;
    let plan;
    if(editing)plan=readEditor();
    else {try{plan=JSON.parse($('flow-plan-json').value);}catch(e){throw new Error('계획 JSON을 확인하세요: '+e.message);}}
    const result=await api(`/flow-plans/${selected.id}`,{method:'PUT',body:{expected_revision:selected.revision,plan}});
    render(result);await loadWork(workId);notice('계획 초안을 저장했습니다.');
  }
  async function approve(){
    if(!selected?.plan)return;
    if($('flow-plan-editor').open)await save();
    const result=await api(`/flow-plans/${selected.id}/approve`,{method:'POST',body:{expected_revision:selected.revision}});
    render(result);await window.workflows.loadWork(workId,true);await window.workflowOperations.loadWork(workId);await loadWork(workId);notice('승인한 계획을 Workflow와 일정에 연결했습니다.');
  }
  async function showCatalog(){
    catalog=await api('/flow-plans/catalog');$('flow-plan-catalog-preview').textContent=JSON.stringify(catalog,null,2);
  }
  $('flow-plan-generate').onclick=async()=>{try{
    const goal=$('flow-plan-goal').value.trim();if(goal.length<10)throw new Error('목표를 10자 이상 작성하세요.');
    $('flow-plan-generate').disabled=true;
    const plan=await api(`/works/${state.work.id}/flow-plans`,{method:'POST',body:{goal,source_ids:selectedContext(),artifact_ids:selectedLibrary(),resource_ids:window.conversations?.queueContext?.().resource_ids||[]}});
    await loadWork(state.work.id);render(plan);$('flow-plan-goal').value='';
  }catch(e){notice(e.message);}finally{$('flow-plan-generate').disabled=false;}};
  $('flow-plan-refresh').onclick=()=>Promise.resolve(selected?open(selected.id):loadWork(state.work.id)).catch(e=>notice(e.message));
  $('flow-plan-search').oninput=()=>renderList(allPlans);
  $('flow-plan-save').onclick=()=>save().catch(e=>notice(e.message));
  $('flow-plan-approve').onclick=()=>approve().catch(e=>notice(e.message));
  $('flow-plan-add-task').onclick=()=>{if(!editing)return;readEditor();const id='task_'+crypto.randomUUID().replaceAll('-','').slice(0,12),linked=!!state.work?.linked_workspace_path;editing.workflow.tasks.push({id,name:'새 작업',instruction:'수행할 작업을 구체적으로 작성하세요.',runtime:'CODEX',model:null,reasoning:null,execution_profile:null,review_policy:'AUTO',context_rule:{inherit_workflow_context:true,source_ids:[],artifact_ids:[],path_patterns:[],read_paths:linked?['.']:[],search_paths:linked?['.']:[]},input_rule:[],output_rule:[],workspace_mode:'ARTIFACT_ONLY',display_order:editing.workflow.tasks.length,depends_on:[]});renderEditor();};
  $('flow-plan-apply-json').onclick=()=>{try{editing=JSON.parse($('flow-plan-json').value);renderEditor();notice('JSON을 편집 양식에 적용했습니다. 저장을 눌러 검증하세요.');}catch(e){notice(e.message);}};
  $('flow-plan-open-workflow').onclick=async()=>{try{if(!selected)return;window.controlCenter.tab('workflow');if(selected.workflow_definition_id)await wfSelectDefinition(selected.workflow_definition_id);else await window.workflows.openDraft(selected.id);}catch(e){notice(e.message);}};
  $('flow-plan-open-schedule').onclick=async()=>{if(!selected?.schedule_id)return;window.controlCenter.tab('schedule');await window.workflowOperations.loadWork(workId);await window.workflowOperations.openSchedule(selected.schedule_id);};
  $('flow-plan-open-run').onclick=async()=>{if(!selected?.generation_run_id)return;window.controlCenter.tab('execution');await selectRun(selected.generation_run_id);};
  $('flow-plan-catalog-download').onclick=async()=>{try{if(!catalog)await showCatalog();const blob=new Blob([JSON.stringify(catalog,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`control-center-api-contract-${catalog.version}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){notice(e.message);}};
  $('flow-plan-retry-research').onclick=async()=>{try{const plan=await api(`/flow-plans/${selected.id}/retry-research`,{method:'POST'});render(plan);await loadWork(workId);}catch(e){notice(e.message);}};
  $('flow-plan-regenerate').onclick=async()=>{try{const plan=await api(`/flow-plans/${selected.id}/regenerate`,{method:'POST'});render(plan);await loadWork(workId);}catch(e){notice(e.message);}};
  $('flow-plan-continue-research').onclick=async()=>{try{const plan=await api(`/flow-plans/${selected.id}/continue-research`,{method:'POST'});render(plan);await loadWork(workId);}catch(e){notice(e.message);}};
  $('flow-plan-extend-research').onclick=async()=>{try{const plan=await api(`/flow-plans/${selected.id}/extend-research`,{method:'POST'});render(plan);await loadWork(workId);}catch(e){notice(e.message);}};
  $('flow-plan-select-materials').onclick=()=>{$('flow-plan-goal').value=selected.goal;window.controlCenter.tab('materials');notice('자료를 선택한 뒤 업무 플로우 탭에서 목표를 다시 실행하세요.');};
  $('flow-plan-open-research-run').onclick=async()=>{if(!selected?.research_run_id)return;window.controlCenter.tab('execution');await selectRun(selected.research_run_id);};
  $('flow-plan-catalog-preview').textContent='열면 현재 서버의 API 계약을 가져옵니다.';
  $('flow-plan-catalog-preview').closest('details').addEventListener('toggle',e=>{if(e.target.open)showCatalog().catch(err=>notice(err.message));});
  return {loadWork,open};
})();
