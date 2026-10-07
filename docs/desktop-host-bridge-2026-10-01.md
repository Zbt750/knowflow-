# 桌面后端与前端启动桥接（2026-10-01）

本轮把上一轮独立目录原型接成可运行的本地后端：同一 HTTP 端口提供现有 API 和构建后的前端，无需 Vite。不是 Electron 安装包；不初始化、迁移、复制或删除数据库。

## 实现范围

- `scripts/run_desktop_backend.py`：显式资源目录、用户数据父目录、端口及 `DESKTOP_DATABASE_URL`；默认 18750，只监听 127.0.0.1，禁用代理头信任。`--check` 只读预检，不连接数据库或创建用户目录。实际运行要求已有、已迁移的 PostgreSQL。
- `desktop/server.py`：启动前拒绝远程/带查询覆盖参数的数据库 URL、缺失前端构建、非法端口和资源符号链接。不得在错误输出中回显连接串。
- 设置目录接入 LocalAppData/KaoyanStudy（或显式测试目录）；上传、Chroma、模型缓存、模型设置与安装资源分离。保留既有 Windows DPAPI 模型配置，不复制旧开发密钥。
- `APP_RUNTIME_PROFILE=desktop` 时 `get_settings()` 不读工作目录 `.env`；启动器删除该子进程继承的 LLM 配置、测试 URL，并禁止证据原文捕获，不影响父进程、Web 服务或用户 `.env`。普通 Web 的配置行为不变。
- 默认 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，不会首次启动偷偷下载模型。模型缓存不完整时按现有降级行为报告检索不可用，不能标为离线问答验收通过。
- SPA 白名单仅覆盖现有页面与知识讲解深链接；未知 API、缺失资产或私有文件路径不返回成功 HTML。API 路由优先，静态服务只暴露 dist；静态资产限制类型并禁止越界符号链接。
- 桌面专用中间件对全部路径验证精确 Host/端口、loopback peer、Origin、Sec-Fetch-Site 和代理头；静态响应附 CSP、nosniff 和 Referrer-Policy，入口页面不缓存。
- 资源清单补充 desktop Python 模块，但仍是源码清单，不是完整依赖包。

技术依据：[Starlette StaticFiles](https://www.starlette.io/staticfiles/) 的 `follow_symlink=False` 和 [Uvicorn 参数说明](https://www.uvicorn.org/settings/) 的监听与代理头选项。实际安全边界仍须依靠本项目参数和回归，不能只凭引用文档视为安全验收。

## 开发预检与启动

先构建前端，再向**当前进程**提供专用、本机 PostgreSQL 连接串；不要把真实连接串写进代码、命令截图或构建记录。

```powershell
# 在 frontend 内执行 npm run build，回到项目根。
# DESKTOP_DATABASE_URL 由后续数据库 supervisor 提供；本原型不自动读取 .env。
python scripts/run_desktop_backend.py --resources "D:\考研跑通项目" --check
# 预检通过且专用数据库已迁移/准备后，才实际启动：
python scripts/run_desktop_backend.py --resources "D:\考研跑通项目"
```

`--resources` 必须是绝对目录，含 frontend/dist/index.html；`--local-app-data` 默认来自 Windows LOCALAPPDATA，最终数据目录追加 KaoyanStudy。实际启动可能连接和恢复指定数据库中的生成占位，不能把生产或开发连接串随手用于测试。不存在可迁移知识数据的快捷复制逻辑。

## 测试发现与修复

1. Windows StaticFiles 使用 OS 规范化，路径变为反斜杠，导致讲解深链接和资产误404：统一为 URL 分隔符并补测试。
2. 第一轮浏览器验证缺默认 Playwright 浏览器：改用项目已有 Chrome 通道，不额外下载安装或复用用户浏览器资料。
3. 真实构建中的 `_plugin-vue_export-helper` 被资产名白名单误拒，页面动态导入失败：允许下划线开头的正常资产，仍拒绝点开头的私有文件，补回归。不能把第一轮的空壳显示当作页面加载成功。

最终专项 31 项通过（桌面路由/启动/环境隔离含一条真实数据库生命周期测试）。前一阶段桌面与既有发布专项 51 项、后续含 CLI 和数据库专项 38 项也通过，数字是不同组合，不能相加当作独立用例数。

用专用临时用户目录、kaoyan_test、18751 端口启动真实桌面后端，模型未配置、缓存为空；health 正常，检索如实 unavailable。`scripts/desktop_browser_smoke.mjs` 用实际 dist 逐一打开并刷新六个路由，最终零 pageerror/console error/4xx/5xx，测试限制所有请求为同源 GET/HEAD/OPTIONS，不调用模型。测试端口已回收；临时目录保留本地诊断日志，不包含开发资料。

最终修复后后端全量 893 passed（104.55秒），原 Web 离线 Playwright 119 passed（2.9分钟）；前端30单测、typecheck/build、OpenAPI36路径四项、compileall及diff检查通过。8001和18751已回收；开发8000 health正常、5173页面200，未重启用户当前服务。资源清单530项/3413920字节，仍明确 installer_ready=false。成绩为本轮实测，不是沿用上一轮862/119。

## 尚未完成

PostgreSQL 二进制资源与专用数据库编排、首次迁移/种子初始化、后端 exe、Electron 主进程与端口/退出编排、预置模型、升级备份、安装/卸载及干净 Windows 验收。本轮不是完整安装包，不能直接发给无开发环境用户使用。图片审阅、程序 runner、真实题目核验/408 在线题以及 RAG 真实预算效果未在本轮推进或冒充完成。
