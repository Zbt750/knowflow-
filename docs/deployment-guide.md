# Windows 本地部署与运行指南（Phase 5 候选）

本指南描述当前项目仓库中的本机启动方式。Phase 5 已验证隔离环境内的前后端运行、前端类型/单元测试/构建和部分 Chrome E2E；**没有验证真实开发数据上的启动脚本，也没有完成 Docker 容器启动验收**。请先备份真实数据库，并确认要连接的数据库地址，再运行可能执行 migration 或 seed 的命令。

## 要求

- Windows 10/11
- Python 3.12（本机验收：3.12.10）
- Node.js/npm（本机验收：24.18.0 / 11.16.0）
- PostgreSQL 18（项目开发集群端口 5433）
- Google Chrome（仅浏览器 E2E 需要）
- 本地资料向量检索需要缓存 `BAAI/bge-small-zh-v1.5`；缺少模型时检索能力可能不可用

## 本机开发启动

1. 在项目根目录复制 `.env.example` 为 `.env`，按本机数据库、资料目录及模型配置编辑。不要把密钥写入 Git。
2. 确认 PostgreSQL 的数据目录、端口和目标数据库。仓库 README 的开发脚本目标是项目独立 `.pgdata` 集群端口 `5433`；不要用另一套 Windows PostgreSQL 服务或错误的数据目录代替。
3. 完成第一次安装和数据库初始化后，运行：

```powershell
scripts\start-dev.cmd
```

4. 浏览器打开 `http://127.0.0.1:5173`；后端通常在 `http://127.0.0.1:8000`。状态检查可运行 `scripts\status.cmd`，停止服务运行 `scripts\stop-dev.cmd`。

> 注意：启动流程及 `scripts\seed.cmd` 可能执行数据库迁移或种子更新。不要对已有真实学习数据的库盲目执行。Phase 5 没有用当前脚本对 live DB 做写入式启动验收。

## 首次数据库准备

初始化新开发环境时，先阅读仓库 README 的 PostgreSQL 18 `.pgdata` 初始化步骤，确认目录为空且确为新环境后再使用 `initdb`。已有数据目录不得重新初始化。新库建立后，按 `.env.example` 配置数据库连接，并根据项目说明运行 Alembic migration 和 seed。migration 仅用于全新/已备份且被授权的目标库。

## 模型配置

项目支持从环境变量载入问答模型配置；开发环境也可能提供本机设置页。`key_configured` 仅表示已经配置密钥，不代表供应商认证成功、余额充足或模型质量通过。Phase 5 使用离线 E2E Provider，没有真实模型请求。不要把 API 密钥放进报告或命令历史。

## Docker Compose（未完成运行验收）

仓库提供 `.env.compose.example` 和 `docker-compose.yml`。静态部署配置校验及 Compose 配置语法通过，但本机 Docker Desktop Linux Engine pipe 不可连接，因此未执行 build/up。

仓库 Compose 当前使用 `postgres:16-alpine`，而项目真实开发库为 PostgreSQL 18.4。PostgreSQL 主版本的数据目录不能直接跨版本共用；**不要把 PostgreSQL 18 的现有数据卷挂给 PostgreSQL 16 容器，也不要以 `docker compose down -v` 处理版本不兼容**。部署前需要确定受支持的数据库主版本并规划 dump/restore 升级，再在独立副本验证。

静态配置检查命令：

```powershell
python scripts\check_deploy_config.py
docker compose --env-file .env.compose.example config --quiet
```

## 回归测试

```powershell
python -m pytest
cd frontend
npm run typecheck
npm run test:unit
npm run build
npx playwright test
```

后端测试和 E2E 会写测试数据，必须确认 `TEST_DATABASE_URL` 指向隔离数据库，并使用隔离的 upload/Chroma/output 路径。不要通过 5433/`kaoyan` 作为 E2E 测试库。当前仓库的 `scripts\run-e2e.ps1` 已被识别为存在旧的 5433 数据库配置风险；修正并独立复核前，不建议把它作为真实数据环境中的启动入口。

本轮 Phase 5 实际结果及失败组见 [产品验收报告](product-acceptance-report.md) 与 [机器测试摘要](test-summary.json)。

## 常见问题

- PostgreSQL 端口被占用：核对 PID、服务和数据目录；不要强杀未知进程。
- 后端数据库连接失败：核对 `.env` 中的数据库主机/端口/库名，确认指向预期的 PostgreSQL 实例。
- 检索返回不可用：检查 embedding 依赖及模型缓存；不要把关键词查询成功误报为向量检索完整。
- 今日试卷生成返回 409：检查正式 QuestionVersion、审核资格及当前 v3 毕业题集绑定；不要移除资格守卫来规避。
- Docker 起不来：先确认 Docker Desktop Linux Engine 正常。不要清卷或切换 PostgreSQL 主版本以“试试看”。
- 测试权限 EPERM：Windows 沙箱会限制部分 Node 原生文件系统调用；在受控环境提升后复跑，并将两次结果分别记录，不要将沙箱失败改写为测试通过。

## 禁止用于真实学习数据的命令

`scripts\reset-today.cmd` 会重置今日学习相关数据；演示/测试用 shift、graduate-demo 和 seed 命令也可能改变业务状态。仅可在可丢弃隔离数据库使用。任何恢复、迁移、重置或种子操作都应先有经验证备份和明确目标确认。
