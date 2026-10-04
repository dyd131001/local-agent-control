'use strict';
window.workflowOperations = (() => {
  let generation = 0;
  const drafts=new Map();
  async function loadWork(id) {
    const selected = ++generation;
    const [approvals, schedules, delays, queued] = await Promise.all([
      api('/approvals?work_id='+encodeURIComponent(id)),api('/schedules?work_id='+encodeURIComponent(id)),
      api('/delayed-resumes?work_id='+encodeURIComponent(id)),api('/works/'+encodeURIComponent(id)+'/request-queue')]);
    if (selected !== generation || state.work?.id !== id) return;
    if($('review-view-summary'))$('review-view-summary').textContent=`확인할 결과 ${approvals.length}개`;
    window.requestQueue?.accept(id,queued);
    window.requestQueue?.renderSchedules(id,schedules,delays,queued);
    for(const article of $('approval-inbox').children){if(article.dataset.id)drafts.set(article.dataset.id,{note:article.querySelector('textarea').value,scope:article.querySelector('select').value,scopeOpen:article.querySelector('select').closest('details')?.open});}
    $('approval-inbox').replaceChildren();
    for (const approval of approvals) {
      const article=UI.detail(wfState.definitions.flatMap(d=>d.tasks||[]).find(t=>t.id===approval.task_definition_id)?.name||'작업 결과',{status:UI.status('WAITING','검토 대기')});article.classList.add('review-detail');article.dataset.id=approval.id;
      article.append(UI.metadata([['검토 방식',approval.policy==='APPROVAL_REQUIRED'?'승인 후 진행':'진행 후 검토'],['실행 상태',UI.status(approval.task_status)]]));
      if(approval.policy==='APPROVAL_REQUIRED')article.append(UI.warning('이 결과를 승인하면 후속 작업이 진행됩니다. 수정 요청은 기존 결과를 바탕으로 새 실행을 만듭니다.','후속 작업이 승인을 기다리고 있습니다.'));
      const outputs=document.createElement('div');outputs.className='review-outputs';
      for(const output of approval.outputs){const row=document.createElement('div');row.className='ui-lineage-row';row.append(wfArtifactLink(output.artifact),UI.status(output.artifact.availability));outputs.append(row);}article.append(outputs);
      if (!approval.outputs.length) {const text=document.createElement('pre');text.textContent=approval.final_text;article.append(text);}
      const note=document.createElement('textarea');note.rows=3;note.placeholder='수정 요청 지시 또는 검토 의견';note.setAttribute('aria-label','수정 요청 지시 또는 검토 의견');note.value=drafts.get(approval.id)?.note||'';const noteLabel=document.createElement('label');noteLabel.textContent='검토 의견 · 수정 지시';noteLabel.append(note);article.append(noteLabel);
      const scope=document.createElement('select');wfOptions(scope,[['WORK','Work에 Publish'],['CATEGORY','Category에 Publish'],['GLOBAL','Global에 Publish']],drafts.get(approval.id)?.scope||'WORK');scope.setAttribute('aria-label','결과물 공개 범위');const scopeLabel=document.createElement('label');scopeLabel.textContent='승인 및 Publish의 공개 범위';scopeLabel.append(scope);const scopeDetails=UI.disclosure('Publish 공개 범위',scopeLabel);scopeDetails.open=!!drafts.get(approval.id)?.scopeOpen;article.append(scopeDetails);
      const buttons=document.createElement('div');buttons.className='actions';
      for (const [action,label] of [['APPROVE','승인'],['APPROVE_PUBLISH','승인 및 Publish'],['REJECT','반려'],['REVISION','수정 요청']]) {
        buttons.append(wfButton(label,async()=>{
          const result=await api(`/approvals/${approval.id}/decision`,{method:'POST',body:{action,comment:note.value,
            instruction:action==='REVISION'?note.value:null,scope:scope.value}});
          await loadWork(id);await wfSelectRun(result.revision_workflow_run_id||approval.workflow_run_id);
        },false,action==='APPROVE'?'primary':action==='REJECT'?'danger':'secondary'));
      }article.append(buttons);$('approval-inbox').append(article);
    }
    if(!approvals.length)$('approval-inbox').replaceChildren(UI.empty('검토할 결과가 없습니다.','승인이나 사후 검토가 필요한 작업 결과가 여기에 표시됩니다.'));
    $('workflow-schedules').replaceChildren();
    for(const schedule of schedules){
      const row=UI.detail(wfState.definitions.find(d=>d.id===schedule.workflow_definition_id)?.name||'Workflow',{status:UI.status(schedule.enabled?'ACTIVE':'DISABLED')});
      row.append(UI.metadata([['실행 방식',schedule.kind==='RECURRING'?'반복 실행':'한 번 실행'],['다음 실행',date(schedule.next_fire_at)],['놓친 예약',schedule.misfire_policy==='SKIP'?'허용 지연 초과 시 생략':'지연 시 한 번 실행']]));
      const actions=document.createElement('div');actions.className='actions ui-actions';row.append(actions);
      actions.append(wfButton('예약 편집',()=>openSchedule(schedule.id)));
      actions.append(wfButton(schedule.enabled?'비활성화':'활성화',async()=>{
        await api(`/schedules/${schedule.id}`,{method:'PATCH',body:{enabled:!schedule.enabled}});await loadWork(id);
      },!schedule.enabled&&!schedule.next_fire_at,schedule.enabled?'danger':'secondary'));
      actions.append(wfButton('예약 기록',async()=>{const detail=await api(`/schedules/${schedule.id}`);$('schedule-history').textContent=JSON.stringify(detail.fires,null,2);$('schedule-history-list').replaceChildren();for(const fire of detail.fires){const entry=UI.detail('예약 실행',{status:UI.status(fire.status)});entry.append(UI.metadata([['예정 시각',date(fire.scheduled_for)]]));if(fire.error)entry.append(UI.warning(fire.error,'예약 처리 오류'));if(fire.workflow_run_id)entry.append(wfButton('실행 보기',()=>wfSelectRun(fire.workflow_run_id)));$('schedule-history-list').append(entry);}if(!detail.fires.length)$('schedule-history-list').append(UI.empty('아직 발생한 예약이 없습니다.'));$('schedule-history-list').closest('details').open=true;}));
      $('workflow-schedules').append(row);
    }
    if(!schedules.length)$('workflow-schedules').append(UI.empty('Workflow 예약이 없습니다.','상단에서 Workflow를 선택해 예약할 수 있습니다.'));
    $('workflow-delays').replaceChildren();
    for(const job of delays){const row=UI.detail('Checkpoint 이어하기',{status:UI.status(job.status)});row.append(UI.metadata([['예정 시각',date(job.due_at)]]));if(job.error)row.append(UI.warning(job.error,'이어하기 처리 오류'));
      if(job.status==='PENDING')row.append(wfButton('예약 취소',async()=>{await api(`/delayed-resumes/${job.id}/cancel`,{method:'POST'});await loadWork(id);},false,'danger'));
      if(job.workflow_run_id)row.append(wfButton('새 실행 기록',()=>wfSelectRun(job.workflow_run_id)));
      $('workflow-delays').append(row);}
    if(!delays.length)$('workflow-delays').append(UI.empty('이어하기 예약이 없습니다.','Workflow의 완료한 작업에서 Checkpoint 이어하기를 예약할 수 있습니다.'));
  }
  function renderRun(detail) {
    const wr=detail.workflow_run, terminal=['COMPLETED','CANCELLED','REJECTED'].includes(wr.status);
    $('workflow-pause').disabled=terminal||wr.paused;
    $('workflow-resume').disabled=terminal||!wr.paused;
    $('workflow-pause').onclick=async()=>{try{await api(`/workflow-runs/${wr.id}/pause`,{method:'POST'});await wfSelectRun(wr.id);}catch(e){notice(e.message);}};
    $('workflow-resume').onclick=async()=>{try{await api(`/workflow-runs/${wr.id}/resume`,{method:'POST'});await wfSelectRun(wr.id);}catch(e){notice(e.message);}};
    loadWork(wr.work_id).catch(e=>notice(e.message));
  }
  async function openSchedule(scheduleId=null) {
    if(!scheduleId&&!wfState.definition)return notice('Workflow를 먼저 선택하세요.');
    const schedule=scheduleId?(await api(`/schedules/${scheduleId}`)).schedule:null;
    $('schedule-editor').dataset.scheduleId=scheduleId||'';
    $('schedule-editor').querySelector('h2').textContent=schedule?'Workflow 예약 편집':'Workflow 예약';
    $('schedule-kind').value=schedule?.kind||'ONE_TIME';$('schedule-interval').value=schedule?.interval_seconds?String(schedule.interval_seconds/60):'60';
    $('schedule-misfire').value=schedule?.misfire_policy||'FIRE_ONCE';
    const future=schedule?.next_fire_at?new Date(schedule.next_fire_at):new Date(Date.now()+60*60000);
    const local=new Date(future.getTime()-future.getTimezoneOffset()*60000);
    $('schedule-start').value=local.toISOString().slice(0,16);$('schedule-interval').closest('label').hidden=$('schedule-kind').value!=='RECURRING';$('schedule-editor').showModal();
  }
  async function saveSchedule(){
    const kind=$('schedule-kind').value;
    const scheduleId=$('schedule-editor').dataset.scheduleId;
    const body={kind,interval_minutes:kind==='RECURRING'?Number($('schedule-interval').value):null,misfire_policy:$('schedule-misfire').value};
    if(scheduleId){body.enabled=true;body.next_fire_at=new Date($('schedule-start').value).toISOString();await api(`/schedules/${scheduleId}`,{method:'PATCH',body});}
    else{body.start_at=new Date($('schedule-start').value).toISOString();body.source_ids=selectedContext();body.artifact_ids=selectedLibrary();await api(`/workflows/${wfState.definition.id}/schedules`,{method:'POST',body});}
    $('schedule-editor').close();await loadWork(state.work.id);window.controlCenter?.tab('schedule');
  }
  function openDelay(task){$('delay-editor').dataset.taskId=task.id;$('delay-instruction').value='Checkpoint와 결과물을 참고하여 작업을 이어 주세요.';$('delay-hours').value='5';$('delay-editor').showModal();}
  async function saveDelay(){await api(`/task-runs/${$('delay-editor').dataset.taskId}/delayed-resumes`,{method:'POST',
    body:{instruction:$('delay-instruction').value,delay_hours:Number($('delay-hours').value)},headers:{'Idempotency-Key':crypto.randomUUID()}});
    $('delay-editor').close();await loadWork(state.work.id);}
  $('workflow-schedule-new').onclick=()=>openSchedule();
  $('operations-refresh').onclick=()=>loadWork(state.work.id).catch(e=>notice(e.message));
  $('schedule-save').onclick=()=>saveSchedule().catch(e=>notice(e.message));$('schedule-close').onclick=()=>$('schedule-editor').close();
  $('delay-save').onclick=()=>saveDelay().catch(e=>notice(e.message));$('delay-close').onclick=()=>$('delay-editor').close();
  $('schedule-kind').onchange=()=>{$('schedule-interval').closest('label').hidden=$('schedule-kind').value!=='RECURRING';};
  return {loadWork,renderRun,openDelay,openSchedule};
})();
