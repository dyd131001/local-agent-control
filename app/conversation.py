"""Explicit context selection and durable resources above the existing Run engine."""
import base64
import json
import math
from datetime import timedelta, timezone
from pathlib import Path
from fastapi import HTTPException
from .db import (Artifact, ContextPack, ContextPackItem, EphemeralQuery, Event, Handoff,
                 Instruction, Promotion, Request, Resource, Run, Source, ThreadRecord, Work, dump, now)
from .workspace import atomic_write, ident, safe_child, sha
from .storage import file_bytes
from .artifact_service import admit_artifact, artifact_bytes, publish
from .config import DATA_DIR, UPLOAD_LIMIT
from .context_policy import policy, prompt_cost, short_summary
from .storage import location_root

STRATEGIES = {'CONTINUE_THREAD','FORK_THREAD','FRESH_CONTEXT','CONTEXT_PACK','EPHEMERAL_QUERY'}
KINDS = {'DECISION','KNOWLEDGE','POLICY','TEMPLATE','NOTE','SUMMARY','ARTIFACT'}
TERMINAL = {'COMPLETED','FAILED','CANCELLED'}

def row(db, cls, key):
    value=db.get(cls,key)
    if value is None:raise HTTPException(404, cls.__name__+' not found')
    return value

def scoped(resource, work, thread_id=None):
    return resource.scope=='GLOBAL' or (resource.scope=='CATEGORY' and resource.category_id==work.category_id) or (resource.scope=='WORK' and resource.work_id==work.id) or (resource.scope=='THREAD' and resource.work_id==work.id and resource.thread_id==thread_id)

def resources(db, work, thread_id=None):
    return [r for r in db.query(Resource).order_by(Resource.created_at.desc()) if scoped(r,work,thread_id)]

def thread_for_run(db, run):
    if run.conversation_id:return row(db,ThreadRecord,run.conversation_id)
    # Existing Runs are adopted only when explicitly used. No historical content is migrated.
    thread=db.query(ThreadRecord).filter_by(codex_thread_id=run.thread_id).first() if run.thread_id else None
    if not thread:
        thread=ThreadRecord(id=ident('thread'),work_id=run.work_id,codex_thread_id=run.thread_id,
                            title='기존 대화',status='IDLE')
        db.add(thread);db.flush()
    run.conversation_id=thread.id
    return thread

def new_thread(db, work, title, parent=None, relation=None, query=False):
    thread=ThreadRecord(id=ident('thread'),work_id=work.id,title=title[:160] or '새 대화',
                        status='EPHEMERAL' if query else 'ACTIVE',parent_thread_id=parent.id if parent else None,
                        relation_type=relation)
    db.add(thread);db.flush();return thread

def latest(db, thread):
    candidates=db.query(Run).filter(Run.work_id==thread.work_id).filter((Run.conversation_id==thread.id) | ((Run.thread_id==thread.codex_thread_id) if thread.codex_thread_id else False)).order_by(Run.created_at.desc()).all()
    if any(r.status not in TERMINAL or r.safety_block for r in candidates):raise HTTPException(409,'이 대화에 실행 중이거나 복구가 필요한 Run이 있습니다')
    result=next((r for r in candidates if r.turn_id),None)
    if not result:raise HTTPException(409,'Runtime Turn이 있는 완료된 실행이 필요합니다')
    return result

def snapshot(db, work, kind, key, thread_id=None, mode=None):
    if kind=='RESOURCE':
        r=row(db,Resource,key)
        if not scoped(r,work,thread_id):raise HTTPException(403,'Resource scope does not permit this Work / Thread')
        data=r.content.encode();name=r.title;version=r.version;owner=r.work_id
    elif kind=='SOURCE':
        r=row(db,Source,key)
        if r.work_id!=work.id:raise HTTPException(403,'Source must belong to this Work; use published Library artifacts for cross-Work files')
        data=file_bytes(work,r,UPLOAD_LIMIT);name=r.name;version=None;owner=r.work_id
        if sha(data)!=r.sha256:raise HTTPException(409,'Source bytes changed; re-register the selected source')
    elif kind=='ARTIFACT':
        r=admit_artifact(db,key,work);data=artifact_bytes(db,r);name=r.name;version=None;owner=r.work_id
    else:raise HTTPException(422,'Invalid context source type')
    selected=policy(kind,r,mode)
    result={'source_type':kind,'source_id':key,'source_version':version,'sha256':sha(data),
            'name':name,'size':len(data),'owner_work_id':owner,'include_mode':selected,
            'mime':getattr(r,'content_type','text/plain' if kind=='RESOURCE' else None),
            'summary':(r.content[:240] if kind=='RESOURCE' else short_summary(name,r.content_type,data)),
            'relative_path':getattr(r,'relative_path',None),
            'location_root':str(location_root(work if kind=='SOURCE' else db.get(Work,r.work_id),r)) if kind!='RESOURCE' else None}
    if selected=='FULL':result['data']=base64.b64encode(data).decode()
    return result

