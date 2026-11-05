"""Blind daily-plan wire representation; full pinned draft stays server-side."""
from collections import Counter
from hashlib import sha256
import json


def public_inventory(inventory):
    """Allow only exact eligible-question counts onto the homepage wire."""
    if not isinstance(inventory,dict):
        return None
    nodes=[]
    for node in inventory.get('recommendation_nodes') or []:
        if not isinstance(node,dict) or not node.get('kp_id'):
            continue
        nodes.append({key:node[key] for key in (
            'kp_id','name','practice_eligible_count','available_to_append_count'
        ) if key in node})
    return {
        'practice_eligible_count':int(inventory.get('practice_eligible_count') or 0),
        'available_to_append_count':int(inventory.get('available_to_append_count') or 0),
        'recommendation_nodes':nodes,
    }


def public_paper(paper):
    if not isinstance(paper,dict):
        return None
    questions=paper.get('questions') or []
    counts=Counter(str(q.get('kp_id')) for q in questions)
    names={str(q.get('kp_id')):q.get('kp_name','') for q in questions}
    nodes={str(n['kp_id']):dict(n) for n in paper.get('scope_nodes') or []}
    for kp in paper.get('selected_kp_ids') or counts:
        key=str(kp)
        nodes.setdefault(key,{'kp_id':key,'name':names.get(key,'')})
    result={k:paper[k] for k in ('budget_minutes','total_minutes','question_limit','selected_kp_ids','allocation_kp_ids') if k in paper}
    result.update(questions=[],question_count=len(questions),scope_nodes=[{
        'kp_id':key,'name':node.get('name') or names.get(key,''),
        'assigned_count':counts[key],
        'allocation_status':node.get('allocation_status','assigned' if counts[key] else 'unassigned'),
        'allocation_reason':node.get('allocation_reason'),
    } for key,node in nodes.items()])
    result['selection_fingerprint']=sha256(json.dumps([
        [q.get('question_id'),q.get('question_version_id')] for q in questions
    ],separators=(',',':')).encode('utf8')).hexdigest()
    diff=paper.get('diff')
    if isinstance(diff,dict):
        result['change_summary']={k:len(diff.get(k) or []) for k in ('added','removed','retained')}
    return result


def public_preview(value):
    if not isinstance(value,dict):
        return value
    # Deliberate allowlist. New internal diagnostics/selection metadata cannot
    # silently become a browser-visible question or source identifier.
    keys=('task_id','session_id','goal','status','message','error_code','draft_version','budget_minutes',
          'receipt','adjustment_origin','adjustment_error','undo_available','redo_available','kind')
    out={k:value[k] for k in keys if k in value}
    if isinstance(value.get('intent_trace'),dict):
        out['intent_trace']={k:value['intent_trace'][k] for k in ('operation','source','used_model') if k in value['intent_trace']}
    if 'draft' in value: out['draft']=public_paper(value['draft'])
    if 'retained_baseline' in value: out['retained_baseline']=public_paper(value['retained_baseline'])
    if 'context' in value:
        context=value.get('context') or {}
        out['context']={k:context[k] for k in ('request_origin','study_date','expires_at',
            'workload_pending','workload_accepted','workload','system_recommendations','unavailable_nodes') if k in context}
        out['context']['baseline']=public_paper(context.get('baseline'))
        out['context']['evidence']={}
        out['context']['inventory']=public_inventory(context.get('inventory'))
    for key in ('fallback_preview','workload_candidate'):
        if key in value: out[key]=public_preview(value[key])
    return out


def public_system(value):
    return {k:value[k] for k in ('recommendations','blockers','note') if k in value} | {
        'initial_paper':public_paper(value.get('initial_paper')),
        'inventory':public_inventory(value.get('inventory')),'evidence':{}}
