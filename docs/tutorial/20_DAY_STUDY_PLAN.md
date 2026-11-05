# 20 天 AI 应用开发实习导向复现路线

> 历史版安排。当前按项目主线与API保护规则重排，执行时请使用[tutorial-roadmap.md](tutorial-roadmap.md)，不要与本表混用日期或权重。

第二版，2026-10-16。[总设计](PHASE6_0_TEACHING_DESIGN.md) · [代码地图](CODE_IMPORTANCE_MAP.md)。

下面是未来课程安排，不是本轮执行结果；课程正文和完整代码待总方案确认后逐章提供。每天 5 小时：上午 1 小时理解需求与设计，下午 3 小时手写/运行，晚上 1 小时复盘/独立重写/面试。机器下载和长测试等待可与阅读交错，不把等待充当学习。

## 时间账本

| 类别 | 日期 | 天数 | 小时 | 权重 |
|---|---|---:|---:|---:|
| 后端/数据库/核心业务 | 1、10、11、12 | 4 | 20 | 20% |
| RAG | 2、3、4、5、6 | 5 | 25 | 25% |
| LLM/Prompt/SSE/评测 | 7、8、9 | 3 | 15 | 15% |
| Agent | 13、14、15、16、17 | 5 | 25 | 25% |
| 前端理解 | 18 | 1 | 5 | 5% |
| 工程化/测试/部署 | 19、20 | 2 | 10 | 10% |
| 合计 | 1–20，不重叠 | 20 | 100 | 100% |

AI 核心为 RAG+LLM+Agent，13 天/65 小时/65%。每天按主教学目标记账，集成用到其他模块不额外累计。普通 CRUD 只服务主线；大量历史兼容代码完整配套，不占核心手写时间。

所有数据库/资料/索引写入都在独立学习环境；真实 DeepSeek 不作为每天的必做测试。每晚思考题在正式章节立即给答案，不让学生补核心代码。

## Day 1｜后端：一次请求怎样到达数据库并返回？

- **上午 1h：**从“读一份资料/一个节点”认识 HTTP、Router、Pydantic、Depends、Service；画 main → create_app → lifespan → app.state。Engine/SessionFactory/Session 和 flush/commit 只讲本项目用法。
- **下午 3h，必须手写：**main/app 的核心骨架、Settings、请求级 Session 依赖、一个真实小查询服务及响应 DTO。源码对应 backend/main.py、app.py、config.py、db.py、api/deps.py。
- **复制后理解：**完整错误契约、基础模型/迁移和检索栈/后台资源接线；先不展开所有内部实现。模型缓存未就绪时应明确 unavailable，不能伪造 ready。
- **运行验收：**课程提供的独立 *_test 数据库迁移到约定版本；健康/有效查询正常，无效参数422，事务异常回滚；确认host/port/database，不能回退5433。
- **晚上 1h：**遮答案写一个带Depends的查询；口述“共享Engine为何不能等于共享Session”。面试重点：为什么Service层、何时提交、为什么app.state只存共享基础设施。
- **产物/只读边界：**可运行后端骨架与一条请求流；不做一堆CRUD，不深入MVCC/WAL或ORM源码。

## Day 2｜RAG：用户资料怎样进入系统？

- **上午 1h：**用户上传文件后需要可读、可检索，为什么先保存/排队再处理；Material/DocumentJob和pending/indexing/ready/failed的含义。
- **下午 3h，必须手写：**上传Router→Service、流式文件保存与大小/路径校验、parse_source主调用；用Markdown/TXT打通一份合成资料。对应 api/routes/materials.py、services/material_service.py、ingestion/file_storage.py、document_parsers.py。
- **复制后理解：**完整DOCX/PDF适配、MaterialJobRunner/worker；不重新写第三方解析器或Celery。文本层PDF与扫描PDF能力区分。
- **运行验收：**文件与Material/Job关联正确；不支持格式、过大文件、解析失败都可解释；上传成功不能提前显示可检索。
- **晚上 1h：**画multipart→落盘→记录→任务→解析数据流。面试重点：为什么不在路由里完成所有PDF/Embedding工作？文件成功而DB失败如何处理？
- **产物/只读边界：**一份真实走隔离摄取管线的合成资料；不扩写OCR能力。

