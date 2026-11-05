# 奶蛙盲测续测：输出预算修复与真实出题结论

> 运行状态补记：用户随后明确授权仅重启项目后端。2026-10-19 20:08（上海时间）已完成，8000 后端 PID 4828→8560；健康及前端代理健康均通过，启动清单哈希与当前代码一致。PostgreSQL PID 21052、前端 PID 22184 未变。只读复核11张业务表数量/摘要不变，没有新增模型调用。下文“待确认”保留为续测交付当时的历史状态，现已解除。

日期：2026-10-19。承接 `NAIWA_REAL_USER_BLIND_ACCEPTANCE_20261019.md`，不是另开 10 次预算。

## 最终结论

**整体仍为 NOT_ACCEPTED。** 普通概念问答已取得一次真实修复通过；真实出题仍失败，不能声称完成“真实生成 → 加入今日卷 → 实际作答 → 学习记录恢复”。

累计 **10/10 次真实 DeepSeek 物理请求**，剩余 **0**。包含初次的 5 次和本次追加的 5 次，失败/截断均计数，没有自动重试、收费裁判或超额请求。后续只执行了免费浏览器和离线验证。

## 1. 追加调用逐次结果

| 总序号 | 用途 | HTTP | 耗时（秒） | 输入 Token | 输出 Token | finish_reason | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 6 | 原始幂级数概念问答复测 | 200 | 20.625 | 628 | 4000 | length | FAIL：请求级策略被延迟 Provider 包装器绕过，仍使用 low reasoning |
| 7 | 原始具体例子追问 | 200 | 19.140 | 640 | 3780 | stop | 内容相关并承接上下文；刷新历史相同，但不能抵消第6次失败 |
| 8 | 原始“比当前题难一点”的单题请求 | 200 | 6.219 | 972 | 1399 | stop | 非法 JSON，拒绝保存；独立阅读又确认答案与解析冲突 |
| 9 | 修复真实延迟 Provider 后再次原句问答 | 200 | 5.188 | 604 | 1035 | stop | PASS：实际 thinking=disabled，完整正文、数学内容相关；刷新与公式核验通过 |
| 10 | 同一原始单题变式请求 | 200 | 6.984 | 1028 | 1533 | stop | FAIL：非法 JSON，拒绝保存；独立阅读确认数学错误 |

前5次明细保留在原报告。当前完整账本输入 **9,445**、输出 **20,594**、总 **30,039 Token**，全部请求取得 usage，未知 usage 请求数 0。

按已核实官方高峰价格估算：未缓存保守总费用 **¥0.183642**，按实际缓存命中修正 **¥0.17561384**。不是实际供应商扣费账单；没有查询余额或宣称供应商硬性金额上限。软件阈值仍为 ¥0.90，未提高输入/输出额度。

## 2. 问答预算的真实根因与修复

原先 `reasoning_effort=low` 仍可能耗尽 4000 Token，不能保证有正文。第5次的4000 Token全部为 reasoning；第6次也达到 length。

先实现了请求级的普通概念讲解非思考策略，离线直接 Provider 测试通过；但第6次真实调用证明它未生效。追踪真实 HTTP 链路发现：

`/assistant:stream → _DeferredProvider → _provider_for_answer → isinstance(Provider)`。

延迟包装器不是 Provider，原先直接返回，所有只在实际 Provider 对象上实施的请求级策略都被绕过。这是产品真实调用链问题，不是可以用单元通过掩盖的模型偶发问题。

修复：

- `backend/chat/service.py`：对普通 general/normal 概念讲解克隆本次 Provider，并设置 `thinking=disabled`；保留4000输出上限。解题、当前题、复杂求值/证明、资料比较和 Agent 不整体关闭思考。
- `backend/api/routes/chat.py`：延迟 Provider 在确实需要送模时解析并转发 `for_answer`，应用同一请求级策略，免费确认/通知仍不要求模型。
- `tests/unit/test_blind_user_findings.py`：新增真实 HTTP 包装器路径回归，验证真正的请求参数，而不只检查直接构造的 Provider。

官方参数依据：https://api-docs.deepseek.com/guides/thinking_mode/ 。`low` 不等于关闭思考，关闭使用 `thinking.type=disabled`。

