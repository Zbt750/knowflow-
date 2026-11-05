# Phase 6 黑马式 AI 应用开发教程——总设计方案

> 当前长期规范、20天安排和API护栏已经统一为[tutorial-rules.md](tutorial-rules.md)、[tutorial-roadmap.md](tutorial-roadmap.md)、[api-contract-baseline.md](api-contract-baseline.md)。本文件保留历史分析，不再作为当前日期/篇幅/契约约定。

> 后续读者反馈已修正教学规范：以同一复现工程的真实功能增量为主线，不以独立lab为主线，不强套每篇模板或面试题。具体以[最新教程生成规范](TUTORIAL_AUTHORING_RULES.md)为准；本文件原章节样式约定与之冲突处不再适用。已试写的两篇实验样章不代表正式章节通过。

项目：《自适应考研学习知识库》  
版本：2026-10-16 第二版；按 AI 应用开发实习目标重新分配权重。  
状态：PHASE6_0_DESIGN_READY_AWAITING_CONFIRMATION

本轮只修订总设计、代码地图和学习安排，尚未编写课程正文或教学代码。确认本方案后，再开始第一章。产品架构、题库、毕业算法、运行配置和冻结评测资产均保持原样。

配套：[20 天逐日安排](20_DAY_STUDY_PLAN.md) · [代码重要性地图](CODE_IMPORTANCE_MAP.md) · [源码与资产基线](SOURCE_BASELINE.json)。

## 1. 教学目标与硬性时间分配

课程名称：《自适应考研学习知识库——20 天从零到项目落地手把手教程》。

每天暂按 **5 小时，合计 100 小时**规划。每段教学按主目标只计入一个时间类别，不把同一小时同时算入 RAG、LLM 和 Agent。

| 教学类别 | 权重 | 小时 | 对应日期 | 最终能力 |
|---|---:|---:|---|---|
| RAG / 检索增强 | 25% | 25 | D2–6 | 独立实现结构化分块、索引、三路召回、融合与上下文 |
| Agent / Tool Calling / 学习任务 | 25% | 25 | D13–17 | 工具取证、有限循环、预算、草案、校验、确认、回放 |
| 后端 / 数据库 / 核心学习业务 | 20% | 20 | D1、D10–12 | 独立写接口/事务，解释版本、作答和证据闭环 |
| LLM / Prompt / SSE / AI 评测 | 15% | 15 | D7–9 | 模型接入、多轮/流式、引用、错误、测评和计费记录 |
| 工程化 / 测试 / 部署 | 10% | 10 | D19–20 | 隔离验证、错误定位、Windows 运行、发布边界 |
| Vue 3 / TypeScript 接口理解 | 5% | 5 | D18 | 看懂页面→API→状态/SSE，定位前后端问题 |
| 合计 | 100% | 100 | 20 天 | AI 核心 65%，其余支撑 35% |

每一天按“上午 1 小时理解 → 下午 3 小时实现/运行 → 晚上 1 小时复盘/面试”组织。这里表示学习时段，并不要求必须在白天学习。

与第一版相比，Agent 从 3 天增加为 5 天；数据模型、练习、证据和毕业集中在 3 天业务主线，加上 1 天后端基础；AI 评测获得明确的课程位置。前端集中 1 天，之前使用 Swagger/测试客户端验证后端，不额外安排 Vue 重写。

基础假设：能写 Python 函数/类、使用字典/列表和 import，但可以没有 FastAPI、SQLAlchemy、RAG、Agent 经验。D1 补齐阅读所需的类型、异常、with、async 基础。若每天实际只有 2–3 小时，需要调整天数或独立手写范围，不能承诺同样深度。

## 2. 4,000–6,000 行指什么

这是最终能独立重写的核心代码范围参考，**不是**整个产品的目标总行数，更不是删代码指标。

| 核心手写内容 | 参考规模 |
|---|---:|
| RAG：清洗/标题树/分块、编码与索引、BM25/Vector/Title、RRF、重排/Context | 1,200–1,500 行 |
| Agent：工具、事实、循环、校验/确认、Context、恢复与回放核心 | 1,200–1,500 行 |
| 后端与业务：接口/Session、核心模型/查询、版本/作答/证据 | 800–1,200 行 |
| LLM：Provider、Prompt、SSE、多轮、评测与 ledger 核心 | 600–1,000 行 |
| 工程测试/配置核心和少量前端接口 | 280–650 行 |
| 合计参考 | 约 4,080–5,850 行 |

