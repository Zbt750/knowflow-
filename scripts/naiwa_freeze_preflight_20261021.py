"""Preparation ONLY: no enable command, no real Provider factory or model call."""
from pathlib import Path
import sys,json,hashlib,shutil,time,contextvars,asyncio
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_naiwa_experience_20261020 import save,snapshot,RUN,MODULES,TABLES,database_url,existing_manager
from scripts.phase5_eval_meter import Meter,BudgetStop
OUT=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021'
CAPS={'AGENT':4,'GENERATE':1}
SCENE=contextvars.ContextVar('freeze_retest_scene',default=None)
SERVICE_FILES=[f'backend/services/{n}.py' for n in ['learning_planner_scope','learning_assistant_service','assistant_router',
    'learning_task_tools','generation_formula_consistency','personal_question_general','question_generation']]
LEDGERS=[ROOT/'storage/quality-audits/naiwa-real-20261020/provider-ledger.json',
    ROOT/'storage/quality-audits/naiwa-real-retest-20261020-budget7/provider-ledger.json']
def load(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

class FreezeMeter(Meter):
    """New ledger only. Phase1 never installs this meter on an actual Provider."""
    def __init__(self,output,*,simulated=False):
        assert output.resolve().is_relative_to(OUT.resolve()),'new round evidence only'
        output.mkdir(parents=True,exist_ok=True)
        super().__init__(output,max_requests=5)
        self.simulated=simulated;self.control=output/'control.json'
        if not self.control.exists():self.seal('preparation_no_execution_authorization')
        path=output/'provider-ledger.json'
        if path.exists():
            old=load(path);assert old['limits']['max_requests']==5 and old['scene_limits']==CAPS
            self.records,self.stop_reason=old['requests'],old['stop_reason']
            if any(not r.get('finished') for r in self.records):
                self.stop_reason='unfinished_request_requires_reconciliation';self.seal(self.stop_reason)
        self.flush()
    def flush(self):
        super().flush();path=self.output/'provider-ledger.json';value=load(path)
        value.update(scene_limits=CAPS,simulated_zero_network=self.simulated,
            scene_counts={s:sum(r['case_id']==s for r in self.records) for s in CAPS})
        save(path,value)
    def seal(self,reason):
        save(self.control,{'paid_enabled':False,'authorization_received':False,'active_scene':None,'reason':reason,'time':time.time()})
    def begin(self,request):
        with self.lock:
            state=load(self.control);scene=SCENE.get()
            if not(state.get('paid_enabled') and state.get('authorization_received') and scene in CAPS and state.get('active_scene')==scene):
                raise BudgetStop('paid_exit_closed_or_browser_scene_not_authorized')
            if len(self.records)>=5:
                self.seal('global_cap5');raise BudgetStop('global_cap5')
            if sum(r['case_id']==scene for r in self.records)>=CAPS[scene]:
                self.seal('scene_cap');raise BudgetStop('scene_cap')
            self.case_id=scene
            try:return super().begin(request)
            except BaseException:
                self.seal('blocked_before_physical_send');raise
    def finish(self,record,*args,**kwargs):
        super().finish(record,*args,**kwargs)
        if record and (record.get('error_type') or (record.get('http_status') or 599)>=400):
            self.stop_reason='network_or_provider_error'
        if self.stop_reason:self.seal(self.stop_reason)
        elif len(self.records)>=5:self.seal('global_cap5')
        elif record and sum(r['case_id']==record['case_id'] for r in self.records)>=CAPS[record['case_id']]:self.seal('scene_cap')
        self.flush()

def selftest():
    import httpx,tempfile
    # Windows constructs a local socketpair for asyncio's wake-up IPC. Build
    # that loop before the no-connect hook; all stub requests run AFTER it.
    loop=asyncio.new_event_loop()
    # Hard proof that these are no-network stubs, not real paid acceptance.
    def deny(event,args):
        if event=='socket.connect':raise AssertionError('selftest_must_not_open_network_socket')
    sys.addaudithook(deny)
    checks=[];sent=[0]
    payload={'model':'deepseek-flash','max_tokens':100,'messages':[{'role':'user','content':'offline counter test'}]}
    reply={'choices':[{'message':{'content':'stub'},'finish_reason':'stop'}],
           'usage':{'prompt_tokens':20,'completion_tokens':10}}
    def ok(request):sent[0]+=1;return httpx.Response(200,json=reply)
    def enable(m,scene):SCENE.set(scene);save(m.control,{'paid_enabled':True,'authorization_received':True,'active_scene':scene})
    def blocked(fn):
        try:fn()
        except BudgetStop:return
        raise AssertionError('expected hard block')
    with tempfile.TemporaryDirectory(prefix='zero-network-',dir=OUT) as temp:
        directory=Path(temp);meter=FreezeMeter(directory,simulated=True);meter.install()
        try:
            with httpx.Client(transport=httpx.MockTransport(ok),trust_env=False) as client:
                post=lambda:client.post('https://api.deepseek.com/chat/completions',json=payload)
                blocked(post);assert sent[0]==0;checks.append('closed gate blocks before send')
                enable(meter,'AGENT')
                for _ in range(4):post()
                enable(meter,'AGENT');blocked(post)
                assert sent[0]==4 and len(meter.records)==4
                checks.append('Agent4 cap; remaining generation slot cannot transfer')
        finally:meter.uninstall()
        meter=FreezeMeter(directory,simulated=True);assert len(meter.records)==4
        checks.append('restart resumes existing count4')
        meter.install()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):yield ('data: '+json.dumps(reply)+'\n\ndata: [DONE]\n\n').encode()
        async def async_ok(request):sent[0]+=1;return httpx.Response(200,stream=Stream())
        async def fifth():
            enable(meter,'GENERATE')
            async with httpx.AsyncClient(transport=httpx.MockTransport(async_ok),trust_env=False) as client:
                async with client.stream('POST','https://api.deepseek.com/chat/completions',json=payload) as r:await r.aread()
        try:
            loop.run_until_complete(fifth());assert sent[0]==5 and len(meter.records)==5
            assert load(meter.control)['paid_enabled'] is False
            with httpx.Client(transport=httpx.MockTransport(ok),trust_env=False) as client:
                enable(meter,'GENERATE');blocked(lambda:client.post('https://api.deepseek.com/chat/completions',json=payload))
            assert sent[0]==5;checks.append('async SSE counted; global5 and sixth request blocked')
        finally:meter.uninstall()
        # Each fault has a separate simulated ledger, never the real-round file.
        for fault in ['network','timeout','auth','usage_missing','unfinished_restart']:
            m=FreezeMeter(directory/fault,simulated=True);enable(m,'GENERATE')
            def fail(request):
                if fault=='network':raise httpx.ConnectError('stub',request=request)
                if fault=='timeout':raise httpx.ReadTimeout('stub',request=request)
                return httpx.Response(401 if fault=='auth' else 200,json={} if fault=='usage_missing' else reply)
            if fault=='unfinished_restart':
                r=m.begin(httpx.Request('POST','https://api.deepseek.com/chat/completions',json=payload))
                assert r is not None
                restarted=FreezeMeter(directory/fault,simulated=True)
                assert len(restarted.records)==1 and restarted.stop_reason and not load(restarted.control)['paid_enabled']
            else:
                m.install()
                try:
                    with httpx.Client(transport=httpx.MockTransport(fail),trust_env=False) as client:
                        try:client.post('https://api.deepseek.com/chat/completions',json=payload)
                        except httpx.HTTPError:pass
                    assert len(m.records)==1 and not load(m.control)['paid_enabled']
                finally:m.uninstall()
            checks.append(fault+' retains physical reservation and seals exit')
    save(OUT/'counter-selftest.json',{'status':'PASS','checks':checks,'real_model_requests':0,
        'transport':'httpx.MockTransport; all socket.connect denied','limits':CAPS,'total':5})
    loop.close()
    print(json.dumps({'selftest':'PASS','checks':len(checks),'real_requests':0}))

