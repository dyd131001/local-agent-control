"""Read-only Git Diff and frozen Review inputs. AI execution stays in Run Service."""
import base64
import difflib
import json
from pathlib import Path, PurePosixPath
from fastapi import HTTPException
from .config import DATA_DIR, RUNTIME_DIR, STATE_DIR
from .git_workspace import git
from .storage import workspace_root, validate_workspace
from .workspace import safe_child, safe_read, sha

MAX_FILES=500
MAX_FILE_BYTES=2*1024*1024
MAX_CONTEXT_BYTES=8*1024*1024


def selected_path(value):
    try:value.encode('utf-8')
    except UnicodeEncodeError:raise HTTPException(422,'Work Tools paths must use UTF-8 file names')
    path=PurePosixPath(value)
    if not value or len(value)>1024 or path.is_absolute() or '\\' in value or '\x00' in value or any(p in {'','..','.'} or p.casefold()=='.git' for p in value.split('/')):
        raise HTTPException(422,'Select exact workspace-relative files; Git metadata and traversal are not allowed')
    return value


def work_root(work):
    root=workspace_root(work)
    # Preserve legacy material access but never expose Backend Run / Git administration.
    if work.storage_layout=='LEGACY':
        if root.is_symlink():raise HTTPException(422,'Workspace root cannot be a symlink')
        root=root.resolve(strict=True)
        if root.is_relative_to(STATE_DIR) or root.is_relative_to(RUNTIME_DIR):raise HTTPException(422,'Backend state is not a Work Tools workspace')
    else:root=validate_workspace(str(root))
    return root


def commands(root,*args):return git(['--literal-pathspecs','-C',str(root),*args])


def repository(work):
    try:root=work_root(work)
    except (OSError,ValueError):return None,None,'Workspace is unavailable'
    try:actual=Path(commands(root,'rev-parse','--show-toplevel').decode().strip()).resolve()
    except ValueError:return root,None,'Workspace is not a Git repository'
    if actual!=root:return root,None,'Connect the Git repository root; ancestor repositories are not inspected'
    try:head=commands(root,'rev-parse','--verify','HEAD^{commit}').decode().strip()
    except ValueError:return root,None,'Repository has no HEAD commit; use selected-file Review'
    return root,head,None


def commit(root,ref):
    if not ref or len(ref)>200 or ref.startswith('-') or any(c in ref for c in '\x00\r\n'):
        raise HTTPException(422,'Invalid Git comparison reference')
    return commands(root,'rev-parse','--verify','--end-of-options',ref+'^{commit}').decode().strip()


def changed_names(data):
    values=data.decode('utf-8',errors='surrogateescape').split('\x00');result=[];i=0
    while i<len(values) and values[i]:
        status=values[i];i+=1;old=values[i];i+=1
        if status[0] in {'R','C'}:
            path=values[i];i+=1
        else:path=old;old=None
        result.append({'path':path,'old_path':old,'status':status})
    return result


def stats(data):
    parts=data.decode('utf-8',errors='surrogateescape').split('\x00');result={};i=0
    while i<len(parts) and parts[i]:
        add,delete,path=parts[i].split('\t',2);i+=1
        if not path:i+=1;path=parts[i];i+=1
        result[path]={'additions':None if add=='-' else int(add),'deletions':None if delete=='-' else int(delete),'binary':add=='-' or delete=='-'}
    return result


def check_paths(work,paths):
    values=list(dict.fromkeys(selected_path(p) for p in paths))
    if legacy_overlap(work) and any(p.split('/')[0] in {'runs','git','artifacts'} for p in values):raise HTTPException(422,'Select original materials, not legacy Backend execution folders')
    return values

def legacy_overlap(work):
    return work.storage_layout=='LEGACY' and workspace_root(work).resolve()==Path(work.path).resolve()


