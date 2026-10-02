# P5 真实模型闭环复测与说明坏例

## 本轮实测

本轮在上一条已明确的隔离数据、费用和8次任务边界下，根据用户“继续下一步”应答执行。只使用合成数学/二叉树题、合成学习记录，以及允许的内置节点讲解；没有发送私人上传资料、开发学习记录、原始作答或本地凭据。

原始报告：`eval/reports/agent-evidence-live-20261001T122041-acd37f.json`。
SHA256：`fd2fe4384dbfa553bcd453b3d1497749fa1cc378843b2848e1f6cf6eaf09df81`。
来源为 HEAD `c841adbbddf82c5da3103474e63d7889afaf9c7f` 上的未提交工作区，具体关键代码/数据/工具哈希保存在该报告中。

- dataset：`p5-evidence-journey-v1`，P1源文件 SHA256 `23afaed03155afdf20bd792c21c311ba9b2ace52cf2b3124bd9d200703f3b575`。
- 模型：deepseek-flash，Provider configured output=4000；工具轮实际输出上限2000。
- Prompt：learning-task-v5，Prompt和工具定义哈希记录于原报告。
- 限制：每任务6轮、10工具调用、60秒，每轮至多两次尝试；整轮最多4场景/8任务，未追加自动整轮复跑。
- 实测：4/4程序约束通过，8任务、34次真实模型请求，0失败请求、0重试；无记录到的输出截断。
- 上游返回 usage 完整，观测 total_tokens=87,577，不据此估算金额。
- 整轮83.26秒；任务累积82.343秒，单任务8.828–12.250秒。

八次任务都实际使用 search_knowledge、get_learning_state、find_questions 和 validate_plan；408定位多次查询仍在轮次预算内。模型不是只能润色固定接口：它根据提交后的工具结果重新选题，并通过后端校验形成草案。确认由评测脚本模拟用户显式确认，在隔离schema中写入，确认与作答均检查幂等，确认前无业务写入。

## 程序结果与代码辅助内容审阅必须分开

下表是 Codex 对实际输出、工具事实与题目元数据的逐项核对，不是独立人工审核，也不是新的RAGAS评分。

| 场景 | 程序检查 | 真实第二次安排 | 内容审阅 |
| --- | --- | --- | --- |
| math_independent | 通过 | 读取1条独立结果证据，选另一道题 | 核心解释与证据一致；一道题不代表全面掌握 |
| math_wrong | 通过 | 读取客观错误/待复测，安排原题复测 | 核心解释与证据一致，不把结果证据当过程证据 |
| tree_assisted | 通过 | 识别solution_assisted_correct，安排原题重新验证 | 第二次辅助识别正确；首次说明却虚构已有自述，并把typical题说成变式题 |
| tree_ungraded | 通过 | 保留unknown，不制造客观错题，安排原题重新验证 | 首次说明虚构legacy自述；第二次文字声称已在今日卷，与in_today_plan=false及同段rationale矛盾 |

**不能把4/4程序PASS写成“所有解释都准确”。** 有问题的自然语言原样保留，不删除408坏例或重写原报告的 passed。独立真人教学审阅仍 pending，黄金题目核验仍未完成。

### 核心坏例及依据

1. `basis=legacy_self_reported` 仅是存储口径。两条408首轮工具数据的 `self_report=null`、`history_available=false`，模型却说“仅有有限自述/仅legacy自述”。这是把数据口径误当成事实存在。
2. T02 的 `question_role=typical`、`is_variant=false`，capability_keys仅 final_result。模型首轮把它说成“优先选变式计算题”。毕业缺口中的 required_variant 不证明候选就是变式题。
3. tree_ungraded 第二轮所选题的 `in_today_plan=false`，validate_plan通过；但message说“本题已在今日卷中不重复选，故没有备用题”，与工具及同轮rationale“今日卷无同题”冲突。另一个候选仍存在，不能依据历史做过或本次只选一题断言没有备用题。

这些问题说明选题/事务硬约束已经挡住非法写入，但自由文本解释尚不能当可靠事实。没有凭PASS筛掉这些问题。

## 本轮针对性补强（尚无修后真实模型分数）

