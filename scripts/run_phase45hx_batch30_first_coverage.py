"""Batch 30: first public-original coverage for the next 50 empty 408 nodes."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-29-first-coverage"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_29_FIRST_COVERAGE_COMPLETE":
    raise RuntimeError("batch29_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch29_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-30-first-coverage"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_29_FIRST_COVERAGE_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-30-first-coverage"
batch.SUCCESS_STATUS = "BATCH_30_FIRST_COVERAGE_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []

empty = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 0
}


def add(req, node, stem, choices, answer, explanation,
        method1, result1, method2, result2, step1, step2, skills):
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
            {"method": method1, "result": f"独立路径一（{method1}）：{result1}；核得答案 {answer}。"},
            {"method": method2, "result": f"独立路径二（{method2}）：{result2}；复核答案 {answer}。"},
        ],
        "explanation_key_steps": [f"第一步：{step1}", f"第二步：{step2}"],
        "option_truth_table": {chr(65 + i): chr(65 + i) == answer for i in range(4)},
        "skill_tags": skills,
    })


# 50 concrete nodes; the one inventory node without a usable topic label is excluded.
add("hx30-interrupt-mode", "cs408.co.topic.1401561f15d5",
    "外设完成一次输入操作并向处理器发出中断请求后，CPU 通常会（）。",
    ["在允许响应时保存现场并转入相应中断服务程序", "直接将设备数据当作指令执行", "清空整个主存", "永久停止当前进程"], "A",
    "处理器在适当边界响应中断，保存必要现场并通过中断向量转到服务程序。",
    "interrupt-control-flow", "中断响应包括现场保护、识别来源和执行相应服务程序。",
    "return-path", "服务程序完成后恢复被中断上下文，原程序可继续运行。",
    "从请求到服务程序描述中断控制流程。", "检查服务结束后的现场恢复与返回。", ["程序中断", "中断响应"])
add("hx30-os-interrupt-exception", "cs408.os.topic.4ac423ec47e2",
    "与外部设备中断通常异步于当前指令流不同，缺页异常通常属于（）。",
    ["由当前指令访存引起的同步异常", "外部网卡随机发出的异步中断", "仅由定时器产生的中断", "DMA 完成通知"], "A",
    "缺页由当前指令引用的页面不在内存触发，异常与该指令执行同步。",
    "instruction-causality", "若没有当前指令访问缺页，该异常不会发生，具有同步因果关系。",
    "exception-classification", "缺页是处理器检测到的访存异常，不是设备完成事件。",
    "定位异常的直接触发指令。", "按异常和外部中断分类区分其同步性。", ["中断与异常", "缺页异常"])
add("hx30-os-boot", "cs408.os.topic.099b85d78c35",
    "计算机启动时，固件中的引导程序最主要的任务之一是（）。",
    ["初始化必要硬件并装入后续引导程序或操作系统内核", "执行所有应用程序", "永久保存用户文件", "替代 CPU 完成指令执行"], "A",
    "启动代码完成基本硬件初始化并定位、装入下一阶段引导代码或内核。",
    "boot-chain", "启动从固件开始逐级装入引导加载器与内核。",
    "memory-residency", "操作系统运行前必须先把内核映像装入内存并转交控制权。",
    "识别系统启动的先后阶段。", "说明控制权如何从固件移交给内核。", ["操作系统引导", "启动过程"])
add("hx30-encoding-qpsk", "cs408.cn.topic.1e611d5e4eb0",
    "理想 QPSK 调制的每个信号符号可区分 4 种状态，因此每个符号携带多少比特？",
    ["1 bit", "2 bit", "4 bit", "8 bit"], "B",
    "每符号信息量为 log₂M；M=4 时 log₂4=2 bit。",
    "constellation-cardinality", "四个不同符号状态可编码2位二进制组合。",
    "logarithmic-information", "log₂(4)=2，给出每个符号可承载的信息位数。",
    "确定调制状态数 M。", "计算每符号的二进制信息量。", ["编码与调制", "QPSK", "符号率"])
add("hx30-framing", "cs408.cn.topic.7507d0c4e02a",
    "数据链路层组帧的直接目的主要是（）。",
    ["标识链路层数据单元的边界并附加链路控制信息", "为 IP 地址分配域名", "选择端到端 TCP 端口", "计算应用程序语法"], "A",
    "帧封装为网络层数据提供边界、地址及差错检测等链路层控制信息。",
    "layer-encapsulation", "网络层分组被链路层封装成具有帧首尾边界的帧。",
    "receiver-delimitation", "接收端须从连续比特流识别帧起止，组帧机制提供该边界。",
    "明确链路层封装的服务对象。", "从接收端识别边界说明组帧作用。", ["数据链路层", "组帧"])
add("hx30-ethernet-switch", "cs408.cn.topic.201ce80c4dd6",
    "以太网交换机收到帧后，通常依据什么信息选择转发端口？",
    ["目的 MAC 地址与转发表", "目的 IP 地址的域名部分", "TCP 源端口", "应用层 URL 路径"], "A",
    "二层交换机依据目的 MAC 地址查 MAC 地址转发表并决定输出端口。",
    "layer-two-forwarding", "交换转发字段是以太网帧的目的MAC地址。",
    "table-lookup", "查表命中时定向转发，未知目的地址时在相应 VLAN 内泛洪。",
    "确定设备工作在数据链路层。", "将帧目的地址映射到交换表端口。", ["以太网交换机", "MAC地址转发"])
add("hx30-shell-sort", "cs408.ds.topic.1408569fd510",
    "希尔排序的基本思想是（）。",
    ["按逐渐缩小的增量对间隔元素进行插入排序", "每趟都选择全局最小元素放到首位", "只使用二叉堆删除最大元素", "递归地将序列合并为两半"], "A",
    "希尔排序先按较大增量形成若干子序列进行插入排序，再逐步减小增量，最终增量为1。",
    "gap-subsequences", "每个增量定义一组间隔元素子序列，各自执行插入排序。",
    "final-gap-one", "最终增量为1时相当于对近乎有序序列做直接插入排序。",
    "说明增量如何划分子序列。", "解释最后一趟增量为1的作用。", ["希尔排序", "增量排序"])
add("hx30-free-space-bitmap", "cs408.os.topic.b5a459680f3e",
    "文件系统用位图管理磁盘块时，通常用一个位表示什么？",
    ["一个磁盘块是否空闲或已分配", "一个进程的全部寄存器", "一个目录的文件名", "一条网络路由"], "A",
    "位图中每位对应一个磁盘块，位值按约定表示该块空闲或已占用。",
    "bit-block-mapping", "对块号 b 计算其位图位置即可检查对应块状态。",
    "space-accounting", "位图所有位汇总编码文件系统的数据块分配状态。",
    "建立位与磁盘块的一一对应。", "用相应位值更新分配与释放状态。", ["外存空闲空间管理", "位图"])
add("hx30-classic-sync-empty", "cs408.os.topic.a28022393ec2",
    "有界缓冲区含 N 个空槽，生产者—消费者信号量模型中，初始 empty 与 full 通常分别为（）。",
    ["N 与 0", "0 与 N", "1 与 1", "N 与 N"], "A",
    "初始时N个槽均空、缓冲区没有产品，因此empty=N、full=0。",
    "resource-count", "empty计数空槽数量为N，full计数已用槽为0。",
    "initial-state", "信号量初值必须与缓冲区物理初始状态相符。",
    "统计初始空槽。", "统计初始已有产品槽。", ["经典同步问题", "生产者消费者", "信号量"])
add("hx30-shannon-capacity", "cs408.cn.topic.e09a336289ea",
    "理想无噪声信道带宽为 3 kHz，采用 4 种离散信号状态时，奈奎斯特最高数据率为多少？",
    ["6 kbit/s", "12 kbit/s", "18 kbit/s", "24 kbit/s"], "B",
    "奈奎斯特公式 C=2B log₂M，代入 B=3000、M=4 得 2×3000×2=12000 bit/s。",
    "nyquist-substitution", "直接代入公式得到12000 bit/s，即12 kbit/s。",
    "symbol-rate-times-bits", "最大符号率为6000 Baud，每符号2 bit，乘积仍为12000 bit/s。",
    "先算最大符号率。", "乘以每个符号可承载的比特数。", ["奈奎斯特定理", "信道容量"])
add("hx30-channel-tdma", "cs408.cn.topic.9a617d7c8ebe",
    "时分多址（TDMA）将共享信道主要划分为（）。",
    ["按时间分配给不同站点的时隙", "按频率分配给不同站点的子频带", "每个站点独占一根物理光纤", "按 IP 地址分配路由表"], "A",
    "TDMA在时间轴上划分时隙，不同站点按分配的时隙发送。",
    "resource-dimension", "TDMA分割的资源维度是时间而非频谱。",
    "multiple-access-schedule", "时隙轮转使多个站点共享同一信道且减少同时发送冲突。",
    "识别多址方案分割资源的维度。", "根据时隙调度说明站点如何共享信道。", ["信道划分 MAC", "TDMA"])
add("hx30-transport-functions", "cs408.cn.topic.4ca2f6021eeb",
    "传输层提供的端到端逻辑通信通常以什么作为区分应用进程的重要依据？",
    ["端口号", "以太网帧的前导码", "磁盘块号", "CPU 指令地址"], "A",
    "传输层端口号标识主机中的通信端点，使数据交付到相应应用进程。",
    "socket-demultiplexing", "传输层根据目的端口等字段把报文复用/分用到套接字。",
    "layer-service", "IP地址定位主机，端口号在主机内定位传输层端点。",
    "区分主机寻址与进程寻址。", "说明接收端如何按端口分用数据。", ["传输层功能", "端口号", "复用分用"])
add("hx30-udp", "cs408.cn.topic.b6784d3204ca",
    "UDP 的典型服务特征是（）。",
    ["无连接且不保证可靠交付与顺序", "面向连接并保证按序可靠交付", "仅用于物理层编码", "必须先完成三次握手"], "A",
    "UDP提供无连接的数据报服务，不由协议本身保证可靠性、重传或按序交付。",
    "protocol-semantics", "UDP数据报独立发送，协议没有连接建立状态。",
    "service-guarantee", "UDP首部不提供TCP式确认、重传和序号排序机制。",
    "检查UDP是否维护连接状态。", "对照可靠传输所需确认重传机制。", ["UDP协议", "无连接服务"])
add("hx30-http-get", "cs408.cn.topic.415100bf0700",
    "HTTP 中客户端通常使用哪种方法请求服务器返回指定资源的表示？",
    ["GET", "ARP", "RIP", "DHCP"], "A",
    "GET用于请求目标资源的表示；其余选项属于网络层或链路配置协议。",
    "method-semantics", "GET方法的语义是获取由请求目标标识的资源表示。",
    "protocol-layer", "GET属于HTTP应用层方法，不是地址解析、路由或地址配置协议。",
    "从HTTP方法语义判断请求目标。", "排除不同层次的协议名称。", ["WWW与HTTP", "HTTP方法"])
add("hx30-dfs", "cs408.ds.topic.2067aabae2b5",
    "深度优先搜索在递归实现中，主要借助什么机制保存待返回的搜索路径？",
    ["函数调用栈", "优先队列", "散列表冲突链", "磁盘索引块"], "A",
    "递归DFS通过调用栈保存当前访问路径与返回位置；非递归DFS可显式使用栈。",
    "recursive-call-stack", "每次递归深入都会压入调用帧，回溯时弹出。",
    "iterative-equivalent", "显式栈实现与递归调用栈模拟相同的后进先出遍历控制。",
    "跟踪递归深入时保存的状态。", "用显式栈的等价实现复核。", ["深度优先搜索", "栈"])
add("hx30-kmp-prefix", "cs408.ds.topic.545d41f3ba0c",
    "KMP 字符串匹配在失配时利用 next/前缀函数，主要避免了哪种重复工作？",
    ["主串指针回退并重新比较已匹配字符", "重新读取整个主串", "为每个字符重新排序", "重复构造模式串的逆序串"], "A",
    "KMP依据模式串已匹配前缀与后缀关系移动模式串，主串指针不回退。",
    "failure-function", "next值给出可保留的最长相等真前后缀长度。",
    "text-pointer-invariant", "匹配过程中主串扫描位置单调前进，因此避免回退重比。",
    "计算失配位置可保留的前缀长度。", "检查主串位置是否回退。", ["KMP算法", "前缀函数"])
add("hx30-computer-hierarchy", "cs408.co.topic.3f6ede8e6fb2",
    "计算机系统的层次结构中，应用程序通常通过什么接口使用底层硬件资源？",
    ["操作系统提供的抽象与系统调用等接口", "直接操作任意硬件引脚", "文件扩展名", "交换机 MAC 地址表"], "A",
    "操作系统向应用提供进程、文件、虚拟内存和系统调用等抽象，管理对硬件的访问。",
    "abstraction-layer", "应用使用操作系统抽象而非直接管理所有设备细节。",
    "protected-access", "特权操作由内核代表应用执行并受权限检查。",
    "识别应用与硬件之间的软件层。", "说明接口如何兼顾抽象与受控访问。", ["计算机系统层次结构", "操作系统抽象"])
add("hx30-floating-add", "cs408.co.topic.c08c6a818873",
    "浮点数加减运算前通常首先需要（）。",
    ["对阶，使两个操作数阶码一致", "交换两个操作数的符号位", "把尾数全部清零", "将阶码直接相乘"], "A",
    "浮点加减需先把较小阶码的尾数右移到相同阶码，再进行尾数加减和规格化。",
    "exponent-alignment", "只有相同权重的位才能逐位相加，故先统一阶码。",
    "place-value", "对阶保持数值不变地调整尾数，使两数位权相同。",
    "比较两数阶码。", "调整尾数后执行加减并按需规格化。", ["浮点数运算", "对阶"])
add("hx30-bus-timing", "cs408.co.topic.497f9a53d9d0",
    "同步总线进行数据传送时，通常以什么作为统一的操作节拍？",
    ["公共时钟信号", "文件系统时间戳", "网卡 MAC 地址", "磁盘转速"], "A",
    "同步总线的各操作步骤按公共时钟边沿推进。",
    "clock-edge", "主从设备在约定时钟边沿采样地址、控制与数据。",
    "fixed-cycle", "时钟周期数定义同步传送的时序长度。",
    "识别同步时序参照。", "说明公共时钟如何协调总线双方。", ["总线定时", "同步总线"])
add("hx30-circular-list", "cs408.ds.topic.6c5786034fef",
    "带头结点的循环单链表中，若表中没有数据结点，通常有何指针关系？",
    ["头结点的 next 指回头结点自身", "头结点 next 必为任意野指针", "尾结点必须指向空地址", "头结点被释放"], "A",
    "空循环链表仍保留头结点，其next指针回指自身以形成闭环。",
    "empty-invariant", "无数据结点时唯一结点就是头结点，循环链接使next回到自身。",
    "sentinel-representation", "头结点作为哨兵保留，空表通过头结点指针关系表示。",
    "确定该表采用带头结点表示。", "应用循环链表空表不变量。", ["循环链表", "头结点"])
add("hx30-row-major", "cs408.ds.topic.9554f672c611",
    "二维数组 A[0..1][0..2] 按行优先存储，首地址100、每元素4字节，则 A[1][2] 地址为（）。",
    ["108", "112", "120", "124"], "C",
    "按行优先的零起始偏移为 1×3+2=5 个元素，字节地址为 100+5×4=120。",
    "row-major-offset", "行号前有3个元素，本行目标列前有2个，共偏移5个。",
    "byte-address", "5个元素乘每个4字节得到20字节，再加基址100。",
    "按行数计算前面完整行元素个数。", "加列偏移并换算成字节地址。", ["多维数组", "行优先存储", "地址计算"])
add("hx30-symmetric-compression", "cs408.ds.topic.1b4089986d5e",
    "一个 n 阶实对称矩阵只存储主对角线及其上三角元素，需要保存多少个元素？",
    ["n²", "$n(n-1)/2$", "$n(n+1)/2$", "2n"], "C",
    "上三角含对角线的元素数为 n+(n−1)+…+1=n(n+1)/2。",
    "triangle-count", "逐行计数分别为n到1，等差数列求和为n(n+1)/2。",
    "symmetry-sharing", "对称性使下三角可由对应上三角元素恢复，不需重复存储。",
    "统计每行保留的元素数。", "利用对称性确认只需保留一个三角区。", ["特殊矩阵", "对称矩阵压缩存储"])
add("hx30-bplus-leaves", "cs408.ds.topic.0a3a485f45d4",
    "B+ 树中，通常将实际记录或记录指针统一存放在哪一层？",
    ["叶结点", "仅根结点", "每个内部结点随机存放", "不存放在树中"], "A",
    "B+树内部结点主要保存索引关键字，实际记录或记录指针位于叶结点，叶层通常顺序链接。",
    "node-role", "内部结点负责导航，叶结点承载数据记录项。",
    "range-scan", "叶结点链便于按关键字顺序进行范围扫描。",
    "区分内部索引结点与叶结点职责。", "用顺序范围查询验证叶层组织作用。", ["B+树", "叶结点", "索引"])
add("hx30-external-merge", "cs408.ds.topic.9de322fe9c8d",
    "当待排序文件远大于内存容量时，常用的外部排序方法是（）。",
    ["多路归并排序", "仅在内存中直接插入排序", "深度优先搜索", "线性探测散列"], "A",
    "外部归并先生成有序段，再通过多路归并顺序读写外存完成排序。",
    "run-generation-merge", "内存中可处理的块先形成有序归并段，之后多轮合并。",
    "sequential-io", "归并阶段主要顺序访问外存，适合磁盘I/O特性。",
    "把大文件分成可装入内存的初始段。", "说明多路归并如何生成整体有序文件。", ["外部排序", "多路归并"])
add("hx30-sort-stability", "cs408.ds.topic.0924b31367c4",
    "若排序后相同关键字记录的相对先后顺序仍与输入相同，则该排序算法称为（）。",
    ["稳定排序", "原地排序", "内部排序", "非比较排序"], "A",
    "稳定性定义就是相同关键字元素排序后相对次序不改变。",
    "definition", "直接对照稳定排序的定义。",
    "equal-key-pair", "跟踪任意相等关键字记录对，其先后关系保持即稳定。",
    "选取具有相同关键字的两个记录。", "比较排序前后的相对次序。", ["排序通论", "稳定性"])
add("hx30-assembler", "cs408.co.topic.53f5a8046fd9",
    "汇编程序（assembler）的主要作用是（）。",
    ["将汇编语言指令翻译为机器代码", "将网络域名解析成 IP 地址", "把磁盘块映射到文件名", "调度 CPU 时间片"], "A",
    "汇编器把符号化汇编指令及伪指令处理为目标机器代码或目标文件。",
    "translation-stage", "汇编语言助记符与机器指令编码对应，由汇编器完成转换。",
    "object-file", "汇编结果可形成含机器码与重定位信息的目标文件。",
    "区分高级语言编译与汇编阶段。", "追踪目标文件中机器码的产生来源。", ["高级语言到机器级代码", "汇编器"])
add("hx30-segment-bounds", "cs408.os.topic.83dc2a1b2ae2",
    "分段存储管理中，逻辑地址为 (段号 s, 段内偏移 d)，合法性检查通常要求（）。",
    ["d 小于该段长度界限", "d 大于物理内存总容量", "段号等于页框号", "每个段必须等长"], "A",
    "段表提供段基址与段长，访问前检查偏移 d 未超过段界限，合法后基址加偏移形成物理地址。",
    "segment-limit-check", "按段表长度字段检查段内偏移范围。",
    "address-formation", "合法地址由段基址加段内偏移得到，段长用于阻止越界。",
    "查找段号对应的段表项。", "比较偏移与段长后形成地址或触发保护异常。", ["段式管理", "段表", "越界检查"])
add("hx30-spooling", "cs408.os.topic.e54fc352f4b6",
    "SPOOLing 技术常用外存作为缓冲区，典型用途是（）。",
    ["把多个进程的打印请求排队并由打印机逐个输出", "让打印机同时打印所有文件", "取代文件系统目录", "把 CPU 缓存写入寄存器"], "A",
    "假脱机把独占设备虚拟为可共享服务，作业先暂存磁盘队列，再由后台进程串行输出。",
    "disk-queue", "输出作业被写入外存队列，设备空闲时再取出执行。",
    "device-virtualization", "多个用户可提交作业，SPOOLing协调单台物理打印机。",
    "识别慢速独占输出设备。", "说明外存队列如何解耦提交者与设备。", ["SPOOLing", "假脱机", "设备共享"])
add("hx30-monitor-condition", "cs408.os.topic.e7303b384744",
    "管程中的条件变量执行 wait 操作时，调用线程通常会（）。",
    ["释放管程互斥并阻塞，待唤醒后重新竞争进入", "继续持有互斥锁并忙等", "终止整个操作系统", "永久删除条件变量"], "A",
    "条件变量wait原子地释放管程锁并阻塞；被signal唤醒后需重新获得管程互斥才能继续。",
    "atomic-release-and-block", "wait释放锁与进入等待队列作为不可分割的同步动作。",
    "mutual-exclusion-restoration", "唤醒不等于立即执行，线程须重新获得管程锁。",
    "说明 wait 如何避免持锁睡眠。", "追踪唤醒后重新进入临界区的条件。", ["管程", "条件变量", "同步"])
add("hx30-superblock", "cs408.os.topic.02e11d34761a",
    "文件系统的超级块（或卷控制块）通常保存哪类信息？",
    ["文件系统整体参数与空闲空间等元数据", "每个进程的通用寄存器值", "以太网冲突次数", "CPU 的指令流水线状态"], "A",
    "超级块保存文件系统规模、块大小、空闲空间管理和根目录等全局结构信息。",
    "filesystem-metadata", "这些字段描述整个文件系统卷而非单个进程或设备帧。",
    "mount-validation", "挂载文件系统时内核读取超级块以识别并验证卷结构。",
    "区分卷级元数据与文件级目录项。", "说明挂载时超级块用于读取全局参数。", ["文件系统全局结构", "超级块"])
add("hx30-inorder", "cs408.ds.topic.f32b740044c8",
    "二叉树的中序遍历递归访问次序为（）。",
    ["左子树、根、右子树", "根、左子树、右子树", "左子树、右子树、根", "右子树、根、左子树"], "A",
    "中序遍历定义为先遍历左子树，再访问根，最后遍历右子树。",
    "traversal-definition", "直接按中序递归定义写出左右与根的顺序。",
    "recursive-trace", "对任一结点先完成左子树调用，访问该结点，再调用右子树。",
    "明确根结点访问时机。", "用递归调用顺序确认左右子树位置。", ["中序遍历", "二叉树遍历"])
add("hx30-memory-locality", "cs408.co.topic.7bfee1be5b94",
    "程序近期访问过某存储单元后，短时间内再次访问同一单元的现象称为（）。",
    ["时间局部性", "空间局部性", "对齐", "外部碎片"], "A",
    "时间局部性指刚访问过的数据或指令在近期可能再次被访问。",
    "locality-definition", "访问时间上的重复性对应时间局部性。",
    "cache-reuse", "缓存保留近期访问项正是利用短期重访概率。",
    "观察同一地址是否重复访问。", "联系缓存命中解释时间局部性用途。", ["存储器层次结构", "时间局部性"])
add("hx30-risc-load-store", "cs408.co.topic.0d0cb51a5974",
    "典型 RISC 设计常采用的 load-store 结构意味着（）。",
    ["只有 load/store 指令直接访问内存，算术运算主要在寄存器间进行", "所有算术指令都必须访问磁盘", "指令长度必然可变且复杂", "不存在通用寄存器"], "A",
    "load-store结构将内存访问集中于加载与存储指令，算术逻辑操作数通常在寄存器中。",
    "instruction-classification", "对算术指令和访存指令分类，可见只有load/store访问内存。",
    "operand-location", "算术运算使用寄存器操作数，访存通过显式加载或存储完成。",
    "识别 load 与 store 的职责。", "判断普通算术操作数所在位置。", ["CISC与RISC", "load-store结构"])
add("hx30-ftp", "cs408.cn.topic.d8296e4021b3",
    "FTP 协议最主要提供哪种应用层服务？",
    ["文件传输", "IP 地址自动配置", "链路层冲突检测", "域名解析"], "A",
    "FTP是应用层文件传输协议，支持控制连接及数据传送。",
    "application-function", "FTP名称与协议服务均对应文件传输。",
    "layer-comparison", "其他选项分别属于DHCP、MAC机制和DNS用途。",
    "确定协议的服务对象。", "将协议用途与其他常见协议区分。", ["FTP协议", "文件传输"])
add("hx30-heapsort", "cs408.ds.topic.f6d5e81af153",
    "堆排序在最坏情况下的时间复杂度是（）。",
    ["O(n)", "O(n log n)", "O(n²)", "O(2ⁿ)"], "B",
    "建堆为O(n)，随后进行n次根删除或交换，每次堆调整O(log n)，总体O(n log n)。",
    "heap-adjust-count", "线性数量的下滤操作各至多沿树高log n调整。",
    "height-bound", "二叉堆高度为O(log n)，重复取顶元素n次得O(n log n)。",
    "分别估算建堆与排序阶段。", "用堆高估算每次调整成本。", ["堆排序", "时间复杂度"])
add("hx30-stop-wait-timeout", "cs408.cn.topic.cbb222f5869a",
    "停等协议发送数据帧后，在超时前未收到确认，发送方通常应（）。",
    ["重传尚未确认的数据帧", "立即发送无限多个新帧", "把序号清空并关闭网络层", "认为数据必然已成功交付"], "A",
    "计时器超时说明确认未按时到达，发送方重传当前未确认帧。",
    "sender-state", "停等发送窗口只有一个未确认帧，超时后重发该帧。",
    "loss-recovery", "数据帧或确认丢失都会通过超时重传恢复。",
    "定位发送方当前未确认的数据帧。", "按超时恢复机制决定重传对象。", ["停止等待协议", "超时重传"])
add("hx30-thread-sharing", "cs408.os.topic.e8dd56864fdc",
    "同一进程内的多个线程通常共享哪项资源？",
    ["进程地址空间中的代码与全局数据", "各自独立的进程地址空间", "每线程唯一的文件系统", "不同的操作系统内核"], "A",
    "同进程线程共享代码段、全局数据和打开文件等进程资源，但各自有栈、寄存器上下文。",
    "address-space-model", "线程在同一进程地址空间运行，可访问共享代码与全局对象。",
    "per-thread-state", "栈和处理器上下文通常各线程独有，区别于共享进程资源。",
    "区分进程级共享资源与线程级执行状态。", "举例说明共享地址空间及私有栈。", ["线程实现", "线程资源"])
add("hx30-transmission-media", "cs408.cn.topic.1a141eb77fc0",
    "以下哪一种属于导向传输介质？",
    ["光纤", "无线电波", "微波自由空间链路", "红外无线链路"], "A",
    "光纤以物理介质引导光信号传播；无线电、微波和红外属于非导向传播。",
    "guided-path", "光在纤芯和包层构成的实体介质中传播。",
    "medium-classification", "其余选项均通过空间传播而非实体线路引导。",
    "判断是否存在实体传输通道。", "区分导向介质与无线空间传播。", ["传输介质", "导向介质"])
add("hx30-network-p2p", "cs408.cn.topic.a44bb362c00a",
    "对等（P2P）网络模型中，一个节点通常可以（）。",
    ["既作为服务请求方，也作为资源提供方", "只能永久充当中心服务器", "只负责物理信号放大", "不能与其他节点直接交换资源"], "A",
    "P2P节点可直接向其他节点请求资源，也可向其他节点提供资源。",
    "peer-role-symmetry", "节点角色不是固定的客户端或中心服务器，可以双向提供服务。",
    "resource-sharing", "文件分块等资源可由多个对等节点分别提供。",
    "识别节点角色是否固定。", "从资源请求与共享两个方向核对。", ["网络应用模型", "P2P"])
add("hx30-forest-binary-transform", "cs408.ds.topic.1d253ee449a8",
    "森林转换为二叉树时，常用的左孩子—右兄弟表示中，结点的右指针通常指向（）。",
    ["它在森林中的下一个兄弟", "它的父结点", "整棵树的根结点", "任意叶结点"], "A",
    "左孩子右兄弟表示用左链指向第一个孩子、右链指向下一个兄弟。",
    "pointer-meaning", "右指针语义固定为同层下一个兄弟。",
    "sibling-chain", "同一父结点的孩子通过右链串接。",
    "确定第一个孩子由哪个指针表示。", "顺着兄弟链检查右指针语义。", ["森林与二叉树转换", "左孩子右兄弟"])
add("hx30-selection-sort", "cs408.ds.topic.ddb8a6a53756",
    "简单选择排序对 n 个元素完成排序时，关键字比较次数为（）。",
    ["n−1", "n(n−1)/2", "n log₂n", "随输入是否有序而变化"], "B",
    "每趟在未排序区查找最小值，比较数为(n−1)+(n−2)+…+1=n(n−1)/2。",
    "comparison-sum", "将每一趟线性查找的比较次数相加得到三角数。",
    "input-independence", "无论数据初始次序如何，每趟都扫描剩余区，比较次数固定。",
    "列出剩余区长度。", "累加各趟比较次数并简化。", ["简单选择排序", "比较次数"])
add("hx30-unsigned-division", "cs408.co.topic.0efeb18eeae7",
    "无符号整数 13 除以 3，商和余数分别为（）。",
    ["商4余1", "商3余4", "商4余0", "商5余−2"], "A",
    "13=4×3+1 且余数满足0≤1<3，因此商为4、余数为1。",
    "division-identity", "使用被除数=除数×商+余数计算13=3×4+1。",
    "repeated-subtraction", "从13中减去3四次剩1，第五次会为负，故商4余1。",
    "应用整数除法恒等式。", "验证余数范围。", ["整数除法", "商与余数"])
add("hx30-multiprocessor-shared-memory", "cs408.co.topic.b084a43130bd",
    "共享存储多处理器系统中，多个处理器通常通过什么方式交换共享数据？",
    ["读写共同的主存地址空间", "只能通过各自独立磁盘交换", "通过修改彼此的指令寄存器", "只能使用路由器转发"], "A",
    "共享存储系统的处理器访问共同地址空间，通过读写共享变量通信。",
    "shared-address-space", "共享内存对各处理器可见，提供共同通信对象。",
    "communication-model", "与消息传递系统显式发送消息不同，共享存储通过共同内存交换状态。",
    "明确系统共享的资源。", "用共享变量与消息传递的差异核对。", ["多处理器", "共享存储"])
add("hx30-os-structure-microkernel", "cs408.os.topic.1bd4d45eb1a0",
    "微内核结构的一个典型设计特点是（）。",
    ["尽量把非核心服务移到内核外的用户态服务器", "把所有应用程序都放入内核态", "取消进程间通信", "不提供任何系统调用"], "A",
    "微内核仅保留调度、基本通信等少量机制，文件系统和驱动等服务可在用户态运行。",
    "kernel-minimization", "微内核设计目标是减小内核特权代码规模。",
    "service-placement", "非核心服务通过进程间通信向用户态服务器委托。",
    "区分核心机制与系统服务。", "定位非核心服务的执行位置。", ["OS结构", "微内核"])
add("hx30-ipv6-length", "cs408.cn.topic.76b87a32829d",
    "IPv6 地址长度为多少位？",
    ["32 位", "64 位", "128 位", "256 位"], "C",
    "IPv6地址长度固定为128位。",
    "protocol-format", "IPv6地址由128位组成，常以八组十六进制数表示。",
    "address-space", "128位可表示2的128次方个地址。",
    "记忆协议地址字段长度。", "由十六进制分组形式核对总位数。", ["IPv6", "地址长度"])
add("hx30-orthogonal-list", "cs408.ds.topic.ea735e877597",
    "有向图的十字链表中，一条弧结点通常同时链接到（）。",
    ["弧尾的出边链与弧头的入边链", "两个顶点的邻接矩阵行", "两个不同图的边表", "排序序列的相邻元素"], "A",
    "十字链表为每条有向弧同时维护同弧尾出边链和同弧头入边链。",
    "arc-incidence", "弧的尾端关联出边链，头端关联入边链。",
    "in-out-traversal", "该结构可分别高效遍历顶点的出弧和入弧。",
    "识别有向弧的尾与头。", "按两个关联方向描述弧结点链接。", ["十字链表", "有向图存储"])
add("hx30-vlan-broadcast", "cs408.cn.topic.560367fe85a6",
    "在二层交换网络中划分 VLAN 的一个直接效果是（）。",
    ["把一个物理局域网划分为多个逻辑广播域", "自动增加 IP 地址位数", "让不同 VLAN 的广播帧必定互通", "取消交换机 MAC 地址学习"], "A",
    "VLAN把交换网络划分为逻辑广播域，广播通常不会跨VLAN转发。",
    "broadcast-domain", "每个VLAN形成独立二层广播域。",
    "frame-isolation", "广播帧在本VLAN内泛洪，跨VLAN通信需三层转发。",
    "分析广播帧的泛洪范围。", "区分二层隔离与跨网段路由。", ["VLAN", "广播域"])
add("hx30-block-search-index", "cs408.ds.topic.9bb3378707e8",
    "索引顺序查找（分块查找）中，索引表通常为每个块保存（）。",
    ["该块最大关键字等索引信息及块首地址", "每个元素的完整机器码", "所有记录的逆序副本", "CPU 的当前程序计数器"], "A",
    "常见分块查找在索引表中保存各块最大关键字与块起始位置，再定位块内查找。",
    "block-range-index", "块最大关键字标识块值域上界，供索引顺序定位。",
    "two-stage-search", "先查索引表确定块，再在该块内部查找记录。",
    "确定块内关键字范围。", "按索引定位与块内检索两个阶段核对。", ["分块查找", "索引表"])
add("hx30-virtual-machine-hypervisor", "cs408.os.topic.5aeca0416861",
    "虚拟机监控器（hypervisor）的主要职责是（）。",
    ["管理物理资源并为多个虚拟机提供隔离的虚拟硬件环境", "负责把所有文件名解析成 IP 地址", "只执行用户应用的算术指令", "替代网络交换机转发帧"], "A",
    "Hypervisor对CPU、内存和设备等物理资源进行虚拟化、调度与隔离，支持多个虚拟机运行。",
    "resource-virtualization", "虚拟CPU、内存和设备由监控器映射到物理资源。",
    "isolation-boundary", "虚拟机间隔离由监控器管理硬件访问和资源分配实现。",
    "列出监控器管理的底层资源。", "说明多个虚拟机共享主机硬件但保持隔离。", ["虚拟机", "Hypervisor"])
add("hx30-vfs-mount", "cs408.os.topic.4b8b4cf18f4d",
    "把一个文件系统挂载到目录树中时，挂载点通常是什么？",
    ["已有目录树中的一个目录", "一个 CPU 寄存器", "某个 TCP 端口", "磁盘控制器中断号"], "A",
    "挂载把待挂文件系统的根目录接到现有目录树中的挂载点目录，用户由该路径访问其内容。",
    "namespace-attachment", "挂载点是现有目录命名空间中的目录节点。",
    "path-resolution", "路径解析到达挂载点后继续进入新文件系统的根目录。",
    "区分文件系统与挂载点。", "按路径遍历说明挂载点如何接入新根目录。", ["虚拟文件系统", "挂载"])

expected = {spec["node_code"] for spec in batch.CODEX_PUBLIC_ORIGINALS}
if len(expected) != 50 or len(batch.CODEX_PUBLIC_ORIGINALS) != 50:
    raise RuntimeError("batch30_must_target_50_unique_nodes")
if not expected.issubset(empty):
    raise RuntimeError(f"batch30_targets_not_empty_in_checkpoint:{sorted(expected-set(empty))}")
if any(".family." in node for node in expected):
    raise RuntimeError("batch30_must_not_target_family_nodes")

if __name__ == "__main__":
    raise SystemExit(batch.main())