规模包含选定的核心函数与必要行为测试，不把生成代码、整份历史兼容文件和完整 Vue 页面算成独立手写成绩。具体篇幅以完整可运行和行为正确为准，不为达到行数删约束。

A 类核心必须亲手写；B 类业务跟着完整实现；C 类框架/历史兼容完整配套并读懂连接点；D 类前端大部分复用后理解；E 类评测核心同样必须写，历史批次脚本只读。

## 3. 当前项目实际规模和证据边界

统计为指定目录中的 Python/TS/Vue/PowerShell/CMD 非空文本行，包含注释/文档字符串，不是纯代码 SLOC。未计依赖、数据库、模型权重、上传资料、图片、CSS 和运行产物。

| 范围 | 文件数 | 非空行 |
|---|---:|---:|
| backend | 155 | 27,430 |
| frontend/src（含生成类型和单测） | 82 | 17,923 |
| tests | 243 | 26,613 |
| frontend/e2e | 46 | 5,497 |
| migrations | 29 | 1,827 |
| scripts | 259 | 45,756 |
| desktop | 6 | 723 |
| 上述代码范围合计 | 820 | 125,769 |

frontend/src/api/types.ts 为生成文件，占 9,692 行；21 个前端单测文件占 538 行。其余本口径 TS/Vue 为 7,693 行。大量 scripts 是历史内容建设/维护，并非每天运行的产品主线。

另核对了 eval 与 docs：eval 主要是数据、资料、rubric 和执行计划，不是 Python 包；检索指标代码在 backend/eval，AI 测评运行器在 scripts。排除 eval/reports 后，eval 有 16 个 Markdown 文档；本轮修订前 docs 有 196 个 Markdown 文档，这些不能全部当最新规范通读。

本次先复核第一版 60 个关键源码文件的 hash，全部未变化，再补查评测/部署代码。没有连接数据库、运行模型、执行迁移或重新跑测试。既有 [Core UX 收口报告](../CORE_UX_FINAL_CLOSEOUT_20261016.md) 的 213/0/7 是历史验收证据，本轮不改标为新结果。1804 道正式题和 253 套题集来自已有发布证据，不是本轮实时库统计。

## 4. 必须纠正的旧描述

| 旧描述/示意 | 当前源码事实 | 教程处理 |
|---|---|---|
| 全项目约两万行，按文件学完 | 当前后端已超过该规模，还有大量脚本/测试 | 选核心职责，不按文件均分时间 |
| 固定跨天/题型/变式配额是当前毕业条件 | v3 检查适用非空冻结题集的可信完成；v1/v2 是历史兼容 | 重点讲题目完成、学习安排、节点汇总的区别 |
| 一次正确永远不能完成题目 | 可信独立正确可形成题目确认；辅助/特殊重做类别另判 | 不混淆单题确认与节点完成全部规定题 |
| Question 只有 ID 和指针 | Question 保留当前投影，flush 生成不可变 QuestionVersion | 讲实际模型，不虚构纯身份表重构 |
| Agent Prompt 是 v18，eval README 写 v10 | 当前 Agent v19-lossless-records，chat trace 为 v11 | 报告保留历史版本，课程以源码为准 |
| Provider / SSE 各有独立文件 | Provider、encode_sse、stream_answer 主要在 chat/service.py | 精确定位现有符号，不发明 provider.py |
| 标题树就是知识树/纯语义分块 | 文档树先确定结构，字符窗口与段落边界兜底；知识树另有模型 | 两棵树分开讲，不宣称纯语义分块 |
| 所有问答都走一个范围切换器 | ChatPage 学习问答；MaterialsPage/MaterialSearch 做资料查询 | 按实际页面与 API 分支说明 |
| 图中 Repository 表示已有仓储包 | 当前没有统一 Repository 包，部分路由也查询/组装响应 | 不为教学新增架构层 |
| Agent 或问答一次任务等于一次模型请求 | 工具循环、意图辅助调用和有界重试可能额外发 HTTP | 逐物理请求记账，业务回合另统计 |
| Chroma 是 Compose 服务，Docker 与本机一致 | 本地 Chroma 客户端；Compose PG16，本机验收 PG18.4 | 不复用 PG18 物理目录给 PG16 |
| 旧 Golden Slice 人工审核说明是当前所有正式题门槛 | eval/golden 是历史小切片；当前公共正式题有 AUTO_VERIFIED 路径 | 用于解释演进，不恢复旧人工逐题门禁 |
| health 是只读，所以启动原应用也只读 | lifespan 有恢复 generating 消息等写行为 | 教程仅启动独立学习库 |

