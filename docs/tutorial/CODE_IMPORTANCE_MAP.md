# 代码重要性地图：20 天应该写什么、读什么

> 源码定位仍可参考；日期及分类执行以[tutorial-roadmap.md](tutorial-roadmap.md)的A/B/C划分为准，API以[契约基线](api-contract-baseline.md)为准。

依据：2026-10-16 第二版，当前工作区实际文件。配套：[教学设计](PHASE6_0_TEACHING_DESIGN.md) · [逐日安排](20_DAY_STUDY_PLAN.md) · [60 个关键文件 hash](SOURCE_BASELINE.json)。

本地图的星级表示在 20 天内的学习优先级，不表示代码的产品质量。一个大文件可以同时含 A 类核心和 C 类兼容部分；不能把整文件统一判成“必须背诵”。

## 1. A–E 分类与学习动作

| 分类 | 含义 | 需要做什么 | 不要求做什么 |
|---|---|---|---|
| A：核心 | 决定请求、检索、证据、版本和计划是否正确 | 跟写完整核心，第二遍遮答案重写，能解释边界 | 不手抄整份历史兼容文件 |
| B：业务 | 把核心能力组成真实用户行为 | 跟着完整代码实现，能定位调用和事务 | 不把所有 CRUD 平均展开 |
| C：框架与兼容 | 生命周期、适配、恢复、历史兼容等配套 | 配套代码完整提供，读清职责与失败行为 | 逐行背诵框架/历史兼容 |
| D：前端展示 | 页面、组件、API client、状态显示 | 会看请求/响应、定位错误、读 SSE 与确认操作 | 重写全套 Vue/CSS |
| E：测试/配置/脚本 | 验证边界、运行环境和研发工具 | 重点写核心行为测试、理解隔离/预算/日志 | 手抄全部历史批次脚本 |

- ★★★★★：必须掌握，能自己写核心并讲出数据流。
- ★★★★：重点理解并跟做，能调试和解释。
- ★★★：理解作用、输入输出与连接点。
- ★★：快速浏览，知道何时查阅。
- ★：本 20 天不花主线时间，完整参考仍保留。

时间归属严格对应：后端 D1/D10–12（20%），RAG D2–6（25%），LLM/评测 D7–9（15%），Agent D13–17（25%），前端 D18（5%），工程化 D19–20（10%）。某文件跨日被引用不表示额外增加教学时数。

## 2. 整个工作区的边界

| 目录 | 分类/星级 | 本轮学习位置 |
|---|---|---|
| backend 根目录 | A/C，★★★★★ | main/app/config/db/errors 的核心路径 |
| backend/api | A/B，★★★★ | 路由、DTO 与服务边界，重点四条用户链 |
| backend/models | A/B，★★★★★ | 题目版本、作答、事件、题集、资料与会话 |
| backend/schemas | B/C，★★★★ | 输入校验与响应契约，工具参数 schema |
| backend/ingestion | A/B，★★★★★ | 标题树、分块、offset；格式适配读懂即可 |
| backend/retrieval | A，★★★★★ | 三路、RRF、范围、向量适配、重排 |
| backend/chat | A/B，★★★★★ | Provider、Context、Citation、SSE；不逐行背两千行 service |
| backend/mastery | A/B，★★★★★ | v3 与证据主线；历史 v1/v2 读懂兼容原因 |
| backend/jobs | B/C，★★★ | 本地后台任务、状态、失败恢复 |
| backend/services | A/B/C，分项如下 | 不把 71 个文件全部当作同等重点 |
| backend/eval | A/E，★★★★★ | 必须手写检索指标核心，理解指标分母与失败分类 |
| frontend/src/api | D，★★★★ | API client、请求/响应、SSE、幂等键 |
| frontend/src/pages/components | D，★★★ | 今日学习/资料/聊天/知识树/确认 UI |
| frontend/src/api/types.ts | D/C，★ | 自动生成，知道 OpenAPI 来源，不手写 9,692 行 |
| frontend/src/lib/composables | D/B，★★★ | 状态、防迟到响应、输入规范化等关键边界 |
| frontend/src/assets/styles | D，★ | 能找问题即可；本课程不视觉重设计 |
| tests | E，分项如下 | 按功能选正例/反例/事务测试 |
| frontend/e2e | E/D，★★★★ | 核心用户行为，少量 mock 边界与真实隔离 API 区分 |
| migrations | E/C，★★★★ | schema 演进；f53/f54 与版本绑定重点 |
| scripts | E，分项如下 | 启动/测试脚本与内容建设历史脚本分开 |
| desktop | C/E，★–★★ | 了解打包入口，非本轮复现主线 |
| seed/resources | 配套数据，★★ | 理解 schema 与来源；不重新生产题库 |
| docs | 参考，★★★ | 以源码核对最新报告；旧报告保留历史语境 |
| eval 中冻结案例 | A/E，★★★★★ | AI 验收主线：冻结案例、rubric、结果/ledger关联；不修改原资产，不默认收费 |
| storage/.pgdata/上传/向量/运行报告 | 运行资产 | 不作为代码参考快照复制，不接入真实用户数据 |

