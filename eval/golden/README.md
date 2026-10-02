# P1 · Golden Learning Slice

这是两个小型原创合成专题，不是全数学二/408题库，也不是考研真题合集。

- 定积分的计算：`math.exam.c431f98f817c`，8 道候选题。
- 二叉树基础（性质+存储）：`cs408.ds.topic.1efaf3d00b50`，8 道候选题。

版本化资产为 `integral_binary_tree_v1.json`。13 道拟用现有单选/数值最终答案比较器，3 道不自动判分。全部候选题六项审核状态为 GENERATED，两份讲解为 UNVERIFIED；自动检查通过不能晋级 VERIFIED。

## 离线检查

在项目根运行：

```powershell
python scripts/audit_golden_learning_slice.py
python scripts/audit_golden_learning_slice.py --review-sheet eval/golden/review-copy.md
python -m pytest tests/unit/test_golden_learning_slice.py tests/integration/test_golden_learning_slice.py -q
```

审核清单拒绝覆盖旧文件。审计退出码 0 只表示结构与有限判题探针通过；须另读 `release_ready` 和 `human_review_complete`，不能把退出码当成发布许可。

检查使用现有年度节点索引确认编号/名称/科目，讲解绑定实际文件 SHA256；不会访问数据库、模型或用户资料。集成测试另外使用受 APP_ENV=test 保护的隔离数据库及离线协议替身，其“human”审核为明确标注的 SIMULATED 测试声明，绝不保存回候选资产或开发库。

## 人工核验与导入

每题必须分别审核 `source / stem / answer / explanation / mapping / grading`。审核标准包括：发布来源是否明确、题意及选项是否唯一、条件是否完备、答案及解析是否正确、是否真正属于该节点，以及最终答案能证明什么、不能证明什么。

只有真实人工审核后，才将对应 review 设为 VERIFIED，并填写 `reviewer_kind=human`、真实 `reviewed_by`、`reviewed_on`、`note` 与该题的 `content_sha256`。哈希覆盖内容、来源和测试探针，不含审核声明。任一字段修改后必须重新审核，不得复制旧哈希。讲解须另按当前文件哈希记录审核。脚本**没有**自动打 VERIFIED 的选项。

审核记录是受信任维护者的人工声明，不是身份认证：填写字符串不能证明是谁审核、也不能保证内容正确，不接受 LLM 自称 human 的结果作为审核。

完整人工审核和结构检查通过后：

```powershell
python scripts/audit_golden_learning_slice.py reviewed-slice.json --export-reviewed reviewed-pack.json
python scripts/import_reviewed_questions.py reviewed-pack.json
# dry-run 及原引用节点的在线毕业策略审核确认后，才显式 --apply。
```

导出和导入复用已有 `QuestionPack`，不新建判题器、Agent 或掌握度算法；导入器不改旧作答、毕业状态或引用节点策略。候选内容位于 eval/golden 而不是 seed/questions.json，不会被默认种子脚本导入。

独立多项式积分、节点计数和遍历算法只验证这组有限样例的结果；不能验证任意表达式、证明过程、伪代码可运行性、耗时估计或全部知识映射。证明、符号答案和算法题保留 unknown，不伪造客观掌握证据。P2 的完整同题尝试序列和提示分级不是本阶段交付。
