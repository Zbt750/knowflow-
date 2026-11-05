"""Evidence-backed reports; no model, database connection, or historical writes."""
from pathlib import Path
import json,csv,hashlib
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'storage/quality-audits/naiwa-v33-continue-20261023'
OLD=ROOT/'storage/quality-audits/naiwa-v33-final-20261023'
def write(name,body):
    with (OUT/name).open('x',encoding='utf-8') as f:f.write(body)
def main():
    stats=json.loads((OUT/'bug-register-statistics.json').read_text(encoding='utf-8'))
    matrix=json.loads((OUT/'visible-matrix/result.json').read_text(encoding='utf-8'))
    core=json.loads((OUT/'visible-core/result.json').read_text(encoding='utf-8'))
    fixture=json.loads((OUT/'clean-fixture.json').read_text(encoding='utf-8'))
    proc=json.loads((OUT/'clean-processes.json').read_text(encoding='utf-8'))
    incident=json.loads((OLD/'history-drift-incident.json').read_text(encoding='utf-8'))
    # Original per-physical-request records are preserved; never reclassify reservations.
    ledger_paths=[ROOT/'storage/quality-audits/naiwa-real-20261020/provider-ledger.json',ROOT/'storage/quality-audits/naiwa-real-retest-20261020-budget7/provider-ledger.json',ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021/provider-ledger.json']
    interactions=[];ledger_summary=[]
    for p in ledger_paths:
        d=json.loads(p.read_text(encoding='utf-8'));records=d.get('requests',[])
        ledger_summary.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'records':len(records)})
        for r in records:
            req=r.get('request') or {};messages=req.get('messages',[]) if isinstance(req,dict) else []
            users=[m.get('content') for m in messages if m.get('role')=='user']
            response={}
            try:response=json.loads(r.get('response_text') or '{}')
            except (ValueError,TypeError):pass
            choices=response.get('choices') or [];message=(choices[0].get('message') or {}) if choices else {}
            interactions.append({'ledger':str(p),'number':r.get('number'),'scene':r.get('case_id'),'http_status':r.get('http_status'),'finish_reason':r.get('finish_reason'),'usage':r.get('usage'),'latency_seconds':r.get('latency_seconds'),
                'latest_user_or_structured_goal':users[-1] if users else None,'assistant':message.get('content'),'tool_calls':message.get('tool_calls'),
                'quality':'历史响应原文归档；本轮未重新判定所有内容，工具调用并非最终回答'})
    transcript=['# 历史真实请求与完整正文（从原账本读取）','本轮未新增真实调用；结构化goal不冒充用户UI原文。工具回合可能没有正文，缺失字段为未知。']
    for r in interactions:
        transcript += [f"\n## {Path(r['ledger']).parent.name} / #{r['number']} / {r['scene']}",
            '状态与usage：'+json.dumps({k:r[k] for k in ('http_status','finish_reason','usage','latency_seconds')},ensure_ascii=False),
            '### 请求中的最新用户消息或结构化goal\n'+str(r['latest_user_or_structured_goal']),
            '### 实际助手正文\n'+(str(r['assistant']) if r['assistant'] is not None else '本回合没有可提取的正文；见工具调用或原始账本。'),
            '### 工具调用\n'+json.dumps(r['tool_calls'],ensure_ascii=False)]
    write('historical-model-transcripts.md','\n\n'.join(transcript))
    write('model-call-ledger-summary.md','# 真实请求及预算核对\n\n本轮新增真实模型物理请求 **0**。旧40次canonical仍为1次，不代表当前可直接使用39次。原付费epoch与当前源码不符；本轮新干净集群的cluster_id也不等于原授权运行时，未修改其授权或绑定规则，未调用open_scene。\n\n'+
        '\n'.join(f"- {r['path']}：{r['records']}条记录，SHA-256 {r['sha256']}。" for r in ledger_summary)+
        '\n\n前三阶段记录分别19、5、1；round5另有一个保守失败占额，DNS阻断与确认HTTP发送必须区分，不把它加成成功模型调用。完整历史正文及usage见historical-model-transcripts.md。本轮没有新的HTTP状态、usage、finish_reason或模型耗时；未知不填0。')
    write('V33-final-acceptance.md',f'''# 奶蛙最终真实用户深度测试与修复验收报告

日期2026-10-23。整体 **PARTIAL**；GET只读保护定向回归通过；不是全场景ENGINEERING_PASS或MODEL_QUALITY_PASS。

## 数据事故处理

原63044事故库未连接、未恢复两条漂移行、未迁移、未重写基线。事故文件仍在上一轮目录。调用链为study页面获取需求列表→正式GET /api/practice-requests→list_requests→提交事务中修改ORM。现改为只读会话和返回字典推导。

审查又发现GET /api/learning-tasks/{{id}}→get_task→factory.begin→将超时running改failed。现改为纯读取及TaskView副本；只有用户显式POST run时才在行锁下处理超时状态，不因刷新自动调用模型。

第一批独立PG测试1 passed。扩展后的最终独立集合 **6 passed / 0 failed**，不与前一批相加。扩展用例创建新的合成历史草案与超时任务，正式GET重复3轮及8线程并发4轮，覆盖请求列表、详情、跨会话、会话历史、今日卷及任务详情；前后public全表完整行哈希相等，并用SQL监听拒绝写入语句。未将内存桩当数据库验证。见pg-readonly-expanded/pytest.log和run-summary.json。该临时测试cluster_id与数据只属于测试runner，结束按原流程清理；长期干净体验站另行保留。

## 独立干净体验站

访问 http://127.0.0.1:{proc['identity']['web_port']}/ ，API {proc['identity']['api_port']}，PG {proc['identity']['pg_port']}，数据库naiwa_clean_test。新cluster_id {proc['identity']['cluster_id']}。监督{proc['supervisor']}，API{proc['api']}，Vue{proc['web']}，PG{proc['pg']}（启动时观测，需当前进程复核）。全新合成数据，不从已污染状态做恢复基线，不冒充旧体验站恢复。固定Provider和socket封闭；不修改日常5433/8000/5173。

## 实际页面

- 原V3.2 **48条**输入已通过可见Chrome逐条执行，保存回复/SSE/截图，JS错误{len(matrix['errors'])}；仅表示输入执行与渲染证据，不宣称48条语义全部PASS。固定回答无法证明真实数学理解。
- 核心五项脚本执行完成：C3版本交接、点击确认、正式题号、刷新；C5/D8撤回旧卡与不同候选；D6正库存；F7只读。见visible-core/result.json。
- 并发操作脚本在最后固定4选项断言FAIL，实际新合成题2选项。此前双标签确认、响应丢失回读等步骤的断言已走过，但**不把整脚本标PASS**。旧断言未改，失败日志在operations-clean/failure.json。
- 新独立尾部页面：实际3题已入卷后D6候选耗尽，仍讲解、无新草案，刷新一致，390×844无横向溢出。visible-tail/result.json。

## 尚未完成

取消/确认竞态、查询异常的浏览器故障注入、全部语义人工审阅、全部数学独立核验、整体生产构建/Vitest最终统一重跑、真实DeepSeek复验尚未完成。不能把历史测试通过数拼成本轮通过数。

代码修改：backend/services/learning_task_service.py；新增tests/integration/test_v33_get_row_preservation.py；新隔离启动器与浏览器脚本。上一轮list_requests修复本轮经过PG验证。没有毕业规则、正式题库或原学习证据修改。
''')
    write('scenario-matrix.md','# 本轮用户场景与状态\n\n48条均由可见Chrome、真实输入框发送。以下状态仅陈述执行终态，语义是否完全满足需看正文及工具。\n\n|编号|用户原文|HTTP|工程终态|回答质量|\n|---|---|---:|---|---|\n'+
        '\n'.join(f"|{r['label']}|{r['input'].replace('|','／')}|{r['http']}|{'SSE失败' if any(f['event']=='error' for f in r['frames']) else '已执行待语义审阅'}|固定Provider，真实质量未验|" for r in matrix['results'])+
        '\n\n另有visible-core的8条前置/主输入及确认操作，不能当成8条独立新语义；脚本核心断言通过。operations-clean整脚本FAIL；visible-tail零库存/手机刷新PASS。')
    old_history=(OLD/'naiwa-all-testing-history.md').read_text(encoding='utf-8')
    write('naiwa-all-testing-history.md',old_history+f'''

## 2026-10-23继续执行增补（优先于旧稿的当前状态）

本轮确实完成了真实PG GET验证、新干净持久站、48原文重放及核心业务UI，不再只有旧八条。历史事故没有恢复或抹去。又发现get_task的同类GET提交，将其独立列为S09。

CSV目前有{stats['total']}个去重ID，类型统计{json.dumps(stats['byType'],ensure_ascii=False)}，状态统计{json.dumps(stats['byStatus'],ensure_ascii=False)}。这是**已读证据覆盖集合**，不是宣称从最早所有测试目录穷尽。缺少逐字原文的项明确写摘要，不能虚构。N02原汇总拆成NET-F1/F2/F3，不重复计入。旧ID状态按本轮证据更新，仍未最终复验的记部分修复或未验证。

本轮重新读取19次原账本：真实回答记录、tool_calls、usage和finish_reason全部提取到historical-model-transcripts.md。需修正“历史真实题均失败”的印象：原19次中R2有独立数学核验和生成题做题记录，independent-math-review.json给出函数二阶展开极限1；learning-loop.json显示实际Attempt，客观结果unknown、assisted=true，未当作独立毕业证据。这是一个历史限定样例，不证明当前所有数学题正确。原7次授权阶段实际5次中的错误极限仍为真实生成FAIL。

### 为什么还会出现新问题

单元测试的内存状态、数据库事务、异步通知和多轮页面组合是不同观察面。旧测试只看新增题数会漏掉GET改历史状态；时间模拟和跨会话列表进一步触发该边界。重复scope字段、早返回意图路由、卡片缓存无失效通知是反复问题的共同架构原因。扩大覆盖不是把过去结果作废，但必须保留未覆盖边界，不能把HTTP200当业务PASS。

当前能做后端教程学习，但不宜宣称系统全场景冻结。真实模型、跨用户权限、取消/确认竞态及完整历史穷尽仍未验收；旧40次授权运行时未安全重绑定，不继续收费。
''')
    write('model-interaction-issues.md',(OLD/'model-interaction-issues.md').read_text(encoding='utf-8')+'\n\n## 本轮增补\n\n本轮真实模型0次。新增historical-model-transcripts.md提取历史19+5+1条记录的正文、工具调用和usage，缺失原文不填造。原19次中R2正确示例及unknown/assisted作答边界与错误生成样例分开评价。48条固定Provider重放不能算真实回答准确率。W01首用能力介绍缺项仍未真实复测。')
    write('system-and-infrastructure-issues.md',(OLD/'system-and-infrastructure-issues.md').read_text(encoding='utf-8')+'\n\n## 本轮新证据\n\nS08列表GET及S09任务GET均已通过真实新PG全表行哈希回归；原事故行不恢复。T01旧操作脚本固定四选项与新二选项fixture不匹配，保留FAIL，不修改断言迁就。新站是独立集群，不是绕过旧事故库身份保护。真实付费runtime依旧未绑定新代码和新集群。')
    write('unresolved-issues.md','''# 未完成与明确阻塞

1. 原两条漂移行仍保留事故状态；本轮未授权恢复，未更新旧基线。
2. 原10个历史诊断JSON原始字节仍未恢复。
3. 真实模型canonical账本仍1次，但旧付费epoch不匹配；新干净集群不是原授权运行时。不修改授权规则、旧哈希或预算来强开。需新的可审计受控绑定，而不是再次口头增加次数。
4. 操作脚本整体验收FAIL：固定4选项断言不适配新2选项fixture。应另补基于真实字段的通用断言，保留旧失败，不改变业务资格。
5. 取消/确认竞态、浏览器查询依赖异常、全部48语义人工判定、全历史逐条穷尽未完成。CSV34项是已核读集合，不虚构全量Bug总数。
6. 当前工程PARTIAL；真实模型质量PENDING。干净站固定Provider，不能用它评价真实模型回答质量。
''')
    write('evidence-index.md','''# 证据索引

- pg-readonly/：首次独立PG测试1通过，不与后续数量相加。
- pg-readonly-expanded/：本轮最新独立集合6通过，包含同类任务GET、列表、详情、重复及并发，无写SQL且全表哈希不变。
- clean-processes.json、clean-loaded.json、clean-fixture.json：新集群、进程、加载源码与合成数据。
- visible-matrix/：48条原始语义输入的完整SSE、正文、截图。
- visible-core/：原五项核心旅程及真实receipt/today API，精确版本与题号。
- operations-clean/：取消、双标签、丢响应过程；failure.json明确整脚本失败，不伪造result。
- visible-tail/：实际候选耗尽后D6讲解与无方案、手机刷新。
- historical-model-transcripts.md：从原19、旧实际5和V2单条账本提取的完整正文与工具回合，不等于本轮新调用。
- bug-register.csv：已读证据覆盖34项，逐项类型/根因/文件/状态/证据与局限。
- 原事故：../naiwa-v33-final-20261023/history-drift-incident.json；原始证据不覆盖。
- 原19次正确示例：../naiwa-real-20261020/independent-math-review.json、learning-loop.json；不能把unknown判题当可靠自动正确。
''')
    write('executive-summary.md',f'''# 本轮继续执行结论

整体PARTIAL，不是完全验收通过。GET数据保护修复已不再仅有内存测试：最终新PG集合6项通过，重复/并发/跨会话GET保持完整行哈希，另修复get_task同类写入。原事故库和漂移行未恢复或改写。

干净体验站：http://127.0.0.1:{proc['identity']['web_port']}/ ，固定Provider、零真实模型。原48条已实际输入，可见Chrome核心五项脚本通过；并发操作脚本整体FAIL（固定选项数假设），尾部零库存手机刷新另通过。

原40次账本没新增，当前付费运行epoch和集群未受控重绑定，真实测试BLOCKED。不能把理论余额39直接消费，也没有自动额外授权。

本目录已交付两份主要中文报告及CSV等10项文件，另附完整历史模型账本正文提取。CSV统计34项已读证据，不宣称全历史穷尽；未完成范围在unresolved-issues.md。下一步应先补通用字段断言及竞态回归，再做受控付费runtime绑定，不再反复增加口头预算。
''')
    print('REPORTS_CREATED',len(list(OUT.glob('*.md'))))
if __name__=='__main__':main()
