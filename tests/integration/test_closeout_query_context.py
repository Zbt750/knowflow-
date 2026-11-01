"""New isolated PG only. No Provider/network; persisted time and scope contracts."""
import asyncio,json
from datetime import datetime,timezone
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from tests.conftest import TEST_DATABASE_URL
from tests.integration.query_followup_backend import prepare_fixture,NoModel
from backend.models.chat import ChatSession,ChatMessage
from backend.schemas.learning_assistant import AssistantRequest,StudyContext
from backend.services.learning_assistant_service import assistant_stream,planner_handoff
from backend.services.assistant_router import CapabilityRoute
from uuid import uuid4

def test_injected_clock_scope_handoff_and_readonly_mode_switch():
    engine=create_engine(TEST_DATABASE_URL);factory=sessionmaker(bind=engine,expire_on_commit=False)
    facts=prepare_fixture(factory);now=datetime(2040,4,3,1,tzinfo=timezone.utc)
    with factory.begin() as db:
        row=ChatSession(mode='builtin',purpose='qa',title='独立逻辑时钟回归');db.add(row);db.flush();sid=row.id
    async def talk(text):
        raw=[r async for r in assistant_stream(factory,request=None,session_id=sid,
            body=AssistantRequest(question=text,study_context=StudyContext(surface='chat')),
            stack=None,provider=NoModel(),now=now)]
        frames=[]
        for r in raw:
            lines=r.decode().splitlines();frames.append((lines[0][7:],json.loads(lines[1][6:])))
        assert not any(e=='error' for e,d in frames),frames
        return frames
    for text in ['洛必达有多少道可练题？','这些题我做过几道？','那里面哪些做错了？']:
        asyncio.run(talk(text))
    with factory() as db:
        messages=list(db.scalars(select(ChatMessage).where(ChatMessage.session_id==sid)))
        assert len(messages)==6 and all(m.created_at==now for m in messages)
    handoff=planner_handoff(factory,ctx=StudyContext(surface='chat',conversation_id=sid),
        user_id=uuid4(),message='给我安排一道。',route=CapabilityRoute('planner','plan',1,'test'),now=now)
    assert handoff.constraints['scope_origin']=='same_session_query_scope'
    assert list(map(str,handoff.target_knowledge_node_ids))==[facts['lhopital_id']]
    asyncio.run(talk('这次只想看题库，不要创建计划。'))
    with factory() as db:
        answer=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,ChatMessage.role=='assistant').order_by(ChatMessage.seq.desc()))
        evidence=answer.metadata_['read_only_data_query']
        assert evidence['scope_node_ids']==[facts['lhopital_id']]
        assert evidence['query_state']['subject']=='考研数学'
        assert '408原创' not in answer.content
    engine.dispose()
