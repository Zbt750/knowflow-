# 自适应考研学习知识库：20天黑马式项目复现路线

日期：2026-10-16。状态：CHAPTERS_00_TO_03_DELIVERED。本文保留已确认路线；已交付第00–03篇。教程代码在独立复现工程，不修改产品代码或API。

长期规则：[tutorial-rules.md](tutorial-rules.md)。接口护栏：[api-contract-baseline.md](api-contract-baseline.md)。这三份为当前依据；旧20天日期表、固定24项章模板及独立lab主线不再适用。

## 1. 这20天到底重建什么

重建一个与现有项目同结构、同核心契约的可运行教学工程：后端、资料/RAG、会话/LLM/SSE、学习事实/版本、Agent任务与确认、测试和运行链。

不是逐文件背源码，也不是删减业务规则的“理想简版”。最终关键API、数据语义、来源/版本/毕业/确认边界与产品保持对应；边缘兼容和重复样板以完整配套接入。

### 现实时间条件

- 每天5小时，合计100小时；会基础Python函数/类/集合、终端操作。没有这些基础时，20天内达到同等独立程度不现实。
- 每天约1小时理解/推导、3小时编码/运行、1小时复盘；具体按任务调配，不机械套正文模板。
- 完整产品所有兼容路径、前端和历史脚本都从头独立手写，100小时做不到。不能为了赶进度省略安全、版本或确认规则。
- 下载/环境问题必须记录；不能把10小时排错隐藏为“课程5小时”。若连续两天超时，先降低B/C的手写量，不删A类行为约束，必要时延长学习天数。
- 不要求所有AI问题真实付费验证。默认离线协议测试＋历史真实证据；新真实模型测试另行确认请求/金额/数据。

### 时间权重（按主教学目标，不重复计时）

| 主类别 | 日期 | 小时 | 权重 | 学习结果 |
|---|---|---:|---:|---|
| 后端、数据库与学习业务 | D1–2、D10–12 | 25 | 25% | API/事务/模型/版本/证据可独立解释与实现 |
| RAG与资料摄取 | D3–7 | 25 | 25% | 真资料→Chunk/索引→三路检索→Context/引用 |
| LLM、SSE与会话 | D8–9 | 10 | 10% | 可配置Provider、真实状态/历史/流式 |
| Agent/Tools/任务确认 | D13–16 | 20 | 20% | 取证→规划→校验→确认→执行→恢复 |
| AI评测/费用/失败归因 | D17 | 5 | 5% | 冻结案例、回放、rubric、ledger与成本 |
| 测试工程与部署 | D18–19 | 10 | 10% | 隔离回归、Windows/Compose运行边界 |
| 最小前端联调与全链演示 | D20 | 5 | 5% | 知道页面/API/SSE连接，完整演示并复盘 |
| 合计 | D1–20 | 100 | 100% | AI相关主线60%，其余支撑40% |

这是最新附件建议顺序对应的当前分配，不沿用旧版“Agent固定5天”的日期表。数据库/测试/配置也会在AI章节实际使用，但同一小时不重复记账。D20的Vue语法/CSS阅读最多1小时，其余用于真实请求、状态、恢复和演示，不是5小时写UI。

## 2. 当前项目事实：不能照想象讲课

- app入口是backend/main.py→backend/app.py:create_app；lifespan会初始化共享资源及做恢复，不可对真实库随便启动。
- Router→Service/ORM是实际边界，没有统一Repository包。不为课程新增仓储架构。
- Material/DocumentChunk的权威正文在PostgreSQL；Chroma是本地派生索引，不是独立云向量服务。
- 文档标题树在ingestion/title_tree.py，结合段落/字符窗口分块；标题召回在retrieval/keyword.py。知识树是另一套KnowledgePoint教学结构。
- search_chunks负责检索编排；KeywordIndex有正文和标题召回；RRF融合后回表，再按配置重排/条件MMR。不是向量相似度直接加BM25分数。
- Provider、SSE与较多聊天逻辑在chat/service.py，不虚构provider.py或另换Agent框架。
- Agent当前Prompt为learning-task-v19-lossless-records；有6轮、10工具、60秒和60000字节输入守卫，不当作60000 token。
- Question保留当前投影；QuestionVersion保存受保护内容快照，历史练习绑定旧版本。
- v3毕业依据适用非空冻结题集的可信完成；不重引跨天/真题/题型配额。个人题、辅助正确、自评不冒充正式毕业证据。
- 当前有62个API操作、80个组件Schema；旧前端OpenAPI存档有20处Schema差异，见基线，不能假装零漂移。
- Compose是PostgreSQL16配置；既有本地验收涉及18.4。不同主版本不能共用物理数据目录。Docker未验收就如实记录。
- 未见当前架构使用Redis/Celery/LangGraph，不为“像AI项目”添加。