“覆盖整个工程”通过目录职责和低优先级文件规则完成，不等于要求把 820 个范围内代码文件逐一讲一遍。

## 3. 启动、配置、数据库与 HTTP

| 文件/符号 | 级别 | 动手范围与验收 | 日期 |
|---|---|---|---|
| [main.py](../../backend/main.py) | A★★★★★ | 导入 create_app，说明导入/启动区别 | D1 |
| [app.py](../../backend/app.py)：create_app/lifespan | A★★★★★ | Router 注册、共享基础设施、启动/退出资源顺序 | D1 |
| app.py：独占锁心跳/任务恢复 | C★★★ | 理解为什么单用户也需防重复进程；不手抄所有恢复分支 | D19 |
| [config.py](../../backend/config.py)：Settings/active_database_url | A★★★★★ | 配置优先级、SecretStr、缓存、测试库保护 | D1 |
| [db.py](../../backend/db.py) | A★★★★★ | Engine、SessionFactory、yield依赖/关闭/回滚 | D1 |
| [api/deps.py](../../backend/api/deps.py) | A★★★★ | get_db/get_time_provider/get_session_factory | D1 |
| [errors.py](../../backend/errors.py) | B★★★★ | 稳定错误码/HTTP/前端提示，别泄露底层连接信息 | 每日 |
| [api/routes/health.py](../../backend/api/routes/health.py) | B★★★★ | 服务/数据库/检索/worker 分别反映真实可用性 | D1、D19 |
| [models/base.py](../../backend/models/base.py)、types.py | A/C★★★★ | Base、metadata、主键/时间类型；理解服务端默认值 | D1 |
| [migrations/env.py](../../migrations/env.py) | E/C★★★★ | 使用同一 Settings 选择目标；模型登记 | D1 |

当前没有统一的 Repository 包。不要在教程中凭架构习惯新增一层。study/chat 路由也存在查询和响应组装逻辑；教学重点是复杂规则与事务的可测试边界，不声称“路由里绝对不能出现 SQL”。

## 4. 资料处理与 RAG

