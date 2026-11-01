"""Close V32 write window and preserve objective final evidence, not a PASS generator."""
from pathlib import Path
import os,sys,json,collections,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_v32_audit import OUT,read,sha,save,snapshot,protected

def main():
    import httpx
    from scripts.naiwa_v31_handoff_policy import close_window
    run=OUT/'runtime-10';control=read(run/'window.json')
    assert protected()==read(OUT/'protected-before.json'),'historical file drift STOP'
    originals=read(OUT/'ledger-before.json')
    assert all(sha(Path(v['path']))==v['sha256'] for v in originals),'ledger drift STOP'
    snapshot('before-close')
    close_window(run/'window.json')
    from scripts.naiwa_v31_runtime import put
    put(run/'fault.json',{'mode':'none','simulation':True})
    sessions=read(run/'sessions.json');sid=next(iter(sessions))
    with httpx.Client(trust_env=False,timeout=8) as client:
        base='http://127.0.0.1:63246'
        response=client.post(base+'/api/chat/sessions/'+sid+'/assistant:stream',headers={'origin':base,'x-naiwa-v31':control['nonce']},json={'question':'V32 CLOSED PROBE MUST NOT BE SAVED'})
        assert response.status_code==403
        health=client.get(base+'/api/health');assert health.status_code==200
    save('closed-window.json',{'status':response.status_code,'body':response.json(),'negative_protocol_probe_not_a_ui_message':True})
    final=snapshot('final');initial=read(OUT/'database-before.json');prior=read(OUT/'database-before-close.json')
    assert final['row_sha256']==prior['row_sha256'],'closed/GET probe wrote business rows STOP'
    differences={}
    for table,rows in initial['rows'].items():
        pk=initial['schema'][table]['primary_key']['constrained_columns']
        key=lambda row:tuple(row[k] for k in pk) if pk else json.dumps(row,ensure_ascii=False,sort_keys=True)
        before={key(r):r for r in rows};after={key(r):r for r in final['rows'][table]}
        removed=[k for k in before if k not in after];modified=[k for k in before if k in after and before[k]!=after[k]]
        differences[table]={'before':len(rows),'after':len(final['rows'][table]),'added':len(after.keys()-before.keys()),'removed':removed,'original_modified':modified}
        assert not removed and not modified,(table,removed,modified)
    save('database-diff.json',{'original_rows_preserved':True,'closed_probe_no_change':True,'tables':differences})
    after=protected();assert after==read(OUT/'protected-before.json');save('protected-final.json',after)
    save('ledger-final.json',{'canonical':[{**v,'after_sha256':sha(Path(v['path']))} for v in originals],'new_real_requests':0,'paid_enabled':False,'no_budget_reset':True})
    catalog=[]
    for p in (ROOT/'storage/quality-audits').rglob('*ledger*.json'):
        if OUT in p.parents:continue
        try:
            value=read(p);requests=value.get('requests') if isinstance(value,dict) else None
            count=len(requests) if isinstance(requests,(list,dict)) else None
        except (ValueError,OSError):count=None
        catalog.append({'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p),'entries_if_standard':count})
    save('ledger-catalog-final.json',{'captured_at':'end_of_V32_not_a_retroactive_full_initial_catalog','files':catalog})
    from scripts import naiwa_v32_runtime as runtime
    loaded=read(run/'loaded-code.json');assert loaded['source_sha256']==runtime.sources()
    suite=ET.parse(OUT/'python-final-r5.xml').getroot().find('testsuite')
    save('final-verification.json',{'status':'PARTIAL','code_matches_loaded':True,'epoch':10,'manifest':read(run/'epoch.json'),
        'processes':read(run/'processes.json'),'health':health.json(),'database':final['identity'],'cluster_id':final['cluster_id'],
        'protected_count':len(after),'historical_10_original_bytes_recovered':False,'write_window_closed':True,'fault':'none','paid_enabled':False,
        'new_real_model_requests':0,'python':suite.attrib,'stage4':'NOT_AUTHORIZED_NOT_EXECUTED'})
    # Semantic review explicitly separates deterministic tools from fixed text.
    matrix=read(OUT/'final-matrix-ready/matrix-results.json')
    failures={'C3':'没有精确引用刚才的预览，而新建泛化交接卡','C5':'换一道未走题库替换/澄清流程','D6':'未查询条件是否成立，只返回讲解','D8':'取消并换题的两个子目标未处理','F7':'只看题库未进入确定性查询或澄清'}
    blocked={'A2','A3','A4','A5','A7','A8','C8','D7','E5','E6','E7','E8','F3','F4'}
    reviewed=[]
    for row in matrix['results']:
        label=row['label'];status='FAIL' if label in failures else 'BLOCKED' if label in blocked else 'PASS'
        reason=failures.get(label,'固定Provider不能证明教学/上下文效果，或隔离资料/时间证据不足' if status=='BLOCKED' else '业务数据/讲解或明确只读行为有本轮页面证据')
        if label=='E5':reason='固定未来时钟与消息created_at实际时间存在跨度，30分钟范围继承保护生效；不改写消息时间伪造通过'
        reviewed.append({'id':label,'input':row['input'],'status':status,'reason':reason,'http':row['http'],'evidence':'final-matrix-ready/matrix/'+label+'.json','sse':'final-matrix-ready/matrix/'+label+'.sse','screenshot':'final-matrix-ready/matrix/'+label+'.png','quality':row['answerQuality']})
    counts=dict(collections.Counter(r['status'] for r in reviewed));assert len(reviewed)==48
    save('scenario-matrix.json',{'unique_inputs':48,'counts':counts,'rows':reviewed,'note':'PASS is engineering-scoped, never real-model quality. Replays not added.'})
    lines=['# V3.2 自然输入语义审阅（48条，不叠加重跑）','',f'状态统计：{counts}。所有真实模型调用为0。','', '| ID | 实际输入 | 结果 | 依据/限制 |','|---|---|---|---|']
    for row in reviewed:lines.append(f"| {row['id']} | {row['input']} | {row['status']} | [{row['reason']}]({row['evidence']}) |")
    with (OUT/'scenario-matrix.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n')
    print('CLOSED_AND_PRESERVED',counts,'Python',suite.attrib)
    print({t:d for t,d in differences.items() if d['added']})

if __name__=='__main__':main()
