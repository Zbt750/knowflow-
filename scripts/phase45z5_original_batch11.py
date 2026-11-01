"""Eleventh offline-authored public-original batch for the owned isolated DB."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.phase45z5_original_batch01 import run as run_batch, sha_file  # noqa: E402
from scripts.phase45z5_original_batch02 import item  # noqa: E402

BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch10/post-batch10.dump"
BACKUP_SHA256 = "C92B7C213E58FD840FCD293F21A2A73C6D55D0C11057D648958009F70EEDA55D"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch11-retry2"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"


def candidates():
    return [
        # Mathematics II (5)
        item("z5b11-math-secant-slope-convexity", "math.exam.423bee85b09f", "A",
            "对x>0定义g(x)=ln(1+x)−ln x。关于g的单调性与凹凸性，正确的是（ ）。",
            {"A": "严格递减且严格凸", "B": "严格递增且严格凸", "C": "严格递减且严格凹", "D": "严格递增且严格凹"},
            "g'(x)=1/(1+x)−1/x=−1/[x(x+1)]<0，所以g严格递减。再求导，g''(x)=(2x+1)/[x²(x+1)²]>0，因此g严格凸。也可写成g(x)=ln(1+1/x)，但对其求导仍须注意1/x随x递减。",
            [("differentiate_difference", "分别求两项导数得到g'=-1/[x(x+1)]，故严格递减。"),
             ("second_derivative_sign", "求g''=(2x+1)/[x²(x+1)²]>0，故严格凸。")],
            [("monotonicity", "分母x(x+1)>0，因此g'<0。"),
             ("convexity", "g''的分子、分母在x>0均为正，因此g''>0。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要对对数差连续求两阶导数并分别判断单调性与凹凸性。",
             "直接微分与化为ln(1+1/x)后检查导数符号相互核对。",
             "g'为负但g''为正；单调递减不代表凹，二阶导数决定凹凸。",
             "把割线斜率相关的对数差转化为严格单调和凸性判断。"),
            ["凹凸函数与割线斜率单调性", "对数函数", "二阶导数"], difficulty="medium"),

        item("z5b11-math-vector-span-parameter", "math.exam.44eab8b0d00b", "C",
            "向量a=(1,1,0)、b=(0,1,1)。向量vλ=(2,λ,4)属于span{a,b}时，λ及其在(a,b)下的坐标依次为（ ）。",
            {"A": "λ=4，(2,4)", "B": "λ=5，(2,4)", "C": "λ=6，(2,4)", "D": "λ=6，(4,2)"},
            "设vλ=αa+βb，则(α,α+β,β)=(2,λ,4)。前后两坐标分别给出α=2、β=4，中间坐标必须满足λ=α+β=6。因此向量确在该张成空间中，且表示系数唯一。",
            [("coordinate_equations", "逐坐标比较得到α=2、β=4以及λ=α+β=6。"),
             ("span_plane_equation", "a、b张成平面满足x−y+z=0；代入(2,λ,4)得λ=6。")],
            [("linear_combination", "2a+4b=(2,6,4)，直接验证所求λ与坐标。"),
             ("independence", "a、b不成比例，线性无关，坐标(2,4)唯一。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("要同时检验向量是否属于由两向量张成的空间并求其唯一坐标。",
             "解线性组合方程，并用张成平面的线性约束独立核验。",
             "两个自由坐标确定组合系数，第三坐标是参数约束，不能遗漏。",
             "联结向量组线性表示、张成空间判定和坐标唯一性。"),
            ["向量组之间的线性表示", "向量组线性相关性", "线性方程组"]),

        item("z5b11-math-improper-sine-remainder-parameter", "math.exam.a62c828f6537", "B",
            "讨论反常积分I(p)=∫₀¹(x−sin x)/xᵖ dx的敛散性。其收敛的充要条件是（ ）。",
            {"A": "p<3", "B": "p<4", "C": "p≤4", "D": "任意实数p"},
            "唯一可能的反常点是x=0。由Taylor展开x−sin x=x³/6+o(x³)，故被积函数与(1/6)x^{3−p}等价。∫₀¹x^q dx当且仅当q>−1收敛，因此3−p>−1，即p<4；p=4时与1/(6x)同阶而发散。",
            [("taylor_limit_comparison", "lim_{x→0+}(x−sin x)/x³=1/6，化为幂函数比较。"),
             ("power_integral_threshold", "指数3−p须大于−1，得到严格条件p<4。")],
            [("endpoint_analysis", "x=1处被积函数连续；只需检查0端点。"),
             ("boundary_case", "p=4时 integrand~1/(6x)，对数发散；p<4收敛。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要先识别三阶消去后的首个非零项，再将参数问题化为幂积分临界值。",
             "Taylor首项和极限比较给出同一等价阶，随后检查临界端点。",
             "分子不是与x等价而是与x³等价；临界指数处仍发散，不能写成p≤4。",
             "训练带参数反常积分中的局部阶数估计和端点临界分类。"),
            ["端点比较与参数范围", "反常积分", "Taylor展开"], difficulty="medium"),

        item("z5b11-math-quadratic-form-congruence-inertia", "math.exam.7af99f485eff", "D",
            "二次型Qₐ(x,y)=x²+4xy+(4+a)y²。按实数a分类，下列说法正确的是（ ）。",
            {"A": "a>0时负定，a=0时秩2", "B": "a<0时正定，a=0时秩1", "C": "任意a均非退化", "D": "a>0时正定，a=0时秩1半正定，a<0时不定"},
            "作可逆线性替换u=x+2y，可得Qₐ=u²+ay²。该变换是合同变换，不改变惯性指数。a>0时两个平方项系数均正，正定；a=0时为u²，秩1且半正定；a<0时一正一负，正负惯性指数各1，故不定。",
            [("complete_square_congruence", "配方得Q=(x+2y)²+ay²，变换矩阵可逆。"),
             ("principal_minor_classification", "矩阵首顺序主子式1>0、行列式a，分别判定a正、零、负三类。")],
            [("rank_and_inertia", "a=0时规范形diag(1,0)，秩1；a<0时diag(1,a)一正一负。"),
             ("positive_definiteness", "a>0时规范形两个对角系数均正，严格正定。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("须通过可逆合同变换得到规范形，并依据系数符号分别处理参数临界值。",
            "配方规范形、主子式符号分类与参数边界结论相互校验。",
             "行列式为零的a=0仍可半正定但降秩；a<0时不是负定而是不定。",
             "综合二次型配方、合同变换、秩和惯性指数判断。"),
            ["合同变换与规范形", "二次型", "惯性指数"], difficulty="medium"),

        item("z5b11-math-adjugate-linear-system", "math.exam.8b6ba0b9a789", "A",
            "矩阵A=[[2,1],[1,2]]，向量b=(1,3)ᵀ。用伴随矩阵表示A⁻¹并求解Ax=b，解向量为（ ）。",
            {"A": "(−1/3, 5/3)ᵀ", "B": "(1/3, 5/3)ᵀ", "C": "(−1/3, 3/5)ᵀ", "D": "(5/3, −1/3)ᵀ"},
            "det(A)=4−1=3，adj(A)=[[2,−1],[−1,2]]，故A⁻¹=(1/3)adj(A)。计算adj(A)b=(-1,5)ᵀ，得到x=(-1/3,5/3)ᵀ。代回可得2(-1/3)+5/3=1，且-1/3+2(5/3)=3。",
            [("adjugate_formula", "det(A)=3且adj(A)b=(-1,5)，由A⁻¹=adj(A)/det(A)求解。"),
             ("direct_elimination", "方程组2x+y=1、x+2y=3解得x=−1/3、y=5/3。")],
            [("determinant_and_adjugate", "二阶矩阵伴随为交换主对角元并改变非对角元符号。"),
             ("substitution_check", "将解代回两行方程分别得到1和3。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要检查矩阵可逆性、构造伴随矩阵并将线性系统解回向量，再代回验证。",
            "伴随矩阵公式和高斯消元分别求解，再将结果代回原方程组核对。",
             "伴随矩阵需乘1/det(A)；漏除行列式会造成整体倍数错误。",
             "把伴随矩阵、逆矩阵和线性方程组解联系起来。"),
            ["伴随矩阵与逆矩阵", "矩阵运算", "线性方程组"]),

        # Computer Science 408 (15)
        item("z5b11-408-selection-sort-stability-trace", "cs408.ds.topic.ddb8a6a53756", "B",
            "对记录序列[4a,2,4b,1]执行标准直接选择排序：每趟在未排序区选择首个最小记录并与区首交换，比较采用严格小于。排序结束时，关键字比较次数及算法稳定性为（ ）。",
            {"A": "6次，稳定", "B": "6次，不稳定", "C": "5次，不稳定", "D": "7次，稳定"},
            "n=4的直接选择排序比较次数固定为3+2+1=6。第一趟将1与首元素4a交换，序列变为[1,2,4b,4a]；后续趟次不会恢复两个相等记录的相对顺序。因此最终4b仍先于4a，算法不稳定。",
            [("comparison_count", "三趟未排序区长度为4、3、2，合计3+2+1=6。"),
             ("tagged_record_trace", "首趟交换把4a越过4b，原相对次序改变，证明不稳定。")],
            [("algorithm_invariant", "每趟固定扫描剩余区，因此比较次数与输入排列无关。"),
             ("stability_counterexample", "带标签相等键4a、4b在一次长距离交换后逆序。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要同时推演选择排序的区间扫描成本和带相同关键字记录的交换影响。",
             "比较次数由公式计算，稳定性用明确反例追踪。",
             "严格小于处理相等项并不能消除远距离交换造成的相对次序改变。",
             "从操作轨迹而非仅凭稳定排序表格判断算法性质。"),
            ["简单选择排序", "排序算法稳定性", "比较次数"]),

        item("z5b11-408-postorder-from-pre-in", "cs408.ds.topic.de07cf385c9a", "A",
            "某二叉树的先序序列为A、B、D、E、C、F，中序序列为D、B、E、A、C、F。其后序遍历序列为（ ）。",
            {"A": "D、E、B、F、C、A", "B": "D、B、E、F、C、A", "C": "E、D、B、C、F、A", "D": "F、C、D、E、B、A"},
            "先序首项A为根。中序中A左侧为D、B、E，右侧为C、F。左子树先序为B、D、E，因此B的左右孩子分别是D、E；右子树先序为C、F且中序为C、F，因此C的右孩子为F。后序按左、右、根得到D、E、B、F、C、A。",
            [("preorder_inorder_reconstruction", "由根A划分左右子树，再递归确定B、C子树结构。"),
             ("postorder_walk", "逐子树按左—右—根输出D,E,B与F,C，最后输出A。")],
            [("left_subtree", "左子树根B，叶结点D、E的后序为D,E,B。"),
             ("right_subtree", "右子树C只有右孩子F，后序F,C；与左树合并后根为A。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需由先序和中序递归恢复结构，再执行不同顺序的后序遍历。",
             "左右子树划分与逐树遍历两步校验输出序列。",
             "不能将中序或先序序列直接重新排列；需先确定各子树根的位置。",
             "训练根据遍历序列恢复二叉树结构并完成遍历转换。"),
            ["后序遍历", "先序遍历", "中序遍历"]),

        item("z5b11-408-circular-queue-wraparound", "cs408.ds.topic.e26b2753a525", "C",
            "循环队列数组容量为6，采用牺牲一个存储单元判满；front指向队头元素，rear指向下一次入队位置，初始front=rear=4。依次入队A、B、C、D，出队两次，再入队E、F。最后(front,rear,队列长度)为（ ）。",
            {"A": "(4,4,0)", "B": "(0,3,3)", "C": "(0,4,4)", "D": "(5,4,5)"},
            "四次入队依次写入下标4、5、0、1，rear变为2。两次出队移走A、B，front从4经5绕回0。再入队E、F写入下标2、3，rear变为4。队列中剩C、D、E、F共4项，故为(0,4,4)。",
            [("modular_index_trace", "rear=(4+4) mod 6=2；front=(4+2) mod 6=0；再入队两项rear=4。"),
             ("queue_length_formula", "(rear−front+6) mod 6=(4−0)=4，与保留元素数一致。")],
            [("operation_simulation", "按入队尾指针、出队头指针逐步更新并核对剩余元素序列。"),
             ("empty_slot_invariant", "队列有4项，小于可用容量5，未触及判满边界。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要在多次回绕操作后同步追踪队头、队尾和实际元素数，并按取模更新。",
            "逐操作模拟指针变化，并以模运算长度公式复核剩余元素数。",
             "rear指向下一空位而非最后元素；混淆约定会产生整体偏移。",
             "检验循环队列取模更新、牺牲单元判满和队长计算。"),
            ["循环队列", "队列操作", "取模运算"]),

        item("z5b11-408-merge-sort-comparisons", "cs408.ds.topic.fb59cb1478ef", "D",
            "对8个互异关键字按原顺序递增的序列执行标准自顶向下归并排序，每次合并时比较两个有序子表当前首元素，某一子表耗尽后直接复制另一子表。实际关键字比较次数及最坏比较次数分别为（ ）。",
            {"A": "8，17", "B": "12，16", "C": "15，17", "D": "12，17"},
            "已递增输入在每次合并中左子表元素都先于右子表耗尽，因此大小为1+1的4次合并各比较1次，2+2的2次合并各比较2次，4+4的合并比较4次，合计4+4+4=12。最坏情况满足C(n)=2C(n/2)+n−1，C(1)=0，n=8时C=17。",
            [("merge_level_count", "递增输入每层比较数为4、4、4，实际总数12。"),
             ("worst_case_recurrence", "T(8)=2T(4)+7、T(4)=2T(2)+3、T(2)=1，得到17。")],
            [("merge_trace", "连续递增时每次合并都在较短一侧的左表耗尽处停止比较。"),
             ("comparison_bound", "最坏比较数n log₂n−n+1=17，实际12不超过上界。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要区分具体有序输入下的合并比较数与算法最坏比较上界。",
             "按递归层逐层计数和递推式两种方法分别核验。",
             "归并排序比较次数依赖输入；不能把最坏公式直接当该有序序列的实际次数。",
             "比较排序算法的运行轨迹成本和渐近/最坏情况界。"),
            ["各排序算法比较", "归并排序", "比较次数"]),

        item("z5b11-408-uefi-boot-sequence", "cs408.os.topic.099b85d78c35", "B",
            "采用UEFI启动且启动项指向系统引导程序的计算机，从按下电源键到操作系统提供用户态服务的典型顺序是（ ）。",
            {"A": "内核先执行→UEFI读取文件系统→加载CPU微码→引导程序运行", "B": "UEFI完成平台初始化并选择启动项→引导程序加载内核及必要映像→内核初始化设备与根文件系统→启动init/system服务", "C": "用户态init先运行→加载内核→UEFI初始化硬件", "D": "UEFI把整个磁盘文件系统复制进内存→CPU执行所有驱动→引导程序启动"},
            "固件首先完成基本平台初始化并按启动项找到EFI引导程序；引导程序负责将内核及必要的初始映像载入内存并移交控制。内核随后建立运行环境、初始化驱动并挂载根文件系统，最后启动init/system等用户态服务管理进程。",
            [("boot_stage_order", "逐阶段排列固件、引导程序、内核和首个用户态服务。"),
             ("control_transfer", "只有内核完成必要初始化并启动用户空间后，常规用户服务才能运行。")],
            [("firmware_entry", "UEFI执行平台初始化、读取启动项并加载对应EFI程序。"),
             ("kernel_to_userspace", "引导程序移交内核；内核初始化后启动init/system服务。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要区分固件、引导程序、内核和用户态服务的职责及时序。",
             "按控制权交接过程和各阶段依赖条件复核顺序。",
             "UEFI不会先运行内核；用户态服务也不能先于内核建立执行环境。",
             "把计算机启动链路与操作系统引导机制放在完整系统场景中分析。"),
            ["操作系统引导", "启动过程", "内核与用户态"]),

        item("z5b11-408-double-buffer-pipeline-time", "cs408.os.topic.4daa9addd7e4", "C",
            "某设备顺序输入10个数据块，每块I/O耗时6 ms，CPU处理每块耗时3 ms。使用两个缓冲区使相邻块的I/O与CPU处理可完全重叠；忽略启动、切换和最终提交开销。完成10块的最短总时间为（ ）。",
            {"A": "60 ms", "B": "90 ms", "C": "63 ms", "D": "66 ms"},
            "首块先经6 ms I/O后才能处理。此后双缓冲允许CPU处理当前块时设备输入下一块，流水线节拍由较慢的I/O阶段6 ms决定。10块总时间为首个I/O 6 ms、之后9个节拍54 ms、最后一块CPU处理3 ms，共63 ms。单缓冲串行则为10(6+3)=90 ms。",
            [("pipeline_schedule", "块1在0–6ms输入、6–9ms处理；之后每6ms可启动下一块处理流水。"),
             ("formula_crosscheck", "T=6+(10−1)max(6,3)+3=63ms。")],
            [("stage_bottleneck", "稳态节拍取I/O与CPU阶段耗时较大者，即6ms。"),
             ("single_buffer_bound", "串行单缓冲时间90ms，双缓冲重叠后63ms，数量关系合理。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要区分首块填充、稳定流水节拍和末块排空时间。",
             "按时间线模拟与流水线公式得到相同总时长。",
             "不能简单用10乘较慢阶段；首块前无重叠，末块还需CPU处理。",
             "分析操作系统I/O缓冲如何通过双缓冲实现设备与CPU并行工作。"),
            ["缓冲区管理", "双缓冲", "I/O与CPU重叠"]),

        item("z5b11-408-user-thread-blocking-model", "cs408.os.topic.e8dd56864fdc", "A",
            "某运行时将同一进程的多个用户级线程全部映射到一个内核调度实体（多对一模型）。其中一个用户线程执行可能阻塞的同步磁盘读调用时，通常会发生什么？",
            {"A": "该内核调度实体阻塞，进程内其他用户线程也无法在该实体上运行，且该模型不能让同一进程线程并行占用多个CPU核", "B": "内核自动把其他用户线程提升为独立进程，因此仍可并行", "C": "只有发起调用的用户线程阻塞，内核必定切换到同进程的另一个内核线程", "D": "用户级线程不需要内核态，因此磁盘读不会阻塞"},
            "多对一模型把多个用户线程映射到单个内核调度实体。若该实体进入阻塞式系统调用，内核只能阻塞这一调度实体，用户线程库无法在其上切换到另一个可运行用户线程；且单一内核实体不能同时在多个处理器上执行。",
            [("mapping_and_blocking", "一个内核实体被同步I/O阻塞时，映射到它的整组用户线程失去内核执行机会。"),
             ("parallelism_limit", "并行执行要求多个可独立调度的内核执行实体，多对一不具备该条件。")],
            [("kernel_visibility", "内核只看到一个调度实体，无法单独调度某个用户级线程。"),
             ("multiprocessor_case", "同一进程只有一个内核执行实体，因此无法同时占据两个CPU核。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需从用户线程到内核调度实体的映射关系推导阻塞传播与并行上限。",
             "内核可见性和多核可调度实体数量两条依据相互补充。",
             "用户态调度并不能绕开同步系统调用对唯一内核实体的阻塞。",
             "比较线程实现模型对阻塞隔离和多处理器并行能力的影响。"),
            ["线程实现", "用户级线程", "多对一模型"]),

        item("z5b11-408-monitor-condition-recheck", "cs408.os.topic.e7303b384744", "D",
            "采用Mesa语义的管程中，消费者在条件变量notEmpty上等待。生产者放入一个项目后signal(notEmpty)，但在被唤醒消费者重新获得管程锁前，另一个消费者可能先进入并取走该项目。原消费者恢复后应如何编写条件检查？",
            {"A": "不需要检查，signal保证项目仍存在", "B": "用if检查一次即可，因为条件变量自动保留资源", "C": "改用signalAll后仍不需要重新检查", "D": "用while循环重新检查缓冲区非空条件，不满足时再次wait"},
            "Mesa语义下signal只使等待线程变为可运行，发信号线程通常继续持有管程锁；等待者恢复前，条件可能已被其他线程改变。因此消费者必须在获得锁后重新检查谓词，使用while而非if；若资源已被取走，则再次等待。",
            [("mesa_signal_semantics", "被signal唤醒不代表立即获得锁，也不保证谓词持续为真。"),
             ("predicate_loop", "用while(notEmpty条件不满足) wait，确保每次恢复都验证共享状态。")],
            [("interleaving_trace", "生产者signal后另一消费者可先取走项目，使缓冲区重新为空。"),
             ("spurious_or_competing_wakeup", "循环重检同时防止竞争唤醒和虚假唤醒导致错误读取。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要根据Mesa唤醒和锁重新竞争的时序分析条件变量谓词是否仍成立。",
             "构造竞争消费者交错执行，再验证while谓词循环。",
             "signal不是资源计数器，不会为被唤醒线程保留一个项目。",
             "训练管程条件变量、共享谓词和并发交错下的正确等待模式。"),
            ["管程与条件变量", "条件变量", "并发同步"]),

        item("z5b11-408-bitmap-contiguous-allocation", "cs408.os.topic.b5a459680f3e", "B",
            "文件系统用位图管理编号0–31的磁盘块，位值1表示空闲，块号从小到大首次适配连续分配。当前空闲区间为[3,5]、[8,12]、[16,23]，其余块均已占用。先请求4个连续块，再请求5个连续块，两次分配的起始块号分别为（ ）。",
            {"A": "3，16", "B": "8，16", "C": "8，12", "D": "16，21"},
            "扫描最小块号开始的空闲段，[3,5]只有3块，不能满足4块；下一段[8,12]满足，因此第一次分配8–11，留下块12。随后剩余可用连续段有单块12和[16,23]；第二次需5块，只能从16开始。起始块号为8和16。",
            [("first_fit_run_scan", "按块号扫描空闲连续段，长度依次3、5、8，第一次选起点8。"),
             ("residual_extent", "分配8–11后，块12长度仅1，下一段16–23仍可满足第二次请求。")],
            [("bitmap_semantics", "位1代表空闲，连续分配要求同一空闲区间长度达到请求块数。"),
             ("allocation_order", "第一次占用后更新位图再执行第二次首次适配。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要按首次适配顺序更新位图，并重新评估分配后的连续空闲区。",
             "逐段扫描和分配后空闲区长度复核得到两个起始块。",
             "不能把相邻编号但中间已占用的块拼成一个连续区间。",
             "把位图表示、连续空间约束和首次适配策略结合起来。"),
            ["外存空闲空间管理", "位图", "连续块分配"]),

        item("z5b11-408-cache-writeback-eviction", "cs408.co.topic.3b93ddd0af00", "C",
            "两行直接映射Cache采用写回、写分配策略，地址块A=0、B=1、C=2按块号模2映射到行。Cache初始为空，依次执行写A、再写A、读B、写C。忽略写缓冲合并。写回到主存的次数在最后一次访问后立即统计为多少；若随后显式刷新所有脏行又增加多少？",
            {"A": "2次；0次", "B": "0次；2次", "C": "1次；1次", "D": "1次；2次"},
            "A映射行0，第一次写A缺失并按写分配载入后置脏；第二次写A命中，仍只保留一个脏行。B映射行1，读入不产生写回。写C也映射行0，替换脏A时写回一次；C随后成为脏行。访问结束立即统计为1次，显式刷新再写回脏C一次，增加1次。",
            [("cache_line_trace", "跟踪行0的A→C替换，A被驱逐时写回一次，C留下脏标志。"),
             ("write_policy_contrast", "写回按脏块驱逐/刷新触发；两次对A的写合并在同一脏行状态中。")],
            [("address_mapping", "块号模2给出A、C同映射行，B映射另一行。"),
             ("dirty_eviction_and_flush", "脏A驱逐写回一次，之后脏C刷新再写回一次。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要将地址映射、写分配缺失、脏标志和脏行驱逐时机串联推演分析。",
            "按Cache行状态逐步跟踪，并依据脏块替换和刷新条件分别计数。",
             "写回不是每次store都访问主存；显式flush的写回需与替换写回分开。",
             "分析Cache写策略如何改变主存写流量和脏块替换行为。"),
            ["Cache 写策略", "直接映射Cache", "脏块写回"]),

        item("z5b11-408-risc-cisc-execution-time", "cs408.co.topic.0d0cb51a5974", "A",
            "完成同一程序时，RISC处理器执行1.2×10⁹条指令，平均CPI=1.5，时钟频率2 GHz；CISC处理器执行0.6×10⁹条指令，平均CPI=2.5，时钟频率1.25 GHz。忽略其他开销，两者CPU执行时间及较快者为（ ）。",
            {"A": "RISC 0.9 s、CISC 1.2 s，RISC较快", "B": "RISC 0.6 s、CISC 1.5 s，RISC较快", "C": "RISC 0.9 s、CISC 1.2 s，CISC较快", "D": "RISC 1.5 s、CISC 0.9 s，CISC较快"},
            "CPU时间=指令数×CPI/时钟频率。RISC为1.2×10⁹×1.5/(2×10⁹)=0.9s；CISC为0.6×10⁹×2.5/(1.25×10⁹)=1.2s。虽然CISC指令数较少，但其CPI和周期时间较大，总执行时间更长。",
            [("cpu_time_equation", "分别代入IC×CPI/f得到0.9s和1.2s。"),
             ("cycle_count_crosscheck", "RISC总周期1.8×10⁹、CISC总周期1.5×10⁹，再分别除以频率核对时间。")],
            [("instruction_and_cpi", "RISC周期数1.8×10⁹；CISC周期数1.5×10⁹。"),
             ("frequency_conversion", "GHz换算为10⁹周期/秒，得到0.9s和1.2s。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需综合指令数、平均CPI和时钟频率，不能只比较指令数量或单条指令复杂度。",
             "使用CPU时间公式与总周期数计算两条独立路径核对。",
             "CISC指令数减半并不自动更快；频率与CPI共同决定执行时间。",
             "在具体工作负载中量化RISC/CISC性能，而非凭体系结构标签判断。"),
            ["CISC 与 RISC", "CPU性能", "CPI与执行时间"]),

        item("z5b11-408-ipv4-fragment-offsets", "cs408.cn.topic.07c35172a523", "D",
            "一个IPv4数据报总长度为4000 B，首部20 B，经MTU=1500 B链路转发；不考虑选项，除最后一片外每片数据部分取最大且必须为8 B整数倍。三片的总长度、片偏移(以8 B为单位)及MF标志依次为（ ）。",
            {"A": "(1500,0,1)、(1500,184,1)、(1040,370,0)", "B": "(1500,0,1)、(1500,185,0)、(1040,370,0)", "C": "(1500,0,1)、(1500,180,1)、(1040,360,0)", "D": "(1500,0,1)、(1500,185,1)、(1040,370,0)"},
            "原数据部分为4000−20=3980 B。每个非末片最多携带1500−20=1480 B，且1480能被8整除；剩余数据为3980−2×1480=1020 B。因此第三片总长1040 B。片偏移依原始数据起点，分别为0、1480/8=185、2960/8=370；前两片后还有数据，MF=1，末片MF=0。",
            [("payload_partition", "3980B数据拆成1480、1480、1020B，满足MTU且前两片按8B对齐。"),
             ("offset_and_flags", "数据起点累计为0、1480、2960B，除8得0、185、370；MF为1、1、0。")],
            [("length_conservation", "三片数据长度和1480+1480+1020=3980B，总长度和4040B包含三份首部。"),
             ("fragment_field_rule", "片偏移以原数据中的8B单位表示，MF只在末片清零。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需区分原数据长度与片总长度、8字节偏移单位及末片标志。",
             "数据长度守恒、MTU对齐和偏移字段规则三步校验。",
             "每片都含20B首部；偏移不是字节数，MF也不能在中间片清零。",
             "在真实MTU约束下推演IPv4分片的长度、位置和控制字段。"),
            ["IPv4 分组与地址", "IPv4分片", "MTU"]),

        item("z5b11-408-ethernet-switch-learning", "cs408.cn.topic.201ce80c4dd6", "B",
            "一台交换机的MAC表初始为空，帧依次为：①从端口1收到源A、目的B；②从端口2收到源B、目的A；③从端口3收到源C、目的B。忽略VLAN。第三帧应从哪些端口转发，且此时A、B、C分别学习到哪个端口？",
            {"A": "除端口3外全部转发；A→1、B→2、C→3", "B": "仅从端口2转发；A→1、B→2、C→3", "C": "仅从端口1转发；A→1、B→2、C→3", "D": "丢弃；A→1、B→2，C未学习"},
            "交换机收到每帧时先依据源MAC学习入端口。①学习A→1，目的B未知故泛洪；②学习B→2，目的A已知在端口1，故仅转发至端口1；③学习C→3，目的B已知在端口2且不同于入端口3，因此只从端口2转发。",
            [("source_learning_sequence", "三帧依次建立A→1、B→2、C→3的源地址表项。"),
             ("destination_forwarding", "第三帧目的B已知映射端口2，非入端口，定向转发至2。")],
            [("bridge_learning_rule", "交换表通过源MAC及入端口学习，不从目的地址学习。"),
             ("known_unicast_rule", "已知单播发往目的端口；若目的端口等于入端口才过滤。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要逐帧更新交换表，再根据第三帧的已知单播目的地址决定端口。",
             "源地址学习顺序与目的地址转发规则分别复核。",
             "交换机按源MAC学习；未知目的泛洪只适用于第一帧，第三帧目的已知。",
             "推演透明网桥自学习、未知单播泛洪和已知单播转发状态。"),
            ["以太网交换机", "交换表自学习", "帧转发"]),

        item("z5b11-408-selective-repeat-window", "cs408.cn.topic.6e5dd5812d0e", "C",
            "选择重传ARQ使用m位序号，序号空间按模2ᵐ循环。为避免接收窗口把旧分组重传误认为序号回绕后的新分组，发送窗口和接收窗口的最大尺寸应满足什么条件？若m=3，最大窗口尺寸为多少？",
            {"A": "W≤2ᵐ，m=3时8", "B": "W≤2ᵐ−1，m=3时7", "C": "W≤2ᵐ⁻¹，m=3时4", "D": "W≤2，m=3时2"},
            "选择重传允许接收窗口保存多个失序帧。若窗口大于序号空间的一半，回绕后旧序号集合会与新接收窗口重叠，接收端无法仅凭序号区分新旧分组。因此W≤2^{m−1}；m=3时序号空间8，窗口最大4。",
            [("sequence_space_overlap", "当W超过半空间，回绕后的新窗口可能覆盖尚可被接受的旧序号。"),
             ("numeric_bound", "2^{3−1}=4，达到边界仍不与旧窗口产生歧义。")],
            [("modular_interval", "序号空间N=8，发送与接收窗口须各自避免跨半空间重叠。"),
             ("boundary_counterexample", "W=5时窗口跨度超过4，旧帧序号可能落入新接收区间。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需从序号回绕后的新旧分组可区分性推导窗口上限。",
             "模序号区间重叠分析与代入m=3计算相互校验。",
             "选择重传比停等协议需要更严格的窗口约束；不能让窗口占满全部序号空间。",
             "连接可靠传输窗口设计、有限序号空间和分组重复识别。"),
            ["选择重传（SR）", "滑动窗口", "序号空间"]),

        item("z5b11-408-http-persistent-rtt", "cs408.cn.topic.415100bf0700", "D",
            "浏览器顺序获取1个HTML对象及其引用的3个小对象；忽略DNS、传输时间和服务器处理时间，RTT固定为80 ms。不并行建立连接。非持久HTTP每个对象单独建立TCP连接；持久HTTP只建立一次连接且每个对象顺序请求响应、不使用流水线。两种方式总时间分别为（ ）。",
            {"A": "非持久320 ms，持久240 ms", "B": "非持久640 ms，持久320 ms", "C": "非持久400 ms，持久320 ms", "D": "非持久640 ms，持久400 ms"},
            "共有4个对象。非持久HTTP每个对象需要一次TCP握手RTT和一次请求/首字节RTT，共8RTT=640ms。持久HTTP仅一次握手1RTT，随后4个对象各需1RTT顺序请求响应，共5RTT=400ms。题干忽略传输与处理开销，因此不再加其他时间。",
            [("nonpersistent_connection_cost", "4个对象各需2RTT，得到8×80=640ms。"),
             ("persistent_sequential_cost", "1次握手加4次顺序请求响应，共5×80=400ms。")],
            [("connection_count", "非持久建4条TCP连接，持久仅建1条。"),
             ("request_response_rounds", "无流水线意味着每个对象的请求响应仍各占一个RTT。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要区分连接建立RTT与每个HTTP请求响应的RTT，并处理连接复用。",
             "按对象数计费和按TCP连接数计费两条路径核对。",
             "持久连接减少握手次数但未启用流水线，因此仍须逐对象等待响应。",
             "量化HTTP连接管理方式对一组页面对象获取时延的影响。"),
            ["WWW 与 HTTP", "持久连接", "往返时延"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    args = parser.parse_args()
    if not BACKUP.is_file() or hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper() != BACKUP_SHA256:
        raise SystemExit("prebatch_backup_missing_or_hash_mismatch")
    pg_restore = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
    toc = subprocess.run([str(pg_restore), "--list", str(BACKUP)], capture_output=True, timeout=30)
    if toc.returncode or b"TABLE DATA public questions" not in toc.stdout:
        raise SystemExit("prebatch_backup_archive_invalid")
    output = OUT_DIR / ("preview.json" if args.mode == "dry-run" else "checkpoint.json")
    if output.exists():
        raise SystemExit(f"refusing_to_overwrite_existing_output:{output.name}")
    from scripts import phase45z5_original_batch01 as runner
    runner.BACKUP, runner.BACKUP_SHA256 = BACKUP, BACKUP_SHA256
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres",
        host="127.0.0.1", port=PORT, database=DB_NAME), pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.begin()
            try:
                report = run_batch(db, candidate_specs=candidates(), batch_id="11")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH11_APPLIED"
                report["backup"]["toc_entries"] = len(toc.stdout.splitlines())
                if sha_file(BACKUP) != BACKUP_SHA256:
                    raise ValueError("backup_changed_during_batch")
                db.rollback() if args.mode == "dry-run" else db.commit()
            except Exception:
                db.rollback()
                raise
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({"status": report["status"], "candidates": len(candidates()),
            "accepted": len(report["accepted"]), "rejected": report["rejected"],
            "checkpoint": output.relative_to(ROOT).as_posix(), "paid_model_calls": 0},
            ensure_ascii=False, default=str))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
