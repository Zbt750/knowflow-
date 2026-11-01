"""V33 independent read-only baseline and snapshots; retain all old evidence."""
from pathlib import Path
import sys,json,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_v32_audit import read,sha
from scripts import naiwa_v32_audit as prior
OLD=prior.OUT;OUT=ROOT/'storage/quality-audits/naiwa-v33-20261022'
def save(name,value):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,default=str)
def protected():
    result=prior.protected()
    for p in OLD.rglob('*'):
        if p.is_file() and not (p.parent.name=='runtime-10' and p.name in {'api.log','web.log','postgres.log','window.json','stop.request','admission.lock','sessions.lock'}):
            result[p.relative_to(ROOT).as_posix()]=sha(p)
    return result
def snapshot(label):
    before=prior.OUT;prior.OUT=OUT
    try:return prior.snapshot(label)
    finally:prior.OUT=before
def check():
    expected=read(OUT/'protected-before.json');actual=protected()
    assert actual==expected,'V33 historical evidence changed STOP'
    for row in read(OUT/'ledger-before.json')['canonical']:
        assert sha(Path(row['path']))==row['sha256'],'canonical ledger changed STOP'
def preflight():
    assert not OUT.exists();OUT.mkdir()
    assert prior.protected()==read(OLD/'protected-final.json')
    from scripts import naiwa_v32_runtime as runtime
    loaded=read(OLD/'runtime-10/loaded-code.json')
    assert loaded['source_sha256']==runtime.sources()
    assert not read(OLD/'runtime-10/window.json')['enabled']
    ledger=read(OLD/'ledger-final.json')
    for row in ledger['canonical']:assert sha(Path(row['path']))==row['sha256']
    catalog=read(OLD/'ledger-catalog-final.json')
    for row in catalog['files']:assert sha(ROOT/row['path'])==row['sha256']
    save('ledger-before.json',ledger);save('ledger-catalog-before.json',catalog)
    save('protected-before.json',protected());snapshot('before')
    save('history-incident.json',{'original_10_bytes_recovered':False,'reference':str(OLD/'history-incident.json'),'sha256':sha(OLD/'history-incident.json')})
    save('running-before.json',{'loaded':loaded,'processes':read(OLD/'runtime-10/processes.json')})
    (OUT/'git-before.txt').write_text(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,encoding='utf-8',errors='replace'),encoding='utf-8')
    failures={label:read(OLD/'final-matrix-ready/matrix'/f'{label}.json') for label in ['C3','C5','D6','D8','F7']}
    save('original-failures-reference.json',{k:{'input':v['input'],'frames':v['frames'],'body':v['body'],'screenshot':str(OLD/'final-matrix-ready/matrix'/f'{k}.png')} for k,v in failures.items()})
    save('preflight.json',{'status':'PASS','canonical_count':4,'catalog_files':len(catalog['files']),'old_756_verified':True,'real_requests':0})
    print('V33_BASELINE_PASS')
if __name__=='__main__':
    if sys.argv[1]=='preflight':preflight()
    elif sys.argv[1]=='snapshot':check();snapshot(sys.argv[2]);print('SNAPSHOT_AND_PROTECTION_PASS')