## A. 项目真实架构

~~~mermaid
flowchart TB
    UI["Vue 页面 / API client / SSE reader"]
    API["FastAPI Router + Pydantic + Depends"]
    LIFE["lifespan / app.state<br/>Settings · Engine · SessionFactory · RetrievalStack"]
    MAT["Material Service → DocumentJob / Worker"]
    ING["Parser → Normalize → Title Tree → Chunk"]
    RET["Vector + 正文BM25 + 标题BM25<br/>RRF → 可选Rerank/MMR"]
    CHAT["会话 / Scope / History / Context / Citation / SSE"]
    ROUTE["assistant_router / learning_assistant_service"]
    TASK["TaskTools / 有界循环 / 事实压缩 / Draft"]
    VALID["Validate → 用户确认 → 再校验"]
    STUDY["今日学习 / 判题 / Attempt / Event / 状态投影"]
    PG[("PostgreSQL<br/>权威正文、题目版本、事实与状态")]
    VECTOR[("本地 Chroma 派生索引")]
    FILE[("上传目录 / 本地模型缓存")]
    LLM["配置的 OpenAI-compatible Provider"]

    UI --> API
    LIFE --> API
    API --> MAT
    MAT --> FILE
    MAT --> ING
    ING --> PG
    ING --> VECTOR
    API --> CHAT
    CHAT --> RET
    RET --> PG
    RET --> VECTOR
    CHAT --> LLM
    API --> ROUTE
    ROUTE --> CHAT
    ROUTE --> TASK
    TASK --> PG
    TASK --> LLM
    TASK --> VALID
    VALID --> STUDY
    API --> STUDY
    STUDY --> PG
~~~

这些框是一个本地单用户应用的职责，不是新增微服务。当前使用 DocumentJob/本地任务线程，不引入 Celery/Redis；Chroma 不是独立部署服务。

## B. RAG 完整数据流

~~~mermaid
flowchart LR
    U["上传资料"] --> F["流式保存 / Material / DocumentJob"]
    F --> P["格式解析 / 规范化"]
    P --> T["标题序列 / 栈构树 / 正文归属"]
    T --> C["Chunk / heading_path / offset / hash"]
    C --> DB[("PostgreSQL")]
    C --> E["Embedding"]
    E --> V[("Chroma")]
    DB --> K["内存正文/标题 BM25"]
    Q["问题 + 会话资料范围"] --> S["ready / active_version / material过滤"]
    S --> R["三路召回"]
    V --> R
    K --> R
    R --> RF["RRF"]
    RF --> BACK["回表读取权威正文"]
    DB --> BACK
    BACK --> RK["可选 CrossEncoder / 条件 MMR"]
    RK --> CT["有限 Context / 引用映射"]
    CT --> M["Prompt / LLM / SSE"]
    M --> CIT["回答 + chunk/material 定位"]
~~~

RAG 的 25 小时分别解决摄取、结构、索引、召回、证据五层问题：

- 当前标题树先划定同一路径的直接正文，再以段落/句末和默认 700 字符窗口切分，不称“纯标题树智能分块”。
- 必须保持 content == normalized_text[start:end]；heading_path 是结构，不是额外拼接进权威正文的字符串。
- BM25、余弦、RRF 分数用途不同。RRF 只融合名次，不能作为事实正确性阈值。
- CrossEncoder 未配置时用 IdentityReranker；MMR 在 diversify 路径条件启用，不宣称请求都实际经过两者。
- query_context.py 只对有限显式追问补充前一个具体用户问题，不是万能 LLM query rewrite。
- 回答引用只能来自当前实际证据；资料不足时区分严格资料范围与允许标识的通用知识，不取消范围隔离。
- D6 写检索指标：当前 backend/eval 的 Recall 是按标题主题覆盖计算，不把它冒充 RAGAS Context Recall。

## C. Agent 完整数据流

