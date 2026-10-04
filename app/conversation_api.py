"""Minimal conversation commands, immutable packs and explicit promotion."""
import json
from typing import Literal
from fastapi import APIRouter, HTTPException, Request as HttpRequest
from pydantic import BaseModel, ConfigDict, Field
from .db import ContextPack, EphemeralQuery, Handoff, Request, Resource, Run, Session, Source, Artifact, ThreadRecord, Work, dump, now
from .conversation import (create_pack, dispose_query, expire_queries, inspector, latest, new_thread, pack_view,
                           promote, resources, row, scoped, thread_for_run)
from .execution_settings import ExecutionProfile, catalog_from, override, inherited, resolve
from .workflow import COMMAND_LOCK
from .workspace import ident, sha
from .artifact_service import admit_artifact

router=APIRouter(prefix='/api')
runner=None
queue=None

def configure(worker, queue_run):
    global runner, queue
    runner,queue=worker,queue_run
    return router

class Body(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)

class ContextBody(Body):
    source_ids:list[str]=Field(default_factory=list,max_length=100)
    artifact_ids:list[str]=Field(default_factory=list,max_length=100)
    resource_ids:list[str]=Field(default_factory=list,max_length=100)
    exclude_resource_ids:list[str]=Field(default_factory=list,max_length=100)
    budget:int=Field(default=40000,ge=100,le=1000000)
    context_policies:dict[str,Literal['REFERENCE','RETRIEVE','FULL']]=Field(default_factory=dict,max_length=300)

class ConversationBody(ContextBody):
    action:Literal['NEW','CONTINUE','RESUME','COMPACT','QUERY','FORK','HANDOFF']='NEW'
    thread_id:str|None=None
    from_run_id:str|None=None
    pack_id:str|None=None
    instruction:str=Field(min_length=1,max_length=30000)
    title:str=Field(default='',max_length=160)
    execution_profile:ExecutionProfile|None=None
    include_defaults:bool|None=None
    allow_over_budget:bool=False
    confirmed:bool=False
    supersede_parent:bool=False
    write_query:bool=False
    artifact_creation:bool=False

class PackBody(ContextBody):
    thread_id:str|None=None
    name:str=Field(min_length=1,max_length=160)
    goal:str=Field(default='',max_length=10000)
    current:str=Field(default='',max_length=10000)
    completed:str=Field(default='',max_length=10000)
    pending:str=Field(default='',max_length=10000)
    decisions:str=Field(default='',max_length=10000)
    blockers:str=Field(default='',max_length=10000)
    next_instruction:str=Field(default='',max_length=10000)

class Confirmation(Body):
    confirmed:Literal[True]

class PromotionBody(Body):
    kind:Literal['DECISION','KNOWLEDGE','POLICY','ARTIFACT','TEMPLATE','NOTE','SUMMARY']='DECISION'
    scope:Literal['THREAD','WORK','CATEGORY','GLOBAL']='WORK'
    title:str=Field(min_length=1,max_length=160)
    content:str=Field(min_length=1,max_length=200000)
    default_include:bool=False

class ResourceChange(Body):
    title:str|None=Field(default=None,min_length=1,max_length=160)
    content:str|None=Field(default=None,min_length=1,max_length=200000)
    default_include:bool|None=None

class QueryDecision(Body):
    action:Literal['DISCARD','PROMOTE','HANDOFF']
    summary:str=Field(default='',max_length=4000)
    promotion:PromotionBody|None=None
    execution_profile:ExecutionProfile|None=None

class Lifecycle(Body):
    status:Literal['IDLE','ARCHIVED','CLOSED','SUPERSEDED']

class RuntimeImport(Body):
    runtime_thread_id:str=Field(min_length=1,max_length=160)


@router.get('/conversation-capabilities')
def conversation_capabilities():
    capability=getattr(runner.gateway,'conversation_capabilities',None)
    return capability() if callable(capability) else {'discovery':False,'resume':False}


