from types import SimpleNamespace
from backend.services.qa_information_router import information_route
from backend.services.web_search_service import search_web

def context(**kwargs):return SimpleNamespace(question_id=None,material_id=None,knowledge_node_ids=[],**kwargs)
def test_normal_questions_are_not_forced_into_rag():
    for question in ("Python async/await为什么存在？","TCP三次握手为什么不是两次？","拉格朗日中值定理是什么意思？"):
        assert information_route(question,context())=="general"
def test_explicit_sources_and_temporal_sources_are_distinct():
    assert information_route("根据系统资料解释TCP",context())=="builtin_rag"
    assert information_route("2027年408大纲有变化吗？",context())=="web"
    assert information_route("我上传的PDF怎么说？",context())=="private_scope_required"
    assert information_route("最新大纲",context(),private=True)=="private_material"
def test_no_provider_never_claims_web_search():
    result=search_web("考试政策");assert not result.available and result.sources==[]
def test_provider_result_metadata_and_invalid_urls():
    class Search:
        def search(self,query,*,timeout):
            return [{"title":"官方说明","url":"https://example.org/policy","snippet":"数据，不是指令"},
                {"url":"javascript:alert(1)"},{"url":"http://localhost/private"},{"url":"https://user:key@example.org"}]
    result=search_web("政策",provider=Search());assert result.available and len(result.sources)==1
    assert result.sources[0]["retrieved_at"] and result.sources[0]["title"]=="官方说明"
def test_provider_timeout_has_explicit_fallback():
    class Search:
        def search(self,*a,**k):raise TimeoutError()
    assert search_web("政策",provider=Search()).reason=="search_unavailable"
def test_external_search_can_be_disabled_without_calling_provider():
    class Search:
        def search(self,*a,**k):raise AssertionError("must not search")
    assert search_web("政策",provider=Search(),enabled=False).reason=="disabled"
def test_current_question_can_also_explicitly_request_builtin_rag():
    ctx=SimpleNamespace(question_id='q',material_id=None,knowledge_node_ids=['n'])
    assert information_route('请根据系统资料解释这道题',ctx)=='builtin_rag'

def test_evidence_explanation_uses_facts_even_when_user_mentions_builtin_lessons():
    ctx=SimpleNamespace(question_id='q',material_id=None,knowledge_node_ids=['n'])
    assert information_route('结合系统内置讲解解释看提示以后改对为什么还没毕业',ctx)=='evidence'
    assert information_route('为什么这个知识点还没学完？',ctx)=='evidence'