def pack_items(db,pack):return db.query(ContextPackItem).filter_by(context_pack_id=pack.id).all()

def freshness(db, pack):
    items=[]
    work=row(db,Work,pack.work_id)
    for item in pack_items(db,pack):
        state='CURRENT'
        try:
            current=snapshot(db,work,item.source_type,item.source_id,pack.thread_id)
            if current['sha256']!=item.source_hash or current.get('source_version')!=item.source_version:state='CHANGED'
        except HTTPException as exc:
            state='CHANGED' if exc.status_code==409 else 'MISSING'
        except (ValueError,OSError):state='MISSING'
        items.append({'id':item.id,'source_type':item.source_type,'source_id':item.source_id,'state':state})
    age=now()-pack.created_at.replace(tzinfo=pack.created_at.tzinfo or timezone.utc)
    state=next((s for s in ('MISSING','CHANGED') if any(i['state']==s for i in items)), 'STALE' if age>timedelta(days=30) else 'CURRENT')
    return {'state':state,'items':items}

def pack_view(db, pack):
    return {**dump(pack),'summary':json.loads(pack.summary),'items':[{**dump(i),'snapshot':{k:v for k,v in json.loads(i.snapshot).items() if k!='data'}} for i in pack_items(db,pack)],'freshness':freshness(db,pack), 'warnings':['PACK_OVER_BUDGET'] if pack.estimated_size>pack.budget else []}

def create_pack(db,work,body,previous=None):
    if body.context_policies:
        raise HTTPException(422,'Context Packs store references; choose FULL only for a Run input')
    thread=row(db,ThreadRecord,body.thread_id) if body.thread_id else None
    if thread and thread.work_id!=work.id:raise HTTPException(403,'Thread belongs to a different Work')
    summaries={key:getattr(body,key) for key in ('goal','current','completed','pending','decisions','blockers','next_instruction')}
    pack=ContextPack(id=ident('pack'),family_id=previous.family_id if previous else ident('packfamily'),work_id=work.id,
                     thread_id=thread.id if thread else None,name=body.name,version=(db.query(ContextPack).filter_by(family_id=previous.family_id).count()+1) if previous else 1,
                     status='DRAFT',summary=json.dumps(summaries,ensure_ascii=False),estimated_size=0,budget=body.budget)
    db.add(pack);db.flush()
    unique=set();size=len(pack.summary.encode())
    for kind,keys in [('SOURCE',body.source_ids),('ARTIFACT',body.artifact_ids),('RESOURCE',body.resource_ids)]:
        for key in dict.fromkeys(keys):
            data=snapshot(db,work,kind,key,pack.thread_id,'REFERENCE')
            if data['sha256'] not in unique:size+=len(json.dumps(data,ensure_ascii=False).encode());unique.add(data['sha256'])
            db.add(ContextPackItem(id=ident('packitem'),context_pack_id=pack.id,source_type=kind,source_id=key,
                                   source_hash=data['sha256'],source_version=data['source_version'],include_mode='REFERENCE',snapshot=json.dumps(data)))
    pack.estimated_size=math.ceil(size/4);db.flush();return pack

