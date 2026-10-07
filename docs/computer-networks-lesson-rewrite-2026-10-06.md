# 408 计算机网络节点讲解改写（2026-10-06）

## 本批范围

- 以当前 `cs408.cn` 知识树为范围，覆盖章节导读与 39 个专题节点，共 40 页。
- 每个专题补充定义/适用边界、原创完整例题与逐步解答、常见混淆点；练习仍从关联题库获取。
- 不在讲解页附加历年题号索引，也不宣称这份节点目录等同官方考试范围。

## 验收记录

- `scripts/computer_networks_textbook_content.py` 按真实知识树做严格节点覆盖校验，节点增删会使测试失败。
- 后端回归：`tests/unit/test_computer_networks_textbook_content.py`、`test_builtin_lessons.py`、`test_lesson_content_catalog.py` 共 15 项通过。覆盖时延/带宽时延积、CIDR、IPv4 分片、GBN/SR 窗口、累计确认、Dijkstra、CRC 发送与校验、停等利用率算例。
- Playwright：`frontend/e2e/computer-networks-textbook.spec.ts` 通过，40 页逐页检查标题、例题、KaTeX、无公式错误、无横向溢出、无页面/控制台异常。
- 仅同步 `cs408.cn`：新建导读 1 份、更新专题资料 39 份；数据库核验 40/40 份为 `ready`，激活索引共 84 个 chunk，失败 0。
- 在线 API 抽查 IPv4 分片与 CRC 讲解均返回 200 和本批正文，分别显示 1、2 道关联题目；健康接口为 `ok`、数据库 connected、索引 ready、worker running。

## 限制

本批是项目原创学习草稿，尚未经过独立教师逐条审核；协议细节可能因版本、实现和题目约定不同而变化。本批不改题库答案、知识映射、学习证据或其他科目。
