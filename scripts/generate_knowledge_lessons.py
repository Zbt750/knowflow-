"""为知识树中的每个节点补齐可浏览的原创讲解页。

讲解页是项目发布资源，按稳定的节点 code 命名。现有人工编写页面不会被覆盖；
缺失页面生成概念、原创例题，并链接节点已关联的历年真题。原卷题干与商业解析不会被复制。

用法：
    python scripts/generate_knowledge_lessons.py
    python scripts/generate_knowledge_lessons.py --check
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.exam_reference_service import build_exam_reference_seed  # noqa: E402

LESSON_DIR = PROJECT_ROOT / "seed" / "lessons"
SUPPLEMENT_MARKER = "<!-- knowledge-lesson-addon:v1 -->"
REFERENCE_MARKER = "<!-- exam-reference-index:v1 -->"


@dataclass(frozen=True)
class Profile:
    focus: str
    method: str
    example: str
    exercise: str
    answer: str


PROFILES: dict[str, Profile] = {
    "math_limit": Profile(
        focus="极限研究变量趋近某点或无穷远时函数值的变化趋势；连续性则把极限与函数值接起来。等价无穷小只能在保持乘除结构时替换，加减抵消时要保留高阶项。",
        method="先代入判断未定式，再选因式分解、有理化、等价替换、泰勒展开或洛必达。使用定理前写明适用条件；分段函数还要分别计算左右极限。",
        example="求 $\\lim_{x\\to0}\\frac{\\sin(3x)}{\\tan(2x)}$。由 $\\sin(3x)\\sim3x$、$\\tan(2x)\\sim2x$，原式极限为 $3/2$。复合角里的系数不能漏。",
        exercise="求 $\\lim_{x\\to0}\\frac{e^{2x}-1}{\\sin(5x)}$。",
        answer="由 $e^{2x}-1\\sim2x$、$\\sin(5x)\\sim5x$，极限为 $2/5$。",
    ),
    "math_derivative": Profile(
        focus="导数与微分描述局部变化率；复合、隐函数和反函数求导的关键是依赖关系与链式因子。偏导固定其他变量，全微分给出局部线性近似。",
        method="先标出自变量与中间变量，逐层使用链式法则；隐函数对 $x$ 求导时把 $y$ 当作 $y(x)$。计算后检查定义域、分母非零等条件。",
        example="由 $x^2+xy+y^2=3$ 求点 $(1,1)$ 处切线。隐式求导得 $2x+y+xy'+2yy'=0$，代入得 $y'=-1$，所以切线为 $y-1=-(x-1)$。",
        exercise="由 $x^2+y^2=25$ 求点 $(3,4)$ 处的 $dy/dx$。",
        answer="求导得 $2x+2yy'=0$，故 $y'=-x/y$；在 $(3,4)$ 处为 $-3/4$。",
    ),
    "math_multivariable": Profile(
        focus="多元函数把多个变量映射到一个函数值。偏导是坐标方向变化率，可微意味着存在统一的线性近似；二元极值常由驻点与 Hessian 判别。",
        method="先求各偏导并联立驻点方程；极值判别计算 $D=f_{xx}f_{yy}-f_{xy}^2$，再结合 $f_{xx}$。$D=0$ 时不能据此下结论。",
        example="令 $f(x,y)=x^2+xy+y^2$。驻点满足 $2x+y=0$、$x+2y=0$，得到 $(0,0)$；Hessian 判别量为 $4-1=3>0$ 且 $f_{xx}=2>0$，所以为严格极小点。",
        exercise="对 $f(x,y)=x^2+2y^2$ 求驻点并判断类型。",
        answer="$f_x=2x,f_y=4y$，唯一驻点为 $(0,0)$；$D=2\\cdot4=8>0$ 且 $f_{xx}=2>0$，为严格极小点。",
    ),
    "math_application": Profile(
        focus="导数应用把函数变化转成单调、极值、凹凸、拐点或切线信息。结论来自导数符号及其变化，而不是只看 $f'=0$。",
        method="求定义域和临界点，制作导数符号表；分类驻点时检查符号变化，求闭区间最值时比较端点。中值定理证明要先验证连续与可导条件。",
        example="$f(x)=x^3-3x$，$f'=3(x-1)(x+1)$。导数在 $(-1,1)$ 为负、两侧为正，因此 $x=-1$ 为极大点、$x=1$ 为极小点，函数值分别为 $2,-2$。",
        exercise="判断 $g(x)=x^3-3x$ 在 $[-2,2]$ 上的最大值与最小值。",
        answer="比较端点和临界点：$g(-2)=-2,g(2)=2,g(-1)=2,g(1)=-2$，最大值 $2$，最小值 $-2$。",
    ),
    "math_integral": Profile(
        focus="积分既是求原函数，也是累积量。定积分应用要识别区间和被积量；变上限求导要再乘上限的导数；反常积分必须先按极限定义讨论收敛。",
        method="先选择换元或分部积分；定积分计算时同步更新上下限；几何应用先画区间并分段。反常端点写成极限，不能只看原函数是否存在。",
        example="计算 $\\int_0^1 xe^{x^2}\\,dx$。令 $u=x^2$，$du=2x\\,dx$，结果为 $\\frac12\\int_0^1e^u du=(e-1)/2$。",
        exercise="计算 $\\int_0^1\\frac{2x}{1+x^2}\\,dx$。",
        answer="令 $u=1+x^2$，积分为 $[\\ln(1+x^2)]_0^1=\\ln2$。",
    ),
    "math_double_integral": Profile(
        focus="二重积分对平面区域上的函数作累积。区域描述、积分次序和面积元必须一致；极坐标变换时面积元包含 Jacobian 因子 $r$。",
        method="先画区域，再选直角坐标切片或极坐标；换积分次序时重写同一区域边界；对称性只有在区域与被积函数满足条件时才可使用。",
        example="在单位圆盘 $D$ 上计算 $\\iint_D(x^2+y^2)dA$。用极坐标得到 $\\int_0^{2\\pi}\\int_0^1r^2\\cdot r\\,drd\\theta=\\pi/2$。",
        exercise="计算 $\\iint_{x^2+y^2\\le1}1\\,dA$。",
        answer="这是单位圆面积；极坐标积分 $\\int_0^{2\\pi}\\int_0^1r\\,drd\\theta=\\pi$。",
    ),
    "math_ode": Profile(
        focus="常微分方程描述未知函数及其导数之间的关系。先辨认阶数、线性与右端类型，再选择分离变量、积分因子或特征方程。",
        method="一阶线性式 $y'+P(x)y=Q(x)$ 使用积分因子 $e^{\\int Pdx}$；二阶常系数式先解特征方程，再按右端形式确定特解。最后代回初值。",
        example="解 $y'+y=e^x$。积分因子为 $e^x$，所以 $(e^xy)'=e^{2x}$，得 $y=\\frac12e^x+Ce^{-x}$。",
        exercise="求 $y'+2y=0$ 的通解。",
        answer="分离变量或使用积分因子，得到 $y=Ce^{-2x}$。",
    ),
    "math_series": Profile(
        focus="无穷级数研究部分和的极限。级数收敛当且仅当部分和序列有有限极限；通项趋零是必要条件但不是充分条件。",
        method="先检查通项，再根据正项、交错或幂级数选择比较、比值、根值或交错级数判别；求和要确认收敛后再使用公式。",
        example="$\\sum_{n=1}^{\\infty}(1/3)^n$ 是首项 $1/3$、公比 $1/3$ 的等比级数，和为 $\\frac{1/3}{1-1/3}=1/2$。",
        exercise="判断 $\\sum_{n=1}^{\\infty}(2/5)^n$ 的敛散性并求和。",
        answer="公比绝对值小于 1，收敛；和为 $(2/5)/(1-2/5)=2/3$。",
    ),
    "math_determinant": Profile(
        focus="行列式是方阵对应的标量，反映可逆性与体积缩放。行变换对行列式的影响需区分交换、倍乘和倍加。",
        method="优先利用三角化、按行列展开或把某行/列变成稀疏；每次初等变换旁边记录行列式因子。判断可逆时可检查行列式是否非零。",
        example="$A=\\begin{pmatrix}1&2\\\\3&5\\end{pmatrix}$，$\\det A=5-6=-1$，故矩阵可逆。若把两行交换，行列式变为 $1$。",
        exercise="计算 $\\begin{vmatrix}2&1\\\\4&3\\end{vmatrix}$，并判断对应矩阵是否可逆。",
        answer="行列式为 $2\\cdot3-1\\cdot4=2$，不为零，矩阵可逆。",
    ),
    "math_matrix": Profile(
        focus="矩阵表示线性变换或线性方程组。乘法通常不可交换；可逆性、秩、伴随矩阵与方程解结构彼此关联。",
        method="先核对矩阵维数，再做行变换或分块运算；用增广矩阵解方程。遇到方阵幂、恒等式或逆矩阵时优先利用结构而非盲目展开。",
        example="解 $x+y=3, x-y=1$。增广矩阵行消元得到 $2x=4$，故 $x=2,y=1$。对应系数矩阵行列式为 $-2\\ne0$，解唯一。",
        exercise="判断 $\\begin{pmatrix}1&2\\\\2&4\\end{pmatrix}$ 是否可逆，并求其秩。",
        answer="第二行是第一行的 2 倍，行列式为 0，不可逆；只有一行线性无关，秩为 1。",
    ),
    "math_vector_system": Profile(
        focus="向量组的秩是其极大线性无关组所含向量数；线性方程组的解的存在性由系数矩阵与增广矩阵的秩比较。",
        method="把向量列成矩阵并行化简；对 $Ax=b$ 比较 $r(A)$ 与 $r(A|b)$，齐次系统解空间维数为未知数个数减秩。",
        example="$A$ 有 3 列且 $r(A)=2$，则 $Ax=0$ 的解空间维数为 $3-2=1$，基础解系含一个线性无关解向量。",
        exercise="矩阵 $A$ 有 5 列且 $r(A)=3$，齐次方程 $Ax=0$ 的解空间维数是多少？",
        answer="由秩—零度定理，维数为 $5-3=2$。",
    ),
    "math_eigen": Profile(
        focus="特征值刻画线性变换在特定方向上的伸缩；相似矩阵表示同一线性变换在不同基下的矩阵。能否对角化取决于线性无关特征向量数。",
        method="解 $\\det(A-\\lambda I)=0$ 求特征值，再求各特征空间维数；相似变换保留特征多项式、行列式和迹。",
        example="$A=\\operatorname{diag}(2,3)$ 的特征值为 2、3，对应特征向量分别为 $(1,0)^T$、$(0,1)^T$，因此已是对角形式。",
        exercise="矩阵 $A=\\begin{pmatrix}4&0\\\\0&-1\\end{pmatrix}$ 的特征值是什么？",
        answer="对角矩阵的特征值为对角元，即 4 和 -1。",
    ),
    "math_quadratic": Profile(
        focus="二次型写成 $x^TAx$，通常取 $A$ 为对称矩阵。正定性可由特征值或顺序主子式判断；合同变换与相似变换不可混为一谈。",
        method="先把交叉项系数平均放到对称矩阵的两个位置；判断正定可检查 Sylvester 顺序主子式，也可求特征值。化标准形时注明变换类型。",
        example="$Q=x_1^2+2x_1x_2+2x_2^2$ 对应 $A=\\begin{pmatrix}1&1\\\\1&2\\end{pmatrix}$，顺序主子式为 $1,1$，均正，故 $Q$ 正定。",
        exercise="判断 $Q=2x_1^2+2x_1x_2+2x_2^2$ 是否正定。",
        answer="对应矩阵 $\\begin{pmatrix}2&1\\\\1&2\\end{pmatrix}$ 的顺序主子式为 2 和 3，均正，故正定。",
    ),
    "ds_list": Profile(
        focus="线性表按逻辑次序组织元素，顺序表支持按下标常数时间访问；链表靠指针连接，插删局部灵活但按位查找需要遍历。",
        method="先确定存储结构和下标约定，再数需要移动或访问的元素；链表操作要分别检查头结点、尾结点和空表。",
        example="长度为 $n$ 的顺序表在下标 1 插入元素（下标从 0 开始），需将原下标 1 到 $n-1$ 的元素后移，共 $n-1$ 次移动。",
        exercise="长度为 8 的顺序表在尾部追加元素，需要移动多少个原元素？",
        answer="尾部追加不需要移动原元素，移动次数为 0；若需要扩容，另计扩容复制。",
    ),
    "ds_stack_queue": Profile(
        focus="栈是后进先出，队列是先进先出。区分逻辑操作顺序与数组/链式存储实现，循环队列还要确认空满判定约定。",
        method="按操作序列逐步记录栈顶或队头队尾；遇到循环队列先标明容量、是否留空槽以及 front/rear 的定义。",
        example="栈依次执行 push(1), push(2), pop(), push(3), pop(), pop()，弹出序列为 2、3、1。",
        exercise="空栈依次 push(A), push(B), pop(), push(C), pop(), pop()，弹出序列是什么？",
        answer="依次弹出 B、C、A。",
    ),
    "ds_tree": Profile(
        focus="树通过父子关系表达层次。二叉树遍历顺序的区别在根的位置；树、森林、线索树与二叉搜索树各有不同结构约束。",
        method="做遍历先画树，再严格按根左右/左根右/左右根的定义递归；由遍历序列还原时要确认序列组合是否足以唯一确定。",
        example="根 A、左子 B、右子 C 的二叉树，先序为 A B C，中序为 B A C，后序为 B C A。",
        exercise="对上述树写出层序遍历序列。",
        answer="从根开始按层从左到右访问，层序为 A、B、C。",
    ),
    "ds_graph": Profile(
        focus="图由顶点和边组成，邻接矩阵便于判边，邻接表适合稀疏图。DFS/BFS 遍历；最短路、生成树、拓扑排序有各自适用条件。",
        method="先识别有向/无向、权值和连通性，再选择算法；Dijkstra 要求非负边权，拓扑排序只适用于 DAG。手算时记录已确定集合或队列。",
        example="无权图中 A 与 B、C 相邻，B 与 D 相邻，C 与 D 相邻。以 A 做 BFS，队列访问层次为 A；B、C；D。",
        exercise="有向图存在环时，是否一定能完成拓扑排序？",
        answer="不能。拓扑排序存在的必要充分条件是有向图无环；有环时无法给所有顶点排出满足边方向的线性序。",
    ),
    "ds_sort_search": Profile(
        focus="查找关注关键字定位；排序关注记录次序。复杂度、稳定性、是否原地是不同指标，不能由一个指标推出另一个。",
        method="先确认输入是否有序、数据存储方式和算法边界，再按算法步骤追踪；分析排序要明确最坏/平均/最好情形。",
        example="在有序数组 [2,5,8,12,17,23,31] 中二分查找 17，依次比较中间元素 12、23、17，找到目标。",
        exercise="折半查找能否直接用于无序顺序表？说明原因。",
        answer="不能保证正确。折半查找每次丢弃一半区间依赖关键字有序这一条件。",
    ),
    "ds_hash": Profile(
        focus="散列表通过哈希函数把关键字映射到表地址，冲突处理方式决定探查或链结构；装填因子影响冲突概率。",
        method="按题目给出的哈希函数和冲突策略逐项插入；开放定址要继续探查到空槽，删除还需处理墓碑标记。",
        example="表长 7，$h(k)=k\\bmod7$，线性探查插入 10、17：二者初始地址均为 3，17 冲突后放到地址 4。",
        exercise="继续向上述表插入 24，采用线性探查，放在哪个地址？",
        answer="初始地址仍为 3，3 和 4 已占用，故放到地址 5。",
    ),
    "co_number": Profile(
        focus="机器数的位串解释取决于位宽与编码。补码可统一加减法，但要区分进位与溢出；浮点表示还受阶码、尾数和舍入影响。",
        method="先写出位宽、编码及是否截断，再转换成位串逐位计算；补码溢出看两个同号数相加后结果符号是否改变。",
        example="8 位补码表示 $-5$：$5=00000101$，按位取反为 11111010，再加 1 得 11111011。",
        exercise="8 位补码计算 $7+3$，是否溢出？",
        answer="00000111+00000011=00001010，即 10，未溢出。8 位补码范围是 -128 至 127。",
    ),
    "co_memory": Profile(
        focus="存储层次利用局部性缩小平均访问时间。Cache 地址划分由块大小、组数和地址位宽决定；TLB 未命中不等于缺页。",
        method="明确字节/字编址，先算块内偏移位，再按组数算索引位，剩余为标记位；虚拟地址转换逐步检查 TLB、页表和缺页。",
        example="32 位字节编址，Cache 容量 16 KiB、块 64 B、直接映射。偏移 6 位、行数 256、索引 8 位，标记 18 位。",
        exercise="同一 Cache 若块大小变为 32 B、容量不变，直接映射的块内偏移和索引各几位？",
        answer="偏移为 $\\log_2 32=5$ 位；行数 $16384/32=512$，索引 9 位。",
    ),
    "co_cpu": Profile(
        focus="CPU 按指令系统约定取指、译码、执行并更新状态。寻址方式决定有效地址；数据通路和控制信号决定部件如何协同。",
        method="先拆字段和寻址方式，再计算有效地址；流水线题要区分结构、数据、控制冒险及解决机制，不把流水级数直接当加速比。",
        example="基址寻址中基址寄存器内容为 1000、指令位移为 24，则有效地址为 1024（按题设单位计算）。",
        exercise="PC 相对寻址的有效地址通常由哪两部分相加得到？",
        answer="由下一条指令地址（或题目约定的 PC 值）与有符号位移相加；必须遵循题目明确的 PC 更新时机。",
    ),
    "co_io": Profile(
        focus="总线连接多个部件并按时序传递地址、数据和控制信号。程序查询、中断和 DMA 是不同 I/O 控制方式，CPU 参与程度不同。",
        method="带宽题统一单位后计算；DMA 题分清初始化、块传送与完成中断；总线定时题沿时间顺序标出请求、授权和数据阶段。",
        example="设备用 DMA 传送一块数据时，CPU 设置首地址、长度和方向，DMA 控制器完成块传输后再以中断通知 CPU。",
        exercise="DMA 传输期间，CPU 是否完全不能运行其他指令？",
        answer="不一定。DMA 可与 CPU 并行工作，但会竞争总线，可能带来访存等待；具体以题目总线仲裁模型为准。",
    ),
    "os_process": Profile(
        focus="进程承载资源与执行状态，线程是执行流。调度把就绪进程分配给 CPU；等待事件的阻塞态不同于只是等待 CPU 的就绪态。",
        method="调度题画时间轴，按到达、抢占与时间片规则推进；完成时间减到达时间得周转时间，再除服务时间得带权周转时间。",
        example="P1 在 0 时刻到达、运行 3 单位；P2 在 1 时刻到达、运行 1 单位，非抢占 FCFS 下 P1 先运行至 3，再运行 P2 至 4。",
        exercise="上例中 P2 的周转时间是多少？",
        answer="P2 完成于 4、到达于 1，周转时间为 3 个时间单位。",
    ),
    "os_sync": Profile(
        focus="并发程序的执行顺序不确定，共享状态需要互斥与同步约束。信号量既可计数资源，也可保护临界区，但 P/V 顺序会影响正确性。",
        method="先列出共享资源和不变量，再写进入/离开临界区的 P/V 操作；逐步模拟并检查是否死锁、越界或丢失唤醒。",
        example="单一临界区用初值为 1 的互斥信号量 mutex：进区前 P(mutex)，离区后 V(mutex)，保证同一时刻至多一个线程进入。",
        exercise="若互斥信号量初值误设为 2，能否保证互斥？",
        answer="不能。最多允许两个执行流同时通过 P 操作进入临界区，破坏互斥。",
    ),
    "os_deadlock": Profile(
        focus="死锁需同时具备互斥、占有并等待、不可剥夺、循环等待四个条件。安全状态与当前是否阻塞不是同一概念。",
        method="分析资源分配图或银行家算法；先检查可用资源能否满足某进程的剩余需求，再释放其资源并继续寻找安全序列。",
        example="若仅有一个资源实例，P1 持有资源 R 并等待 S，P2 持有 S 并等待 R，就形成等待环，可能发生死锁。",
        exercise="破坏四个必要条件之一，能否从理论上避免死锁？",
        answer="可以。死锁四条件必须同时成立；预防策略通过保证至少一个条件不成立来避免死锁。",
    ),
    "os_memory": Profile(
        focus="操作系统内存管理从逻辑地址映射到物理内存。分页按页/页框管理；页面置换在缺页且无空闲页框时选择淘汰对象。",
        method="地址题拆页号与页内偏移；置换题每次访问都更新算法状态。FIFO 看进入时间，LRU 看最近使用时间。",
        example="3 个空页框按 FIFO 访问 1,2,3,1,4。访问 4 时页 1 最早装入，故被淘汰；命中页 1 不改变 FIFO 顺序。",
        exercise="对序列 1,2,3,1,4 使用 LRU，访问 4 时淘汰哪个页？",
        answer="淘汰页 2，因为访问 1 后，页 2 是最近最久未使用者。",
    ),
    "os_file": Profile(
        focus="文件系统用目录组织命名空间，以控制块/inode 保存元数据，并管理文件数据块、空闲空间和访问权限。设备管理还包括缓冲与 I/O 调度。",
        method="文件分配题明确连续、链接或索引结构，追踪逻辑块到物理块的映射；目录题区分路径名、目录项和文件控制信息。",
        example="索引分配中，文件的索引块保存各数据块号；访问第 $i$ 个逻辑块时先定位索引项，再按块号访问数据。",
        exercise="连续分配的主要优点和典型缺点各是什么？",
        answer="优点是顺序/随机访问简单高效；缺点是外部碎片，并且扩展文件可能需要移动或重新分配空间。",
    ),
    "net_physical": Profile(
        focus="物理层将比特表示为信号并通过介质传输。速率、带宽、码元率、传播时延是不同概念；香农/奈奎斯特公式的假设不能混用。",
        method="通信计算先统一 bit、Hz、秒等单位；传播时延用距离除传播速度，发送时延用数据长度除链路速率。",
        example="发送 12000 bit 数据，链路速率 2 Mbit/s，发送时延为 $12000/2000000=0.006$ s，即 6 ms。",
        exercise="长度 1.5 km 的链路传播速度为 $2\\times10^8$ m/s，传播时延是多少？",
        answer="$1500/(2\\times10^8)=7.5\\times10^{-6}$ s，即 7.5 μs。",
    ),
    "net_link": Profile(
        focus="数据链路层把网络层分组封装为帧，并处理链路寻址、差错检测及介质访问。交换机依据源 MAC 学习转发表，VLAN 会划分广播域。",
        method="帧题按封装字段和发送时序分析；CRC 题做模 2 除法；MAC 题区分随机接入、冲突检测/避免及交换网络转发。",
        example="CRC 发送端对数据后补 0，再用生成多项式做模 2 长除，余数附加到数据末尾；接收端对整个码字除法检查余数。",
        exercise="以太网交换机收到目的 MAC 尚未学习过的帧，通常如何处理？",
        answer="交换机学习源 MAC 与入端口的映射，并将未知目的帧泛洪到该 VLAN 内除入端口外的其他端口。",
    ),
    "net_network": Profile(
        focus="网络层负责跨网络转发。IPv4/CIDR 用前缀区分网络与主机部分；路由器通常采用最长前缀匹配选择下一跳。",
        method="子网题先明确前缀长度和地址边界；路由题逐条比较目标地址与表项前缀，选择匹配位数最长者。",
        example="$192.168.10.77/26$ 的块大小为 64，所在网段为 $192.168.10.64/26$，广播地址为 .127。",
        exercise="$10.0.0.130/25$ 属于哪个网络地址？",
        answer="/25 子网块大小为 128，130 落在 128–255，网络地址为 $10.0.0.128/25$。",
    ),
    "net_transport": Profile(
        focus="传输层实现进程间通信。UDP 面向数据报；TCP 提供可靠字节流，序号按字节编号。流量控制保护接收方，拥塞控制保护网络。",
        method="TCP 题画时间线并按字节计算序号/确认号；吞吐与窗口题统一单位，并分别识别接收窗口、拥塞窗口和往返时延。",
        example="首字节序号为 1000 的 TCP 段携带 500 字节且全部正确收到，累计确认号为 1500，表示下一期待字节。",
        exercise="首字节序号 700 的段携带 120 字节，接收方确认号是多少？",
        answer="累计确认号为 $700+120=820$。",
    ),
    "net_application": Profile(
        focus="应用层协议定义应用进程交换消息的格式和语义。DNS 解析名称，HTTP 描述请求/响应；性能题还需区分带宽、吞吐和时延组成。",
        method="协议题按客户机/服务器角色、请求顺序和缓存状态追踪；时延题分解发送、传播、处理和排队部分。",
        example="浏览器访问新域名时，先查询本地/递归 DNS 缓存；未命中则解析获得 IP，随后建立传输连接并发送 HTTP 请求。",
        exercise="DNS 递归查询与迭代查询的主要区别是什么？",
        answer="递归查询要求被查询服务器替客户端继续查询并返回最终结果；迭代查询返回下一步可联系的服务器信息，由客户端/解析器继续。",
    ),
    "general_math": Profile(
        focus="本节点是数学二课程的组织节点，下面列出所属知识链。学习时应把定义、运算条件、典型方法和跨章联系连起来。",
        method="读题后先识别对象与目标，再列出可用定理及前提；计算后代回原条件检查。",
        example="若高等数学中 $F(x)=\\int_0^{x^2}e^{-t^2}dt$，由变上限积分求导和链式法则，$F'(x)=2xe^{-x^4}$。",
        exercise="若 $G(x)=\\int_1^{3x}t^2dt$，求 $G'(x)$。",
        answer="由链式法则，$G'(x)=(3x)^2\\cdot3=27x^2$。",
    ),
    "general_408": Profile(
        focus="本节点用于组织 408 四门课程。综合分析时明确抽象层次：数据结构组织信息，组成原理执行指令，操作系统管理资源，网络传递数据。",
        method="遇到综合题画结构或状态变化图，标清输入、状态、操作和输出；再按课程原理逐步推演。",
        example="程序通过网络读取文件，可从应用请求向下追踪 HTTP/TCP/IP、网卡 DMA、操作系统缓冲和文件系统，再沿接收路径返回。",
        exercise="文件通过 TCP 发送时，TCP 直接理解文件格式吗？",
        answer="不理解。TCP 提供字节流传输；文件格式由上层应用定义，TCP 负责传输与可靠性机制。",
    ),
}


def _profile(node: dict, parent_names: dict[str, str]) -> Profile:
    code = node["code"]
    name = node["name"]
    parent = node.get("parent_code") or ""
    subject = node.get("subject", "")
    if subject in {"考研数学", "数学二"} or code.startswith("math."):
        if code in {"math.calculus", "math.calculus.exam.comprehensive", "math.linear-algebra"}:
            return PROFILES["general_math"]
        if any(x in name for x in ("二重积分", "极坐标", "积分区域", "黎曼和")):
            return PROFILES["math_double_integral"]
        if "微分方程" in name or "降阶" in name:
            return PROFILES["math_ode"]
        if "二次型" in name or "合同变换" in name or "规范形" in name:
            return PROFILES["math_quadratic"]
        if any(x in name for x in ("行列式",)):
            return PROFILES["math_determinant"]
        if any(x in name for x in ("特征值", "特征向量", "相似对角化", "相似")):
            return PROFILES["math_eigen"]
        if any(x in name for x in ("线性方程组", "向量组", "线性表示", "极大无关组", "秩与")):
            return PROFILES["math_vector_system"]
        if any(x in name for x in ("矩阵", "伴随", "幂零", "置换")):
            return PROFILES["math_matrix"]
        if any(x in name for x in ("级数", "敛散性", "等比级数")):
            return PROFILES["math_series"]
        if any(x in name for x in ("偏导", "多元", "二元", "Hessian", "全微分")):
            return PROFILES["math_multivariable"]
        if any(x in name for x in ("极限", "连续", "无穷小", "洛必达", "泰勒")):
            return PROFILES["math_limit"]
        if any(x in name for x in ("积分", "引力", "物理应用", "旋转体")):
            return PROFILES["math_integral"]
        if any(x in name for x in ("极值", "最值", "导数", "微分", "曲率", "凹凸", "拐点", "中值", "渐近")):
            return PROFILES["math_application" if any(x in name for x in ("极值", "最值", "凹凸", "拐点", "中值", "渐近", "曲率")) else "math_derivative"]
        if parent.startswith("math.linear-algebra"):
            return PROFILES["math_matrix"]
        if parent.startswith("math.calculus"):
            return PROFILES["general_math"]
        return PROFILES["general_math"]

    if code == "cs408":
        return PROFILES["general_408"]
    if parent == "cs408.ds" or subject == "408" and code.startswith("cs408.ds"):
        if any(x in name.lower() for x in ("散列", "哈希")):
            return PROFILES["ds_hash"]
        if any(x in name for x in ("树", "遍历", "哈夫曼")):
            return PROFILES["ds_tree"]
        if any(x in name for x in ("图", "拓扑", "最短", "网络", "生成树")):
            return PROFILES["ds_graph"]
        if any(x in name for x in ("排序", "查找", "二分", "折半")):
            return PROFILES["ds_sort_search"]
        if any(x in name for x in ("栈", "队列")):
            return PROFILES["ds_stack_queue"]
        return PROFILES["ds_list"]
    if parent == "cs408.co" or subject == "408" and code.startswith("cs408.co"):
        if any(x in name.lower() for x in ("cache", "主存", "存储器", "虚拟存储")):
            return PROFILES["co_memory"]
        if any(x in name for x in ("总线", "I/O", "中断", "DMA")):
            return PROFILES["co_io"]
        if any(x in name for x in ("补", "浮点", "定点", "编码", "运算", "IEEE")):
            return PROFILES["co_number"]
        return PROFILES["co_cpu"]
    if parent == "cs408.os" or subject == "408" and code.startswith("cs408.os"):
        if any(x in name for x in ("死锁",)):
            return PROFILES["os_deadlock"]
        if any(x in name for x in ("同步", "互斥", "信号量", "通信")):
            return PROFILES["os_sync"]
        if any(x in name for x in ("内存", "页", "虚拟", "置换", "分配")):
            return PROFILES["os_memory"]
        if any(x in name for x in ("文件", "目录", "磁盘", "I/O", "设备", "缓冲", "假脱机")):
            return PROFILES["os_file"]
        return PROFILES["os_process"]
    if parent == "cs408.cn" or subject == "408" and code.startswith("cs408.cn"):
        if any(x in name.upper() for x in ("TCP", "UDP", "拥塞", "流量", "连接管理")):
            return PROFILES["net_transport"]
        if any(x in name.upper() for x in ("IPV4", "IPV6", "CIDR", "NAT", "路由", "ARP", "DHCP", "ICMP", "分组与地址")):
            return PROFILES["net_network"]
        if any(x in name.upper() for x in ("MAC", "以太网", "VLAN", "帧", "链路", "CRC")):
            return PROFILES["net_link"]
        if any(x in name.upper() for x in ("DNS", "HTTP", "WWW", "FTP", "应用", "电子邮件")):
            return PROFILES["net_application"]
        if any(x in name for x in ("介质", "信道", "奈奎斯特", "香农", "物理", "通信基础")):
            return PROFILES["net_physical"]
        return PROFILES["net_application"]

    # 分类节点或未预见的代码，按父节点所在学科回退，不生成未经证据支持的题目标签。
    parent_name = parent_names.get(parent, "")
    if "数据结构" in parent_name:
        return PROFILES["ds_list"]
    if "组成原理" in parent_name:
        return PROFILES["co_cpu"]
    if "操作系统" in parent_name:
        return PROFILES["os_process"]
    if "计算机网络" in parent_name:
        return PROFILES["net_application"]
    return PROFILES["general_math"]


def _all_nodes() -> tuple[list[dict], dict[str, int], dict[str, str]]:
    syllabus = json.loads((PROJECT_ROOT / "seed" / "syllabus.json").read_text(encoding="utf-8"))
    nodes: list[dict] = []
    parent_names: dict[str, str] = {}

    def walk(rows: list[dict], parent_code: str | None = None) -> None:
        for row in rows:
            node = {**row, "subject": syllabus["subject"], "parent_code": parent_code, "is_reference_only": False}
            nodes.append(node)
            parent_names[node["code"]] = node["name"]
            walk(row.get("children", []), node["code"])

    walk(syllabus["nodes"])
    exam_nodes, references = build_exam_reference_seed()
    for node in exam_nodes:
        nodes.append(node)
        parent_names[node["code"]] = node["name"]
    # Unify the duplicate stable code, if a future source maps a label directly to a normal node.
    unique = {node["code"]: node for node in nodes}
    ref_counts: dict[str, int] = {}
    for ref in references:
        code = ref["knowledge_point_code"]
        ref_counts[code] = ref_counts.get(code, 0) + 1
    return list(unique.values()), ref_counts, parent_names


def _render(node: dict, references: list[dict], parent_names: dict[str, str], nodes: list[dict]) -> str:
    profile = _profile(node, parent_names)
    parent_code = node.get("parent_code") or ""
    parent_name = parent_names.get(parent_code, "课程总览")
    is_reference_only = bool(node.get("is_reference_only"))
    is_family = ".family." in node["code"]
    children = [item["name"] for item in nodes if item.get("parent_code") == node["code"]]
    framing = (
        "本专题由项目按年度来源标签归并，便于跨年浏览；不是官方命题分类。"
        if is_family
        else (
            "本页针对知识树中的考点标签作概念复习，标签来自第三方/人工索引，不等同官方命题标注。"
            if is_reference_only
            else "本页按本项目知识树的课程结构原创整理，实际考试边界以当年正式考试说明为准。"
        )
    )
    if node.get("is_assessable"):
        scope = f"该节点属于“{parent_name}”，关注：**{node['name']}**。"
    elif children:
        scope = f"这是“{parent_name}”下的组织节点，包含：{'、'.join(children)}。"
    else:
        scope = (
            f"这是按历年真题索引整理的考点条目，归属“{parent_name}”，索引主题为**{node['name']}**。"
            "下文提供该主题的概念框架与原创例题；索引标签不代表官方大纲的唯一分类。"
        )
    if references:
        ref_lines = ["| 年份 | 题号 | 索引考点 |", "| ---: | ---: | --- |"]
        ref_lines.extend(
            f"| {ref['year']} | 第 {ref['question_number']} 题 | {ref['topic_label']} |"
            for ref in references
        )
        refs = "本节点可直接用下列原卷题目练习。索引只提供题号与来源，不包含原卷题干或答案；请打开来源或桌面原卷作答。\n\n" + "\n".join(ref_lines)
    else:
        refs = "本节点没有直接关联的题号索引。若这是组织节点，请沿子节点查看真题；若为可考核叶子，后续可在知识树中为它补充经核对的真题来源。"
    return f"""<!-- knowledge-node-lesson:v1; code={node['code']} -->
