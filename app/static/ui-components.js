'use strict';
// Shared presentation primitives. Values and actions remain owned by each screen.
window.UI = (() => {
  let choiceSequence=0;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={AVAILABLE:'사용 가능',MISSING:'파일 없음',CHANGED:'원본 변경',UNAVAILABLE:'사용 불가',PARTIAL:'일부 결과',ACTIVE:'활성',DISABLED:'비활성',PENDING:'대기',TRIGGERED:'실행 전달됨',CLAIMED:'실행 준비',APPROVED:'승인됨',WAITING:'승인 대기',REJECTED:'반려',FAILED:'실패',CANCELLED:'취소',COMPLETED:'완료',RUNNING:'진행 중',BLOCKED:'실행 보류',QUEUED:'실행 대기',CURRENT:'최신',REVIEWED:'내용 확인됨',DRAFT:'초안',RESEARCHING:'자료 조사 중',NO_SOURCES:'자료 없음',REVIEW_LIMIT:'조사 검토 필요',NEEDS_REPLAN:'계획 재생성 필요',GENERATING:'계획 생성 중',INVALID:'형식 확인 필요',STALE:'오래됨',ARCHIVED:'보관됨',SKIPPED:'생략'};
  function node(markup){const template=document.createElement('template');template.innerHTML=markup.trim();return template.content.firstElementChild;}
  function statusHTML(value,label){return `<span class="badge ui-status" data-status="${esc(value)}">${esc(label||labels[value]||window.controlCenter?.status(value)||value||'확인 필요')}</span>`;}
  function fileSize(value){const bytes=Number(value);if(!Number.isFinite(bytes)||value==null)return '크기 미제공';if(bytes<1024)return bytes+' B';if(bytes<1024*1024)return (bytes/1024).toFixed(1)+' KB';return (bytes/1024/1024).toFixed(1)+' MB';}
  function metadataHTML(entries,compact=false){return `<dl class="ui-metadata${compact?' ui-metadata-compact':''}">${entries.map(([key,value,kind])=>`<div><dt>${esc(key)}</dt><dd>${kind==='path'?`<code class="ui-path" title="${esc(value)}">${esc(value||'미정')}</code>`:esc(value??'미정')}</dd></div>`).join('')}</dl>`;}
  function helpHTML(text,title='안내'){return `<div class="ui-help"><span class="ui-help-label">${esc(title)}</span><p>${esc(text)}</p></div>`;}
  function warningHTML(text,title='확인 필요'){return `<div class="ui-warning" role="note"><strong>${esc(title)}</strong><p>${esc(text)}</p></div>`;}
  function emptyHTML(title,description=''){return `<div class="ui-empty"><span class="ui-empty-symbol" aria-hidden="true">◇</span><strong>${esc(title)}</strong>${description?`<p>${esc(description)}</p>`:''}</div>`;}
  function actionStyle(button,kind='secondary'){
    button.classList.add('ui-action');button.dataset.action=kind;
    button.classList.toggle('primary',kind==='primary');return button;
  }
  function action(label,fn,{kind='secondary',disabled=false}={}){
    const button=document.createElement('button');button.type='button';button.textContent=label;button.disabled=disabled;actionStyle(button,kind);
    button.onclick=async()=>{try{await fn();}catch(error){if(typeof notice==='function')notice(error.message||String(error));}};return button;
  }
  function metadata(entries,{compact=false}={}){
    const list=document.createElement('dl');list.className='ui-metadata'+(compact?' ui-metadata-compact':'');
    for(const [key,value,kind] of entries){const pair=document.createElement('div'),term=document.createElement('dt'),definition=document.createElement('dd');term.textContent=key;
      if(value instanceof Node)definition.append(value);
      else if(kind==='path'){const path=document.createElement('code');path.className='ui-path';path.textContent=value||'미정';path.title=value||'';definition.append(path);}
      else definition.textContent=value??'미정';pair.append(term,definition);list.append(pair);
    }return list;
  }
  function empty(title,description='',actions=[]){const region=node(emptyHTML(title,description));if(actions.length){const controls=document.createElement('div');controls.className='ui-actions';controls.append(...actions);region.append(controls);}return region;}
  function detail(title,{status=null,description=null}={}){
    const pane=document.createElement('section');pane.className='ui-detail';
    const header=document.createElement('div');header.className='ui-detail-heading';const heading=document.createElement('h3');heading.textContent=title;header.append(heading);if(status)header.append(status);pane.append(header);if(description)pane.append(node(helpHTML(description)));return pane;
  }
  function advanced(title,contents){const details=document.createElement('details');details.className='ui-advanced';const summary=document.createElement('summary');summary.textContent=title;details.append(summary);if(contents)details.append(contents);return details;}
  function disclosure(title,contents,{id='',open=false}={}){
    const details=document.createElement('details');details.className='ui-disclosure';details.open=open;if(id)details.id=id;
    const summary=document.createElement('summary');summary.textContent=title;details.append(summary);
    if(contents){const body=document.createElement('div');body.className='ui-disclosure-body';body.append(...(Array.isArray(contents)?contents:[contents]));details.append(body);}return details;
  }
  function selectable({title,value,selected=false,disabled=false,metadata:entries=[],description='',onChange,actions=[]}){
    const label=document.createElement('div');label.className='context-item ui-selectable';
    const input=document.createElement('input');input.type='checkbox';input.id='ui-choice-'+(++choiceSequence);input.value=value;input.checked=selected;input.disabled=disabled;
    const body=document.createElement('div');body.className='ui-selectable-body';const heading=document.createElement('label');heading.htmlFor=input.id;heading.className='ui-list-title';heading.textContent=title;body.append(heading);
    if(description){const hint=document.createElement('span');hint.className='ui-list-description';hint.textContent=description;body.append(hint);}
    const visibleEntries=entries.filter(entry=>entry[2]!=='path'),paths=entries.filter(entry=>entry[2]==='path');
    if(visibleEntries.length){const values=metadata(visibleEntries,{compact:true});values.id=input.id+'-metadata';input.setAttribute('aria-describedby',values.id);body.append(values);}
    if(paths.length)body.append(disclosure('파일 위치',metadata(paths)));
    const sync=()=>{label.classList.toggle('is-selected',input.checked);label.classList.toggle('selected',input.checked);};input.addEventListener('change',()=>{sync();onChange?.(input.checked);});sync();label.append(input,body);
    // Secondary controls are siblings of the checkbox's associated label content.
    for(const control of actions){control.addEventListener('click',event=>event.stopPropagation());label.append(control);}
    label.addEventListener('click',event=>{if(disabled||event.target.closest('input,label,a,button,select,textarea,details'))return;input.click();});return label;
  }
  function enhance(root=document){
    for(const el of root.querySelectorAll('.view-toolbar'))el.classList.add('ui-toolbar');
    for(const el of root.querySelectorAll('details'))if(!el.matches('.row-menu,.action-menu,.workspace-region,.history-turn,.work-menu'))el.classList.add('ui-disclosure');
    for(const el of root.querySelectorAll('.badge'))el.classList.add('ui-status');
    for(const el of root.querySelectorAll('.empty'))el.classList.add('ui-empty','ui-empty-compact');
    for(const el of root.querySelectorAll('.info-note, [data-ui="help"]'))el.classList.add('ui-help');
    for(const el of root.querySelectorAll('.warning-banner, .inline-error, .workspace-help, [data-ui="warning"]'))el.classList.add('ui-warning');
    for(const el of root.querySelectorAll('dl.metadata-grid, dl.thread-metadata, dl.category-metadata'))el.classList.add('ui-metadata');
    for(const el of root.querySelectorAll('[data-ui="detail"]'))el.classList.add('ui-detail');
    for(const el of root.querySelectorAll('[data-ui="advanced"], details.history-ids, details.storage-info'))el.classList.add('ui-advanced');
    for(const button of root.querySelectorAll('button, a.file-button'))if(!button.classList.contains('ui-action'))actionStyle(button,button.dataset.action|| (button.classList.contains('primary')?'primary':'secondary'));
  }
  return {status:(value,label)=>node(statusHTML(value,label)),statusHTML,metadata,metadataHTML,fileSize,
    help:(text,title)=>node(helpHTML(text,title)),helpHTML,warning:(text,title)=>node(warningHTML(text,title)),warningHTML,
    empty,emptyHTML,detail,selectable,advanced,disclosure,action,actionStyle,enhance};
})();