| 文件/符号 | 级别 | 必须掌握的范围 | 日期 |
|---|---|---|---|
| [api/routes/materials.py](../../backend/api/routes/materials.py) | B★★★★ | 上传→服务→任务；检索/阅读/删除/重建路由 | D2、D6 |
| [models/rag.py](../../backend/models/rag.py) | A★★★★★ | Material、DocumentChunk、ChunkKnowledgePoint 与约束 | D2–4 |
| [material_service.py](../../backend/services/material_service.py) | B★★★★ | 保存记录/任务、删除依赖、重建入口 | D2、D4 |
| [file_storage.py](../../backend/ingestion/file_storage.py) | A/B★★★★ | 流式大小限制、路径约束、哈希与文件清理 | D2 |
| [document_parsers.py](../../backend/ingestion/document_parsers.py) | B★★★ | parse_source、文本层 PDF、DOCX/TXT；扫描件不假装解析成功 | D3 |
| [text_normalize.py](../../backend/ingestion/text_normalize.py) | A★★★★★ | 唯一正文坐标系、稳定 hash | D3 |
| [title_tree.py](../../backend/ingestion/title_tree.py) | A★★★★★ | scan_headings、build_title_tree、direct_ranges、路径/元数据继承 | D3 |
| [chunker.py](../../backend/ingestion/chunker.py) | A★★★★★ | split_block、build_chunk_drafts、切片不变量 | D3 |
| line_spans.py/source_io.py/parse_worker.py | C★★★ | 文本坐标、格式/进程适配与异常 | D3 |
| [ingestion_service.py](../../backend/services/ingestion_service.py) | A/B★★★★★ | plan/parse/build/activate、同版本重建与关键词重建 | D2–4 |
| [jobs/worker.py](../../backend/jobs/worker.py)、runner.py | B/C★★★ | claim/运行/失败/恢复，线程退出 | D2、D4、D19 |
| [embedding.py](../../backend/retrieval/embedding.py) | A/B★★★★ | encode 接口、维度、模型缓存；不学模型训练 | D4 |
| [vector_store.py](../../backend/retrieval/vector_store.py) | A/B★★★★ | Chroma 持久化适配、metadata/filter、归一化 | D4、D6 |
| [keyword.py](../../backend/retrieval/keyword.py) | A★★★★★ | 正文 BM25、标题树召回与范围 | D5 |
| [fusion.py](../../backend/retrieval/fusion.py) | A★★★★★ | RRF、单路去重、稳定排名，必须独立写 | D5 |
| [retrieval_service.py](../../backend/services/retrieval_service.py) | A★★★★★ | filter→三路→融合→回表→重排→可选 MMR | D5–6 |
| [rerank.py](../../backend/retrieval/rerank.py) | A/B★★★★ | Identity/CrossEncoder、失败降级、保留原始排序证据 | D6 |
| [stack.py](../../backend/retrieval/stack.py) | C★★★★ | 一进程共享栈、模型/维度一致性、索引恢复 | D4 |
| [protocols.py](../../backend/retrieval/protocols.py) | A/B★★★★ | Hit、Filter、Request 与能力接口 | D4–6 |
| [material_search_service.py](../../backend/services/material_search_service.py) | B★★★★ | 日内资料会话、选定资料范围、连续提问 | D6、D8 |

Rerank/MMR 是“有配置/有请求条件才启用”的能力，不能把每次请求画成一定经过真实 CrossEncoder。索引中的正文不替代 PostgreSQL 规范化正文的权威地位。

## 5. 会话、Provider 与 SSE

| 文件/符号 | 级别 | 必须掌握的范围 | 日期 |
|---|---|---|---|
| [models/chat.py](../../backend/models/chat.py) | A/B★★★★★ | Session、Message、Citation、状态/顺序 | D8 |
| [api/routes/chat.py](../../backend/api/routes/chat.py) | A/B★★★★ | assistant:stream 与 answers:stream、资料会话、历史读取 | D7–8 |
| [chat/service.py](../../backend/chat/service.py)：Provider/provider_from_settings | A★★★★★ | 真实 HTTP 协议、timeout/max_tokens/finish_reason、配置来源 | D7 |
| chat/service.py：select_history_within_budget/prepare/stream/finalize | A★★★★★ | 历史裁剪、上下文、引用映射、流式终态与存储 | D8 |
| chat/service.py：旧路由与大量范围特例 | B/C★★★ | 按调用链读，不要求把两千多行逐行背诵 | D8 |
| [chat/evidence.py](../../backend/chat/evidence.py) | A/B★★★★ | 实际资料证据、上下文与引用关联 | D6、D8 |
| query_context.py/file_scope.py/answer_contract.py | A/B★★★★ | 多轮范围、资料限定与回答契约 | D8 |
| [call_trace.py](../../backend/chat/call_trace.py) | E/B★★★★ | 真实调用观察、usage、错误、截断和重试数 | D7–9、D19 |
| context_screening.py | B/C★★ | 实验 off/shadow/filter 与证据筛选边界，知道默认状态 | D8 |
| model_settings_service.py | B/C★★★ | 本地设置覆盖、DPAPI/SecretStr边界，UI不回显密钥 | D1、D19 |

