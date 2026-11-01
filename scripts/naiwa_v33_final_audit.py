"""New final-run evidence; no old baselines/ledgers are rewritten."""
from pathlib import Path
import json
from scripts import naiwa_v33_audit as previous
ROOT=previous.ROOT
OUT=ROOT/'storage/quality-audits/naiwa-v33-final-20261023'

def save(name,value):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,default=str)

def snapshot(label):
    original=previous.OUT;previous.OUT=OUT
    try:return previous.snapshot(label)
    finally:previous.OUT=original

def protect():
    previous.check()
    for row in json.loads((OUT/'protected-before.json').read_text(encoding='utf-8')).items():
        name,digest=row
        assert previous.sha(ROOT/name)==digest, 'final_history_drift_STOP:'+name

def prepare():
    previous.check();OUT.mkdir()
    protected={}
    for p in previous.OUT.rglob('*'):
        if p.is_file() and not (p.parent.name=='recovery-4' and p.name in {'api.log','web.log','postgres.log','window.json','stop.request','admission.lock','sessions.lock'}):
            protected[p.relative_to(ROOT).as_posix()]=previous.sha(p)
    save('protected-before.json',protected)
    snapshot('before')
    from scripts.naiwa_v32_runtime import sources
    loaded=json.loads((previous.OUT/'recovery-4/loaded-code.json').read_text(encoding='utf-8'))
    assert loaded['source_sha256']==sources(),'runtime_source_mismatch_STOP'
    save('runtime-before.json',loaded)
    from scripts import naiwa_v3_runtime_20261022 as paid
    ledger=json.loads(paid.LEDGER.read_text(encoding='utf-8'))
    control=json.loads((paid.OUT/'control.json').read_text(encoding='utf-8'))
    epoch=json.loads((paid.RUN/'active-source-hashes.json').read_text(encoding='utf-8'))
    save('paid-readiness.json',{'canonical_path':str(paid.LEDGER),'canonical_sha256':previous.sha(paid.LEDGER),
        'ledger':ledger,'original_scene_caps':paid.LEGACY_CAPS,'paid_enabled':control.get('paid_enabled'),
        'source_epoch_matches_current':epoch.get('source_sha256')==paid.hashes(),
        'current_runtime':'fixed offline recovery-4, not the paid runtime',
        'decision':'BLOCKED_PENDING_CONTROLLED_RUNTIME_REBIND; do not call open_scene or bypass hash guards'})

if __name__=='__main__':prepare()