~~~mermaid
flowchart LR
    REQ["用户任务 / StudyContext"] --> RT["意图/能力路由"]
    RT --> LOOP["有界模型循环"]
    LOOP --> CALL["白名单 Tool Calling / Schema"]
    CALL --> FACT["真实学习状态 / 库存 / 来源 / 版本 / 资格"]
    FACT --> PACK["送模副本无损压缩 / 引用去重"]
    PACK --> LOOP
    LOOP --> DRAFT["Task Draft"]
    DRAFT --> VP["服务端 validate_plan"]
    VP --> WAIT["保存草案 / 等待用户"]
    WAIT --> CONF["用户确认 draft_version"]
    CONF --> RECHECK["重查资格/版本/时间/范围/当前计划签名"]
    RECHECK --> PLAN["事务内建卷或追加"]
    PLAN --> LEARN["用户真实作答"]
    LEARN --> EVENT["Attempt / LearningEvent / KpState"]
~~~

模型负责理解和选择工具，服务端提供事实、约束和执行权限。工具读取数据不等于授权写入，草案也不是计划。Agent 未读到事实时不能凭常识补库存或学习记录。

25 小时用五个完整任务学习 Agent：真实工具、有界循环、可确认方案、Context、恢复与评测。时间/题型/范围、个人题隔离、辅助正确与历史版本全部沿原业务链复用。

当前约束来自 learning_task_service.py：最多 6 轮、10 次工具调用、总任务 60 秒，messages+tools 送模序列化超过 60,000 bytes 被拦截。字节、估算 token、输出 max_tokens 和费用停止是四件不同的事。

## D. 后端请求链路

普通短请求：Vue/API client → Router 校验 HTTP/DTO → Depends 提供 Session/时钟 → Service 规则/事务 → ORM/PostgreSQL → Response Schema → 前端状态。

SSE/Agent/后台任务：Router 获取共享 session_factory → 服务在合适的短事务中读/写 → 释放连接 → 网络或长任务 → 再用独立短事务保存结果。不能把一个请求 Session 跨线程共享，或占着事务等待模型。

Engine 管连接池，Session 管工作单元，flush 不是 commit。lifespan 创建共享基础设施并关闭资源；app.state 存工厂/模型/索引，不存某个请求独有的 Session。D1 用完整配套代码讲清这些骨架，不用大量 CRUD 练习占掉 AI 时间。

## E. 数据模型关系与事实边界

下图是实际模型的概念关系，不凭图新增表。题集成员实际为版本表中的 JSON ID 数组和 hash。

~~~mermaid
flowchart TB
    KP["KnowledgePoint 父子教学结构"]
    Q["Question 稳定ID + 当前投影"]
    QV["QuestionVersion append-only"]
    DP["DailyPlan"]
    PI["PracticeItem 绑定版本"]
    AT["QuestionAttempt 作答事实"]
    EV["LearningEvent 行为/证据事实"]
    KS["KpState 状态投影 / 适用题集绑定"]
    SET["KpGraduationQuestionSetVersion<br/>题目ID/版本ID数组+hash"]
    MAT["Material"]
    CH["DocumentChunk"]
    CS["ChatSession"]
    CM["ChatMessage"]
    MC["MessageCitation"]
    LT["LearningTask 工作状态 / Draft / trace"]

    KP --> Q
    Q --> QV
    Q -->|current_version_id| QV
    DP --> PI
    QV --> PI
    PI --> AT
    QV --> AT
    AT --> EV
    QV --> EV
    KP --> KS
    EV --> KS
    KP --> SET
    SET -->|版本化成员| QV
    KS -->|固定适用版本| SET
    MAT --> CH
    CS --> CM
    CM --> MC
    MC --> CH
    CS --> LT
~~~

QuestionVersion、Attempt、LearningEvent 和审核事件保存历史事实；KpState 是投影，不替代原始事实；LearningTask 是规划工作状态，不证明已学习。Question 当前投影、Material 状态、任务状态可以按受保护流程改变，不代表旧版本可改。

v3 毕业依据适用规定题集全部可信完成。先前做错不永久封死单题完成；辅助后立即答对不冒充独立完成。复习安排留在学习驱动层，个人题不进入正式毕业，历史题集与已毕业事实不被新题改写。D10–12 讲当前业务主线，旧 v1/v2 兼容完整提供但不逐行复刻。

## F. LLM 调用链与 15 小时教学内容

~~~mermaid
flowchart LR
    CFG["Settings + 本地设置覆盖"] --> PRO["provider_from_settings / Provider"]
    INTENT["QA / RAG / Agent 业务意图"] --> MSG["System / User / History / Tool Messages"]
    CT["真实检索证据或工具事实"] --> MSG
    MSG --> LIMIT["输入/输出/时间预算"]
    LIMIT --> PRO
    PRO --> HTTP["OpenAI-compatible HTTP / DeepSeek配置"]
    HTTP --> RESP["content / tool_calls / usage / finish_reason"]
    RESP --> STATE["校验 / 持久化 / SSE 或 Task结果"]
    HTTP --> ERR["网络/超时/Provider/截断/预算分类"]
    ERR --> STATE
    STATE --> LED["trace / 物理请求 ledger / 用户可恢复终态"]