这里没有单独的 backend/chat/provider.py 或 sse.py；课程以真实符号为索引。预算必须区分输入估算、输出 max_tokens、物理请求重试与评测软件金额停止条件。

## 6. 知识树、题目、证据与毕业

| 文件/符号 | 级别 | 必须掌握的范围 | 日期 |
|---|---|---|---|
| [models/learning.py](../../backend/models/learning.py)：KnowledgePoint/KpState | A★★★★★ | 父子、is_assessable、投影、题集绑定 | D10、D12 |
| 同文件：Question/QuestionVersion | A★★★★★ | 当前投影、不可变版本、版本号/hash与外键 | D10 |
| 同文件：DailyPlan/PracticeItem/QuestionAttempt/LearningEvent | A★★★★★ | 从计划到每次真实作答和领域行为 | D11–12 |
| 同文件：KpMasteryPolicy/KpGraduationQuestionSetVersion | A/B★★★★★ | 规定题集 JSON 成员/版本/hash、适用绑定 | D12 |
| 同文件：审核/来源/历史一致性模型 | B★★★ | 理解当前资格如何证明，不重做内容审核 | D10 |
| [api/routes/study.py](../../backend/api/routes/study.py) | A/B★★★★ | today/tree/node/answer-submissions/answer-reveal 调用链 | D10–12 |
| lesson_service.py/builtin_material_service.py | B★★★ | 节点讲解与内置资料来源；不逐份阅读教学正文 | D10 |
| [question_versions.py](../../backend/services/question_versions.py) | A★★★★★ | snapshot/hash、before_flush、question_for_practice_item/attempt | D10 |
| [question_eligibility.py](../../backend/services/question_eligibility.py) | A/B★★★★★ | 归属、当前审核/核验、可判题与个人题排除 | D10、D13 |
| [question_availability.py](../../backend/services/question_availability.py) | A/B★★★★★ | 总量/分科/预览/可追加、真实来源分类 | D10、D13 |
| grading_basis.py | A/B★★★★ | 能反馈正确与能形成正式证据的差别 | D11–12 |
| [answer_grading.py](../../backend/services/answer_grading.py) | A★★★★★ | 单选与受限数值/分数/格式、right/wrong/unknown | D11 |
| [answer_submission_service.py](../../backend/services/answer_submission_service.py) | A★★★★★ | 锁/幂等、按绑定版本判题、辅助状态、Attempt/Event | D11–12 |
| [attempt_service.py](../../backend/services/attempt_service.py) | A/B★★★★ | 领域事件到状态持久化、收据/版本过滤 | D12 |
| [practice_service.py](../../backend/services/practice_service.py) | A/B★★★★ | 初始卷、已有题追加、版本/资格/题集要求 | D11 |
| [planning_service.py](../../backend/services/planning_service.py) | A/B★★★★ | 层级推荐、真实缺口、不是额外毕业门槛 | D11 |
| [mastery/evidence.py](../../backend/mastery/evidence.py)、attempt_sequence.py | A★★★★★ | 独立/辅助/错误与同题重做的分类 | D12 |
| [mastery/rules.py](../../backend/mastery/rules.py) | A★★★★★ | v3 graduation_check/analyze_gaps；旧配额分支理解即可 | D12 |
| [mastery/transition.py](../../backend/mastery/transition.py) | A★★★★★ | 可信事件驱动的纯状态转换、保留完成/毕业事实 | D12 |
| [mastery/storage.py](../../backend/mastery/storage.py) | A/B★★★★★ | 纯类型↔ORM、policy_for_node 历史题集绑定 | D12 |
| mastery/policy.py/types.py/enums.py | A/B★★★★ | 显式类型、边界与历史版本；不用背所有枚举 | D12 |
| mastery/selection.py/learning_progress.py/capability.py | B★★★★ | 推荐/表现投影，不当作新的毕业算法 | D10、D11 |
| [graduation_question_set.py](../../backend/services/graduation_question_set.py) | A/B★★★★★ | freeze/publish、成员/版本hash、发布与旧绑定分离 | D12 |
| policy_evidence_service.py/evidence_pool.py | B★★★★ | 当前策略下的可信收据/供给，复用统一事实 | D12–13 |
| [post_graduation_service.py](../../backend/services/post_graduation_service.py) | B★★★★ | mastered_at 之后的新练习、近期状态、历史毕业不回填 | D12 |
| node_assessment_service.py/capability_service.py | B★★★ | 自评/能力视图边界，不能冒充正式掌握 | D10、D12 |

