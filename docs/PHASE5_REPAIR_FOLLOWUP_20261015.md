# Phase 5 验收问题修复跟进

日期：2026-10-15  
当前结论：`PHASE5_PRODUCT_ACCEPTANCE_INCOMPLETE`

## 修复内容

- 将受历史 `PracticeItem` 绑定的题目测试改为验证不可变 `QuestionVersion`：旧练习继续解释旧版本，新审核只对新版本生效。
- 调整过时测试夹具，使未正式审核的公共题明确被挡在新练习与严格证据之外；测试不再把历史题记录、AI一致性或旧来源声明当作当前正式资格。
- 迁移前置校验补齐 f52/f53/f54 兼容链，当前 f54 Schema 可通过只读漂移核验。
- 旧答案验证事件被明确撤销时，版本读取投影不再暴露该事件为当前有效凭据。
- 浏览器测试题库夹具改为复用 `prepare_e2e_learning`，在隔离库中给合成测试题建立版本绑定与 TEST_FIXTURE 毕业题集；不写入真实库、不代表真实人工审核。
- 修正状态矩阵的空资料搜索用例：显式 stub 当日个人资料搜索会话和空消息，避免读到同一测试日先前浏览器用例留下的会话。

涉及主要文件：

- `backend/services/question_versions.py`
- `scripts/migrate_graduation_policy_semantics.py`
- `scripts/run_question_repair_pilot.py`
- `scripts/prepare_phase45e_browser.py`
- `frontend/e2e/state-matrix.spec.ts`
- 多个题目版本、毕业资格、历史学习和Agent集成测试夹具

## 本轮验证

- 题目版本、判题、毕业、历史学习与Agent相关回归：119/119 通过。
- 毕业边界及旧库存兼容回归复跑：25/25 通过。
- 生题/教学质量边界单元测试：45/45 通过。
- 浏览器答题提交流程：13/13 通过。
- 浏览器聊天流程：12 通过，1 项按条件跳过。
- 导航、学习进展、状态矩阵、历史、题目来源和学习范围浏览器组：64/64 通过。
- 当前完整 Playwright 套件：第一次运行 211 通过、1 失败、7 跳过（219 项）。唯一失败为状态矩阵测试继承当日资料搜索历史；修复后该完整矩阵 29/29 通过。**修复后未再次重跑整套 219 项**，因此不把抽样复跑写成完整套件全绿。
- 前端 `npm run typecheck` 通过；Python 修改文件 `py_compile` 通过；`git diff --check` 无空白错误（仅提示仓库既有 CRLF/LF 差异）。
- 测试均由隔离 PostgreSQL runner 执行；各次 runner 结果均记录 `original_cluster_touched: false`，临时实例已停止并回收。

完整浏览器首次运行日志：[playwright.log](../storage/quality-audits/phase5-repair-browser-full-20261015/playwright.log)  
修复后状态矩阵日志：[playwright.log](../storage/quality-audits/phase5-repair-browser-state-matrix-final-20261015/playwright.log)  
核心后端回归日志：[pytest.log](../storage/quality-audits/phase5-repair-core-regression-final2-20261015/pytest.log)  
单元边界日志：[pytest.log](../storage/quality-audits/phase5-repair-unit-boundaries-20261015/pytest.log)

## 尚未完成的验收

- 后端全量 pytest 在全部修复后尝试重跑，但近 10 分钟仅到约 10%；为避免无效长时间占用而中止，没有全量最终结果。该次测试只运行在临时隔离 PG18 集群；中止后确认服务已停止，并清理了该次运行专属临时目录。日志保留在 [pytest.log](../storage/quality-audits/phase5-repair-backend-full-final-20261015/pytest.log)，不能将进度片段当作全量通过。
- Docker Engine 不可用，Compose 容器 build/up、卷持久化和容器内端到端没有完成。
- 本轮未连接真实开发库，未执行迁移、写入、恢复或同步；未发起付费模型请求。

因此 Phase 5 仍未达到产品验收完成状态。下一步应在有可用 Docker Engine 的环境完成容器验收，并安排一次完整后端回归；本次修复没有改变毕业算法、毕业策略、历史学习证据或真实开发库数据。
