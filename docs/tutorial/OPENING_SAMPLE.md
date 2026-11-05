# 第1天 · 开篇试读：先让我们的学习系统接住第一个请求

项目：《自适应考研学习知识库——AI应用开发实战》  
建议用时：30–45分钟。这里只是第一天的开头，不是第一天全部内容。

## 1. 今天先不接DeepSeek，我们先解决什么？

想象你是一名考研学生。你打开软件，准备上传一份高数资料，再问：“这一章的定积分应该怎么复习？”

这句话最终要交给模型，但浏览器不能自己承担所有工作。谁保存资料？谁读取学习记录？谁检查模型生成的计划有没有超过你的20分钟？这些事情需要后端。

因此，我们先让后端接住一个最简单的请求：**“服务启动了吗？”**

不要小看这个接口。以后页面打不开时，我们先用它区分：是前端没启动，还是后端根本没有响应。

这一节只验证HTTP服务，不连接数据库、不下载模型、不发送收费请求。数据库和检索是否正常，要等后续接入后分别检查；不能返回一个“ok”就宣称整个AI系统可用。

## 2. 先看我们要走通的路线

```text
浏览器访问 /api/health
    ↓
Uvicorn接收HTTP请求
    ↓
FastAPI根据路径和请求方法找到函数
    ↓
函数返回Python字典
    ↓
FastAPI把字典转换成JSON
    ↓
浏览器显示结果
```

现在没有业务查询，因此不为了画满架构图，强行添加Service、Repository和数据库。等功能真的需要这些职责时，我们再引入。

## 3. 创建独立的练习项目

不要在原项目上清空文件重写。打开PowerShell，执行：

```powershell
Set-Location ([Environment]::GetFolderPath('Desktop'))
New-Item -ItemType Directory -Path 'kaoyan-rebuild'
Set-Location -LiteralPath 'kaoyan-rebuild'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install fastapi==0.141.1 uvicorn==0.52.4
New-Item -ItemType Directory -Path 'backend'
```

这里使用当前项目Windows依赖记录中的版本，方便对齐课程。命令需要联网下载Python包，但不会调用AI模型。如果`kaoyan-rebuild`已经存在，先检查里面是什么，不要覆盖已有练习。

虚拟环境可以理解为“这个练习项目自己的Python工具箱”。后续直接使用它的python.exe，不需要修改PowerShell执行策略，也不会把依赖装进原项目。

## 4. 创建三个文件，写下完整代码

用编辑器打开刚才的kaoyan-rebuild目录。完成后的结构应为：

```text
kaoyan-rebuild/
├── .venv/
└── backend/
    ├── __init__.py
    ├── app.py
    └── main.py
```

**首先创建backend/__init__.py，完整内容如下：**

```python
"""学习系统后端包。"""
```

**然后创建backend/app.py，完整内容如下：**

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    """统一组装应用，后续会在这里接入路由和生命周期。"""
    app = FastAPI(title="自适应考研学习知识库", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        # 此时只验证HTTP链路，不能假装数据库或模型已经就绪。
        return {"status": "ok", "scope": "http_only"}

    return app
```

**最后创建backend/main.py，完整内容如下：**

```python
from backend.app import create_app

# 给启动服务器提供一个明确入口；这里不迁移数据库或调用模型。
app = create_app()
```

## 5. 这几行代码为什么这样组织？

先看create_app。它不处理用户问题，而是负责“组装一个应用”。返回值FastAPI告诉我们：调用这个函数，会得到一个可以交给服务器运行的应用对象。

为什么不把所有代码都塞进main.py？因为后面还要接资料上传、聊天、学习计划等路由。把组装和启动入口分开，更容易在测试时创建新的应用。这不是为了分层而分层，而是避免入口文件逐渐承担所有职责。

再看@app.get。它不是立即执行health，而是在应用中登记一条规则：“收到GET /api/health时，执行下面这个函数。”GET适合读取状态，本节没有创建计划或保存作答，所以不能顺手在这里写入业务数据。

health返回的是字典，不是自己拼接的JSON字符串。FastAPI负责序列化；dict[str, str]说明这里的键和值都是字符串。它不是完整的业务校验方案，后面有复杂输入输出时还会引入Pydantic模型。

现在用普通def，是因为函数只返回内存中的小字典。async不是让代码自动变快的开关，后面遇到网络等待和流式响应时，再结合实际调用方式学习。

这与原项目backend/main.py → backend/app.py的入口关系一致，但只是逐步实现的起点。正式项目的health还检查数据库、检索栈等能力，后续会扩展并拆出APIRouter；本节没有冒充已经实现这些功能。

## 6. 启动，亲眼看见第一次返回

仍在kaoyan-rebuild根目录执行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 18080 --reload
```

backend.main是模块位置，冒号后面的app是main.py中创建的变量。18080用于练习，避免占用原产品常见端口；--reload只用于开发，保存代码后会重新加载。

保持这个终端运行，浏览器打开：

```text
http://127.0.0.1:18080/api/health
```

应看到以下JSON，空格和排版不同不影响结果：

```json
{"status":"ok","scope":"http_only"}
```

再打开http://127.0.0.1:18080/docs，你会看到FastAPI自动生成的接口页面。展开GET /api/health，点击Try it out，再点击Execute，检查响应码为200。

## 7. 如果没有成功，先按顺序排查

| 现象 | 先检查什么 |
|---|---|
| 浏览器无法连接 | 终端是否还运行、是否启动报错、地址端口是否是18080 |
| 404 Not Found | 路径应是/api/health；访问根路径/出现404在本节是正常的 |
| 405 Method Not Allowed | 本接口只支持GET，不是POST |
| No module named backend | 是否在kaoyan-rebuild根目录启动，是否创建了backend目录 |
| No module named fastapi | 是否使用.venv中的python.exe安装并启动 |
| 端口占用/WinError 10048 | 不要结束不认识的进程；改用18081，并同步修改浏览器地址 |
| 500 Internal Server Error | 先看后端终端的异常栈，定位自己写错的行，而不是反复刷新 |

本节没有请求参数，所以不设计422场景；也没有环境变量、数据库、模型或SSE，相关报错不应该在本节凭空出现。后面接入这些能力时，会分别给出复现方法和排查步骤。

## 8. 怎么判断这一小节真的学会了？

- 能从空目录启动自己的服务，而不是启动原项目。
- 浏览器和/docs都能调用接口，响应为200。
- 能指出请求路径在哪登记、函数返回什么。
- 关闭服务器后访问失败，重新启动后恢复；知道这里还没有任何数据持久化。

**面试官可能会问：**

1. **FastAPI和Uvicorn有什么区别？**前者组织应用、路由和数据契约，后者是运行ASGI应用的服务器；写好路由不等于进程已经监听端口。
2. **为什么保留create_app？**把应用组装与启动入口分开，便于管理后续资源和构造测试应用；但它不会自动保证数据库隔离。
3. **为什么这个接口不能证明RAG正常？**它没有访问数据库、模型和索引，只证明HTTP请求链路能返回。后续健康检查必须分别反映各依赖的真实状态。

到这里，我们没有“做完后端”，但已经走通了第一条可以验证的链路。下一小节才引入配置和请求数据校验，接着建立独立数据库连接；不会突然把一整套最终源码扔给你。
