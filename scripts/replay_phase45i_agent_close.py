"""Audit all twenty frozen C7 responses without network or database access."""
from pathlib import Path
from uuid import UUID
from hashlib import sha256
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
SOURCE=ROOT/'storage/quality-audits/phase45i-agent-real-20261010/run-06'
OUTPUT=ROOT/'storage/quality-audits/phase45i-agent-close-20261010'


def frozen_rows():
    calls=[json.loads(line) for line in (SOURCE/'provider-calls.jsonl').read_text(encoding='utf-8').splitlines() if line]
    turns=[json.loads(line) for line in (SOURCE/'turns.jsonl').read_text(encoding='utf-8').splitlines() if line]
    if len(calls)!=20 or len(turns)!=20:raise ValueError('Expected exactly twenty frozen records')
    return calls,turns


def audit():
    from backend.models.learning import KnowledgePoint
    from backend.services.question_generation import C7Output,parse_generated_output,assess_output
    from backend.services.personal_question_families import resolve_family
    from backend.services.personal_question_service import verified_problem_identity
    hashes={p.name:sha256(p.read_bytes()).hexdigest() for p in [SOURCE/'provider-calls.jsonl',SOURCE/'turns.jsonl',SOURCE/'progress.json']}
    calls,turns=frozen_rows();rows=[];identities={}
    for call,turn in zip(calls,turns):
        raw=call['response_content']
        old='AUTO_PASS' if turn.get('question_ids') else turn['failures'][0]['review_status']
        row={'number':call['request_number'],'subject':call['subject'],'node_code':turn['knowledge_node_code'],
            'question_type':turn['question_type'],'difficulty':turn['difficulty'],'original_status':old,
            'raw_sha256':sha256(raw.encode()).hexdigest(),'raw_response':raw,'finish_reason':call['finish_reason'],
            'database_saved':False,'new_paid_calls':0}
        try:
            parsed=json.loads(raw);row['json_syntax_valid']=True
            try:C7Output.model_validate(parsed);row['original_schema_valid']=True
            except Exception as exc:
                row['original_schema_valid']=False
                row['original_schema_errors']=exc.errors(include_input=False) if hasattr(exc,'errors') else str(exc)
        except Exception:
            row['json_syntax_valid']=False;row['original_schema_valid']=False
        if call['finish_reason']=='length':
            row.update(status='OUTPUT_TRUNCATED',practice_candidate=False,normalization_changes=[])
            rows.append(row);continue
        try:
            out,changes=parse_generated_output(raw,compatibility=True,model_class=C7Output)
            node=KnowledgePoint(id=UUID(turn['knowledge_node_id']),code=turn['knowledge_node_code'],
                name=turn['knowledge_node_name'],subject='408' if turn['subject']=='408' else '考研数学',
                is_active=True,is_assessable=True,is_reference_only=True)
            spec=resolve_family(node.code,out.question_type)
            result=assess_output(out,node,request_id=f'AGENT_CLOSE_REPLAY:{call["request_number"]}',mode='original',
                family=turn['family'],family_spec=spec,difficulty={'improved':'medium','comprehensive':'advanced'}.get(turn['difficulty'],turn['difficulty']),
                trace={'prompt_version':'question-generation-c7-v1','model':call['model'],'mode':'simulation',
                    'model_calls':0,'normalization_changes':changes,'raw_response_sha256':row['raw_sha256']})
            row.update(status=result['review_status'],normalization_changes=changes,normalized_output=out.model_dump(),
                errors=result['errors'],uncertainties=result['uncertainties'],independent=result['record']['independent_verification'],
                narrative=result['record']['narrative_verification'],practice_candidate=result['status']=='AUTO_PASS')
            key=verified_problem_identity(result['question']) if row['practice_candidate'] else None
            row['duplicate_of']=identities.get(key) if key else None
            if key:identities.setdefault(key,row['number'])
        except Exception as exc:
            row.update(status='FORMAT_ERROR',error=str(exc),practice_candidate=False,normalization_changes=[])
        rows.append(row)
    unchanged=all(sha256((SOURCE/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items())
    if not unchanged:raise ValueError('Frozen source drift')
    result={'new_paid_calls':0,'source_hashes':hashes,'source_unchanged':unchanged,'rows':rows,
        'code_hashes':{p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in
            [ROOT/'backend/services/question_generation.py',ROOT/'backend/services/phase45i_quality_verifiers.py',
             ROOT/'backend/services/personal_question_service.py',ROOT/'backend/services/post_graduation_service.py']},
        'individually_approved':sum(r['practice_candidate'] for r in rows),
        'distinct_approved':sum(r['practice_candidate'] and not r.get('duplicate_of') for r in rows),
        'normalized_count':sum(bool(r['normalization_changes']) for r in rows)}
    OUTPUT.mkdir(parents=True,exist_ok=True)
    archive=OUTPUT/('frozen-replay-'+result['code_hashes']['backend/services/phase45i_quality_verifiers.py'][:12]+'.json')
    if not archive.exists():archive.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    (OUTPUT/'frozen-replay.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'rows','source_hashes','code_hashes'}},ensure_ascii=False))
    return result


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    audit()