第9次实际请求已核对该参数，输出4000上限未增加，最终1035 Token完成正文。实际回答清楚区分求导/积分指数与系数变化、重编号、半径不变、端点单独判断；几何级数和对数级数例子无本次可确认的数学错误。浏览器有正常 KaTeX、没有 KaTeX 错误，刷新前后持久化消息完全一致。

这只证明该代表性概念讲解修复，不代表任意数学解题都完成真实质量验收。

## 3. 题目一致性检查的加强

涉及文件：

- `backend/services/generation_formula_consistency.py`。
- `backend/services/personal_question_general.py`。
- `backend/services/question_generation.py`。
- `backend/services/generation_diagnostics.py`。
- `tests/unit/test_blind_user_findings.py`。

在原有答案与 final_value 冲突检查之外，增加**有界、可独立推导的幂级数反证**：

1. 只处理可明确解析的单一幂级数，起点 n=1、系数为有限 Laurent 多项式，指数 -1 到4。
2. 从题干系数独立分解，通过几何级数的 Euler 求导和 `sum(x^n/n)=-ln(1-x)` 推导和函数。
3. 对正确答案和 final_value 分别检查；两个相同的错误答案不能相互证明正确。
4. 对明确的收敛域结论检查 ±1 的通项必要条件，拒绝多项式系数不趋零却包含闭端点的结论。
5. 采用受限 AST，不用 eval/parse_expr，不执行模型代码；长度、AST节点、运算数量、整数位数及幂指数均有界。
6. 找到可证明反例才拒绝；不支持的形式仍为 unknown，**不授予整题 PASS，不修改正式毕业规则**。
7. 新拒绝标识 `statement_answer_conflict` 进入现有答案检查诊断，不映射成网络失败。

提示也补充了同一份推导提取答案、通项趋零、低阶系数与 JSON 反斜杠转义要求。但**提示修改不作为质量通过证据**，后两次真实生成依然失败。

前端 `frontend/src/components/PersonalQuestionResult.vue` 对 reference-only 结果改为“已保存的个人参考练习”，并直接说明保存不等于答案正确性获得证明，不再仅使用“通过检查并保存”的大标题造成误解。该标签调整通过类型/构建检查；本次没有合格新题，不能冒充合格新题预览验收。

## 4. 后两次真实生题为什么仍失败

### 第8次

模型提出系数 `n^2+1/(n+1)` 的级数，同时给出和函数、收敛域和 x=1/2 的值。响应包含非法 JSON 转义，被解析层拒绝。

独立阅读发现其答案还与解析冲突：和函数中 `-1/x` 与 `-1` 混淆；数值答案写 `5-2ln2`，解析最后却得 `5+2ln2`。即使修复 JSON，也不能把这个响应当作合格题保存。

### 第10次

模型提出系数 `(n+2)/n=1+2/n` 的级数。正确和函数在 `|x|<1` 内应为：

`S(x)=x/(1-x)-2ln(1-x)`，收敛域 `(-1,1)`。

但 correct_answer 和 final_value 给出 `(2x-x^2)/(1-x)^2`；解析中又写回正确对数表达式，还将第3项系数写成7/3而不是5/3。原始 JSON 同时有不合法的转义，因此实际服务首先按格式错误拒绝保存。

**严格区分两件事**：

- 服务端真实执行到的是 JSON 解析拒绝；不能声称这两次实际触发了新增数学核验分支。
- 对内容的独立阅读和针对系数族的离线反证，说明它们即使被解析也含数学错误。没有为了跑完流程去修补这些响应、补写成正确题或绕过质量门。

本次3次真实变式生成（第4、8、10次）均没有取得可以认可的正确新题。最早第4次错误参考题仍只保留在隔离库审计；第8、10次没有保存题目、没有自动重试或创建练习。

## 5. 实际闭环状态

| 环节 | 最新状态 |
| --- | --- |
| 默认一道、一次Provider调用 | 真实确认正确 |
| 当前题/版本/知识点/相对难度传入 | 真实确认正确 |
| 普通概念问答修复后完整回答 | 第9次 PASS |
| 普通问答与study持久化及隔离 | 当前隔离范围 PASS |
| 生成一题且独立复核合格 | FAIL，没有合格真实题 |
| 合格真实题加入今日卷 | BLOCKED，未执行 |
| 提交该题、保存Attempt/LearningEvent | BLOCKED，未执行 |
| 该真实题作答与解析刷新恢复 | NOT_RUN |