此前代码规模口径：backend约27430非空行（含注释），不是整个项目只有2万行。含测试/历史脚本/生成类型的范围更大；旧“2万行”只能作粗略印象，不能作为手写配额。本轮复核原登记源码/冻结资产未变，不重新声称数据库或真实AI已验收。

## 3. 一个工程、连续检查点

拟定结构如下，确认后才逐章产出正文/检查点，不一次创建几十篇空文件：

~~~text
tutorial/
├── README.md
├── tutorial-rules.md
├── tutorial-roadmap.md
├── api-contract-baseline.md
├── 00_项目与契约/
├── 01_后端与数据库/
├── 02_资料进入系统/
├── 03_RAG检索与证据/
├── 04_LLM与会话/
├── 05_学习闭环/
├── 06_Agent任务系统/
├── 07_AI评测/
├── 08_测试与部署/
├── 09_联调与复盘/
├── code/                 # 同一复现工程，backend/frontend/tests等保持真实路径
├── checkpoints/          # 关键阶段完整状态，不是独立demo
├── diagrams/
└── checklists/           # 完成对应章节时生成，不先造空清单
~~~

学生只建立一次空复现目录及独立运行环境。课程文件、完整配套与快照不包含密钥、原.pgdata、真实上传或学习历史。章节不会通过sys.path指向原产品来补缺失实现。

每个检查点包含该阶段全部必要文件、依赖、迁移、测试数据与命令；A类正文完整给代码并分段解释，B/C完整配套并简讲。未实现功能不挂缩减DTO的正式API，不用假成功；等达到既有契约后接线。

### 依赖地图

~~~text
D1启动/HTTP → D2数据库/Session
                 ├→ D3上传/任务 → D4结构分块 → D5真实索引
                 │                              ↓
                 │                  D6混合检索 → D7Context/引用
                 │                              ↓
                 │                  D8Provider/SSE → D9会话/RAG闭环
                 └→ D10题目版本 → D11作答/事件 → D12完成/毕业
                                                 ↓
                D9会话 + D12可信事实 → D13工具 → D14Context
                                                 ↓
                                    D15规划 → D16确认/执行/恢复
                                                 ↓
                              D17评测 → D18工程回归 → D19部署 → D20演示
~~~

测试贯穿每一条箭头；D18是汇总，不是第一次写测试。技术上先提供够用的模型/适配完整配套，D10–12再深讲学习领域；不能出现Agent先依赖一套未教、也未配套的证据服务。

## 4. 完整模块目录：不逐文件平均讲

以下编号是功能模块编号，不强制等同于正文篇号。数据库模块已经拆为第02篇（独立PG与真实健康检查）和第03篇（Material与迁移/事务），共同承接D2，不额外增加学习天数；工具已备齐时两篇预计合计4–5小时，首次安装和环境问题另计。后续资料上传将接着写第04篇。数量可随正文合理合并，模块总时数不能偷偷膨胀；每模块内有多个短验证节点，不规定每个Markdown同样长。