@router.get('/works/{work_id}/runtime-conversations')
async def runtime_conversations(work_id:str,cursor:str|None=None):
    import asyncio
    from pathlib import Path
    from .storage import workspace_root
    capability=conversation_capabilities()
    if not capability['discovery'] or not capability['resume']:raise HTTPException(501,'현재 Runtime은 기존 Codex 대화 조회·재개를 지원하지 않습니다.')
    with Session() as db:
        root=str(workspace_root(row(db,Work,work_id)).resolve())
        owned={t.codex_thread_id:t.work_id for t in db.query(ThreadRecord).filter(ThreadRecord.codex_thread_id.is_not(None))}
        owned.update({r.thread_id:r.work_id for r in db.query(Run).filter(Run.thread_id.is_not(None))})
    try:result=await asyncio.wait_for(runner.gateway.list_threads(root,cursor),20)
    except Exception as exc:raise HTTPException(503,'Codex 대화 목록을 조회할 수 없습니다. Runtime 연결과 조회 지원 여부를 확인하세요.') from exc
    result['threads']=[{**t,'connected':t['id'] in owned,'other_work':owned.get(t['id']) not in {None,work_id}}
                       for t in result['threads'] if t.get('cwd') and Path(t['cwd']).resolve()==Path(root) and not t.get('ephemeral')]
    return result


@router.post('/works/{work_id}/runtime-conversations/import',status_code=201)
async def import_runtime_conversation(work_id:str,body:RuntimeImport):
    import asyncio
    from datetime import datetime, timezone, timedelta
    from pathlib import Path
    from .storage import workspace_root
    capability=conversation_capabilities()
    if not capability['discovery'] or not capability['resume']:raise HTTPException(501,'현재 Runtime은 기존 Codex 대화 연결을 지원하지 않습니다.')
    with Session() as db:
        root=workspace_root(row(db,Work,work_id)).resolve()
        linked=db.query(ThreadRecord).filter_by(codex_thread_id=body.runtime_thread_id).first()
        if linked:
            if linked.work_id!=work_id:raise HTTPException(409,'이 대화는 다른 Work에 연결되어 있습니다.')
            return dump(linked)
    try:history=await asyncio.wait_for(runner.gateway.read_thread(body.runtime_thread_id),20)
    except Exception as exc:raise HTTPException(503,'선택한 Codex 대화를 읽을 수 없습니다.') from exc
    if not history.get('cwd') or Path(history['cwd']).resolve()!=root:raise HTTPException(403,'현재 Workspace와 같은 경로의 대화만 연결할 수 있습니다.')
    turns=history.get('turns',[])
    if history.get('ephemeral') or not turns or any(t['status'] not in {'completed','failed','interrupted'} for t in turns):
        raise HTTPException(409,'실행이 끝난 일반 대화를 선택하세요. 진행 중인 대화는 연결할 수 없습니다.')
    def timestamp(value):
        return datetime.fromtimestamp(value,timezone.utc) if isinstance(value,(int,float)) else None
    with COMMAND_LOCK,Session() as db:
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        work=row(db,Work,work_id)
        if workspace_root(work).resolve()!=root:raise HTTPException(409,'Workspace가 변경되었습니다. 다시 선택하세요.')
        if work.archived:raise HTTPException(409,'보관된 Work입니다.')
        thread=db.query(ThreadRecord).filter_by(codex_thread_id=body.runtime_thread_id).first()
        if thread:
            if thread.work_id!=work.id:raise HTTPException(409,'이 대화는 다른 Work에 연결되어 있습니다.')
            return dump(thread)
        existing=db.query(Run).filter_by(thread_id=body.runtime_thread_id).first()
        if existing:
            if existing.work_id!=work.id:raise HTTPException(409,'이 대화의 실행은 다른 Work에 속합니다.')
            thread=thread_for_run(db,existing);db.commit();return dump(thread)
        title=history.get('name') or next((t.get('instruction') for t in turns if t.get('instruction')),'기존 Codex 대화')
        thread=new_thread(db,work,title);thread.codex_thread_id=body.runtime_thread_id;thread.status='IDLE';thread.turn_count=len(turns)
        start=timestamp(history.get('created_at')) or now()
        thread.created_at=start
        previous=None
        for index,turn in enumerate(turns):
            started=timestamp(turn.get('started_at'))
            request=Request(id=ident('req'),work_id=work.id,instruction=turn.get('instruction') or '(기존 Codex 요청)',created_at=started or start+timedelta(microseconds=index))
            db.add(request);db.flush()
            status={'completed':'COMPLETED','failed':'FAILED','interrupted':'CANCELLED'}[turn['status']]
            run=Run(id=ident('run'),request_id=request.id,work_id=work.id,conversation_id=thread.id,
                    thread_id=body.runtime_thread_id,turn_id=turn['id'],parent_run_id=previous,operation='import',
                    model=history.get('model') or '기존 Codex',reasoning=history.get('reasoning') or 'unknown',
                    status=status,phase=status,runtime_status=turn['status'],artifact_state='NONE',
                    final_text=turn.get('final_text') or '',created_at=start+timedelta(microseconds=index),started_at=started,
                    completed_at=timestamp(turn.get('completed_at')),
                    manifest=json.dumps({'imported':True,'workspace_root':str(root),'runtime_time_available':started is not None}))
            db.add(run);db.flush();previous=run.id
        db.commit();return dump(thread)