合法个人题的工程闭环仍有隔离数据库与固定 Provider 测试覆盖，但不是本次真实模型质量验收。不能用它填补本表后三项。

## 6. 免费测试及浏览器复核

- 最新相关后端回归（包含嵌套幂安全预算）：**55 passed，0 failed，0 skipped，8.54s**。
- 最后在保留的隔离库重复专项回归：**11 passed，0 failed，0 skipped，0.80s**，与55项有重叠，不相加成66项。
- 前端：**125 passed**；类型检查、生产构建通过。
- 最终免费 Chrome：**4项 PASS**：
  - 第9次真实回答历史刷新和公式渲染，API消息前后一致。
  - 最后失败批次和诊断刷新恢复，今日卷不变，没有伪造成功预览。
  - study会话不能通过QA链接混入QA历史。
  - 服务端 QA/study 列表分别过滤、无ID交集。
- 最终浏览器页面异常0。
- 免费脚本在传输层禁止 DeepSeek 请求，复核前后账本始终10次。

第一次免费复核曾错误地期望从QA页面打开study会话，其失败记录保留为 `closure-attempt1-results.json`。最终改为验证正确的用途隔离，没有为让测试通过而暴露study历史。

## 7. 数据安全、运行版本与剩余阻塞

仍使用独立 `127.0.0.1:56675/kaoyan_blind_test`。续测仅修正了我们自己的测试计划状态 draft→active，解决初次夹具错误；没有改变原题或学习证据，没有把该修改用于强行加入错题。

最终数据库（相对最早夹具）：

- ChatSession：0→11，ChatMessage：0→33。
- Question：1→2，QuestionVersion：1→2，只有最早那道错误参考题，后两次没有新增题。
- PersonalGenerationBatch：0→3（1个早期完成，2个失败）。
- DailyPlan：1→1，PracticeItem：1→1。
- QuestionAttempt：0→0，LearningEvent：0→0，KpState：1→1。

没有修改真实开发库权限、题库、学习证据或毕业资格。本次所有自有验收服务和 PostgreSQL 已停止，隔离数据保留。

**开发8000的重启尚待用户单独确认**。已核对 PID 4828 属于本项目、使用 Python312 和原有启动器，但未终止它。隔离实例已加载新代码，不等于开发进程已加载。

剩余核心阻塞：

1. 真实出题仍无法稳定交付正确、合法结构的题目，完整闭环未验收；不能因已拦截坏题就说生题可用了。
2. 受限检查不是任意数学题/证明题的正确性证明，未知内容必须继续明示不确定性，不能升级正式资格。
3. 真实调用额度已用尽。未来任何真实模型复测需要新的明确授权，本次“继续”没有被解释为额外10次。
4. 开发服务生效待重启确认；没有静默重启或隐藏这一限制。

**最终：QA代表性修复已真实通过；真实出题与做题闭环仍未通过，状态 NOT_ACCEPTED。**

## 8. 证据

在 `storage/quality-audits/blind-user-20261019-v2/`：

- `provider-ledger.json`：累计10次，保留前5次原始记录，未重置。
- `continuation-results.json`、`final-model-results.json`：追加真实输入、SSE、页面回复、拒绝诊断。
- `FINAL-A1-concept.png`、`FINAL-B-generation.png`。
- `closure-results.json`、`closure-errors.json`、`CLOSE-real-qa-history.png`、`CLOSE-real-generation-failure-restored.png`。
- `database-after-continuation.json`、`database-after-final-model.json`、`database-after-closure.json`。
- `continuation-fixture-correction.json`、`resume-cleanup.json`。
- `storage/quality-audits/blind-user-20261019-final-safety-regression/pytest.log`。

辅助脚本更新：`scripts/blind_user_20261019_continuation.cjs`、`scripts/blind_user_20261019_closure.cjs`、`scripts/blind_user_20261019_resume.py`。这些属于本次独立验收，不替代正式产品接口。
