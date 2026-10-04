'use strict';
// One profile editor is shared by runs, tasks, branches and sparse defaults.
window.executionSettings = (() => {
  let base = null, editing = null, previewGeneration = 0;
  function mount(container, prefix) {
    container.classList.add('profile-editor');
    container.innerHTML = [['model','Model'],['reasoning','Reasoning'],['personality','Personality'],['permission','Permission'],['speed','Speed / Fast']]
      .map(([key,label]) => `<label>${label}<select id="${prefix}${key}" ${key==='personality'?'disabled':''}>${key==='personality'?'<option>현재 Runtime 미지원</option>':''}</select>${!prefix&&key!=='personality'?`<small id="resolved-${key}" class="resolved-value"></small>`:''}</label>`).join('');
  }
  for (const container of document.querySelectorAll('[data-execution-settings]')) mount(container, container.dataset.executionSettings);
  const field = (prefix, key) => document.getElementById(prefix + key);
  function options(select, entries, value) {
    select.replaceChildren();
    for (const [id, label] of entries) {
      const item = document.createElement('option'); item.value = id; item.textContent = label; select.append(item);
    }
    select.value = value ?? '';
  }
  function modelFor(prefix) {
    const parent = prefix === 'defaults-' ? editing?.parent : base;
    const id = field(prefix, 'model')?.value || parent?.model;
    return state.models.find(m => m.id === id) || state.models.find(m => m.default);
  }
  function extras(prefix, profile = {}) {
    options(field(prefix, 'permission'), [['', '기본값 상속'], ['read-only', '읽기 전용 · read-only'],
      ['workspace-write', '쓰기 허용 · workspace-write']], profile.permission);
    speeds(prefix, profile.speed);
  }
  function speeds(prefix, value) {
    const select = field(prefix, 'speed'); if (!select) return;
    const previous = value === undefined ? select.value : value;
    options(select, [['', '기본값 상속'], ['default', 'Standard'],
      ...(modelFor(prefix)?.service_tiers || []).filter(t => t.id !== 'default').map(t => [t.id, t.name])], previous);
    if (select.selectedIndex < 0) select.value = '';
  }
  function reasoning(prefix, value) {
    options(field(prefix, 'reasoning'), [['', '기본값 상속'], ...(modelFor(prefix)?.reasoning || []).map(r => [r, r])], value);
    speeds(prefix);
  }
  function populate(prefix, profile = {}) {
    options(field(prefix, 'model'), [['', '기본값 상속'], ...state.models.map(m => [m.id, m.label])], profile.model);
    reasoning(prefix, profile.reasoning); extras(prefix, profile);
  }
  function read(prefix) {
    const result = {};
    for (const key of ['model', 'reasoning', 'permission', 'speed']) {
      const value = field(prefix, key)?.value; if (value) result[key] = value;
    }
    return result;
  }
  async function refresh(work, preserve) {
    const resolved = await api('/execution-settings/resolve', {method:'POST', body:{work_id:work.id}});
    if (state.work?.id !== work.id) return;
    base = resolved;
    state.inheritedProfile = resolved;
    if (!preserve) populate('', {});
    await preview();
  }
  async function preview(){
    if(!state.work)return;
    const id=state.work.id,generation=++previewGeneration;
    const input=read(''),query=($('request-condition')?.value||'NOW')==='NOW'&&!!document.querySelector('[data-conversation-action="QUERY"].active');
    if(query)input.permission=document.getElementById('query-write')?.checked?'workspace-write':'read-only';
    const resolved=await api('/execution-settings/resolve',{method:'POST',body:{work_id:id,execution_profile:input}});
    if(generation!==previewGeneration||state.work?.id!==id)return;
    state.resolvedProfile=resolved;
    for(const key of ['model','reasoning','permission','speed']){
      const label=document.getElementById('resolved-'+key);if(label)label.textContent='실제 적용: '+resolved[key]+(key==='permission'&&query?' · 질문 모드':'');
      const inherited=field('',key)?.querySelector('option[value=""]');if(inherited&&base)inherited.textContent='기본값 상속 · '+base[key];
    }
    const summary=document.getElementById('execution-inheritance');summary.className='resolved-profile';
    summary.innerHTML=`<span class="metadata-label">이번 요청의 실제 실행 설정</span><span class="resolved-profile-values">${['model','reasoning','permission','speed'].map(key=>`<span>${escape(resolved[key])}</span>`).join('')}</span>`;
    window.storageUI?.permissionView();return resolved;
  }
  async function openDefaults(scope) {
    const id = scope === 'GLOBAL' ? 'global' : scope === 'CATEGORY' ? state.work.category_id : state.work.id;
    const [profile, global, category] = await Promise.all([
      api(`/execution-settings/defaults/${scope}/${id}`),
      scope !== 'GLOBAL' ? api('/execution-settings/defaults/GLOBAL/global') : {},
      scope === 'WORK' ? api(`/execution-settings/defaults/CATEGORY/${state.work.category_id}`) : {}
    ]);
    editing = {scope, id, parent:{...global,...category}}; populate('defaults-', profile);
    document.getElementById('execution-defaults-title').textContent = `${scope} 실행 기본값`;
    document.getElementById('execution-defaults').showModal();
  }
  async function saveDefaults() {
    await api(`/execution-settings/defaults/${editing.scope}/${editing.id}`, {method:'PUT', body:read('defaults-')});
    document.getElementById('execution-defaults').close(); await refresh(state.work, true);
  }
  function bind() {
    for (const scope of ['GLOBAL', 'CATEGORY', 'WORK']) {
      document.getElementById('execution-default-' + scope).onclick = () => openDefaults(scope).catch(e => notice(e.message));
    }
    document.getElementById('execution-defaults-save').onclick = () => saveDefaults().catch(e => notice(e.message));
    document.getElementById('execution-defaults-close').onclick = () => document.getElementById('execution-defaults').close();
    field('defaults-', 'model').onchange = () => reasoning('defaults-');
    document.addEventListener('change',event=>{
      if(['model','reasoning','permission','speed','query-write','request-condition'].includes(event.target.id))preview().catch(error=>notice(error.message));
    });
    document.addEventListener('click',event=>{if(event.target.closest('[data-conversation-action]'))queueMicrotask(()=>preview().catch(error=>notice(error.message)));});
  }
  return {read, populate, reasoning, speeds, extras, refresh, preview, bind, mount};
})();