@router.post('/runtime-conversations/sync')
async def sync_runtime_conversations():
    """Reconcile only explicitly connected Codex Threads; never discover/import on refresh."""
    import asyncio
    from datetime import datetime, timezone, timedelta
    from pathlib import Path
    from .storage import workspace_root
    capability=conversation_capabilities()
    if not capability['discovery'] or not capability['resume']:
        return {'supported':False,'checked':0,'new_turns':0,'updated':0,'active':0,'failed':0}

    with Session() as db:
        linked=(db.query(ThreadRecord.id,ThreadRecord.codex_thread_id,ThreadRecord.work_id)
                .join(Run,Run.conversation_id==ThreadRecord.id)
                .filter(ThreadRecord.codex_thread_id.is_not(None),Run.operation=='import').distinct().all())

    async def reconcile(entry):
        with Session() as db:
            work=db.get(Work,entry.work_id)
            if not work:return (0,0,False)
            root=workspace_root(work).resolve()
        history=await asyncio.wait_for(runner.gateway.read_thread(entry.codex_thread_id),20)
        if history.get('ephemeral') or not history.get('cwd') or Path(history['cwd']).resolve()!=root:
            raise ValueError('Runtime Thread Workspace does not match the connected Work')
        turns=history.get('turns') or []
        if not turns:raise ValueError('Connected Runtime Thread did not return its Turn history')
        def timestamp(value):
            return datetime.fromtimestamp(value,timezone.utc) if isinstance(value,(int,float)) else None
        with COMMAND_LOCK,Session() as db:
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            thread=db.get(ThreadRecord,entry.id);work=db.get(Work,entry.work_id)
            if not thread or not work or thread.codex_thread_id!=entry.codex_thread_id or workspace_root(work).resolve()!=root:
                raise ValueError('Connected Thread or Workspace changed during refresh')
            existing={run.turn_id:run for run in db.query(Run).filter_by(conversation_id=thread.id).filter(Run.turn_id.is_not(None))}
            previous=None;new_turns=0;updated=0
            for index,turn in enumerate(turns):
                turn_id=turn.get('id');status=turn.get('status')
                if not turn_id:continue
                known=existing.get(turn_id)
                if known:
                    if known.operation=='import' and status in {'completed','failed','interrupted'}:
                        final=turn.get('final_text') or ''
                        if known.final_text!=final:known.final_text=final;updated+=1
                    previous=known.id
                    continue
                if status not in {'completed','failed','interrupted'}:continue
                started=timestamp(turn.get('started_at'))
                created=started or timestamp(history.get('updated_at')) or now()+timedelta(microseconds=index)
                request=Request(id=ident('req'),work_id=work.id,instruction=turn.get('instruction') or '(기존 Codex 요청)',created_at=created)
                db.add(request);db.flush()
                mapped={'completed':'COMPLETED','failed':'FAILED','interrupted':'CANCELLED'}[status]
                run=Run(id=ident('run'),request_id=request.id,work_id=work.id,conversation_id=thread.id,
                        thread_id=entry.codex_thread_id,turn_id=turn_id,parent_run_id=previous,operation='import',
                        model=history.get('model') or '기존 Codex',reasoning=history.get('reasoning') or 'unknown',
                        status=mapped,phase=mapped,runtime_status=status,artifact_state='NONE',
                        final_text=turn.get('final_text') or '',created_at=created,started_at=started,
                        completed_at=timestamp(turn.get('completed_at')),
                        manifest=json.dumps({'imported':True,'workspace_root':str(root),'runtime_time_available':started is not None}))
                db.add(run);db.flush();existing[turn_id]=run;previous=run.id;new_turns+=1
            active=any(turn.get('status') not in {'completed','failed','interrupted'} for turn in turns)
            usage=json.loads(thread.usage or '{}')
            recent=next((turn.get('instruction') for turn in reversed(turns) if turn.get('instruction')),'')
            usage['runtime_sync']={'active':active,'last_instruction':recent,'observed_at':now().isoformat(),
                                   'updated_at':history.get('updated_at')}
            thread.usage=json.dumps(usage,ensure_ascii=False)
            thread.turn_count=max(thread.turn_count or 0,len(turns))
            if history.get('name') and thread.title!=history['name']:thread.title=history['name'];updated+=1
            if thread.status not in {'ARCHIVED','CLOSED','SUPERSEDED'}:thread.status='ACTIVE' if active else 'IDLE'
            db.commit()
            return (new_turns,updated,active)

    semaphore=asyncio.Semaphore(4)
    async def limited(entry):
        async with semaphore:
            try:return await reconcile(entry)
            except Exception:return None
    results=await asyncio.gather(*(limited(entry) for entry in linked))
    return {'supported':True,'checked':len(linked),'new_turns':sum(result[0] for result in results if result),
            'updated':sum(result[1] for result in results if result),'active':sum(bool(result[2]) for result in results if result),
            'failed':sum(result is None for result in results)}

