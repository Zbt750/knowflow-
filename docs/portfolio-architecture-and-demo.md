# 求职版架构与演示路线（冻结候选）

这是当前代码的工程说明，不是最终版本发布声明。私有题库、模型、Actual Context和历史报告不随源码克隆恢复。验收状态见 [当前收口](portfolio-closeout-2026-10-04.md)。

## 两条主链与权限边界

```text
Vue页面 → FastAPI API → SQLAlchemy / PostgreSQL
                       ├─ 资料解析/索引 → 标题树 + BM25 + Chroma → RRF/可选重排
                       │                                   ↓
                       │                          实际证据快照 → LLM → SSE/引用
                       └─ Question → Attempt Sequence → Evidence → Knowledge State
                                                               ↓
用户本次目标 → 有界Agent工具循环 → 读取状态与题池 → 校验草案 → 用户确认 → 今日卷
```

模型理解目标、选择只读工具、组织方案；后端执行参数/范围/题目/时间校验及最终写入。过程辅助意见、照片转写、用户自述不能替代客观判题。确认前可以保存任务运行和草案，但不能写练习业务数据。幂等确认不重复加题，原卷引用不是Question。

## 主要源码入口

| 链路 | 现有入口 | 要理解的设计 |
| --- | --- | --- |
| 页面与导航 | `frontend/src/router.ts`、`frontend/src/pages/` | 页面懒加载、资料阅读、作答与任务恢复 |
| 学习推荐/今日卷 | `backend/services/planning_service.py`、`practice_service.py` | 规则推荐、同日计划约束与追加；不是由模型自由写表 |
| 最终答案与尝试 | `answer_submission_service.py`、`answer_grading.py`、`attempt_service.py` | 判题适用边界、幂等提交和多次尝试 |
| 学习证据 | `backend/mastery/attempt_sequence.py`、`evidence.py`、`capability.py`、`backend/services/capability_service.py` | 独立正确、自纠、辅助、重复、unknown的差异 |
| Agent | `learning_task_service.py`、`learning_task_tools.py` | 有界循环、真实工具事实、草案与确认恢复；主Prompt v7 |
| RAG | `backend/services/retrieval_service.py`、`backend/retrieval/`、`backend/chat/service.py` | 既有三路召回及上下文预算，不重复造Pipeline |
| 实际上下文与评测 | `backend/chat/evidence.py`、`scripts/freeze_current_rag_baseline.py`、`run_isolated_chat_ragas.py` | 按本轮实际证据评估，不重新检索替换生成上下文 |
| 内容与核验 | `question_pack.py`、`question_verification_upgrade.py`、`scripts/prepare_real_slice_review.py` | 来源、内容核验与判题支持不能混成一种状态 |
| 图片与过程 | `vision_recognition_service.py`、`process_review_service.py` | 先同意，再核对；是辅助功能，不是自动判卷/OJ |

未加完整用户认证，只适合本地单用户；Docker前端只绑定回环。公网产品化需要独立权限、安全和数据隔离工作，不因API已经存在而适合公网发布。

## 安全演示顺序

1. 开发服务健康：打开今日学习、知识树、资料、问答和设置。不要展示密钥或私人文档。
2. 知识节点：阅读讲解、查看关联在线题与来源，说明待核验题可以练习，但不能形成可靠掌握确认。
3. 今日学习：树形调整范围、按题型浏览、提交、解析、再试一次。未核验题展示unknown边界，不能故意演示成机器已判对。
4. 证据对照：用隔离回归报告说明首次独立正确、自行改正、解析后完成和重复正确的差异。合成核验夹具不冒充核验过的真题。
5. 今日学习页的“安排学习”：展示草案与用户确认、原地更新今日卷交互，问答页不再保留此面板。若需要真实调用，应先获得限定数据/次数授权；普通展示可用既有浏览器回归录像/报告，不在演示中默认发起付费任务。
6. RAG报告：展示六个Actual Context校验、原四指标、低Precision和跨文件慢例；不只挑高分，不宣称全系统准确率。
7. 恢复能力：说明隔离备份恢复、幂等、失败保留与安全源码清单。展示脱敏汇总，不打开私人归档。

最终三个真实题闭环仍是验收门禁，不能用第4步工程演示替代。真实照片准确率验证可选，照片功能本身的发送同意、核对和失败保护仍须可靠。

## 冻结后的教学与Mini范围

最终课程待真实题、当前Agent和发布门禁收口后，基于明确冻结版本编写。现在只确定学习入口，不提前宣称课程完成。

Mini重建优先：一个知识点、几道明确来源与审核状态的题、提交与Attempt Sequence、简单Evidence投影、一个有界只读工具Agent、用户确认追加。再补一份资料的RAG、Actual Context和一个固定评测案例。暂不复制整个题库、视觉识别、安装包或沙箱。

面试应能回答：为什么看解析后答对不能算独立掌握；为什么模型不能改状态；如何定位文件概述漏章；为什么Precision低但Recall高；如何证明确认不重复写；如何区分源码恢复、数据恢复与完整部署复现。