题集成员实际存储在版本表的 ID 数组及 hash 中，不是凭教程图凭空新增一张 members 表。QuestionVersion.content_hash 与 answer_submission_service.question_content_hash 的语义要分别读。

## 7. Agent 的重点与阅读止点

| 文件/符号 | 级别 | 学习结果 | 日期 |
|---|---|---|---|
| [assistant_router.py](../../backend/services/assistant_router.py) | A/B★★★★★ | 明确学习意图/库存/QA 的正反例，路由不直接授权写入 | D13 |
| [learning_assistant_service.py](../../backend/services/learning_assistant_service.py) | A/B★★★★ | StudyContext、QA/库存/任务分支、确定性毕业说明、SSE | D13–17 |
| schemas/learning_assistant.py/learning_task.py | A/B★★★★ | 结构化请求/上下文/工具参数/确认版本 | D13、D15 |
| [learning_task_tools.py](../../backend/services/learning_task_tools.py) | A★★★★★ | tool_definitions、TaskTools、真实事实与 validate_plan | D13–15 |
| [planner_facts.py](../../backend/services/planner_facts.py) | A/B★★★★★ | 当前卷/库存/观察/正式证据事实汇总，避免模型重新计数 | D13、D15、D17 |
| [learning_task_service.py](../../backend/services/learning_task_service.py) | A★★★★★ | 有界循环、工具执行/轨迹、Draft、预算/终态 | D14 |
| 同文件 confirm_task/get_task/cancel_task | A★★★★★ | 版本签名再校验、幂等确认、恢复/取消、迟到结果 | D15、D17 |
| [learning_task_context.py](../../backend/services/learning_task_context.py) | A★★★★★ | 同构记录列式压缩、无损往返、完全相同结果的引用 | D16 |
| models/learning_task.py | A/B★★★★ | Task 与学习完成记录不同，状态/trace/draft/metrics | D13 |
| practice_request_service.py/deep_qa_handoff_service.py/study_context_service.py | B★★★★ | 从聊天需求到今日学习的两次明确确认、当前位置校验 | D15、D17 |
| learning_qa_service.py | B★★★★ | 提示/解析辅助事实与证据连接 | D12、D13 |
| personal_generation_intent.py/personal_question_service.py | B★★★ | 主动生题意图、个人归属、审核/额度/失败边界；本课不收费生题 | D13 |
| personal_question_families.py/question_generation.py | B★★ | 能力边界/生产链参考，完整提供；不新建或扩展题族 | D13 |

必须保留：Question ID/Version、来源、资格/审核 hash、库存总量/预览区别、独立/辅助证据、时间/范围、确认边界。压缩不是把这些内容交给 LLM 自由摘要。

## 8. 后端其余业务的学习范围

上表之外的 services 文件按下列规则覆盖，完整原代码仍保留：

- **内容资格及来源参考，B★★–★★★：**auto_question_review、answer_verification、answer_consistency、question_attestation、question_identity、question_pack、public_practice_release、question_answer_revision、grading_basis。重点跟一次“内容/来源/hash→资格”的读取，理解后停止，不重建题库生产流水线。
- **历史题库建设/独立验证，B/E★–★★：**phase45hs_verifiers、phase45hx_*、phase45i_quality_verifiers、quality_verifiers、quality_sources、public_bank_batch、public_bank_supply、question_production_pipeline、question_repair、question_verification_upgrade、golden_*、answer_consistency 的历史批次工具。知道为何存在，不逐个手写专用 solver。
- **引用与历史资料，B★★：**exam_reference_service。能说明原卷引用不等于在线可判题题目即可。
- **设置、辅助能力与适配，C/B★★：**vision_recognition_service、vision_settings_service、web_search_service、program_sandbox_policy、practice_lock、graduation_policy_migration、qa_information_router、constant_expression。与当日链路相关时再看，不能为了课程换框架或引入新能力。
- **功能不在每天主线中时：**引用原项目完整文件配套，章节明确“了解即可”的原因；不会通过删除这些模块来制造更简单的产品。

