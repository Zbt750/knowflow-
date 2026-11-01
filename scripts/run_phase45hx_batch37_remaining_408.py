"""Batch 37: second distinct item for the last 40 one-question 408 leaves."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-36-second-supply"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_36_SECOND_SUPPLY_COMPLETE":
    raise RuntimeError("batch36_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch36_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-37-remaining-408"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_36_SECOND_SUPPLY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-37-remaining-408"
batch.SUCCESS_STATUS = "BATCH_37_REMAINING_408_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []
single = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 1 and row.get("subject") == "408"
    and ".family." not in row["node_code"]
    and row["node_code"] != "cs408.os.topic.28afec2a802b"
}


def add(req, node, stem, choices, answer, explanation, method1, result1,
        method2, result2, step1, step2, skills):
    if node not in single:
        raise RuntimeError(f"target_not_single_question_node:{node}")
    batch.CODEX_PUBLIC_ORIGINALS.append({
        "request_id": req,
        "node_code": node,
        "output": base.choice(stem, {chr(65 + i): value for i, value in enumerate(choices)},
                              answer, explanation,
                              f"independent-check:{method1}; {method2} -> {answer}"),
        "derived_answer": answer,
        "method_evidence": [
            {"method": method1, "result": f"路径一：{result1}，得到 {answer}。"},
            {"method": method2, "result": f"路径二：{result2}，复核为 {answer}。"},
        ],
        "explanation_key_steps": [f"第一步：{step1}", f"第二步：{step2}"],
        "option_truth_table": {chr(65 + i): chr(65 + i) == answer for i in range(4)},
        "skill_tags": skills,
    })


# 408: focused, self-contained second items for every remaining one-question leaf.
add("hx37-co-float-add", "cs408.co.topic.c08c6a818873",
    "按二进制规格数运算：1.01₂×2² 与 1.10₂×2¹ 相加，规范化结果为哪一项？",
    ["1.000₂×2²", "1.000₂×2³", "1.100₂×2³", "1.000₂×2⁴"], "B",
    "两数分别为5和3，和为8；规范化为1.000₂×2³。",
    "exact-binary-values", "1.01₂=1.25，乘4得5；1.10₂=1.5，乘2得3，总和8。",
    "normalization", "8=1.000₂×2³，且尾数满足首位为1的规范形式。",
    "先把两个二进制数换成精确十进制整数值。", "相加后规范化并核对指数。", ["浮点数运算", "规格化"])
add("hx37-co-bus-throughput", "cs408.co.topic.497f9a53d9d0",
    "同步总线频率为50 MHz，每周期完成一次数据传送，数据线宽32位。忽略其他开销，其理论带宽是多少？",
    ["50 MB/s", "100 MB/s", "200 MB/s", "1.6 GB/s"], "C",
    "每周期4字节，每秒5×10⁷次传送，带宽为2×10⁸ B/s，即200 MB/s。",
    "cycle-count", "50 MHz×4 B/cycle=200,000,000 B/s。",
    "unit-conversion", "32位=4字节；按十进制MB计为200 MB/s。",
    "把数据宽度换算成字节并乘时钟频率。", "按题设采用十进制MB/s表示。", ["总线定时", "总线带宽"])
add("hx37-ds-circular-tail-delete", "cs408.ds.topic.6c5786034fef",
    "带头结点的循环单链表非空，尾指针 r 指向最后一个数据结点；已知尾结点的前驱 p。删除尾结点后应如何更新？",
    ["p.next=r 且 r.next=head", "head.next=p 且 r=p.next", "p.next=head 且 r=p", "p.next=null 且 r=null"], "C",
    "删去尾结点后，前驱指向头结点以保持循环，再把尾指针移到 p。",
    "pointer-invariant", "循环单链表尾结点的后继应为head；删除后p成为尾结点。",
    "boundary-case", "链表仍非空，故head.next不变且r指向p。",
    "将尾结点从环中摘除并接回头结点。", "同步更新尾指针为原尾结点的前驱。", ["循环链表", "尾结点删除"])
add("hx37-ds-column-major", "cs408.ds.topic.9554f672c611",
    "二维数组 A[1..3][1..4] 按列优先存储，A[1][1] 地址为100，每元素4字节。A[3][2] 的地址是多少？",
    ["120", "124", "128", "132"], "A",
    "列优先偏移为(2−1)×3+(3−1)=5个元素，字节偏移20，地址120。",
    "column-major-offset", "偏移元素数=(列号−1)×行数+(行号−1)=3+2=5。",
    "byte-address", "100+5×4=120。",
    "先求按列优先的线性下标偏移。", "乘元素字节数并加基地址。", ["多维数组存储", "列优先地址计算"])
add("hx37-ds-tridiagonal-space", "cs408.ds.topic.1b4089986d5e",
    "一个8阶三对角矩阵只存储主对角线及其紧邻的上下两条对角线，需存储多少个元素？",
    ["16", "21", "22", "24"], "C",
    "主对角线有8项，上下两条各7项，总数8+7+7=22。",
    "diagonal-count", "三条对角线项数分别为n、n−1、n−1，代入n=8得22。",
    "closed-form", "3n−2=24−2=22。",
    "分别数主对角线和两条偏移对角线。", "用总项数公式复核。", ["特殊矩阵压缩存储", "三对角矩阵"])
add("hx37-ds-bplus-range", "cs408.ds.topic.0a3a485f45d4",
    "在 B+ 树中执行查找键值区间 [a,b] 的范围查询，定位到包含 a 的叶结点后，通常如何高效取得后续结果？",
    ["逐层回到根结点重新查每个键", "沿叶结点间的顺序链扫描至键值超过 b", "只检查根结点中的分隔键", "遍历所有内部结点而不访问叶结点"], "B",
    "B+ 树叶结点按键值有序链接；定位起点后顺链扫描即可输出区间记录。",
    "leaf-link-order", "范围起点定位后，叶链按键值顺序覆盖后续记录。",
    "output-sensitive-search", "先O(log n)定位，再扫描区间涉及的叶记录。",
    "先用树查找区间下界所在叶结点。", "沿叶链输出直到键值大于 b。", ["B+树", "范围查询"])
add("hx37-ds-external-merge-passes", "cs408.ds.topic.9de322fe9c8d",
    "外部排序已经生成8个初始有序归并段，每趟最多进行4路归并。仅计算归并趟数，至少需要几趟？",
    ["1", "3", "2", "4"], "C",
    "每趟最多把段数缩为原来的四分之一：8→2→1，共2趟。",
    "run-count-recurrence", "ceil(log₄8)=2。",
    "pass-by-pass", "第一趟生成2段，第二趟将2段归并成1段。",
    "列出每一趟后的归并段数。", "达到1段时结束。", ["外部排序", "多路归并"])
add("hx37-ds-sort-lower-bound", "cs408.ds.topic.0924b31367c4",
    "对4个互异关键字排序的比较算法，决策树必须区分4!种输入次序。其最坏情况下的关键字比较次数至少是多少？",
    ["4", "5", "6", "8"], "B",
    "二叉比较决策树深度 d 至多有2^d个叶结点；2⁴<24≤2⁵，因此 d 至少为5。",
    "decision-tree-leaves", "需要24个叶结点，深度4最多16叶，不足；深度5可达32叶。",
    "information-lower-bound", "ceil(log₂(4!))=ceil(log₂24)=5。",
    "计算不同排列数4!。", "用二叉树叶数上界求最小深度。", ["排序通论", "比较排序下界"])
add("hx37-co-linker-symbols", "cs408.co.topic.53f5a8046fd9",
    "两个目标文件分别定义函数 main 和 helper，main 中引用 helper。将外部符号引用解析并生成可执行映像，主要由哪个阶段完成？",
    ["预处理", "汇编", "链接", "中断处理"], "C",
    "链接器合并目标模块并解析跨模块符号引用；预处理和汇编不完成该跨文件地址绑定。",
    "build-pipeline", "目标文件中的未解析外部符号由链接阶段匹配定义。",
    "symbol-resolution", "链接器确定helper定义并修补相应重定位项。",
    "识别跨目标文件的外部符号引用。", "按编译、汇编、链接流程定位解析阶段。", ["高级语言到机器级代码", "链接"])
add("hx37-os-time-sharing", "cs408.os.topic.6eeb2632531c",
    "分时系统中某进程用完时间片但仍未主动阻塞时，操作系统通常采取什么措施？",
    ["通过时钟中断抢占并调度其他就绪进程", "永久终止该进程", "关闭所有 I/O 设备", "把进程移入磁盘文件系统"], "A",
    "时间片耗尽触发时钟中断，调度器可抢占当前进程并选取其他就绪进程。",
    "timer-preemption", "时钟中断标记时间片到期并转入内核调度。",
    "ready-queue", "被抢占进程仍可保持就绪，随后其他就绪进程获得CPU。",
    "确定时间片由何种事件终止。", "区分抢占调度与进程终止。", ["操作系统概念与发展", "分时系统"])
add("hx37-os-segment-address", "cs408.os.topic.83dc2a1b2ae2",
    "某段的基址为4000，段长为1200字节，采用零起始段内偏移。逻辑地址偏移1199对应的物理地址是多少？",
    ["4000", "5199", "5200", "无效地址"], "B",
    "偏移须满足0≤1199<1200；物理地址=4000+1199=5199。",
    "bounds-check", "1199小于段长1200，地址合法。",
    "base-plus-offset", "4000+1199=5199。",
    "先检查偏移是否落在段长范围内。", "基址加段内偏移得到物理地址。", ["段式管理", "地址转换", "越界检查"])
add("hx37-os-spooling-concurrency", "cs408.os.topic.e54fc352f4b6",
    "多个进程共享一台打印机并采用 SPOOLing。一个进程提交打印任务后，通常可以怎样继续运行？",
    ["必须一直占有打印机直到打印完", "任务先进入磁盘缓冲队列，进程可在提交后继续", "每个进程必须安装一台物理打印机", "SPOOLing 会把打印任务当作 CPU 指令执行"], "B",
    "SPOOLing将任务暂存于磁盘队列，由后台输出程序串行使用独占设备，提交进程无需等待打印完成。",
    "queue-decoupling", "磁盘缓冲把进程提交与慢速打印设备执行解耦。",
    "device-sharing", "后台服务按队列调度共享打印机。",
    "区分任务提交和设备实际输出。", "说明磁盘缓冲队列如何实现虚拟共享。", ["假脱机 SPOOLing", "设备共享"])
add("hx37-os-monitor-mutual-exclusion", "cs408.os.topic.e7303b384744",
    "在采用监视器机制实现互斥的前提下，任一时刻最多允许多少个进程或线程在监视器内部执行？",
    ["一个", "两个", "与处理器数量相同", "任意多个"], "A",
    "监视器入口受互斥约束，同一时刻只有一个执行流可在监视器内部活动。",
    "monitor-invariant", "互斥进入条件直接给出临界区并发数上限为1。",
    "serialization", "后续调用必须等待当前执行者离开监视器。",
    "识别监视器提供的互斥保证。", "将互斥语义转化为同时执行数量。", ["管程与条件变量", "监视器互斥"])
add("hx37-os-free-block-bitmap", "cs408.os.topic.02e11d34761a",
    "文件系统用位图管理空闲数据块时，位图中的每一位通常对应什么状态？",
    ["一个文件名的字符", "一个进程的优先级", "一个磁盘块是否空闲或已分配", "一条网络路由"], "C",
    "空闲空间位图将位位置映射到数据块，用位值表示该块的占用状态。",
    "bitmap-index", "第 i 位对应约定的第 i 个块号。",
    "allocation-update", "分配/释放块时更新对应位。",
    "建立位图位序号与块号的对应。", "说明分配和释放对位图的更新。", ["文件系统全局结构", "空闲空间管理"])
add("hx37-ds-inorder-output", "cs408.ds.topic.f32b740044c8",
    "二叉树根为 A，A 的左、右孩子分别为 B、C；B 只有右孩子 D。该树的中序遍历序列是什么？",
    ["A,B,D,C", "B,A,D,C", "B,D,A,C", "D,B,A,C"], "C",
    "中序次序为左子树、根、右子树：先访问B的右孩子D，再访问B、A，最后C。",
    "recursive-order", "B子树中序为B,D；整树为B,D,A,C。",
    "explicit-stack-trace", "按左—根—右逐层展开所得序列为B,D,A,C。",
    "先写出B为根的左子树中序结果。", "再按整树左—根—右拼接。", ["中序遍历", "递归遍历"])
add("hx37-co-average-memory-time", "cs408.co.topic.7bfee1be5b94",
    "某存储层次命中时间为2 ns，命中率为0.9；未命中时访问的总延迟（含命中检查）为25 ns。平均访问时间是多少？",
    ["2.3 ns", "3.8 ns", "4.0 ns", "4.3 ns"], "D",
    "平均时间=0.9×2+0.1×25=4.3 ns。",
    "weighted-average", "命中贡献1.8 ns，未命中贡献2.5 ns，总计4.3 ns。",
    "miss-probability", "未命中率为0.1，依题意25 ns是未命中总时间。",
    "求未命中概率。", "按两种互斥情况作加权平均。", ["存储器层次结构", "命中率", "平均访问时间"])
add("hx37-co-risc-decode", "cs408.co.topic.0d0cb51a5974",
    "相较于指令格式和操作种类更复杂的设计，RISC 常采用较规则的指令格式，直接有利于哪一方面？",
    ["使每条指令都能直接访问任意多个内存操作数", "简化指令译码并便于流水线控制", "取消寄存器", "保证程序指令条数一定更少"], "B",
    "规则编码和较简单操作有助于译码与流水线控制；它不保证指令数更少。",
    "format-regularity", "固定或规则字段边界减少译码复杂性。",
    "pipeline-control", "较一致的指令阶段便于流水线设计。",
    "辨认规则指令编码对硬件控制的影响。", "排除与RISC不相符的绝对化说法。", ["CISC 与 RISC", "指令译码", "流水线"])
add("hx37-cn-ftp-channels", "cs408.cn.topic.d8296e4021b3",
    "FTP 传输文件时，控制命令和文件数据在经典 FTP 模型中通常如何传送？",
    ["全部复用同一个 UDP 数据报", "控制连接和数据连接分开", "控制信息只能写入文件头", "文件数据通过 DNS 连接发送"], "B",
    "FTP将持续的控制会话与文件数据连接分离，二者承担不同用途。",
    "connection-roles", "控制连接承载命令响应，独立数据连接承载文件列表或文件内容。",
    "protocol-session", "文件传输期间控制会话仍用于控制交互。",
    "区分命令控制面与数据传输面。", "说明两类连接各自承载的信息。", ["FTP 协议", "控制连接", "数据连接"])
add("hx37-ds-heap-adjust", "cs408.ds.topic.f6d5e81af153",
    "最大堆按层序数组表示为 [9,7,8,3,6,5]。删除最大值后，将末元素移到根并向下调整，剩余堆的层序数组是什么？",
    ["[8,7,5,3,6]", "[7,8,5,3,6]", "[8,6,7,3,5]", "[5,7,8,3,6]"], "A",
    "末元素5移到根，与较大的孩子8交换，得到[8,7,5,3,6]，已满足最大堆。",
    "sift-down", "根5先与孩子7、8中的较大者8交换；此后5无活动孩子。",
    "heap-invariant", "其余父子关系仍满足父值不小于孩子。",
    "交换根与最后一个元素并缩小堆。", "每次与较大孩子交换直到满足堆序。", ["堆排序", "删除堆顶", "向下调整"])
add("hx37-cn-stop-wait-sequence", "cs408.cn.topic.cbb222f5869a",
    "停等协议使用交替位序号0和1。接收方已按序交付序号0的数据帧并发送ACK0后，下一帧新数据应使用哪个序号？",
    ["0", "1", "2", "由接收方随机指定"], "B",
    "交替位协议在每个新数据帧间切换0/1；已确认序号0后下一个新帧用1。",
    "alternating-bit-state", "状态从已交付0转换为期待1。",
    "duplicate-detection", "若重发0会被识别为旧帧，故新帧应携带1。",
    "读取当前已确认帧序号。", "按模2交替规则确定下一新帧序号。", ["停止-等待协议", "交替位协议"])
add("hx37-os-many-to-one-block", "cs408.os.topic.e8dd56864fdc",
    "在多对一线程模型中，多个用户线程映射到一个内核线程；其中一个用户线程执行阻塞式系统调用时，通常会怎样？",
    ["只有该用户线程阻塞，其他线程仍由独立内核线程运行", "整个进程对应的内核执行流可能阻塞，其他用户线程也无法运行", "内核自动把它改为一对一模型", "阻塞系统调用会变成异步信号"], "B",
    "多对一模型只有一个内核调度实体；该实体进入阻塞态会使进程内所有用户线程不能继续获得CPU。",
    "mapping-count", "所有用户线程共享同一内核线程。",
    "blocking-kernel-call", "唯一内核线程阻塞时没有其他内核执行流运行这些用户线程。",
    "确定进程拥有的内核调度实体数量。", "分析唯一内核线程阻塞的影响。", ["线程实现", "多对一模型"])
add("hx37-cn-twisted-pair", "cs408.cn.topic.1a141eb77fc0",
    "双绞线将一对导线按一定节距相互绞合，主要有助于减轻哪种影响？",
    ["传播时延完全消失", "线对间电磁干扰和串扰", "信号无需编码", "距离增加后信号不再衰减"], "B",
    "绞合使两导线受到的外界干扰趋于抵消，可降低电磁干扰及线对间串扰。",
    "twist-cancellation", "相邻绞合段的感应影响部分抵消。",
    "pair-crosstalk", "绞合也降低相邻线对间的耦合串扰。",
    "观察绞合对两根导线受扰对称性的影响。", "区分降低干扰与消除衰减。", ["传输介质", "双绞线", "串扰"])
add("hx37-cn-client-server", "cs408.cn.topic.a44bb362c00a",
    "在典型客户机/服务器应用模型中，哪项描述最符合服务器角色？",
    ["通常等待客户端请求并提供服务", "只在收到请求时临时充当物理路由器", "只能主动向客户端发送广播而不能响应", "必须与客户端共享同一进程"], "A",
    "服务器进程通常持续监听服务端点，客户端发起请求，服务器处理并响应。",
    "request-response", "通信方向与角色由客户端请求、服务器服务响应刻画。",
    "endpoint-lifecycle", "服务端通常预先运行并等待新的客户端连接。",
    "按谁发起服务请求区分角色。", "说明服务器的监听和响应职责。", ["网络应用模型", "客户机/服务器"])
add("hx37-ds-forest-links", "cs408.ds.topic.1d253ee449a8",
    "一个有10个结点、3棵树的森林共有多少条父子边？把森林转为左孩子右兄弟二叉树后，二叉链中的非空指针边共有多少条？",
    ["7条；9条", "9条；7条", "10条；10条", "7条；7条"], "A",
    "森林父子边数为 n−k=7；转换后是一棵含10结点的二叉树，非空左右孩子边总数为n−1=9。",
    "forest-edge-count", "每棵树有节点数减1条边，合计n−k=7。",
    "binary-tree-edge-count", "转换后单一二叉树有10个结点，边数为9。",
    "按森林中各树的边数求和。", "利用树的边结点关系核对转换后数量。", ["森林与二叉树的转换", "左孩子右兄弟"])
add("hx37-ds-selection-stability", "cs408.ds.topic.ddb8a6a53756",
    "直接选择排序采用“将未排序区间最小元素与区间首元素交换”的常见实现。记录为 (3a,3b,2)，其中 a、b 表示原相对顺序；排序后会出现什么情况？",
    ["始终稳定，等关键字仍为3a、3b", "可能不稳定，等关键字次序变为3b、3a", "排序后所有关键字仍降序", "是否稳定只由数组长度决定"], "B",
    "首轮将2与3a交换得到(2,3b,3a)，两个关键字相等的记录相对次序反转，因此该实现不稳定。",
    "first-pass-simulation", "最小值2与首元素3a互换，序列成为2,3b,3a。",
    "stability-definition", "相等关键字的相对次序改变即不稳定。",
    "模拟第一趟选择并交换。", "检查相等记录的前后次序。", ["简单选择排序", "稳定性"])
add("hx37-co-signed-multiply-overflow", "cs408.co.topic.0efeb18eeae7",
    "若结果用8位二进制补码保存，计算 (−12)×11 时会发生什么？",
    ["结果−132可直接表示", "结果为132且可表示", "发生有符号溢出", "结果必为0"], "C",
    "8位补码范围为−128至127，而−132低于最小值，故结果不可表示并发生溢出。",
    "range-check", "−132<−128。",
    "two-complement-bound", "8位有符号补码的最小值是−2⁷=−128。",
    "先求精确数学乘积。", "与8位补码可表示范围比较。", ["整数乘除运算", "有符号溢出"])
add("hx37-co-numa-access", "cs408.co.topic.b084a43130bd",
    "在 NUMA 多处理器中，处理器访问本地内存与远端节点内存的延迟通常有何关系？",
    ["本地访问通常更低，远端访问通常更高", "所有访问都必须经同一磁盘", "远端访问必为零延迟", "NUMA 不包含共享主存"], "A",
    "NUMA具有分布式内存节点和统一地址空间；本地内存通常延迟较低，远端访问经互连较慢。",
    "memory-placement", "内存物理归属在各节点，本地控制器访问路径较短。",
    "nonuniform-latency", "远程节点访问还需经过互连，体现非一致访问时间。",
    "区分UMA与NUMA的内存组织。", "比较本地与远端路径的延迟。", ["多处理器基本概念", "NUMA"])
add("hx37-os-layered-design", "cs408.os.topic.1bd4d45eb1a0",
    "分层操作系统结构中，某一层通常通过定义良好的接口调用下一较低层。该设计最直接的好处是什么？",
    ["所有层必须共享同一全局变量", "任意上层可以绕过所有下层", "完全消除层间通信开销", "隐藏下层实现细节并便于模块化验证"], "D",
    "层接口隔离实现细节，使上层依赖抽象服务，便于分模块设计与测试；并不保证零开销。",
    "abstraction-boundary", "上层只依赖下层接口，不需要了解内部实现。",
    "module-testing", "层职责明确可分别实现与验证。",
    "识别层间接口的抽象作用。", "区分模块化收益与不现实的零开销保证。", ["OS 结构", "分层结构"])
add("hx37-cn-crc-redundancy", "cs408.cn.topic.aa75b70d073a",
    "CRC生成多项式 G(x) 的次数为3。按标准模2除法生成CRC校验序列时，通常需附加多少个校验位？",
    ["2位", "3位", "4位", "与生成多项式次数无关"], "B",
    "生成多项式次数为 r 时，CRC余数长度至多为 r 位；因此此处附加3位。",
    "polynomial-degree", "被除数补r个零，余数最高次数小于r。",
    "remainder-width", "次数为3的生成多项式产生3位CRC余数。",
    "确定生成多项式的最高次数。", "根据CRC余数位数规则确定附加长度。", ["差错控制", "CRC"])
add("hx37-cn-ipv6-prefix", "cs408.cn.topic.76b87a32829d",
    "IPv6 地址 2001:db8:1234:5678:abcd:ef01:2345:6789/64 中，网络前缀对应地址的哪一部分？",
    ["前32位", "前48位", "前64位", "后64位"], "C",
    "/64表示最高64位为网络前缀，剩余64位为接口标识部分。",
    "prefix-length", "/64中的64直接给出前缀比特数。",
    "address-halves", "IPv6地址128位，前64位为前缀，后64位为接口标识。",
    "读取CIDR前缀长度。", "将128位地址按前缀长度划分。", ["IPv6", "前缀长度"])
add("hx37-ds-orthogonal-links", "cs408.ds.topic.ea735e877597",
    "有向图的十字链表中，同一条弧结点要同时链接到尾顶点的出边链和头顶点的入边链。常用哪个指针分别完成这两种链接？",
    ["tlink 链同尾弧，hlink 链同头弧", "hlink 链同尾弧，tlink 链同头弧", "两者都只链接同尾弧", "两者都只链接同头弧"], "A",
    "十字链表弧结点的 tlink 指向同尾弧，hlink 指向同头弧。",
    "tail-chain", "尾顶点出边链按相同尾顶点串接，使用tlink。",
    "head-chain", "头顶点入边链按相同头顶点串接，使用hlink。",
    "分别识别弧的尾顶点和头顶点。", "把两个链字段对应到出边链与入边链。", ["邻接多重表/十字链表", "十字链表"])
add("hx37-cn-vlan-trunk", "cs408.cn.topic.560367fe85a6",
    "两台交换机之间的一条 802.1Q trunk 链路需要承载多个 VLAN 的流量。发送帧通常如何标明所属 VLAN？",
    ["在以太帧中加入 VLAN 标记", "为每个VLAN单独建立物理交换机", "用IP地址最后一位代替MAC地址", "对每帧执行一次DNS查询"], "A",
    "802.1Q trunk通过帧内标签携带VLAN标识，使同一链路复用多个VLAN。",
    "tag-field", "交换机在trunk帧中加入VLAN ID标签。",
    "shared-trunk", "标签使接收交换机能把帧归入对应逻辑VLAN。",
    "区分接入链路和trunk链路。", "说明VLAN标签如何在共享链路上区分帧。", ["VLAN", "802.1Q", "Trunk"])
add("hx37-ds-block-search-bound", "cs408.ds.topic.9bb3378707e8",
    "含100个元素的有序表分成10个等长块，每块10个元素。采用顺序查找索引表、再顺序查找候选块；成功查找时最多比较多少个关键字？",
    ["10", "20", "50", "100"], "B",
    "最坏先比较10个索引关键字，再在选中的块中比较10个数据关键字，总计不超过20次。",
    "two-stage-bound", "两个顺序阶段分别最多10次比较。",
    "worst-block-position", "目标若在候选块末尾，块内最多检查10个元素。",
    "分开计算索引查找和块内查找的上界。", "将两个阶段的比较次数相加。", ["分块查找", "查找比较次数"])
add("hx37-os-hypervisor-type1", "cs408.os.topic.5aeca0416861",
    "哪一种虚拟机监控器通常直接运行在物理硬件之上，而不是作为普通宿主操作系统上的应用程序运行？",
    ["Type-2 hypervisor", "应用层解释器", "Type-1 hypervisor", "文件系统驱动"], "C",
    "Type-1监控器直接运行在硬件层；Type-2通常运行于宿主操作系统之上。",
    "layer-placement", "Type-1又称裸机型，直接占据硬件与来宾系统之间的位置。",
    "type-comparison", "宿主OS之上运行的类型是Type-2，不符合题干。",
    "判断监控器是否依赖宿主操作系统。", "据运行层次区分Type-1和Type-2。", ["虚拟机", "Hypervisor", "Type-1"])
add("hx37-os-vfs-abstraction", "cs408.os.topic.4b8b4cf18f4d",
    "虚拟文件系统（VFS）为上层程序提供统一文件操作接口，其核心作用是什么？",
    ["把通用操作分派到具体文件系统实现", "保证所有文件系统使用同一种磁盘布局", "取消目录和文件对象", "直接替代磁盘控制器"], "A",
    "VFS提供统一抽象接口，并将操作分派给具体文件系统的实现方法。",
    "operation-dispatch", "open/read等通用请求根据对象类型转到相应文件系统操作表。",
    "implementation-abstraction", "上层应用不必依赖每种文件系统的内部格式。",
    "区分统一接口与统一物理格式。", "说明VFS如何连接通用调用和具体实现。", ["虚拟文件系统与挂载", "VFS抽象"])
add("hx37-os-private-mmap", "cs408.os.topic.ad1f1d04dbc6",
    "进程以私有写时复制方式映射文件区域后，仅修改该进程映射中的一个字节，通常会发生什么？",
    ["修改立即同步覆盖所有其他进程映射", "该页可能通过写时复制变为进程私有，原文件不因此被修改", "整个磁盘文件被删除", "CPU禁止读取该页"], "B",
    "私有映射写入采用写时复制语义，进程获得私有页，修改不会作为共享写入更新底层文件。",
    "mapping-semantics", "MAP_PRIVATE的写入不作为对映射文件的共享修改。",
    "copy-on-write", "首次写入时复制页面并仅改变当前进程的私有副本。",
    "识别题设的私有映射属性。", "区分私有写入与共享映射更新。", ["内存映射文件", "私有映射", "写时复制"])
add("hx37-ds-levelorder-result", "cs408.ds.topic.7efb7d5560e4",
    "二叉树根为 A，左、右孩子为 B、C；B 的孩子为 D、E，C 只有左孩子 F。按层序从左到右遍历的结果是什么？",
    ["A,B,C,D,E,F", "A,B,D,E,C,F", "D,E,B,F,C,A", "A,C,B,F,E,D"], "A",
    "层序遍历按深度从小到大、同层从左到右访问，依次为A、B、C、D、E、F。",
    "queue-trace", "队列依次弹出根、第二层B/C、第三层D/E/F。",
    "level-order", "每层从左到右连接即为A,B,C,D,E,F。",
    "按层列出结点。", "保持每层从左到右顺序。", ["层序遍历", "队列"])
add("hx37-os-load-relocation", "cs408.os.topic.8266516a5539",
    "可重定位程序的一条地址引用相对装入基址的偏移为 0x30，实际装入基址为 0x4000。装入时该引用应调整为哪个地址？",
    ["0x0030", "0x4030", "0x4000", "0x4300"], "B",
    "装入地址等于实际基址加相对偏移：0x4000+0x30=0x4030。",
    "relocation-addend", "将0x30加到装入基址0x4000。",
    "address-offset", "十六进制相加得0x4030。",
    "识别引用保存的是相对偏移。", "加上实际装入基址。", ["程序链接与装入", "重定位"])
add("hx37-os-device-status-register", "cs408.os.topic.feae17c9ece4",
    "设备接口中的状态寄存器通常用于报告哪类信息？",
    ["设备是否就绪、忙或发生错误", "进程的虚拟地址空间大小", "目录项的文件名字符串", "CPU的所有通用寄存器内容"], "A",
    "状态寄存器反映设备控制器当前状态，如就绪、忙和错误标志。",
    "register-role", "状态字段供CPU或驱动查询设备运行状况。",
    "status-polling", "驱动根据就绪/忙标志决定能否继续读写设备。",
    "区分状态寄存器与数据寄存器。", "举例设备状态位的典型用途。", ["I/O 设备分类与接口", "状态寄存器"])
add("hx37-cn-packet-switching", "cs408.cn.topic.1e841423f29c",
    "采用数据报分组交换的网络中，同一应用报文拆成的不同分组可能出现哪种情况？",
    ["所有分组必定预留同一专用电路", "每个分组必须占用独立物理链路", "不同分组可能独立转发并经历不同路径", "路由器不能读取目的网络信息"], "C",
    "数据报网络按分组转发，分组可独立选择下一跳，因此同一报文的分组路径不必完全相同。",
    "datagram-forwarding", "每个分组携带目的地址并由路由器逐跳转发。",
    "statistical-multiplexing", "网络链路由多个流量按需共享，不为连接专门保留固定电路。",
    "区分数据报转发和电路交换。", "判断各分组是否必须沿同一路径。", ["网络概念组成与功能", "分组交换"])

if len(batch.CODEX_PUBLIC_ORIGINALS) != 40:
    raise RuntimeError(f"batch37_requires_40_unique_targets:{len(batch.CODEX_PUBLIC_ORIGINALS)}")
if len({x["node_code"] for x in batch.CODEX_PUBLIC_ORIGINALS}) != 40:
    raise RuntimeError("batch37_target_nodes_not_unique")
if {x["node_code"] for x in batch.CODEX_PUBLIC_ORIGINALS} != set(single):
    raise RuntimeError("batch37_targets_do_not_match_remaining_408_single_question_nodes")

if __name__ == "__main__":
    raise SystemExit(batch.main())