## Day 3｜RAG：结构化分块怎样保留上下文与引用位置？

- **上午 1h：**同一章不同小节混切的问题；规范化坐标、标题栈、直接正文与子树；标题树和教学知识树的区别。
- **下午 3h，必须手写：**normalize_text、scan_headings/build_title_tree、核心区间分配与ChunkDraft/build_chunk_drafts；对应 ingestion/text_normalize.py、title_tree.py、chunker.py。
- **复制后理解：**格式适配/子进程错误封装、kp hint所有边缘语法，提供完整参考但不逐条背。
- **运行验收：**无标题、嵌套、跳级、代码围栏、重复句子均有明确结果；content == normalized_text[start:end]，ordinal与hash稳定。结构优先后仍有默认700字符/段落窗口。
- **晚上 1h：**不看代码重写标题栈或分块不变量检查。面试重点：为什么不简单500字切块？heading_path为何有用？为何不能分块后再清洗正文？
- **产物：**一组可定位原文的chunks与结构/offset反例测试。

## Day 4｜RAG：Embedding与可重建向量索引

- **上午 1h：**表示模型与生成模型的区别；PostgreSQL权威正文和Chroma派生索引；模型名/维度/激活版本为什么要一致。
- **下午 3h，必须手写：**encode调用、批量VectorRecord写入/检索、索引版本构建→验证→激活的核心；对应 retrieval/embedding.py、vector_store.py、services/ingestion_service.py。
- **复制后理解：**完整SentenceTransformer/Chroma适配、cache/probe、worker恢复；不训练Embedding模型。
- **运行验收：**本地真实缓存Embedding产生向量；chunks与向量数量一致；重开索引可查询；维度/模型不匹配明确失败；新索引失败不损伤旧激活版本。
- **晚上 1h：**解释“数据库有块但查不到”的排查顺序。面试重点：为什么两种数据库分开？Chroma丢了能否恢复？为什么不能随意换Embedding？
- **产物：**一份资料的稳定可重建索引与计数/版本记录。

## Day 5｜RAG：三路召回与RRF

- **上午 1h：**分别看术语精确、语义相似、章节定位的失败例；BM25/Vector/Title Tree提供的互补证据。
- **下午 3h，必须手写：**KeywordIndex关键调用、标题路径/子树候选、向量候选接口、reciprocal_rank_fusion、单路去重/稳定排序。对应 retrieval/keyword.py、fusion.py、services/retrieval_service.py。
- **复制后理解：**索引缓存/协议数据类与大量中文分词细节；保留当前架构，不替换检索框架。
- **运行验收：**展示各路candidate IDs/rank及融合结果；与手算一致；同一路重复ID不额外加分，跨路命中正常累加。
- **晚上 1h：**独立写RRF并手算三份列表。面试重点：为什么不把BM25和余弦直接相加？为什么RRF高分仍可能不相关？
- **产物：**三路召回→融合的可调试返回与算法测试。

## Day 6｜RAG：过滤、重排、MMR、Context与检索评测

- **上午 1h：**召回多不等于上下文好；scope/ready/active_version、TopK与candidate_k、去冗余和引用映射。
- **下午 3h，必须手写：**过滤/回表核心、重排适配调用、条件MMR核心、有限Context/citation_map、Hit@K/主题Recall@K/MRR的小指标。对应 retrieval_service.py、rerank.py、chat/evidence.py、backend/eval/metrics.py。
- **复制后理解：**CrossEncoder模型内部、完整Chroma过滤适配；不配置rerank时保留Identity，不伪称启用了模型。
- **运行验收：**指定资料不串库；不存在资料范围不放开；索引旧ID回表被过滤；MMR场景减少冗余；手工标记主题的检索结果与指标一致。
- **晚上 1h：**画RAG召回前后过滤。面试重点：rerank与RRF区别？MMR解决什么？主题覆盖Recall与RAGAS Context Recall为何不是同一口径？
- **产物：**资料→检索Context完整链、失败分类、免费检索评测结果。

