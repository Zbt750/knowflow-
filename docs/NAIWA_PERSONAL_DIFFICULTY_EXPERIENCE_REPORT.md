# 奶蛙个人题难度要求与结果预览改进

日期：2026-10-19。仅个人题生成体验；没有修改正式题库、数据库结构或毕业规则，没有收费模型请求。

## 1. 原有问题

- `_preferences` 只把“综合”分成comprehensive，其余包含中等/难/挑战的描述大多合并为improved；没有保存“简单一点/更难/难很多/相近”的独立相对约束。
- Provider有粗略difficulty和部分user_requirement，但没有稳定的相对难度合同，也不返回结构化难度自评。
- 题目预览仅展示题干、题型、节点、加入动作，无法知道用户目标、模型估计或估计依据。

## 2. 现在的数据与行为

### 要求

`PersonalGenerationRequest` 增加可选 `difficulty_requirement`：raw_text、target_level、relative_change、absolute_explicit。

- 新目标等级：basic基础、medium中等、hard较难、challenge综合挑战。
- 相对要求：easier、much_easier、similar、harder、much_harder、unspecified。
- 原始要求保留；分开识别“中等”与“更难”，不会把“难很多”降成普通提高。
- 最近的难度修订优先；“原题：”后题干文字不决定用户目标。
- 服务端重算有原文的合同，旧客户端错误传入basic不能覆盖“比原题难很多”。不改变调用方对象。
- 原有GenerationTarget的basic/improved/comprehensive继续兼容，较难/中等的细分存放在新合同中；旧Question.difficulty是粗粒度请求标签，不冒充实际难度测量。
- “保持相近”但没有可靠绝对等级时，预览目标明确写“与原题相近（绝对等级未确定）”，不凭空标定原题等级。

### 生成

Provider同时收到原始要求、目标、相对变化和原题。提示明确要求用知识深度、必要推理步骤、方法组合、参数结构或综合应用调整难度，不能只把数字变大。

模型额外返回 `difficulty_assessment`：estimated_level、relative_change、reason、mechanisms。该元数据经过独立Schema校验后进入调用trace，不混入题干/答案模型，也不取代既有答案和质量检查。旧Provider未返回时兼容处理为未评估。

### 校验与保存

在已有内容、答案等质量门之后，保存之前新增难度要求一致性检查：

- 仅换常数大小而题面结构相同的相对变式拒绝。
- 只改变幂次/导数阶数可能确实增加推理，因此不以简单数字替换规则误杀，仍交给原质量检查并标为难度未独立验证。
- 模型明确自评为更简单，不能满足更难；自评略难不能满足难很多；明确绝对目标与模型自评等级冲突也拒绝。
- 使用 `DIFFICULTY_MISMATCH` / `personal_generation_difficulty_mismatch`，阶段difficulty_check；保留失败理由和难度分析，但不保存失败Question/Version，不创建卷或PracticeItem，没有额外自动模型修复调用。
- 无法可靠判断时不伪装通过难度认证。`constraint_check`是要求一致性检查，`independent_check`保持not_independently_verified；这是两种不同概念。
- 合格个人题的难度摘要随Question.grading_config进入新的QuestionVersion快照，同时放入批次difficulty_summaries和个人题读取结果。旧版本、原题与历史记录均不更新。
- 通用题既有“参考答案未完整独立验证/不计正式毕业”边界保持。自评难度不是题目正确性证明，也不是毕业资格。

## 3. 前端

仅在成功题目预览中显示：

1. 目标难度。
2. 预计实际难度，明确“模型自评”。
3. 相对原题要求与模型自评变化。
4. 一两句模型自评理由。
5. 尚无独立难度验证、不代表真实考研难度分布。

可展开查看原始要求。没有可靠原题时说明相对变化无法确认；缺少新字段的旧记录说明未保存难度分析。不向每条普通消息插入标签。

手机真实截图暴露旧全局flex把会话栏与正文挤成两窄列，已做最小响应式修复：会话导航放在上方横向列表；生成题编号缩进减小；难度字段在小屏单列。桌面仍两列字段，不改全站视觉。

## 4. 文件

