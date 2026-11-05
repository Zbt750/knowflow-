from copy import deepcopy
from backend.services.home_public_view import public_paper,public_preview,public_system


def test_blind_response_retains_real_counts_without_question_identity_or_content():
    draft={'selected_kp_ids':['kp1','kp2'],'questions':[
        {'question_id':'secret-q1','question_version_id':'secret-v1','kp_id':'kp1','kp_name':'洛必达',
         'minutes':5,'stem':'secret-stem','options':{'A':'secret-option'}}],
        'total_minutes':5,'budget_minutes':90,'diff':{'added':['secret-q1'],'removed':[],'retained':[]}}
    original=deepcopy(draft)
    public=public_paper(draft)
    assert public['question_count']==1 and public['questions']==[]
    assert sum(n['assigned_count'] for n in public['scope_nodes'])==1
    assert public['scope_nodes'][0]['name']=='洛必达'
    assert public['change_summary']=={'added':1,'removed':0,'retained':0}
    assert 'secret-' not in str(public)
    assert draft==original


def test_every_nested_fallback_workload_and_baseline_is_blinded():
    p={'questions':[{'kp_id':'kp','question_id':'secret','stem':'secret'}]}
    raw={'task_id':'task','draft_version':'hash','draft':p,'internal_question_ids':['secret'],
        'context':{'baseline':p,'bank_selection':{'matches':{'secret':{}}}},
        'retained_baseline':p,'workload_candidate':{'draft':p}}
    out=public_preview(raw)
    assert out['draft']['question_count']==1
    assert out['context']['baseline']['questions']==[]
    assert out['workload_candidate']['draft']['questions']==[]
    assert 'secret' not in str(out)


def test_public_system_and_preview_keep_real_eligible_counts_but_only_allowlisted_inventory_fields():
    inventory={'practice_eligible_count':30,'available_to_append_count':28,
        'active_question_count':42,'blocked_question_count':12,
        'recommendation_nodes':[
            {'kp_id':'kp-limit','name':'洛必达法则','practice_eligible_count':12,'available_to_append_count':11},
            {'kp_id':'kp-hidden','name':'隐函数求导','practice_eligible_count':0,'available_to_append_count':0},
        ],'question_ids':['secret-question'],'question_versions':['secret-version']}
    paper={'selected_kp_ids':['kp-limit'],'questions':[
        {'question_id':'secret-question','question_version_id':'secret-version','kp_id':'kp-limit',
         'kp_name':'洛必达法则','stem':'secret-stem','options':{'A':'secret-option'}}],
        'total_minutes':25,'budget_minutes':90}
    raw={'recommendations':[{'kp_id':'kp-limit','name':'洛必达法则'}],
        'inventory':inventory,'initial_paper':paper,'evidence':{'secret':'private'},
        'blockers':[],'note':''}
    system=public_system(raw)
    assert system['inventory']=={'practice_eligible_count':30,'available_to_append_count':28,
        'recommendation_nodes':[
            {'kp_id':'kp-limit','name':'洛必达法则','practice_eligible_count':12,'available_to_append_count':11},
            {'kp_id':'kp-hidden','name':'隐函数求导','practice_eligible_count':0,'available_to_append_count':0},
        ]}
    assert system['initial_paper']['questions']==[]
    assert 'secret' not in str(system)
    preview=public_preview({'task_id':'task','context':{'inventory':inventory,'baseline':paper,
        'study_date':'2026-11-04','expires_at':'2026-11-04T01:00:00Z'},'draft':paper})
    assert preview['context']['inventory']==system['inventory']
    assert preview['draft']['questions']==[] and preview['context']['baseline']['questions']==[]
    assert 'secret' not in str(preview)