def freeze_context(db,work,thread,config,source_ids=(),artifact_ids=(),query=False):
    config=dict(config or {})
    config.setdefault('strategy','EPHEMERAL_QUERY' if query else 'FRESH_CONTEXT')
    if config['strategy'] not in STRATEGIES:raise HTTPException(422,'Invalid context strategy')
    selected=list(config.get('resource_ids',[]));excluded=set(config.get('exclude_resource_ids',[]))
    if config.get('include_defaults',not query):
        selected.extend(r.id for r in resources(db,work,thread.id) if r.default_include and r.id not in excluded)
    allowed_policy_keys={kind+':'+key for kind,keys in [('RESOURCE',[key for key in selected if key not in excluded]),('SOURCE',source_ids),('ARTIFACT',artifact_ids)] for key in keys}
    if set(config.get('context_policies',{}))-allowed_policy_keys:
        raise HTTPException(422,'Context policy must target a selected Material, Artifact or Resource')
    snapshots=[];warnings=[]
    explicit_scope=config.get('context_source_thread_id') if config.get('context_source_thread_id') and thread.parent_thread_id==config.get('context_source_thread_id') else thread.id
    for key in dict.fromkeys(selected):
        if key not in excluded:
            selected_snapshot=snapshot(db,work,'RESOURCE',key,explicit_scope,config.get('context_policies',{}).get('RESOURCE:'+key))
            selected_snapshot['thread_scope_id']=explicit_scope
            snapshots.append(selected_snapshot)
    if config.get('pack_id'):
        pack=row(db,ContextPack,config['pack_id'])
        if pack.work_id!=work.id:raise HTTPException(403,'Context Pack must belong to this Work; share its resources instead')
        if pack.status!='REVIEWED':raise HTTPException(409,'Preview and confirm this Context Pack before execution')
        state=freshness(db,pack)['state']
        if state!='CURRENT':raise HTTPException(409,'Context Pack references changed; review and create a new version')
        config.update(pack_version=pack.version,pack_summary=json.loads(pack.summary))
        for item in pack_items(db,pack):
            # Recheck scope at execution; snapshots do not grant access to private resources.
            if item.source_type=='RESOURCE':
                r=db.get(Resource,item.source_id)
                if r and not scoped(r,work,pack.thread_id):raise HTTPException(403,'Pack contains a Resource outside its reviewed source scope')
            elif item.source_type=='ARTIFACT' and db.get(Artifact,item.source_id):admit_artifact(db,item.source_id,work)
            # Legacy Packs may contain base64 bytes. Resolve the reviewed item as a
            # reference so old content is never silently re-injected.
            selected_snapshot=snapshot(db,work,item.source_type,item.source_id,pack.thread_id,'REFERENCE')
            selected_snapshot['thread_scope_id']=pack.thread_id
            snapshots.append(selected_snapshot)
    # Backend Work Tools use the same snapshot compiler; clients cannot submit these fields.
    snapshots.extend(config.pop('tool_inputs',[]))
    seen=set();bytes_count=0
    policies=config.get('context_policies',{})
    for kind,keys,cls in [('SOURCE',source_ids,Source),('ARTIFACT',artifact_ids,Artifact)]:
        for key in keys:
            r=row(db,cls,key)
            mode=policy(kind,r,policies.get(kind+':'+key))
            if r.sha256 not in seen:
                seen.add(r.sha256)
                bytes_count+=len(json.dumps({'id':key,'name':r.name,'path':r.relative_path,
                                              'sha256':r.sha256,'mime':r.content_type,'policy':mode},ensure_ascii=False).encode())
                if mode=='FULL':bytes_count+=r.size
    dedup=[]
    for item in snapshots:
        item=dict(item)
        if item['sha256'] in seen:
            warnings.append('DUPLICATE_CONTEXT');item['duplicate']=True
        else:seen.add(item['sha256']);bytes_count+=prompt_cost(item)
        dedup.append(item)
    bytes_count+=len(json.dumps(config.get('pack_summary',{}),ensure_ascii=False).encode())+len(config.get('instruction','').encode())
    bytes_count+=sum(len(json.dumps({k:v for k,v in item.items() if k!='data'},ensure_ascii=False).encode()) for item in dedup)
    target=config.get('budget',40000);estimate=math.ceil(bytes_count/4)
    if estimate>target:warnings.append('CONTEXT_OVER_BUDGET')
    if len(source_ids)+len(artifact_ids)+len(snapshots)>40:warnings.append('MANY_FILES')
    if thread.turn_count>=20:warnings.append('LONG_THREAD_HANDOFF_RECOMMENDED')
    usage=json.loads(thread.usage)
    if usage.get('model_context_window') and usage.get('last',{}).get('totalTokens',0)>usage['model_context_window']*.8:warnings.append('RUNTIME_CONTEXT_HIGH')
    if thread.compact_state=='COMPLETED':warnings.append('COMPACTED_THREAD_HANDOFF_RECOMMENDED')
    config.update(snapshots=dedup,budget_report={'estimate':estimate,'target':target,'method':'Injected prompt bytes / 4 (approximate, excludes Runtime history)','warnings':sorted(set(warnings))})
    if estimate>target and not config.get('allow_over_budget'):
        raise HTTPException(409,{'message':'Context 예산을 초과했습니다. 자료를 줄이거나 명시적으로 초과 실행을 선택하세요','budget':config['budget_report']})
    return config