def diff(work,body):
    paths=check_paths(work,body.paths)
    root,head,reason=repository(work)
    if reason:return {'contract_version':1,'available':False,'reason':reason,'work_id':work.id,'scope':body.scope,'files':[],'patch':None,'diff_sha256':None,'ai_run_created':False}
    base=commit(root,body.base_ref) if body.base_ref else head
    target=commit(root,body.target_ref) if body.scope=='BRANCH' else None
    refs=[base]+([target] if target else [])
    flags=['--no-ext-diff','--no-textconv','--no-color','--find-renames','--submodule=short']
    def patch_bytes():return commands(root,'diff',*flags,'--patch','--unified=3',*refs,'--',*paths)
    before=commands(root,'status','--porcelain=v1','-z','--untracked-files=all') if not target else b''
    names=changed_names(commands(root,'diff',*flags,'--name-status','-z',*refs,'--',*paths))
    numeric=stats(commands(root,'diff',*flags,'--numstat','-z',*refs,'--',*paths))
    patch=patch_bytes()
    original_tracked_patch=patch
    files=[{**n,**numeric.get(n['path'],{'additions':None,'deletions':None,'binary':None})} for n in names]
    for file in files:
        selected_path(file['path'])
        if file.get('old_path'):selected_path(file['old_path'])
    if len(files)>MAX_FILES:raise HTTPException(413,'Too many changed files; select a smaller scope')
    if not target:
        untracked=commands(root,'ls-files','--others','--exclude-standard','-z','--',*paths).decode('utf-8',errors='surrogateescape').split('\x00')
        read_bytes=0
        for name in filter(None,untracked):
            if len(files)>=MAX_FILES:raise HTTPException(413,'Too many changed files; select a smaller scope')
            selected_path(name)
            if legacy_overlap(work) and name.split('/')[0] in {'runs','git','artifacts'}:continue
            file={'path':name,'old_path':None,'status':'UNTRACKED','additions':None,'deletions':0,'binary':None,'content_sha256':None}
            try:
                if read_bytes>=MAX_CONTEXT_BYTES:raise ValueError('Diff content limit reached')
                data=safe_read(root,name,min(MAX_FILE_BYTES,MAX_CONTEXT_BYTES-read_bytes));read_bytes+=len(data)
                file['content_sha256']=sha(data)
                binary=b'\x00' in data
                try:text=data.decode('utf-8')
                except UnicodeDecodeError:binary=True;text=''
                file['binary']=binary
                if not binary:
                    file['additions']=len(text.splitlines())
                    extra=''.join(difflib.unified_diff([],text.splitlines(keepends=True),fromfile='/dev/null',tofile='b/'+name))
                    if text and not text.endswith('\n'):extra+='\n\\ No newline at end of file\n'
                    patch+=extra.encode()
                else:patch+=('Binary untracked file: '+name+'\n').encode()
            except (OSError,ValueError):file['content_omitted']='File unavailable, unsafe, or exceeds Diff content limit'
            files.append(file)
    after=commands(root,'status','--porcelain=v1','-z','--untracked-files=all') if not target else b''
    if before!=after:raise HTTPException(409,'Git changes moved during Diff capture; request a fresh preview')
    # Detect content edits that leave porcelain status unchanged.
    tracked_patch=patch_bytes()
    if tracked_patch!=original_tracked_patch:raise HTTPException(409,'Git changes moved during Diff capture')
    for file in files:
        if file.get('content_sha256') and sha(safe_read(root,file['path'],MAX_FILE_BYTES))!=file['content_sha256']:
            raise HTTPException(409,'Untracked file changed during Diff capture')
    # Include immutable refs, file metadata and full patch in the preview identity.
    identity=sha(json.dumps({'base':base,'target':target,'files':files},sort_keys=True,ensure_ascii=True).encode()+patch)
    max_bytes=body.max_patch_bytes
    text_patch=patch[:max_bytes].decode('utf-8',errors='replace')
    return {'contract_version':1,'available':True,'work_id':work.id,'scope':body.scope,'base_commit':base,'target_commit':target,
            'paths':paths,'files':files,'summary':{'changed_files':len(files),'additions':None if any(f['additions'] is None for f in files) else sum(f['additions'] for f in files),
            'deletions':None if any(f['deletions'] is None for f in files) else sum(f['deletions'] for f in files),
            'known_additions':sum(f['additions'] or 0 for f in files),'known_deletions':sum(f['deletions'] or 0 for f in files),
            'binary_files':sum(bool(f.get('binary')) for f in files),'unknown_line_counts':sum(f.get('additions') is None for f in files)},
            'patch':text_patch,'patch_bytes':len(patch),'truncated':len(patch)>max_bytes or any(f.get('content_omitted') for f in files),
            'diff_sha256':identity,'ai_run_created':False}