@router.post('/conversations/{thread_id}/compact/reconcile')
async def reconcile_compaction(thread_id:str):
    with Session() as db:
        thread=row(db,ThreadRecord,thread_id)
        if thread.compact_state!='UNKNOWN':raise HTTPException(409,'No uncertain compaction to reconcile')
        runtime_id=thread.codex_thread_id
        run=db.query(Run).filter_by(conversation_id=thread.id).order_by(Run.created_at.desc()).first()
        baseline=set(json.loads(run.manifest).get('compact_before',[]))
    import asyncio
    history=await asyncio.wait_for(runner.gateway.read_thread(runtime_id),20)
    turns=history.get('turns',[])
    observed={item for turn in turns for item in turn.get('compactions',[])}
    if not observed-baseline or any(t['status'] not in {'completed','failed','interrupted'} for t in turns):
        raise HTTPException(409,'Runtime did not confirm a new completed compaction. Preserve this Thread and use a fresh Handoff.')
    with COMMAND_LOCK,Session() as db:
        thread=row(db,ThreadRecord,thread_id)
        if thread.compact_state!='UNKNOWN':raise HTTPException(409,'Compaction state changed')
        thread.compact_state='COMPLETED';db.commit();return dump(thread)

@router.get('/works/{work_id}/conversations')
def conversations(work_id:str):
    with COMMAND_LOCK,Session() as db:
        work=row(db,Work,work_id);expire_queries(db)
        threads=[dump(t) for t in db.query(ThreadRecord).filter_by(work_id=work.id).order_by(ThreadRecord.created_at.desc())]
        known={t['codex_thread_id'] for t in threads}
        # Display legacy threads without changing any existing data on read.
        for run in db.query(Run).filter_by(work_id=work.id,is_query=False).filter(Run.thread_id.is_not(None)).order_by(Run.created_at.desc()):
            if run.thread_id not in known:
                threads.append({'id':None,'legacy_run_id':run.id,'title':'기존 대화','status':'ACTIVE' if run.status in {'CREATED','RUNNING'} else 'IDLE','parent_thread_id':None,'relation_type':None,'turn_count':None,'created_at':dump(run)['created_at']})
                known.add(run.thread_id)
        queries=[{**dump(q),'run':dump(row(db,Run,q.run_id))} for q in db.query(EphemeralQuery).join(Run,Run.id==EphemeralQuery.run_id).filter(Run.work_id==work.id,EphemeralQuery.status.in_(['PENDING','READY','FAILED']))]
        db.commit()
        return {'threads':threads,'queries':queries,'packs':[pack_view(db,p) for p in db.query(ContextPack).filter_by(work_id=work.id).order_by(ContextPack.created_at.desc())]}


