# 奶蛙个人出题：取消固定知识点白名单

日期：2026-10-17。

## 产品行为

默认的「奶蛙生成新题」现在允许选择全部有效、启用的可考核叶子知识节点，不再因为没有注册某个专用求解器就阻止该节点出题。等比级数的敛散性与求和等原先被拦截的节点使用通用个人生成通路。

支持单选、填空、计算、证明及主观分析题；算法设计、讨论等请求使用已有主观题模型。没有建立第二个题库，仍保存到 Question，并由现有不可变版本机制创建 QuestionVersion。

流程仍为：明确要求出新题 → 确认具体知识节点 → 调用已配置模型生成 → 检查 → 保存并展示 → 用户决定是否加入今日学习。保存不创建 PracticeItem，即使自然语言包含“加入今日”或旧参数 append_to_today=true，也不自动追加。

没有今日计划时，加入操作仍须经过现有前端确认；重复生成请求、重复加入保持幂等。

## 检查和证据边界

- 有兼容专用求解器的题型、难度继续复用原独立检查流程。
- 没有兼容题族的节点、题型或难度使用新通用生成通路。
- 通用题检查 JSON 结构、题干和解析完整性、选项与答案键、重复或数值等价选项、缺图缺表和占位内容、可核算等式冲突及答案/结论的可判定冲突。
- 可选独立求解器明确发现错误则拒绝；不适用或报错只如实记录，不伪造 PASS，也不再因此阻止整个知识范围出题。
- 通用题的状态记录为 `STRUCTURE_CHECKED_REFERENCE_ONLY`，不是 AUTO_VERIFIED 或公共正式题资格。前端显示参考答案未完整独立核验。
- 无可靠判题依据时提交记录为 unknown，并显示参考学习提示，不将 AI 答案强行当成可信标准答案判定掌握。
- 个人题始终不产生正式毕业证据，不进入公共正式题集；历史题目、审核事件、学习证据和毕业算法没有改写。
- 有效节点约束、质量检查、单次最多5道、每日调用和 Token 保护仍保留。“取消知识点白名单”不等于无限计费或保证任意生成内容都正确。
- 「快速练习」仍为无需模型的预设基础题型，不能冒充能覆盖所有节点的 AI 出题。界面已明确区分。

## 主要修改

| 文件 | 内容 |
| --- | --- |
| backend/services/personal_question_general.py | 通用输出、结构检查、可选独立求解结果及仅个人参考的内容绑定 |
| backend/services/personal_question_service.py | 未覆盖题族/题型/难度走通用生成，复用预算、批次、版本保存和加入分离 |
| backend/services/personal_generation_intent.py | 确认列表开放全部有效叶子节点，识别计算、证明、算法等请求 |
| backend/services/question_generation.py | 通用个人生题 Prompt、完整响应解析和内容绑定 |
| backend/services/learning_assistant_service.py | 助手流不再按专用题族拦截 AI 生成请求 |
| backend/services/question_eligibility.py | 带当前内容绑定的通用个人参考题可练习，不取得正式客观证据资格 |
| backend/services/question_quality.py | 通用题节点绑定记录不再错误声称是白名单绑定 |
| backend/schemas/personal_questions.py | 复用已有计算、证明、主观题型，扩充请求允许值，无新接口/迁移 |
| frontend/src/components/PersonalGenerationConfirmation.vue | 全节点确认说明 |
| frontend/src/components/PersonalQuestionResult.vue | 通用题参考答案提示 |
| frontend/src/components/LearningTaskPanel.vue | 明确全部节点AI出题与预设快速练习的区别 |
| frontend/src/api/personalQuestions.ts | 通用参考题 ID 的结果字段 |
| frontend/openapi.json、frontend/src/api/types.ts | 用已有工具同步契约及生成类型 |

## 实际验证

- 最终相关后端回归：**185 passed，150.67秒**。包括通用生成、原题族、预算、截断、幂等、提交锁定及学习助手。
- 全节点确认测试使用253个明确标记的合成有效叶子节点，确认它们不再受求解器白名单限制；这不是向真实知识树或题库写入测试题。
- 单选、填空、计算、证明、主观五类均验证：保存 QuestionVersion，不创建计划；明确加入后可记录 Attempt / LearningEvent，正式确认次数保持0，不错误毕业。
- 检查重复选项、错误等式、错题型、空解析、超时、内容或节点绑定篡改及可选求解器异常。
- 验证个人题不能取得公共正式审核资格。
- Chrome相关浏览器：**6 passed，0 failed，0 skipped，14.2秒**，含等比级数证明题确认、参考提示、暂不加入、无计划确认和重复加入边界。浏览器响应使用明确标记的受控UI夹具；另有真实服务加隔离数据库的助手SSE集成回归。
- 前端：103单元测试、类型检查和生产构建通过；OpenAPI漂移检查通过。

证据：

- `storage/quality-audits/general-generation-20261017/final/pytest.log`
- `storage/quality-audits/general-generation-20261017/final/run-summary.json`
- `storage/quality-audits/general-generation-20261017/verified/playwright.log`
- `storage/quality-audits/general-generation-20261017/verified/browser-report.json`

所有测试使用新建、自有的高端口隔离PostgreSQL和本地测试模型，无真实付费模型调用。最终测试实例正常停止并清理自身临时数据；没有操作真实库迁移、seed或题库导入。

## 生效与未验证内容

已仅重启核验过的项目8000后端进程，未重启PostgreSQL。正常应用启动沿用自身恢复及后台流程，不应将启动表述为完全没有数据库操作。

本轮未实测真实 DeepSeek 生成答案质量，不承诺每次生成必然成功或无误。模型未配置、网络失败、响应截断、明显错误、重复内容或费用守卫仍可能使某次请求失败，但不再事先将合法知识点排除在AI出题范围外。
