"""GET-only daily API/source comparison for the explicitly requested incident."""
from pathlib import Path
import hashlib
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/geometric-actual-question-20261024'

def main():
    import httpx
    data=json.loads((OUT/'actual-records.json').read_text(encoding='utf-8'))
    version=data['incident']['version'];item=data['incident']['item'];batch=data['incident']['batch']
    results={}
    with httpx.Client(trust_env=False,timeout=8,follow_redirects=False) as client:
        today=client.get('http://127.0.0.1:8000/api/plans/today');today.raise_for_status()
        body=today.json();wire=next(row for row in body['items'] if row['id']==item['id'])
        assert wire['stem']==version['stem'] and wire['options']==version['options']
        assert wire['question_version_id']==version['id']
        results['today']={'http_status':today.status_code,'plan_total':len(body['items']),'item':wire,
            'version_matches':True,'stem_and_options_match':True}
        batch_response=client.get('http://127.0.0.1:8000/api/personal-questions/batches/'+batch['id'])
        batch_response.raise_for_status();results['batch']={'http_status':batch_response.status_code,'result':batch_response.json()}
        # No answer-reveal endpoint: even reading an answer can have learning semantics.
        sources={}
        for path in ('src/main.ts','src/lib/markdownMath.ts','src/components/MarkdownContent.vue','src/components/StudyFocus.vue'):
            response=client.get('http://127.0.0.1:5173/'+path);response.raise_for_status()
            sources[path]={'http_status':response.status_code,'served_transformed_sha256':hashlib.sha256(response.content).hexdigest(),
                'workspace_sha256':hashlib.sha256((ROOT/'frontend'/path).read_bytes()).hexdigest(),
                'served_text':response.text}
        # Served transformed code is retained, not falsely compared byte-for-byte with TypeScript/SFC source.
        results['frontend_sources']=sources
    results.update(browser_ui_tested=False,actual_historical_sse_record_available=False,
        original_model_bodies_available=False,real_model_requests=0,
        warning='Source/GET checks are not browser layout or historical SSE verification')
    with (OUT/'wire-and-source.json').open('x',encoding='utf-8') as stream:json.dump(results,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'today_total':len(body['items']),'display_number':wire.get('display_number'),
        'version_matches':True,'stem_matches':True,'trust':wire.get('question_trust'),
        'served_frontend_paths':list(sources),'model_calls':0},ensure_ascii=False))

if __name__=='__main__':main()
