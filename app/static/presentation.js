'use strict';
// Progressive disclosure keeps the existing controls mounted and their values intact.
window.uiPresentation = (() => {
  // Explicit roles for static controls; dynamic screens use the same UI primitives.
  for(const id of ['cancel','archive-work','deactivate-category','workflow-disable','workflow-cancel','wf-remove-task','conversation-archive','conversation-close','cancel-login'])if($(id))UI.actionStyle($(id),'danger');
  for(const id of ['editor-save','materials-open','artifact-register','material-save','workspace-save','schedule-save','delay-save','pack-confirm','promotion-save','execution-defaults-save','download'])if($(id))UI.actionStyle($(id),'primary');
  for(const id of ['events','manifest','workflow-events','artifact-advanced','schedule-history','pack-preview-text','tool-diff-advanced'])$(id)?.closest('details')?.classList.add('ui-advanced');
  for(const id of ['resume-label','execution-mode-note','workspace-permission-guide'])$(id)?.classList.add('ui-help');
  for(const details of document.querySelectorAll('details'))if(details.querySelector(':scope > summary')?.textContent.includes('고급 옵션')||details.querySelector(':scope > summary')?.textContent.includes('경로 직접 입력'))details.classList.add('ui-advanced');
  UI.enhance();
  function fold(nodes,title,id,parent){
    const items=nodes.filter(Boolean);if(!items.length)return;
    const details=UI.disclosure(title,null,{id});details.classList.add('settings-disclosure');
    if(parent)parent.append(details);else items[0].before(details);
    for(const item of items)details.append(item);return details;
  }
  const defaults=$('execution-default-GLOBAL').parentElement;
  fold([defaults],'기본 실행 설정 관리','defaults-disclosure');
  // Keep the common permission control beside filesystem access status.
  const permission=$('permission').closest('label');permission.firstChild.textContent='이 요청의 Permission';$('workspace-permission-control').append(permission);
  // Retain the same controls and native form association in a compact sticky dock.
  const execution=$('tab-execution'),dock=document.createElement('div');dock.id='execution-dock';dock.className='execution-dock';
  dock.innerHTML='<div id="execution-dock-status"><span class="ui-field-label">현재 Run 상태</span></div><div class="execution-dock-thread"><span class="ui-field-label">현재 Thread / 실행 모드</span><div id="execution-dock-thread-content"></div></div><div class="execution-dock-controls"><button id="execution-thread-picker" type="button">대화 · 모드 변경</button><div id="execution-dock-actions"></div></div>';
  execution.prepend(dock);$('execution-dock-thread-content').append($('conversation-selected'),$('composer-title'));
  $('execution-dock-status').append($('run-status'));
  $('execute').setAttribute('form','request-form');$('execution-dock-actions').append($('execute'),$('cancel'),$('reconcile'));
  const conversations=fold([$('conversation-panel')],'대화 선택 · 이력 · 동작','conversation-browser-disclosure');conversations.classList.add('execution-disclosure');
  $('conversation-panel').prepend($('execution-actions'),$('execution-mode-note'));
  const request=$('request-form'),profile=request.querySelector('.execution-settings');profile.id='execution-settings-disclosure';
  profile.classList.add('execution-disclosure');$('instruction').rows=5;
  profile.querySelector('summary').textContent='Execution Settings 상세';profile.append($('defaults-disclosure'),$('conversation-query-options'));
  request.prepend(request.querySelector('.selection-summary'));$('instruction').after(request.querySelector('.selection-summary'));request.querySelector('.selection-summary').after($('execution-inheritance'),profile);
  const permissionLink=wfButton('Workspace · 권한 확인',()=>{$('workspace-panel').open=true;$('workspace-panel').scrollIntoView({block:'start'});$('permission').focus({preventScroll:true});});profile.append(permissionLink);
  $('request-condition').closest('.request-timing').after($('resume-label'));
  // Requests and answers precede every operational / debug disclosure.
  const viewer=execution.querySelector('.panel.execution'),runHeading=viewer.querySelector('.panel-heading');runHeading.querySelector('h2').textContent='현재 요청 / 응답';
  const question=$('run-instruction').closest('.run-question'),answer=$('final-answer'),answerHeading=document.createElement('h3');answerHeading.textContent='AI 응답';
  runHeading.after($('run-activity'),question,answerHeading,answer);
  const context=$('context-inspector').closest('details');context.id='run-context-disclosure';context.classList.add('execution-disclosure');
  context.querySelector('summary').textContent='Context · 현재 Run의 실행 설정';context.querySelector('summary').after($('run-meta'));
  const runActions=fold([$('steer-form'),$('resume').parentElement,$('clear-resume'),$('run-steer-history')],'추가 지시 · Continue / Retry','run-actions-disclosure');runActions.classList.add('execution-disclosure');
  const debug=fold([$('events').closest('details'),$('manifest').closest('details')],'고급 정보 · Raw Event / Manifest / Runtime','run-debug-disclosure');debug.classList.add('execution-disclosure','ui-advanced');
  viewer.append(runActions,context,debug);
  const history=fold([$('run-history').parentElement],'이전 실행 기록','execution-history-disclosure');history.classList.add('execution-disclosure');
  $('execution-thread-picker').onclick=()=>{conversations.open=!conversations.open;if(conversations.open){conversations.scrollIntoView({block:'nearest'});$('conversation-search').focus({preventScroll:true});}};
  document.addEventListener('click',event=>{const action=event.target.closest('[data-conversation-action]');if(action&&!action.disabled)conversations.open=false;});
  // A sticky notice and the dock must not cover each other.
  const noticeSize=new ResizeObserver(()=>{const top=($('notice').hidden?12:$('notice').getBoundingClientRect().height+24)+'px';dock.style.top=top;document.documentElement.style.setProperty('--ui-sticky-top',top);});noticeSize.observe($('notice'));
  fold([$('workflow-history').previousElementSibling,$('workflow-history')],'Workflow 실행 기록','workflow-history-disclosure');
  const artifactOverview=$('work-recent-artifacts');const runsOverview=$('work-recent-runs');
  const recentGrid=document.createElement('div');recentGrid.className='overview-recent-grid';runsOverview.previousElementSibling.before(recentGrid);
  for(const list of [runsOverview,artifactOverview]){const panel=document.createElement('section');panel.className='recent-panel';panel.append(list.previousElementSibling,list);recentGrid.append(panel);}
  const materialSection=$('tab-materials');
  const upload=materialSection.querySelector('.upload');$('material-tabs').before(upload);
  // Source group labels already provide the title; remove the old repeated headings.
  for(const h of materialSection.querySelectorAll(':scope > h3'))h.remove();
  const materialHelp=materialSection.querySelector(':scope > p');if(materialHelp)materialHelp.textContent='필요한 자료만 선택하세요. 탭을 이동해도 선택은 유지됩니다.';
  // The same compact toolbar anchors every main screen, with optional detail below.
  function toolbar(root,summaryId){
    const header=root.querySelector('.view-toolbar');if(!header)return;
    header.classList.add('ui-toolbar','ui-sticky');
    if(summaryId){const heading=header.querySelector('h2'),identity=document.createElement('div');identity.className='ui-toolbar-identity';heading.before(identity);identity.append(heading);const summary=document.createElement('span');summary.id=summaryId;summary.className='ui-toolbar-summary';identity.append(summary);}
  }
  for(const [id,summary] of [['tab-overview',null],['tab-materials','materials-view-summary'],['tab-artifacts','artifacts-view-summary'],['tab-schedule','schedule-view-summary'],['tab-review','review-view-summary'],['tab-tools',null],['category-view',null],['management-view','category-management-summary'],['overview',null]])toolbar($(id),summary);
  const materialSummary=document.createElement('div');materialSummary.id='materials-selection-summary';materialSummary.className='ui-selection-summary';upload.before(materialSummary);
  UI.actionStyle(materialSection.querySelector('.view-toolbar [data-tab="execution"]'),'primary');
  UI.actionStyle($('category-create-work'),'primary');
  UI.actionStyle($('schedule-create'),'secondary');
  const scheduleActions=$('tab-schedule').querySelector('.view-toolbar .actions'),workflowSchedule=UI.disclosure('Workflow 예약',[$('schedule-workflow'),$('schedule-create')],{id:'schedule-workflow-actions'});workflowSchedule.classList.add('ui-toolbar-disclosure');scheduleActions.append($('operations-refresh'),workflowSchedule,$('schedule-request-new'));
  const workflowHeader=$('workflow-panel').querySelector(':scope > .panel-heading');workflowHeader.classList.add('ui-toolbar','view-toolbar','ui-sticky');
  const workflowIdentity=document.createElement('div');workflowIdentity.className='ui-toolbar-identity';workflowHeader.firstElementChild.before(workflowIdentity);workflowIdentity.append(workflowHeader.querySelector('h2'));const workflowSummary=document.createElement('span');workflowSummary.id='workflow-view-summary';workflowSummary.className='ui-toolbar-summary';workflowIdentity.append(workflowSummary);
  UI.actionStyle($('workflow-new'),'primary');
  fold([$('workflow-description')],'설명','workflow-description-disclosure');
  const workflowManage=UI.disclosure('Workflow 관리',[$('workflow-edit'),$('workflow-save-template'),$('workflow-disable')]);$('workflow-start').parentElement.append(workflowManage);workflowManage.classList.add('ui-toolbar-disclosure');
  const activity=$('tab-activity'),activityHeader=document.createElement('div');activityHeader.className='view-toolbar ui-toolbar ui-sticky';activity.prepend(activityHeader);activityHeader.append(activity.querySelector(':scope > h2'));const activitySummary=document.createElement('span');activitySummary.id='activity-view-summary';activitySummary.className='ui-toolbar-summary';activityHeader.append(activitySummary);
  const toolHeader=$('work-tools').querySelector('.view-toolbar');toolHeader.querySelector('.muted').remove();const toolActions=document.createElement('div');toolActions.className='actions';toolActions.append($('tool-diff'),$('tool-review'));toolHeader.append(toolActions);UI.actionStyle($('tool-diff'),'secondary');
  $('tools-availability').classList.add('ui-help');
  UI.actionStyle($('tool-save'),'primary');
  const resource=$('material-resources');const packs=$('material-context-packs');resource.classList.add('material-section');packs.classList.add('material-section');
  const budget=$('conversation-budget').closest('label'),over=$('conversation-over-budget').closest('label');fold([budget,over],'Context 예산 설정','context-budget-settings');
  const instructions=$('tool-instruction').closest('label');fold([instructions,$('tool-settings').closest('details'),$('tool-include-context').closest('label'),$('tool-include-context').closest('label').nextElementSibling],'검토 지시 · 실행 설정','review-settings');
  fold([$('tool-patch')],'변경 내용 펼치기','tool-patch-details');
  $('tool-review-result').closest('section').hidden=true;
  fold([$('tool-review-history').parentElement],'이전 코드 검토','tool-history-disclosure');
  const workflowHelp=$('workflow-panel').querySelector(':scope > p');if(workflowHelp)workflowHelp.hidden=true;
  const branchHelp=$('workflow-branch').querySelector('p.ui-help');if(branchHelp)fold([branchHelp],'대화 분기 안내','branch-guidance');
  const headingPath=$('work-paths');headingPath.title=headingPath.textContent;
  // Toolbar and input labels for compact screens and keyboard navigation.
  $('refresh').title='현재 화면 새로고침';$('steer-text').setAttribute('aria-label','실행 중 추가 지시');
  const toggle=document.createElement('button');toggle.className='sidebar-toggle';toggle.setAttribute('aria-label','탐색 메뉴 접기 / 펼치기');toggle.setAttribute('aria-expanded','true');toggle.textContent='☰';
  document.querySelector('main > header').prepend(toggle);
  toggle.onclick=()=>{const closed=document.body.classList.toggle('sidebar-collapsed');toggle.setAttribute('aria-expanded',String(!closed));};
  document.addEventListener('click',event=>{for(const menu of document.querySelectorAll('.row-menu[open],.action-menu[open],.ui-toolbar-disclosure[open]'))if(!menu.contains(event.target))menu.open=false;});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const menu of document.querySelectorAll('.ui-toolbar-disclosure[open]')){menu.open=false;menu.querySelector('summary').focus();}});
  function workLoaded(){
    $('work-paths').title=$('work-paths').textContent;UI.enhance($('work-view'));
    $('tool-review-result').closest('section').classList.toggle('has-result',!!$('tool-review-result').textContent);
    const detail=state.workDetail;
    $('materials-view-summary').textContent=`Workspace 자료 ${detail.sources.length}개`;
    $('artifacts-view-summary').textContent=`결과물 ${detail.artifacts.length}개`;
    $('activity-view-summary').textContent=`실행 이력 ${detail.runs.length}개`;
    selectionChanged();
  }
  function selectionChanged(){if($('materials-selection-summary'))$('materials-selection-summary').textContent=$('selected-materials-summary').textContent;}
  document.addEventListener('change',selectionChanged);
  function threadChosen(){conversations.open=false;}
  function graphControls(container){
    let viewport=container.parentElement;
    if(viewport.classList.contains('graph-viewport'))return;
    const shell=document.createElement('div');shell.className='graph-interaction';const tools=document.createElement('div');tools.className='graph-toolbar';tools.innerHTML='<span>Flow <small>노드를 선택하여 상세 확인</small></span><div class="graph-controls"></div>';
    viewport=document.createElement('div');viewport.className='graph-viewport';viewport.tabIndex=0;viewport.setAttribute('aria-label','Workflow 그래프. 확대 후 스크롤하여 이동');container.before(shell);shell.append(tools,viewport);viewport.append(container);
    let zoom=1;const value=document.createElement('span');value.className='zoom-value';value.textContent='100%';
    function setZoom(next){zoom=Math.min(1.8,Math.max(.45,next));container.style.zoom=zoom;value.textContent=Math.round(zoom*100)+'%';container.dispatchEvent(new Event('graphzoom'));}
    const controls=tools.lastChild;const minus=wfButton('−',()=>setZoom(zoom-.15)),plus=wfButton('+',()=>setZoom(zoom+.15));minus.setAttribute('aria-label','그래프 축소');plus.setAttribute('aria-label','그래프 확대');controls.append(minus,value,plus,wfButton('맞춤',()=>{setZoom(1);setZoom(Math.min(1,viewport.clientWidth/container.scrollWidth));viewport.scrollTo({left:0,top:0,behavior:'instant'});}));
    viewport.addEventListener('keydown',event=>{if(event.target!==viewport)return;if(event.key==='+'||event.key==='='){event.preventDefault();setZoom(zoom+.15);}if(event.key==='-'){event.preventDefault();setZoom(zoom-.15);}});
    let drag=null;viewport.addEventListener('pointerdown',event=>{if(event.button!==0||event.target.closest('.flow-task'))return;drag={x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};viewport.setPointerCapture(event.pointerId);viewport.classList.add('dragging');});
    viewport.addEventListener('pointermove',event=>{if(drag){viewport.scrollLeft=drag.left-(event.clientX-drag.x);viewport.scrollTop=drag.top-(event.clientY-drag.y);}});
    const stop=()=>{drag=null;viewport.classList.remove('dragging');};viewport.addEventListener('pointerup',stop);viewport.addEventListener('pointercancel',stop);
  }
  function graphRendered(container){graphControls(container);}
  UI.enhance($('work-view'));UI.enhance($('category-view'));UI.enhance($('management-view'));
  return {workLoaded,graphRendered,threadChosen,selectionChanged};
})();