def tool_input(name,data,version=None):
    return {'source_type':'WORK_TOOL','source_id':'tool-'+sha((name+sha(data)).encode())[:24], 'source_version':None,'sha256':sha(data),
            'name':name,'size':len(data),'include_mode':'FULL','data':base64.b64encode(data).decode(),'git_version':version}


def review_inputs(work,body):
    paths=check_paths(work,body.paths)
    if body.scope=='FILES' and not paths:raise HTTPException(422,'Select one or more files for Review')
    try:root=work_root(work)
    except (OSError,ValueError) as exc:raise HTTPException(409,'Review Workspace is unavailable') from exc
    preview=diff(work,body)
    if body.scope!='FILES' and not preview['available']:raise HTTPException(409,preview['reason'])
    if body.expected_diff_sha256 and body.expected_diff_sha256!=preview.get('diff_sha256'):raise HTTPException(409,'Diff preview is stale; inspect the current changes before Review')
    if preview.get('truncated'):raise HTTPException(413,'Diff is incomplete or exceeds the Review limit; select fewer files')
    inputs=[];total=0
    if preview.get('available'):
        summary={k:v for k,v in preview.items() if k not in {'patch'}}
        inputs.append(tool_input('diff-summary.json',json.dumps(summary,ensure_ascii=True,indent=2).encode()))
        inputs.append(tool_input('changes.patch',(preview['patch'] or '(no changes)').encode()))
    by_path={f['path']:f for f in preview['files']}
    chosen=[by_path.get(p,{'path':p,'status':'SELECTED'}) for p in paths] if body.scope=='FILES' else preview['files']
    if len(chosen)>100:raise HTTPException(413,'Review supports up to 100 files; select a smaller scope')
    omitted=[]
    for file in chosen:
        name=file['path'];selected_path(name)
        if file.get('binary'):omitted.append({'path':name,'reason':'binary content is not reviewed'});continue
        if preview.get('target_commit'):
            version=preview['base_commit'] if file['status'].startswith('D') else preview['target_commit']
            data=commands(root,'show',version+':'+name)
        elif file['status'].startswith('D'):
            version=preview['base_commit'];data=commands(root,'show',version+':'+name)
        else:
            version=None
            try:data=safe_read(root,name,MAX_FILE_BYTES)
            except OSError as exc:raise HTTPException(410,'Selected Review file is unavailable: '+name) from exc
        if b'\x00' in data:
            omitted.append({'path':name,'reason':'binary content is not reviewed'});continue
        try:data.decode('utf-8')
        except UnicodeDecodeError:omitted.append({'path':name,'reason':'non UTF-8 content is not reviewed'});continue
        total+=len(data)
        if len(data)>MAX_FILE_BYTES or total>MAX_CONTEXT_BYTES:raise HTTPException(413,'Review file inputs exceed the 8 MiB total / 2 MiB per file limit')
        inputs.append(tool_input(name,data,version))
    if preview.get('available') and body.scope!='BRANCH':
        again=diff(work,body)
        if preview['diff_sha256']!=again['diff_sha256']:raise HTTPException(409,'Workspace changed while Review inputs were being frozen')
    elif body.scope=='FILES':
        for item in inputs:
            if not item.get('git_version') and sha(safe_read(root,item['name'],MAX_FILE_BYTES))!=item['sha256']:raise HTTPException(409,'Selected file changed during capture')
    if body.scope=='FILES' and not inputs:raise HTTPException(422,'Selected files contain no reviewable UTF-8 text')
    return inputs,{'kind':'REVIEW','scope':body.scope,'paths':paths,'diff_sha256':preview.get('diff_sha256'),
                   'base_commit':preview.get('base_commit'),'target_commit':preview.get('target_commit'),
                   'workspace_root':str(root),'omitted_files':omitted,'captured_input_count':len(inputs)}
