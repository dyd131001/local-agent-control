'use strict';
window.workTools = (() => {
  let workId=null, previewDiff=null, reviewId=null, generation=0, command=null, capability=null, loaded=false;
  const diffHistory=[];
  $('work-tools').innerHTML=`<div class="view-toolbar"><h2>작업 도구</h2><span class="muted">변경사항 보기 · AI 코드 검토</span></div>
    <p id="tools-availability" class="muted"></p>
    <section class="panel"><h3>검토 범위</h3><div id="tool-scope-fields"><label>범위<select id="tool-scope"><option value="WORKING_TREE">현재 변경사항</option><option value="FILES">선택 파일</option><option value="BRANCH">Branch 비교</option></select></label>
    <label id="tool-paths-label" hidden>Workspace 상대 파일 경로 (한 줄에 하나)<textarea id="tool-paths" rows="3" placeholder="src/main.py"></textarea></label>
    <div id="tool-branches" class="select-row" hidden><label>기준 Branch / Commit<input id="tool-base" value="HEAD"></label><label>비교 Branch / Commit<input id="tool-target"></label></div></div>
    <button id="tool-diff">변경사항 보기</button><p id="tool-diff-summary" role="status"></p><div id="tool-diff-files"></div><pre id="tool-patch" class="patch-view" hidden></pre><details><summary>고급 정보 · Diff</summary><pre id="tool-diff-advanced"></pre></details></section>
    <section class="panel"><h3>AI 코드 검토</h3><p class="muted">선택 범위의 스냅샷으로 검토합니다. 기본 권한은 Read Only입니다.</p><label>검토 지시<textarea id="tool-instruction" rows="3">변경사항의 오류와 회귀 위험을 검토하고, 근거와 파일 위치, 수정 제안을 알려 주세요. 파일은 수정하지 마세요.</textarea></label><details><summary>Execution Settings Override</summary><div id="tool-settings"></div></details>
    <label><input id="tool-include-context" type="checkbox">자료 탭에서 선택한 Resource와 이전 결과물을 추가</label><p class="muted">Workspace 파일은 위 검토 범위에서 선택합니다.</p><button id="tool-review" class="primary">AI 코드 검토 실행</button></section>
    <section class="panel"><div class="panel-heading"><h3>검토 결과</h3><button id="tool-review-refresh">갱신</button></div><div id="tool-review-status"></div><pre id="tool-review-result" class="answer-view"></pre><div class="actions"><button id="tool-review-run" disabled>실행 상세</button></div><div id="tool-save-fields" hidden><div class="select-row"><label>결과물 이름<input id="tool-save-title" value="AI Review" maxlength="160"></label><label>저장 범위<select id="tool-save-scope"><option value="WORK">이 Work</option><option value="CATEGORY">같은 Category · Publish</option><option value="GLOBAL">모든 Work · Publish</option></select></label></div><button id="tool-save">결과물로 저장</button></div><div id="tool-saved-artifacts"></div></section>
    <section class="panel"><h3>최근 코드 검토</h3><div id="tool-review-history"></div><p class="muted">최근 200개 실행에서 코드 검토를 표시합니다.</p></section>`;
  window.executionSettings.mount($('tool-settings'),'tool-');
  $('tool-model').onchange=()=>window.executionSettings.reasoning('tool-');
  function scopeBody(){const scope=$('tool-scope').value;return {scope,paths:scope==='FILES'?$('tool-paths').value.split('\n').map(p=>p.trim()).filter(Boolean):[],...(scope==='BRANCH'?{base_ref:$('tool-base').value,target_ref:$('tool-target').value}:{})};}
  function invalidate(){previewDiff=null;$('tool-diff-summary').textContent='선택 범위의 변경사항을 조회하세요.';$('tool-diff-files').replaceChildren();$('tool-patch').hidden=true;$('tool-patch').closest('details')?.removeAttribute('open');$('tool-diff-advanced').textContent='';}
  $('tool-scope-fields').addEventListener('input',invalidate);
  $('tool-scope').onchange=()=>{$('tool-paths-label').hidden=$('tool-scope').value!=='FILES';$('tool-branches').hidden=$('tool-scope').value!=='BRANCH';};
  function reset(){generation++;workId=null;loaded=false;capability=null;reviewId=null;previewDiff=null;command=null;}
  async function load(id){
    if(workId===id && loaded)return;
    workId=id;const epoch=++generation;
    const data=await api('/works/'+id+'/tools');
    if(epoch!==generation||state.work?.id!==id)return;
    capability=data;loaded=true;
    $('tools-availability').textContent=data.diff.available?'Workspace Git 변경사항을 조회할 수 있습니다.':`Git 변경사항 조회 불가: ${data.diff.reason}. 선택 파일의 AI 검토는 사용할 수 있습니다.`;
    $('tool-review').disabled=!data.review.available || !state.models.length;
    $('tool-diff').disabled=false;
    $('tool-scope').value=data.diff.available?'WORKING_TREE':'FILES';$('tool-scope').onchange();$('tool-paths').value='';$('tool-include-context').checked=false;
    window.executionSettings.populate('tool-',{permission:'read-only'});
    invalidate();reviewId=null;$('tool-review-status').textContent='아직 선택한 검토가 없습니다.';$('tool-review-result').textContent='';$('tool-review-result').closest('section').hidden=true;$('tool-saved-artifacts').replaceChildren();$('tool-review-run').disabled=true;$('tool-save-fields').hidden=true;
    await history();
  }
  async function history(){
    const id=workId;const data=await api('/operations/dashboard?'+new URLSearchParams({work_id:id,limit:200}));if(workId!==id||state.work?.id!==id)return;
    rows('tool-review-history',data.recent_runs.items.filter(r=>r.title==='AI Review'),r=>`<button>AI 코드 검토<small>${date(r.updated_at)}</small></button><span class="badge" data-status="${escape(r.state)}">${escape(window.controlCenter.status(r.state))}</span>`,r=>openReview(r.id));
  }
  action('tool-diff',async()=>{
    const id=workId, epoch=generation, body=scopeBody();const data=await api('/works/'+id+'/tools/diff',{method:'POST',body});
    if(epoch!==generation||workId!==id||JSON.stringify(body)!==JSON.stringify(scopeBody()))return;
    previewDiff={data,body};
    $('tool-diff-summary').textContent=data.available?`${data.files.length}개 변경 파일${data.truncated?' · 표시 한도 초과로 일부 내용 생략':''}`:`변경사항 조회 불가: ${data.reason}`;
    $('tool-diff-files').replaceChildren();
    for(const file of data.files){const row=document.createElement('div');row.className='row';row.innerHTML=`<span>${escape(file.old_path?file.old_path+' → ':'')}${escape(file.path)}</span><span>${escape(file.status)} · ${file.binary?'Binary':`+${file.additions??'?'} / −${file.deletions??'?'}`}</span>`;$('tool-diff-files').append(row);}
    $('tool-patch').textContent=data.patch||'변경 내용이 없습니다.';$('tool-patch').hidden=!data.available;
    $('tool-diff-advanced').textContent=JSON.stringify({hash:data.diff_sha256,base:data.base_commit,target:data.target_commit},null,2);
    if(data.available){diffHistory.unshift({workId:id,workName:state.work.name,categoryId:state.work.category_id,at:new Date().toISOString()});diffHistory.splice(10);}
  });
  action('tool-review',async()=>{
    const id=workId,body=scopeBody();if(body.scope!=='FILES'&&!previewDiff?.data.available)throw new Error('먼저 변경사항을 조회하세요.');
    Object.assign(body,{instruction:$('tool-instruction').value,execution_profile:window.executionSettings.read('tool-'),budget:Number($('conversation-budget').value),allow_over_budget:$('conversation-over-budget').checked});
    if(previewDiff?.data.diff_sha256)body.expected_diff_sha256=previewDiff.data.diff_sha256;
    if($('tool-include-context').checked){body.artifact_ids=selectedLibrary();body.resource_ids=[...$('conversation-resources').querySelectorAll('input:checked')].map(i=>i.dataset.resource);}
    const signature=JSON.stringify([id,body]);if(command?.signature!==signature)command={signature,key:crypto.randomUUID()};
    $('tool-review').disabled=true;
    try{const run=await api('/works/'+id+'/tools/reviews',{method:'POST',body,headers:{'Idempotency-Key':command.key}});command=null;if(workId!==id||state.work?.id!==id)return;await selectWork(id,true);await openReview(run.id);await history();}
    finally{if(workId===id)$('tool-review').disabled=!capability?.review.available || !state.models.length;}
  });
  async function openReview(id){
    if(workId!==state.work?.id||!loaded)await load(state.work.id);
    const epoch=generation;const data=await api('/work-tools/reviews/'+id);
    if(epoch!==generation||state.work?.id!==data.run.work_id)return;
    reviewId=id;window.controlCenter.tab('tools');renderReview(data);
  }
  function renderReview(data){
    $('tool-review-result').closest('section').hidden=false;
    $('tool-review-status').replaceChildren(UI.metadata([['실행 상태',UI.status(data.run.status)],['모델',data.run.model],['Reasoning',data.run.reasoning],['Permission',data.run.execution_profile?.permission||'read-only']]));
    $('tool-review-result').textContent=data.result.text||'실행 중입니다. 완료되면 검토 결과가 여기에 표시됩니다.';
    $('tool-review-run').disabled=false;$('tool-save-fields').hidden=!data.actions.some(a=>a.name==='save_artifact');
    rows('tool-saved-artifacts',data.result.saved_artifacts,artifactRow,preview);
  }
  async function refresh(){if(!reviewId)return;const id=reviewId,epoch=generation;const data=await api('/work-tools/reviews/'+id);if(epoch===generation&&reviewId===id)renderReview(data);}
  action('tool-review-refresh',refresh);action('tool-review-run',()=>selectRun(reviewId));
  action('tool-save',async()=>{const id=reviewId;const artifact=await api('/work-tools/reviews/'+id+'/save',{method:'POST',body:{title:$('tool-save-title').value,scope:$('tool-save-scope').value}});await selectWork(state.work.id,true);await refresh();notice('검토 결과를 결과물에 저장했습니다.');await preview(artifact);});
  return {load,reset,openReview,refresh,recentDiffs:()=>diffHistory,runUpdated:run=>{if(run.id===reviewId)refresh().catch(e=>notice(e.message));}};
})();