## Day 7｜LLM：模型接入、Prompt和结构化协议

- **上午 1h：**从业务需求构造System/User/Evidence Prompt；模型配置与本地覆盖；为什么Provider接口隔开业务和具体供应商。
- **下午 3h，必须手写：**Provider.complete/tool_turn/stream接口的核心HTTP接入、消息构造、usage/finish_reason提取及错误映射。真实源码Provider在 backend/chat/service.py。
- **复制后理解：**本地密钥保存适配、完整AppError/HTTPX封装。用离线传输替身验证，不读打印真实Key、不实际发DeepSeek。
- **运行验收：**合法内容/工具消息可解析；字段不完整、length截断、超时、ConnectError、Provider错误分别有状态；JSON解析成功不等于答案正确。
- **晚上 1h：**重写一次请求/响应转换。面试重点：OpenAI-compatible是什么？Prompt与业务验证各做什么？Embedding为何不是LLM？
- **产物：**有界Provider与Prompt结构测试；不硬编码历史计价当现价。

## Day 8｜LLM：多轮、SSE与可信引用

- **上午 1h：**用户首问/追问/刷新/取消的体验；ChatSession/Message、历史预算和资料会话；通用知识与资料依据。
- **下午 3h，必须手写：**encode_sse、流式事件/错误终态、历史裁剪、受限追问上下文与引用校验核心。对应 chat/service.py、query_context.py、file_scope.py、answer_contract.py、material_search_service.py。
- **复制后理解：**长service中的旧分支/持久化配套；完整Vue页面。先通过测试客户端观察流，前端专门放D18。
- **运行验收：**meta/delta/done/error可解释；断流不永远generating；多轮问题不误入库存；未知chunk引用拒绝；限定资料不足不引入范围外内容。
- **晚上 1h：**复述Q07截断、Q14/Q15多轮问题为何不能只改Prompt。面试重点：SSE为什么不是简单JSON？HTTP200为何不等于成功？历史为什么按预算裁剪？
- **产物：**会话→上下文→模型替身→SSE→持久化完整链。

## Day 9｜LLM：AI评测、冻结案例与Provider Ledger

- **上午 1h：**程序可运行与答案可相信的差别；rubric/expected behavior/失败分母；RAGAS四指标、同模型裁判偏差与适用范围。
- **下午 3h，必须手写：**案例加载/评分聚合、调用记录、输入/输出预留与BudgetStop判定核心、历史回答/证据对照报告。对应 backend/eval、scripts/phase5_eval_meter.py、chat/call_trace.py、冻结评测资产的读取。
- **复制后理解：**完整真实测评运行器、历史RAGAS集成；不默认执行它们。Golden Slice按历史用途解释，不把旧审核要求引入当前产品。
- **运行验收：**一次业务可对应多笔HTTP；超时/截断/预算停止/未执行不能计PASS；未知usage不是0；分科/分轨/可评分与全样本分母正确；原始记录不覆盖。
- **晚上 1h：**读一条真实ledger和原回答，不依赖报告摘要判原因。面试重点：如何评价引用？怎样防止刷分？为什么离线通过不能证明DeepSeek回答成功？
- **产物：**免费重放的评测报告、成本与错误解释；不调用收费裁判或新模型。

## Day 10｜后端：知识结构、业务模型与不可变题目版本