- 新增 `backend/schemas/generation_difficulty.py`、`backend/services/generation_difficulty.py`。
- 修改 `backend/schemas/personal_questions.py`、`backend/services/personal_generation_intent.py`、`backend/services/question_generation.py`、`backend/services/personal_question_service.py`、`backend/services/generation_diagnostics.py`。
- 新增 `frontend/src/components/GenerationDifficultySummary.vue`；修改 `frontend/src/api/personalQuestions.ts`、`frontend/src/components/PersonalQuestionResult.vue`、`frontend/src/components/GenerationFailureNotice.vue`、`frontend/src/product-theme.css`。
- 新增 `tests/unit/test_generation_difficulty.py`、`tests/integration/test_personal_generation_difficulty.py`。
- 修改固定测试Provider `tests/integration/generation_journey_backend.py` 和浏览器验收 `frontend/acceptance/generation-conversation-persistence.spec.ts`。

没有新增迁移，没有修改教程、大题库、正式审核资格或毕业算法。

## 5. 测试证据

根目录：`storage/quality-audits/generation-difficulty-20261019/`。

| 范围 | 实际结果 | 证据 |
| --- | --- | --- |
| 初轮难度/旧质量/原题/通用个人题回归 | 71 passed，0 failed，17.13s | targeted-v1/pytest.log |
| 扩展回归，含会话隔离与幂次边界 | 74 passed，0 failed，18.24s | verified/pytest.log |
| 最后标签和要求检查，含独立验证状态与一致性检查分离 | 29 passed，0 failed，6.96s | final-label-checks-v2/pytest.log |
| 旧个人题库、题族与确定性/增强模式兼容回归 | 97 passed，0 failed，38.64s | legacy-regression/pytest.log |
| 实际Chrome、实际前后端与隔离PG | 4 passed，0 failed，16.0s | verified/playwright.log |
| 前端相关单元 | 16 passed，0 failed，303ms | 本轮vitest输出 |
| 前端typecheck | 通过 | 本轮vue-tsc输出 |

这些范围重叠，不能相加成唯一测试总数。没有全量后端或全站浏览器重跑，没有新增skip。

覆盖基础、中等、较难、综合挑战，变简单、变难、难很多、保持相近；检查请求、结果标签、元数据快照与读取，而不只检查参数。三种明显冲突均断言零Question、零Version、零DailyPlan、零PracticeItem。普通合格流程继续验证明确加入与版本绑定、幂等、刷新恢复。

浏览器新增“要求更难但Provider自评更简单”场景，确认无成功预览、刷新保留难度冲突。成功场景检查实际难度标签与理由、未独立验证声明；桌面1366×768与手机390×844都有截图，手机断言预览宽度大于300px、单列字段且不超屏。

截图：

- `verified/browser-artifacts/generation-conversation-pe-d32e0--explicit-idempotent-append/difficulty-preview-desktop.png`
- `verified/browser-artifacts/generation-conversation-pe-d32e0--explicit-idempotent-append/difficulty-preview-mobile.png`
- 难度冲突截图在同目录树的冲突用例中：`difficulty-conflict-not-saved.png`。

初次手机检查虽通过“不溢出”断言，截图实际过窄，没有视为验收成功；补充最小宽度断言后真实发现284px，继续修正生成题缩进，未降低断言。失败截图保留在browser-v1和final，不覆盖。

## 6. 真实运行与限制

本机8000后端核对属于项目后，通过原run-backend.cmd安全重启。当前PID24552，单监听127.0.0.1:8000；健康检查ok/database connected。manifest为 `tmp/dev-backend-manifests/runtime-161f916ee69b455593536ef0dd0f50a2.json`。运行中OpenAPI已经包含difficulty_requirement可选字段。前端使用当前源码。

真实模型请求0，真实数据库业务写入0，未调整权限。所有生成/保存/加入和删除测试数据均位于独立测试PostgreSQL，账本确认原集群未触及，测试集群已停止并移除。

工程链路、质量边界、结果展示及桌面/手机可读性已实际验证；**真实DeepSeek是否稳定生成具有所需难度的题，尚未实测**。固定Provider不证明模型自评准确，也不证明题目符合考研难度分布。没有独立难度标定器，本轮不虚构这项能力。真实效果验证需用户手动生成，或另行确认费用预算后进行少量真实调用。

刷新前端后，新生成题显示新说明；历史题不会被追补或改写为虚假的难度认证。
