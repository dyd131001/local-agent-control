"""Dashboard contracts project existing state and expose existing commands."""
import asyncio
from fastapi import APIRouter, Query
from .gateway import error_text
from .operations_dashboard import read_operations
from .operations_contracts import DashboardResponse, RuntimeResponse

router=APIRouter(prefix='/api')
runner=None

def configure(worker):
    global runner
    runner=worker
    return router

async def provider_status(refresh=False):
    if refresh:
        invalidate=getattr(runner.gateway,'invalidate_runtime_status',None)
        if callable(invalidate):invalidate()
    method=getattr(runner.gateway,'runtime_status',None)
    if method is None:
        return {'connection':'UNKNOWN','observed_at':None,'rate_limits':{'status':'UNAVAILABLE','data':None,'observed_at':None},'reason':'Gateway does not provide Runtime status'}
    try:return await method()
    except Exception as exc:
        return {'connection':'UNKNOWN','observed_at':None,'rate_limits':{'status':'UNAVAILABLE','data':None,'observed_at':None},'error':error_text(exc)}

async def dashboard_data(work_id=None,category_id=None,limit=50,offset=0,include_queries=False,legacy=False,refresh_runtime=False):
    result,provider=await asyncio.gather(asyncio.to_thread(read_operations,work_id=work_id,category_id=category_id,limit=limit,offset=offset,include_queries=include_queries,legacy=legacy),provider_status(refresh_runtime))
    operations=result['operations'] if legacy else result
    operations['runtime']={'provider':provider,'dispatcher':{'running':runner.task is not None and not runner.task.done(),
                                                          'error':runner.dispatch_error,'max_parallel_tasks':runner.max_parallel_tasks},
                           'executions':operations.pop('runtime_executions'),'global_execution_block':operations['global_execution_block'],
                           'usage':operations['usage'],'note':'Settings are Run snapshots. Usage is observed Runtime data; unavailable values remain null. Thread totals are not summed.'}
    return result

@router.get('/operations/dashboard',response_model=DashboardResponse,response_model_exclude_unset=True)
async def dashboard(work_id:str|None=None,category_id:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),include_queries:bool=False,refresh_runtime:bool=False):
    return await dashboard_data(work_id,category_id,limit,offset,include_queries,refresh_runtime=refresh_runtime)

@router.get('/runtime/status',response_model=RuntimeResponse,response_model_exclude_unset=True)
async def runtime(work_id:str|None=None,category_id:str|None=None):
    data=await dashboard_data(work_id,category_id,200)
    return {'contract_version':1,'generated_at':data['generated_at'],'scope':data['scope'],**data['runtime']}