- **上午 1h：**KnowledgePoint、Question、QuestionVersion、PracticeItem的关系；源题身份/当前投影/历史内容；其余核心模型完整图。
- **下午 3h，必须手写：**核心ORM字段/外键/查询、question_version_snapshot/hash、绑定版本读取。对应 models/learning.py、question_versions.py、study.py知识树/节点读取。
- **复制后理解：**完整模型/约束、flush事件/DB append-only约束、f53/f54历史迁移、讲解加载与旧策略兼容。
- **运行验收：**旧PracticeItem读旧题面答案，新练习用新版本；跨题版本拒绝；审核/答案hash绑定正确；叶子/父汇总和真实库存不混淆。
- **晚上 1h：**画Question→Version→PracticeItem→Attempt。面试重点：为什么不直接改旧题？哪些表是事实、状态、工作状态？模型中Attempt实际叫QuestionAttempt。
- **产物：**历史版本保护正反例和知识节点查询，不手抄全部模型注解/历史脚本。

## Day 11｜后端：今日学习、判题与作答记录

- **上午 1h：**推荐→用户选择→建卷→答题→反馈；单选/数值/分数/LaTeX比较能力和unknown。
- **下午 3h，必须手写：**推荐/组卷服务核心、保守比较器、answer-submissions事务、幂等键与Attempt/Event写入主链。对应 planning_service.py、practice_service.py、answer_grading.py、answer_submission_service.py。
- **复制后理解：**已冻结题集选题和资格检查的完整配套；复杂格式/旧原卷参考模式；不做万能CAS。
- **运行验收：**GET不自动建卷；同日恢复同卷；1/2与0.5在支持范围等价；unknown不当wrong；响应丢失/重发不重复记录；答案从绑定Version读取。
- **晚上 1h：**画一次成功和一次回滚。面试重点：为什么Attempt不是KpState？为什么有题不代表可判题/可形成毕业证据？
- **产物：**真实隔离业务库上的作答闭环，历史内容不覆盖。

## Day 12｜后端：可信证据、冻结题集、毕业与自适应复习

- **上午 1h：**独立正确/辅助正确/错后立即改正/后续复测的区别；有限题集的真正完成和近期表现。
- **下午 3h，必须手写：**证据分类、v3集合完成判断、关键状态转换/投影、推荐理由的连接。对应 mastery/evidence.py、rules.py、transition.py、storage.py及attempt_service.py。
- **复制后理解：**policy_for_node历史绑定、完整确认收据校验、题集发布/旧毕业兼容、post_graduation_service。原算法不改。
- **运行验收：**第一次可信独立正确可完成单题；解析后立即正确不冒充独立；规定题全完成才毕业；空集/个人题不毕业；新题集不扩大旧实例要求；毕业后复习不随意撤销事实。
- **晚上 1h：**为Agent准备可核对的学习事实。面试重点：学习驱动和毕业判断为什么分开？错过一次为何不能永久卡住？为何KpState不替代事件？
- **产物：**三种证据、版本绑定与毕业反例，用于下一天真实工具查询。

## Day 13｜Agent：白名单Tools与真实学习事实

- **上午 1h：**Agent和Chat的差别；LLM提出调用，服务器解析Schema/执行工具；模型不是数据库或权限系统。
- **下午 3h，必须手写：**tool_definitions、工具分发/参数校验、search_knowledge/get_learning_state/find_questions/get_question_availability的关键查询。对应 learning_task_tools.py、question_availability.py、planner_facts.py。
- **复制后理解：**完整资格、历史Version/审核hash读取服务；不另建学习状态系统，不导出无关标准答案。
- **运行验收：**总库存与有限预览分别正确；来源由bank_scope/qualification判断；独立/辅助/自评区分；工具未知ID失败且不写学习状态。
- **晚上 1h：**遮住代码写一个工具Schema与事实返回。面试重点：为什么不能让模型报“你有20道题”？同一道题3次作答为何不是3道题？
- **产物：**结构化真实工具结果与读取边界测试。

## Day 14｜Agent：有界Tool Calling循环

