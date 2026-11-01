"""Explicit OFFLINE fault injection at real dependencies; never returns fake API results.

Only loaded by the V32 test host, selected by a local file, no public control API.
The existing route/service/DB transaction/error persistence paths remain intact.
"""
import json
def install(application,run):
    from backend.chat import service
    from scripts.manual_naiwa_experience import FixedProvider
    from backend.services.learning_task_tools import TaskTools
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    def mode():
        p=run/'fault.json'
        value=json.loads(p.read_text(encoding='utf-8')).get('mode','none') if p.exists() else 'none'
        if value not in {'none','egress_closed','stream_broken','tool_failure','db_rollback'}:raise RuntimeError('unrecognized offline fault')
        return value
    def observed(stage):
        with (run/'fault-observations.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'simulation':True,'mode':mode(),'stage':stage,'external_requests':0})+'\n')
    class FaultProvider(FixedProvider):
        def complete(self,*args,**kwargs):
            if mode()=='egress_closed':
                from scripts.phase5_eval_meter import BudgetStop
                observed('fixed_provider_before_model_send');raise BudgetStop('paid_exit_closed')
            return super().complete(*args,**kwargs)
        async def stream(self,*args,**kwargs):
            if mode()=='stream_broken':
                import httpx
                observed('fixed_stream_after_local_delta')
                yield '【离线中断测试】这是保留的中文片段，公式 $\\frac{1}{2}$。'
                raise httpx.RemoteProtocolError('controlled offline stream interruption')
            async for text in super().stream(*args,**kwargs):yield text
    service.Provider=FaultProvider
    original=TaskTools.execute
    def execute(self,name,args):
        if mode()=='tool_failure' and name=='find_questions':
            observed('real_find_questions_dependency');raise RuntimeError('controlled offline query dependency failure')
        return original(self,name,args)
    TaskTools.execute=execute
    def cursor(conn,cursor,statement,parameters,context,executemany):
        if mode()=='db_rollback' and statement.lstrip().lower().startswith('insert into practice_items'):
            observed('before_real_practice_item_insert');raise RuntimeError('controlled offline transaction failure')
    event.listen(Engine,'before_cursor_execute',cursor)
