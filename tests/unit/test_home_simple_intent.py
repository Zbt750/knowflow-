from types import SimpleNamespace
from uuid import uuid4
import json
from backend.services import home_recommendation_service as service
from backend.services.bank_selection_intent import bank_selection_request


def test_count_only_revision_preserves_visible_scope_without_inventing_another_node(monkeypatch):
    node=uuid4()
    monkeypatch.setattr(service,'_tools',lambda *args,**kwargs:SimpleNamespace(explicit_scope=None,excluded_scope=set()))
    assert service.resolve_scope(None,None,'保留推荐范围，减少到5道题',{'selected_kp_ids':[str(node)]},None)==[node]


def test_unmatched_new_target_does_not_inherit_previous_scope(monkeypatch):
    monkeypatch.setattr(service,'_tools',lambda *args,**kwargs:SimpleNamespace(explicit_scope=None,excluded_scope=set()))
    assert service.resolve_scope(None,None,'我要学不存在的知识点',{'selected_kp_ids':[str(uuid4())]},None)==[]


def test_unknown_target_with_count_is_not_a_count_only_revision(monkeypatch):
    monkeypatch.setattr(service,'_tools',lambda *args,**kwargs:SimpleNamespace(explicit_scope=None,excluded_scope=set()))
    assert service.resolve_scope(None,None,'我要学一个不存在的节点，只练2道题',{'selected_kp_ids':[str(uuid4())]},None)==[]


def test_named_addition_merges_with_base_scope_without_replacing_it():
    base=[uuid4(),uuid4()]
    extra=[uuid4()]
    request=bank_selection_request('帮我加入两道洛必达法则的题进来')
    plan=service._bank_scope_plan(base,extra,request,explicit_scope=True)
    assert plan['scope_mode']=='append' and plan['additional_count']==2
    assert plan['base_scope_ids']==base and plan['additional_scope_ids']==extra
    assert plan['selected_scope_ids']==base+extra
    assert json.loads(json.dumps(service._json_value(plan)))['base_scope_ids']==[str(value) for value in base]


def test_addition_without_named_scope_uses_current_base_as_query_scope():
    base=[uuid4(),uuid4()]
    request=bank_selection_request('保留原推荐，额外加一道题进来')
    plan=service._bank_scope_plan(base,[],request,explicit_scope=False)
    assert plan['additional_scope_ids']==base and plan['selected_scope_ids']==base


def test_explicit_replacement_does_not_merge_base_scope():
    base=[uuid4(),uuid4()]
    target=[uuid4()]
    request=bank_selection_request('只练洛必达法则，再加入两道题')
    plan=service._bank_scope_plan(base,target,request,explicit_scope=True)
    assert plan['scope_mode']=='replace' and plan['additional_count'] is None
    assert plan['selected_scope_ids']==target


def test_addition_to_a_base_node_keeps_the_scope_unique():
    base=[uuid4(),uuid4()]
    request=bank_selection_request('帮我加入一道题进来')
    plan=service._bank_scope_plan(base,[base[0]],request,explicit_scope=True)
    assert plan['scope_mode']=='append'
    assert plan['selected_scope_ids']==base


def test_only_keep_first_nodes_narrows_the_displayed_recommendation(monkeypatch):
    nodes=[uuid4(),uuid4(),uuid4()]
    monkeypatch.setattr(service,'_tools',lambda *args,**kwargs:SimpleNamespace(explicit_scope=None,excluded_scope=set()))
    previous={'selected_kp_ids':[str(node) for node in nodes]}
    assert service.resolve_scope(None,None,'只保留前两个知识点',previous,None)==nodes[:2]


def test_named_node_addition_keeps_current_recommendation(monkeypatch):
    base, extra = uuid4(), uuid4()
    monkeypatch.setattr(service, '_tools', lambda *a, **k: SimpleNamespace(explicit_scope={extra}, excluded_scope=set()))
    db = SimpleNamespace(scalars=lambda query: [SimpleNamespace(id=extra)])
    assert service.resolve_scope(db, None, '把洛必达法则加进去。', {'selected_kp_ids':[str(base)]}, None) == [base, extra]


def test_delete_third_node_uses_displayed_order(monkeypatch):
    nodes = [uuid4(), uuid4(), uuid4(), uuid4()]
    monkeypatch.setattr(service, '_tools', lambda *a, **k: SimpleNamespace(explicit_scope=None, excluded_scope=set()))
    assert service.resolve_scope(None, None, '把第三个知识点删掉。', {'selected_kp_ids':[str(n) for n in nodes]}, None) == nodes[:2] + nodes[3:]


def test_named_exclusion_preserves_other_recommended_nodes(monkeypatch):
    keep, remove = uuid4(), uuid4()
    monkeypatch.setattr(service, '_tools', lambda *a, **k: SimpleNamespace(explicit_scope=None, excluded_scope={remove}))
    assert service.resolve_scope(None, None, '不要洛必达法则', {'selected_kp_ids':[str(keep), str(remove)]}, None) == [keep]


def test_multiple_base_nodes_survive_additive_scope_and_duplicate_target():
    base = [uuid4(), uuid4(), uuid4()]
    extra = uuid4()
    request = bank_selection_request('帮我加入两道洛必达法则的题进来')
    result = service._bank_scope_plan(base, [base[1], extra, extra], request, explicit_scope=True)
    assert result['base_scope_ids'] == base
    assert result['selected_scope_ids'] == base + [extra]
    assert result['additional_count'] == 2


def test_ordinal_removal_keeps_unassigned_scope_nodes_after_ranked_nodes(monkeypatch):
    nodes=[uuid4(),uuid4(),uuid4()]
    monkeypatch.setattr(service,'_tools',lambda *a,**k:SimpleNamespace(explicit_scope=None,excluded_scope=set()))
    previous={'selected_kp_ids':[str(n) for n in nodes], 'questions':[{'kp_id':str(n)} for n in reversed(nodes[:2])]}
    assert service.resolve_scope(None,None,'把第三个知识点删掉',previous,None)==list(reversed(nodes[:2]))