- 学习状态工具新增 self_report_available 和 basis_note，明确口径与实际自评存在性不同；不回填旧数据。
- 题库工具显式返回 question_role、is_variant，配合已有 capability_keys；不依据题干猜测角色。
- 有界查询读取最多17条，仅返回16条候选，额外标记 candidate_list_complete；不能将截断候选数量冒充全部题量。
- 工具说明明确历史作答不等于今日已加入，只按 in_today_plan 描述；毕业缺口不证明库内已有对应类型题。
- 任务Prompt升为 **learning-task-v6**，增加上述事实约束。不改变普通问答Prompt、RAG检索或P0基线。

这是根据实测坏例补工具事实与提示，不是通用自然语言事实验证器；不能宣称提示词本身保证了无幻觉。原v5报告仍可证明该版本的选题/事务路径，但不能直接证明修后v6的解释准确率。

## 回归、范围及后续门禁

修后专项84 passed，无失败/跳过，33.962秒，报告 `eval/reports/agent-evidence-p5-grounding-20261001/targeted-junit.xml`。两个408场景修后离线协议均通过（4任务），报告 `eval/reports/agent-evidence-protocol-20261001T122910-6c2489.json`，不当作真实模型质量复测。36路径OpenAPI校验通过。

评测入口增加重复不扩量的 `--case` 选择，报告按所选场景记录 max_tasks/requested_cases。下一轮只有获得新的确认，才允许运行下列两个场景最多4任务；本轮8任务额度已用完，没有再调用：

```powershell
python scripts/run_agent_evidence_journey.py --live --allow-synthetic-data --case tree_assisted --case tree_ungraded
```

独立内容审核、模型优于规则的有效对照、更多题型/更长学习周期仍不能由本轮证明。P5不是全面教学质量完成，不自动进入P6或安装包路线。

## 获准后的 v6 定点复测：1/2，不隐藏新失败

用户明确确认“允许，仅两个408合成场景，最多4次任务”后，仅运行 tree_assisted/tree_ungraded，4任务、20真实模型请求。报告 `eval/reports/agent-evidence-live-20261001T123346-3485e2.json`，SHA256 `4644ce08c3cc61d4f7e635d99607d04b78a5de8d2f350e38f888957a9470639c`。

| 项目 | 结果 |
| --- | --- |
| 实际版本 | learning-task-v6，与修前v5报告分别保存 |
| 约束/目标检查 | 1/2；tree_ungraded通过，tree_assisted的requested_adaptation失败 |
| 用时 | 整轮47.23秒；任务累积46.499秒，单任务11.109–12.219秒 |
| 调用与用量 | 20请求，0请求失败/重试/记录到的截断，观测54,601 tokens，usage完整 |
| 原坏例 | 本次两场景不再把空自评说成有自述、普通题说成变式或历史作答说成今日已加入 |
| 新坏例 | 将“pending_review为空”当成“不能按用户要求复验原题”，辅助完成场景擅自换另一题 |

tree_assisted 第二轮明确读到 assistance=true、原题在今日卷之外、原题预计2分钟且预算5分钟；模型仍声称“当前没有待复测题，无法按重新验证上次那道题安排，只能选一道未做过的题目”。这是错误的规则推断，不是题量/预算真的不足。后端允许次日在新练习项复验，pending_review只是客观错题状态，不是复练许可。

没有放宽 requested_adaptation 断言，没有把选中其他真实题就算成功，没有自动第三轮调用。两次授权累计最多12任务，本轮实际12任务，后续预算不沿用。

## v7 有限补强与仍待证明的内容

- 候选新增 can_repractice_in_new_item，按实际今日卷成员关系派生，明确同卷去重与新练习项复验的区别。
- 工具说明和 learning-task-v7 明确：pending_review=false不代表禁止复练；辅助、猜测、unknown也可以按用户明确要求重新验证；原题可用且满足约束时不能擅自换新题。
- 保留原题定位来自真实最近记录，不用后端针对这条合成题写死题号，也不按特定句子改选题事务。
- 12个数学/408结果类别闭环都断言次日原题 can_repractice_in_new_item=true，只有客观错题/即时纠正保留pending_review；预算与去重仍由validate_plan负责。