@router.post('/works/{work_id}/conversations',status_code=202)
async def execute(work_id:str,body:ConversationBody,http:HttpRequest):
    catalog=await catalog_from(runner.gateway)
    with COMMAND_LOCK,Session() as db:
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        work=row(db,Work,work_id)
        key=http.headers.get('idempotency-key')
        if key and len(key)>160:raise HTTPException(400,'Idempotency key too long')
        identity=(work.id+':conversation:'+key,sha(json.dumps(body.model_dump(mode='json'),sort_keys=True).encode())) if key else None
        if identity:
            existing=db.query(Run).filter_by(command_key=identity[0]).first()
            if existing:
                if existing.command_hash!=identity[1]:raise HTTPException(409,'Idempotency key was used with different input')
                return dump(existing)
        source=row(db,ThreadRecord,body.thread_id) if body.thread_id else thread_for_run(db,row(db,Run,body.from_run_id)) if body.from_run_id else None
        if source and source.work_id!=work.id:raise HTTPException(403,'Thread belongs to a different Work')
        action=body.action
        if action!='NEW' and not source and action!='QUERY':raise HTTPException(422,'Select a source Thread')
        if source and source.status=='EPHEMERAL' and action in {'CONTINUE','RESUME','COMPACT','FORK','HANDOFF'}:raise HTTPException(409,'Ephemeral query history cannot be resumed; promote selected information instead')
        same=action in {'CONTINUE','RESUME','COMPACT'}
        if same and source.status in {'CLOSED','SUPERSEDED'}:raise HTTPException(409,'This conversation is closed; create a fresh handoff or fork')
        if same and source.compact_state in {'RUNNING','UNKNOWN'}:raise HTTPException(409,'Compaction outcome is unknown; inspect Runtime state or use a fresh handoff')
        parent=latest(db,source) if same or action=='FORK' else None
        if body.from_run_id and action=='FORK' and parent.id!=body.from_run_id:raise HTTPException(409,'Exact Fork is supported only at the latest terminal turn; use a Context Pack for older results')
        strategy={'NEW':'FRESH_CONTEXT','CONTINUE':'CONTINUE_THREAD','RESUME':'CONTINUE_THREAD','COMPACT':'CONTINUE_THREAD','QUERY':'EPHEMERAL_QUERY','FORK':'FORK_THREAD','HANDOFF':'CONTEXT_PACK'}[action]
        config={'strategy':strategy,'resource_ids':body.resource_ids,'exclude_resource_ids':body.exclude_resource_ids,
                'budget':body.budget,'allow_over_budget':body.allow_over_budget,'pack_id':body.pack_id,'title':body.title,
                'include_defaults':body.include_defaults if body.include_defaults is not None else action not in {'QUERY','HANDOFF'},
                'artifact_creation':body.artifact_creation if action=='QUERY' else True,
                'context_policies':body.context_policies}
        if action=='HANDOFF':
            if not body.pack_id or not body.confirmed:raise HTTPException(409,'Preview and explicitly confirm a Context Pack for Handoff')
        if action=='COMPACT':config['compact']=True
        if action=='FORK':config.update(fork_thread_id=parent.thread_id,fork_turn_id=parent.turn_id)
        if action=='QUERY' and body.artifact_creation and not body.write_query:raise HTTPException(422,'Artifact creation requires explicitly enabling query write mode')
        profile=override(body)
        if action=='QUERY':
            permission='workspace-write' if body.write_query else 'read-only'
            if profile.get('permission') and profile['permission']!=permission:raise HTTPException(422,'Query permission must match explicit write_query mode')
            profile['permission']=permission
        relation={'FORK':'FORKED_FROM','QUERY':'QUERY_FROM','HANDOFF':'HANDOFF_FROM'}.get(action)
        if source and relation:config['context_source_thread_id']=source.id
        target=source if same else new_thread(db,work,body.title or body.instruction,source if relation else None,relation,action=='QUERY')
        run=queue(db,work,body.instruction,body.source_ids,None,None,http,'resume' if same else 'new',parent,
                  artifact_ids=body.artifact_ids,input_override=profile,catalog=catalog,context_config=config,conversation=target,commit=False,command_identity=identity)
        # Idempotent replay may have built a transient new target: roll it back.
        if run.conversation_id!=target.id:return dump(run)
        if action=='HANDOFF' and not db.query(Handoff).filter_by(run_id=run.id).first():
            pack=row(db,ContextPack,body.pack_id)
            db.add(Handoff(id=ident('handoff'),source_thread_id=source.id,target_thread_id=target.id,context_pack_id=pack.id,run_id=run.id,summary=pack.summary))
            # Supersession is recorded only after successful execution, not on enqueue.
            if body.supersede_parent:
                conf=json.loads(run.context_config);conf['supersede_parent']=source.id;run.context_config=json.dumps(conf)
        db.commit();runner.wake.set()
        return dump(run)