def inventory(stage):
    OUT.mkdir(parents=True,exist_ok=True)
    data=json.loads(json.dumps(snapshot('freeze-preflight-'+stage),default=str))
    save(OUT/('database-'+stage+'.json'),data)
    evidence={str(p.relative_to(ROOT)):sha(p) for p in LEDGERS}
    assert [len(load(p)['requests']) for p in LEDGERS]==[19,5]
    prior=load(ROOT/'storage/quality-audits/naiwa-scope-math-zero-20261021-v9/history-preservation.json')
    assert evidence==prior['ledger_sha256'],'historical ledger changed'
    active={t:[str(r.get('id')) for r in data[t] if r.get('status') in {'running','generating','queued','pending','created','processing'}]
            for t in ('chat_messages','learning_tasks','personal_generation_batches','materials')}
    if stage=='before':
        assert not any(active.values()),active
        for name in ['runtime.json','loaded-code.json','backend.log','supervisor.log']:
            source=RUN/name
            if source.exists():shutil.copy2(source,OUT/('before-'+name))
        assert not (OUT/'baseline.json').exists(),'never overwrite round baseline'
        save(OUT/'baseline.json',{'database':data,'ledger_hashes':evidence,'source_hashes':{p:sha(ROOT/p) for p in SERVICE_FILES},'active':active})
        FreezeMeter(OUT/'round5').seal('phase1_not_authorized')
    else:
        previous=load(OUT/'baseline.json');assert evidence==previous['ledger_hashes']
        changes={}
        for table in TABLES:
            key=lambda r:str(r.get('id',r.get('kp_id')))
            a={key(r):r for r in previous['database'][table]};b={key(r):r for r in data[table]}
            changes[table]={'before':len(a),'after':len(b),'identical':a==b}
        assert all(c['identical'] for c in changes.values()),changes
        loaded=load(RUN/'loaded-code.json')
        hashes=loaded['source_sha256']
        match={p:hashes.get(p)==sha(ROOT/p)==previous['source_hashes'][p] for p in SERVICE_FILES}
        assert all(match.values()),match
        assert loaded['guard_self_check_passed'] and loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL'
        for name in ['runtime.json','loaded-code.json']:shutil.copy2(RUN/name,OUT/('after-'+name))
        save(OUT/'preservation-and-load-check.json',{'identity':data['identity'],'table_comparison':changes,
            'ledger_hashes':evidence,'loaded_sources_match':match,'active':active,'paid_enabled':False,'real_calls':0})
    print(json.dumps({'stage':stage,'identity':data['identity'],'active':active,'real_calls':0}))

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    if sys.argv[1]=='selftest':selftest()
    elif sys.argv[1] in {'before','after'}:inventory(sys.argv[1])
    else:raise ValueError('phase1 commands only')
