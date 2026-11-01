"""Summarize frozen private H-S evidence without DB or model access."""
import json,sys
from pathlib import Path
from collections import Counter
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    out=ROOT/'storage/quality-audits/phase45hs-20261010'
    read=lambda name:json.loads((out/name).read_text(encoding='utf-8'))
    report=read('report.json');baseline=read('baseline.json');export=read('formal-bank-export.json');coverage=read('coverage.json')
    from backend.models.learning import Question
    from backend.services.question_identity import match_reasons
    qs=[Question(**row) for row in export['questions']];pairs=[]
    for index,left in enumerate(qs):
        for right in qs[index+1:]:
            reasons=match_reasons(left,right)
            if reasons:pairs.append({'left':str(left.id),'right':str(right.id),'reasons':reasons})
    duplicate_ids={qid for pair in pairs for qid in (pair['left'],pair['right'])}
    formal=[r for r in report['rows'] if r['formal_eligible']]
    paths=['backend/services/question_identity.py','backend/services/phase45hs_verifiers.py',
        'backend/services/public_bank_batch.py','backend/services/auto_question_review.py',
        'backend/services/personal_question_service.py','backend/services/question_pack.py',
        'backend/services/answer_grading.py','backend/services/public_bank_supply.py','backend/mastery/origin_evidence.py','scripts/run_phase45hs_public_bank.py']
    summary={'total_preserved':len(qs),'active':baseline['active'],'inactive':baseline['inactive'],
        'classifications':dict(Counter(r['classification'] for r in report['rows'])),
        'reasons':dict(Counter(r['reason'] for r in report['rows'])),
        'formal_by_subject':dict(Counter(r['subject'] for r in formal)),
        'formal_by_type':dict(Counter(r['after']['question_type'] for r in formal)),
        'formal_by_node':[{k:row[k] for k in ('code','name','subject','strict_eligible_raw','blocking_reasons','status')} for row in coverage if row['strict_eligible_raw']],
        'policy_coverage':dict(Counter(r['status'] for r in coverage)),
        'pilot_types':dict(Counter(r['before']['question_type'] for r in report['pilot_results'])),
        'pilot_classifications':dict(Counter(r['classification'] for r in report['pilot_results'])),
        'repair_counts':report['repair_counts'],'approved_q6_sign_correction':1,
        'existing_duplicate_pairs':pairs,'duplicate_question_ids':sorted(duplicate_ids),
        'qualified_exam_curated':len(formal),'new_exam_variant':0,'new_development_original':0,'new_personal':0,
        'source_asset_hashes':{'database.dump':read('owner.json')['backup_sha256'],'latest_snapshot':baseline['latest_snapshot_sha256']},
        'code_sha256':{path:sha256((ROOT/path).read_bytes()).hexdigest() for path in paths},
        'paid_calls':0,'development_5433_touched':False,'deployed_to_original_db':False}
    target=out/'summary.json';target.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in {'code_sha256','formal_by_node','existing_duplicate_pairs','duplicate_question_ids'}},ensure_ascii=False))
    print('existing_duplicate_pairs='+str(len(pairs)))
if __name__=='__main__':main()
