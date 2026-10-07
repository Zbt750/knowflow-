# Docker Compose 部署说明

本文档描述本地部署（不涉及公网/云）。**当前验证状态：见文末「验证状态」一节** ——
配置已完成并通过静态校验，但本机没有安装 Docker，因此**尚未真实执行过 `docker compose up`**。

## 前置条件

| 组件 | 要求 |
|---|---|
| Docker Engine | 24+（含 `docker compose` v2 子命令） |
| 可用磁盘 | 至少 6 GB（Postgres 卷 + 向量库 + 前端镜像；装向量依赖时另外需要约 3 GB） |
| 内存 | 建议 4 GB 以上（embedding 模型加载时约需 1 GB） |

## 快速开始

```bash
# 1) 准备环境变量（真实密码只写在 .env.compose，该文件已被 .gitignore 忽略）
cp .env.compose.example .env.compose
# 编辑 .env.compose：至少把 POSTGRES_PASSWORD 改成自己的强密码

# 2) 构建并启动
docker compose --env-file .env.compose up --build

# 3) 打开浏览器
#    http://127.0.0.1:8080
```

数据库迁移与种子数据由后端容器启动脚本自动完成（`alembic upgrade head` + `scripts/seed.py`），
都是幂等的，重复启动不会产生重复数据。

## 启用向量检索（可选但推荐）

默认构建**不装** `torch`/`sentence-transformers`：它们体积大、构建慢，而缺少它们时
系统仍然可用 —— 学习闭环、知识树、资料上传解析都正常，只有检索接口会明确返回
`503 retrieval_unavailable`，不会假装成功。

启用步骤：

```bash
# 1) 让镜像安装向量依赖
#    在 .env.compose 里设置 INSTALL_EMBED=1
docker compose --env-file .env.compose build --no-cache backend

# 2) 把本机已缓存的模型放进卷（离线环境必须做这一步）
#    Windows PowerShell：
#    $vol = docker volume inspect 考研跑通项目_storage_data --format '{{.Mountpoint}}'
#    然后把它替换成下面的 <VOLUME_PATH>
docker run --rm -v 考研跑通项目_storage_data:/app/storage -v "$env:USERPROFILE\.cache\huggingface\hub:/src:ro" alpine sh -c "mkdir -p /app/storage/models/hub && cp -r /src/* /app/storage/models/hub/"

# 3) 重启后端
docker compose --env-file .env.compose up -d backend
```

模型目录布局要求如下（`MODEL_CACHE_DIR=storage/models`，HuggingFace 缓存根为 `storage/models/hub`）：

```
storage/models/hub/
  models--BAAI--bge-small-zh-v1.5/
    blobs/  refs/  snapshots/  trees/
```

> 能联网时可以在 `.env.compose` 里把 `HF_HUB_OFFLINE` 与 `TRANSFORMERS_OFFLINE` 设为 `0`，
> 让容器自己下载模型（首次启动会明显变慢）。

## 常用操作

```bash
# 查看状态
docker compose ps

# 看后端日志（含迁移与种子输出）
docker compose logs -f backend

# 只重建后端
docker compose --env-file .env.compose build backend
docker compose --env-file .env.compose up -d backend

# 停止（保留数据卷）
docker compose down

# 停止并清空数据（数据库 + 上传文件 + 向量库全部删除，不可恢复）
docker compose down -v
```

## 架构与端口

```
浏览器 ──:8080──> frontend(Nginx)
                     ├── /            静态文件（Vue 构建产物）
                     └── /api/  ────> backend(FastAPI :8000)
                                          ├──> db(Postgres :5432)
                                          └──> storage 卷（上传件 / Chroma / 模型缓存）
```

只有前端端口对外暴露；后端与数据库都在 Compose 内网，不映射到宿主机。

## 卷与数据

| 卷 | 内容 | 删掉会怎样 |
|---|---|---|
| `db_data` | PostgreSQL 数据目录 | 知识点、题库、学习进度、资料记录全部丢失 |
| `storage_data` | 上传的原文件、Chroma 向量库、模型缓存 | 资料文件与向量索引丢失；向量库可由资料重建，但上传的原文件不可恢复 |

**Chroma 是可重建的派生索引，PostgreSQL 才是正文权威副本。** 因此向量库损坏时，
在资料页点「重建索引」即可恢复，不需要重新上传文件。

## 与本地开发的区别

| 项目 | 本地开发 | Compose 部署 |
|---|---|---|
| 数据库 | 项目内独立集群（端口 5433，trust 认证） | 容器内 Postgres 16（密码认证，不对外暴露） |
| 后端端口 | 8000（直接访问） | 8000（仅内网；通过 8080 的 `/api` 访问） |
| 前端 | Vite 开发服务器（5173，带 HMR） | Nginx 静态文件 + 反向代理 |
| 迁移 | 手动 `alembic upgrade head` | 容器启动时自动执行 |
| 模型缓存 | `storage/models`（本机已就绪） | `storage_data` 卷（需按上文准备） |

## 验证状态

| 检查项 | 状态 |
|---|---|
| 部署配置静态校验（`python scripts/check_deploy_config.py`） | ✅ 通过（COPY 源、卷、健康检查、LF 行尾、nginx 变量等） |
| `docker compose config` 语法校验 | ❌ 未执行（本机无 Docker） |
| `docker compose up --build` 真实启动 | ❌ 未执行（本机无 Docker） |
| 容器内四页可达与主流程 | ❌ 未执行（本机无 Docker） |

**未验证的部分不会被说成已验证。** 在有 Docker 的机器上首次执行时，最可能出问题的地方是：

1. `INSTALL_EMBED=1` 时 `torch` 的下载体积与耗时；
2. 离线模型目录布局（必须严格是 `hub/models--<org>--<name>/...`）；
3. `postgres:16-alpine` 与 `postgres:18` 生成的 `db_data` 卷**不兼容**；如果你之前用 18 建过卷，需要先 `docker compose down -v`。
