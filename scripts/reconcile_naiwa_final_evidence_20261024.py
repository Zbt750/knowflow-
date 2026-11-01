"""Offline arithmetic and immutable-artifact reconciliation, no sockets or Provider."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'storage/quality-audits/naiwa-final-freeze-20261024'
AUDIT=ROOT/'storage/quality-audits/naiwa-differentiated-acceptance-20261024'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(name,data):
    with (OUT/name).open('x',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2,default=str)

def main():
    snapshot=read(OUT/'database-after-readonly.json')['tables']
    generation=read(AUDIT/'H-RETEST-1792836068109214700.json')
    rag=read(AUDIT/'D-RAG-1792836075961424000.json')
    material=read(AUDIT/'fresh-runtime-final32/rag-material.json')
    gen_response=json.loads(generation['provider_records'][0]['response_text'])
    raw=gen_response['choices'][0]['message']['content']
    candidate=json.loads(raw)
    import sympy as sp
    x,t=sp.symbols('x t',real=True)
    counterexample=sp.simplify((sp.integrate(t,(t,0,x))-x*x)/x**3)
    assert counterexample==-1/(2*x)
    assert sp.limit(counterexample,x,0,dir='+')==-sp.oo
    assert sp.limit(counterexample,x,0,dir='-')==sp.oo
    result=generation['generation_result'];assert result['status']=='failed' and not result['question_ids']
    assert result['failures'][0]['reason']=='CONFIRMED_WRONG'
    assert generation['database_counts_before']['questions']==generation['database_counts_after']['questions']==22
    assert generation['database_counts_before']['question_versions']==generation['database_counts_after']['question_versions']==22
    for table in ('daily_plans','practice_items','question_attempts','learning_events'):
        assert generation['database_counts_before'][table]==generation['database_counts_after'][table]==0
    frames=rag['turn_evidence'][0]['events'];done=next(d for name,d in frames if name=='done')
    delta=''.join(d['text'] for name,d in frames if name=='delta')
    assistant=rag['persisted_history'][-1]
    dbmessage=next(row for row in snapshot['chat_messages']['rows'] if row['id']==assistant['message_id'])
    assert delta==done['answer']==assistant['content']==dbmessage['content']
    citations=[]
    for cite in assistant['citations']:
        chunk=next(row for row in snapshot['document_chunks']['rows'] if row['id']==cite['chunk_id'])
        assert chunk['material_id']==cite['material_id']==material['material_id']
        assert chunk['index_version']==material['active_index_version']
        assert chunk['content']==material['normalized_text'][chunk['start_offset']:chunk['end_offset']]
        assert chunk['heading_path']==cite['heading_path']
        assert any(c['message_id']==assistant['message_id'] and c['chunk_id']==chunk['id']
            for c in snapshot['message_citations']['rows'])
        citations.append({'label':cite['label'],'chunk_id':chunk['id'],'material_id':chunk['material_id'],
            'index_version':chunk['index_version'],'content':chunk['content'],'persisted':True,'offset_matches':True})
    assert citations
    save('model-quality-verification.json',{'generation':{'raw_content_sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'candidate':candidate,'model_generation_quality':'FAIL','quality_gate':'PASS',
        'independent_counterexample':'f(x)=x satisfies all stated assumptions; original quotient = -1/(2*x)',
        'right_limit':'-infinity','left_limit':'+infinity','option_set_has_no_correct_two_sided_value':True,
        'additional_model_error':'explanation assumes f second derivative exists although stem only assumes continuous first derivative',
        'saved_question_count':0,'batch_id':result['batch_id']},
        'rag':{'result':'PASS_SINGLE_NEGATIVE_SAMPLE','answer':done['answer'],'citations':citations,
            'stream_done_db_history_identical':True,'browser_ui_tested':False}})
    protected_path=ROOT/'storage/quality-audits/naiwa-v33-closeout-20261023/paid-continuation-r8z/protected-start.json'
    expected=read(protected_path)
    changed=[name for name,value in expected.items() if not (ROOT/name).is_file() or sha(ROOT/name)!=value]
    assert not changed,changed
    save('history-protection.json',{'manifest':str(protected_path),'checked_files':len(expected),'changed':changed,
        'original_ten_json_incident':'UNRECOVERED: current protected copy integrity does not restore lost original bytes',
        'original_two_practice_request_drift_rows':'not restored or modified; retained incident database not connected',
        'ledger_verified_independently':True})
    ledger_path=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-v33-exploratory-r8z/provider-ledger.json'
    ledger=read(ledger_path);assert len(ledger['requests'])==17
    assert all(r.get('finished') for r in ledger['requests'])
    requests=[{'number':i,'request_id':row.get('request_id'),'scene':row.get('case_id'),
        'purpose':row.get('purpose'),'http_status':row.get('http_status'),
        'dispatch_attempts':row.get('http_dispatch_attempts'),'finish_reason':row.get('finish_reason'),
        'usage':row.get('usage'),'state':row.get('state')}
        for i,row in enumerate(ledger['requests'],1)]
    summary={'ledger_path':str(ledger_path),'sha256':sha(ledger_path),'count_before':15,'count_after':17,
        'real_requests_this_task':2,'global_remaining':23,'unknown_or_unfinished':0,
        'local_conservative_ceiling':22,'local_remaining':5,'unused_slots_are_not_new_authorization':True,
        'usage':{key:sum((r.get('usage') or {}).get(key,0) for r in ledger['requests'])
            for key in ('prompt_tokens','completion_tokens','total_tokens')},'requests':requests}
    save('ledger-summary.json',summary)
    lines=['# 真实 DeepSeek 请求账本摘要','',
        '本次追加 2 次，15→17；40 次总上限尚余 23 次。更严格的本地保留上限是累计 22，尚余 5；没有追加授权，也不自动续用。',
        '模型为 deepseek-flash；真实请求经过后端业务路由，不是浏览器 UI。未完成请求 0。',
        '',f'Canonical SHA-256：`{sha(ledger_path)}`。',
        '累计 tokens：输入 27,873，输出 11,835，总计 39,708。没有取得供应商实际账单，不编造人民币成本。','',
        '|序号|场景|请求 ID|HTTP|完成原因|总 tokens|','|---:|---|---|---:|---|---:|']
    for row in requests:
        lines.append(f"|{row['number']}|{row['scene']}|`{row['request_id']}`|{row['http_status']}|{row['finish_reason']}|{(row['usage'] or {}).get('total_tokens','未知')}|")
    lines+=['','## 本次新增',
        '- #16 R：历史生成失败修复后的正式生成/保存抽查。895 输入 + 604 输出 = 1,499 tokens；模型数学 FAIL，保存前拒绝 PASS；不自动重试。',
        '- #17 D：已索引测试资料不含考试频次的负向问答。2,393 输入 + 266 输出 = 2,659 tokens；明确缺乏依据且引用正确。',
        '- 本次新增合计 4,158 tokens；#1–15 不计入本次新增。R 为已授权的失败复测用途，不借用已耗尽的 C 生成场景额度。',
        '', '场景累计：A=3、B=2、C=4、D=2、E=2、F=2、H=1、R=1。场景上限没有修改。',
        '原父账本与旧账本受保护，本轮 canonical 只合法追加两笔；请求超时、失败及未知状态仍按原规则保留占额。',
        '', '完整机器证据见 [ledger-summary.json](ledger-summary.json)，原始 SSE 和模型 content 见 evidence-index.md。']
    with (OUT/'03-真实DeepSeek请求账本摘要.md').open('x',encoding='utf-8') as stream:stream.write('\n'.join(lines)+'\n')
    transcript=['# 本次真实模型原始回答与业务结果','', '这是后端正式路由测试，不是网页输入框对话。','',
        '## #16 生成复验',generation['user_prompt'],'','模型原始 content（原样保留，未纠错）：','```json',raw,'```','',
        '正式业务结果：failed；CONFIRMED_WRONG；saved_items=[]；question_ids=[]。',
        '', '## #17 RAG 负向问答',rag['user_prompt'],'',assistant['content'],'',
        'C2 已核对实际 chunk、资料、索引版本、正文偏移与持久化引用；没有 PDF 页码。']
    with (OUT/'REAL-MODEL-TRANSCRIPTS.md').open('x',encoding='utf-8') as stream:stream.write('\n'.join(transcript)+'\n')
    suite=ET.parse(ROOT/'storage/quality-audits/naiwa-four-item-closeout-20261024/final-replay/junit.xml').getroot().find('testsuite')
    assert (suite.get('tests'),suite.get('failures'),suite.get('errors'),suite.get('skipped'))==('4','0','0','0')
    print(json.dumps({'real_requests':2,'ledger_total':17,'generation_quality':'FAIL','gate':'PASS','rag':'PASS',
        'current_protected_files':len(expected),'changed_protected_files':0,'pg_tests':4},ensure_ascii=False))

if __name__=='__main__':main()