@router.patch('/conversations/{thread_id}')
def lifecycle(thread_id:str,body:Lifecycle):
    with COMMAND_LOCK,Session() as db:
        thread=row(db,ThreadRecord,thread_id)
        if db.query(Run).filter_by(conversation_id=thread.id).filter(Run.status.in_(['CREATED','RUNNING'])).first():raise HTTPException(409,'Thread has a queued / active Run')
        if thread.status=='EPHEMERAL':raise HTTPException(409,'Use query result actions')
        thread.status=body.status;thread.archived_at=now() if body.status in {'ARCHIVED','CLOSED','SUPERSEDED'} else None
        db.commit();return dump(thread)

@router.get('/works/{work_id}/resources')
def list_resources(work_id:str,thread_id:str|None=None):
    with Session() as db:
        work=row(db,Work,work_id)
        if thread_id and row(db,ThreadRecord,thread_id).work_id!=work.id:raise HTTPException(403,'Thread scope mismatch')
        return [dump(r) for r in resources(db,work,thread_id)]

@router.patch('/resources/{resource_id}')
def change_resource(resource_id:str,body:ResourceChange):
    from .workspace import sha
    with COMMAND_LOCK,Session() as db:
        resource=row(db,Resource,resource_id)
        for field in ('title','content','default_include'):
            value=getattr(body,field)
            if value is not None:setattr(resource,field,value)
        resource.sha256=sha(resource.content.encode());resource.version+=1;resource.updated_at=now()
        db.commit();return dump(resource)

@router.post('/runs/{run_id}/promotions',status_code=201)
def promote_answer(run_id:str,body:PromotionBody):
    with COMMAND_LOCK,Session() as db:
        run=row(db,Run,run_id)
        if run.is_query:
            query=db.query(EphemeralQuery).filter_by(run_id=run.id).one()
            if query.status=='DISPOSED':raise HTTPException(410,'Query answer was disposed')
        target=promote(db,run,body);db.commit();return dump(target)