| 模块与拟章节 | 目标/真实工程落点 | 教学动作与重点 | 时间/依赖/验收 |
|---|---|---|---|
| 00 项目效果、需求、真实架构、契约护栏 | app、api/routes、前端client、契约基线 | B完整阅读；先画四条用户链，不讲一堆术语 | 含D1的1h；验收能指出入口/存储/确认边界 |
| 01 第一个请求与应用组装 | main.py、app.py、config.py、errors.py、api/deps.py | A写骨架/依赖；B完整错误/配置接线；不另造业务URL | D1其余4h；健康语义匹配，无假ready |
| 02 PostgreSQL、Session、事务与迁移 | db.py、models/base.py、models/rag.py、migrations | A核心模型/查询/回滚；B完整迁移与隔离启动 | D2 5h；独立库表/Session正确，禁止回退5433 |
| 03 用户资料可靠进入系统 | materials路由、material_service、file_storage、DocumentJob/runner | A上传/文件与事务；B解析适配和完整任务接线 | D3 5h，依赖02；201满足material/job_id/message，轮询状态可解释 |
| 04 资料怎样变成可引用正文块 | document_parsers、text_normalize、title_tree、chunker | A结构/offset/Chunk；B PDF/DOCX与边界语法完整适配 | D4 5h，依赖03；正文切片/hash/路径稳定，扫描件不假成功 |
| 05 让正文进入真实向量索引 | embedding、vector_store、ingestion_service、retrieval/stack | A编码/写入/查询与激活流程；B底层模型/Chroma适配 | D5 5h，依赖04；真实本地模型、磁盘索引可恢复，失败不激活 |
| 06 用户问题触发三路混合召回 | keyword、fusion、retrieval_service、materials/search | A BM25调用/标题扩展/RRF/接线；不重复实现第三方BM25全部内部 | D6 5h，依赖05；三路追踪、范围、回表、TopK及API集成 |
| 07 给模型可靠的证据而非一堆文本 | rerank、mmr_select_hits、chat/evidence、引用组装 | A Context/范围/出处；B可选重排/MMR与完整实现 | D7 5h，依赖06；预算/去冗余/定位正确，未启用不伪称运行 |
| 08 LLM怎样被安全接入和流式呈现 | chat/service Provider/Prompt/encode_sse、call_trace | A HTTP/消息/finish_reason/流终态；B密钥保存适配 | D8 5h，依赖07；离线协议/截断/超时/取消区分 |
| 09 用户继续追问与恢复会话 | chat路由、models/chat、query_context、material_search_service | A历史/范围/真实引用链；B旧分支与完整持久化 | D9 5h，依赖08；多轮不误路由、刷新不重发，RAG完整离线链 |
| 10 题目改了，旧作答为何不变 | models/learning、question_versions、question_eligibility | A版本快照/读取/绑定；B完整hash/审核与历史兼容 | D10 5h，依赖02；旧练习旧版本，当前资格不回溯证明旧内容 |
| 11 今日卷、判题、Attempt与Event | planning、practice、answer_grading、answer_submission、attempt_service | A事务/幂等/判题主链；B支持格式与复杂接口配套 | D11 5h，依赖10；GET不建卷，提交可追溯，辅助行为正确 |
| 12 从学习事实识别真正完成 | mastery/evidence/rules/transition/storage、graduation_question_set、post_graduation | A证据分类/v3汇总；B历史题集和毕业后逻辑完整接入 | D12 5h，依赖11；全规定题可信完成才毕业，个人题不混入 |
| 13 奶蛙先学会读事实 | assistant_router、learning_task_tools、planner_facts、availability | A Tool Schema/真实查询/事实返回；B统一资格与历史读取 | D13 5h，依赖09/12；库存/来源/版本/独立辅助证据可核对 |
| 14 模型多轮使用工具且不撑爆Context | learning_task_service、learning_task_context、Provider.tool_turn | A有界循环/压缩/引用；B完整恢复轨迹配套 | D14 5h，依赖13；事实往返一致，变化不误复用，原预算守卫有效 |
| 15 20分钟任务如何成为合法草案 | validate_plan、learning_assistant_service、约束/来源纠正 | A时长/范围/ID校验及草案；B意图/QA交接完整适配 | D15 5h，依赖14；20不变90，不编题/来源，未确认不执行 |
| 16 用户确认后才执行与安全恢复 | confirm_task/get_task/cancel_task、practice_requests、版本与计划签名 | A事务复验/幂等/取消；B完整锁/历史约束 | D16 5h，依赖15；过期拒绝、确认一次、恢复不重复收费 |
| 17 AI效果不是HTTP200 | backend/eval、eval冻结案例、Meter/ledger、历史回放脚本 | A指标/评分聚合/物理调用计数；B完整运行器只读；C历史批次 | D17 5h，依赖09/16；分清模型/工具/预算/夹具，未知usage不记0 |
| 18 用户链与测试工程 | tests、Vitest、Playwright、隔离runner | A必要反例/事务/API；B完整fixture/E2E/进程管理 | D18 5h；复现自己的结果，不冒充原全量通过 |
| 19 从代码到可运行软件 | Windows启动、Dockerfile、Compose、desktop与备份入口 | B完整运行脚本/配置；C安装器内部和历史运维 | D19 5h，依赖18；独立环境持久化/恢复、明确Docker未验证项 |
| 20 最小前端联调、全链演示、架构复盘 | Vue页面、api/*.ts、types、SSE reader、Network | B接口联调，C绝大多数Vue/CSS；关键模块集中追问 | D20 5h；原契约未变，能跑并解释四条链，不冒充商业UI/性能验收 |

## 5. 每天学什么、写什么、测什么、交付什么

| 天 | 今日目标 | 必须动手 | 当天测试 | 最终可观察成果 |
|---|---|---|---|---|
| 1 | 空工程接住真实请求 | 建backend骨架、Settings、Router/依赖/错误主线 | 健康/无效路径/安全错误；未完成DB不宣称connected | 能解释并运行HTTP入口；API改动标否 |
| 2 | 请求可靠访问独立PG | Engine/SessionFactory、Material等必要模型、迁移 | 独立库身份与端口、回滚、不跨Session共享 | 可持久查询，不依赖原项目库 |
| 3 | 学生上传并观察处理任务 | 文件保存/清理、事务、上传/列表/任务接线 | 大小/类型/失败补偿、分页与完整DTO | 页面/接口能上传、看pending/任务，而非假ready |
| 4 | 文档结构变成稳定Chunk | 标题栈/直接正文、规范化、分块/offset | 围栏/重复文本/层级/切片不变量 | DB能看到正确heading_path和原文定位 |
| 5 | 真实本地索引可查 | Embedding、Chroma写/查、版本构建/激活 | 数量/维度/模型不匹配、新索引失败保护 | 重启后真实向量可查；没有模型就记阻塞 |
| 6 | 三路结果进入同一个搜索服务 | BM25/标题扩展/RRF、回表、API调用 | 单路重复/跨路支持/空范围/陈旧ID/TopK | POST /materials/search返回真实合法hits |
| 7 | 候选变成有限且可引用的证据 | Context/citation map、条件重排/去重调用 | 越界资料/上下文预算/引用label位置 | 当前证据能定位，RRF不冒充置信度 |
| 8 | 模型协议与SSE可以诊断 | Provider、Prompt、事件编码/错误/终态 | OfflineProvider、超时/截断/断流、UTF-8拆包 | 用户看到可恢复终态；不谎报真实模型成功 |
| 9 | 资料问答连续性和会话恢复 | 历史裁剪、资料范围、消息/引用持久化 | Q07/Q14/Q15类反例、恢复/删除后的引用边界 | 资料→检索→离线回答→引用→历史完整链 |
| 10 | 当前题与旧题内容分开 | 核心ORM、Version快照/绑定读取 | 原题更新、跨题绑定、审核hash失效 | 旧PracticeItem保持题干/答案语义 |
| 11 | 今日学习与作答闭环 | 推荐/确认建卷、按版本判题、Attempt/Event幂等 | 正确/错误/未知、解析辅助、重复提交 | 作答历史保存，GET不创建计划 |
| 12 | 判断真完成而不混淆学习驱动 | 独立/辅助分类、v3集合汇总/投影 | 空集合、个人题、自评、旧实例、毕业后复习 | 有限题集完成才毕业，历史事实保护 |
| 13 | Agent读取真实证据 | Tool Schema、学习状态/题库/来源查询 | 未知ID、库存总量与预览、独立/辅助/自评 | 工具结果可和DB证据逐项对照 |
| 14 | Agent有界循环和无损Context | 多轮消息、工具执行、pack/expand/相同结果引用 | 6轮/10工具/60秒/60KB边界，变化不复用 | 原始轨迹保留，送模副本有界 |
| 15 | 生成可执行但尚未执行的草案 | validate_plan、用户时间/范围/题型、来源纠正 | 20分钟、库存不足、虚构来源、无确认 | TaskView与draft有真实ID和可核对约束 |
| 16 | 用户确认与事务执行 | 版本签名/计划签名/资格再验、幂等、取消恢复 | 过期、并发/重复、迟到结果、已绑定历史版本 | 确认才追加PracticeItem，恢复不重复模型调用 |
| 17 | 评估AI的事实与成本 | 案例读取、评分聚合、ledger预算、回放断言 | 网络/Provider/工具/预算/截断分类、未知usage | 免费评测/回放报告与待授权真实测评方案 |
| 18 | 系统级测试与定位 | 相关后端/前端/E2E、合成fixture、日志关联 | 版本/确认/范围/辅助证据与完整链 | 自己的准确测试摘要；不能把部分写全量 |
| 19 | Windows与Compose运行方法 | 配置、独立数据目录、启动/健康、备份恢复演练 | 首次启动、重启持久化、隔离恢复、版本差异 | 可复现运行说明；Docker不可用如实未验证 |
| 20 | 界面联调、演示、面试复盘 | 跟踪真实页面→API/SSE；独立重写关键段 | 原请求/响应/SSE保持、刷新恢复、未确认不写 | 同一工程四条链可演示，写清实际掌握与限制 |

不要求每天新增一个不连通目录。缺少某前置模块时，完整阶段代码会显式提供；不让读者自行补核心。API仍在构建时不以缩减response假装现有前端兼容。

## 6. 核心代码复现清单

| 分级 | 必须完成的学习动作 | 当前真实代码落点 |
|---|---|---|
| A 必须亲手写 | HTTP/依赖/Session/事务核心 | app/main/config/db/api/deps/errors主路径 |
| A | 标题与分块核心、编码/索引调用、BM25/标题路、RRF、范围/回表/Context/引用 | ingestion、retrieval、retrieval_service、chat/evidence |
| A | Provider HTTP/消息转换、Prompt、SSE/历史预算/终态 | chat/service、call_trace、query_context |
| A | 题目版本读取、作答幂等、证据分类与v3完成主链 | question_versions、answer_submission、mastery |
| A | Tool Schema/事实、Agent有限循环、20分钟校验、草案/确认/Context/恢复关键段 | learning_task_tools/context/service、planner_facts |
| A | 必要正反例、指标/评分和物理请求记账核心 | tests、backend/eval、Meter与回放核心 |
| B 完整代码跟做并理解 | 长文件其余状态机接线、资格/审核读取、历史兼容、PDF/DOCX/模型适配、任务线程/锁/完整DTO/迁移 | 原结构完整配套，不另写一套资格或学习状态 |
| B | Windows/Compose启动与测试runner、API client关键段 | scripts、Dockerfile/Compose、api/*.ts |
| C 提供必要代码，阅读定位即可 | 大部分Vue/CSS/生成类型、历史题库批次脚本、打包内部、库算法内部 | frontend、历史scripts、desktop、第三方实现 |

### 手写/理解量的实际预期

- A类独立手写目标约4000–6000行**选定核心和必要测试**，随章节实际调整；不是每天必须敲300行。
- B类预计重点阅读/跟做约4000–8000行，主要看职责、契约、调用和失败边界，不逐行背。
- C类只按链路定位，可能涉及数千至上万行，但不要求连续读完，尤其不抄9692行生成类型。
- A/B/C可在同一大文件按函数/职责划分；上述阅读范围有交叉，不能简单相加成“已掌握总行数”。
- 不承诺20天能脱稿写出完整现有产品或全部4–6千行。验收是能独立写关键路径并运行、解释边界；若A类没有理解，应延时或减少旁支，不装作完成。
- “最有价值20%–40%”只能指选定业务主线的学习精力，不能冒称已覆盖含历史脚本/测试的整个12万行工作区。

## 7. 核心模块怎样从零长出来

### RAG不是算法拼盘

从本工程上传真资料，拿到真实Material/Job，解析/规范化/Chunk入库后建立真实BGE/Chroma索引；先观察一路遗漏，再增加正文/标题召回；三路都有实际结果才引出RRF。融合接入search_chunks并调用原API，随后加入条件重排/MMR、有限Context和引用，再接Provider/SSE。5分钟手算可插入，不成为独立lab主线。

### Agent不是另造一套内存计划器

先用真实业务服务读学习状态、库存、来源和Version，再实现Tool消息协议/循环；构造可核对证据上下文，验证预算与候选，形成TaskView/Draft；用既有用户确认协议重验并提交。然后处理取消/迟到/恢复。先离线验证协议，再另行授权真实模型，不偷换模型或自动补发。

### 数据库不是只有CRUD

需求→事实/投影/工作状态→字段/外键与hash→完整Model/迁移→查询/事务→API→测试。重点讲QuestionVersion、PracticeItem/Attempt绑定、LearningEvent与KpState为何分开，不对所有普通字段平均展开。

## 8. 怎样保证后续前端优化不毁掉课程

1. 每章标“本节是否修改API契约：否/是”，默认否。
2. 以当前62操作/80Schema、动态返回和SSE补充为基线，不只看路径列表。
3. 教学分步不删既有必填DTO；后端未满足契约时不接正式路由，不用假字段填充。
4. 前端最小联调沿原api client/请求/错误/流格式；CSS和布局留待表现层优化。
5. 真实变更先标【API CONTRACT CHANGE】，同步后端、OpenAPI/基线、前端/类型、相关测试、E2E与教程检查点说明。
6. 已知前端OpenAPI存档漂移先记录，不能在只写教程的授权下擅自修类型或改业务。

## 9. 完成以后应达到什么水平

应能讲清四条链：

- 资料上传→任务→规范化/结构分块→数据库/索引→三路检索→Context/引用。
- 用户问题→会话/范围/历史→Provider→SSE→持久化/恢复。
- 今日学习推荐→确认→PracticeItem/Version→判题→Attempt/Event→单题完成→题集毕业。
- 学习目标→Tools/真实证据→有界循环/Context→合法草案→用户确认→复验/事务→恢复。

应能独立实现选定核心，不依赖“AI替我把剩下的补上”。面试追问集中于混合检索取舍、Context/引用、Agent执行权限、版本与证据、事务/并发、预算/评测、部署局限，不在每篇CRUD后重复套题。

不用深入：模型训练、torch内部、Chroma底层索引实现、全部历史批次solver、复杂CSS/动画、安装器所有细节。可以解释为什么没有引入Redis/Celery/大型Agent框架，不伪装它们已存在。

**作为AI应用开发实习项目具备可展示的题材和工程深度，但简历可信度取决于你实际能演示、重写和解释的部分。**不要声称RAG零幻觉、真实40案例全绿、Docker生产验收通过或已有高并发压测。

## 10. 当前正文交付边界

现有正式正文为第00–03篇；第02篇接通独立PG，第03篇建立Material与迁移/事务。它们的完整源码检查点位于course/checkpoints；学生仍只在桌面kaoyan-rebuild连续开发。最新教程规范已纳入PyCharm现场操作、为什么现在写、短验证节点、前后能力与上下游说明。没有生成后续章节，也不开始前端视觉优化。

仅为课程验证创建了自己的教学PG并正常停止；没有连接5433、修改产品代码/API/冻结案例或用户数据。真实HTTP与真实PG测试不冒充浏览器视觉、真实模型或完整产品验收。

此前未交付的project_samples_v2草稿由于尚未满足API契约/验证要求，不是正式可运行检查点。本路线不会把该草稿的部分实现冒充验收通过。目录确认后，逐章提供符合契约的完整实现、检查点与实际验证记录。
