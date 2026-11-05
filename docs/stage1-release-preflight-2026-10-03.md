# 两个真实题切片：释放预检与闭环前置检查

本轮延续 Stage 1，不绕过真人核验进入真题 VERIFIED 释放。复用 existing graded-answer API 与六方面真人核验桥接，不增加新的 AI 功能或通用数学判题器。

## 完成的下一步

新增 `scripts/check_slice_release_readiness.py`，检查候选批次 SHA、每道题完整内容 SHA、重复身份、伪造工作单批准标记；对离线副本测试现有判题器的适用性。工作单内的所有原始 issues、题意边界和失败项保留。

脚本的 `verified=True` 仅是内存里的假设解析器测试，不写入数据库、不代表核验通过、不产生 Evidence。未核验副本全部返回 unknown。真人审核仍须走既有 `prepare_real_slice_review.py`，不能翻转工作单中的标记替代。

工作单更新为 `storage/question-intake/real-slices-20261003/derivation-review-v5.json`，新增在线题的实际 `question_type` 字段；旧 v1–v4 保留。初次预检报告存于 `eval/reports/stage1-20261003/release-preflight-v1.json/.md`；后续版本另存，不覆盖。

15 道待核验题中，10 道在当前结构/答案格式下，**假设真实核验以后**能由现有解析器识别；释放数量仍为 0。这个 10 不是可信题数量、题目质量分数或完成真实学习闭环的证据。

## 新发现的具体缺口

- 数学 2025-13 当前答案 `$-\frac14$` 不被现有 numeric_final 接受，返回 unsupported_reference。核验后的内容可显式使用 `-1/4` 或规范的带花括号 LaTeX；这是未来审核后的内容修订，不静默改开发库答案。
- 数学 2024-7 候选缺少结构化 `question_type`，当前不能启用所建议的 single_choice。它仍需完整题型、选项结构、答案和原卷核验。
- 数学 2024-19、2025-17、2026-11 的答案包含混合常量或区间，现有保守比较器适用性未成立。保留可阅读/待核验，不把 unsupported 扩大成“机器确认”。
- 408 上标转录风险、量词差异和范围映射问题仍保留，选择题比较器能比对字母并不证明选项内容真实。

## 复现

```powershell
.venv-ragas/Scripts/python.exe scripts/check_slice_release_readiness.py storage/question-intake/real-slices-20261003/derivation-review-v5.json --batch storage/question-intake/real-slices-20261003/structured-candidates-v3.json --output eval/reports/stage1-20261003/release-preflight-new.json
.venv-ragas/Scripts/python.exe -m pytest tests/unit/test_slice_release_readiness.py tests/unit/test_slice_derivation_review.py tests/unit/test_real_slice_review_bridge.py -q
```

脚本拒绝覆盖旧报告，输出只能在本地被忽略的 intake/reports 中。在线题只检查已保存快照，不能宣称报告生成时又核对过最新数据库；升级题目前必须比较当前内容哈希。

## 下一阶段边界

本轮实测：31 条相关单元/边界测试通过；`tests/integration/test_golden_learning_slice.py` 与 `test_answer_submissions.py` 合计 53 条隔离 PostgreSQL 集成测试通过，进程 exit 0；`git diff --check` 通过。集成测试使用测试库、合成黄金题、模拟审核声明和离线 Planner，不调用真实模型或向开发库写入。不是整仓全量回归，不能替代真实题审核。

释放后的三种验收继续采用：A 薄弱状态变化、B 看解析后完成不算独立证据、C 同题反复正确不无限增长确认。现有合成隔离题/离线 Planner 的接口测试只能证明事务、证据与工具协议，不证明真题可信度或真实模型决策质量。真题源版及六方面实际独立审核尚缺，因此本阶段不宣称释放或真实题闭环完成，也不新增付费模型调用。
