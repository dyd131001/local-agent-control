'use strict';
window.requestQueue = (() => {
  let workId=null, jobs=[], generation=0, command=null, selectedRun=null, lastCondition='NOW', loading=false;
  const pending=new Set(['PENDING','BLOCKED','QUEUED','RUNNING']);
  const conditions={NOW:'지금 실행',AT_TIME:'특정 시각',AFTER_RUN_COMPLETED:'Run 종료 후 · 성공 / 실패 / 취소 포함',AFTER_RUN_SUCCEEDED:'Run 성공 후'};
  const statuses={PENDING:'조건 대기',BLOCKED:'BLOCKED · 실행 보류',QUEUED:'실행 대기',RUNNING:'진행 중',COMPLETED:'완료',FAILED:'실패',CANCELLED:'취소'};
  const guard=fn=>async()=>{try{notice('');await fn();}catch(e){notice(e.message);}};
  function timing(){
    const condition=$('request-condition').value,after=condition.startsWith('AFTER_RUN_');
    $('request-time-field').hidden=condition!=='AT_TIME';$('request-predecessor-field').hidden=!after;
    $('request-due-at').required=condition==='AT_TIME';$('request-predecessor').required=after;
    $('request-timing-help').hidden=condition==='NOW';$('execute').textContent=condition==='NOW'?'작업 실행':condition==='AT_TIME'?'요청 예약':'후속 Queue에 등록';
    if(condition==='AT_TIME'&&!$('request-due-at').value){const future=new Date(Date.now()+60*60000);$('request-due-at').value=new Date(future.getTime()-future.getTimezoneOffset()*60000).toISOString().slice(0,16);}
    if(after&&lastCondition!==condition)predecessors(true);
    lastCondition=condition;
  }
  function predecessors(useCurrent=false){
    const select=$('request-predecessor'),old=select.value;
    if(!useCurrent&&document.activeElement===select)return;
    const runs=(state.workDetail?.runs||[]).filter(r=>!r.is_query&&!['reference','import'].includes(r.operation));
    const current=state.run&&runs.some(r=>r.id===state.run.id)?state.run.id:null;
    const active=runs.find(r=>['CREATED','RUNNING'].includes(r.status))?.id;
    const chosen=useCurrent?current||old||active:old||current||active;
    wfOptions(select,[['','선행 Run 선택'],...runs.map(r=>[r.id,`${state.workDetail.requests.find(q=>q.id===r.request_id)?.instruction.slice(0,70)||'실행'} · ${window.controlCenter?.status(r.status)||r.status} · ${date(r.created_at)}`])],chosen||'');
    if(select.selectedIndex<0)select.value='';
  }
  function runSelected(run){if(state.work?.id!==run.work_id)return;if(selectedRun!==run.id){selectedRun=run.id;predecessors(true);}}
  function row(job,index=null){
    const article=UI.detail((index===null?'':(index+1)+'. ')+job.instruction.slice(0,120),{status:UI.status(job.status,statuses[job.status]||job.status)});article.classList.add('queue-item');article.dataset.queueId=job.id;article.dataset.status=job.status;
    article.append(UI.metadata([['실행 조건',conditions[job.condition]],['예정 시각',job.due_at?date(job.due_at):job.condition==='NOW'?'실행 대기열 순서에 따라':job.triggered_at?date(job.triggered_at):'조건 충족 시'],...(job.predecessor?[['선행 요청',job.predecessor.instruction],['선행 상태',UI.status(job.predecessor.status)]]:[])]));
    if(job.blocked_reason)article.append(UI.warning(job.blocked_reason==='PREDECESSOR_NOT_SUCCEEDED'?'선행 Run이 성공하지 않아 보류되었습니다. 이 요청은 유지되며 취소하거나 지금 실행할 수 있습니다.':job.blocked_reason,'자동 실행이 보류되었습니다.'));
    const detail=document.createElement('details');detail.className='queue-snapshot ui-disclosure';detail.innerHTML=`<summary>요청 · 저장된 자료와 설정</summary><span class="ui-field-label">요청 원문</span><p class="request-content">${escape(job.instruction)}</p>${UI.metadataHTML([['모델',job.execution_profile.model],['Reasoning',job.execution_profile.reasoning],['Permission',job.execution_profile.permission],['Speed',job.execution_profile.speed]])}<span class="ui-field-label">등록 당시 자료</span><ul class="ui-snapshot-list">${(job.context_config?.snapshots||[]).map(s=>`<li><strong>${escape(s.name)}</strong><span>${escape(s.source_type)} · ${escape(s.include_mode||'REFERENCE')}</span></li>`).join('')}</ul>`;
    if(!job.context_config?.snapshots?.length)detail.append(UI.help('등록 당시 선택한 자료가 없습니다. 요청 원문과 실행 설정으로 실행합니다.','자료 선택'));article.append(detail);
    const actions=document.createElement('div');actions.className='actions';
    if(['PENDING','BLOCKED'].includes(job.queue_status)){
      actions.append(wfButton('지금 실행',()=>update(job,'execute'),false,job.queue_status==='BLOCKED'?'primary':'secondary'),wfButton('취소',()=>update(job,'cancel'),false,'danger'));
    }else if(job.run_id){
      actions.append(wfButton('실행 보기',()=>selectRun(job.run_id)));
      if(['QUEUED','RUNNING'].includes(job.status))actions.append(wfButton('취소',async()=>{await api('/runs/'+job.run_id+'/cancel',{method:'POST'});await refresh();},false,'danger'));
    }
    article.append(actions);return article;
  }
  function render(){
    const box=$('request-queue-list'),history=$('request-queue-history-list');
    const opened=new Set([...box.querySelectorAll('.queue-item'),...history.querySelectorAll('.queue-item')].filter(item=>item.querySelector('.queue-snapshot')?.open).map(item=>item.dataset.queueId));
    box.replaceChildren();history.replaceChildren();
    const active=jobs.filter(job=>pending.has(job.status));active.forEach((job,index)=>box.append(row(job,index)));
    for(const job of jobs.filter(job=>!pending.has(job.status)))history.append(row(job));
    for(const item of [...box.children,...history.children])if(opened.has(item.dataset.queueId))item.querySelector('.queue-snapshot').open=true;
    if(!active.length)box.append(UI.help('대기 중인 후속 요청이 없습니다. 요청 입력란에서 실행 시점을 선택하여 등록하세요.','Queue'));
    $('request-queue-history').hidden=!history.children.length;
    $('request-queue-history').querySelector('summary').textContent=`완료 · 취소 이력 · ${history.children.length}개`;
    $('request-queue-panel').hidden=!jobs.length;
    $('request-queue-summary').textContent=active.length?`후속 작업 ${active.length}개`:`후속 작업 없음 · 이력 ${history.children.length}개`;
    const blocked=active.filter(job=>job.status==='BLOCKED').length;
    $('request-queue-blocked-summary').hidden=!blocked;$('request-queue-blocked-summary').textContent=`보류 ${blocked}개`;
  }
  function accept(id,data){if(state.work?.id!==id)return;workId=id;jobs=data;render();predecessors();}
  async function load(id,reset=false){
    const epoch=++generation;
    if(reset||workId!==id){workId=id;jobs=[];command=null;selectedRun=null;$('request-condition').value='NOW';$('request-due-at').value='';$('request-predecessor').value='';timing();}
    const data=await api('/works/'+encodeURIComponent(id)+'/request-queue');
    if(epoch!==generation||state.work?.id!==id)return;accept(id,data);
  }
  async function refresh(){const id=state.work?.id;if(!id)return;await window.workflowOperations.loadWork(id);await dashboard();}
  async function update(job,action){
    const result=await api('/request-queue/'+job.id+'/'+action,{method:'POST'});
    await refresh();if(action==='execute'&&state.work?.id===job.work_id){await selectWork(job.work_id,true);await selectRun(result.run_id);}
  }
  async function register(body){
    const id=state.work.id,condition=$('request-condition').value;
    const payload={...body,...(window.conversations?.queueContext()||{}),condition};
    if(condition==='AT_TIME'){
      if(!$('request-due-at').value)throw new Error('예정 시각을 선택하세요.');
      payload.due_at=new Date($('request-due-at').value).toISOString();
    }
    if(condition.startsWith('AFTER_RUN_')){
      payload.predecessor_run_id=$('request-predecessor').value;
      if(!payload.predecessor_run_id)throw new Error('선행 Run을 선택하세요.');
    }
    const signature=JSON.stringify([id,payload]);if(command?.signature!==signature)command={signature,key:crypto.randomUUID()};
    const job=await api('/works/'+id+'/request-queue',{method:'POST',body:payload,headers:{'Idempotency-Key':command.key}});
    command=null;if(state.work?.id!==id)return job;
    await selectWork(id,true);await dashboard();notice('요청과 선택한 자료 · Resource · 실행 설정을 저장했습니다. 조건이 충족되면 자동 실행합니다.');
    $('request-queue-panel').scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    return job;
  }
  function renderSchedules(id,schedules,delays,queued){
    if(state.work?.id!==id)return;
    if($('schedule-view-summary'))$('schedule-view-summary').textContent=`일반 · 후속 요청 ${queued.filter(job=>pending.has(job.status)).length}개 · Workflow 예약 ${schedules.filter(job=>job.enabled).length}개 · 이어하기 ${delays.filter(job=>job.status==='PENDING').length}개`;
    const box=$('unified-schedule-list'),opened=new Set([...box.querySelectorAll('.queue-item')].filter(item=>item.querySelector('.queue-snapshot')?.open).map(item=>item.dataset.queueId));box.replaceChildren();
    const entries=[...queued.map(job=>({kind:'REQUEST',at:job.due_at||job.created_at,job})),
      ...schedules.map(job=>({kind:'WORKFLOW',at:job.next_fire_at||job.created_at,job})),
      ...delays.map(job=>({kind:'DELAY',at:job.due_at,job}))].sort((a,b)=>(a.at||'').localeCompare(b.at||''));
    for(const entry of entries){
      const {kind,job}=entry;
      if(kind==='REQUEST'){
        const item=row(job);if(opened.has(job.id))item.querySelector('.queue-snapshot').open=true;const label=document.createElement('span');label.className='schedule-type';label.textContent=job.condition.startsWith('AFTER_RUN_')?'후속 Run':'일반 Request';item.prepend(label);box.append(item);continue;
      }
      const name=kind==='WORKFLOW'?wfState.definitions.find(d=>d.id===job.workflow_definition_id)?.name||'Workflow':'Checkpoint 이어하기';
      const item=UI.detail(name,{status:kind==='WORKFLOW'?UI.status(job.enabled?'ACTIVE':'DISABLED',job.enabled?'예약 활성':'예약 비활성'):UI.status(job.status)});item.classList.add('queue-item');
      const type=document.createElement('span');type.className='schedule-type';type.textContent=kind==='WORKFLOW'?'Workflow 예약':'Delayed Resume';item.prepend(type);
      item.append(UI.metadata([['예정 시각',date(entry.at)],['실행 조건',kind==='WORKFLOW'?job.kind==='RECURRING'?`${job.interval_seconds/60}분마다 반복`:'한 번 실행':'Checkpoint에서 새 실행']]));
      if(job.error)item.append(UI.warning(job.error,'예약 처리 오류'));
      const actions=document.createElement('div');actions.className='actions';
      if(kind==='WORKFLOW'){
        actions.append(wfButton(job.enabled?'예약 취소':'예약 활성화',async()=>{await api('/schedules/'+job.id,{method:'PATCH',body:{enabled:!job.enabled}});await refresh();},!job.enabled&&!job.next_fire_at,job.enabled?'danger':'secondary'));
        actions.append(wfButton('발생 기록',()=>{$('workflow-schedules').closest('details').open=true;$('workflow-schedules').scrollIntoView({block:'center'});}));
      }else{
        if(job.status==='PENDING')actions.append(wfButton('취소',async()=>{await api('/delayed-resumes/'+job.id+'/cancel',{method:'POST'});await refresh();},false,'danger'));
        if(job.workflow_run_id)actions.append(wfButton('실행 보기',()=>wfSelectRun(job.workflow_run_id)));
      }
      item.append(actions);box.append(item);
    }
    if(!entries.length)box.append(UI.empty('등록된 일정과 후속 요청이 없습니다.','일반 요청 예약 또는 Workflow 예약으로 시작하세요.'));
  }
  $('request-condition').onchange=timing;
  $('request-queue-refresh').onclick=guard(refresh);
  $('schedule-request-new').onclick=()=>{$('request-condition').value='AT_TIME';timing();window.controlCenter.tab('execution');$('instruction').focus();};
  timing();
  setInterval(async()=>{
    if(document.hidden||loading||!state.work||($('tab-execution').hidden&&$('tab-schedule').hidden))return;
    loading=true;
    try{if(!$('tab-schedule').hidden)await window.workflowOperations.loadWork(state.work.id);else await load(state.work.id);}catch(e){notice(e.message);}finally{loading=false;}
  },4000);
  return {load,accept,register,runSelected,renderSchedules};
})();
