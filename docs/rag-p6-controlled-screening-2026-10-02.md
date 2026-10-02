# P6 受控上下文筛选接入（2026-10-02）

## 当前交付

把两批离线试验的低门槛候选接入实际问答准备边界，增加 `CHAT_CONTEXT_SCREENING=off|shadow|filter`，默认 **off**。没有修改私人 `.env` 或默认打开筛选，不重新运行模型/裁判，不把局部合成标签覆盖写成真实问答准确率。

策略模块 `backend/chat/context_screening.py`：版本 `ordinary-cosine-screen-v1`，固定实验候选余弦门槛0.50。不支持随意填0.70等数字绕过版本与验证。字段经Settings校验，错误模式启动失败。

- off：保留所有原结果，不筛选。
- shadow：计算预计删块数，但Prompt、引用、归因和快照仍使用原结果。
- filter：仅在适用范围中删除已观测且有限的原向量余弦低于0.50的命中。
- 纯关键词命中、缺失/非有限/类型异常的余弦保留。不会退回使用RRF、CrossEncoder或普通 `score` 判断相关性。
- 全部筛空时进入现有“通用知识参考”路径，没有资料引用或知识点归因；不会强行保留首块伪造依据，也不增加额外生成调用。

这是受控接入而不是宣布0.50普适正确。两批合成试验尚不足以证明在用户资料和大规模题库里的表现。

## 边界与一致性

普通混合检索返回之后、证据构建之前执行。明确文件范围、识别出的文件概述/比较、综合型MMR问题、检索降级、启用过重排的结果绕过筛选；明确阶段、全文与跨文件由现有专用概述路径处理，不进入此分支。

筛选后的同一组hits用于：

1. 证据块、顺序连续的C1/C2等引用编号。
2. 资料Prompt与来源映射。
3. 内置知识点归因；“我的资料”仍永不归因。
4. Actual Context Snapshot及最终成功/失败持久化。

成功和失败的消息metadata都记录仅数值诊断：策略版本、模式、门槛、前后块数、预计/实际删除数、未知分数数量、应用与绕过原因。诊断不带原问句、正文、文件名或chunk ID；正文快照仍仅受控测试环境显式启用，普通开发/生产不额外复制私人资料。

快照v2新增可选 `context_screening` 诊断，实际证据块/Prompt一致性、引用映射及哈希验证保持不变；旧快照不回填。普通Prompt v6与Agent v7不变，筛选变化由独立策略版本与评测manifest的 `context_screening_configuration` 区分。manifest不保存密钥/数据库连接串。

## 使用与回退

默认无需操作，仍为off。需要受控实验时，在对应隔离进程环境设置 `CHAT_CONTEXT_SCREENING=shadow` 或 `filter` 并重新启动该进程。未改网页模型设置表单，也不声称这些模式已经默认应用到正在运行的开发后端。

回退设为off并重启进程即可，不涉及迁移、重建索引或改动已保存的作答记录。历史消息保留生成时的诊断，不因现在开关变化而改写旧证据。

## 本轮真实环境与失败保留

开始测试时原PG未运行，首轮87个setup error为数据库无法连接。用原 `.pgdata` 和5433启动，未执行initdb、reset、清理schema或删除文件。PG自动完成中断恢复；日志 `.devlogs/p6-screening-postgres-20261002.log` 保留。测试库为 `kaoyan_test`，测试夹具的迁移/清表不针对开发库。

恢复后的新测试出现三处测试构造错误：诊断字典误当函数调用、模拟命中缺material_id、集成测试助手参数误写normalized而非body。均修正，失败报告不覆盖。不将这些假阳性描述成产品业务缺陷。

报告目录：`eval/reports/rag-p6-screening-20261002/`：

- `targeted-junit.xml`：原87 setup errors（环境失败），保留。
- `targeted-restored-junit.xml`：83通过/4失败（测试构造），保留。
- `targeted-verified-junit.xml`：87通过。
- `backend-full-junit.xml`：核心接入全量1278通过，0失败/错误/跳过，174.171秒；SHA256 `952ce73c011e0e4155cff6650c8e3b7b26209e66f1209aa4c6cd0b0b657b3105`。
- `sse-manifest-junit.xml`：82通过/4失败（测试助手参数），保留。
- `sse-manifest-verified-junit.xml`：86通过，含追加四种SSE成功/失败模式与manifest配置测试；SHA256 `852b0daddaa71a8c5d13e6c7c7b0d495a0776610d67b2c94e4710ddfabdb4757`。
- 最终新增5条测试后的完整回归另存 `backend-final-junit.xml`：**1283 passed / 0 failed / 0 errors / 0 skipped**，pytest终端221.05秒、JUnit suite220.684秒。SHA256 `90fc03774c1a41959e8a0b70d2fbbcf205e3ea8efe4e402aa713962ca516db7a`。不使用中间1278代替最终计数，不把测试耗时当回答时延。

SSE使用真实测试数据库与脚本Provider，能够证明存储/帧/快照接线，不证明真实模型更准确或更快。本轮无前端改动、不重复前端E2E，无真实LLM/RAGAS费用。

## 仍需完成的验收

1. 扩大不同资料与领域的样例，验证受控filter的漏召回边界，尤其无标准术语及关键词独有依据。
2. 用同一版本实际快照对照受控开关的真实回答；需要费用时先列样本、调用范围与目的等待确认。
3. v6命题方向真实补证、文件比较坏例和独立人工复核仍待完成。

不把默认off的接入写成已完成线上质量优化，不把这一批标为P6整体完成。