## 9. 前端只花在这些接口交互上

| 页面/组件与 API 文件 | 需要看懂什么 | 优先级 |
|---|---|---|
| router.ts / main.ts / App.vue | 页面入口、路由、公共状态、代理地址 | D★★★ |
| api/client.ts | JSON/错误码/网络异常，不把 HTTP 200 当业务成功 | D★★★★ |
| ChatPage.vue / api/chat.ts | assistant/answers SSE、缓冲、会话恢复/切换 | D★★★★ |
| MaterialsPage.vue / MaterialSearch.vue / api/materialSearch.ts | 上传、范围、检索会话、引用定位 | D★★★★ |
| KnowledgePage.vue / KnowledgeLessonReader.vue | 节点选择、详情、讲解、路径 | D★★★ |
| StudyPage.vue / StudyFocus.vue / api/study.ts | 推荐→确认→卷子→作答→解析/恢复 | D★★★★ |
| LearningTaskPanel.vue / PlannerDraftCard.vue / api/learningTasks.ts | 草案、确认版本、轮询、取消/恢复 | D★★★★ |
| ProcessReview.vue / PhotoTranscription.vue | 辅助行为/用户确认与临时状态，不做视觉算法复现 | D★★ |
| lib/answerInput.ts / answerFeedback.ts / attemptSequence.ts | 支持格式与业务状态不能相互误解释 | D★★★ |
| composables/useAsyncTask.ts | loading/error/retry、迟到请求保护 | D★★★ |
| SettingsPage.vue / api/settings.ts | 本地配置、密钥不回显 | D★★ |
| CSS/宠物图片/图标/Vite 内部 | 会启动和定位文件即可 | D★ |

每章只跟一段 Network 请求与页面处理：请求参数、返回字段、状态变化、失败提示、是否意外多发请求。不在此课程重写 UI。

## 10. 重点测试与配套工程

| 行为 | 当前参考入口 | 学习重点 |
|---|---|---|
| 标题/分块不变量 | tests/unit/ingestion/test_markdown_chunks.py | 结构、路径、切片/hash |
| RRF/混合检索 | tests/retrieval/test_hybrid_search.py、test_retrieval_core.py | 各路结果、范围/降级 |
| Provider/SSE | tests/integration/test_chat_stream.py、test_chat_sessions.py | 终态、历史、取消/异常 |
| 多轮与范围 | tests/unit/test_chat_query_context.py、test_chat_multifile_scope.py | 问题/历史/资料过滤 |
| 不可变版本 | tests/integration/test_question_immutable_versions.py | 旧内容可还原，新版本不污染旧作答 |
| 判题 | tests/unit/grading/test_answer_grading.py、test_bounded_final_inputs.py | right/wrong/unknown 边界 |
| 证据 | tests/unit/mastery/test_objective_evidence.py、test_attempt_sequence.py | 独立/辅助/重做 |
| v3 毕业 | tests/unit/mastery/test_frozen_graduation_set.py | 集合完成、空集、个人题隔离 |
| Agent 工具/确认 | tests/integration/test_learning_tasks.py | 库存、预算、无确认不写、过期草案 |
| Context | tests/unit/test_agent_tool_context.py | round-trip、不丢事实、变化不复用 |
| 数据库隔离 | tests/conftest.py、tests/unit/test_test_database_isolation_guard.py | 显式端口/库名、禁止回退 |
| 浏览器用户行为 | frontend/e2e/chat-first-message.spec.ts、answer-submissions.spec.ts、learning-task.spec.ts、materials.spec.ts | 输入→请求→服务→显示→刷新 |
| 准备合成环境 | scripts/prepare_e2e_learning.py、prepare_e2e_data.py、run-e2e.ps1 | 自有测试库、合成资格、独立资源目录 |
| Windows/依赖 | constraints/runtime-win-py312-observed-v1.txt、scripts/start-dev.ps1 | 读懂依赖/端口与启动副作用，不对5433试跑 |
| 打包/Compose | desktop/、docker-compose.yml、backend/Dockerfile、frontend/Dockerfile | 部署思路和未验证项，不承诺安装包已验收 |