- **上午 1h：**assistant.tool_calls→带tool_call_id的结果→下一轮模型；轮次/工具数/总时间的生命周期。
- **下午 3h，必须手写：**有界循环、工具白名单、参数错误反馈、消息追加、最后轮结束/失败分类。对应 learning_task_service.py与Provider.tool_turn。
- **复制后理解：**任务存储/线程执行/trace完整配套；不换成通用Agent框架。
- **运行验收：**离线协议替身走多轮真实工具；无意义重复受限；异常工具名/参数、网络/超时/Provider/预算有明确终态；不无限重试或把未完成标成功。
- **晚上 1h：**手画三轮消息，标出每笔物理HTTP可能出现的位置。面试重点：为什么业务回合不等于请求数？为什么LLM不能直写SQL？
- **产物：**可结束、可诊断的Agent循环和逐轮轨迹。

## Day 15｜Agent：Draft → Validate → Confirm → Plan

- **上午 1h：**用户20分钟/数学二/填空偏好是硬约束；草案为何要先验、确认时再验；两次确认的实际页面语义。
- **下午 3h，必须手写：**validate_plan核心、草案成员/时长/资格快照、confirm_task的版本/计划签名复验与幂等执行。对应 learning_task_tools.py、learning_task_service.py。
- **复制后理解：**锁顺序/冲突保护、PracticeRequest关联与已有计划追加完整配套。
- **运行验收：**20分钟不能给90分钟；不存在ID/来源未知不伪造；未确认无DailyPlan改变；过期草案被拒；重复确认不重复加题；新建PracticeItem绑定正确版本。
- **晚上 1h：**独立写“求和时长与允许题目ID”校验小段。面试重点：为什么模型已经解释合理，服务端仍需复验？草案生成后题库变化怎么办？
- **产物：**一个可确认草案与违规/过期/重复确认负例。

## Day 16｜Agent：Context为何爆，怎样无损压缩？

- **上午 1h：**USER-A1/A3真实轨迹：工具事实重复累积，下一轮发送前超过60KB；字节/Token/上下文窗口/费用预算的差别。
- **下午 3h，必须手写：**pack_records/expand_records、公共字段提取、相同完整结果引用、model messages副本转换与输入守卫。对应 learning_task_context.py、learning_task_service.py。
- **复制后理解：**原始trace和确认快照不压缩改写；完整v19 Prompt协议说明。
- **运行验收：**事实round-trip一致；ID/Version/来源/审核hash/独立辅助/库存/范围/时间全保留；事实改变不能复用旧快照；真实历史载荷离线重建通过原预算边界。
- **晚上 1h：**不看答案重写一个同构记录压缩/展开。面试重点：为什么不直接把Token上限加大？同工具同参数为什么还不能证明结果相同？
- **产物：**可复现的载荷字节对比与事实一致性报告，不宣称新的模型回答成功。

## Day 17｜Agent：恢复、取消、来源纠正与效果评测

- **上午 1h：**一次任务不只正常完成：取消、迟到结果、状态轮询、来源断言冲突、库存不足/无法完成。
- **下午 3h，必须手写：**get_task/cancel/run_token关键恢复、基于真实工具的最终事实检查/可执行摘要、Agent行为评测/离线轨迹回放核心。对应 task_service、planner_facts、assistant_service、phase5_agent_final_offline。
- **复制后理解：**完整历史案例运行器；正式模型测试仅设计执行边界，不收费运行。
- **运行验收：**取消后旧结果不能覆盖；响应丢失只读恢复不重复模型调用；来源纠正后保留合法计划；无库存说不足；辅助证据不升级；评测区分PASS/PARTIAL/FAIL/无法评分。
- **晚上 1h：**对一条历史失败按路由/工具/模型/预算/夹具分层诊断。面试重点：怎样证明Agent不是聊天机器人？离线回放证明什么、不能证明什么？
- **产物：**Agent离线效果报告、失败归因与真实复测方案；不自动追加请求或改冻结rubric。

## Day 18｜前端：看懂页面→API→后端→SSE

