"""Batch 35: a distinct second item for 50 additional single-question topics."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-34-second-supply"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_34_SECOND_SUPPLY_COMPLETE":
    raise RuntimeError("batch34_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch34_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-35-second-supply"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_34_SECOND_SUPPLY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-35-second-supply"
batch.SUCCESS_STATUS = "BATCH_35_SECOND_SUPPLY_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []
single = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 1 and ".family." not in row["node_code"]
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


# Mathematics II: nine currently single-question leaves.
add("hx35-math-ftc-chain", "math.exam.3504d885999b",
    "设 F(x)=∫₀^(x²)t dt，求 F'(2)。",
    ["8", "12", "16", "24"], "C",
    "由微积分基本定理与链式法则，F'(x)=x²·2x=2x³，故 F'(2)=16。",
    "fundamental-theorem-chain-rule", "上限导数为2x，被积函数在x²处为x²，乘积2x³在2处为16。",
    "integral-evaluation", "F(x)=x⁴/2，直接求导为2x³，代入2得16。",
    "对上限复合函数使用链式法则。", "先求原函数再求导进行复核。", ["变限积分", "复合上限求导"])
add("hx35-math-bivariate-minimum", "math.exam.e2de677ebe0d",
    "函数 f(x,y)=3x²+y²−6x+4y 在 R² 上的最小值是多少？",
    ["−7", "−5", "−3", "0"], "A",
    "配方得 f=3(x−1)²+(y+2)²−7，故全局最小值为−7。",
    "complete-squares", "两个平方项系数为正，常数项−7即最小值。",
    "gradient-and-Hessian", "驻点(1,−2)，Hessian diag(6,2)正定，函数值−7。",
    "分别对 x、y 配方。", "用驻点和正定 Hessian 核验。", ["二元函数极值", "配方法"])
add("hx35-math-hessian-saddle", "math.exam.58a5d04a7be9",
    "函数 f(x,y)=x²−3y² 在原点的 Hessian 判别结果是什么？",
    ["严格极小点", "严格极大点", "鞍点", "无法判别且为退化点"], "C",
    "Hessian 为 diag(2,−6)，特征值异号、二次型不定，原点为鞍点。",
    "Hessian-eigenvalue-test", "二阶型 x²−3y² 可取正也可取负，判为鞍点。",
    "coordinate-directions", "沿 x 轴函数为 x²增，沿 y 轴为−3y²减，邻域内两侧取值异号。",
    "写出二阶偏导组成的 Hessian。", "沿坐标方向检验函数值变化。", ["Hessian 判别法", "鞍点"])
add("hx35-math-volume-square-root", "math.exam.9f10ce353fbd",
    "曲线 y=√x（0≤x≤1）绕 x 轴旋转所得旋转体体积是多少？",
    ["π/3", "π/2", "π", "2π"], "B",
    "圆盘法 V=π∫₀¹(√x)²dx=π∫₀¹x dx=π/2。",
    "disk-method", "截面积为πx，积分后得到π/2。",
    "shell-free-slice-check", "每个垂直截面半径平方为x，体积微元πx dx，合计π/2。",
    "确定旋转截面的半径。", "积分截面积并代入上下限。", ["旋转体体积", "圆盘法"])
add("hx35-math-nonlinear-ode-slope", "math.exam.ec75fe95fe0f",
    "非线性方程 y''=(y')² 满足 y'(0)=1。其解在 x=1/2 处的斜率 y'(1/2) 为多少？",
    ["1/2", "1", "2", "4"], "C",
    "令 p=y'，则 p'=p²、p(0)=1；分离变量得 p=1/(1−x)，故 p(1/2)=2。",
    "order-reduction", "p'=p²，解得p(x)=1/(1−x)，代入为2。",
    "direct-substitution", "p=1/(1−x)满足p'=p²且p(0)=1，因此斜率为2。",
    "令 p=y' 降阶。", "解一阶方程并代入 x=1/2。", ["二阶非线性微分方程", "降阶代换"])
add("hx35-math-reduction-initial", "math.exam.66f8f7b61188",
    "初值问题 y''=6x、y(0)=0、y'(0)=2 的解在 x=1 处取值是多少？",
    ["2", "3", "4", "5"], "B",
    "积分得 y'=3x²+2，再积分得 y=x³+2x，使用 y(0)=0，故 y(1)=3。",
    "successive-integration", "两次积分并代入初值，得1+2=3。",
    "verify-candidate", "y=x³+2x 满足 y''=6x 与两个初值，代入1得3。",
    "先积分求 y'。", "再次积分并用初值确定常数。", ["降阶与初值", "初值问题"])
add("hx35-math-vector-rank", "math.exam.8d8ad14b2a44",
    "向量 v₁=(1,1,0)、v₂=(0,1,1)、v₃=(1,2,1) 的秩是多少？",
    ["1", "2", "3", "0"], "B",
    "v₃=v₁+v₂，且 v₁、v₂不成比例，故三向量的秩为2。",
    "linear-relation", "存在关系 v₁+v₂−v₃=0，且前两向量独立，秩为2。",
    "minor-test", "前两向量构成的两个坐标列线性独立，矩阵秩至少2；关系给出秩至多2。",
    "找出第三向量与前两者的关系。", "证明前两向量线性无关。", ["向量组秩", "极大无关组"])
add("hx35-math-matrix-power", "math.exam.0949f5ff08f9",
    "矩阵 A=diag(2,3)，则 A² 等于哪一个矩阵？",
    ["diag(4,9)", "diag(2,9)", "diag(4,6)", "diag(5,6)"], "A",
    "对角矩阵相乘时对应对角元分别平方，A²=diag(2²,3²)=diag(4,9)。",
    "diagonal-power", "对角矩阵幂对角元逐个取幂，结果diag(4,9)。",
    "matrix-multiplication", "直接计算A·A，非对角元仍为0，对角元4、9。",
    "应用对角矩阵幂的性质。", "逐项相乘核验。", ["矩阵分解与矩阵幂", "对角矩阵"])
add("hx35-math-double-integral-square", "math.exam.936d8c834760",
    "计算二重积分 ∫₀¹∫₀¹(x+2y)dy dx。",
    ["1/2", "1", "3/2", "2"], "C",
    "内层积分为 x+1，再对 x 从0到1积分，得到3/2。",
    "iterated-integration", "∫₀¹(x+1)dx=1/2+1=3/2。",
    "separate-rectangle", "矩形上∫x=1/2，∫2y=1，总和3/2。",
    "先对 y 积分。", "按线性性拆成两个矩形积分核验。", ["二重积分", "累次积分"])

# Computer Science 408: 41 additional nodes, selected from the current live one-question inventory.
add("hx35-cs-collision-domain", "cs408.cn.topic.f4c8aca76dcc",
    "在全双工交换式以太网链路中，两端可同时发送且链路专用。与传统共享半双工介质相比，通常不会发生哪种现象？",
    ["以太网帧封装", "碰撞", "MAC 地址转发", "链路层差错检测"], "B",
    "专用全双工点到点链路不使用冲突检测共享信道，正常情况下不会发生以太网碰撞。",
    "duplex-medium", "全双工专用链路两方向可同时传输，不存在共享介质争用碰撞。",
    "CSMA-CD-applicability", "碰撞机制针对共享半双工介质，不适用于全双工交换链路。",
    "辨别共享半双工与全双工链路。", "据此确定碰撞机制是否适用。", ["随机访问 MAC", "全双工以太网"])
add("hx35-cs-complexity-nlogn", "cs408.ds.topic.53f56bc6fb55",
    "程序外层循环执行 n 次；每次外层迭代中，变量 j 从1开始并反复乘2，直到 j≥n。其时间复杂度为（）。",
    ["O(log n)", "O(n)", "O(n log n)", "O(n²)"], "C",
    "内层每次迭代使 j 翻倍，共 O(log n) 次；外层执行 n 次，合计 O(n log n)。",
    "nested-loop-count", "n乘以⌈log₂n⌉次内层工作，得O(n log n)。",
    "doubling-series", "j=1,2,4,…达到n需约log₂n步，每个外层迭代重复一次。",
    "计数内层翻倍次数。", "乘以外层迭代数。", ["时间复杂度", "循环分析"])
add("hx35-cs-stack-order", "cs408.ds.topic.838a22b8d08d",
    "空栈依次执行 push(4)、push(7)、push(9)，随后连续执行两次 pop，返回值依次是什么？",
    ["4，7", "9，7", "7，9", "9，4"], "B",
    "栈遵循后进先出，先弹出最后压入的9，再弹出7。",
    "LIFO-sequence", "压入顺序4、7、9，弹出顺序反向为9、7。",
    "stack-top", "栈顶先后为9和7，故两次pop返回9、7。",
    "标出每步后的栈顶。", "按后进先出规则读出结果。", ["顺序栈", "栈操作"])
add("hx35-cs-queue-order", "cs408.ds.topic.cd35413f05e7",
    "空队列按顺序执行 enqueue(A)、enqueue(B)、enqueue(C)，随后执行两次 dequeue，输出次序是什么？",
    ["A、B", "C、B", "B、A", "C、A"], "A",
    "队列遵循先进先出，先删除最早入队的A，再删除B。",
    "FIFO-sequence", "入队次序A、B、C与出队次序相同，前两项为A、B。",
    "head-tail-state", "队首依次从A移动到B，两次返回A和B。",
    "按先进先出维护队首。", "模拟两次删除操作。", ["队列", "先进先出"])
add("hx35-cs-circular-empty", "cs408.ds.topic.e26b2753a525",
    "循环队列用“牺牲一个存储单元”区分空满，队首指针 front 与队尾指针 rear 相等表示什么？",
    ["队列为空", "队列已满", "队列恰有一个元素", "指针发生溢出"], "A",
    "牺牲一个单元的约定下，front==rear 表示空；满队列则为 (rear+1) mod N==front。",
    "empty-full-invariant", "约定的空条件为front与rear相等。",
    "one-slot-reservation", "预留一个空槽避免满状态与空状态指针相同。",
    "回忆空队列的指针不变量。", "与队满条件对照。", ["循环队列", "队空队满判定"])
add("hx35-cs-postorder-inorder", "cs408.ds.topic.21d435b75fbc",
    "结点关键字互异时，哪组遍历序列可以唯一确定一棵二叉树？",
    ["后序和中序", "前序和后序但无其他条件", "仅前序", "仅后序"], "A",
    "中序序列确定根的左右子树范围，后序末项确定根并递归确定各子树，因而唯一。",
    "root-and-partition", "后序末项给出根，中序位置唯一划分左右子树。",
    "recursive-reconstruction", "对左右子树重复同一规则，结点互异时每步选择唯一。",
    "从后序末项定位根。", "利用中序划分并递归重建。", ["遍历序列构造", "中序与后序"])
add("hx35-cs-preorder-example", "cs408.ds.topic.56a82ba8b1ba",
    "某二叉树根为 A，A 的左孩子为 B、右孩子为 C，且 B、C 均为叶结点。其前序遍历序列是什么？",
    ["A，B，C", "B，A，C", "B，C，A", "A，C，B"], "A",
    "前序顺序为根、左子树、右子树，所以序列是A、B、C。",
    "preorder-definition", "先访问根A，再递归左子树B和右子树C。",
    "recursive-traversal", "按根左右的递归过程访问三个结点。",
    "写出前序遍历的访问次序。", "对给定根和叶结点应用。", ["前序遍历", "根左右"])
add("hx35-cs-bst-insert", "cs408.ds.topic.62419b290ce1",
    "二叉搜索树根为8，左孩子为3，右孩子为10；结点3的左右孩子为空。插入关键字6后，它成为谁的孩子？",
    ["结点3的右孩子", "结点3的左孩子", "根8的右孩子", "结点10的左孩子"], "A",
    "6<8，向左到3；6>3，故插入为3的右孩子。",
    "BST-search-path", "搜索路径为8→3，下一空位置是3的右孩子。",
    "ordering-invariant", "插入后左子树关键字小于8且右子树关键字大于3，位置符合BST性质。",
    "按关键字与根比较。", "继续与结点3比较直至空链。", ["二叉搜索树", "插入"])
add("hx35-cs-adjacency-matrix-edges", "cs408.ds.topic.f26de897ea89",
    "无向简单网络有7条边。其邻接矩阵中值为1的元素总数是多少？",
    ["7", "14", "21", "49"], "B",
    "每条无向边在邻接矩阵中对应两个对称的1，因此共有2×7=14个1。",
    "edge-entry-count", "每条边贡献(i,j)和(j,i)两个矩阵项，合计14。",
    "degree-sum", "邻接矩阵所有元素和等于度数和2E=14。",
    "确定无向边对应的矩阵项数量。", "用握手定理再次核对。", ["邻接矩阵", "无向边存储"])
add("hx35-cs-adjacency-list-degree", "cs408.ds.topic.0eb5ea0549e9",
    "无向简单网络有12条边，采用邻接表存储；所有顶点邻接表结点数之和是多少？",
    ["12", "18", "24", "144"], "C",
    "每条无向边在两个端点的邻接表中各出现一次，总结点数为2E=24。",
    "adjacency-entry-count", "12条边各登记在两个端点，得到24个邻接项。",
    "handshaking-lemma", "邻接表长度总和等于所有顶点度数和2E=24。",
    "识别无向边两端都要登记。", "对边数乘以2。", ["邻接表", "度数和"])
add("hx35-cs-chaining-alpha", "cs408.ds.topic.8c073162e98e",
    "散列表有8个槽，采用拉链法存放20个关键字，装填因子 α=n/m 为多少？",
    ["0.4", "1", "2.5", "28"], "C",
    "拉链法装填因子为关键字数除以槽数，20/8=2.5。",
    "load-factor-definition", "α=n/m=20/8=2.5。",
    "chain-length-average", "平均每槽链长为20/8=2.5，与装填因子定义一致。",
    "代入关键字数和槽数。", "用平均链长解释该值允许大于1。", ["散列表", "拉链法", "装填因子"])
add("hx35-cs-heap-delete", "cs408.ds.topic.64cda87cdc82",
    "最大堆数组表示为 [20,18,15,10,12,8]。删除最大值20并调整后，新的堆顶是多少？",
    ["8", "12", "15", "18"], "D",
    "删除根后将末元素8置于根，再向下调整；它先与18交换，最终堆顶为18。",
    "delete-max-sift-down", "根8与较大孩子18交换，新根18。",
    "heap-order-check", "调整只改变根附近次序，最大剩余关键字为18并成为根。",
    "用最后一个元素填补根。", "与较大孩子比较并下滤。", ["堆", "删除最大值"])
add("hx35-cs-critical-path-duration", "cs408.ds.topic.6d4cb688c2ee",
    "工程仅有两条从起点到终点的活动路线，持续时间分别为3+4和2+6。该工程最短完成时间是多少？",
    ["7", "8", "9", "15"], "B",
    "工程需等待所有并行路线完成，工期为关键路线长度 max(7,8)=8。",
    "parallel-project-duration", "两条路线耗时7和8，并行完成时间取较大值8。",
    "longest-path", "AOE网络的总工期等于起点至终点最长路径长度，即8。",
    "求两条路径各自的活动时间和。", "并行工程取最长路径。", ["关键路径", "AOE 网", "工期"])
add("hx35-cs-data-alignment", "cs408.co.topic.236ea41712f9",
    "某处理器要求4字节对象按4字节边界自然对齐。地址1004与地址1006中，哪一个满足该要求？",
    ["仅1004", "仅1006", "二者都满足", "二者都不满足"], "A",
    "4的倍数地址满足4字节对齐；1004能被4整除，1006不能。",
    "modulo-test", "1004 mod 4=0，1006 mod 4=2。",
    "alignment-boundary", "相邻合法4字节边界每隔4个地址，1004位于边界。",
    "分别对地址取模4。", "确认对象大小与对齐边界要求。", ["数据对齐", "边界对齐"])
add("hx35-cs-polling-cost", "cs408.co.topic.bfd3c1878167",
    "程序查询式 I/O 在设备尚未就绪时，CPU 反复读取状态寄存器等待。该等待方式最典型的代价是什么？",
    ["CPU 可能忙等而占用处理时间", "设备不再需要控制器", "数据自动进入用户栈", "中断向量表被删除"], "A",
    "轮询持续检查状态，设备等待期间CPU仍执行查询，可能产生忙等开销。",
    "poll-loop", "状态未就绪时查询循环继续占用处理器周期。",
    "interrupt-contrast", "中断方式可在等待时让CPU做其他工作，轮询不具备这一特性。",
    "识别设备未就绪时的重复查询。", "与中断通知方式比较CPU占用。", ["程序查询方式", "忙等待"])
add("hx35-cs-user-privileged", "cs408.os.topic.ca43cc94bc12",
    "用户态程序试图直接改写页表基址寄存器，这种特权操作通常会触发什么？",
    ["保护异常并由内核接管", "自动把进程变成系统进程", "无条件成功", "只清除该程序的缓存"], "A",
    "页表基址寄存器属于特权状态，用户态直接写入违反权限控制并触发异常。",
    "privilege-check", "用户模式不能执行特权指令，硬件检测后产生保护异常。",
    "kernel-boundary", "只有切换到内核态后操作系统才可安全修改地址转换控制寄存器。",
    "识别目标寄存器是否影响全局内存管理。", "应用用户态权限检查规则。", ["CPU 运行模式", "特权指令"])
add("hx35-cs-device-driver", "cs408.os.topic.7f10bf9cb4e0",
    "设备驱动程序在 I/O 软件层次中的典型职责是什么？",
    ["把通用 I/O 请求转换为具体设备控制操作", "为所有文件分配网络端口", "替代文件系统保存目录名", "只负责应用层协议解析"], "A",
    "驱动程序屏蔽设备差异，将较通用的操作映射为设备寄存器、命令和中断处理。",
    "device-abstraction", "驱动把统一读写请求转换成设备特有命令。",
    "layer-responsibility", "设备无关层提供抽象，驱动层处理硬件细节。",
    "区分通用请求和硬件控制。", "定位驱动程序在分层结构中的职责。", ["I/O 软件层次", "设备驱动"])
add("hx35-cs-deadlock-prevention", "cs408.os.topic.630c531fe924",
    "为避免死锁，可规定进程必须一次性申请完成任务所需的全部资源，从而破坏哪项必要条件？",
    ["互斥", "请求并保持", "不可剥夺", "循环等待"], "B",
    "一次性申请不允许进程持有部分资源再等待其余资源，破坏请求并保持条件。",
    "coffman-condition", "整体申请消除了持有资源同时继续请求资源的状态。",
    "deadlock-prevention", "死锁必要条件之一是请求并保持；资源预申请直接取消该条件。",
    "识别进程何时持有资源并等待。", "映射到四个死锁必要条件。", ["死锁", "请求并保持"])
add("hx35-cs-reclaim-frames", "cs408.os.topic.58a4bb84b898",
    "进程退出后，操作系统释放其私有地址空间；这些页面对应的物理页框通常应如何处理？",
    ["归还可分配的空闲页框集合", "永久绑定到原进程", "全部改为只读缓存", "作为目录项保留"], "A",
    "进程地址空间释放后，专属页框可回收并供其他进程重新分配。",
    "resource-lifetime", "进程结束使其私有映射生命周期结束，页框可释放。",
    "allocator-invariant", "空闲页框管理器重新登记该页框，后续分配可复用。",
    "确定映射所属进程已结束。", "按物理内存资源管理规则回收。", ["页框分配与回收", "空闲页框"])
add("hx35-cs-tlb-purpose", "cs408.os.topic.db2a9445e210",
    "转换后备缓冲器 TLB 的主要作用是什么？",
    ["缓存近期虚拟页号到物理页框号的转换结果", "缓存全部磁盘文件内容", "代替CPU执行进程调度", "保存网络连接端口"], "A",
    "TLB是地址转换缓存，保存近期页表项以减少访存转换开销。",
    "address-translation-cache", "TLB项缓存虚页号到物理页框的映射。",
    "page-table-walk-contrast", "TLB命中可避免每次都遍历内存中的页表。",
    "展开 TLB 的全称及用途。", "与页表的后备遍历过程区分。", ["内存管理", "TLB", "地址转换"])
add("hx35-cs-double-buffer", "cs408.os.topic.4daa9addd7e4",
    "双缓冲 I/O 最直接的性能作用是什么？",
    ["在一个缓冲区供设备传输时，CPU可处理另一个缓冲区", "把磁盘转速提高一倍", "保证任何设备永不等待", "消除所有数据复制"], "A",
    "双缓冲允许生产与消费阶段部分重叠，缓和CPU和设备速度差异。",
    "pipeline-overlap", "一块缓冲交给设备，另一块可被CPU填充或处理。",
    "single-versus-double-buffer", "单缓冲阶段常需等待交接，双缓冲可重叠部分阶段。",
    "跟踪两个缓冲区的交替使用。", "说明重叠为何减少空闲等待。", ["缓冲区管理", "双缓冲"])
add("hx35-cs-symbol-baud", "cs408.cn.topic.e567ffa4c80f",
    "某调制方式每个信号符号有8种可区分状态，符号率为2000 Baud，忽略编码开销，比特率是多少？",
    ["2000 bit/s", "4000 bit/s", "6000 bit/s", "16000 bit/s"], "C",
    "8种状态每符号承载 log₂8=3 bit，故比特率=2000×3=6000 bit/s。",
    "bits-per-symbol", "每符号3比特，乘2000符号/秒得6000比特/秒。",
    "state-count-capacity", "一个符号的8种状态可编码3位二进制信息。",
    "计算每符号信息量。", "将符号率换算为比特率。", ["通信基础", "符号率", "比特率"])
add("hx35-cs-selective-repeat-window", "cs408.cn.topic.6e5dd5812d0e",
    "选择重传 ARQ 使用 k=3 位序号。为避免新帧与仍可能到达的旧帧序号混淆，发送窗口最大值是多少？",
    ["3", "4", "7", "8"], "B",
    "序号空间大小为2³=8，选择重传窗口不得超过序号空间的一半，最大为4。",
    "sequence-space-half", "SR窗口上限2^(k−1)=2²=4。",
    "wraparound-ambiguity", "窗口若大于4，序号回绕后新旧帧可能不可区分，因此上限4。",
    "计算序号空间大小。", "应用半序号空间约束。", ["选择重传", "序号空间", "窗口"])
add("hx35-cs-wlan-ack", "cs408.cn.topic.1351211c91cf",
    "IEEE 802.11 DCF 使用载波侦听并在发送后等待确认帧。即使发送站未检测到冲突，未收到 ACK 通常表示什么？",
    ["接收成功已由发送方确认", "该帧可能未被成功接收，发送方应按规则重传", "目的MAC地址自动改写", "链路改为有线以太网"], "B",
    "无线站点无法像有线冲突检测那样可靠检测碰撞，ACK用于确认接收；超时未确认通常触发重传。",
    "DCF-acknowledgment", "ACK缺失意味着发送方没有获得成功接收确认。",
    "wireless-collision-limit", "无线发送时不能依赖发送端检测碰撞，故使用ACK和超时重传。",
    "辨析无线局域网的确认机制。", "根据未收到ACK判断是否确认交付。", ["无线局域网", "DCF", "确认帧"])
add("hx35-cs-time-wait", "cs408.cn.topic.6bb96577c0c4",
    "TCP 主动关闭连接的一方在发送最后一个 ACK 后进入 TIME_WAIT，主要目的之一是什么？",
    ["确保对端有机会重传最后的 FIN，并让旧报文在网络中失效", "永久占用连接带宽", "让对端自动进入监听状态", "重新协商应用层域名"], "A",
    "TIME_WAIT持续一段报文生存时间，可在最后 ACK 丢失时重发确认，并避免旧连接报文干扰新连接。",
    "last-ACK-retransmission", "对端FIN重传时主动关闭方仍可回ACK。",
    "maximum-segment-lifetime", "等待旧报文在网络中消失，避免连接四元组复用冲突。",
    "追踪主动关闭方最后一次确认的可靠性。", "说明等待旧段失效的作用。", ["TCP 连接管理", "TIME_WAIT"])
add("hx35-cs-boot-order", "cs408.os.topic.099b85d78c35",
    "系统启动中，引导程序完成必要的硬件初始化并定位内核后，下一步通常是什么？",
    ["将内核装入内存并把控制权转交给内核入口", "永久停留在固件中运行应用", "清空所有外存", "启动每个用户进程而不加载内核"], "A",
    "引导链的目标是装载操作系统内核到内存，然后跳转到内核入口继续初始化。",
    "boot-chain", "固件或引导管理器定位并装载内核后转交执行权。",
    "execution-handoff", "内核代码须先驻留内存才能执行后续系统初始化。",
    "按固件、引导程序、内核的次序理解启动链。", "确认控制权最终交给内核。", ["操作系统引导", "内核装载"])
add("hx35-cs-qam-bit-rate", "cs408.cn.topic.1e611d5e4eb0",
    "某调制方式每个符号有8种可区分状态，符号率为2400 Baud。忽略编码开销时比特率是多少？",
    ["2400 bit/s", "4800 bit/s", "7200 bit/s", "19200 bit/s"], "C",
    "每符号可编码 log₂8=3 bit，2400符号/秒对应7200 bit/s。",
    "modulation-capacity", "8个信号状态编码3比特，速率为2400×3=7200。",
    "binary-labeling", "三位二进制标签共有8种，故每符号3比特。",
    "计算状态数对应的比特数。", "乘以符号率。", ["编码与调制", "符号率"])
add("hx35-cs-framing-escape", "cs408.cn.topic.7507d0c4e02a",
    "字节定界组帧采用转义字符方案。若数据字段中出现与帧结束标记相同的字节，发送方通常如何处理？",
    ["在该数据字节前插入转义标记", "直接删除该数据字节", "把该字节解释为新帧结束", "将数据全部转为IP地址"], "A",
    "字节填充通过转义特殊数据字节，防止其被接收方误认为帧定界符。",
    "byte-stuffing-rule", "特殊字节前加入转义字符，接收端再还原。",
    "boundary-preservation", "转义后数据中的标记值不再与真正帧边界混淆。",
    "识别数据字节与控制定界符冲突。", "说明转义如何保留数据并避免误分帧。", ["数据链路层", "组帧", "字节填充"])
add("hx35-cs-switch-learning", "cs408.cn.topic.201ce80c4dd6",
    "以太网交换机收到来自端口3、源MAC为 M 的帧时，通常如何更新自学习表？",
    ["把源MAC M 与端口3关联", "把目的IP地址与端口3关联", "删除所有其他表项", "只记录帧长度"], "A",
    "交换机通过入帧源MAC学习该地址所在端口，并据此建立转发表项。",
    "source-address-learning", "入端口3的帧源地址M被记录为可经端口3到达。",
    "forwarding-database", "自学习表以源MAC作为学习键，端口作为值。",
    "区分学习字段与转发查找字段。", "用帧的到达端口建立映射。", ["以太网交换机", "自学习"])
add("hx35-cs-shell-gap-one", "cs408.ds.topic.1408569fd510",
    "希尔排序执行完最后一趟增量为1的插入排序后，序列具有什么状态？",
    ["已整体有序", "仅奇数位置有序", "仍需再做冒泡排序", "每个元素都被移动一次"], "A",
    "增量为1时比较相邻元素的普通插入排序完整作用于整个序列，结束后序列整体有序。",
    "final-gap-pass", "最后一趟就是标准插入排序并处理所有相邻逆序。",
    "insertion-sort-invariant", "插入排序对全序列完成后建立全局非降序次序。",
    "识别增量1对应普通插入排序。", "应用插入排序结束时的有序性。", ["希尔排序", "增量序列"])
add("hx35-cs-bitmap-bytes", "cs408.os.topic.b5a459680f3e",
    "位图管理32768个磁盘块，每块用1位表示空闲状态。忽略额外结构，位图本身占用多少字节？",
    ["1024 B", "2048 B", "4096 B", "32768 B"], "C",
    "32768位除以每字节8位，得到4096字节。",
    "bitmap-bit-count", "32768 bits/8=4096 bytes。",
    "power-of-two-conversion", "32768=2^15 bits，除8=2^12 bytes=4096。",
    "计算总位数。", "换算成字节并检查2的幂。", ["外存空闲空间管理", "位图"])
add("hx35-cs-producer-full", "cs408.os.topic.a28022393ec2",
    "有界缓冲区容量为5，初始为空；生产者已成功放入5个数据项，消费者尚未取出。此时 empty 和 full 信号量的值分别是多少？",
    ["0 和 5", "5 和 0", "1 和 4", "5 和 5"], "A",
    "五个槽位都被占用，空槽数为0，已有数据项数为5。",
    "buffer-count", "empty=capacity−items=5−5=0，full=items=5。",
    "semaphore-invariant", "empty+full=5且缓冲全满，唯一值为0和5。",
    "用缓冲容量减已放入数量。", "检查两个计数之和仍等于容量。", ["经典同步问题", "生产者消费者", "empty/full"])
add("hx35-cs-shannon-capacity", "cs408.cn.topic.e09a336289ea",
    "带宽为3 kHz、信噪比为15（线性值）的理想信道，按香农公式计算的容量是多少？",
    ["6 kbit/s", "9 kbit/s", "12 kbit/s", "15 kbit/s"], "C",
    "C=B log₂(1+SNR)=3000·log₂16=3000·4=12000 bit/s。",
    "shannon-formula", "带宽3000乘以log₂16=4，容量12000 bit/s。",
    "power-of-two", "1+15=16=2⁴，故每赫兹4 bit/s，乘3kHz得12kbit/s。",
    "代入线性信噪比而非分贝值。", "计算以2为底的对数。", ["奈奎斯特与香农定理", "香农容量"])
add("hx35-cs-fdma", "cs408.cn.topic.9a617d7c8ebe",
    "频分多址（FDMA）让多个用户同时共享信道时，主要为不同用户分配什么资源？",
    ["不同频率子带", "不同时间片", "不同磁盘柱面", "不同TCP序号空间"], "A",
    "FDMA按频率划分信道，为用户分配互不重叠或受保护的频带。",
    "multiple-access-definition", "Frequency Division Multiple Access按频带分配用户。",
    "contrast-TDMA", "时间片属于TDMA机制，FDMA区分资源是频率。",
    "展开 FDMA 名称。", "与时分接入的时间资源对照。", ["信道划分 MAC", "FDMA"])
add("hx35-cs-tcp-timeout", "cs408.cn.topic.940692c0d533",
    "TCP Reno 检测到重传超时后，拥塞窗口通常采取哪种初始调整？",
    ["降到1个 MSS 左右并重新慢启动", "保持超时前数值不变", "立刻设为接收窗口的两倍", "永久置为0且不恢复"], "A",
    "超时被视为严重拥塞信号，TCP Reno通常将 ssthresh 设为飞行数据量的一半，并将 cwnd 降至1 MSS后慢启动。",
    "RTO-response", "超时后拥塞窗口重置到小初值，通常1 MSS。",
    "congestion-severity", "超时表示可能严重丢包，与快速重传后的温和减半处理不同。",
    "区分超时与三次重复ACK。", "说明超时后的窗口重启策略。", ["TCP 拥塞控制", "超时恢复"])
add("hx35-cs-transport-demux", "cs408.cn.topic.4ca2f6021eeb",
    "主机收到多个应用进程的数据段后，传输层通常依据什么信息把数据交给正确的套接字？",
    ["端口号及相关连接标识", "磁盘块号", "CPU频率", "以太网前导码长度"], "A",
    "传输层利用端口号和协议相关的套接字标识实现多路复用与分用。",
    "transport-demultiplexing", "目的端口参与确定接收数据的应用套接字。",
    "socket-identifier", "TCP通常还结合源/目的地址端口与协议，定位连接套接字。",
    "从网络层交付到主机后辨认应用端点。", "概括传输层分用依据。", ["传输层功能", "端口", "分用"])
add("hx35-cs-udp-length", "cs408.cn.topic.b6784d3204ca",
    "不含IP头部时，UDP首部的固定长度是多少字节？",
    ["4", "8", "16", "20"], "B",
    "UDP首部含源端口、目的端口、长度和校验和四个16位字段，共8字节。",
    "header-fields", "4个字段×2字节=8字节。",
    "protocol-constant", "UDP固定首部长度为8字节，之后才是数据。",
    "列出四个16位字段。", "将16位换算为2字节后求和。", ["UDP", "首部格式"])
add("hx35-cs-http-redirect", "cs408.cn.topic.415100bf0700",
    "HTTP 状态码 301 的典型含义是什么？",
    ["永久重定向", "资源临时不可用", "服务器内部错误", "请求成功但无内容"], "A",
    "301 Moved Permanently 表示资源已永久迁移，响应通常提供新的 URI。",
    "status-code-semantics", "3xx为重定向类别，301具体表示永久移动。",
    "contrast-codes", "临时重定向常用302，服务器错误为5xx，故301为永久重定向。",
    "识别HTTP 3xx类别。", "区分301与临时重定向、服务端错误。", ["WWW 与 HTTP", "状态码", "重定向"])
add("hx35-cs-dfs-visited", "cs408.ds.topic.2067aabae2b5",
    "在可能含环的有限网络上执行深度优先搜索时，设置 visited 标记的主要作用是什么？",
    ["避免重复访问顶点并保证搜索过程结束", "保证找到权值最小路径", "使算法不再需要栈或递归", "将所有边改为有向边"], "A",
    "visited记录已经发现的顶点，防止环导致重复递归或循环，并避免重复处理。",
    "cycle-termination", "环上的已访问顶点不会再次入栈展开，搜索得以终止。",
    "complexity-bound", "每个顶点至多首次访问并处理，结合边扫描得到O(V+E)。",
    "考虑深度优先遇到回边的情形。", "结合每个顶点只处理一次的界限核验。", ["深度优先搜索", "visited"])
add("hx35-cs-kmp-prefix", "cs408.ds.topic.545d41f3ba0c",
    "模式串 abab 的前缀函数在最后一个位置的值是多少？（取最长真前缀且也是后缀的长度。）",
    ["0", "1", "2", "3"], "C",
    "对整个串 abab，最长真前缀且为后缀的是 ab，长度2。",
    "prefix-suffix-enumeration", "真前缀 ab 与后缀 ab 相等，长度2。",
    "KMP-border", "abab的最长border为ab；更长长度3的前缀aba不等于后缀bab。",
    "列出可能的真前缀长度。", "排除长度3后取最大相等前后缀。", ["KMP", "前缀函数", "失配信息"])
add("hx35-cs-isa-boundary", "cs408.co.topic.3f6ede8e6fb2",
    "指令集体系结构（ISA）主要规定软件可见的哪类内容？",
    ["指令、寄存器和寻址等机器级接口", "晶体管制造工艺尺寸", "机箱风扇转速", "显示器像素排列"], "A",
    "ISA定义机器指令、寄存器、数据类型、寻址方式和异常等软硬件接口。",
    "software-visible-interface", "编译器和机器码依赖ISA定义的指令及寄存器语义。",
    "abstraction-boundary", "相同ISA可由不同微体系结构实现，说明它处于软件可见接口层。",
    "辨认机器级程序依赖的契约。", "区分ISA与具体电路实现。", ["计算机系统层次结构", "ISA"])

if len(batch.CODEX_PUBLIC_ORIGINALS) != 50:
    raise RuntimeError(f"batch35_requires_50_unique_targets:{len(batch.CODEX_PUBLIC_ORIGINALS)}")
if len({x["node_code"] for x in batch.CODEX_PUBLIC_ORIGINALS}) != 50:
    raise RuntimeError("batch35_target_nodes_not_unique")

if __name__ == "__main__":
    raise SystemExit(batch.main())