~~~

D7：配置/Provider/Prompt/结构化输出协议；D8：多轮、SSE、历史与引用；D9：模型应用评测、错误和计费记录。

Provider 当前就在 chat/service.py，不能为了教学换成另一家 SDK/框架。工具参数 Schema 是协议约束，不能单凭“输出了 JSON”就认定事实正确。Embedding 模型负责表示，生成模型负责文本/工具消息，二者不能混称。

课堂默认离线 Provider 保护协议测试；读取历史真实回答分析质量。真实 DeepSeek 验收必须另行批准请求/金额/外发数据，历史授权不沿用。没有 usage 记未知，不写零；软件费用停止不是供应商扣费硬上限。也不把代码里的历史价格默认值当当前报价。

## G. 评测与测试体系

评测是 AI 核心教学，不只在最后讲 pytest。

| 层 | 当前位置 | 学生要实现/理解什么 |
|---|---|---|
| 检索客观指标 | backend/eval/dataset.py、metrics.py；scripts/run_retrieval_eval.py | 自写 Hit@K/主题 Recall@K/MRR，解释分母与越界 |
| RAG 回答/引用 | chat/evidence.py、answer_contract.py；eval/dataset、RAGAS scripts | 证据支持/引用范围/要点覆盖；四项 RAGAS 概念与裁判局限 |
| Agent 行为 | TaskTools、validate_plan；tests/integration/test_learning_tasks.py | 取证、真实ID/来源、时长、可执行草案、确认边界 |
| 冻结案例/rubric | eval/phase5-closeout-v1 | 案例/fixtures/rubric/hash/执行范围，PASS与未完成不能混算 |
| 历史 Golden Slice | eval/golden | 小范围来源与正确性证据的演进，不复制旧人工审核门槛 |
| 调用观察与费用 | chat/call_trace.py、scripts/phase5_eval_meter.py | 物理请求、usage/finish_reason、未知预留、BudgetStop |
| 离线回放 | scripts/phase5_agent_final_offline.py、真实历史工具轨迹 | 重建载荷/验证事实，不能冒充新模型成功 |
| 自动化工程测试 | pytest、Vitest、Playwright | 算法、事务、UI三层职责与合成隔离 |

D6 评检索，D9 评回答/引用/成本，D17 评 Agent，D19 汇总工程回归。RAGAS 有可能触发收费裁判，课程默认只读既有结果和讲公式/偏差，不自动运行收费评分。评分失败、网络停止、未执行必须保留，不从分母中删掉。

### Phase 5 工程案例如何进入课程

| 案例 | 真实问题和出处 | 教学动作 | 验收边界 |
|---|---|---|---|
| Q07 | 输出 length/截断；PHASE5_AI_REAL_RETEST_REPORT | 查看 finish_reason、输出预算、SSE error终态 | 摘录短不等于真实截断 |
| Q14/Q15 | 多轮数学问答误入库存/上下文连续性 | 看路由正反例和 history/query 区别 | 原问题不改，失败不能归咎模型 |
| USER-A1/A3 | 工具后消息越过60KB；FINAL_REAL_USER_ACCEPTANCE_REPORT | 原轨迹→v19无损压缩→字节/往返回归 | 离线载荷通过不等于新DeepSeek回答通过 |
| A04/A09/A18 | 正式证据读模型、来源纠正丢安排、时间预算 | 复用可信证据服务，保留校验草案，服务器算时间 | 不让模型重算/虚构事实 |
| QA-04 | 评测中间件scope白名单409，未到Provider | 对照当前修复与浏览器监听端点 | 不把测试运行器错误当模型错误 |

旧 v18 报告、v19 修复和后来 Core UX 离线全绿按时间分别解释；不把几轮最好结果拼成一次“40 案例全通过”。

## H. 20 天路线与先后依赖

