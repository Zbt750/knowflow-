"""Keep exact development validation commands, exit codes, logs and source hashes."""
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'storage/quality-audits/naiwa-answer-handoff-20261024-dev-validation'
NODE=Path('D:/应用安装包/node.exe')
FILES=['backend/mastery/storage.py','backend/services/answer_submission_service.py','backend/api/routes/study.py',
    'backend/errors.py','frontend/src/lib/answerSubmissionFailure.ts','frontend/src/pages/StudyPage.vue',
    'frontend/src/components/StudyFocus.vue','frontend/src/pages/StudyPage.answer-state.test.ts',
    'tests/integration/test_first_answer_state.py','scripts/naiwa_student_ui_acceptance_20261024.py',
    'scripts/naiwa_answer_handoff_provider.py','scripts/naiwa_answer_handoff_20261024.ps1']


def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}


def main():
    OUT.mkdir(exist_ok=False)
    before=hashes()
    records=[]
    commands=[('vitest',[str(NODE),'node_modules/vitest/vitest.mjs','run','src/pages/StudyPage.answer-state.test.ts',
        'src/lib/answerInteraction.test.ts','src/lib/answerFeedback.test.ts','src/components/AnswerExplanation.state.test.ts',
        '--reporter=default','--reporter=junit','--outputFile='+str(OUT/'frontend-junit.xml')]),
        ('typecheck',[str(NODE),'node_modules/vue-tsc/bin/vue-tsc.js','--noEmit']),
        ('build',[str(NODE),'node_modules/vite/bin/vite.js','build','--outDir',str(OUT/'frontend-build')])]
    for label,command in commands:
        with (OUT/(label+'.log')).open('xb') as stream:
            result=subprocess.run(command,cwd=ROOT/'frontend',stdout=stream,stderr=subprocess.STDOUT,
                timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        records.append({'name':label,'command':command,'cwd':str(ROOT/'frontend'),'exit_code':result.returncode,'log':label+'.log'})
        if result.returncode:break
    after=hashes()
    report={'time':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'commands':records,
        'source_sha256_before':before,'source_sha256_after':after,'source_unchanged_during_validation':before==after,
        'real_model_requests':0,'browser_used':False}
    (OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(OUT),'checks':[{k:r[k] for k in ('name','exit_code')} for r in records],
        'source_unchanged':before==after},ensure_ascii=False))
    return int(len(records)!=3 or any(r['exit_code'] for r in records) or before!=after)


if __name__=='__main__':raise SystemExit(main())
