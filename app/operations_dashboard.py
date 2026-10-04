"""Read-only projection of existing operations. No scheduler or execution ownership."""
import json
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import case, func
from .db import (Approval, Artifact, ArtifactReview, Category, ContextPack, ContextPackItem,
                 DelayedResume, Event, Request, RequestQueue, Resource, Run, ScheduleFire, Session, Source, TaskRun,
                 ThreadRecord, Work, WorkflowDefinition, WorkflowRun, WorkflowSchedule, dump, now, read_snapshot)
from .execution_settings import legacy_profile

STATES=('RUNNING','QUEUED','FAILED','WAITING_APPROVAL','PAUSED','SCHEDULED','RECOVERY_REQUIRED','CONTEXT_WARNING')
ACTIVE={'CREATED','RUNNING'}

def iso(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None

def obj(value, default=None):
    try:return json.loads(value) if value else ({} if default is None else default)
    except (TypeError,ValueError):return {} if default is None else default

def extracted(column, path):
    # Select only operational fields, never multi-MiB frozen context bytes / answers.
    return func.json_extract(case((func.json_valid(column),column),else_='{}'),path)

def action(name,path,method='GET',**extra):return {'name':name,'method':method,'path':path,**extra}

def page(items,limit,offset):
    return {'total':len(items),'items':items[offset:offset+limit],'offset':offset,'limit':limit,'has_more':offset+limit<len(items)}

def aggregate(db, *, work_id=None,category_id=None,limit=50,offset=0,include_queries=False):
    read_snapshot(db)
    works_query=db.query(Work)
    if work_id:
        if not db.get(Work,work_id):raise HTTPException(404,'Work not found')
        works_query=works_query.filter_by(id=work_id)
    if category_id:
        if not db.get(Category,category_id):raise HTTPException(404,'Category not found')
        works_query=works_query.filter_by(category_id=category_id)
    works={w.id:w for w in works_query.order_by(Work.created_at.desc())}
    work_ids=list(works)
    workflows={w.id:w for w in db.query(WorkflowRun).filter(WorkflowRun.work_id.in_(work_ids)).order_by(WorkflowRun.created_at.desc(),WorkflowRun.id)}
    definitions={d.id:d for d in db.query(WorkflowDefinition).filter(WorkflowDefinition.work_id.in_(work_ids))}
    attempts=db.query(TaskRun).filter(TaskRun.workflow_run_id.in_(workflows)).order_by(TaskRun.attempt_number.desc(),TaskRun.created_at.desc()).all()
    current={}
    for t in attempts:current.setdefault((t.workflow_run_id,t.task_definition_id),t)
    current_ids={t.id for t in current.values()}
    tasks_by_run={t.run_id:t for t in current.values() if t.run_id}
    all_task_runs={t.run_id:t for t in attempts if t.run_id}
    approvals={a.task_run_id:a for a in db.query(Approval).filter(Approval.task_run_id.in_(current_ids))}
    columns=[Run.id,Run.work_id,Run.request_id,Run.parent_run_id,Run.conversation_id,Run.thread_id,Run.turn_id,
             Run.model,Run.reasoning,Run.execution_profile,Run.status,Run.phase,Run.runtime_status,Run.safety_block,
             Run.error,Run.operation,Run.is_query,Run.created_at,Run.started_at,Run.completed_at,
             extracted(Run.manifest,'$.context_budget').label('budget'),
             extracted(Run.context_config,'$.budget_report').label('queued_budget'),
             extracted(Run.context_config,'$.tool_context').label('tool_context'),
             extracted(Run.manifest,'$.context_strategy').label('strategy'),
             extracted(Run.context_config,'$.strategy').label('queued_strategy')]
    runs=[dict(r._mapping) for r in db.query(*columns).filter(Run.work_id.in_(work_ids),Run.operation!='reference').order_by(Run.created_at.desc(),Run.id)]
    buckets={s:[] for s in STATES}; run_cards=[]; context_cards=[]; workflow_cards=[]
    def item(entity_type,key,state,wid,title,at,**fields):
        return {'entity_type':entity_type,'id':key,'state':state,'work_id':wid,'work_name':works[wid].name,
                'category_id':works[wid].category_id,'title':title,'updated_at':iso(at),**fields}
    latest_request={}
    for r in runs:latest_request.setdefault(r['request_id'],r['id'])
    for r in runs:
        task=all_task_runs.get(r['id']);old_attempt=task is not None and r['id'] not in tasks_by_run
        visible_query=include_queries or not r['is_query'] or r['status'] in ACTIVE or r['safety_block']
        if not visible_query:continue
        state='RECOVERY_REQUIRED' if r['safety_block'] or r['phase']=='RECOVERING' else 'QUEUED' if r['status']=='CREATED' and r['phase']=='QUEUED' else 'RUNNING' if r['status'] in ACTIVE else r['status']
        settings=obj(r['execution_profile']) or legacy_profile(r['model'],r['reasoning'])
        budget=obj(r['budget']) or obj(r['queued_budget'])
        paused=bool(task and workflows[task.workflow_run_id].paused and not workflows[task.workflow_run_id].cancel_requested and workflows[task.workflow_run_id].status not in {'COMPLETED','FAILED','CANCELLED','REJECTED'})
        links=[action('run','/api/runs/'+r['id']),action('context','/api/runs/'+r['id']+'/context')]
        if task:links.append(action('workflow','/api/workflow-runs/'+task.workflow_run_id))
        if r['safety_block']:links.append(action('reconcile','/api/runs/'+r['id']+'/reconcile','POST'))
        elif r['status'] in ACTIVE:links.append(action('cancel','/api/runs/'+r['id']+'/cancel','POST'))
        elif r['status']=='FAILED' and not old_attempt and not r['is_query']:
            links.append(action('retry','/api/task-runs/'+task.id+'/retry' if task else '/api/requests/'+r['request_id']+'/retry','POST',body_kind='execution_profile'))
        card=item('RUN',r['id'],state,r['work_id'],'임시 질문' if r['is_query'] else 'AI Review' if obj(r['tool_context']).get('kind')=='REVIEW' else ('Workflow Task' if task else 'Run'),r['completed_at'] or r['started_at'] or r['created_at'],
                  status=r['status'],phase=r['phase'],runtime_status=r['runtime_status'],execution_settings=settings,
                  settings_source='resolved_run_snapshot' if r['execution_profile'] else 'legacy_run_columns_and_app_policy',is_query=r['is_query'],request_id=r['request_id'],
                  conversation_id=r['conversation_id'],workflow_run_id=task.workflow_run_id if task else None,
                  task_run_id=task.id if task else None,blocked_by_pause=paused,error=obj(r['error']),
                  context={'budget':budget or None,'strategy':r['strategy'] or r['queued_strategy'],'source':'provided_context_manifest'},actions=links)
        run_cards.append(card)
        if state in {'RUNNING','QUEUED','RECOVERY_REQUIRED'} or (state=='FAILED' and not old_attempt and latest_request[r['request_id']]==r['id']):buckets[state].append(card)
        warnings=budget.get('warnings',[])
        if warnings and not old_attempt:
            warning={**card,'state':'CONTEXT_WARNING','warnings':warnings}
            context_cards.append(warning);buckets['CONTEXT_WARNING'].append(warning)
    approval_cards=[]
    for (wrid,_),task in current.items():
        wr=workflows[wrid];review=approvals.get(task.id)
        if task.status=='COMPLETED' and review and review.status=='WAITING' and not wr.cancel_requested:
            card=item('APPROVAL',review.id,'WAITING_APPROVAL',wr.work_id,'결과 확인 대기',review.created_at,
                      task_run_id=task.id,workflow_run_id=wr.id,policy=review.policy,blocks_downstream=review.policy=='APPROVAL_REQUIRED',
                      actions=[action('workflow','/api/workflow-runs/'+wr.id),action('decision','/api/approvals/'+review.id+'/decision','POST',choices=['APPROVE','APPROVE_PUBLISH','REJECT','REVISION'])])
            approval_cards.append(card);buckets['WAITING_APPROVAL'].append(card)
        if not task.run_id and task.status in {'READY','BLOCKED','FAILED'}:
            state='FAILED' if task.status=='FAILED' else 'QUEUED'
            card=item('TASK',task.id,state,wr.work_id,'Workflow Task 대기' if state=='QUEUED' else 'Workflow Task 실패',task.completed_at or task.created_at,
                      workflow_run_id=wr.id,status=task.status,blocked_by_pause=wr.paused,blocked_reason=obj(task.blocked_reason),error=obj(task.error),
                      actions=[action('workflow','/api/workflow-runs/'+wr.id)])
            buckets[state].append(card)
    for wr in workflows.values():
        tasks=[t for (wid,_),t in current.items() if wid==wr.id]
        counts=Counter(t.status for t in tasks);waiting=[approvals[t.id] for t in tasks if t.id in approvals and approvals[t.id].status=='WAITING' and t.status=='COMPLETED']
        completed=counts['COMPLETED'];total=len(tasks)
        effective_paused=wr.paused and not wr.cancel_requested and wr.status not in {'COMPLETED','FAILED','CANCELLED','REJECTED'}
        links=[action('workflow','/api/workflow-runs/'+wr.id)]
        if effective_paused:links.append(action('resume','/api/workflow-runs/'+wr.id+'/resume','POST'))
        elif wr.status in {'CREATED','RUNNING','WAITING_APPROVAL'}:links.append(action('pause','/api/workflow-runs/'+wr.id+'/pause','POST'))
        if wr.status in {'CREATED','RUNNING','WAITING_APPROVAL','PAUSED'}:links.append(action('cancel','/api/workflow-runs/'+wr.id+'/cancel','POST'))
        card=item('WORKFLOW',wr.id,'PAUSED' if effective_paused else wr.status,wr.work_id,definitions[wr.workflow_definition_id].name if wr.workflow_definition_id in definitions else 'Workflow',wr.completed_at or wr.started_at or wr.created_at,
                  status=wr.status,paused=effective_paused,pause_requested=wr.paused,progress={'total':total,'completed':completed,'completion_percent':round(completed/total*100,1) if total else None,'by_status':dict(counts),
                  'waiting_approvals':len(waiting),'blocking_approvals':sum(a.policy=='APPROVAL_REQUIRED' for a in waiting)},
                  tasks=[{'id':t.id,'task_definition_id':t.task_definition_id,'attempt_number':t.attempt_number,'status':t.status,'run_id':t.run_id} for t in tasks],actions=links)
        workflow_cards.append(card)
        if effective_paused:buckets['PAUSED'].append(card)
        if wr.status=='FAILED':buckets['FAILED'].append(card)
    scheduled=[]
    schedules={s.id:s for s in db.query(WorkflowSchedule).filter(WorkflowSchedule.workflow_definition_id.in_(definitions))}
    for s in schedules.values():
        if s.enabled and s.next_fire_at:
            definition=definitions[s.workflow_definition_id]
            card=item('SCHEDULE',s.id,'SCHEDULED',definition.work_id,definition.name,s.next_fire_at,
                      due_at=iso(s.next_fire_at),kind=s.kind,interval_seconds=s.interval_seconds,misfire_policy=s.misfire_policy,
                      actions=[action('schedule','/api/schedules/'+s.id),action('disable','/api/schedules/'+s.id,'PATCH',body={'enabled':False})])
            scheduled.append(card);buckets['SCHEDULED'].append(card)
    for fire in db.query(ScheduleFire).filter(ScheduleFire.schedule_id.in_(schedules),ScheduleFire.status.in_(['CLAIMED','FAILED'])):
        s=schedules[fire.schedule_id];definition=definitions[s.workflow_definition_id];state='FAILED' if fire.status=='FAILED' else 'SCHEDULED'
        card=item('SCHEDULE_FIRE',fire.id,state,definition.work_id,definition.name,fire.scheduled_for,due_at=iso(fire.scheduled_for),status=fire.status,retry_at=iso(fire.retry_at),error=fire.error,
                  actions=[action('schedule','/api/schedules/'+s.id)])
        if state=='SCHEDULED':scheduled.append(card)
        buckets[state].append(card)
    task_ids={t.id:t for t in attempts}
    for delay in db.query(DelayedResume).filter(DelayedResume.source_task_run_id.in_(task_ids),DelayedResume.status.in_(['PENDING','FAILED'])):
        task=task_ids[delay.source_task_run_id];wr=workflows[task.workflow_run_id];state='SCHEDULED' if delay.status=='PENDING' else 'FAILED'
        card=item('DELAYED_RESUME',delay.id,state,wr.work_id,'지연 이어하기',delay.due_at,due_at=iso(delay.due_at),status=delay.status,error=delay.error,
                  actions=[action('workflow','/api/workflow-runs/'+wr.id)]+([action('cancel','/api/delayed-resumes/'+delay.id+'/cancel','POST')] if state=='SCHEDULED' else []))
        if state=='SCHEDULED':scheduled.append(card)
        buckets[state].append(card)
    queue_columns = [RequestQueue.id, RequestQueue.work_id, RequestQueue.status, RequestQueue.condition,
                     RequestQueue.due_at, RequestQueue.created_at, RequestQueue.predecessor_run_id,
                     RequestQueue.blocked_reason, RequestQueue.execution_profile,
                     func.substr(Request.instruction, 1, 120).label('instruction')]
    for job in db.query(*queue_columns).join(Request, Request.id == RequestQueue.request_id).filter(
            RequestQueue.work_id.in_(work_ids), RequestQueue.status.in_(['PENDING', 'BLOCKED'])):
        state = 'SCHEDULED' if job.status == 'PENDING' else 'QUEUED'
        card = item('REQUEST_QUEUE', job.id, state, job.work_id,
                    ('BLOCKED · ' if job.status == 'BLOCKED' else '') + job.instruction, job.due_at or job.created_at,
                    due_at=iso(job.due_at), condition=job.condition, status=job.status,
                    predecessor_run_id=job.predecessor_run_id, blocked_reason=job.blocked_reason,
                    execution_settings=obj(job.execution_profile),
                    actions=[action('queue', '/api/works/'+job.work_id+'/request-queue'),
                             action('cancel', '/api/request-queue/'+job.id+'/cancel', 'POST'),
                             action('execute', '/api/request-queue/'+job.id+'/execute', 'POST')])
        scheduled.append(card); buckets[state].append(card)
    # Freshness here uses registered metadata only; preview API verifies physical file bytes.
    packs={p.id:p for p in db.query(ContextPack).filter(ContextPack.work_id.in_(work_ids))}
    source_hashes={s.id:s.sha256 for s in db.query(Source.id,Source.sha256).filter(Source.work_id.in_(work_ids))}
    artifact_hashes={a.id:a.sha256 for a in db.query(Artifact.id,Artifact.sha256)}
    resource_hashes={r.id:(r.sha256,r.version) for r in db.query(Resource.id,Resource.sha256,Resource.version)}
    pack_states=defaultdict(set)
    for p in packs.values():
        if p.estimated_size>p.budget:pack_states[p.id].add('PACK_OVER_BUDGET')
        if now()-p.created_at.replace(tzinfo=p.created_at.tzinfo or timezone.utc)>timedelta(days=30):pack_states[p.id].add('PACK_STALE')
    for i in db.query(ContextPackItem.context_pack_id,ContextPackItem.source_type,ContextPackItem.source_id,ContextPackItem.source_hash,ContextPackItem.source_version).filter(ContextPackItem.context_pack_id.in_(packs)):
        current_hash=source_hashes.get(i.source_id) if i.source_type=='SOURCE' else artifact_hashes.get(i.source_id) if i.source_type=='ARTIFACT' else resource_hashes.get(i.source_id,(None,None))[0]
        if current_hash is None:pack_states[i.context_pack_id].add('PACK_MISSING')
        elif current_hash!=i.source_hash or (i.source_type=='RESOURCE' and resource_hashes[i.source_id][1]!=i.source_version):pack_states[i.context_pack_id].add('PACK_CHANGED')
    for pid,codes in pack_states.items():
        if not codes:continue
        p=packs[pid];card=item('CONTEXT_PACK',pid,'CONTEXT_WARNING',p.work_id,p.name,p.created_at,version=p.version,warnings=sorted(codes),
                              freshness_source='registered_metadata_and_age; preview verifies filesystem',actions=[action('preview','/api/context-packs/'+pid)])
        context_cards.append(card);buckets['CONTEXT_WARNING'].append(card)
    for thread in db.query(ThreadRecord).filter(ThreadRecord.work_id.in_(work_ids)):
        if thread.status in {'CLOSED','SUPERSEDED','EPHEMERAL'}:continue
        usage=obj(thread.usage)
        runtime_sync=usage.get('runtime_sync') or {}
        if thread.status!='ARCHIVED' and runtime_sync.get('active') and not any(r['conversation_id']==thread.id and r['status'] in ACTIVE for r in runs):
            card=item('THREAD',thread.id,'RUNNING',thread.work_id,thread.title,now(),
                      last_request=runtime_sync.get('last_instruction'),source='connected_codex_thread',
                      actions=[action('conversations','/api/works/'+thread.work_id+'/conversations')])
            buckets['RUNNING'].append(card)
        if thread.compact_state in {'UNKNOWN','RUNNING'}:
            card=item('THREAD',thread.id,'RECOVERY_REQUIRED' if thread.compact_state=='UNKNOWN' else 'RUNNING',thread.work_id,thread.title,thread.created_at,compact_state=thread.compact_state,
                      actions=[action('conversations','/api/works/'+thread.work_id+'/conversations')]+([action('reconcile_compaction','/api/conversations/'+thread.id+'/compact/reconcile','POST')] if thread.compact_state=='UNKNOWN' else []))
            if thread.compact_state=='UNKNOWN':buckets['RECOVERY_REQUIRED'].append(card)
        codes=[]
        if thread.turn_count>=20:codes.append('LONG_THREAD_HANDOFF_RECOMMENDED')
        if thread.compact_state=='COMPLETED':codes.append('COMPACTED_THREAD_HANDOFF_RECOMMENDED')
        last=usage.get('last',{});window=usage.get('model_context_window')
        if window and last.get('totalTokens',0)>window*.8:codes.append('RUNTIME_CONTEXT_HIGH')
        if codes:
            card=item('THREAD',thread.id,'CONTEXT_WARNING',thread.work_id,thread.title,thread.created_at,warnings=codes,actions=[action('conversations','/api/works/'+thread.work_id+'/conversations')])
            context_cards.append(card);buckets['CONTEXT_WARNING'].append(card)
    # Per-Run last-turn usage is distinct from cumulative thread totals. Never add cumulative totals together.
    latest_usage={}
    for e in db.query(Event.id,Event.run_id,Event.payload,Event.created_at).join(Run,Event.run_id==Run.id).filter(Run.work_id.in_(work_ids),Event.type=='CONTEXT_USAGE').order_by(Event.id.desc()):
        if e.run_id not in latest_usage:
            p=obj(e.payload);latest_usage[e.run_id]={'run_id':e.run_id,'last_turn':p.get('last'),'thread_total':p.get('total'),'model_context_window':p.get('model_context_window'),
                                                       'observed_at':iso(e.created_at),'source':'runtime_notification'}
    for card in run_cards:card['usage']=latest_usage.get(card['id'])
    artifacts=[]
    reviews={r.artifact_id:r.status for r in db.query(ArtifactReview)}
    for a in db.query(Artifact).filter(Artifact.work_id.in_(work_ids)).order_by(Artifact.created_at.desc(),Artifact.id).limit(offset+limit+1):
        artifacts.append({'id':a.id,'work_id':a.work_id,'work_name':works[a.work_id].name,'run_id':a.run_id,'name':a.name,'size':a.size,'partial':a.partial,
                          'availability':a.availability,'review_status':reviews.get(a.id),'created_at':iso(a.created_at),
                          'actions':[action('artifact','/api/artifacts/'+a.id),action('download','/api/artifacts/'+a.id+'/download')]})
    artifact_total=db.query(Artifact).filter(Artifact.work_id.in_(work_ids)).count()
    for s in STATES:buckets[s].sort(key=lambda x:(x['updated_at'] or '',x['entity_type'],x['id']),reverse=s not in {'SCHEDULED','WAITING_APPROVAL'})
    scheduled.sort(key=lambda x:(x['due_at'] or x['updated_at'] or '',x['id']))
    summary={s:{'total':len(buckets[s]),'by_entity_type':dict(Counter(x['entity_type'] for x in buckets[s]))} for s in STATES}
    recovery_global=db.query(Run.id).filter(Run.safety_block.is_(True)).count()
    return {'contract_version':1,'generated_at':iso(now()),'scope':{'work_id':work_id,'category_id':category_id,'include_queries':include_queries},
            'summary':summary,'states':{s:page(buckets[s],limit,offset) for s in STATES},'workflows':page(workflow_cards,limit,offset),
            'approvals':page(approval_cards,limit,offset),'scheduled':page(scheduled,limit,offset),'context_warnings':page(context_cards,limit,offset),
            'recent_runs':page([r for r in run_cards if include_queries or not r['is_query']],limit,offset),
            'recent_artifacts':{'total':artifact_total,'items':artifacts[offset:offset+limit],'offset':offset,'limit':limit,'has_more':offset+limit<artifact_total},
            'runtime_executions':sorted([r for r in run_cards if r['status'] in ACTIVE or r['state']=='RECOVERY_REQUIRED'],key=lambda r:{'RUNNING':0,'QUEUED':1,'RECOVERY_REQUIRED':2}.get(r['state'],3)),
            'usage':page(list(latest_usage.values()),limit,offset),'global_execution_block':{'blocked':bool(recovery_global),'recovery_run_count':recovery_global},
            'goal':{'status':'NOT_INTEGRATED','value':None},'count_semantics':'Entity counts; a Workflow and its failed Run may describe the same incident. Current Task attempts only. Query history excluded by default; active / recovery queries remain visible.'}


def read_operations(*, legacy=False, **kwargs):
    with Session() as db:
        operations=aggregate(db,**kwargs)
        if not legacy:return operations
        from .workflow_operations_api import monitoring
        return {'categories':[dump(x) for x in db.query(Category).order_by(Category.created_at.desc())],
                'works':[dump(x) for x in db.query(Work).order_by(Work.created_at.desc())],
                'runs':[dump(x) for x in db.query(Run).filter_by(is_query=False).order_by(Run.created_at.desc()).limit(30)],
                'artifacts':[dump(x) for x in db.query(Artifact).order_by(Artifact.created_at.desc()).limit(20)],
                'monitoring':monitoring(db),'operations':operations}
