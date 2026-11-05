"""Phase4C factual check: at most 12 real requests, synthetic materials/state only.

Existing public unused question content may be included. All data creation and
Planner confirmation run inside a transaction that is rolled back. No rerun.
"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from uuid import UUID,uuid4
from hashlib import sha256
import argparse,asyncio,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from backend.services.model_settings_service import load_local_settings
from backend.chat.service import provider_from_settings
from backend.models.chat import ChatSession,ChatMessage
from backend.models.learning import Question,KnowledgePoint,KpState,QuestionAttempt,DailyPlan,PracticeItem
from backend.models.practice_request import PracticeRequest
from backend.schemas.learning_assistant import AssistantRequest,StudyContext
from backend.schemas.learning_task import ConfirmTask
from backend.services.question_eligibility import question_eligibility
from backend.services.learning_assistant_service import assistant_stream
from backend.services.practice_request_service import send_request,plan_request
from backend.services.deep_qa_handoff_service import create_deep_qa
from backend.services.learning_task_service import confirm_task
from backend.services.answer_submission_service import submit_answer
from scripts.evaluate_phase4_learning_assistant import LimitedProvider,Alive
from scripts.expand_phase3b_inventory import protected_fingerprints,dump
from backend.models.rag import Material,DocumentChunk
from backend.retrieval.protocols import VectorRecord
from backend.retrieval.embedding import FakeEmbedder
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.rerank import IdentityReranker
from backend.retrieval.stack import RetrievalStack
from backend.retrieval.vector_store import InMemoryVectorStore

def create_material(db,*,title,body,source_type):
    material=Material(title=title,source_type=source_type,stored_path=f'evaluation/{uuid4()}/source.md',normalized_text=body,
        content_hash=sha256(body.encode()).hexdigest(),raw_hash=sha256(body.encode()).hexdigest(),file_size=len(body.encode()),status='ready',active_index_version='phase4c-isolated-v1')
    db.add(material);db.flush();return material
def create_chunk(db,material,*,content,ordinal):
    chunk=DocumentChunk(material_id=material.id,index_version=material.active_index_version,ordinal=ordinal,content=content,
        start_offset=0,end_offset=len(content),heading_path=[],content_hash=sha256(content.encode()).hexdigest())
    db.add(chunk);db.flush();return chunk

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--targeted',action='store_true');parser.add_argument('--max-requests',type=int,default=12);args=parser.parse_args()
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):parser.error('new report under tmp required')
    used=sum(json.loads(p.read_text(encoding='utf-8')).get('model_calls',0) for p in (ROOT/'tmp/phase4c_20261007').glob('factual-*.json'))
    if args.execute and not 1<=args.max_requests<=12-used:parser.error('phase4c aggregate budget exceeded')
    settings=load_local_settings(get_settings());engine=create_db_engine(str(settings.active_database_url));normal=create_session_factory(engine)
    if settings.app_env=='test':raise RuntimeError('evaluation must not import or inherit pytest environment; refusing test database')
    with normal() as db:
        baseline=protected_fingerprints(db);occupied=set(db.scalars(select(DailyPlan.study_date)))
        attempted=set(db.scalars(select(QuestionAttempt.kp_id).distinct()));groups={}
        for q in db.scalars(select(Question).order_by(Question.id)):
            node=db.get(KnowledgePoint,q.kp_id);state=db.get(KpState,q.kp_id)
            if q.kp_id in attempted or (state and (state.node_self_grade is not None or state.evidence_window or state.manual_credit_count)):continue
            if question_eligibility(q,node).practice_eligible:groups.setdefault(q.kp_id,[]).append(q.id)
        nid,ids=next((nid,ids) for nid,ids in groups.items() if len(ids)>=2 and db.get(KnowledgePoint,nid).subject=='考研数学')
        qids=ids[:2]
    report={'version':'phase4c-factual-v2-targeted' if args.targeted else 'phase4c-factual-v2','model':settings.llm_model,'maximum_requests':args.max_requests,'private_materials_sent':False,'real_user_records_sent':False,
        'database_environment':settings.app_env,'database_name':str(settings.active_database_url).rsplit('/',1)[-1],
        'retrieval':'real hybrid pipeline with isolated InMemoryVectorStore/FakeEmbedder; not production embedding-quality evaluation','cases':[],
        'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'model_calls':0}
    if not args.execute:dump(output,{**report,'mode':'dry_run'});return
    connection=engine.connect();outer=connection.begin();factory=sessionmaker(bind=connection,expire_on_commit=False,autoflush=False,join_transaction_mode='create_savepoint')
    provider=LimitedProvider(provider_from_settings(settings),limit=args.max_requests)
    now=datetime(2099,4,1,4,tzinfo=timezone.utc)
    while now.date().isoformat() in occupied:now+=timedelta(days=1)
    embedder=FakeEmbedder(dimension=64);stack=RetrievalStack(embedder=embedder,vector_store=InMemoryVectorStore(embedding_model=embedder.model_name),keyword_index=KeywordIndex(),reranker=IdentityReranker())
    with factory.begin() as db:
        qa=ChatSession(mode='builtin',purpose='qa',title='Phase4C合成评测');study=ChatSession(mode='builtin',purpose='study',study_date=now.date().isoformat());plan=DailyPlan(study_date=now.date().isoformat(),status='active')
        db.add_all([qa,study,plan]);db.flush();qa_id=qa.id;study_id=study.id
        q=db.get(Question,qids[0]);item=PracticeItem(plan_id=plan.id,question_id=q.id,kp_id=q.kp_id,ordinal=1);db.add(item);db.flush()
        if db.get(KpState,q.kp_id) is None:db.add(KpState(kp_id=q.kp_id));db.flush()
        wrong=next((k for k in q.options or {} if k!=q.correct_answer),'987654321')
        attempt=submit_answer(db,item_id=item.id,selected_option=wrong if q.options else None,raw_answer=None if q.options else wrong,idempotency_key=str(uuid4()),now=now)
        ctx=StudyContext(surface='chat',question_id=q.id,practice_item_id=item.id,daily_plan_id=plan.id,attempt_id=attempt.attempt_id,knowledge_node_ids=[q.kp_id])
        records=[];material_ids=[]
        for title,content,source in [('Phase4C合成队列讲义','环形队列使用count记录元素数，count==capacity时队满，count==0时队空。插入后count加1。','builtin'),
            ('Phase4C合成私人笔记','这份合成笔记规定实验缓冲区采用count==capacity判断满，满时拒绝继续插入。','user'),
            ('Phase4C未选合成笔记','PRIVATE_UNSELECTED_SENTINEL：实验缓冲区满时应覆盖所有数据，这是未选择资料里的说法。','user')]:
            material=create_material(db,title=title,body=content,source_type=source);chunk=create_chunk(db,material,content=content,ordinal=0)
            material_ids.append(material.id);records.append(VectorRecord(chunk_id=chunk.id,material_id=material.id,index_version=chunk.index_version,ordinal=0,content=content,heading_path=(),source_type=source))
        private=ChatSession(mode='user',purpose='materials',material_scope_ids=[str(material_ids[1])]);db.add(private);db.flush();private_id=private.id
    stack.vector_store.upsert(records,embedder.encode([r.content for r in records]));stack.keyword_index.rebuild(records)
    async def ask(case,sid,question,context,action='auto'):
        before=provider.calls;frames=[]
        async for raw in assistant_stream(factory,request=Alive(),session_id=sid,body=AssistantRequest(question=question,study_context=context,qa_action=action),stack=stack,provider=provider,now=now):
            lines=raw.decode().splitlines();frames.append((lines[0].removeprefix('event: '),json.loads(lines[1].removeprefix('data: '))))
        done=next((d for e,d in reversed(frames) if e=='done'),{});error=next((d for e,d in frames if e=='error'),None)
        mid=next((d.get('message_id') for e,d in frames if e=='meta'),done.get('message_id'))
        with factory() as db:meta=dict(db.get(ChatMessage,UUID(mid)).metadata_) if mid else {}
        entry={'case':case,'calls':provider.calls-before,'completion':'error' if error else 'completed','answer':done.get('answer'),'citations':done.get('citations',[]),
            'error':error,'generation_trace':meta.get('generation_trace'),'learning_trace':meta.get('learning_trace'),'information_route':meta.get('qa_information_route'),
            'assistance_level':meta.get('assistance_level'),'practice_request':next((d for e,d in frames if e=='practice_request'),None)}
        report['cases'].append(entry);report['model_calls']=provider.calls;dump(output,report);print(json.dumps({'case':case,'calls':provider.calls,'completion':entry['completion']}),flush=True)
        return entry
    try:
        if not args.targeted:asyncio.run(ask('general_qa',qa_id,'Python async/await为什么存在？',StudyContext()))
        if not args.targeted:
            asyncio.run(ask('builtin_rag',qa_id,'根据Phase4C合成队列讲义，如何区分队满和队空？',StudyContext(material_id=material_ids[0])))
            asyncio.run(ask('current_question_hint',study_id,'给当前题一点方向，不要透露最终答案。',ctx,'hint_1'))
        asyncio.run(ask('evidence_explanation',qa_id,'这个知识点为什么还没毕业？请区分实际作答记录和系统可靠题库不足。',ctx))
        drafted=asyncio.run(ask('practice_request',qa_id,'给我补1道这种题。',ctx))
        if drafted['practice_request']:
            rid=UUID(drafted['practice_request']['id']);send_request(factory,rid,source_conversation_id=qa_id,now=now);before=provider.calls
            proposed=plan_request(factory,rid,study_session_id=study_id,provider=provider,now=now)
            report['cases'].append({'case':'planner_request','calls':provider.calls-before,'request':proposed['request'],'task':proposed['task'],'completion':proposed['request']['status']})
            if proposed['request']['status']=='proposed':
                task=proposed['task'];first=confirm_task(factory,UUID(task['task_id']),ConfirmTask(draft_version=task['draft_version']),now=now);second=confirm_task(factory,first.task_id,ConfirmTask(draft_version=task['draft_version']),now=now)
                report['confirmation']={'added':first.metrics['commit']['added_count'],'idempotent':first.metrics['commit']==second.metrics['commit']}
        asyncio.run(ask('web_unavailable',qa_id,'2027考研最新大纲是否有变化？请联网查。',StudyContext()))
        if not args.targeted:asyncio.run(ask('private_scope',private_id,'根据这份合成私人笔记，实验缓冲区满时怎么办？',StudyContext(surface='materials',material_id=material_ids[1])))
        handoff=create_deep_qa(factory,source_session_id=study_id,context=ctx,learning_problem='请详细讲解刚才的问题',request_key=uuid4(),now=now)
        report['deep_handoff']={'created':True,'context':handoff['study_context'],'assistance':handoff['handoff']['assistance_already_given']}
    except Exception as exc:report['harness_error']=type(exc).__name__;report['model_calls']=provider.calls;dump(output,report);raise
    finally:
        outer.rollback();connection.close()
        with normal() as db:report['rollback_verified']=protected_fingerprints(db)==baseline;report['temporary_qa_remaining']=db.get(ChatSession,qa_id) is not None
        report['model_calls']=provider.calls;dump(output,report);engine.dispose()
    print(json.dumps({'model_calls':provider.calls,'rollback_verified':report['rollback_verified']}))
if __name__=='__main__':main()
