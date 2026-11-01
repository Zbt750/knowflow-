# 项目代码学习索引

本文件为后续教程准备代码入口，不替代实际代码阅读。建议先沿一条请求链路学习，再深入数据模型与算法。

## 系统结构

- `backend/`：FastAPI 服务、业务规则、数据访问与 AI 服务。
- `backend/api/routes/`：HTTP 路由；业务入口按学习、资料、问答、任务等职责组织。
- `backend/services/`：领域服务，承载题目资格、学习计划、作答证据、RAG 和 Agent 工具逻辑。
- `backend/models/`：SQLAlchemy 数据模型。
- `backend/chat/`：对话请求、证据、工具调用及流式响应相关实现。
- `frontend/`：Vue 3、TypeScript 与 Vite 客户端。
- `tests/`：后端单元、集成与浏览器自动化测试。
- `scripts/`：本地开发、隔离测试数据准备、E2E 启动和维护脚本。
- `docs/`：业务说明、验收报告与本学习索引。

## 核心后端入口

- 应用创建：`backend/app.py`。
- 学习计划 HTTP 入口：`backend/api/routes/learning_tasks.py`、`backend/api/routes/study.py`。
- 资料上传与检索入口：`backend/api/routes/materials.py`。
- 对话/RAG入口：`backend/api/routes/chat.py`。
- 学习任务规划与确认：`backend/services/learning_task_service.py`。
- Agent 工具及真实库存/学习状态读取：`backend/services/learning_task_tools.py`。
- Agent 输入事实压缩与模型消息构造：`backend/services/learning_task_context.py`。
- 助手意图路由与确定性学习回答：`backend/services/assistant_router.py`、`backend/services/learning_assistant_service.py`。
- 当前可练题库存和来源统计：`backend/services/question_availability.py`。

## 重要数据模型

从 `backend/models/` 下对应模型文件跟踪关系，优先阅读以下实体及其外键：

- `Question`、`QuestionVersion`：题目身份与不可变内容版本。
- 题目资格/审核事件：审核事实必须绑定被审核内容版本或 hash。
- `PracticeItem`、`DailyPlan`：计划中实际分配的题目及其题目版本。
- `QuestionAttempt`、`LearningEvent`：作答和学习行为的历史证据。
- `KpState`、`KnowledgePoint`：知识节点状态及知识树。
- 毕业题集版本与成员：节点规定的公共正式题及版本化集合。
- 个人 AI 题相关模型：个人归属与公共正式题资格是不同事实；个人题不得形成基础毕业证据。

## 主要业务调用链

### 作答与学习证据

`study/作答 API → 当前 PracticeItem 绑定的 QuestionVersion → 判题服务 → Attempt/LearningEvent → KpState 与毕业证据服务`

读这条链时重点追踪辅助状态：独立答对、提示后答对、看解析后答对不能混为同一种证据。

### 奶蛙学习规划

`学习助手请求 → assistant_router → learning_task_service → learning_task_tools → 真实库存/学习状态/题目版本及资格事实 → 计划草案 → 用户确认 → DailyPlan`

工具建议与已创建的计划是不同阶段。确认以前不应写入正式计划。上下文编码只压缩重复字段，解码后必须与原始工具事实一致。

### RAG 问答

`chat API → 会话及资料范围 → 检索/引用证据 → Provider 流式回答 → SSE → 前端引用展示`

用户资料范围和内置资料范围应沿调用参数及检索过滤条件追踪；回答引用需要对应实际检索到的来源片段。

### 题目版本与毕业

`Question.current_version → 新练习实例绑定版本；旧 PracticeItem/Attempt 读取原版本`

毕业题集版本提供有限的节点题目集合。逐题可信完成状态由现有学习证据计算；个人 AI 练习不能混入公共毕业集合。

## 前端入口建议

从 `frontend/src/` 查找 Vue 路由、页面和 API client。按路由找到“今日学习”“知识树/节点详情”“资料库”“聊天/奶蛙”页面，再沿页面调用的 API 方法追到 `backend/api/routes/`。避免只看组件截图；同时检查 loading、空结果、错误和 SSE 结束状态。

## 推荐学习顺序

1. 先读项目 README、部署说明和本索引，了解本地服务组成。
2. 从 `backend/app.py` 学 FastAPI 路由注册、依赖注入和启动配置。
3. 跟读一道题的完整作答链：route、QuestionVersion、判题、Attempt/LearningEvent、节点状态。
4. 学数据库模型与 Alembic migration，重点理解历史版本绑定。
5. 跟读奶蛙规划链路：路由识别、工具执行、上下文构造、时间预算、确认写入。
6. 跟读 RAG：资料上传、解析与分块、索引、检索证据、SSE 返回和引用定位。
7. 阅读 Vue 路由和 API client，逐页面对照后端契约。
8. 最后运行单元、集成、Playwright 测试，理解测试隔离夹具与真实开发数据库的边界。

## 本轮相关回归

本轮上下文打包格式在送给模型前会压缩同构工具记录，并提供可逆展开协议。阅读 `learning_task_context.py` 时，应同时看对应单元测试和离线历史轨迹回放；离线协议测试不能替代真实 Provider 质量验收。