| 日期 | 主类别 | 当天业务问题 |
|---|---|---|
| D1 | 后端 | 一次 HTTP 请求怎样到数据库并返回？ |
| D2 | RAG | 上传的资料怎样安全进入处理流程？ |
| D3 | RAG | 怎样按结构切块并能精确定位原文？ |
| D4 | RAG | 怎样建立可重建且版本一致的向量索引？ |
| D5 | RAG | 怎样让术语、语义、章节三路共同召回？ |
| D6 | RAG | 怎样过滤/重排/去冗余并证明检索有效？ |
| D7 | LLM | 怎样让业务接入可配置、可观察的模型？ |
| D8 | LLM | 怎样连续回答、流式展示并保存真实引用？ |
| D9 | LLM | 怎样评估 AI 效果、错误、token 和费用？ |
| D10 | 后端 | 怎样保存知识结构与不可变题目历史？ |
| D11 | 后端 | 怎样建卷、判题并留下可追溯作答？ |
| D12 | 后端 | 怎样从学习事实识别完成并安排复习？ |
| D13 | Agent | 奶蛙怎样读取真实证据而不编造？ |
| D14 | Agent | 模型怎样有界调用工具并结束任务？ |
| D15 | Agent | 怎样生成合法草案并在用户确认后执行？ |
| D16 | Agent | 怎样压缩工具上下文且不丢事实？ |
| D17 | Agent | 任务失败、取消、恢复与效果如何验证？ |
| D18 | 前端 | 怎样从页面追到API/SSE并定位接口问题？ |
| D19 | 工程 | 怎样用隔离测试证明用户链稳定？ |
| D20 | 工程 | 怎样给别人运行、演示并解释项目？ |

详细的上午/下午/晚上、手写/复制理解/只读/验收/面试见逐日安排。依赖上先有资料与检索，才教模型回答；先有版本/证据，才教 Agent 工具；先有草案验证，才教确认和恢复。测试按模块加入，不拖到最后才想验证。

## I–K. 代码动作、章节与每日面试

最终章节沿业务组织，不按文件顺序讲：

00总览 → 01后端骨架 → 02资料进入系统 → 03标题树分块 → 04索引 → 05混合检索 → 06范围/重排/检索评测 → 07模型接入/Prompt → 08多轮/SSE/引用 → 09AI评测 → 10知识/题目版本 → 11练习/判题 → 12学习证据闭环 → 13真实Tools → 14ToolCalling → 15Draft/Validate/Confirm → 16AgentContext → 17恢复/Agent评测 → 18前端追踪 → 19工程验证 → 20运行/演示/面试。

每章保留原约定的 24 项：目标、需求、使用场景、流程、方案、设计原因、创建文件、完整代码、逐段解析、数据流、请求响应、运行、接口测试、数据库检查、前端联调、常见错误、Debug、小练习、面试、总结、必须掌握、理解即可、暂不深入、下一章依赖。

另外固定提供“实际写了什么 / 运行什么 / 预期结果 / 失败排查 / 不要求掌握”。面试答案按“简短回答 → 深入取舍 → 本项目符号与证据”三层给出。小练习马上附答案，不把关键实现留给学生补。

长文件分步增长，每步实际编写的文件完整给出，解释块级逻辑，不贴两千行后让读者自己看。复杂适配/兼容和Vue文件作为完整配套，不用 TODO 或“其余类似”省略。本阶段还不输出这些课程正文。

## L. 能力、工作区和部署边界

确认后再建立独立学习工作区的 original/、docs/、code/：original 保存当前产品完整参考源码，code 从空目录逐步实现；不移动当前仓库。快照不复制 .env、密钥、.pgdata、用户上传/学习数据或全部审计目录。当前工作区有未提交内容，不能只复制旧 HEAD 代表现在代码。

核心公开签名、数据关系、版本约束和业务规则保持对应；不会创建“理想化简版”替代真实产品。阶段只接入已教功能，不用假成功API冒充尚未实现的功能。封版题库可作为后续内容发布资产，课堂初期用合成数据测试，不重新造题或伪造生产审核。

D20 学部署时会核对 backend/Dockerfile、docker-entrypoint.sh、frontend/Dockerfile、docker-compose.yml、Windows脚本和 desktop 入口：容器入口会 migration/seed，Chroma要持久化，本地Embedding依赖需明确安装。只在独立环境演示；Docker不可用标未验证。安装包/公网部署以现有实现与边界讲解，不在这20天扩展成新开发任务。

最终应能：独立重写RAG/Agent核心、自己写业务API/事务、追踪学习证据、理解前端请求、根据日志和ledger定位故障、演示四条完整链。关于百万chunk、云服务或高并发只讲当前瓶颈与可验证改进，不假称已有生产压测。

本版总设计完成后停止，等待用户确认，再开始第一章正文。

