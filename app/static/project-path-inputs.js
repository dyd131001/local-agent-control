'use strict';
window.projectPathInputs=(()=>{
  let workId=null,saved=null,draft=null,scope=null,activeRoot=null,onApply=null,registeredRoots=[];
  let directory='.',pageOffset=0,treeEpoch=0,previewEpoch=0,previewed=null,shown=[],archiveIds=[];
  const copy=value=>structuredClone(value);
  function fromContext(value={}){
    let read_paths=[...(value.read_paths||[])],legacy_patterns=[...(value.legacy_patterns||value.path_patterns||[])];
    if(!read_paths.length&&legacy_patterns.length&&legacy_patterns.every(pattern=>pattern==='**/*'||(pattern.endsWith('/**')&&!/[*?\[\]]/.test(pattern.slice(0,-3))))){
      read_paths=legacy_patterns.map(pattern=>pattern==='**/*'?'.':pattern.slice(0,-3));legacy_patterns=[];
    }
    const empty=!read_paths.length&&!legacy_patterns.length,explicit='read_paths' in value||'path_patterns' in value,search_paths=[...(value.search_paths||[])];
    return {read_paths:empty&&!explicit?['.']:read_paths,search_paths:empty&&!explicit||(!search_paths.length&&read_paths.includes('.'))?['.']:search_paths,
      legacy_patterns,external_scopes:(value.external_scopes||[]).map(item=>({root:item.root,read_paths:[...(item.read_paths||[])],search_paths:[...(item.search_paths||[])]}))};
  }
  async function loadWork(id,linked){if(workId!==id){workId=id;saved=null;registeredRoots=[];}$('project-path-inputs').hidden=!linked;renderMaterialSummary();
    try{const [found,capability]=await Promise.all([api(`/works/${id}/external-roots`),api('/runtime/read-root-capability')]);if(workId===id){
      registeredRoots=found;if($('project-scope-picker').open)renderRoots();
      if(!capability.supported){for(const target of ['project-picker-runtime-warning','wf-draft-scope-warning','workflow-path-scope-warning']){
        const node=$(target);if(node)node.textContent=`실행 차단: ${capability.reason}`;
      }}
    }}catch(error){if(workId===id)notice(error.message||String(error));}}
  function current(id){return id===workId&&saved?{...copy(saved.scope),archive_artifact_ids:[...saved.artifactIds]}:null;}
  function renderMaterialSummary(){
    const box=$('project-path-summary');
    if(!saved){box.textContent='기본 읽기·탐색 범위: 연결된 프로젝트 전체 · 미리보기 전';return;}
    const {scope:choice,results,artifactIds}=saved;
    box.textContent=`프로젝트 ${1+choice.external_scopes.length}곳 · 읽기 포함 ${results.reduce((n,r)=>n+r.read_count,0)}개 · 탐색 후보 ${results.reduce((n,r)=>n+r.search_count,0)}개 · 묶음 Artifact ${artifactIds.length}개`;
  }
  function invalidate(){previewEpoch++;previewed=null;shown=[];$('project-picker-count').textContent='';$('project-picker-preview-list').textContent='';$('project-picker-preview-more').hidden=true;$('project-picker-apply').disabled=true;$('project-picker-error').hidden=true;}
  function fail(error){$('project-picker-error').textContent=error.message||String(error);$('project-picker-error').hidden=false;}
  function renderRoots(){
    const box=$('project-picker-roots');box.replaceChildren();
    const roots=[{root:null,label:`Primary Workspace · ${state.work?.linked_workspace_path||'연결 프로젝트'}`},
      ...registeredRoots.map(item=>({root:item.path,label:`External Root · ${item.path} · ${item.browse?'탐색 가능':'탐색 불가'} / ${item.read?'AI 읽기 가능':'AI 읽기 불가'}`})),
      ...draft.external_scopes.filter(item=>!registeredRoots.some(root=>root.path===item.root)).map(item=>({root:item.root,label:`이전 작업 범위 · ${item.root} · Work 등록 필요`}))];
    for(const item of roots){
      const row=document.createElement('div');row.className='row';
      const registered=item.root?registeredRoots.find(value=>value.path===item.root):null;
      const button=wfButton(item.label,()=>switchRoot(item.root),!!item.root&&!registered?.browse);button.classList.toggle('selected',item.root===activeRoot);row.append(button);
      if(item.root){const registered=registeredRoots.find(value=>value.path===item.root);
        if(!registered)row.append(wfButton('Work Root 등록',async()=>{const selected=draft.external_scopes.find(value=>value.root===item.root);
          registeredRoots.push(await api(`/works/${workId}/external-roots`,{method:'POST',body:{path:item.root,browse:true,read:!!selected?.read_paths.length}}));renderRoots();}));
        else row.append(wfButton(registered.read?'AI 읽기 해제':'AI 읽기 허용',async()=>{
          const changed=await api(`/works/${workId}/external-roots`,{method:'POST',body:{path:item.root,browse:registered.browse,read:!registered.read,ignore_patterns:registered.ignore_patterns||[]}});
          Object.assign(registered,changed);if(!changed.read){const selected=draft.external_scopes.find(value=>value.root===item.root);if(selected)selected.read_paths=[];}
          invalidate();renderRoots();if(activeRoot===item.root)renderSelections();
        }));
        if(registered)row.append(wfButton(registered.browse?'탐색 해제':'탐색 허용',async()=>{
          const changed=await api(`/works/${workId}/external-roots`,{method:'POST',body:{path:item.root,browse:!registered.browse,read:registered.read,ignore_patterns:registered.ignore_patterns||[]}});
          Object.assign(registered,changed);if(!changed.browse){const selected=draft.external_scopes.find(value=>value.root===item.root);if(selected)selected.search_paths=[];if(activeRoot===item.root)switchRoot(null);}
          invalidate();renderRoots();
        }));
        if(draft.external_scopes.some(value=>value.root===item.root))row.append(wfButton('작업에서 제외',()=>{draft.external_scopes=draft.external_scopes.filter(value=>value.root!==item.root);if(activeRoot===item.root)switchRoot(null);else renderRoots();invalidate();}));
      }
      box.append(row);
    }
    $('project-picker-active-root').textContent=activeRoot?`탐색 중: ${activeRoot}`:`탐색 중: ${state.work?.linked_workspace_path||'Work 프로젝트'}`;
    $('project-picker-ignore').value=activeRoot?(registeredRoots.find(item=>item.path===activeRoot)?.ignore_patterns||[]).join('\n'):'';
    $('project-picker-ignore-control').hidden=!activeRoot;
    $('project-picker-archive').hidden=!activeRoot||!registeredRoots.find(item=>item.path===activeRoot)?.read;
    $('project-picker-archive-status').textContent=archiveIds.length?`이번 선택에서 만든 묶음 Artifact ${archiveIds.length}개`:activeRoot&&!registeredRoots.find(item=>item.path===activeRoot)?.read?'묶음 Artifact를 만들려면 이 Root의 AI 읽기 권한을 허용하세요.':'선택 파일을 경로 구조 그대로 하나의 ZIP Artifact로 묶을 수 있습니다.';
  }
  function renderSelections(){
    for(const [key,id] of [['read_paths','project-picker-read'],['search_paths','project-picker-search']]){
      const box=$(id);box.replaceChildren();
      if(key==='read_paths'&&(scope.legacy_patterns||[]).length){const note=document.createElement('p');note.textContent='기존 저장 범위 · 미리보기로 포함 파일을 확인하고 탐색기 선택으로 바꿀 수 있습니다.';box.append(note);}
      for(const path of scope[key]){const row=document.createElement('div');row.className='row';const name=document.createElement('span');name.textContent=path==='.'?'폴더 전체':path;row.append(name,wfButton('제거',()=>{scope[key]=scope[key].filter(value=>value!==path);invalidate();renderSelections();renderTree();}));box.append(row);}
      if(!box.children.length)box.textContent=key==='read_paths'&&activeRoot?'읽기 권한 없음 · 탐색 후 Artifact로 고정 가능':key==='read_paths'?'선택 없음':'선택 없음';
    }
  }
  function renderTree(){
    if(!scope)return;
    for(const row of $('project-picker-list').querySelectorAll('[data-project-path]')){
      const checkbox=row.querySelector('input[type="checkbox"]');if(checkbox)checkbox.checked=scope[$('project-picker-mode').value].includes(row.dataset.projectPath);
    }
  }
  function withinRead(path){return !!activeRoot&&!scope.read_paths.length||scope.read_paths.includes('.')||scope.read_paths.some(read=>path===read||path.startsWith(read+'/'));}
  function treeUrl(path,offset){return `/works/${workId}/project-tree?path=${encodeURIComponent(path)}&offset=${offset}&limit=100${activeRoot?'&external_root='+encodeURIComponent(activeRoot):''}`;}
  function entryNode(entry){
    const item=document.createElement('div');item.className='project-tree-item';
    const row=document.createElement('div');row.className='row';row.dataset.projectPath=entry.path;
    if(entry.kind==='DIRECTORY'||entry.kind==='FILE'){
      const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=scope[$('project-picker-mode').value].includes(entry.path);
      checkbox.setAttribute('aria-label',`${entry.path} 범위 선택`);
      checkbox.onchange=()=>{const key=$('project-picker-mode').value;if(activeRoot&&key==='read_paths'&&checkbox.checked&&!registeredRoots.find(item=>item.path===activeRoot)?.read){checkbox.checked=false;fail(new Error('먼저 External Root의 AI 읽기 권한을 허용하세요.'));return;}if(key==='search_paths'&&checkbox.checked&&!withinRead(entry.path)&&!(scope.legacy_patterns||[]).length){checkbox.checked=false;fail(new Error('탐색 범위는 읽기 권한 범위 안에서 선택하세요.'));return;}if(key==='read_paths')scope.legacy_patterns=[];scope[key]=checkbox.checked?[...new Set([...scope[key],entry.path])]:scope[key].filter(value=>value!==entry.path);invalidate();renderSelections();};
      row.append(checkbox);
      if(entry.kind==='DIRECTORY'){
        row.append(wfButton(`📁 ${entry.name}`,()=>navigate(entry.path)));
        row.append(wfButton('하위 펼치기',async()=>{
          let children=item.querySelector(':scope > .project-tree-children');if(children){children.remove();return;}
          children=document.createElement('div');children.className='project-tree-children';children.textContent='폴더를 읽는 중…';item.append(children);
          try{await expandDirectory(entry.path,children);}catch(error){children.remove();fail(error);}
        }));
      }else{const name=document.createElement('span');name.textContent=`📄 ${entry.name}`;row.append(name);}
    }else{const label=document.createElement('span');label.textContent=`${entry.kind==='SYMLINK'?'↗ 심볼릭 링크 · 선택 불가':'특수 파일 · 선택 불가'} ${entry.name}`;row.append(label);}
    item.append(row);return item;
  }
  async function expandDirectory(path,container,offset=0){
    const root=activeRoot,data=await api(treeUrl(path,offset));if(root!==activeRoot||!container.isConnected)return;
    if(!offset)container.replaceChildren();for(const entry of data.entries)container.append(entryNode(entry));
    if(data.has_more)container.append(wfButton('다음 100개 보기',()=>{container.lastElementChild?.remove();expandDirectory(path,container,offset+100).catch(fail);}));
    else if(!data.total)container.textContent='비어 있는 폴더';
  }
  async function navigate(path='.',offset=0){
    const request=++treeEpoch,root=activeRoot;directory=path;pageOffset=offset;$('project-picker-list').textContent='폴더를 읽는 중…';
    const data=await api(treeUrl(path,offset));if(request!==treeEpoch||root!==activeRoot||!$('project-scope-picker').open)return;
    const crumbs=$('project-picker-breadcrumb');crumbs.replaceChildren();for(const item of data.breadcrumbs)crumbs.append(wfButton(item.name,()=>navigate(item.path)));
    const list=$('project-picker-list');list.replaceChildren();for(const entry of data.entries)list.append(entryNode(entry));
    if(!data.entries.length)list.textContent='이 폴더는 비어 있습니다.';
    $('project-picker-page').textContent=`${data.total}개 항목 · ${data.total?offset+1:0}–${Math.min(offset+data.entries.length,data.total)}`;
    $('project-picker-prev').disabled=offset===0;$('project-picker-next').disabled=!data.has_more;
  }
  function previewBody(choice,root,kind='SEARCH',offset=0,limit=200){return {read_paths:[...(choice.read_paths||[])],search_paths:[...(choice.search_paths||[])],
    legacy_patterns:[...(choice.legacy_patterns||[])],external_root:root,discovery_only:!!root&&!choice.read_paths.length,list_kind:kind,offset,limit};}
  async function preview(offset=0){
    if(!activeRoot&&!scope.read_paths.length&&!(scope.legacy_patterns||[]).length)throw new Error('Work 읽기 권한 범위를 선택하세요.');
    if(activeRoot&&!scope.search_paths.length)throw new Error('외부 폴더의 탐색 범위를 선택하세요.');
    const choice=copy(scope),root=activeRoot,kind=$('project-picker-list-kind').value,request=++previewEpoch;
    if(!offset){shown=[];$('project-picker-count').textContent='선택 결과를 확인하는 중…';$('project-picker-apply').disabled=true;}
    const result=await api(`/works/${workId}/project-scopes/preview`,{method:'POST',body:previewBody(choice,root,kind,offset)});
    if(request!==previewEpoch||root!==activeRoot||!$('project-scope-picker').open)return;
    previewed={choice,root,result};shown=offset?[...shown,...result.paths]:result.paths;
    $('project-picker-count').textContent=`읽기 포함 ${result.read_count}개 · 탐색 후보 ${result.search_count}개 · 읽기에서 제외 ${result.excluded_count}개 · 따라가지 않는 링크 ${result.symlink_count}개`;
    $('project-picker-preview-list').textContent=shown.join('\n')||'해당 경로가 없습니다.';
    $('project-picker-preview-more').hidden=!result.has_more;
    $('project-picker-apply').disabled=!result.search_count||(!activeRoot&&!result.read_count);
    $('project-picker-error').hidden=true;
  }
  async function previewAll(){
    const choices=[{root:null,choice:draft},...draft.external_scopes.map(choice=>({root:choice.root,choice}))];
    return Promise.all(choices.map(item=>api(`/works/${workId}/project-scopes/preview`,{method:'POST',
      body:previewBody(item.choice,item.root,item.root&&!registeredRoots.find(root=>root.path===item.root)?.browse?'READ':'SEARCH',0,1)})));
  }
  function switchRoot(root){
    if(root&&!registeredRoots.find(item=>item.path===root)?.browse)throw new Error('이 Root에는 탐색 권한이 없습니다.');
    if(root&&!draft.external_scopes.some(item=>item.root===root))draft.external_scopes.push({root,read_paths:[],search_paths:['.']});
    activeRoot=root;scope=root?draft.external_scopes.find(item=>item.root===root):draft;
    directory='.';pageOffset=0;$('project-picker-mode').value=root?'search_paths':'read_paths';$('project-picker-list-kind').value=root?'SEARCH':'READ';
    invalidate();renderRoots();renderSelections();navigate('.').catch(fail);
  }
  async function open(initial={},apply){
    if(!state.work?.linked_workspace_path)throw new Error('연결된 프로젝트가 없습니다.');
    registeredRoots=await api(`/works/${workId}/external-roots`);
    draft=fromContext(initial);archiveIds=[...(initial.archive_artifact_ids||[])];onApply=apply;
    $('project-scope-picker').showModal();switchRoot(null);
  }
  action('project-path-open',()=>open(saved?{...saved.scope,archive_artifact_ids:saved.artifactIds}:{},(choice,results)=>{const {archive_artifact_ids, ...scopes}=choice;saved={scope:scopes,results,artifactIds:archive_artifact_ids};renderMaterialSummary();}));
  action('project-picker-add-root',async()=>{const result=await api('/storage/pick-folder',{method:'POST',body:{purpose:'EXTERNAL'}});if(!result.path)return;
    if(result.path===state.work?.linked_workspace_path){switchRoot(null);return;}
    if(!registeredRoots.some(item=>item.path===result.path))registeredRoots.push(await api(`/works/${workId}/external-roots`,{method:'POST',body:{path:result.path,browse:true,read:false}}));
    switchRoot(result.path);
  });
  action('project-picker-ignore-save',async()=>{if(!activeRoot)return;const existing=registeredRoots.find(item=>item.path===activeRoot);
    const patterns=$('project-picker-ignore').value.split('\n').map(value=>value.trim()).filter(Boolean);
    Object.assign(existing,await api(`/works/${workId}/external-roots`,{method:'POST',body:{path:activeRoot,browse:existing.browse,read:existing.read,ignore_patterns:patterns}}));
    invalidate();renderRoots();navigate('.').catch(fail);notice('이 Root의 제외 규칙을 저장했습니다.');
  });
  action('project-picker-whole',()=>{const key=$('project-picker-mode').value;if(activeRoot&&key==='read_paths'&&!registeredRoots.find(item=>item.path===activeRoot)?.read)throw new Error('먼저 External Root의 AI 읽기 권한을 허용하세요.');if(key==='search_paths'&&!activeRoot&&!scope.read_paths.includes('.'))throw new Error('먼저 프로젝트 전체를 읽기 권한 범위로 선택하세요.');if(key==='read_paths')scope.legacy_patterns=[];scope[key]=['.'];invalidate();renderSelections();renderTree();});
  action('project-picker-prev',()=>navigate(directory,Math.max(0,pageOffset-100)));
  action('project-picker-next',()=>navigate(directory,pageOffset+100));
  $('project-picker-mode').onchange=renderTree;
  $('project-picker-list-kind').onchange=()=>{invalidate();if(scope.search_paths.length||scope.read_paths.length||(scope.legacy_patterns||[]).length)preview().catch(fail);};
  action('project-picker-preview',()=>preview().catch(fail));
  action('project-picker-preview-more',()=>preview(shown.length).catch(fail));
  action('project-picker-archive',async()=>{if(!activeRoot||!scope.search_paths.length)throw new Error('묶을 외부 폴더 탐색 범위를 선택하세요.');
    if(!previewed||previewed.root!==activeRoot||JSON.stringify(previewed.choice)!==JSON.stringify(scope))throw new Error('현재 외부 폴더 범위를 먼저 미리 보세요.');
    const artifact=await api(`/works/${workId}/artifacts/folder`,{method:'POST',body:{root:activeRoot,paths:scope.search_paths}});
    archiveIds=[...new Set([...archiveIds,artifact.id])];renderRoots();notice(`${artifact.file_count}개 파일을 묶음 Artifact ${artifact.id}로 등록했습니다.`);
  });
  action('project-picker-apply',async()=>{if(!previewed||previewed.root!==activeRoot||JSON.stringify(previewed.choice)!==JSON.stringify(scope))throw new Error('변경한 범위를 다시 미리 보세요.');
    const results=await previewAll();onApply?.({...copy(draft),archive_artifact_ids:[...archiveIds]},results);$('project-scope-picker').close();});
  action('project-picker-close',()=>$('project-scope-picker').close());
  return {loadWork,current,open};
})();
