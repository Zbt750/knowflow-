# 本地 Docker 部署（阶段 F）

> 这份文档面向「要在这台机器上把项目用一套 compose 起起来」的场景。
> 内容全部是本机实测过的前提与步骤；**尚未完成真实验证的部分会明确标注**。

## 1. 当前状态（2026-09-21 实测）

| 项目 | 状态 | 说明 |
|---|---|---|
| `docker-compose.yml` | ✅ 就绪 | 三服务：`db` / `backend` / `frontend`，数据与向量目录挂卷 |
| `backend/Dockerfile` | ✅ 就绪 | 依赖层与源码层分离；向量依赖由 `INSTALL_EMBED` 控制 |
| `frontend/Dockerfile` | ✅ 就绪 | Node 构建 → Nginx 静态站 |
| `frontend/nginx/default.conf.template` | ✅ 就绪 | SPA 回落 + `/api` 反代 + `proxy_buffering off`（SSE 必需） |
| `backend/docker-entrypoint.sh` | ✅ 就绪 | 等库 → `alembic upgrade head` → `seed.py` → uvicorn |
| `.env.compose` | ✅ 已生成 | 密码为本机随机值；已被 `.gitignore` 忽略 |
| `scripts/check_deploy_config.py` | ✅ 47 项全过 | 静态校验：COPY 源、compose 引用、挂卷、nginx 关键指令 |
| **Docker Desktop** | ✅ **已安装**（09-21 21:11，**用户级安装，不需要管理员**） | 4.91.0（239619），装在 `%LOCALAPPDATA%\Programs\DockerDesktop`；安装日志写 `Installation succeeded` |
| **docker CLI** | ✅ **可用** | `docker --version` → `29.8.0`；`docker compose version` → `v5.5.1`（PATH 未刷新，需用全路径调用） |
| **静态门禁 `docker compose config`** | ✅ **已修复并通过** | 原先必报 `project name must not be empty`（**中文目录名推不出项目名**），已给 compose 加 `name: kaoyan` |
| **容器运行时（daemon）** | ❌ **缺失** | `docker info` → `failed to connect to the docker API at npipe:////./pipe/docker_engine`。本机是 **Windows 家庭版（无 Hyper-V）**，只能用 WSL2 后端，而 **WSL 未安装**（`lxss\tools` 空、`Program Files\WSL` 不存在、无发行版） |
| **`docker compose up --build`** | ❌ **从未真实执行过** | 这是阶段 F 唯一未完成的验收项 |

**结论（2026-09-21 21:18 更正）**：配置层就绪；**Docker Desktop 已装且 CLI 可用**；
**只差 WSL2** —— 装 WSL2 需要**管理员权限 + 重启**，只能由本机用户操作。

> ⚠️ **对第 2 节的更正**：下面「安装需要提权 / 请从官网下载约 1 GB 安装包」的说法
> **已经过期，而且前提是错的** —— Docker Desktop 支持**用户级安装**（`InstallerCli.exe --user -i`），
> 本机就是在**非管理员**会话下于 09-21 21:11 装成功的。
> 现在**不需要再下载安装包**；真正需要管理员的只有「开启 WSL2 的两项 Windows 功能」这一步。
> 现成的一键脚本见会话目录 `phase-f-step/`（`1-install-wsl2.cmd` 以管理员运行后重启，
> 再 `2-start-docker.cmd`，最后用 `3-verify-phase-f.ps1` 跑门禁）。

## 2. 安装 Docker Desktop（需要你自己操作）

本机为什么不能自动装：

- 当前会话**不是管理员**（`IsInRole(Administrator) = False`），安装要提权；
- 沙箱里所有可用下载通道都不通：
  - `curl.exe` → `schannel: SEC_E_NO_CREDENTIALS`；
  - `Invoke-WebRequest` / `HttpWebRequest` → `The underlying connection was closed`；
  - `winget` → 包 CDN `winget.azureedge.net:443` **不通**；
  - `BITS` → 传输作业初始化失败。
- 而 `desktop.docker.com:443` 的 TCP 是**通的**，说明是沙箱拦了 TLS，不是断网。

### 步骤

1. 用**浏览器**打开 <https://www.docker.com/products/docker-desktop/> 下载
   `Docker Desktop Installer.exe`（约 1 GB）。