- **上午 1h：**Vue单文件组件、props/ref/computed基本阅读、路由、TypeScript DTO；只讲定位接口所需基础。
- **下午 3h，必须动手：**跟写一个API client方法/有限SSE读取核心或独立调试页；对照StudyPage、ChatPage、MaterialSearch、LearningTaskPanel记录请求/响应/状态变化。
- **复制后理解：**整套页面/组件/CSS/生成types；不从零重写Vue产品，不逐行抄9,692行生成类型。
- **运行验收：**Network能识别assistant:stream/answers:stream和confirm；刷新恢复；loading/error/cancel可解释；重复请求/前后端错误能判断；typecheck/unit/build含义清楚。
- **晚上 1h：**画一条“点击确认”从按钮到PracticeItem的链。面试重点：为什么HTTP200但页面还在生成？怎样判断是后端错误、SSE解析还是渲染问题？
- **产物：**接口联调笔记与少量前端手写代码，不做视觉改造。

## Day 19｜工程：测试隔离、日志和完整用户链验证

- **上午 1h：**pytest/Vitest/Playwright分工；合成fixture与生产审核资产区别；显式测试库/目录/端口及进程生命周期。
- **下午 3h，必须动手：**补齐核心正反例、运行相关/完整后端与浏览器套件，记录有效JSON汇总；定位一项受控失败。对应 tests/conftest.py、prepare_e2e_learning.py、prepare_e2e_data.py、run-e2e.ps1。
- **复制后理解：**批量fixture样板、完整浏览器页面场景和通用启动脚本；不手抄全部历史测试。
- **运行验收：**资料→检索→聊天→练习→学习记录→Agent草案/确认可复现；版本/证据/个人题边界不破坏；所有写入隔离；不以历史测试替代自己的结果。
- **晚上 1h：**把一次错误从浏览器日志追到API/工具/DB，写最小诊断。面试重点：为什么单测绿不代表产品可用？夹具错误与产品错误怎么分？
- **产物：**自己的测试摘要/错误清单/核心演示。全量耗时正常可并行读报告，不为省时提前中止再声称通过。

## Day 20｜工程：Windows运行、部署说明、演示与答辩

- **上午 1h：**梳理Python/Node/PG/模型缓存/上传/Chroma路径，源码到软件的启动依赖；看现有Dockerfile、Compose、desktop入口。
- **下午 3h，必须动手：**1小时验证独立Windows启动和构建/配置；1小时完成整条用户演示和可恢复错误；1小时遮答案抽查重写RRF/Agent工具校验/版本读取之一。各AI模块已在前几天做过独立重写，这里抽验。
- **复制后理解：**Docker多阶段构建、卷/代理、entrypoint迁移/seed、安装包入口；不开发新安装器或云部署。PG16/18物理目录不混用，Docker不可用如实记录未验证。
- **运行验收：**别人能按手册在独立环境配置并运行；不用真实用户数据或旧授权；明确哪些依赖/容器/模型质量尚未实测。
- **晚上 1h：**四条主链各3–5分钟答辩，梳理能证明的独立实现范围。面试重点：技术取舍、真实失败复盘、局限与可验证改进。
- **产物：**部署/启动手册、演示脚本、复现成果、答辩清单。不是以“看完了所有文件”宣布完成。

## 最终独立能力检查

必须同时具备：

1. **RAG：**遮答案写出标题/分块或检索核心、RRF、Context与范围检查，能解释Rerank/MMR边界。
2. **Agent：**写出一个真实工具、有界调用循环、20分钟约束与用户确认校验，解释Context往返。
3. **后端：**写一个带ORM查询/事务/DTO的API，解释QuestionVersion及Attempt/Event/KpState。
4. **LLM：**说明Prompt/消息、SSE、截断/失败、usage与物理请求计数，读懂一条真实ledger。
5. **工程/前端：**完整用户链能跑，能在Network/日志/DB定位一项问题，并准确说明未验证内容。

能力未达的地方列出具体缺项，不用重复扩题、改架构或刷收费测评分数填补。