@router.post('/works/{work_id}/context-packs',status_code=201)
def new_pack(work_id:str,body:PackBody):
    with COMMAND_LOCK,Session() as db:
        pack=create_pack(db,row(db,Work,work_id),body);db.commit();return pack_view(db,pack)

@router.post('/context-packs/{pack_id}/versions',status_code=201)
def version_pack(pack_id:str,body:PackBody):
    with COMMAND_LOCK,Session() as db:
        old=row(db,ContextPack,pack_id);pack=create_pack(db,row(db,Work,old.work_id),body,old);db.commit();return pack_view(db,pack)

@router.get('/context-packs/{pack_id}')
def preview_pack(pack_id:str):
    with Session() as db:return pack_view(db,row(db,ContextPack,pack_id))

@router.post('/context-packs/{pack_id}/confirm')
def confirm_pack(pack_id:str,body:Confirmation):
    with COMMAND_LOCK,Session() as db:
        pack=row(db,ContextPack,pack_id);pack.status='REVIEWED';db.commit();return pack_view(db,pack)

@router.get('/works/{work_id}/context-candidates')
def propose(work_id:str,thread_id:str|None=None):
    with Session() as db:
        work=row(db,Work,work_id)
        if thread_id and row(db,ThreadRecord,thread_id).work_id!=work.id:raise HTTPException(403,'Thread scope mismatch')
        artifacts=[]
        for artifact in db.query(Artifact).order_by(Artifact.created_at.desc()):
            try:admit=admit_artifact(db,artifact.id,work);artifacts.append(dump(admit))
            except ValueError:continue
        return {'goal':work.description or work.name,'current':'','completed':'','pending':'','decisions':'','blockers':'','next_instruction':'',
                'sources':[dump(s) for s in db.query(Source).filter_by(work_id=work.id)],'resources':[dump(r) for r in resources(db,work,thread_id)],'artifacts':artifacts,
                'note':'Backend 후보입니다. 필요한 항목만 선택하고 전달 내용을 검토하세요. 대화 기록은 자동 포함하지 않습니다.'}

@router.get('/runs/{run_id}/context')
def context(run_id:str):
    with Session() as db:return inspector(db,row(db,Run,run_id))

@router.post('/queries/{query_id}/decision')
async def query_decision(query_id:str,body:QueryDecision,http:HttpRequest):
    catalog=await catalog_from(runner.gateway) if body.action=='HANDOFF' else None
    with COMMAND_LOCK,Session() as db:
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        query=row(db,EphemeralQuery,query_id)
        if query.status not in {'READY','FAILED'}:raise HTTPException(409,'Query result is not available or already disposed')
        run=row(db,Run,query.run_id);result=None
        if body.action=='PROMOTE':
            if not body.promotion:raise HTTPException(422,'Select promotion content and scope')
            result=dump(promote(db,run,body.promotion))
        elif body.action=='HANDOFF':
            if not body.summary or not query.parent_thread_id:raise HTTPException(422,'A short conclusion and parent Thread are required')
            parent=row(db,ThreadRecord,query.parent_thread_id)
            if parent.status in {'CLOSED','EPHEMERAL','SUPERSEDED'} or parent.compact_state in {'RUNNING','UNKNOWN'}:raise HTTPException(409,'Parent Thread cannot continue; save the conclusion as a Resource')
            previous=latest(db,parent);work=row(db,Work,run.work_id)
            result_run=queue(db,work,'질문에서 선택한 결론:\n'+body.summary,[],None,None,http,'resume',previous,
                             input_override=override(body),catalog=catalog,context_config={'strategy':'CONTINUE_THREAD','include_defaults':False},conversation=parent,commit=False)
            from .workspace import ident
            db.add(Handoff(id=ident('handoff'),source_thread_id=query.thread_id,target_thread_id=parent.id,run_id=result_run.id,summary=body.summary))
            result=dump(result_run)
        dispose_query(db,query,body.action);db.commit();runner.wake.set();return {'query':dump(query),'result':result}
