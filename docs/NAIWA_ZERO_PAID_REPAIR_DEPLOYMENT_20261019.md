# 奶蛙工程修复部署与只读验收

日期：2026-10-19，Asia/Shanghai。最终状态：**DEPLOYED_READONLY_VERIFIED_REAL_MODEL_QUALITY_PENDING**。

本轮仅部署及只读核验，**真实DeepSeek物理请求0次**。未开展功能开发，未执行migration、seed、数据库授权、题库导入或业务清理。

## 1. 部署前安全检查

- 8000唯一监听为 `127.0.0.1:8000`、PID8560。
- Python为 `C:\Users\ZBT\AppData\Local\Programs\Python\Python312\python.exe`。
- 完整进程命令：

```text
"C:\Users\ZBT\AppData\Local\Programs\Python\Python312\python.exe" -u scripts/run_phase4_backend.py --manifest tmp/dev-backend-manifests/runtime-b27442342f47407e829337a2bad5ebcb.json
```

- 原manifest确认 workspace=`D:\考研跑通项目`、module=`backend.main:app`、PID8560、bind=`127.0.0.1:8000`，与进程对应。
- 原启动器 `scripts/run-backend.cmd` 内 `cd /d "%~dp0.."`，使用PATH上的Python；重启前核对PATH解析的Python与原进程完全相同。配置按工作目录 `.env`（UTF-8）及已有本地加密模型设置加载；未输出密码/API Key。
- 在 `127.0.0.1:5433/kaoyan`、角色 `kaoyan` 上执行显式 **REPEATABLE READ / READ ONLY** 事务，仅SELECT核验。26张public表均有读取权限，没有未能核对的表。
- 首次快照与停机前复核均显示：生成消息0、活动学习任务0、资料处理任务0、活动出题批次0。没有带着运行任务重启。
- 保存旧manifest、后端日志、进程及PostgreSQL主进程身份、8个部署相关源码指纹、启动器指纹和业务表摘要。

## 2. 测试版本核对

上一轮最终证据为：后端定向135 passed、浏览器6 passed、相关Vitest14 passed、类型检查与构建成功。对应最终run-summary均退出0，不使用早期失败迭代充当最终结果。

上一轮没有为每份测试产物嵌入Git提交号；本次未虚构测试版本标识。核对方式为：

1. 保全上一轮测试后留下的四个核心后端 `.pyc` 文件及指纹、时间；
2. 编译当前源码但不执行，递归比较指令、变量、参数、闭包及常量；
3. 仅忽略docstring与源行号元数据，四个模块可执行代码全部一致；
4. 已知测试后唯一差别为 `learning_task_service.py` 的函数说明文字更新，不是逻辑改动；
5. 部署前后8个相关源码SHA256保持一致，重启后manifest所列25个文件全部与磁盘SHA256一致。

详细证据：`version-preflight.json`、保全的tested.pyc、`runtime-code-verification.json`。本轮未重跑迁移或写入型测试。

## 3. 实际重启

2026-10-19 22:16左右，仅停止身份已确认且无活动任务的PID8560，确认8000释放后，使用原 `scripts/run-backend.cmd` 隐藏启动。原启动器继续追加 `storage/backend-dev.log`，未覆盖旧日志。

| 项目 | 重启前 | 重启后 |
|---|---|---|
| 后端PID | 8560 | **8888** |
| 后端监听 | 127.0.0.1:8000 | 127.0.0.1:8000，唯一监听 |
| 前端PID | 22184 | 22184，未重启 |
| PostgreSQL主进程PID | 21052 | 21052，未重启 |
| PostgreSQL主进程创建时间 | 2026-10-19 09:13:14.162 +08:00 | 相同（按原PS5记录的毫秒精度核对） |
| 工作目录 | D:\考研跑通项目 | D:\考研跑通项目 |
| Python环境 | Python312原路径 | 相同 |

新进程命令：

```text
"C:\Users\ZBT\AppData\Local\Programs\Python\Python312\python.exe" -u scripts/run_phase4_backend.py --manifest tmp/dev-backend-manifests/runtime-3877e2d858494e3b988ab3f7a1ec9b83.json
```

新manifest：`tmp/dev-backend-manifests/runtime-3877e2d858494e3b988ab3f7a1ec9b83.json`。

- PID8888，parent PID38936，started_at=`2026-10-19T14:16:14.186947+00:00`。
- workspace_phase4_sha256=`3b58e0fb7ba03e27e8955e24dade0b5a63eacc153c15b0d34d7d09bcac9ce608`。
- QA prompt=`learning-qa-v7-round2`，Planner prompt=`learning-task-v19-lossless-records`。
- 本轮未更换模型、密钥、Provider或配置价格。