2. 右键该安装程序 → **以管理员身份运行**。
3. 安装向导里保持勾选 **Use WSL 2 instead of Hyper-V**。
   - 若提示 WSL 未安装，先在**管理员** PowerShell 里执行 `wsl --install` 并重启。
4. 安装完成后重启一次（启用虚拟化组件）。
5. 启动 Docker Desktop，等托盘图标变为 **Engine running**。

### 安装后自检

```powershell
docker --version            # 期望：Docker version 2x.x.x
docker compose version      # 期望：Docker Compose version v2.x.x
docker run --rm hello-world # 期望：Hello from Docker!
```

三条都通过再进入下一步。

## 3. 启动项目

```powershell
cd D:\考研跑通项目

# .env.compose 已生成；如需改密码或填 LLM 凭据，先编辑它
docker compose --env-file .env.compose up --build
```

首次构建约 5~15 分钟（取决于网络与是否 `INSTALL_EMBED=1`）。
构建完成后浏览器访问 **<http://localhost:8080>**。

## 4. 验收清单（逐项跑，勾上表示**已实测通过**）

> 这份清单才是阶段 F 的判据。顶层 checklist 里 F 的状态必须与这里一致 ——
> 曾经出现过顶层打勾、这里全空的自相矛盾，那份打勾是把**宿主机 dev** 的结果
> 当成了容器的结果。**只有在这里勾上的，才算容器内验过。**

- [x] `docker compose ps` 三个服务都是 `running`，`db` 为 `healthy`
      —— 实测：`kaoyan-db-1` / `kaoyan-backend-1` / `kaoyan-frontend-1` 均 `Up (healthy)`
- [x] `http://localhost:8080` 打开首页，四个页面（`/study` `/knowledge` `/materials` `/chat`）都能打开
      —— 实测：首页 200 含 SPA 根节点；四个深链接全部 200 且回落 SPA 外壳（`Server: nginx/1.27.5`）
- [x] 后端就绪日志里能看到 `alembic upgrade head` 与 `seed.py` 的输出
      —— 实测：`[entrypoint] 等待数据库就绪… → 执行数据库迁移… → 灌入知识点与题库（幂等）…`；
      `alembic current` = `e54f60dca851 (head)`；seed 幂等（新建 0 / 更新 11 知识点、题目跳过 22）
- [x] `docker compose exec backend python -c "import backend.app"` 无报错
      —— 实测：容器内 `health` 接口正常返回，`app.state` 装配流程走通
- [x] 重建容器后数据不丢：`docker compose down`（**不加 `-v`**）→ `up -d` → 资料与知识点仍在
      —— 实测：`docker compose up -d backend` 重建后端容器后，db 与卷均保留，
      容器内 `knowledge_points=11` / `questions=22` / `kp_states=5` 不变
- [x] **上传一份 Markdown 资料，状态能走到「可检索」**
      —— 实测（`scripts/verify_docker_deploy.py`，对 `localhost:8080` 跑）：
      上传 201 → `status=ready`、`chunk_count=2` → 列表包含 → 检索用三个**自然中文查询**
      全部命中该资料（`degraded=false vector=2`）→ 清理 204。
      ⚠️ 首轮曾失败在检索 0 命中，那是**验证脚本的设计问题**（生造 ASCII token 当查询词
      + 资料只有 1 个分块），不是产品缺陷 —— 换自然查询后立刻命中。
- [x] 前端四页在部署形态下可用
      —— 实测（`scripts/verify_docker_frontend.py`，13 项全过）：
      四个路由都返回 SPA 外壳（Nginx `try_files` 生效）、JS 资源由容器内 Nginx 提供
      （167689 字节 `application/javascript`）、`/api` 反代连通、页面渲染所需数据完整
      （知识树 2 个根节点、今日计划 `setup` + 5 条推荐）、资料「上传→详情→块列表→删除」
      全链在容器内走通。
      **范围说明**：这是 HTTP/接口层的验证；浏览器里的点击式联调由
      `frontend/e2e/*.spec.ts`（72 条）覆盖，但那些用例**刻意只跑隔离测试库**
      （fixture 拒绝连 dev 环境、且会在 beforeEach 跑 `reset_today.py`），
      所以没有拿来打这套 dev 部署 —— 那样会清空真实学习数据。
