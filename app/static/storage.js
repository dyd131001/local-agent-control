'use strict';
const materialState={workId:null,path:'',selection:new Set(),external:[],generation:0,documentPath:'',documentFolder:'',documentGeneration:0};
function workspaceForm(){
  const linked=$('editor-workspace-kind').value==='LINKED';$('editor-new-workspace').hidden=linked;$('editor-existing-workspace').hidden=!linked;
  $('editor-root-selection').textContent=$('editor-workspace-root').value||'위치를 선택하세요.';
  $('editor-linked-selection').textContent=$('editor-linked-path').value||'선택한 폴더가 없습니다.';
  $('editor-workspace-preview').textContent=`생성 위치: ${$('editor-workspace-root').value.replace(/\/$/,'')}/${$('editor-workspace-folder').value||$('editor-name').value||'<폴더 이름>'}`;
}
async function pickFolder(input,purpose='WORKSPACE',button){
  if(button)button.disabled=true;
  try{const data=await api('/storage/pick-folder',{method:'POST',body:{purpose}});if(data.path){$(input).value=data.path;$(input).dispatchEvent(new Event('input',{bubbles:true}));}return data.path;}
  finally{if(button)button.disabled=false;}
}
function openWorkspace(){
  $('workspace-new-path').value=state.work.workspace_path||state.work.linked_workspace_path||state.work.path;
  $('workspace-new-selection').textContent=$('workspace-new-path').value;
  $('workspace-dialog-error').hidden=true;$('workspace-dialog').showModal();
}
function permissionView(){
  if(!state.work)return;
  const a=state.workspaceAccess,profile=state.resolvedProfile;
  const path=state.work.workspace_path||state.work.linked_workspace_path||state.work.path;
  $('workspace-compact-state').textContent=path.split('/').filter(Boolean).pop()+' · '+(profile?.permission||'권한 확인 중')+(a&&!a.writable?' · 쓰기 확인 필요':'');
  const access=$('workspace-file-access');
  access.innerHTML=a?[['읽기',a.readable],['쓰기 · OS',a.writable]].map(([name,ok])=>`<span class="access-badge ${ok?'available':'unavailable'}">${ok?'✓':'!'} ${name} ${ok?'가능':'불가'}</span>`).join(''):'확인 중…';
  $('workspace-resolved-permission').innerHTML=profile?`<strong>${profile.permission==='workspace-write'?'쓰기 허용':'읽기 전용'}</strong><code>${escape(profile.permission)}</code>`:'설정 확인 중…';
  const readOnly=profile?.permission==='read-only';
  const issue=a?.issue||(!a?'폴더 접근 상태를 확인하고 있습니다.':readOnly?'현재 요청의 권한은 읽기 전용입니다. 파일 생성이 필요하면 workspace-write를 선택하세요.':'');
  $('workspace-access-help').hidden=!issue;$('workspace-access-issue').textContent=issue;
  $('workspace-enable-write').hidden=!readOnly;
  $('directory').disabled=!a?.available;
  $('workspace-permission-guide').hidden=true;
  const permission=$('permission')?.querySelector('option[value=""]');if(permission&&state.inheritedProfile)permission.textContent=`기본값 상속 · ${state.inheritedProfile.permission}`;
}
async function access(work=state.work){
  if(!work)return;
  const id=work.id;
  try{const result=await api(`/works/${id}/workspace/access`);if(state.work?.id!==id)return;state.workspaceAccess=result;}
  catch(error){if(state.work?.id!==id)return;state.workspaceAccess={path:work.workspace_path||work.path,available:false,readable:false,writable:false,issue:'접근 상태를 확인할 수 없습니다. 권한 다시 확인으로 재시도하세요. '+error.message};}
  permissionView();
}
async function beforeExecute(){
  const id=state.work?.id;
  const [profile]=await Promise.all([window.executionSettings.preview(),access()]);
  if(state.work?.id!==id)throw new Error('작업이 변경되었습니다. 현재 Workspace에서 다시 실행하세요.');
  const query=($('request-condition')?.value||'NOW')==='NOW'&&!!document.querySelector('[data-conversation-action="QUERY"].active');
  const savesResults=!query||$('query-artifacts')?.checked;
  if(profile?.permission==='workspace-write'&&savesResults&&!state.workspaceAccess?.writable){
    $('workspace-panel').open=true;
    $('workspace-access-help').hidden=false;$('workspace-access-issue').textContent=state.workspaceAccess?.issue||'결과물을 저장할 쓰기 권한을 확인할 수 없습니다.';
    document.querySelector('.workspace-region').scrollIntoView({behavior:'smooth',block:'start'});
    throw new Error('Workspace에 결과물을 저장할 수 없습니다. 위의 폴더 선택·변경 또는 권한 확인을 사용하세요.');
  }
}
function materialError(message){$('material-error').hidden=!message;$('material-error-text').textContent=message;}
function breadcrumbs(id,path,open){
  const box=$(id);box.replaceChildren();box.append(wfButton('Workspace',()=>open('')));
  const parts=path.split('/').filter(Boolean);parts.forEach((part,index)=>{const slash=document.createElement('span');slash.textContent='/';box.append(slash,wfButton(part,()=>open(parts.slice(0,index+1).join('/'))));});
}
function selectionSummary(){
  const count=materialState.selection.size;
  $('material-selection-summary').replaceChildren(UI.status(count?'ACTIVE':'PENDING',`${count}개 파일 선택됨`),UI.help('폴더를 이동해도 선택은 유지됩니다.','선택 안내'));
}
function filterFiles(){
  const query=$('material-file-search').value.trim().toLowerCase();
  for(const row of $('material-file-list').querySelectorAll('[data-file-name]'))row.hidden=!row.dataset.fileName.includes(query);
}
async function materialBrowse(path=''){
  const id=materialState.workId,generation=++materialState.generation;materialError('');
  $('material-file-list').replaceChildren(UI.status('PENDING','파일을 불러오는 중…'));
  try{
    const data=await api(`/works/${id}/workspace/files?path=${encodeURIComponent(path)}`);
    if(materialState.workId!==id||generation!==materialState.generation||state.work?.id!==id)return;
    materialState.path=path;breadcrumbs('material-browser-path',path,materialBrowse);$('material-browser-up').disabled=!path;$('material-file-list').replaceChildren();
    for(const item of data.entries){
      if(item.is_directory){const button=wfButton('▸ '+item.name,()=>materialBrowse(item.path));button.className='file-folder';button.dataset.fileName=item.name.toLowerCase();$('material-file-list').append(button);}
      else{const label=UI.selectable({title:item.name,value:item.path,selected:materialState.selection.has(item.path),metadata:[['파일',item.path,'path']],onChange:checked=>{checked?materialState.selection.add(item.path):materialState.selection.delete(item.path);selectionSummary();}});label.classList.add('file-entry');label.dataset.fileName=item.name.toLowerCase();$('material-file-list').append(label);}
    }
    if(!data.entries.length)$('material-file-list').append(UI.empty('이 폴더에 선택할 파일이 없습니다.','상위 폴더나 다른 폴더를 선택하세요.'));
    if(data.entries.length===500)$('material-file-list').append(UI.help('첫 500개 항목을 표시합니다. 하위 폴더를 열어 파일을 선택하세요.','표시 범위'));
    filterFiles();selectionSummary();
  }catch(error){if(generation!==materialState.generation||state.work?.id!==id)return;$('material-file-list').replaceChildren();materialError('파일을 열 수 없습니다. '+error.message);await access();}
}
function documentTarget(){
  const name=$('material-document-name').value.trim();
  $('material-document-path').value=[materialState.documentFolder,name].filter(Boolean).join('/');
  $('document-target-preview').replaceChildren(UI.metadata([['저장 위치',$('material-document-path').value||'파일 이름을 입력하세요.','path']]));
}
async function documentBrowse(path=''){
  const id=materialState.workId,generation=++materialState.documentGeneration;
  try{
    const data=await api(`/works/${id}/workspace/files?path=${encodeURIComponent(path)}`);
    if(generation!==materialState.documentGeneration||state.work?.id!==id)return;
    materialState.documentPath=path;breadcrumbs('document-browser-path',path,documentBrowse);$('document-browser-up').disabled=!path;$('document-folder-list').replaceChildren();
    for(const item of data.entries.filter(i=>i.is_directory)){const button=wfButton('▸ '+item.name,()=>documentBrowse(item.path));button.className='file-folder';$('document-folder-list').append(button);}
    if(!$('document-folder-list').children.length)$('document-folder-list').append(UI.empty('하위 폴더가 없습니다.','현재 폴더를 저장 위치로 선택할 수 있습니다.'));
  }catch(error){if(generation!==materialState.documentGeneration||state.work?.id!==id)return;materialError('저장 폴더를 열 수 없습니다. '+error.message);}
}
function renderExternal(){
  $('material-picked-files').replaceChildren();
  for(const path of materialState.external){const row=UI.detail(path.split('/').pop());row.classList.add('picked-file');row.append(UI.metadata([['외부 파일',path,'path']]));const remove=wfButton('선택 해제',()=>{materialState.external=materialState.external.filter(p=>p!==path);renderExternal();});remove.setAttribute('aria-label',path.split('/').pop()+' 선택 해제');row.append(remove);$('material-picked-files').append(row);}
  if(!materialState.external.length)$('material-picked-files').append(UI.empty('연결할 외부 파일이 없습니다.','파일 선택 버튼으로 여러 파일을 추가할 수 있습니다.'));
}
async function materialType(){
  materialError('');const kind=$('material-kind').value;$('material-workspace').hidden=kind!=='WORKSPACE';$('material-markdown').hidden=kind!=='MARKDOWN';$('material-external').hidden=kind!=='EXTERNAL';$('material-result-label').hidden=kind==='MARKDOWN';
  if(kind==='WORKSPACE')await materialBrowse(materialState.path);if(kind==='MARKDOWN')await documentBrowse(materialState.documentPath);if(kind==='EXTERNAL')renderExternal();
}
async function materialOpen(kind='WORKSPACE',relative){
  materialState.workId=state.work.id;materialState.path='';materialState.selection.clear();materialState.external=[];materialState.documentPath='';
  const target=relative||'docs/note.md';materialState.documentFolder=target.split('/').slice(0,-1).join('/');
  $('material-kind').value=kind;$('material-content').value='';$('material-as-result').checked=false;$('material-file-search').value='';$('material-document-path').value=target;$('material-document-name').value=target.split('/').pop();$('material-usage').value=relative?.endsWith('AGENTS.md')?'AGENTS':'MARKDOWN';$('material-external-path').value='';
  documentTarget();for(const details of $('materials-dialog').querySelectorAll('details'))details.open=false;
  $('materials-dialog').showModal();await materialType();
}
async function materialSave(){
  const id=materialState.workId;if(state.work?.id!==id)throw new Error('현재 작업의 Workspace에서 다시 자료를 추가하세요.');
  const kind=$('material-kind').value,result=$('material-as-result').checked,added=[];materialError('');$('material-save').disabled=true;
  try{
    if(kind==='MARKDOWN'){
      if(!state.workspaceAccess?.writable){await access();if(!state.workspaceAccess?.writable)throw new Error('Workspace에 쓸 권한이 없습니다. 다른 폴더를 선택하거나 권한을 확인하세요.');}
      added.push(await api(`/works/${id}/documents`,{method:'POST',body:{relative_path:$('material-document-path').value,usage_type:$('material-usage').value,content:$('material-content').value}}));
    }else if(kind==='EXTERNAL'){
      const paths=materialState.external.length?materialState.external:[$('material-external-path').value.trim()].filter(Boolean);if(!paths.length)throw new Error('연결할 외부 파일을 선택하세요.');
      for(const path of paths)added.push(await api(`/works/${id}/${result?'artifacts/reference':'sources/external'}`,{method:'POST',body:result?{location_type:'EXTERNAL',path}:{path}}));
    }else{
      const paths=[...materialState.selection];if(!paths.length)throw new Error('Workspace 파일을 선택하세요.');
      if(result){for(const path of paths)added.push(await api(`/works/${id}/artifacts/reference`,{method:'POST',body:{location_type:'WORKSPACE',path}}));}else added.push(...await api(`/works/${id}/sources/import`,{method:'POST',body:{paths}}));
    }
    $('materials-dialog').close();if(state.work?.id===id){await selectWork(id,true);if(!result){const ids=new Set(added.map(source=>source.id));for(const input of $('context-list').querySelectorAll('input'))if(ids.has(input.value))input.checked=true;window.controlCenter?.selectionSummary();}}notice(result?'결과물로 등록했습니다.':'자료를 추가하고 실행 입력으로 선택했습니다.');
  }catch(error){materialError(error.message);await access();}finally{$('material-save').disabled=false;}
}
action('editor-workspace-kind',workspaceForm,'change');action('editor-workspace-root',workspaceForm,'input');action('editor-workspace-folder',workspaceForm,'input');action('editor-name',workspaceForm,'input');action('editor-linked-path',workspaceForm,'input');
action('editor-pick-folder',()=>pickFolder('editor-linked-path','WORKSPACE',$('editor-pick-folder')));action('editor-pick-root',()=>pickFolder('editor-workspace-root','PARENT',$('editor-pick-root')));
action('workspace-new-path',()=>{$('workspace-new-selection').textContent=$('workspace-new-path').value;},'input');
action('workspace-pick-folder',async()=>{try{await pickFolder('workspace-new-path','WORKSPACE',$('workspace-pick-folder'));$('workspace-dialog-error').hidden=true;}catch(error){$('workspace-dialog-error').textContent=error.message;$('workspace-dialog-error').hidden=false;}});
action('workspace-change',openWorkspace);action('workspace-recover-pick',openWorkspace);action('workspace-check-access',async()=>{await Promise.all([access(),window.executionSettings.preview()]);});
action('workspace-permission-help',()=>{$('workspace-permission-guide').hidden=!$('workspace-permission-guide').hidden;});
action('workspace-enable-write',async()=>{const query=document.querySelector('[data-conversation-action="QUERY"].active');if(query){$('query-write').checked=true;$('query-write').dispatchEvent(new Event('change',{bubbles:true}));}else{$('permission').value='workspace-write';$('permission').dispatchEvent(new Event('change',{bubbles:true}));}await window.executionSettings.preview();});
action('workspace-save',async()=>{const id=state.work.id;try{await api(`/works/${id}/workspace`,{method:'PUT',body:{workspace_path:$('workspace-new-path').value}});$('workspace-dialog').close();if(state.work?.id===id)await selectWork(id,true);}catch(error){$('workspace-dialog-error').textContent=error.message;$('workspace-dialog-error').hidden=false;}});action('workspace-close',()=>$('workspace-dialog').close());
action('materials-open',()=>materialOpen());action('markdown-open',()=>materialOpen('MARKDOWN'));action('external-open',()=>materialOpen('EXTERNAL'));action('shared-open',()=>{window.controlCenter?.selectMaterialTab('SHARED');});
action('material-kind',materialType,'change');action('material-save',materialSave);action('material-close',()=>{materialState.generation++;materialState.documentGeneration++;$('materials-dialog').close();});action('material-browser-up',()=>materialBrowse(materialState.path.split('/').slice(0,-1).join('/')));action('material-file-search',filterFiles,'input');
action('material-pick-files',async()=>{const id=materialState.workId;$('material-pick-files').disabled=true;try{const result=await api('/storage/pick-files',{method:'POST'});if(id!==materialState.workId||state.work?.id!==id||!$('materials-dialog').open)return;materialState.external=[...new Set([...materialState.external,...result.paths])];$('material-external-path').value='';renderExternal();materialError('');}catch(error){materialError(error.message);}finally{$('material-pick-files').disabled=false;}});
action('material-external-path',()=>{materialState.external=[];renderExternal();},'input');
action('material-change-workspace',()=>{$('materials-dialog').close();openWorkspace();});action('material-check-access',async()=>{await access();await materialType();});
action('document-browser-up',()=>documentBrowse(materialState.documentPath.split('/').slice(0,-1).join('/')));action('document-use-folder',()=>{materialState.documentFolder=materialState.documentPath;documentTarget();});action('material-document-name',documentTarget,'input');
action('material-document-path',()=>{const target=$('material-document-path').value;materialState.documentFolder=target.split('/').slice(0,-1).join('/');$('material-document-name').value=target.split('/').pop();documentTarget();},'input');
action('material-usage',()=>{const defaults={MARKDOWN:'docs/note.md',AGENTS:'AGENTS.md',REQUIREMENTS:'docs/requirements.md',ARCHITECTURE:'docs/architecture.md',IMPLEMENTATION_PLAN:'docs/implementation-plan.md',DECISION:'docs/decision.md'};const target=defaults[$('material-usage').value];materialState.documentFolder=target.split('/').slice(0,-1).join('/');$('material-document-name').value=target.split('/').pop();documentTarget();},'change');
try{if(localStorage.getItem('control-center-workspace-expanded')==='false')$('workspace-panel').open=false;}catch{}
$('workspace-panel').addEventListener('toggle',()=>{try{localStorage.setItem('control-center-workspace-expanded',String($('workspace-panel').open));}catch{}});
window.storageUI={workspaceForm,open:materialOpen,access,permissionView,beforeExecute};