def attach_run(db,run,work,instruction,source_ids,artifact_ids,config=None,thread=None,parent=None,*,frozen_context=None):
    if run.operation=='reference':return
    config=dict(config or {})
    query=config.get('strategy')=='EPHEMERAL_QUERY'
    if thread is None:
        if run.thread_id and parent:thread=thread_for_run(db,parent)
        else:
            fork_parent=db.query(ThreadRecord).filter_by(codex_thread_id=config['fork_thread_id']).first() if config.get('fork_thread_id') else None
            if not fork_parent and config.get('fork_thread_id'):
                source=db.query(Run).filter_by(thread_id=config['fork_thread_id']).first()
                if source:fork_parent=thread_for_run(db,source)
            thread=new_thread(db,work,config.get('title') or instruction,fork_parent,'FORKED_FROM' if fork_parent else None,query)
    if run.operation=='resume':config.setdefault('strategy','CONTINUE_THREAD')
    config['instruction']=instruction
    run.conversation_id=thread.id;run.is_query=query
    if frozen_context is not None:
        # Only the durable queue supplies this backend-owned, already admitted snapshot.
        run.context_config=json.dumps(frozen_context,ensure_ascii=False)
    elif parent and run.operation=='retry' and not query and parent.context_config and not json.loads(parent.context_config).get('strategy')=='EPHEMERAL_QUERY':
        frozen=json.loads(parent.context_config)
        frozen.update(strategy='FRESH_CONTEXT',instruction=instruction)
        for key in ('fork_thread_id','fork_turn_id','compact','supersede_parent'):frozen.pop(key,None)
        run.context_config=json.dumps(frozen,ensure_ascii=False)
    else:run.context_config=json.dumps(freeze_context(db,work,thread,config,source_ids,artifact_ids,query),ensure_ascii=False)
    if not query:thread.status='ACTIVE'
    if query:
        db.add(EphemeralQuery(id=ident('query'),parent_thread_id=thread.parent_thread_id,thread_id=thread.id,run_id=run.id,context_pack_id=config.get('pack_id')))
    db.flush()

def bind_runtime(db,run):
    thread=thread_for_run(db,run)
    thread.codex_thread_id=run.thread_id

def finish_conversation(db,run):
    if not run.conversation_id:return
    thread=row(db,ThreadRecord,run.conversation_id)
    thread.turn_count=db.query(Run).filter_by(conversation_id=thread.id).filter(Run.turn_id.is_not(None)).count()
    if not run.is_query and thread.status=='ACTIVE':thread.status='IDLE'
    config=json.loads(run.context_config or '{}')
    if run.status=='COMPLETED' and config.get('supersede_parent'):
        source=row(db,ThreadRecord,config['supersede_parent'])
        source.status='SUPERSEDED';source.archived_at=now()
    if run.is_query:
        query=db.query(EphemeralQuery).filter_by(run_id=run.id).one()
        if query.status=='PENDING':query.result=run.final_text;query.status='READY' if run.status=='COMPLETED' else 'FAILED'
        run.final_text=''
        # No transient question/answer transcript in durable Run events or on-disk manifest.
        for event in db.query(Event).filter_by(run_id=run.id):
            if event.type in {'ACTIVITY','COMMAND_STARTED','COMMAND_COMPLETED','WARNING'}:event.payload=json.dumps({'message':'Temporary query event','query_id':query.id})


