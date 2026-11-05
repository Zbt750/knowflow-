from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from backend.models.chat import ChatMessage
from backend.schemas.home_recommendation import HomeRecommendationRequest
from backend.services import home_recommendation_service as home


@pytest.mark.parametrize('action',['default','restore','cancel','accept_workload','dismiss_workload'])
def test_system_edit_never_writes_dialogue_even_if_a_goal_is_supplied(action):
    session=NS(id=uuid4(),title='首页推荐调整');written=[]
    body=HomeRecommendationRequest(session_id=session.id,request_key=uuid4().hex,
        action=action,goal='查看系统推荐')
    assert home._record_request_dialogue(NS(add=written.append),session,body,'试卷预览：18道') is False
    assert written==[] and session.title=='首页推荐调整'
    assert home._request_origin(body)=='system'


def test_only_a_real_user_turn_creates_user_and_assistant_messages():
    session=NS(id=uuid4(),title='首页推荐调整');written=[]
    body=HomeRecommendationRequest(session_id=session.id,request_key=uuid4().hex,
        action='adjust',goal='再帮我加入一道洛必达法则的题目。')
    assert home._record_request_dialogue(NS(add=written.append),session,body,'已更新当前方案，尚未生成正式卷。') is True
    assert len(written)==2 and all(isinstance(row,ChatMessage) for row in written)
    assert [(r.role,r.content) for r in written]==[
        ('user',body.goal),('assistant','已更新当前方案，尚未生成正式卷。')]
    assert all(row.session_id==session.id for row in written)
    assert home._request_origin(body)=='chat'


def test_empty_goal_is_not_replaced_by_an_invented_user_message():
    session=NS(id=uuid4(),title='首页推荐调整');written=[]
    body=HomeRecommendationRequest(session_id=session.id,request_key=uuid4().hex,action='adjust')
    assert home._record_request_dialogue(NS(add=written.append),session,body,'系统推荐') is False
    assert written==[]