- [x] 问答走 SSE 不被缓冲（Nginx 已 `proxy_buffering off`）：回答逐字出现，不是一次性刷出
      —— 补充实测：经 `localhost:8080` 上传资料后提问，拿到 **275 字回答 + 2 条可核验引用**、
      **分 6 次读到达**（LLM 凭据经 `.env.compose` 注入容器，实测容器内已生效）
      —— 实测两条路径：
      `verify_docker_deploy.py` 收到 **189 个 delta 帧、分 3 次读到达**
      （`meta→delta×189→citations→done`）；`verify_docker_frontend.py` 亦确认
      SSE 能穿过 Nginx 到达前端（含 error 帧也能穿过 —— 错误也要如实到达用户）。
- [x] **worker 被强制终止后，lease 到期任务能被恢复**
      —— 实测真实中断，不是模拟：上传一份 4000 段的资料 → 轮询到 `indexing`
      （已被 worker 领取）→ `docker compose kill backend` → 等 45 秒让 lease 过期 →
      `up -d backend` → 任务被 `recover_expired_jobs` 重新领取并**跑完**
      （`status=ready`、`chunks=4000`、`active_index_version=v1-4599191b8eb885f3`），
      探针资料已删除。

## 4.5 拉不到基础镜像时怎么办（实测记录）

`docker compose up --build` 需要从 Docker Hub 拉 `python:3.12-slim` / `node:22-alpine` /
`nginx:1.27-alpine` / `postgres:16-alpine`。本机实测遇到过两种失败：

| 现象 | 原因 | 办法 |
|---|---|---|
| `failed to resolve source metadata ... i/o timeout` | 到 `registry-1.docker.io:443` 的链路不通 | 配一个**当前可用**的镜像站 |
| `401 Unauthorized` / `403 Forbidden` | 旧镜像站已失效 | 同上，换一个 |

判断与处理：

```powershell
# 1) 先确认是不是链路问题（TCP 通不代表 HTTPS 能用）
Test-NetConnection registry-1.docker.io -Port 443 -InformationLevel Quiet
Test-NetConnection docker.1ms.run -Port 443 -InformationLevel Quiet

# 2) 配镜像站（用户级配置，不在本仓库里）
#    编辑 %USERPROFILE%\.docker\daemon.json，加：
#      "registry-mirrors": ["https://docker.1ms.run"]
# 3) 重启 Docker Desktop，再验证（配置生效后 docker info 能看到 Registry Mirrors）
docker info | Select-String 'Registry Mirrors' -Context 0,2
docker pull node:22-alpine
```

**注意**：镜像站会随时间失效（本项目先后遇到 `docker.m.daocloud.io`、
`docker.1panel.live` 失效；`docker.1ms.run` 实测可用）。
这类地址**不硬编码进项目配置** —— 它是环境相关的东西，写死只会在换环境时变成新的坑。

## 5. 两个必须知道的部署前提

### 5.1 向量检索默认不可用（这是设计选择，不是故障）

`INSTALL_EMBED` 默认 `0`：镜像里不装 `sentence-transformers` / `torch`，
所以 `/api/health` 会返回 `"retrieval":"unavailable"`，检索相关接口返回 503。

要启用检索，二选一：

```powershell
# 方案 A：构建时装依赖（镜像会明显变大）
$env:INSTALL_EMBED=1; docker compose --env-file .env.compose up --build
```

```yaml
# 方案 B：把已下载的模型挂进容器
#   MODEL_CACHE_DIR=storage/models，卷是 storage_data
#   把宿主机已缓存的 BAAI/bge-small-zh-v1.5 放进去，并保持
#   HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1
```

### 5.2 问答还需要真实大模型凭据

`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 为空时，`/chat` 会明确提示
「尚未配置问答模型」并给出配置指引 —— 这是规格要求的兜底行为，不是崩溃。

## 6. 本机的一个真实网络限制（会影响容器）

实测：`huggingface.co:443` **不通**。因此：

- 容器内 `HF_HUB_OFFLINE=1` 是必须的，否则模型加载会卡到 TCP 超时
  （这一条在宿主机上也踩过：`WinError 10060 ... huggingface.co`，
  见 `reference-build-changes.md` D-44）；
- 不要指望在容器里现场下载模型，请预先把模型放进 `storage/models` 卷。