v7专项84 passed；两个408离线4任务通过，报告 `eval/reports/agent-evidence-protocol-20261001T123751-764eb7.json`。v6之后第一次全量后端1169 passed、无跳过/失败，170.465秒，报告 `agent-evidence-p5-grounding-20261001/backend-junit.xml`，SHA256 `264e9c78f2cf5971dc79be3badc86afb513d6d79a58411e95120aecb3ee1b1fe`。v7最终全量收尾另记，不冒充v6报告已覆盖后来的修改。

**v7尚未做真实模型复测**，所以不能宣称新失败已在真实模型中消失。P0普通RAG数据与Prompt不变；本轮没有前端布局改动，没有重跑浏览器回归，也不把上一轮128条作为本轮新证据。开发只读仍22活动题/2673原卷引用/13作答/6计划，未导入候选或修改用户学习记录。

### v7 收尾

当前完整后端1169 passed、0 failed/error/skipped，171.381秒，报告 `eval/reports/agent-evidence-p5-repeat-policy-20261001/backend-junit.xml`，SHA256 `7edfc097df61457a5a8584616180474d63261da1133aecd70fd6608000f04b03`。专项84 passed，32.676秒；36路径OpenAPI一致，diff检查通过（已有换行格式警告不作为功能失败）。

当前任务服务代码 SHA256 `442c184598e1f2a9fd5d37fb7cd670b255eb71d70adc91ca99f06c5f71e420d2`，工具代码 SHA256 `44c2201dfce5ca7b94932ecf11f0a138c92bc6a736ced78156ac0e70b492af9a`，仍为同一HEAD之上的未提交工作区。只重启身份确认后的本轮开发后端，v7已加载，health为dev/database connected/retrieval ready/worker running；8000/5173/5433可用。没有reset/clean/checkout、提交或推送。

下一次最小补证可仅选择 tree_assisted（作答前后2任务），专门验证v7是否尊重用户复验原题。需另行确认，不自动调用；既有v5/v6失败样例不删除。P5状态仍是“工程回归通过，最新模型行为质量未完全验收”，不是已完成P6。

## v7 最小定点补证（用户继续后执行）

本轮仅 tree_assisted、最多2任务，根据上一条已明确范围与费用的问询及用户“进行下一步”应答运行；未扩大到其他场景，也未自动重复失败任务。原报告 `eval/reports/agent-evidence-live-20261001T125107-2a4757.json`，SHA256 `fa7471ec2cfc927767d0aaba952b6908abcb868d39b2b0c16b5c6c0a1409cb90`。

- 当前learning-task-v7、同一数据集；关键工具/任务服务哈希与v7全量回归一致，其他关键文件哈希在报告中可复现核对。
- 1/1程序目标及事务检查通过，2任务、10真实模型请求，24.19秒；任务累计23.641秒。
- 观测28,492 total_tokens，上游usage完整，0请求失败/重试/记录到的截断。
- 第二次任务实际读取 solution_assisted_correct、无独立确认、无客观待复测标记，以及 can_repractice_in_new_item=true。模型正确按用户要求安排原题，在新练习项重新验证；没有再说“无待复测标记所以不能重做”。
- 两次确认与答案提交幂等、确认前无业务写入、原确认回执保留均通过。开发仍22活动题/2673原卷引用/13作答/6计划，health正常。

代码辅助阅读发现首次说明仍混用“填空题对应计算题”；实际候选、草案question_type与rationale都是calculation，未造成错选或错判。这一表述精度问题保留为已知问题，**不能因为核心复验目标通过就声称所有说明准确**。本轮没有再改Prompt/代码或隐去原输出，独立真人教学审核仍pending。

本次约定的复验坏例已完成定点验证；v7工程回归与该目标已通过，可推进后续工作，但不把v5四场景、v6两场景、v7单场景拼成“最新版本全量4/4”。不证明模型优于规则、全科题库质量、长周期教学效果或重复多次的统计稳定性。黄金内容人工核验仍是独立发布门禁。

本轮只新增评测与记录，产品代码未改变。直接复用哈希一致的v7后端1169全量和84专项，不为了新报告重复执行这些测试或额外调用模型。下一阶段P6应按P0真实RAG坏例定点处理，普通RAG现有基线在本轮未改动。
