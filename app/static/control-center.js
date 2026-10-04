'use strict';
// Navigation and presentation only. Operational states and totals belong to the API.
window.controlCenter = (() => {
  const tabs = [['overview','개요'],['execution','실행'],['flow-plans','업무 플로우'],['workflow','Workflow'],['materials','자료'],['artifacts','결과물'],['tools','작업 도구'],['schedule','일정'],['review','검토'],['activity','활동']];
  const labels = {RUNNING:'진행 중',CREATED:'실행 준비',QUEUED:'대기',COMPLETED:'완료',FAILED:'실패',CANCELLED:'취소',BLOCKED:'차단',READY:'실행 준비',SKIPPED:'생략',WAITING_APPROVAL:'승인 대기',PAUSED:'일시 정지',SCHEDULED:'예정',RECOVERY_REQUIRED:'복구 확인 필요',CONTEXT_WARNING:'Context 경고',REJECTED:'반려'};
  const status = value => labels[value] || value || '미관측';
  let materialTab='WORKSPACE';
  let activeTab='overview', dashboardEpoch=0, workEpoch=0, collectionEpoch=0, restoring=false, ready=false, dashboardScope='', operations=null, viewEpoch=0, freshRuntime=true;
  const busy = fn => async () => {try {await fn();} catch(e) {notice(e.message);}};
  const section = (title,id) => {const el=document.createElement('section');el.className='dashboard-section';el.innerHTML=`<h2>${escape(title)}</h2><div id="${id}"></div>`;return el;};
  const badge = value => UI.statusHTML(value,status(value));
  function setRoute(extra='') {
    if(restoring || !ready)return;
    const hash=state.work?`#work/${encodeURIComponent(state.work.id)}/${activeTab}${extra}`:state.view==='category'?`${state.categoryManagement?'#management/category/':'#category/'}${encodeURIComponent(state.category)}`:state.view==='management'?'#management':`#dashboard${state.category?'?category='+encodeURIComponent(state.category):''}`;
    if(location.hash!==hash)history.pushState(null,'',hash);
  }
  function tab(name, route=true) {
    if(!tabs.some(([id])=>id===name))name='overview';activeTab=name;
    for(const [id] of tabs){$('tab-'+id).hidden=id!==name;const button=$('tab-button-'+id);button.classList.toggle('active',id===name);button.setAttribute('aria-selected',String(id===name));button.tabIndex=id===name?0:-1;}
    if(route)setRoute();
    if(name==='tools' && state.work)window.workTools?.load(state.work.id).catch(e=>notice(e.message));
    if(name==='flow-plans' && state.work)window.flowPlans?.loadWork(state.work.id).catch(e=>notice(e.message));
    if(['artifacts','activity'].includes(name) && state.work)refreshCollection(name).catch(e=>notice(e.message));
    selectionSummary();
  }
  async function refreshCollection(name){
    const id=state.work.id,epoch=++collectionEpoch,data=await api('/works/'+id);
    if(state.work?.id!==id||epoch!==collectionEpoch||activeTab!==name)return;
    if(name==='artifacts'){rows('artifacts',data.artifacts,artifactRow,preview);if($('artifacts-view-summary'))$('artifacts-view-summary').textContent=`결과물 ${data.artifacts.length}개`;}
    else{renderActivity(data);if($('activity-view-summary'))$('activity-view-summary').textContent=`실행 이력 ${data.runs.length}개`;}
  }
  for(const [id,label] of tabs){const button=wfButton(label,()=>tab(id));button.id='tab-button-'+id;button.setAttribute('role','tab');button.setAttribute('aria-controls','tab-'+id);$('work-tabs').append(button);$('tab-'+id).setAttribute('role','tabpanel');$('tab-'+id).setAttribute('aria-labelledby',button.id);}
  $('work-tabs').setAttribute('role','tablist');
  $('work-tabs').addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();let index=tabs.findIndex(([id])=>id===activeTab);index=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tab(tabs[index][0]);$('tab-button-'+activeTab).focus();});
  document.addEventListener('click',event=>{const target=event.target.closest('[data-tab]');if(target)tab(target.dataset.tab);});
  document.addEventListener('change',selectionSummary);
  function workEnabled(w){return !!w&&!w.archived&&!!state.dashboard?.categories.find(c=>c.id===w.category_id)?.active;}
  function navigation(){
    if(!state.dashboard)return;
    const inactiveOpen=$('inactive-navigation')?.open; $('categories').replaceChildren();
    for(const c of state.dashboard.categories.filter(c=>c.active)){
      const group=document.createElement('section');group.className='nav-group';group.dataset.search=c.name.toLowerCase();
      const heading=document.createElement('div');heading.className='category';
      const link=wfButton(c.name,()=>showCategory(c.id));link.classList.toggle('selected-category',state.view==='category'&&state.category===c.id);heading.append(link);group.append(heading);
      for(const w of state.dashboard.works.filter(w=>w.category_id===c.id&&!w.archived)){
        const link=wfButton(w.name,()=>selectWork(w.id));link.className='work-nav';link.dataset.search=w.name.toLowerCase();link.dataset.workId=w.id;link.classList.toggle('active',state.work?.id===w.id);if(state.work?.id===w.id)link.setAttribute('aria-current','page');group.append(link);
      }
      $('categories').append(group);
    }
    const inactive=state.dashboard.categories.filter(c=>!c.active||state.dashboard.works.some(w=>w.category_id===c.id&&w.archived));
    if(inactive.length){
      const section=document.createElement('details');section.id='inactive-navigation';section.className='inactive-navigation';section.open=!!inactiveOpen;section.innerHTML='<summary>비활성 항목 관리</summary>';
      for(const c of inactive){
        const group=document.createElement('section');group.className='nav-group inactive-group';group.dataset.search=c.name.toLowerCase();
        const heading=document.createElement('div');heading.className='category inactive-category';const name=wfButton(c.name+(c.active?'':' · 비활성'),()=>{},true);name.className='inactive-label';const manage=wfButton('관리',()=>showCategory(c.id,true));manage.setAttribute('aria-label',c.name+' 관리');heading.append(name,manage);group.append(heading);
        for(const w of state.dashboard.works.filter(w=>w.category_id===c.id&&(!c.active||w.archived))){const link=wfButton(w.name+(w.archived?' · 보관됨':''),()=>{},true);link.className='work-nav inactive-label';link.dataset.search=w.name.toLowerCase();group.append(link);}
        section.append(group);
      }
      $('categories').append(section);
    }
    filterNavigation();
    $('dashboard-button').classList.toggle('active',state.view==='dashboard');$('manage-categories').classList.toggle('active',state.view==='management'||state.categoryManagement&&state.view==='category');
    wfOptions($('dashboard-category'),[['','전체 Category'],...state.dashboard.categories.filter(c=>c.active).map(c=>[c.id,c.name])],state.view==='dashboard'?state.category||'':'');
  }
  function showDashboard(){viewEpoch++;state.categoryManagement=false;dashboardScope=state.category||'';$('breadcrumb').textContent='CONTROL CENTER / OPERATIONS';navigation();setRoute();}
  function leaveWork(view){state.workSelection++;closeStream();window.workflows?.leave();state.work=null;state.run=null;state.resume=null;state.view=view;$('overview').hidden=true;$('work-view').hidden=true;$('category-view').hidden=view!=='category';$('management-view').hidden=view!=='management';}
  async function showCategory(id,management=false,fetch=true){
    const epoch=++viewEpoch;leaveWork('category');state.category=id;state.categoryManagement=management;$('category-work-filter').value=management?'ALL':'ACTIVE';
    $('category-work-search').value='';
    if(fetch)await dashboard();if(epoch!==viewEpoch||state.view!=='category'||state.category!==id)return;
    const c=state.dashboard?.categories.find(c=>c.id===id);
    if(!c)return showManagement(false);
    if(!c.active)state.categoryManagement=true;
    renderCategory();navigation();setRoute();
  }
  async function showManagement(fetch=true){const epoch=++viewEpoch;leaveWork('management');state.category=null;state.categoryManagement=true;if(fetch)await dashboard();if(epoch!==viewEpoch||state.view!=='management')return;renderManagement();navigation();setRoute();}
  function renderCategory(){
    const c=state.dashboard?.categories.find(c=>c.id===state.category);if(!c)return;
    $('page-title').textContent=c.name;$('breadcrumb').textContent='CONTROL CENTER / CATEGORY';$('category-detail-name').textContent=c.name;
    const works=state.dashboard.works.filter(w=>w.category_id===c.id),active=works.filter(w=>!w.archived);
    const metadata=UI.metadata([['상태',UI.status(c.active?'ACTIVE':'DISABLED')],['포함 Work',`${works.length}개 · 활성 ${active.length} · 보관 ${works.length-active.length}`],['새 Workspace 생성 기본 위치',state.storage?.workspace_root||'확인 필요','path']]);$('category-detail-meta').replaceChildren(...metadata.children);$('category-detail-meta').classList.add('ui-metadata');
    $('category-disabled-note').hidden=c.active;$('category-create-work').disabled=!c.active;$('category-toggle-active').textContent=c.active?'카테고리 비활성화':'카테고리 다시 활성화';UI.actionStyle($('category-toggle-active'),c.active?'danger':'primary');
    const filter=$('category-work-filter').value,box=$('category-work-list'),opened=new Set([...box.children].filter(row=>row.querySelector('details')?.open).map(row=>row.dataset.workId));box.replaceChildren();
    const search=$('category-work-search').value.trim().toLowerCase();
    const shown=works.filter(w=>(filter==='ALL'||(filter==='ACTIVE'?!w.archived:w.archived))&&(`${w.name} ${w.description||''}`).toLowerCase().includes(search));
    for(const w of shown){
      const row=UI.detail(w.name,{status:UI.status(w.archived?'ARCHIVED':c.active?'ACTIVE':'DISABLED',w.archived?'보관됨':c.active?'활성':'Category 비활성')});row.classList.add('ui-managed-row');row.dataset.workId=w.id;
      const main=wfButton('',()=>selectWork(w.id),!workEnabled(w));main.classList.add('managed-work-main');main.innerHTML=`<strong>${escape(w.name)}</strong>`;row.querySelector('h3').replaceWith(main);
      if(w.description){const description=document.createElement('p');description.className='ui-list-description';description.textContent=w.description;row.append(description);}
      const controls=document.createElement('div');controls.className='actions';controls.append(wfButton('이름 · 설명 수정',()=>edit('work',w)),wfButton(w.archived?'보관 해제':'작업 보관',async()=>{await api('/works/'+w.id,{method:'PATCH',body:{archived:!w.archived}});if(w.archived)$('category-work-filter').value='ALL';await dashboard();},false,w.archived?'secondary':'danger'));
      row.append(UI.disclosure('Workspace · Work 관리',[UI.metadata([['현재 Workspace',w.workspace_path||w.linked_workspace_path||w.path,'path']]),controls],{open:opened.has(w.id)}));box.append(row);
    }
    if(!shown.length)box.append(UI.empty(search?'검색 조건에 맞는 Work가 없습니다.':'이 목록에 포함된 작업이 없습니다.',search?'이름이나 상태 필터를 변경하세요.':'상단에서 새 작업을 만들거나 목록 필터를 변경하세요.'));
  }
  function renderManagement(){
    $('page-title').textContent='카테고리 · 작업 관리';$('breadcrumb').textContent='CONTROL CENTER / MANAGEMENT';const box=$('category-management-list');box.replaceChildren();
    const categories=state.dashboard?.categories||[],search=$('category-management-search').value.trim().toLowerCase(),filter=$('category-management-filter').value;
    if($('category-management-summary'))$('category-management-summary').textContent=`전체 ${categories.length}개 · 활성 ${categories.filter(c=>c.active).length} · 비활성 ${categories.filter(c=>!c.active).length}`;
    for(const c of categories.filter(c=>c.name.toLowerCase().includes(search)&&(filter==='ALL'||(filter==='ACTIVE'?c.active:!c.active)))){
      const works=state.dashboard.works.filter(w=>w.category_id===c.id),row=UI.detail(c.name,{status:UI.status(c.active?'ACTIVE':'DISABLED')});row.classList.add('ui-managed-row');row.dataset.categoryId=c.id;
      row.append(UI.metadata([['포함 Work',works.length+'개'],['활성 Work',works.filter(w=>!w.archived).length+'개'],['보관 Work',works.filter(w=>w.archived).length+'개']],{compact:true}));
      const actions=document.createElement('div');actions.className='actions';actions.append(wfButton('상세 · Work 관리',()=>showCategory(c.id,true),false,'primary'),wfButton(c.active?'비활성화':'다시 활성화',()=>setCategoryActive(c),false,c.active?'danger':'secondary'));row.append(actions);box.append(row);
    }
    if(!box.children.length)box.append(UI.empty(categories.length?'검색 조건에 맞는 카테고리가 없습니다.':'아직 카테고리가 없습니다.',categories.length?'검색어나 상태 필터를 변경하세요.':'카테고리를 만들어 작업을 분류하세요.'));
  }
  async function setCategoryActive(c){await api('/categories/'+c.id,{method:'PATCH',body:{active:!c.active}});await dashboard();if(state.view==='category'){state.categoryManagement=!state.dashboard.categories.find(item=>item.id===state.category)?.active;navigation();setRoute();}}
  async function metadataUpdated(){
    if(state.view==='dashboard'&&state.category&&!state.dashboard.categories.find(c=>c.id===state.category)?.active)state.category=null;
    if(state.work&&!workEnabled(state.dashboard.works.find(w=>w.id===state.work.id)))return showCategory(state.work.category_id,true,false);
    if(state.view==='category'){const c=state.dashboard.categories.find(c=>c.id===state.category);if(c&&!c.active)state.categoryManagement=true;renderCategory();setRoute();}
    if(state.view==='management')renderManagement();
  }
  $('manage-categories').onclick=busy(()=>showManagement());$('category-work-filter').onchange=renderCategory;
  $('category-work-search').oninput=renderCategory;$('category-management-search').oninput=renderManagement;$('category-management-filter').onchange=renderManagement;
  $('category-create-work').onclick=()=>edit('work');$('category-rename').onclick=()=>edit('category',state.dashboard.categories.find(c=>c.id===state.category));$('category-toggle-active').onclick=busy(()=>setCategoryActive(state.dashboard.categories.find(c=>c.id===state.category)));
  for(const name of ['개발','업무','기획','학습','개인','리서치']){const button=wfButton(name,()=>{$('editor-name').value=name;$('editor-name').dispatchEvent(new Event('input',{bubbles:true}));});button.className='category-preset';$('category-presets').querySelector('.actions').append(button);}
  $('editor-name').addEventListener('input',()=>{for(const b of $('category-presets').querySelectorAll('button')){const active=b.textContent===$('editor-name').value;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));}});
  $('dashboard-category').onchange=busy(async()=>{state.category=$('dashboard-category').value||null;await showOverview();});
  async function openItem(item){
    if(item.entity_type==='REQUEST_QUEUE'){if(state.work?.id!==item.work_id)await selectWork(item.work_id);if(state.work?.id===item.work_id){await window.workflowOperations.loadWork(item.work_id);tab('schedule');}return;}
    if(state.work?.id!==item.work_id)await selectWork(item.work_id);
    if(state.work?.id!==item.work_id)return;
    if(item.entity_type==='APPROVAL'){tab('review');return;}
    if(['SCHEDULE','SCHEDULE_FIRE','DELAYED_RESUME'].includes(item.entity_type)){tab('schedule');return;}
    if(item.entity_type==='CONTEXT_PACK'){tab('materials');await window.conversations.previewPack(item.id);return;}
    if(item.entity_type==='THREAD'){tab('execution');await window.conversations.selectThread(item.id);return;}
    if(item.entity_type==='RUN'){
      if(item.title==='AI Review'){tab('tools');await window.workTools.openReview(item.id);}
      else await selectRun(item.id);
      return;
    }
    if(item.entity_type==='WORKFLOW' || item.workflow_run_id){await wfSelectRun(item.workflow_run_id||item.id);return;}
    tab('overview');
  }
  function operationRows(container, items){
    if(!items.length){container.innerHTML='<p class="empty">현재 항목이 없습니다.</p>';return;}
    for(const item of items){
      const row=document.createElement('div');row.className='row operation-row';row.dataset.status=item.state;
      const content=document.createElement('button');content.className='row-main';content.innerHTML=`<span class="row-title">${escape(item.work_name)}</span> <span class="muted">${escape(item.title)}</span><small>${date(item.due_at||item.updated_at)}${item.execution_settings?' · '+escape(item.execution_settings.model):''}</small>`;
      if(item.progress)content.innerHTML+=`<div class="progress-track"><span style="width:${Math.max(0,Math.min(100,Number(item.progress.completion_percent)||0))}%"></span></div><small>${item.progress.completed} / ${item.progress.total} Task${item.progress.waiting_approvals?' · 승인 '+item.progress.waiting_approvals+'건 대기':''}</small>`;
      if(item.blocked_by_pause)content.innerHTML+='<small>일시 정지로 대기 중</small>';
      const enabled=workEnabled(state.dashboard?.works.find(w=>w.id===item.work_id));content.disabled=!enabled;
      content.onclick=busy(()=>openItem(item));row.append(content);
      const meta=document.createElement('div');meta.className='row-actions';meta.innerHTML=badge(item.state);
      const menu=document.createElement('details');menu.className='row-menu';menu.innerHTML='<summary aria-label="항목 상세와 제어">···</summary><div class="menu-content"></div>';const choices=menu.lastChild;
      choices.append(wfButton(enabled?'상세 열기':'Work 관리',()=>enabled?openItem(item):showCategory(item.category_id,true)));
      if(item.execution_settings){const p=document.createElement('p');p.className='muted';p.textContent=[item.execution_settings.model,item.execution_settings.reasoning,item.execution_settings.permission,item.execution_settings.speed].join(' · ');choices.append(p);}
      if(item.warnings?.length){const p=document.createElement('p');p.textContent=item.warnings.join(' · ');choices.append(p);}
      for(const a of item.actions||[]){
        const text={cancel:'실행 취소',pause:'일시 정지',resume:'계속하기',disable:'예약 비활성화',reconcile:'상태 다시 확인',reconcile_compaction:'압축 상태 확인'}[a.name];
        if(!text || a.method==='GET'||!enabled)continue;
        choices.append(wfButton(text,async()=>{await api(a.path.replace(/^\/api/,''),{method:a.method,...(a.body?{body:a.body}:{})});if(state.work)await refreshWorkOperations();else await renderDashboard();}));
      }
      meta.append(menu);row.append(meta);container.append(row);
    }
  }
  function disclosure(root,title,id,open=false){
    const el=document.createElement('details');el.className='section-disclosure';el.dataset.disclosure=id;el.open=open;el.innerHTML=`<summary>${escape(title)}<span class="disclosure-chevron">⌄</span></summary><div class="disclosure-body" id="${id}"></div>`;root.append(el);return el.lastChild;
  }
  function addCollection(root,title,key,page,scope,fold=false){
    const id='collection-'+key.replaceAll('.','-');
    let box,sec;
    if(fold){box=disclosure(root,`${title} · ${page.total}`,id);sec=box;}
    else{sec=section(title,id);sec.firstChild.insertAdjacentHTML('beforeend',` <span class="count-pill">${page.total}</span>`);root.append(sec);box=sec.lastChild;}
    operationRows(box,page.items.slice(0,4));
    if(page.items.length>4){const rest=disclosure(sec,`나머지 ${page.items.length-4}개 보기`,id+'-rest');operationRows(rest,page.items.slice(4));}
    if(page.has_more){const more=wfButton('이전 항목 더 보기',async()=>{
      more.disabled=true;
      try{const result=await api('/operations/dashboard?'+new URLSearchParams({...scope,limit:20,offset:page.offset+page.limit}));const next=key.split('.').reduce((value,part)=>value[part],result);page=next;operationRows(box,next.items);more.hidden=!next.has_more;}finally{more.disabled=false;}
    });sec.append(more);}
  }
  function runtimeView(container,data){
    const r=data.runtime, provider=r.provider, rate=provider.rate_limits||{};
    container.innerHTML=`<p>Runtime: ${escape(provider.connection||'미관측')} · 실행기: ${r.dispatcher.running?'동작 중':'중지'} · 동시 실행 한도 ${r.dispatcher.max_parallel_tasks}</p><p class="muted">Usage와 제한은 Runtime 관측값입니다. 미제공 값은 추정하지 않습니다.</p>`;
    const limits=document.createElement('p');limits.textContent=`Rate limit: ${rate.status || 'UNAVAILABLE'} · 관측 ${date(rate.observed_at)}`;container.append(limits);
    const rd=rate.data;
    if(rd){
      const limits=[['계정',rd.primary],...Object.entries(rd.buckets||{})];
      for(const [name,limit] of limits){if(!limit)continue;for(const [label,window] of [['기본',limit.primary],['추가',limit.secondary]])if(window){const p=document.createElement('p');const reset=window.resets_at;p.textContent=`${limit.name||name} · ${label} 사용률 ${window.used_percent==null?'미제공':window.used_percent+'%'} · 재설정 ${reset==null?'미제공':date(typeof reset==='number'?reset*1000:reset)}`;container.append(p);}
        if(limit.spend_control_reached!=null){const p=document.createElement('p');p.textContent=`${name} 지출 제한: ${limit.spend_control_reached?'도달':'미도달'}`;container.append(p);}
      }
      const p=document.createElement('p');p.textContent=`일반 사용 허용: ${rd.ordinary_usage_allowed==null?'미제공':rd.ordinary_usage_allowed?'허용':'제한'}`;container.append(p);
    }
    for(const u of data.usage.items){const row=document.createElement('p');const run=data.recent_runs.items.find(r=>r.id===u.run_id);row.textContent=`${run?.work_name||'실행'} · 마지막 Turn ${u.last_turn?.totalTokens??'미관측'} · Thread 누적 ${u.thread_total?.totalTokens??'미관측'} · Context 한도 ${u.model_context_window??'미관측'}`;container.append(row);}
    if(!data.usage.items.length)container.insertAdjacentHTML('beforeend','<p class="empty">관측된 Usage가 없습니다.</p>');
    const advanced=document.createElement('details');advanced.innerHTML='<summary>고급 정보 · Runtime 관측 원문</summary>';const pre=document.createElement('pre');pre.textContent=JSON.stringify({provider,goal:data.goal},null,2);advanced.append(pre);container.append(advanced);
  }
  async function renderDashboard(){
    const epoch=++dashboardEpoch, scope=state.category?{category_id:state.category}:{};
    const force=freshRuntime;freshRuntime=false;
    let data;try{data=await api('/operations/dashboard?'+new URLSearchParams({...scope,limit:20,...(force?{refresh_runtime:true}:{})}));}catch(error){if(force)freshRuntime=true;throw error;}
    if(epoch!==dashboardEpoch||state.view!=='dashboard')return;
    const root=$('dashboard-content');const expanded=new Map([...root.querySelectorAll('details[data-disclosure]')].map(e=>[e.dataset.disclosure,e.open]));
    const sameScope=dashboardScope===(state.category||'');operations=data;dashboardScope=state.category||'';root.replaceChildren();
    const hero=document.createElement('div');hero.className='dashboard-hero';hero.innerHTML=`<div><span class="eyebrow">YOUR WORKSPACE, AT A GLANCE</span><h2>${data.summary.RUNNING.total?'작업이 진행 중입니다.':'다음 작업을 시작할 준비가 됐어요.'}</h2><p class="muted">${data.summary.RUNNING.total?'진행 상황을 확인하고 필요한 순간에 개입하세요.':'Work를 열어 요청을 보내거나 Workflow를 시작하세요.'}</p></div><span class="live-indicator"><i></i>${data.runtime.dispatcher.running?'실행기 연결됨':'실행기 확인 필요'}</span>`;root.append(hero);
    if(data.global_execution_block.blocked){const block=document.createElement('p');block.className='warning-banner';block.textContent=`전체 실행 차단 · ${data.global_execution_block.recovery_run_count}개 실행의 상태 확인이 필요합니다.`;if(state.category)block.append(wfButton('전체 범위 보기',()=>{state.category=null;showOverview();}));root.append(block);}
    const pulse=document.createElement('div');pulse.className='pulse-strip';
    for(const [key,title,target] of [['RUNNING','진행 중','focus-running'],['WAITING_APPROVAL','승인 대기','focus-attention'],['SCHEDULED','예정 실행','focus-schedule']]){const b=wfButton('',()=>{const t=$(target);t?.closest('details')?.setAttribute('open','');t?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});});b.innerHTML=`<span>${title}</span><strong>${data.summary[key].total}</strong><span class="pulse-arrow">↗</span>`;b.dataset.status=key;pulse.append(b);}root.append(pulse);
    const layout=document.createElement('div');layout.className='dashboard-layout';layout.innerHTML='<div id="focus-running"></div><div class="attention-column" id="focus-attention"></div>';root.append(layout);
    const focus=$('focus-running'),attention=$('focus-attention');
    if(data.states.RUNNING.total)addCollection(focus,'지금 진행 중','states.RUNNING',data.states.RUNNING,scope);
    else{const empty=section('지금 진행 중','running-empty');empty.lastChild.innerHTML='<div class="calm-empty"><span class="empty-orbit">✓</span><strong>현재 실행 중인 작업이 없습니다.</strong><span>새 요청이나 예약된 Workflow가 시작되면 여기에 표시됩니다.</span></div>';focus.append(empty);}
    if(data.states.QUEUED.total)addCollection(focus,'실행 대기','states.QUEUED',data.states.QUEUED,scope,true);
    if(data.states.PAUSED.total)addCollection(focus,'일시 정지','states.PAUSED',data.states.PAUSED,scope,true);
    attention.innerHTML='<div class="section-heading"><h2>확인할 항목</h2><span class="muted">다음 행동</span></div>';
    let needsAttention=false;
    for(const [title,key,page] of [['실패','states.FAILED',data.states.FAILED],['복구 필요','states.RECOVERY_REQUIRED',data.states.RECOVERY_REQUIRED],['승인 대기','approvals',data.approvals]])if(page.total){needsAttention=true;addCollection(attention,title,key,page,scope);}
    if(!needsAttention)attention.insertAdjacentHTML('beforeend','<p class="all-clear"><span>✓</span> 지금 확인할 항목이 없습니다.</p>');
    const upcoming=disclosure(attention,`예정 실행 · ${data.scheduled.total}`,'focus-schedule',data.scheduled.total>0);operationRows(upcoming,data.scheduled.items.slice(0,3));if(data.scheduled.total>3)addCollection(upcoming,'전체 일정','scheduled',data.scheduled,scope,true);
    if(data.context_warnings.total)addCollection(attention,'Context 경고','context_warnings',data.context_warnings,scope,true);
    const limits=data.runtime.provider.rate_limits||{},used=limits.status==='AVAILABLE'?limits.data?.primary?.primary?.used_percent:null;
    const runtime=disclosure(attention,`Runtime · Usage · ${used==null?limits.status==='STALE'?'이전 관측값':'미관측':used+'% 사용'}`,'dashboard-runtime');runtimeView(runtime,data);
    const recent=section('최근 Work','dashboard-works');recent.classList.add('recent-work-section');root.append(recent);recent.lastChild.className='work-card-grid';
    const works=(state.dashboard?.works||[]).filter(w=>workEnabled(w)&&(!state.category||w.category_id===state.category));
    for(const w of works.slice(0,6)){const card=wfButton('',()=>selectWork(w.id));card.className='work-card';const cat=state.dashboard.categories.find(c=>c.id===w.category_id);card.innerHTML=`<span class="work-card-icon">${escape(w.name.slice(0,1))}</span><strong>${escape(w.name)}</strong><small>${escape(cat?.name||'Work')}${w.archived?' · 보관됨':''}</small><span class="work-card-arrow">↗</span>`;recent.lastChild.append(card);}
    if(!works.length)recent.lastChild.innerHTML='<p class="empty">새 작업을 만들어 시작하세요.</p>';
    if(works.length>6)recent.append(wfButton('모든 Work 찾기',()=>{$('nav-search').focus();}));
    const history=disclosure(root,'최근 Workflow · 실행 기록','dashboard-history');addCollection(history,'Workflow','workflows',data.workflows,scope);addCollection(history,'실행','recent_runs',data.recent_runs,scope);
    const artifacts=disclosure(root,`최근 결과물 · ${data.recent_artifacts.total}`,'dashboard-artifacts');
    let artifactPage=data.recent_artifacts;
    function artifactRows(items){for(const a of items){const row=document.createElement('div');row.className='row';row.innerHTML=artifactRow(a);row.querySelector('button').disabled=!workEnabled(state.dashboard?.works.find(w=>w.id===a.work_id));row.querySelector('button').onclick=busy(async()=>{if(state.work?.id!==a.work_id)await selectWork(a.work_id);if(state.work?.id!==a.work_id)return;tab('artifacts');await preview(a);});artifacts.append(row);}}
    artifactRows(artifactPage.items);if(!artifactPage.total)artifacts.innerHTML='<p class="empty">아직 결과물이 없습니다.</p>';
    if(artifactPage.has_more){const more=wfButton('더 보기',async()=>{const next=await api('/operations/dashboard?'+new URLSearchParams({...scope,limit:20,offset:artifactPage.offset+artifactPage.limit}));artifactPage=next.recent_artifacts;artifactRows(artifactPage.items);more.hidden=!artifactPage.has_more;});artifacts.append(more);}
    const reviews=disclosure(root,'최근 Review / Diff','dashboard-tools');operationRows(reviews,data.recent_runs.items.filter(r=>r.title==='AI Review'));
    for(const entry of window.workTools?.recentDiffs()||[]){if(state.category&&entry.categoryId!==state.category)continue;reviews.append(wfButton(`${entry.workName} · Diff 조회 · ${date(entry.at)}`,async()=>{if(state.work?.id!==entry.workId)await selectWork(entry.workId);if(state.work?.id===entry.workId)tab('tools');},!workEnabled(state.dashboard?.works.find(w=>w.id===entry.workId))));}
    const hint=document.createElement('p');hint.className='muted';hint.textContent='Review는 최근 실행 기준, Diff 조회 기록은 현재 세션 기준입니다.';reviews.append(hint);
    const totals=disclosure(root,'전체 운영 상태','dashboard-totals');totals.classList.add('summary-strip');
    for(const [key,value] of Object.entries(data.summary)){const item=document.createElement('span');item.innerHTML=`${escape(status(key))} <strong>${value.total}</strong>`;item.title=Object.entries(value.by_entity_type).map(([type,n])=>`${type}: ${n}`).join(', ');totals.append(item);}
    const note=document.createElement('p');note.className='muted';note.textContent='서버 항목별 집계입니다. Workflow와 실행이 같은 사건을 나타낼 수 있어 합산하지 않습니다.';totals.append(note);
    $('dashboard-updated').textContent='조회 시각 '+date(new Date().toISOString())+' · 자동 갱신';
    if(sameScope)for(const el of root.querySelectorAll('[data-disclosure]'))if(expanded.has(el.dataset.disclosure))el.open=expanded.get(el.dataset.disclosure);
    UI.enhance(root);
  }

  async function refreshWorkOperations(){
    if(!state.work)return;const id=state.work.id, epoch=++workEpoch;
    const data=await api('/operations/dashboard?'+new URLSearchParams({work_id:id,limit:20}));
    if(state.work?.id!==id || epoch!==workEpoch)return;
    const box=$('work-summary'),wasOpen=$('work-other-states')?.closest('details').open;box.replaceChildren();const strip=document.createElement('div');strip.className='pulse-strip compact';
    for(const [key,target] of [['RUNNING','execution'],['WAITING_APPROVAL','review'],['SCHEDULED','schedule']]){const b=wfButton('',()=>tab(target));b.innerHTML=`<span>${status(key)}</span><strong>${data.summary[key].total}</strong><span class="pulse-arrow">↗</span>`;strip.append(b);}box.append(strip);
    for(const key of ['RECOVERY_REQUIRED','FAILED'])if(data.summary[key].total){const p=document.createElement('div');p.className='warning-banner';p.textContent=`${status(key)} ${data.summary[key].total}건`;box.append(p);operationRows(p,data.states[key].items.slice(0,3));}
    if(data.states.RUNNING.total){const active=document.createElement('div');box.append(active);operationRows(active,data.states.RUNNING.items);}
    const rest=disclosure(box,'대기 · Context · 기타 운영 상태','work-other-states',wasOpen);
    for(const key of ['QUEUED','PAUSED','CONTEXT_WARNING']){const p=document.createElement('p');p.textContent=`${status(key)} ${data.summary[key].total}`;rest.append(p);if(data.states[key].total)operationRows(rest,data.states[key].items);}
    $('work-state').textContent=state.work.archived?'보관됨':`진행 ${data.summary.RUNNING.total} · 대기 ${data.summary.QUEUED.total} · 승인 ${data.summary.WAITING_APPROVAL.total}`;
  }
  function selectionSummary(){const source=selectedContext().length, artifacts=window.workflows?.selectedLibrary().length||0;const resources=$('conversation-resources')?.querySelectorAll('input:checked').length||0;$('selected-materials-summary').textContent=`선택 자료 ${source} · 결과물 ${artifacts} · Resource ${resources}${$('conversation-pack')?.value?' · Context Pack 선택됨':''}`;window.uiPresentation?.selectionChanged();}
  function groupMaterials(){
    const source=$('context-list'), lib=$('library-context-list');source.classList.remove('context-list');
    for(const [container,groups] of [[source,[['WORKSPACE','Workspace'],['SHARED','Shared'],['EXTERNAL','External'],['LEGACY','Workspace · 기존 자료']]],[lib,[['SHARED','Shared'],['PREVIOUS','Previous Artifact']]]]){
      const rows=[...container.querySelectorAll('.context-item')];container.replaceChildren();
      for(const [key,label] of groups){const matched=rows.filter(row=>row.dataset.sourceGroup===key);if(!matched.length&&(key==='LEGACY'||key==='WORKSPACE'&&rows.some(row=>row.dataset.sourceGroup==='LEGACY')))continue;const section=document.createElement('section');section.className='material-group';section.dataset.materialGroup=key;section.innerHTML=`<h3>${label}</h3>`;for(const row of matched)section.append(row);if(!matched.length)section.append(UI.empty('등록된 자료가 없습니다.','자료 추가 버튼에서 이 출처의 파일을 연결하세요.'));container.append(section);}
    }
    selectMaterialTab(materialTab);
  }
  function selectMaterialTab(key){materialTab=key;
    for(const group of document.querySelectorAll('[data-material-group]'))group.hidden=group.dataset.materialGroup!==key&&!(key==='WORKSPACE'&&group.dataset.materialGroup==='LEGACY');
    $('material-context-packs').hidden=key!=='PACK';$('material-resources').hidden=key!=='RESOURCE';
    for(const button of $('material-tabs').children){button.classList.toggle('active',button.dataset.materialTab===key);button.setAttribute('aria-pressed',String(button.dataset.materialTab===key));}
  }
  const materialTabs=document.createElement('nav');materialTabs.id='material-tabs';materialTabs.className='tabs secondary-tabs';materialTabs.setAttribute('aria-label','자료 출처');$('context-list').before(materialTabs);
  for(const [key,label] of [['WORKSPACE','Workspace'],['SHARED','Shared'],['EXTERNAL','External'],['PREVIOUS','이전 결과물'],['PACK','Context Pack'],['RESOURCE','결정 · Resource']]){const b=wfButton(label,()=>selectMaterialTab(key));b.dataset.materialTab=key;materialTabs.append(b);}
  function filterNavigation(){const q=$('nav-search')?.value.trim().toLowerCase()||'';for(const group of $('categories').querySelectorAll('.nav-group')){let found=group.dataset.search.includes(q);for(const link of group.querySelectorAll('.work-nav')){link.hidden=!!q&&!link.dataset.search.includes(q)&&!group.dataset.search.includes(q);if(!link.hidden)found=true;}group.hidden=!found;}const inactive=$('inactive-navigation');if(inactive){inactive.hidden=![...inactive.querySelectorAll('.nav-group')].some(g=>!g.hidden);if(q&&!inactive.hidden)inactive.open=true;}}
  $('nav-search').oninput=filterNavigation;
  document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();$('nav-search').focus();$('nav-search').select();}if(event.key==='Escape'&&document.activeElement===$('nav-search')){$('nav-search').value='';filterNavigation();$('nav-search').blur();}});
  async function workLoaded(detail,preserve){
    $('work-category').textContent=state.dashboard.categories.find(c=>c.id===detail.work.category_id)?.name||'Category';
    $('breadcrumb').textContent='CONTROL CENTER / WORK';navigation();groupMaterials();
    if(!preserve)setRoute();
    rows('work-recent-runs',detail.runs.slice(0,5),runRow,r=>selectRun(r.id));rows('work-recent-artifacts',detail.artifacts.slice(0,5),artifactRow,preview);
    renderActivity(detail);
    wfOptions($('schedule-workflow'),wfState.definitions.filter(d=>d.enabled).map(d=>[d.id,d.name]));$('schedule-create').disabled=!$('schedule-workflow').value;
    selectionSummary();await refreshWorkOperations();window.uiPresentation?.workLoaded();
  }
  function renderActivity(detail){
    rows('activity-list',detail.runs,r=>runRow({...r,instruction:detail.requests.find(q=>q.id===r.request_id)?.instruction}),r=>selectRun(r.id));
    const activityWorkflow=UI.disclosure(`Workflow 활동 · ${$('workflow-history').querySelectorAll('button').length}개`,null,{id:'activity-workflows'});
    for(const button of $('workflow-history').querySelectorAll('button'))activityWorkflow.append(wfButton(button.textContent,()=>button.click()));
    if(activityWorkflow.children.length>1)$('activity-list').append(activityWorkflow);
  }
  function runUpdated(detail){
    if(activeTab==='execution')setRoute('/run/'+encodeURIComponent(detail.run.id));
    const manifest=$('manifest');const data=JSON.parse(manifest.textContent||'{}');data.runtime={run_id:detail.run.id,thread_id:detail.run.thread_id,turn_id:detail.run.turn_id};manifest.textContent=JSON.stringify(data,null,2);
  }
  async function restoreRoute(){
    ready=true;const hash=location.hash.slice(1);restoring=true;
    try{
      if(hash.startsWith('work/')){const parts=hash.split('/').map(decodeURIComponent);if(state.work?.id!==parts[1])await selectWork(parts[1]);if(state.work?.id!==parts[1])return;tab(parts[2],false);if(parts[3]==='run'&&parts[4])await selectRun(parts[4]);if(parts[3]==='workflow'&&parts[4])await wfSelectRun(parts[4]);}
      else if(hash.startsWith('category/'))await showCategory(decodeURIComponent(hash.split('/')[1]));
      else if(hash.startsWith('management/category/'))await showCategory(decodeURIComponent(hash.split('/')[2]),true);
      else if(hash==='management')await showManagement();
      else{state.category=new URLSearchParams(hash.split('?')[1]||'').get('category');await showOverview();}
    }catch(error){state.category=null;showOverview();history.replaceState(null,'','#dashboard');notice('이전 화면을 열 수 없어 Dashboard로 이동했습니다. '+error.message);}finally{restoring=false;setRoute();}
  }
  window.addEventListener('popstate',()=>restoreRoute().catch(e=>notice(e.message)));
  $('artifact-register').onclick=busy(async()=>{await window.storageUI.open();$('material-as-result').checked=true;});
  $('schedule-create').onclick=busy(async()=>{await wfSelectDefinition($('schedule-workflow').value);window.controlCenter.tab('schedule');window.workflowOperations.openSchedule();});
  $('review-refresh').onclick=busy(()=>window.workflowOperations.loadWork(state.work.id));
  const taskTabs=[['basic','기본 설정'],['input','입력'],['output','출력'],['conditions','실행 조건'],['settings','Execution Settings Override']];
  function taskTab(name){for(const panel of document.querySelectorAll('[data-task-panel]'))panel.hidden=panel.dataset.taskPanel!==name;for(const button of $('task-tabs').children){button.classList.toggle('active',button.dataset.taskTab===name);button.setAttribute('aria-selected',String(button.dataset.taskTab===name));}}
  for(const [key,label] of taskTabs){const b=wfButton(label,()=>taskTab(key));b.dataset.taskTab=key;$('task-tabs').append(b);}taskTab('basic');
  async function refresh(){await dashboard();if(state.work){await refreshWorkOperations();if(['schedule','review','workflow'].includes(activeTab)&&!document.activeElement?.closest('#approval-inbox'))await window.workflowOperations.loadWork(state.work.id);await window.requestQueue?.load(state.work.id);if(activeTab==='tools')await window.workTools?.refresh();}}

  tab('overview',false);
  return {showCategory,showManagement,metadataUpdated,workEnabled,status,tab,groupMaterials,selectMaterialTab,navigation,showDashboard,renderDashboard,workLoaded,runUpdated,restoreRoute,refresh,refreshRuntime:()=>{freshRuntime=true;},selectionSummary,taskTab,openItem,workflowSelected:id=>{tab('workflow',false);setRoute('/workflow/'+encodeURIComponent(id));}};
})();