关键选择原则：一个测试要保护真实业务错误，不写只复述实现的测试。先纯规则，再事务，最后浏览器；只在影响面和最终验收要求下运行全量。

### AI 评测不是附带脚本

| 实际入口 | 重要性/学习动作 | 日期 |
|---|---|---|
| [dataset.py](../../backend/eval/dataset.py)、[metrics.py](../../backend/eval/metrics.py) | A/E★★★★★：手写案例装载、主题 Recall@K、命中/MRR；标题匹配指标不等于答案正确率 | D6、D9 |
| [run_retrieval_eval.py](../../scripts/run_retrieval_eval.py) | E★★★★：复制运行器后理解数据/检索/汇总连接；使用合成资料，不改冻结集 | D9 |
| [冻结40案例](../../eval/phase5-closeout-v1/cases.json)、[rubric](../../eval/phase5-closeout-v1/rubric.md) | A/E★★★★★：读输入、预期、分母、PASS/PARTIAL/FAIL与未完成；只读原件 | D9、D17 |
| [phase5_eval_meter.py](../../scripts/phase5_eval_meter.py) | A/E★★★★★：手写物理请求计数、usage/未知用量保守预留、软件停止核心；历史单价不代表现价 | D9 |
| [phase5_run_frozen_ai_eval.py](../../scripts/phase5_run_frozen_ai_eval.py)、[phase5_real_retest.py](../../scripts/phase5_real_retest.py) | E★★★★：读业务链调用、隔离夹具、原始输出/轨迹保留和不覆盖；不默认执行收费分支 | D9、D17 |
| [run_ragas_chat_eval.py](../../scripts/run_ragas_chat_eval.py)、[eval说明](../../eval/README.md) | E★★★★：读指标前提/裁判偏差；可能调用收费模型，不把脚本成功当真实正确 | D9 |
| [真实复测报告](../PHASE5_AI_REAL_RETEST_REPORT.md)、[用户验收](../FINAL_REAL_USER_ACCEPTANCE_REPORT.md)、[上下文修复](../CORE_UX_STABILIZATION_REPORT.md) | A/E★★★★★：从Q07/Q14/Q15、USER-A1/A3追到原始证据，区分路由/预算/模型/夹具失败 | D9、D16–17 |

必须能重写的是指标、结果契约、记账与回放断言核心，不是历史运行器全部内容。离线重建送模上下文只证明工程约束，不能冒充真实模型最终回答。Golden Slice 的历史人工核验流程不新增为当前公共题逐题人工准入要求。

## 11. 每条主链必须能回答的追问

1. 上传：为何不是每次请求当场完成全部 Embedding？如何避免新索引失败影响旧版本？
2. 标题树：为什么标题文字不等于 chunk 正文？如何保留祖先路径与精确引用位置？
3. 检索：为何 RRF 不需要把 BM25 和余弦先拉到同一分数范围？为什么它又不能证明资料相关？
4. 聊天：为什么 SSE 断流要有数据库终态？为何 HTTP 200 并不等于模型回答完成？
5. 版本：为什么 Question 仍有当前字段，但旧题必须从 QuestionVersion 读？
6. 证据：为什么答案一样，独立作答与看解析后作答的证据不同？
7. 毕业：为什么题集是有限且版本化的？新增题为何不能自动改变旧学习义务？
8. Agent：为什么先读真实工具，再生成 Draft，用户确认后还要复验？
9. Context：为什么“同名工具+同参数”还不足以判定结果可复用？为何压缩后需验证事实一致？
10. 工程：一次网络 ConnectError、一次输出截断、一次预算停止，应怎样分别展示、记录和恢复？

这些追问的正式答案与完整代码将写入对应章节；本文件只划定应达到的能力和真实入口。

