"""Batch 31: cover the last five specifically labeled empty topics."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-30-first-coverage"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_30_FIRST_COVERAGE_COMPLETE":
    raise RuntimeError("batch30_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch30_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-31-remaining-topics"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_30_FIRST_COVERAGE_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-31-remaining-specific-topics"
batch.SUCCESS_STATUS = "BATCH_31_REMAINING_TOPICS_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []
empty = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 0
}


def add(req, node, stem, choices, answer, explanation, method1, result1,
        method2, result2, step1, step2, skills):
    if node not in empty or ".family." in node:
        raise RuntimeError(f"target_not_an_empty_specific_node:{node}")
    batch.CODEX_PUBLIC_ORIGINALS.append({
        "request_id": req,
        "node_code": node,
        "output": base.choice(
            stem, {chr(65 + i): value for i, value in enumerate(choices)},
            answer, explanation, f"independent-check:{method1}; {method2} -> {answer}",
        ),
        "derived_answer": answer,
        "method_evidence": [
            {"method": method1, "result": f"路径一（{method1}）：{result1}；核得 {answer}。"},
            {"method": method2, "result": f"路径二（{method2}）：{result2}；复核 {answer}。"},
        ],
        "explanation_key_steps": [f"第一步：{step1}", f"第二步：{step2}"],
        "option_truth_table": {chr(65 + i): chr(65 + i) == answer for i in range(4)},
        "skill_tags": skills,
    })


add("hx31-memory-mapped-file", "cs408.os.topic.ad1f1d04dbc6",
    "使用内存映射文件时，进程通常通过什么方式访问文件内容？",
    ["把文件区域映射到虚拟地址空间后用内存读写指令访问", "把文件名当作 CPU 指令执行", "只能通过网卡 DMA 读取", "先将整个磁盘复制到寄存器"], "A",
    "内存映射文件将文件部分或全部区域映射到进程虚拟地址空间，访问映射地址会触发相应页调入。",
    "virtual-address-mapping", "文件偏移区域与进程虚拟页建立映射，处理器通过普通访存指令读取。",
    "page-fault-path", "映射页未驻留时由缺页机制按需调入文件页并更新映射。",
    "识别文件内容被映射到的地址空间。", "沿虚拟内存缺页机制说明按需访问。", ["内存映射文件", "虚拟地址空间"])
add("hx31-level-order", "cs408.ds.topic.7efb7d5560e4",
    "二叉树层序遍历最适合使用哪种辅助数据结构？",
    ["队列", "栈", "最小堆", "散列表"], "A",
    "层序遍历按层从左到右访问，先进先出的队列保证先发现的上一层结点先处理。",
    "fifo-order", "队列按先进先出输出结点，符合层次递增访问顺序。",
    "breadth-first-invariant", "每次出队一个结点并将其孩子入队，队列保持逐层顺序。",
    "从根结点开始入队。", "出队访问并按从左到右加入孩子。", ["层序遍历", "队列", "广度优先"])
add("hx31-linking-loading", "cs408.os.topic.8266516a5539",
    "动态链接的典型特点是（）。",
    ["共享库可在装入或运行时解析并链接", "所有库代码必须在编译前手工复制到源文件", "不需要任何地址重定位", "只能由文件系统完成"], "A",
    "动态链接把部分外部符号解析推迟到装入时或运行时，程序可共享库代码。",
    "link-time-boundary", "与静态链接在生成可执行文件时合并库代码不同，动态链接延后绑定。",
    "shared-library-loading", "运行时装入器定位共享库并完成必要符号解析与重定位。",
    "确定静态链接的处理时点。", "对比装入器运行时完成的动态链接步骤。", ["程序链接", "装入", "动态链接"])
add("hx31-io-device-class", "cs408.os.topic.feae17c9ece4",
    "下列哪种设备通常属于块设备？",
    ["磁盘", "键盘按字符流输入", "串口字符终端", "鼠标事件流"], "A",
    "块设备以可寻址固定大小数据块为基本传输单位，磁盘是典型块设备；其余通常按字符或事件流处理。",
    "addressable-blocks", "磁盘支持按块号定位并读写块数据。",
    "device-semantics", "键盘、串口和鼠标主要提供连续字符或事件流而非块寻址接口。",
    "区分块寻址与流式接口。", "按设备提供的数据访问语义分类。", ["I/O设备分类", "块设备", "字符设备"])
add("hx31-network-basic-function", "cs408.cn.topic.1e841423f29c",
    "计算机网络最基本且直接的功能之一是（）。",
    ["在不同主机之间进行数据通信", "执行单台 CPU 的指令译码", "管理本地磁盘文件分配表", "确定二叉树遍历次序"], "A",
    "网络通过通信链路和协议实现不同主机间的数据交换；资源共享等建立在此通信能力之上。",
    "host-connectivity", "网络协议分层提供端到端或逐跳数据传递机制。",
    "service-purpose", "跨主机信息交换是计算机网络的基础服务，其他选项属于本机或数据结构任务。",
    "确定网络连接的通信实体。", "区分网络功能与单机处理、存储功能。", ["网络概念", "组成与功能", "数据通信"])

expected = {spec["node_code"] for spec in batch.CODEX_PUBLIC_ORIGINALS}
if len(batch.CODEX_PUBLIC_ORIGINALS) != 5 or len(expected) != 5:
    raise RuntimeError("batch31_must_target_five_unique_topics")
if not expected.issubset(empty):
    raise RuntimeError(f"batch31_targets_not_empty_in_checkpoint:{sorted(expected-set(empty))}")
if any(".family." in node for node in expected):
    raise RuntimeError("batch31_must_not_target_family_nodes")

if __name__ == "__main__":
    raise SystemExit(batch.main())
