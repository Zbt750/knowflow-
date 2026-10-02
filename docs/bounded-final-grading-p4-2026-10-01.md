# P4：由黄金题需求驱动的有限最终答案判题

## 范围与取舍

继续当前工作区 P4，不重复开发 Agent、状态机、RAG 或题包导入。先审计 P1 定积分/二叉树 16 题：13 题已有精确数值/单选比较器，M07 候选答案 `ln(2)` 尚不支持，M08 为证明、T08 为算法伪代码。没有多选、矩阵或近似容差的实际题目需求，因此不为技术展示新增这些比较器。

新增 `logarithm_final` 及有限数值输入排版适配。原 P1 资产保持原样、16 题仍 GENERATED、讲解仍 UNVERIFIED、release_ready=false；新增 `eval/golden/p4-grading-proposal-v1.json` 只记录绑定原始文件 SHA256 的 M07 判题提案，不是 reviewed pack、不是核验声明，也不导入开发库。更新该题的拟用方法后必须重新计算内容哈希、重新审核，不能沿用旧审核。

这是 P4 工程能力交付，不替代黄金题的真实人工审核或发布验收。开发题库目前没有自然对数在线题；数值分数输入改进可立即供既有已核验数值题使用。

## 支持和不支持

| 配置 | 支持 | 保守边界 |
| --- | --- | --- |
| numeric_final | 整数、有限小数、单个分数；额外支持 `\frac`、`\dfrac`、`\tfrac` 的数值分子/分母及单层 `$…$` | 仍按 Fraction 精确比较；0.333 不等于 1/3。不解析一般运算、单位、变量、嵌套公式、科学计数法或根式 |
| logarithm_final | 填空/计算题的单个自然对数常量 `ln(q)`，q 为正有理数；支持 ln 2、\ln(2)、有理数参数及数值分数排版 | ln 在正数上单调，用参数精确比较。log 的底数不明确、非正数参数、变量、组合运算和近似值返回 unknown |
| logarithm_final 的特例 | ln(1)=0，可接受精确数值 0 | 不把其他自然对数常量转成浮点值 |
| 证明/讨论/算法过程 | 保留现有文字/伪代码记录与辅助审阅 | 不由新比较器确认过程正确或掌握 |

例如 ln(4/2) 与 ln(2) 为 right，ln(3) 对 ln(2) 为 wrong。数学上等价的 `ln(4)/2` 因超出此解析器范围仍为 unknown，不宣称通用符号等价。`0.693147` 不强行判错，也不算正确。输入超过 128 字符、零分母、恶意代码文本均不执行，返回 unknown；无 eval、CAS、模型调用或新依赖。

只有 config.verified 严格为 true、题型匹配、标准答案处于支持域，`available_grading_method` 才返回方法。提交与题包使用同一适用性检查。即使答案文字相同，未核验候选仍不能产生客观确认；证明题误配置自然对数方法也不自动判分。

## 复用证据与前端

新回执记录 `grading_input_version=bounded-final-input-v2`，自然对数 method 为 `exact_logarithm_v1`；原数值 method `exact_numeric_v1` 及其精确等值含义不变。保留原始输入、既有内容哈希、P2 前驱/幂等/辅助/序列约束及 P3 能力投影；不回填旧回执或重新判定旧 unknown。

正确不等于过程正确；看解析后答对不增加独立确认；错答后同题纠正仍待复测，新练习项可靠作答才可消除该题待复测。一次正确仍不等于毕业。

前端只按现有方法调整专注/整卷输入框的 placeholder；未增加公式工具栏、编辑器、卡片或页面。数值可输入 `1/3` 或 `\frac{1}{3}`，未来审核后的自然对数题提示 `ln(2)`。无可靠比较器继续建议纸上作答并记录关键结论。

## 验证

初始判题/题包专项 59 passed（0.35s），随后包含隔离 API 的专项 69 passed（20.29s）；最后另补提案与原始资产哈希及未核验状态检查，纳入最终全量。前端 typecheck、35 单测（9 文件）、build 通过；OpenAPI 漂移检查通过，仍 36 路径，无新增迁移。

隔离 PG 的 M07 fixture 明确模拟核验，不写回资产或开发库。测试实际提交、回执回放、未核验拦截、非法/空答不积累确认、解析辅助、错答→即时纠正→次日新项、P3 最终答案独立证据，以及误配置证明不确认过程。

首轮集成 7 passed / 1 failed：测试误把历史中有自行改正答对的新项成功期望为 independent_retest_correct；P2 现有契约将任何先前正确结果后的新项成功标为 repeat_correct（UI“再次答对”，不承诺先前独立）。按实际契约检查新项未辅助、待复测清除、不同题确认去重及旧回执保留后通过。没有改状态机来迁就测试，也未删除该场景。

新增专注/整卷浏览器场景走实际答案 API 验证分数排版输入、原始输入持久化及正确标记。最终后端 **1149 passed（161.25s），0 failed / skipped**；显式指定 PG18，包含隔离临时集群用例。最终浏览器 **128 passed（3.2m，JSON duration 190.559s）**，0 unexpected / skipped / flaky，退出码 0。浏览器的 LLM/SSE 场景仍为离线协议替身，不是新真实模型效果评测。

- 后端 JUnit：`eval/reports/bounded-final-grading-p4-20261001/backend-junit.xml`，SHA256 `b4ca50b72297d95e2ca50eeae2b44432906efce76c6f19be9540d06190c31b36`。
- 浏览器 JSON：`eval/reports/bounded-final-grading-p4-20261001/e2e-report.json`，SHA256 `d5ded6c51d5c29b5af7ea2c63facfb17d43edcf346b66254b4e8964d614de2c4`。
- 新开发后端已加载当前 P4 代码，health 为 dev/database connected/retrieval ready/worker running；开发 8000、5173、5433 可用。隔离测试 launcher/子进程回收，8001/5174 释放。
- 开发库只读仍 22 活动题、2673 原卷引用、13 作答、6 计划；无 invalid verified config。没有为展示新比较器写入用户题目或作答。
- P1 原始文件 SHA256 仍 `23afaed03155afdf20bd792c21c311ba9b2ace52cf2b3124bd9d200703f3b575`，审核脚本仍 structural_checks_passed=true、release_ready=false。原报告不改写，新提案只作未核验需求记录。

```powershell
python -m pytest tests/unit/grading/test_bounded_final_inputs.py tests/integration/test_p4_final_grading.py
python scripts/audit_golden_learning_slice.py
python scripts/audit_grading_coverage.py
python scripts/check_openapi_drift.py
# frontend
npm run typecheck
npm run test:unit
npm run build
# root；不要与 pytest 并行使用同一测试数据库
powershell -ExecutionPolicy Bypass -File scripts/run-e2e.ps1
```

当前来源为 HEAD c841adbbddf82c5da3103474e63d7889afaf9c7f 之上的未提交工作区，没有 reset/clean/checkout、提交或推送。真实模型、裁判调用 0，不修改 P0 评测报告、普通 RAG Prompt 或模型设置。图片/拍照识别、程序沙箱仍是独立后续能力，不在本轮冒称完成；P5 真实 Agent 对照也未提前运行。
