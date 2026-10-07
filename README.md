# 自适应考研学习知识库

面向考研数学二与计算机 408 学习场景的全栈学习应用。公开快照包含应用源码、数据库迁移、常规自动化测试、配置模板和通用内置讲解材料。

## 主要功能

- 知识树与专题讲解
- 今日练习、作答记录与学习安排
- 个人资料上传、索引、检索和阅读
- 基于内置讲解或用户资料的问答
- FastAPI 后端、Vue 前端与 Docker Compose 部署

## 技术栈

Vue 3、TypeScript、Vite、FastAPI、SQLAlchemy、Alembic、PostgreSQL、Chroma、Sentence Transformers、pytest、Vitest、Playwright。

## 本地运行

部署和开发说明见 [docs/deploy-local-docker.md](docs/deploy-local-docker.md)。复制环境变量模板前请先检查并替换本机数据库口令；不要把实际密钥、数据库或用户资料提交到 Git。

## 公开数据边界

本公开快照不包含历年原卷、真题题干与答案题库、题源索引、私人上传资料、RAG/Agent 评测语料、评测快照或逐条评测输出。运行内容相关流程时，请自行准备有权使用的数据并保存在本地忽略路径中。