def dispose_query(db,query,action):
    run=row(db,Run,query.run_id)
    if run.status not in TERMINAL:raise HTTPException(409,'Wait for the query to finish')
    query.result='';query.status='DISPOSED';query.result_action=action;query.disposed_at=now()
    run.final_text='';run.context_config=json.dumps({'strategy':'EPHEMERAL_QUERY','budget_report':json.loads(run.context_config or '{}').get('budget_report',{})})
    request=row(db,Request,run.request_id);request.instruction='[임시 질문 폐기]';request.context_ids='[]';request.artifact_ids='[]'
    for instruction in db.query(Instruction).filter_by(run_id=run.id):instruction.text='[폐기]'
    manifest=json.loads(run.manifest)
    for key in ('instruction','instruction_sha256','prompt','prompt_sha256','pack_summary'):manifest.pop(key,None)
    run.manifest=json.dumps(manifest)
    from .workspace import save_manifest
    save_manifest(run.id,manifest)
    thread=row(db,ThreadRecord,query.thread_id);thread.status='CLOSED';thread.title='임시 질문 (폐기됨)';thread.archived_at=now()
    # Runtime's ephemeral flag prevents persisted Runtime history. Purge Backend scratch and inputs.
    from .storage import runtime_root
    from .workspace import safe_child
    import shutil
    folder=safe_child(runtime_root(row(db,Work,run.work_id),manifest),'runs/'+run.id)
    if folder.exists():
        if db.query(Artifact).filter_by(run_id=run.id).first():
            # Explicitly collected Artifacts keep their immutable registered locations.
            inputs=safe_child(folder,'inputs')
            if inputs.exists():shutil.rmtree(inputs)
        else:shutil.rmtree(folder)


def expire_queries(db):
    cutoff=now()-timedelta(hours=24)
    for query in db.query(EphemeralQuery).filter(EphemeralQuery.status.in_(['READY','FAILED']),EphemeralQuery.created_at<cutoff):dispose_query(db,query,'DISCARD')


def promote(db,run,body):
    if run.status!='COMPLETED':raise HTTPException(409,'Only completed answers may be promoted')
    work=row(db,Work,run.work_id)
    if body.kind not in KINDS:raise HTTPException(422,'Invalid promotion kind')
    if body.scope not in {'THREAD','WORK','CATEGORY','GLOBAL'}:raise HTTPException(422,'Invalid promotion scope')
    if body.scope=='THREAD' and not run.conversation_id:raise HTTPException(409,'Thread scope requires a conversation')
    if body.kind=='ARTIFACT':
        if body.scope=='THREAD':raise HTTPException(422,'Artifacts use existing WORK / CATEGORY / GLOBAL Library scopes')
        # Immutable Backend-created result; use existing Artifact and Publish admission.
        from .run_service import create_run
        reference=create_run(db,work.id,'Explicit answer promotion',[],[],'manual','none',operation='reference')
        reference.status=reference.phase='COMPLETED';reference.completed_at=now();reference.artifact_state='READY'
        aid=ident('art');relative=f"works/{work.id}/promotions/{aid}/answer.md";data=body.content.encode()
        atomic_write(safe_child(DATA_DIR,relative),data)
        target=Artifact(id=aid,work_id=work.id,run_id=reference.id,name=body.title+'.md',candidate_path=relative,
                        relative_path=relative,location_root=str(DATA_DIR),location_type='SHARED',content_type='text/markdown',size=len(data),sha256=sha(data),availability='AVAILABLE',partial=False)
        db.add(target);db.flush()
        if body.scope!='WORK':publish(db,target.id,body.scope)
    else:
        target=Resource(id=ident('resource'),work_id=work.id,category_id=work.category_id,
                        thread_id=run.conversation_id if body.scope=='THREAD' else None,
                        kind=body.kind,scope=body.scope,title=body.title,content=body.content,sha256=sha(body.content.encode()),default_include=body.default_include)
        db.add(target);db.flush()
    db.add(Promotion(id=ident('promotion'),source_thread_id=run.conversation_id,source_run_id=run.id,target_type=body.kind,target_id=target.id,scope=body.scope))
    return target