# {node['name']}

> {node.get('subject', '考研复习')} · 上级节点：{parent_name}  
> {framing}

## 一、概念讲解

{scope}

{profile.focus}

**读题时要抓住的核心：**先确认题目考查的对象和目标，再把节点名称对应到定义、成立条件、操作步骤或判别标准；不要只凭关键词套公式。涉及子主题时，回到上级“{parent_name}”检查知识边界。

## 二、解题方法

{profile.method}

**自查顺序：**①对象/变量和边界是否明确；②使用的定理或算法是否满足条件；③计算/状态更新是否逐步可复核；④结果是否代回题意检查。

## 三、例题讲解（原创）

{profile.example}

## 四、历年真题练习入口

{refs}

在知识树节点详情的“历年真题”页签中可以打开题目来源，并把原卷任务加入今日学习。完成后按真实表现自评；没有嵌入题干时，不应把题号索引误当成完整题目。
"""


def _ensure_sections(path: Path, node: dict, references: list[dict], parent_names: dict[str, str], nodes: list[dict]) -> bool:
    """保留原有人工讲解，在缺少概念、例题或真题练习入口时补充。"""
    text = path.read_text(encoding="utf-8")
    profile = _profile(node, parent_names)
    additions: list[str] = []
    needs_supplement = SUPPLEMENT_MARKER not in text
    if needs_supplement and "概念" not in text and "知识点地图" not in text:
        additions.extend(["## 本节点概念摘要", "", profile.focus, ""])
    if needs_supplement and "例题" not in text and "原创例题" not in text:
        additions.extend(["## 补充例题讲解（原创）", "", profile.example, ""])
    if additions:
        additions.insert(0, SUPPLEMENT_MARKER)
    if REFERENCE_MARKER not in text:
        if references:
            additions.extend([REFERENCE_MARKER, "", "## 历年真题练习入口", "", "| 年份 | 题号 | 索引考点 |", "| ---: | ---: | --- |"])
            additions.extend(
                f"| {ref['year']} | 第 {ref['question_number']} 题 | {ref['topic_label']} |"
                for ref in references
            )
        else:
            additions.extend([REFERENCE_MARKER, "", "## 历年真题练习入口", "", "该节点当前没有直接关联的真题索引；可先沿知识树子节点查看真题。"])
    if not additions:
        return False
    path.write_text(text.rstrip() + "\n\n" + "\n".join(additions) + "\n", encoding="utf-8")
    return True


def generate(*, check: bool = False) -> dict[str, int]:
    nodes, _, parent_names = _all_nodes()
    refs_by_code: dict[str, list[dict]] = {}
    _, reference_rows = build_exam_reference_seed()
    for ref in reference_rows:
        refs_by_code.setdefault(ref["knowledge_point_code"], []).append(ref)
    for rows in refs_by_code.values():
        rows.sort(key=lambda ref: (ref["year"], ref["question_number"], ref["topic_label"]))
    LESSON_DIR.mkdir(parents=True, exist_ok=True)
    created = augmented = updated = complete = 0
    missing: list[str] = []
    outdated: list[str] = []
    for node in nodes:
        path = LESSON_DIR / f"{node['code']}.md"
        if not path.exists():
            missing.append(node["code"])
            if not check:
                path.write_text(
                    _render(node, refs_by_code.get(node["code"], []), parent_names, nodes),
                    encoding="utf-8",
                    newline="\n",
                )
                created += 1
        elif path.read_text(encoding="utf-8").startswith("<!-- knowledge-node-lesson:v1;"):
            desired = _render(node, refs_by_code.get(node["code"], []), parent_names, nodes)
            if path.read_text(encoding="utf-8") != desired:
                outdated.append(node["code"])
                if not check:
                    path.write_text(desired, encoding="utf-8", newline="\n")
                    updated += 1
        elif not check:
            if _ensure_sections(path, node, refs_by_code.get(node["code"], []), parent_names, nodes):
                augmented += 1
        if path.exists() or not check:
            complete += 1
    result = {"nodes": len(nodes), "created": created, "updated": updated, "augmented": augmented, "lesson_files": complete, "missing": len(missing), "outdated": len(outdated)}
    if check and missing:
        for code in missing[:30]:
            print(f"missing: {code}")
    if check and outdated:
        for code in outdated[:30]:
            print(f"outdated: {code}")
    print(result)
    return result


if __name__ == "__main__":
    generate(check="--check" in sys.argv[1:])
