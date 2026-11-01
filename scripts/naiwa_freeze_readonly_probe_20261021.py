"""Stage1 only: read-only business resolution; no messages or models."""
from pathlib import Path
import sys,json
from datetime import datetime,timezone
from uuid import UUID,uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from scripts.naiwa_freeze_preflight_20261021 import OUT,save,database_url,existing_manager
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message
from backend.services.learning_assistant_service import planner_handoff
from backend.services.learning_task_tools import TaskTools
from backend.services.personal_generation_intent import explicitly_generate,_preferences
from backend.models.learning import KnowledgePoint

A='我今天有90分钟，请根据我最近的错题和薄弱知识点，给我安排数学二整体复习建议。不要只复习当前这道题，也不要只围绕洛必达法则。先给建议，未经我确认不要创建计划。'
B='根据我当前这道题，生成一道真正更难、考点相关的类似题。请保证题干、选项、答案和解析一致，只生成一道，不要自动加入今日学习。'
engine=create_engine(database_url(existing_manager()),connect_args={'options':'-c default_transaction_read_only=on'})
factory=sessionmaker(engine)
ctx=StudyContext(surface='study',subject='考研数学',knowledge_node_ids=[UUID('32a29e1e-8ae3-41fc-9322-43f727596819')],
    question_id=UUID('9ba9c177-26a2-4918-bf84-b85159f9b002'),question_version_id=UUID('92c57d4d-f0bf-4df2-b9b2-c949a3d43904'),
    conversation_id=UUID('e49210f4-d5c8-4d61-a6c1-05c216c80ee0'))
now=datetime.now(timezone.utc)
route=route_message(A,ctx)
assert (route.capability,route.intent)==('planner','recommend'),route
h=planner_handoff(factory,ctx=ctx,user_id=uuid4(),message=A,route=route,now=now)
assert h.constraints['scope_origin']=='explicit_subject_scope',h.constraints
with factory() as db:
    nodes=[{'id':str(n.id),'code':n.code,'name':n.name,'subject':n.subject} for n in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_([UUID(v) for v in h.constraints['resolved_scope_node_ids']])))]
assert len(nodes)>1 and all(n['subject']=='考研数学' for n in nodes),nodes
tools=TaskTools(factory,budget_minutes=90,now=now,goal=A,handoff=h.model_dump(mode='json'))
inventory=tools.execute('get_question_availability',{})
assert explicitly_generate(B)
difficulty,types=_preferences(B)
assert sum(c for _,c in types)==1
baseline=json.loads((OUT/'database-before.json').read_text(encoding='utf-8'))
archive=['# 原体验站历史消息只读副本','',
    '这是数据库原始正文的只读导出，不是新增 Vue 会话，也不是新的模型回复。',
    '旧资料搜索会话因日内过期规则无法通过当前历史 API 打开；原始记录未删除。','']
for session in baseline['chat_sessions']:
    archive += ['## '+session['title'],'',f"会话：{session['id']}；用途：{session['purpose']}",'']
    for message in sorted((m for m in baseline['chat_messages'] if m['session_id']==session['id']),key=lambda m:m['seq']):
        archive += [f"### {message['role']} · {message['status']}",'',message['content'] or '（无正文）','']
(OUT/'HISTORY_READONLY.md').write_text('\n'.join(archive),encoding='utf-8')
version=next(v for v in baseline['question_versions'] if v['id']==str(ctx.question_version_id))
assert version['question_id']==str(ctx.question_id)
save(OUT/'exact-input-probe.json',{'status':'PASS','mode':'read-only SQL; no Provider; no chat submission',
    'A':{'input':A,'route':route.public_dict(),'handoff':h.model_dump(mode='json'),'resolved_nodes':nodes,'inventory_tool_result':inventory},
    'B':{'input':B,'explicit_generation':True,'count':1,'difficulty':difficulty,'types':types,'question_id':str(ctx.question_id),'question_version_id':str(ctx.question_version_id),'version_snapshot':version},
    'real_model_requests':0,'database_writes':0})
engine.dispose()
print(json.dumps({'status':'PASS','route':route.intent,'scope_origin':h.constraints['scope_origin'],'node_count':len(nodes),'generation_count':1,'real_requests':0}))