执行辅助脚本初次被Windows PowerShell5对无BOM UTF-8路径/manifest的默认解码阻止，均发生在停止进程之前。改为从脚本目录推导项目根目录、显式UTF-8读取后才成功执行；没有因此反复重启服务。另一次PostgreSQL时间精确比较发现PS5 JSON只有毫秒精度，按相同毫秒精度及PID/父PID核对后确认主进程未变，并非PG发生重启。

## 4. 部署后只读检查

| GET端点 | 结果 | 本次单次耗时 |
|---|---|---:|
| 8000 `/api/health` | 200，dev、DB connected、retrieval ready、worker running | 7ms |
| 5173 `/api/health`（Vite代理） | 200，后端状态一致 | 4ms |
| 8000 `/openapi.json` | 200，56个路径，与manifest相符 | 3ms |
| `/api/knowledge/tree` | 200 | 3ms |
| `/api/plans/today` | 200 | 100ms |
| `/api/chat/sessions?mode=builtin&purpose=qa` | 200 | 6ms |
| `/api/materials?source_type=user&limit=1` | 200 | 6ms |
| `/api/question-bank?scope=personal&limit=1` | 200 | 6ms |

这些是只读连通性与接口检查，不是新的性能压测或真实问答测试。没有调用POST问答、生成、重试、确认计划、作答或其他业务变更端点。

OpenAPI中不含隔离测试的 `__zero` 端点。前端5173实际提供的四个模块中检查到：

- ChatPage长回答默认展开的新逻辑；
- chatAnswerText历史重复来源前缀去重；
- main.ts本地KaTeX字体预加载；
- product-theme.css手机奶蛙对话框避开底部导航的新样式。

## 5. 代码生效证据及边界

不是仅凭健康检查200判定部署：旧PID已退出、新Python解释器实际启动、启动命令与工作目录相符、新manifest PID与唯一监听PID一致，manifest中25个文件指纹逐项匹配。

`backend.chat.service`、`learning_task_service`与`learning_assistant_service`由启动导入路径/启动器显式导入，新解释器加载本轮修复版本，未复用旧进程内存。

数学检查 `generation_formula_consistency` 是 `assess_general_output` 内的**惰性导入**。本轮不触发生题，因此不声称该模块在PID8888内已经执行；其磁盘版本与已验收可执行缓存一致，首次生题会按新进程正常导入。不能为了证明它执行而绕过本轮零模型、只读边界。

前端修复已由5173提供；本轮未操作浏览器发送消息。建议用户刷新页面以获取最新前端模块，但不需要再自行重启后端。

## 6. 数据变化

部署前后26张public表：**行数及完整行内容聚合摘要全部一致，changed_tables=[]**，没有缺少读取权限而遗漏的表。题目、版本、审核/资格、今日卷、PracticeItem、QuestionAttempt、LearningEvent、会话、消息、资料与任务记录均未变化。

应用原有启动恢复逻辑包含将残留generating消息收尾的语句；停机前已确认匹配数为0，启动后快照证明没有业务行改变。没有额外人工执行业务写入、迁移、seed、GRANT或数据修复。

运行manifest、日志追加、本轮验收JSON/报告属于文件证据，不是业务数据库变更。

## 7. 最终明确区分

1. **已部署后端工程修复**：新回答来源前缀去重；Agent手动恢复、保留审计、异常分类与不隐式重发；数学校验新磁盘代码待正常业务惰性导入。
2. **前端已提供的修复**：默认完整阅读/主动折叠、历史前缀兼容、字体预加载、手机聊天框避让及按钮字号。5173未重启。
3. **固定Provider已通过的工程测试**：沿用上一轮135后端、14 Vitest、6 Chrome及类型/构建证据；本轮只核对证据和部署，没有伪造新的测试通过数量。
4. **尚未验证真实DeepSeek效果**：数学正确率、相对难度执行、学习规划效果及外部网络稳定性仍为PENDING；本轮没有付费复测，也不宣称全部问题已经通过真实模型验收。

没有本轮部署阻塞。剩余风险是上述真实模型效果待授权验证，不是本次启动失败。

## 8. 证据入口

目录：`storage/quality-audits/zero-paid-ux-deploy-20261019-v1/`。

- `process-before.json` / `process-after.json`：完整进程命令、身份、前端与PG未重启证据。
- `old-runtime-manifest.json` / `new-runtime-manifest.json`：原样保全运行清单。
- `backend-before.log` / `backend-after.log`：部署前后日志。
- `version-preflight.json` / `runtime-code-verification.json`：版本及文件指纹。
- `before.json` / `shutdown-check.json` / `after.json`：只读身份、任务状态及26表摘要。
- `http-after.json` / `openapi-after.json`：实际HTTP结果和OpenAPI。
- `restart-action.json` / `launcher-hashes.json`：原流程启动记录。

新增的两个辅助脚本仅用于本次部署审计：`scripts/verify_zero_paid_deployment_20261019.py`、`scripts/deploy_zero_paid_backend_20261019.ps1`。未改正式产品行为。

**本轮真实DeepSeek物理调用：0。部署完成，停止。**