def compile_context(db,work,run,manifest,root):
    config=json.loads(run.context_config or '{}')
    if not config:return
    warnings=config.get('budget_report',{}).get('warnings',[])
    seen={};aliases=[];files=[]
    for f in manifest['files']:
        if f['sha256'] in seen:
            aliases.append({**f,'duplicate_of':seen[f['sha256']]});warnings.append('DUPLICATE_CONTEXT')
        else:seen[f['sha256']]=f.get('source_id') or f.get('artifact_id');files.append(f)
    manifest['files']=files
    for item in config.get('snapshots',[]):
        meta={k:v for k,v in item.items() if k!='data'}
        if item['sha256'] in seen:
            aliases.append({**meta,'duplicate_of':seen[item['sha256']]});warnings.append('DUPLICATE_CONTEXT');continue
        seen[item['sha256']]=item['source_id']
        if item['source_type']=='WORK_TOOL':
            data=base64.b64decode(item['data'],validate=True)
            if sha(data)!=item['sha256']:raise ValueError('Frozen work tool input hash mismatch')
            relative=f"runs/{run.id}/inputs/context/{item['source_id']}/reference"
            atomic_write(safe_child(root,relative),data)
            manifest['files'].append({**meta,'scope':'work_tool','snapshot_path':relative,'snapshot_root':str(root),
                                      'input_key':'WORK_TOOL:'+item['source_id'],'include_mode':'REFERENCE'})
            continue
        current=snapshot(db,work,item['source_type'],item['source_id'],item.get('thread_scope_id') or run.conversation_id,
                         item.get('include_mode') if item.get('include_mode')!='FULL' or item.get('size',0)<=8192 else None)
        if current['sha256']!=item['sha256'] or current.get('source_version')!=item.get('source_version'):
            raise ValueError('Selected context changed since registration')
        if current['source_type']=='RESOURCE':
            if current['include_mode']=='FULL':
                data=base64.b64decode(current['data'],validate=True)
                relative=f"runs/{run.id}/inputs/context/{item['source_id']}/reference"
                atomic_write(safe_child(root,relative),data)
                manifest['files'].append({**meta,'scope':'resource','snapshot_path':relative,'snapshot_root':str(root),'input_key':'RESOURCE:'+item['source_id'],'include_mode':'FULL','summary':current['summary']})
            else:manifest.setdefault('context_references',[]).append(current)
        else:
            manifest['files'].append({**current,'scope':item['source_type'].lower(),
                                      'snapshot_path':current['relative_path'],'snapshot_root':current['location_root'],
                                      'input_key':item['source_type']+':'+item['source_id'],'delivery':'reference'})
    manifest.update(context_strategy=config['strategy'],conversation_id=run.conversation_id,
                    context_pack_id=config.get('pack_id'),context_pack_version=config.get('pack_version'),
                    context_aliases=aliases,context_budget={**config['budget_report'],'warnings':sorted(set(warnings))},
                    ephemeral=run.is_query,artifact_creation=config.get('artifact_creation',not run.is_query))
    if config.get('pack_summary'):manifest['pack_summary']=config['pack_summary']
    if config.get('fork_thread_id'):manifest.update(fork_thread_id=config['fork_thread_id'],fork_turn_id=config['fork_turn_id'])
    if config.get('compact'):manifest['compact_requested']=True
    if config.get('tool_context'):manifest['tool_context']=config['tool_context']
    if run.is_query:manifest['developer_instructions']='Answer the question using only explicitly provided reference inputs. '+manifest['developer_instructions']


def inspector(db,run):
    manifest=json.loads(run.manifest)
    config=json.loads(run.context_config or '{}')
    return {'work':row(db,Work,run.work_id).name,'thread':dump(row(db,ThreadRecord,run.conversation_id)) if run.conversation_id else None,
            'strategy':manifest.get('context_strategy',config.get('strategy','CONTINUE_THREAD' if run.operation=='resume' else 'FRESH_CONTEXT')),
            'pack_id':manifest.get('context_pack_id',config.get('pack_id')),'pack_version':manifest.get('context_pack_version',config.get('pack_version')),
            'inputs':[{k:v for k,v in f.items() if k not in {'snapshot_root','snapshot_path','data'}} for f in manifest.get('files',[])] +
                     [{k:v for k,v in f.items() if k not in {'data','location_root'}} for f in manifest.get('context_references',[])],
            'aliases':manifest.get('context_aliases',[]),'budget':manifest.get('context_budget',config.get('budget_report',{})),
            'history_note':'같은 Thread / Fork에는 Runtime History가 추가됩니다. 이 목록과 추정치는 제공한 자료만 표시합니다.'}
