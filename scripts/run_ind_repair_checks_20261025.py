"""Record exact source identity, commands and exit codes for scoped offline checks."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys,time,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'storage/quality-audits/naiwa-ind-repair-20261025'
SOURCES=['frontend/src/lib/answerFeedback.ts','frontend/src/lib/answerFeedback.test.ts',
 'frontend/src/pages/StudyPage.vue','frontend/src/pages/StudyPage.answer-state.test.ts',
 'frontend/src/components/StudyFocus.vue','frontend/src/components/KnowledgeQuestionPickerTree.vue',
 'frontend/src/components/StudyRetry.presentation.test.ts','frontend/src/pages/ChatPage.vue',
 'frontend/src/pages/ChatPage.loading.test.ts','backend/api/routes/study.py','backend/errors.py',
 'backend/services/answer_submission_service.py','backend/services/answer_grading.py',
 'backend/services/practice_retry_service.py','tests/integration/test_standalone_practice_retry.py',
 'tests/integration/test_independent_acceptance_repairs.py']
def hashes():return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
def main():
 p=argparse.ArgumentParser();p.add_argument('kind',choices=['frontend','backend']);p.add_argument('tag');args=p.parse_args()
 out=OUT/args.tag;out.mkdir(exist_ok=False)
 before=hashes();env={**os.environ,'PYTHONIOENCODING':'utf-8'}
 node=shutil.which('node');assert node
 if args.kind=='frontend':
  cwd=ROOT/'frontend'
  jobs=[('vitest',[node,'node_modules/vitest/vitest.mjs','run','src/lib/answerFeedback.test.ts',
      'src/pages/StudyPage.answer-state.test.ts','src/components/StudyRetry.presentation.test.ts',
      'src/pages/ChatPage.loading.test.ts','--reporter=default','--reporter=junit','--outputFile='+str(out/'vitest.xml')]),
    ('typecheck',[node,'node_modules/vue-tsc/bin/vue-tsc.js','--noEmit']),
    ('build-types',[node,'node_modules/vue-tsc/bin/vue-tsc.js','--build']),
    ('vite-build',[node,'node_modules/vite/bin/vite.js','build','--outDir',str(out/'build')])]
 else:
  cwd=ROOT;env['PHASE45I_CLOSE_OFFLINE']='1'
  jobs=[('postgres',[sys.executable,'scripts/run_phase45e_test_cluster.py','--tests-only','--workspace-temp','--output-dir',str(out/'pg'),
    '--pytest-file','tests/integration/test_independent_acceptance_repairs.py',
    '--pytest-file','tests/integration/test_standalone_practice_retry.py',
    '--pytest-file','tests/integration/test_first_answer_state.py'])]
 results=[]
 for name,cmd in jobs:
  started=time.time()
  with (out/(name+'.log')).open('xb') as log:
   result=subprocess.run(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600)
  results.append({'name':name,'command':cmd,'cwd':str(cwd),'exit_code':result.returncode,'duration_seconds':round(time.time()-started,3),'source_sha256':before})
 after=hashes()
 with (out/'run.json').open('x',encoding='utf-8') as f:json.dump({'runs':results,'source_before':before,'source_after':after,'source_unchanged_during_run':before==after},f,ensure_ascii=False,indent=2)
 print(json.dumps({'directory':str(out),'exits':{r['name']:r['exit_code'] for r in results},'source_unchanged':before==after}))
 return 0 if before==after and all(r['exit_code']==0 for r in results) else 1
if __name__=='__main__':sys.exit(main())
