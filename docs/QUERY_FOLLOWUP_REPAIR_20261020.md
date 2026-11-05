# 奶蛙同会话题库统计追问修复

日期：2026-10-20（Asia/Shanghai）

状态：PASS——最终代码在隔离 PostgreSQL、真实 Vue、FastAPI/SSE、系统 Chrome 中通过定向验收。
现有 8000 / 5173 服务未重启，本报告不代表当前开发进程已经加载修改。

## 实际根因

1. `classify_read_only_data_query()` 仅处理当前原文。其题库主题规则包含“题库”“题目”“练习题”，遗漏“洛必达法则的题”这种表达；旧指代规则也没有覆盖“其中”“这些题”“那里面”。第二轮因此没有执行数据库查询，而是被路由到普通 QA；这不是一次 SQL 查询失败后的静默降级。
2. `_resolve_query_scope()` 依赖显式知识节点或 `StudyContext.subject`。QA 当前消息中的“数学二”没有被规范化为数据库科目“考研数学”；当页面没有传 subject 时，第一轮就会以 subject=None 查询全部科目。
3. 原来的历史回溯主要读取知识点 ID，没有持久化科目、可练资格和来源筛选口径。即使找到了上一轮知识点，也不能可靠完成“其中真题 → 这些题做过多少 → 哪些做错”的连续筛选。

## 修改

### 业务代码（3 个文件）

- `backend/services/assistant_data_queries.py`：识别数量型追问；规范化数学二/数二/408；从同一会话最近一轮有效业务查询恢复条件；持久化 `query_state` 和 `antecedent_message_id`；对新增知识点与原范围取交集；继承可练资格和来源条件；按真实 QuestionAttempt 查询做过/做错记录；按作答版本显示错题摘要。未知或范围冲突时明确澄清。
- `backend/services/learning_assistant_service.py`：路由执行前调用会话感知的 `classify_session_data_query()`。
- `backend/chat/service.py`：现有资料问答业务数据分支复用相同分类入口，避免该调用方继续只做单句分类。

未新增数据库字段、迁移或生产测试 API。未修改毕业规则、题目资格标准、前端视觉或题库内容。

### 定向测试及隔离设施

- `tests/unit/test_query_followup_routing.py`
- `tests/integration/test_query_followup.py`
- `tests/integration/query_followup_backend.py`
- `frontend/acceptance/query-followup.spec.ts`
- `frontend/playwright.query-followup.config.ts`
- `scripts/run_phase45e_test_cluster.py`：增加本次专用测试后端和配置分支，沿用原有独立 PostgreSQL 管理器与独立端口分配。

## 最终真实链路结果

样本均为明确标记的隔离合成数据：6 道 Question，其中数学二 5 道、408 1 道；数学二中 1 道未审核题不可练。不存在把合成“真题分类样本”冒充真实历年试卷的结论。

| 轮次 | 实际页面输入 | 数据库查询结果 | 实际读取 |
| --- | --- | --- | --- |
| 1 | 我题库里有多少道数学二的可练题？ | 可练 4 道，有效 5 道；不计 408 | question_availability |
| 2 | 那其中洛必达法则的题有多少道？ | 可练 3 道，有效 4 道 | question_availability |
| 3 | 其中多少道是真题？ | 洛必达范围内真题分类可练 2 道 | question_availability + 原始来源分类 |
| 4 | 这些题我做过几道？ | 上一轮 2 道真题均做过，2 次提交 | QuestionAttempt / LearningEvent / get_learning_state |
| 5 | 那里面我做错过哪些？ | 1 道，显示“洛必达真题甲”，不混入原创题 | 同上，附真实 QuestionVersion 绑定 |

五轮均保存 `subject=考研数学`、`eligibility=practice_eligible`；第 2 轮起节点固定为隔离洛必达节点 `d1c6312c-6805-4381-8420-ceb5631b0a82`；第 3 轮起来源为 `exam_curated`。

刷新后 5 条用户消息、5 条回答顺序和最终错题回答保持一致，无浏览器未捕获异常。

查询前后业务实体计数均保持：Question=6、QuestionVersion=18、PracticeItem=5、QuestionAttempt=5、LearningEvent=5。仅隔离会话与消息正常持久化。

另有集成测试先查询库存，再在隔离夹具中隐藏一题，随后追问正确返回更新后的数量，证明查询没有复用预设文本或缓存的上轮数量。

## 实际测试结果

- 最终 Python 定向回归：**91 passed，0 failed，0 skipped**（含 7 项 PostgreSQL/API 集成场景及相关路由回归）。
- 系统 Chrome，真实 Vue → FastAPI/SSE → PostgreSQL：**1 passed，0 failed**；该用例包含完整 5 轮、逐轮数据库核验、查询前基线、刷新恢复与页面截图。最终使用 Chrome headless 模式；不是人工输入或用户本人体验。
- `npm run typecheck`：退出码 0。
- 相关已跟踪修改的 `git diff --check`：通过。
- 无匹配知识点、跨会话无前文、切换到明确新科目、无关回答结束旧查询上下文、查询异常不回退通用回答：通过。
- 最终捕获 **98 条真实只读 SQL**，只记录 SQL 语句和表名，不记录参数或凭据。

早期调试失败产物仍保留于 `run-01` 至 `run-04`：包括夹具缺少资格配置、测试错误依赖 JSON 空格格式、可见 Chrome 窗口关闭。均未删除或降低断言；最终目录为 `final`。

## 证据

目录：`storage/quality-audits/query-followup-20261020/final/`

- `run-summary.json`：隔离 PostgreSQL 端口 **54164**，原集群未触碰，定向验收均退出 0。
- `pytest.log`：91 项后端回归。
- `playwright.log`：真实 Chrome 结果。
- `fixture.json`：隔离题目与节点 ID、已知期望数量。
- `browser-report.json`：包含 `database-before`、`database-round-1` 至 `database-round-5`、`actual-sse` 和 `executed-read-sql` 附件。
- `read-sql.jsonl`：实际执行的只读 SQL。
- `model-calls.json`：空数组。测试 Provider 被实现为拒绝任何模型方法调用，未返回任何预设查询答案。
- `browser-artifacts/.../round-2.png`：原始失败追问现在返回洛必达真实计数。
- `browser-artifacts/.../refresh-restored.png`：五轮后刷新恢复。

## 边界与剩余事项

- 本轮真实 DeepSeek 物理请求：**0**。
- 未连接 127.0.0.1:5433/kaoyan；未重启 8000、5173 或现有 PostgreSQL。
- 所有测试写入仅在本次独立临时 PostgreSQL 中，验收后由原有管理器停止并回收自己的临时集群；证据保留。
- 真实业务库内数学二和洛必达题目数量未查询，不能将本报告的合成样本计数当成用户题库数量。
- 当前开发进程加载本轮修改尚未验证：遵守用户禁止擅自重启的要求，本轮只完成源代码修复和隔离真实链路验收。
