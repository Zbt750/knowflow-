"""Batch 12: independently calculated originals for the owned Z5 test DB."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import phase45z5_original_batch01 as runner
from scripts.phase45z5_original_batch02 import item

BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch11-retry2/post-batch11.dump"
BACKUP_SHA256 = "2C8B058B85624BADC3FEA8EF1E630F3FF08165F582A9CDAC64D91A6A9B2631B0"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch12"
DB_NAME, PORT, SYSTEM_ID = runner.DB_NAME, runner.PORT, runner.SYSTEM_ID


def q(key, node, answer, stem, options, explanation, methods, steps, reason, tags):
    truth = {letter: letter == answer for letter in options}
    return item("z5b12-" + key, node, answer, stem, options, explanation,
                methods, steps, truth, reason, tags, difficulty="medium")


def candidates():
    return [
        q("implicit-second-derivative-ellipse", "math.calculus.differential.implicit", "C",
          "曲线x²+2xy+3y²=1在点(1,0)附近确定可二次求导的y=y(x)。该点的y′与y″分别为（ ）。",
          {"A":"−1，2", "B":"1，−2", "C":"−1，−2", "D":"−1，−4"},
          "令F=x²+2xy+3y²−1。点(1,0)处F_y=2≠0。一阶求导得2x+2y+(2x+6y)y′=0，故y′=−1。二阶关系为2+4y′+6(y′)²+(2x+6y)y″=0，代入得4+2y″=0，故y″=−2。",
          [("implicit_hessian_formula","F_x=F_y=2，F_xx=2、F_xy=2、F_yy=6；代入隐函数二阶导数公式得到−2。"),
           ("local_series_coefficients","置y=−(x−1)+c(x−1)²+o((x−1)²)，原等式二阶系数给c=−1，因此y″=2c=−2。")],
          [("first_derivative","在指定点F_y非零，先求出y′=−1。"),("second_derivative","将一阶导数代入二阶关系，得到y″=−2。")],
          ("需要先核查隐函数条件，再计算一阶和二阶导数的交叉项。",
           "使用二阶隐函数公式求值，并以局部二阶展开独立复核结果。",
           "对含y的系数继续求导会产生交叉项，漏项会造成二阶导数错误。",
           "训练隐式曲线在给定点的局部变化分析与高阶求导方法。"),
          ["隐函数求导","二阶导数","链式法则"]),
        q("nonlinear-order-reduction-domain", "math.exam.66f8f7b61188", "B",
          "初值问题y″=(y′)²，y(0)=0、y′(0)=1的解在包含0的区间内延拓。其y(1/2)及向右延拓时的首个奇异点为（ ）。",
          {"A":"−ln2，x=1", "B":"ln2，x=1", "C":"1/2，x=2", "D":"ln2，无有限奇异点"},
          "令p=y′，得p′=p²及p(0)=1，分离变量得到p=1/(1−x)。再积分并用y(0)=0得y=−ln(1−x)，包含0的最大实区间为x<1。代入x=1/2得ln2；x→1⁻时解与导数发散。",
          [("order_reduction_separation","以p=y′降阶，积分dp/p²=dx得到p=1/(1−x)，再积分得到−ln(1−x)。"),
           ("substitution_and_domain_check","直接求导−ln(1−x)，有y′=(1−x)⁻¹、y″=(1−x)⁻²，满足方程与两项初值且在1处奇异。")],
          [("reduce_order","利用方程不显含y，令p=y′并依据初值确定积分常数。"),("recover_solution","积分p并核对初值、取值和最大实定义区间。")],
          ("需要将非线性二阶方程降阶，并同时处理初值和解的定义区间。",
           "先解一阶分离变量方程，再积分恢复y并逐项代回验证。",
           "积分常数由两项初值分别确定，不能忽略对数定义域和奇异点。",
           "训练降阶方法、初值约束以及微分方程解的延拓边界分析。"),
          ["降阶代换与初值条件","非线性方程","解的定义域"]),
        q("washer-intersections-volume", "math.exam.9f10ce353fbd", "D",
          "平面区域由y=√x与y=x/2两条曲线围成，将该有限区域绕x轴旋转一周。旋转体体积为（ ）。",
          {"A":"8π", "B":"16π/3", "C":"4π/3", "D":"8π/3"},
          "先解√x=x/2，交点横坐标为0和4。在0<x<4内√x>x/2，垫片外半径√x、内半径x/2。因此V=π∫₀⁴[x−x²/4]dx=π[ x²/2−x³/12 ]₀⁴=8π/3。不能把内部空腔遗漏。",
          [("washer_integral","按交点确定积分区间，并对外半径平方减内半径平方积分得到8π/3。"),
           ("outer_minus_inner_volume","外部抛物面体积8π，内部圆锥体积16π/3，二者相减得到8π/3。")],
          [("intersection_and_radius","求得两个交点0、4并判断曲线高低确定内外半径。"),("volume_difference","计算垫片积分，也用两个旋转实体的体积差复核。")],
          ("需要确定封闭区间和曲线高低，再建立带内空腔的旋转体模型。",
           "通过垫片积分与外部旋转体减内部圆锥两种方式计算体积。",
           "不能将两曲线之差直接平方，也不能省略内半径所对应的体积。",
           "训练交点分析、旋转轴选择以及旋转体积分模型的综合运用。"),
          ["旋转体体积","定积分应用","垫片法"]),
        q("parameter-log-integral", "math.exam.8eaf1a6aeb50", "A",
          "设a>−1，F(a)=∫₀¹(xᵃ−1)/ln x dx，其中x=1处取连续延拓值。F(3)等于（ ）。",
          {"A":"ln4", "B":"3", "C":"ln3", "D":"1/4"},
          "对参数求导得到F′(a)=∫₀¹xᵃdx=1/(a+1)。由F(0)=0，得F(a)=ln(a+1)，所以F(3)=ln4。也可用(xᵃ−1)/ln x=∫₀ᵃxᵗdt，对a=3交换非负被积函数的积分次序直接得到∫₀³dt/(t+1)=ln4。",
          [("parameter_differentiation","利用参数导数和F(0)=0得到F(a)=ln(a+1)，代入a=3。"),
           ("double_integral_exchange","把差商写成∫₀³xᵗdt，用非负函数积分次序交换独立计算ln4。")],
          [("parameter_derivative","在a>−1的局部闭区间内可由可积函数控制参数导数。"),("initial_parameter_value","由F(0)=0确定常数并计算F(3)=ln4。")],
          ("需要处理含参数积分与可去奇点，并使用参数积分的初值确定函数。",
           "先计算参数导数，再用积分次序交换的第二条路径核验答案。",
           "x=1处是可去奇点；不能把分母的ln x误当成常数提出积分。",
           "训练参数求导、积分交换和边界控制在非直接积分问题中的应用。"),
          ["含参积分求导","积分次序交换","反常端点"]),
        q("vector-rank-parameter-maximal-set", "math.exam.8d8ad14b2a44", "C",
          "给定a₁=(1,1,0)、a₂=(0,1,1)、a₃=(1,2,1)、a₄=(1,t,1)。关于向量组的秩和极大无关组，下列正确的是（ ）。",
          {"A":"任意t秩为3，{a₁,a₂,a₃}是极大无关组", "B":"t=2时秩为1", "C":"t=2时秩为2；t≠2时秩为3且{a₁,a₂,a₄}是极大无关组", "D":"t≠2时秩为2，因为只有三维向量"},
          "a₃=a₁+a₂，而a₁、a₂线性无关，因此原前三个向量的秩为2。以a₁、a₂、a₄为列的行列式为2−t。t≠2时这三列无关，组的秩为3；t=2时a₄=a₃，秩仍为2。三维空间允许三个无关向量。",
          [("column_determinant","det[a₁,a₂,a₄]=2−t，结合a₃=a₁+a₂分类。"),
           ("span_plane_constraint","span{a₁,a₂}的向量满足x−y+z=0，a₄满足该约束当且仅当t=2。")],
          [("dependent_third_vector","识别a₃为前两列之和，避免将其误算为独立向量。"),("parameter_rank_change","检验a₄是否离开二维张成空间，并确定极大无关组。")],
          ("需要先发现固定线性关系，再研究参数向量是否扩展张成空间。",
           "用三阶行列式及平面线性约束分别检验秩发生变化的条件。",
           "向量个数和环境维数都不能单独决定秩，必须检查实际线性关系。",
           "训练参数向量组的秩分类、空间张成和极大无关组选择。"),
          ["向量组秩与极大无关组","参数讨论","线性表示"]),

        q("linker-relocation-symbol-addend", "cs408.os.topic.8266516a5539", "B",
          "目标文件内符号L的节内偏移为0x120，该节装入基址为0x4000；外部符号E已由链接器解析为绝对地址0x9000，引用E时带加数0x18。采用绝对地址重定位，L地址和E加加数后的引用地址分别为（ ）。",
          {"A":"0x0120，0x0018", "B":"0x4120，0x9018", "C":"0x4120，0xD018", "D":"0x4000，0x9000"},
          "节内符号的最终地址为装入基址加节内偏移，所以L=0x4000+0x120=0x4120。E已经是已解析绝对地址，引用加数只需加0x18，得到0x9018；不能再加本节装入基址。",
          [("relocation_equations","本地节符号使用B+offset，已解析外部符号使用S+addend，分别得到0x4120、0x9018。"),
           ("hexadecimal_integer_check","将地址视为整数做精确十六进制加法，分别复核两类重定位字段。")],
          [("local_symbol","区分节内偏移与装入地址，计算L的最终地址。"),("external_symbol","对已解析绝对符号只加引用加数，避免重复加基址。")],
          ("需要区分节内相对位置和外部绝对符号，再应用不同的重定位规则。",
           "按符号归属列出两条重定位表达式，并做十六进制整数核验。",
           "外部符号已解析成绝对地址后不能再次加当前节基址，否则重复重定位。",
           "训练链接符号解析、装入基址和引用加数在实际地址形成中的作用。"),
          ["程序链接与装入","重定位","符号解析"]),
        q("spooling-complete-file-timeline", "cs408.os.topic.e54fc352f4b6", "D",
          "SPOOLing输出服务按FIFO打印完整关闭的假脱机文件。CPU从0 ms起顺序生成作业A用2 ms、作业B再用3 ms；单台打印机打印A用6 ms、B用4 ms，打印与CPU生成可重叠。忽略磁盘开销。B提交时间及全部打印完成时间分别为（ ）。",
          {"A":"5 ms，15 ms", "B":"2 ms，12 ms", "C":"5 ms，10 ms", "D":"5 ms，12 ms"},
          "A文件在2 ms关闭后提交并开始打印，打印区间为[2,8]。CPU同时在[2,5]生成B，B在5 ms提交，但FIFO打印机正忙，须等8 ms开始，打印至12 ms。提交完成不等于物理输出完成。",
          [("resource_timeline","CPU的A、B生成区间为0–2、2–5；打印机的A、B区间为2–8、8–12。"),
           ("single_server_recurrence","打印完成时刻满足finish=max(submit,previous_finish)+service，得到A=8、B=12。")],
          [("submission_completion","两个文件完整关闭的提交时刻为2和5 ms。"),("printer_queue","按FIFO串行服务并与生成时间重叠，算得最后结束于12 ms。")],
          ("需要把CPU生成、磁盘队列提交和独占打印机服务拆成不同时间线。",
           "逐作业应用单服务台递推，并与CPU和打印机区间图独立核对。",
           "提交文件后CPU可继续运行，但物理设备仍按队列顺序串行打印。",
           "训练SPOOLing的异步解耦、共享设备虚拟化及输出完成时间分析。"),
          ["假脱机 SPOOLing","异步输出","服务时间线"]),
        q("multiprogramming-io-utilization", "cs408.os.topic.6eeb2632531c", "A",
          "单CPU多道程序系统从0时刻同时就绪P₁、P₂，先运行P₁，采用非抢占且工作保持的调度。P₁需CPU 3 ms、I/O 5 ms、再CPU 2 ms；P₂仅需CPU 4 ms。I/O可与另一进程CPU运行重叠。两进程全部完成时间及该期间CPU利用率为（ ）。",
          {"A":"10 ms，90%", "B":"14 ms，约64.3%", "C":"9 ms，100%", "D":"10 ms，70%"},
          "P₁在0–3使用CPU，随后3–8进行I/O；P₂在3–7使用CPU并完成。7–8无就绪进程，CPU空闲。P₁于8 ms恢复就绪并在8–10完成。总CPU忙时3+4+2=9 ms，总历时10 ms，利用率90%。",
          [("event_timeline_simulation","按阻塞和I/O完成事件排出CPU区间0–3、3–7、8–10及空闲7–8。"),
           ("busy_time_conservation","CPU任务总量9ms，唯一空闲间隔1ms，因此完成时间10ms且利用率9/10。")],
          [("overlap_io_and_cpu","P₁等待I/O时运行P₂，避免把两类资源时间串行相加。"),("remaining_idle_gap","P₂先于P₁的I/O结束，保留1ms真实空闲后计算利用率。")],
          ("需要分析阻塞事件、不同资源并行和就绪进程不足造成的CPU空闲。",
           "以事件时间线计算总历时，再用CPU工作量守恒独立复核利用率。",
           "多道程序并不保证CPU永远满负荷；没有就绪进程时仍会发生空闲。",
           "通过具体进程轨迹理解多道程序利用I/O等待提高资源利用率的机制。"),
          ["操作系统概念与发展","多道程序","I/O与CPU重叠"]),
        q("iterative-inorder-stack-trace", "cs408.ds.topic.f32b740044c8", "C",
          "二叉树根为A；A的左右孩子为B、C；B的左右孩子为D、E；E只有左孩子F；C只有右孩子G。采用标准非递归中序遍历：沿左链压栈，弹出访问后转向右孩子。遍历序列和辅助栈最大结点数分别为（ ）。",
          {"A":"D、B、E、F、A、C、G；3", "B":"D、B、F、E、A、G、C；4", "C":"D、B、F、E、A、C、G；3", "D":"A、B、D、E、F、C、G；4"},
          "左子树中序为D、B、F、E，根A之后右子树为C、G，故完整序列D、B、F、E、A、C、G。最初压入A、B、D共3个；访问D、B后，压入E、F时栈为A、E、F仍为3个，其他时刻不超过3。",
          [("recursive_inorder_reference","递归按左—根—右生成D,B,F,E,A,C,G。"),
           ("iterative_stack_simulation","逐次执行压栈、出栈和右孩子转换，得到相同序列且最大栈长3。")],
          [("subtree_order","先对B和C子树分别排列左—根—右序列。"),("stack_occupancy","跟踪待访问祖先和左链，不将整树高度机械等同于当前栈长。")],
          ("需要同时确定中序访问次序和非递归执行时的辅助栈状态。",
           "用递归参考遍历核验序列，再逐操作模拟非递归栈的峰值。",
           "E的左孩子F须先于E访问；右子树的空左链不能颠倒C和G。",
           "训练树结构、递归定义和显式栈实现之间的对应与空间成本分析。"),
          ["中序遍历","非递归遍历","辅助栈"]),
        q("prim-kruskal-weighted-graph", "cs408.ds.topic.b66f6167354e", "B",
          "无向连通图有顶点A、B、C、D、E，边及权重为AB:2、AC:3、BC:1、BD:4、CD:5、CE:6、DE:2、BE:7。从A开始执行Prim算法，选出的边集及最小生成树总权重为（ ）。",
          {"A":"{AB,AC,BD,DE}，11", "B":"{AB,BC,BD,DE}，9", "C":"{AC,BC,CD,DE}，11", "D":"{AB,BC,CE,DE}，11"},
          "初始选AB(2)；已选{A,B}后最小割边为BC(1)；已选{A,B,C}到未选{D,E}的最小割边为BD(4)；再选DE(2)。总权重2+1+4+2=9。用Kruskal按权重选择BC、AB、DE、BD也得到同一树和权重。",
          [("prim_cut_simulation","依次扩展选中顶点集并选最小跨割边，输出AB,BC,BD,DE，总重9。"),
           ("kruskal_union_find","按权重排序并跳过成环边，独立选出BC,AB,DE,BD，总重9。")],
          [("cut_candidates","每一步重新筛选连接已选集与未选集的边，而非仅从最近顶点找边。"),("mst_crosscheck","按Kruskal排序和并查集重新构造最小生成树核对总权重。")],
          ("需要依据当前割边而非固定顶点邻边，连续更新Prim候选集合。",
           "执行Prim过程后，再以不同选择顺序的Kruskal方法核验树和总权重。",
           "不能把已经成环的AC计入生成树，也不能选非最小跨割边增加成本。",
           "训练最小生成树的贪心依据、图状态更新和算法间结果交叉验证。"),
          ["Prim 最小生成树","割边","Kruskal交叉验证"]),
        q("critical-path-activity-slack", "cs408.ds.topic.6d4cb688c2ee", "D",
          "AOE网络活动为1→2:3、1→3:2、2→4:4、3→4:5、2→5:2、4→6:3、5→6:6，冒号后为持续时间。工程最短完成时间和活动3→4的总时差分别为（ ）。",
          {"A":"10，0", "B":"11，0", "C":"10，1", "D":"11，1"},
          "事件最早时间为ve=(0,3,2,7,5,11)。从终点倒推最迟时间vl=(0,3,3,8,5,11)。因此工程完成时间11，关键路径1→2→5→6。活动3→4的最早开始为ve(3)=2，最迟开始为vl(4)−5=3，总时差1。",
          [("forward_backward_aoe","正向取前驱最大值计算ve，再逆向取后继最小值计算vl，活动时差为1。"),
           ("path_duration_enumeration","三条源汇路径持续时间为10、11、10，最长为11；3→4所在路径距最长差1。")],
          [("earliest_latest_events","分别计算事件最早和最迟发生时间，不能把二者混用。"),("activity_slack","以vl(终点)−持续时间−ve(起点)计算活动时差。")],
          ("需要同时求源汇最长路径、最迟事件时间及单活动的可延迟量。",
           "采用正反拓扑递推计算时差，并用源汇路径总长度交叉检验。",
           "两个到事件4的路径虽同时达到最早时间7，其后仍存在1单位可用余量。",
           "训练项目网络工期与活动总时差计算，区分局部等长路径和全局关键路径。"),
          ["关键路径","AOE网络","活动时差"]),
        q("struct-alignment-big-endian", "cs408.co.topic.236ea41712f9", "A",
          "某ABI规定char按1 B对齐、uint32按4 B对齐、uint16按2 B对齐，结构体按成员最大对齐且尾部补齐。结构体顺序为char a; uint32 b; uint16 c，起始地址0x1000，b=0x12345678，机器为大端。c的偏移、结构体大小和地址0x1004处字节分别为（ ）。",
          {"A":"8，12 B，0x12", "B":"5，7 B，0x78", "C":"8，10 B，0x12", "D":"8，12 B，0x78"},
          "a占偏移0，之后填充3 B使b位于偏移4，占4–7；c按2 B对齐位于偏移8，占8–9。结构体总体按4 B对齐，尾部填充至12 B。大端将b最高有效字节0x12放在最低地址0x1004。",
          [("abi_alignment_layout","逐成员向上对齐得到偏移0,4,8；总长度10再按4对齐为12。"),
           ("byte_address_serialization","将0x12345678按大端序拆为12,34,56,78，核对b首地址字节0x12。")],
          [("member_padding","计算成员前填充和结构体末尾填充，二者都须纳入布局。"),("endian_byte_order","按字节顺序核查最低地址保存的是最高有效字节。")],
          ("需要将成员对齐、尾部填充和多字节数的大端存放规则组合分析。",
           "按ABI逐字段布局后，再把整数编码成字节流验证目标地址。",
           "结构体大小不是成员大小之和；大端小端只影响字节顺序不改变对齐位置。",
           "训练数据布局和端序在实际内存地址推算中的综合运用。"),
          ["数据对齐与大小端","结构体布局","字节地址"]),
        q("dram-refresh-bandwidth-overhead", "cs408.co.topic.2d6ca0bb88eb", "C",
          "某DRAM有8192行，每行须在64 ms内刷新一次；一次刷新占用存储器100 ns，刷新期间不可正常访问，采用均匀分散刷新。平均相邻刷新命令间隔与刷新占用时间比例分别为（ ）。",
          {"A":"7.8125 μs，0.128%", "B":"64 μs，1.28%", "C":"7.8125 μs，1.28%", "D":"0.78125 μs，12.8%"},
          "64 ms内需8192次刷新，均匀间隔为64 ms/8192=7.8125 μs。累计占用8192×100 ns=819200 ns=0.8192 ms，所以占用比例0.8192/64=0.0128=1.28%。间隔是命令开始之间的平均距离，包含刷新占用。",
          [("refresh_rate_calculation","按8192行/64ms计算命令频率，其倒数为7.8125μs。"),
           ("occupied_time_fraction","把8192次100ns占用累加后除以64ms，精确得到1.28%。")],
          [("uniform_refresh_interval","一轮中刷新每行一次，平均分散到整个刷新周期。"),("time_unit_conversion","统一毫秒与纳秒单位，计算刷新对可用访问时间的占用比例。")],
          ("需要将保持周期、行数和单次存储器阻塞时间换算到同一时间尺度。",
           "先从刷新次数推命令间隔，再从累计占用时间计算访问带宽损失。",
           "100ns不是两次刷新间隔；比例转成百分数时还须乘一百。",
           "训练DRAM刷新机制对访问时序和有效资源利用率的量化分析。"),
          ["半导体存储器（SRAM/DRAM/Flash）","DRAM刷新","存储器占用"]),
        q("signed-product-truncation-overflow", "cs408.co.topic.0efeb18eeae7", "B",
          "两个8位二进制补码整数−100和3相乘，先保留16位完整乘积，再截取低8位并按8位补码解释。完整16位编码、截取后的值及是否发生8位有符号溢出为（ ）。",
          {"A":"0xFED4，−300，无溢出", "B":"0xFED4，−44，有溢出", "C":"0x012C，44，有溢出", "D":"0xFFD4，−44，无溢出"},
          "精确乘积−300在16位补码中为65536−300=65236，即0xFED4。低8位为0xD4=212，按补码解释为212−256=−44。−300不在8位有符号范围[−128,127]内，故截断发生溢出；不能用截断结果替代完整乘积。",
          [("exact_integer_product_encoding","用整数乘积−300和模2^16编码得到FED4，再模2^8取低位。"),
           ("signed_range_and_extension","低8位D4符号扩展为FFD4而非FED4，表明完整结果不能以8位保持。")],
          [("full_width_product","先算精确乘积并编码为16位二进制补码。"),("truncation_overflow","解释低8位的符号值并以范围和符号扩展检验溢出。")],
          ("需要区分精确整数结果、宽位补码表示和截断后窄位有符号解释。",
           "先做模运算编码，再用可表示范围与符号扩展检查有符号溢出。",
           "截取低位保留模256的值，不能保留超出8位范围的数学乘积。",
           "训练乘法结果位宽、补码编码及软件截断造成的溢出判断。"),
          ["整数乘除运算","补码","乘积位宽"]),
        q("reno-fast-recovery-window-trace", "cs408.cn.topic.940692c0d533", "D",
          "按经典TCP Reno快速恢复规则，发送端cwnd=12 MSS且未确认数据量为12 MSS。收到第三个重复ACK时令ssthresh为未确认量一半、cwnd=ssthresh+3 MSS；每个额外重复ACK再加1 MSS，新ACK到达后退出快速恢复并令cwnd=ssthresh。第三个重复ACK后、再来一个重复ACK后、新ACK后，cwnd依次为（ ）。",
          {"A":"6、7、6 MSS", "B":"12、13、1 MSS", "C":"9、10、9 MSS", "D":"9、10、6 MSS"},
          "门限先设为12/2=6 MSS。第三个重复ACK后的膨胀窗口为6+3=9 MSS；一个额外重复ACK将其增加到10 MSS。收到确认新数据的新ACK时退出快速恢复，窗口回落到门限6 MSS。题干已明确采用经典Reno规则。",
          [("reno_state_transition","按题干状态转移逐步得到ssthresh=6以及cwnd序列9,10,6。"),
           ("window_deflation_check","区分快速恢复的临时膨胀量和长期门限，退出时移除膨胀，回到6 MSS。")],
          [("third_duplicate_ack","按在途量减半计算门限并加入三段临时膨胀。"),("extra_and_new_ack","分别处理额外重复ACK的增加与新ACK退出时的回落。")],
          ("需要依据不同ACK事件切换快速恢复状态，并区分门限与临时窗口。",
           "逐事件计算状态值，再检查退出时窗口是否恢复到未膨胀门限。",
           "重复ACK不是新ACK，三次重复ACK的处理也不同于重传计时器超时。",
           "训练TCP拥塞控制在丢包恢复期间的状态变化和发送窗口推演。"),
          ["TCP 拥塞控制","Reno","快速恢复"]),
        q("tcp-flow-window-unsent-bytes", "cs408.cn.topic.fdfe51b5d88a", "A",
          "TCP发送端最早未确认序号SND.UNA=1000，下一发送序号SND.NXT=3700；接收方通告窗口5000 B，拥塞窗口4 MSS，MSS=1460 B。忽略序号回绕，发送缓存充足且不启用额外发送约束。当前最多还能发送多少新数据，允许序号区间为（ ）。",
          {"A":"2300 B，[3700,6000)", "B":"5000 B，[3700,8700)", "C":"3140 B，[3700,6840)", "D":"2700 B，[1000,3700)"},
          "在途未确认数据为3700−1000=2700 B。有效发送窗口min(5000,4×1460)=5000 B，所以还能发5000−2700=2300 B。窗口右界为SND.UNA+5000=6000，未发送区间是[3700,6000)。",
          [("window_min_minus_flight","计算接收窗口与拥塞窗口的较小值，再减去2700B在途量。"),
           ("sequence_window_interval","根据窗口左界1000和宽度5000确定右界6000，再求未发送区间长度。")],
          [("flight_size","从最早未确认到下一发送序号的差计算已经占用的窗口。"),("usable_window","由接收与拥塞约束共同确定右界并计算新数据空间。")],
          ("需要综合流量控制、拥塞控制和已占用窗口，不能只读取一个窗口值。",
           "用窗口宽度减在途量计算，再以序号区间左右边界独立核对。",
           "通告的5000B包含已有未确认数据，不是可以额外发送的新字节数。",
           "训练TCP序号、接收窗口和拥塞窗口共同约束新数据发送的机制。"),
          ["TCP 流量控制","发送窗口","序号区间"]),
        q("ipv6-path-mtu-router-fragmentation", "cs408.cn.topic.76b87a32829d", "C",
          "IPv6主机发送1800 B报文，路径中某路由器出口MTU为1280 B；未提供可供路由器分片的特殊机制，且路由器可发送ICMPv6。对该报文的标准处理及后续发送方动作，正确的是（ ）。",
          {"A":"路由器按IPv4方式直接分片，发送方无需调整", "B":"路由器截去超过1280B的尾部并转发", "C":"路由器丢弃并回送Packet Too Big信息；源主机根据路径MTU减小报文，必要时由源端使用Fragment首部分片", "D":"中间路由器必须把MTU扩展到1800B后转发"},
          "IPv6中间路由器不实施IPv4式分片。出口无法承载该报文时应丢弃并回送ICMPv6 Packet Too Big，携带MTU信息。源端可使用路径MTU发现调整上层分段或报文长度；若使用IPv6分片，Fragment扩展首部由源端生成。路由器不能静默截断数据。",
          [("ipv6_router_rule","根据IPv6中间路由器不得分片的规则和出口MTU，确定丢弃并发送Packet Too Big。"),
           ("source_pmtu_response","按路径MTU反馈分析源端减小分段或源端分片，保持端到端数据完整性。")],
          [("forwarding_constraint","判断实际报文长度超出出口MTU且路由器不能替源端分片。"),("source_adjustment","通过ICMPv6反馈调整源端发送长度或构造Fragment扩展首部。")],
          ("需要结合报文大小、出口MTU和IPv6源端分片职责确定整条处理链。",
           "先分析中间节点约束，再分析控制反馈驱动的源端适配行为。",
           "IPv6路由器的处理不同于IPv4分片，截断有效载荷会破坏报文完整性。",
           "训练路径MTU发现、ICMPv6反馈和IPv6扩展首部在传输中的关系。"),
          ["IPv6","路径MTU","源端分片"]),
        q("vlan-broadcast-trunk-scope", "cs408.cn.topic.560367fe85a6", "B",
          "交换机S₁的接入口A、B属于VLAN10，C属于VLAN20；S₂的D属于VLAN10、E属于VLAN20。两交换机由允许VLAN10和20的802.1Q trunk连接，VLAN10不是native VLAN。A发送广播帧时，其余终端接收集合及trunk标记为（ ）。",
          {"A":"B、C、D、E；不加标签", "B":"B、D；VLAN10标签", "C":"仅B；VLAN20标签", "D":"D、E；VLAN10标签"},
          "接入口A的帧归入VLAN10，广播只在该VLAN广播域中传播。S₁向同VLAN的B及trunk转发，跨trunk时携带VLAN10标签；S₂再向同VLAN接入口D转发。C、E属于VLAN20不接收，接入口出帧时不带trunk标签。",
          [("vlan_domain_membership","按VLAN10广播域筛选终端集合，除源A外为B、D。"),
           ("two_switch_forwarding_trace","逐交换机追踪接入口分类、trunk携带标签与远端同VLAN端口转发。")],
          [("ingress_classification","由接入口配置确定帧的VLAN归属并限制泛洪范围。"),("trunk_and_egress","通过trunk保留VLAN10身份，在远端只向VLAN10接入口转发。")],
          ("需要跨两个交换机跟踪广播域，并区分接入口和trunk的标签行为。",
           "按VLAN成员集合核验接收终端，再逐链路复核802.1Q标签转换。",
           "物理连接共享不代表两个VLAN的广播会互通，native VLAN条件也不能忽略。",
           "训练VLAN隔离、跨交换机广播转发以及trunk封装的综合场景分析。"),
          ["VLAN","802.1Q","广播域"]),
        q("exception-versus-interrupt-restart", "cs408.os.topic.4ac423ec47e2", "D",
          "用户进程执行访存指令触发缺页异常；稍后磁盘完成调页产生设备中断。关于两事件的发生原因及恢复执行，正确的是（ ）。",
          {"A":"两者均由当前指令同步产生，缺页指令已完成", "B":"缺页是异步中断，磁盘完成是同步异常", "C":"缺页后必须终止进程，设备中断不能用于唤醒", "D":"缺页与当前访存同步相关，调页完成中断来自异步设备；缺页处理完成后应按系统机制重新执行未完成的访存"},
          "缺页由当前访存地址转换发现页不在内存而同步触发，访存尚未完成。系统可将进程阻塞并安排磁盘读取；设备完成后异步发中断，处理程序更新页面状态并唤醒进程。进程恢复后重新执行原访存，而不是直接略过缺页指令。",
          [("event_cause_classification","根据事件与当前指令的因果关系区分同步缺页异常和异步I/O完成中断。"),
           ("demand_paging_state_trace","追踪页不在内存、阻塞调页、设备完成、唤醒和指令重启的完整过程。")],
          [("fault_before_completion","页不在内存使当前访存无法完成，系统记录其可重启上下文。"),("io_interrupt_wakeup","调页完成中断推动页面更新和进程唤醒，随后恢复访存。")],
          ("需要同时判断事件来源、进程阻塞唤醒和未完成指令的恢复语义。",
           "以当前指令关联性分类事件，再沿请求分页的状态变化检查恢复行为。",
           "可处理缺页不等于非法访问终止；磁盘完成也不是当前CPU指令产生的异常。",
           "训练异常、中断和请求分页如何共同维持用户进程的透明执行。"),
          ["中断与异常（OS 视角）","缺页处理","指令重启"]),
        q("ethernet-backoff-slot-frame", "cs408.cn.topic.bcfe8d79341e", "A",
          "传统10 Mb/s半双工以太网采用CSMA/CD，时隙为512 bit时间。某帧已发生3次碰撞，本次二进制指数退避随机选K=5。忽略其他等待开销，该次退避时长及协议最小帧长度（不含前导码/SFD）为（ ）。",
          {"A":"256 μs，64 B", "B":"25.6 μs，64 B", "C":"256 μs，512 B", "D":"51.2 μs，64 B"},
          "一次时隙时间512/(10×10⁶)s=51.2 μs。第三次碰撞后K可在0至7中选择，K=5合法，退避5×51.2=256 μs。最小帧长度512 bit=64 B；它包含从目的地址到FCS的MAC帧，不含前导码和SFD。",
          [("bit_time_exact_calculation","按512bit和10Mb/s换算时隙，再乘随机整数5得到256μs。"),
           ("backoff_range_and_frame_units","第三次碰撞取值范围0..7，确认K合法；512bit换为64B核验帧长。")],
          [("slot_time","将比特时间换为物理时间并按K个时隙退避。"),("range_and_frame","检查指数退避的K范围及最小帧按字节计的长度。")],
          ("需要区分速率、bit时间、退避时隙次数和MAC帧按字节计算的边界。",
           "用精确单位换算求时长，同时以退避取值范围和帧长单位独立核验。",
           "512表示比特而不是字节；退避倍数由随机K决定而非直接等于碰撞次数。",
           "训练共享以太网碰撞检测约束与随机退避开销的定量分析。"),
          ["以太网 / IEEE802.3","CSMA/CD","指数退避"]),
        q("media-propagation-bandwidth-delay", "cs408.cn.topic.1a141eb77fc0", "C",
          "长度2000 km的点对点链路，信号传播速率2×10⁸ m/s，数据速率5 Mb/s。忽略编解码延迟，单程传播时延与链路在满速发送时可同时容纳的比特量分别为（ ）。",
          {"A":"1 ms，5000 bit", "B":"10 ms，5000 bit", "C":"10 ms，50000 bit", "D":"100 ms，500000 bit"},
          "长度换为2×10⁶ m，单程传播时间为2×10⁶/(2×10⁸)=0.01s=10ms。带宽时延积为5×10⁶bit/s×0.01s=50000bit，即6250B。传播时延由距离和传播速度决定，与帧大小无关。",
          [("distance_speed_ratio","以米为统一距离单位计算传播时延0.01秒。"),
           ("spatial_bit_density","单位长度比特密度R/v乘链路长度等于50000bit，与带宽时延积一致。")],
          [("propagation_delay","将km转为m后计算距离除传播速度。"),("bits_in_flight","按发送速率乘单程传播时间求链路在途比特量。")],
          ("需要区别数据发送速率与介质传播速度，并连接时间和空间上的在途量。",
           "使用距离除速度求时延，再用比特空间密度独立计算带宽时延积。",
           "Mb/s中的M是十进制百万；传播时间不能用数据速率除链路长度求得。",
           "训练传输介质距离、传播时延和链路流水发送容量之间的量化关系。"),
          ["传输介质","传播时延","带宽时延积"]),
        q("tcp-demultiplex-four-tuples", "cs408.cn.topic.4ca2f6021eeb", "B",
          "服务器S=10.0.0.1在TCP端口443监听。客户端H=10.0.0.2分别用源端口50000、50001建立两条连接；客户端J=10.0.0.3也用源端口50000连到S:443。三条连接能否并存，服务器如何区分它们？",
          {"A":"只能存在一条，因为服务器端口均为443", "B":"三条可并存，由源IP、源端口、目的IP、目的端口四元组区分", "C":"H的两条不能并存，因为源IP相同", "D":"H与J的50000连接冲突，因为源端口相同"},
          "已建立TCP连接由两端IP和端口四元组标识。H两条连接的源端口不同；H与J的50000连接源IP不同。因此三条四元组各异，均可使用同一服务器监听服务端口443并存。服务器不能只按目的端口区分已建立连接。",
          [("four_tuple_enumeration","枚举(H,50000,S,443)、(H,50001,S,443)、(J,50000,S,443)，三者均不同。"),
           ("socket_demultiplex_check","用四元组集合去重得到三项，分别检查同IP不同端口及同端口不同IP场景。")],
          [("enumerate_connections","列出三条连接的完整两端地址而不只查看服务端端口。"),("compare_identity","逐对比较源端点和目的端点，确认连接标识不冲突。")],
          ("需要区分监听服务端口与已建立连接的身份，分析两类复用情形。",
           "先枚举完整四元组，再按集合唯一性核对三条连接的并存条件。",
           "共享服务端端口并不意味着连接冲突；相同源端口也需结合源IP判断。",
           "训练传输层分用、端点标识和多客户端连接复用的实际场景分析。"),
          ["传输层功能","TCP四元组","连接分用"]),
        q("arp-next-hop-remote-subnet", "cs408.cn.topic.71ab052ca21b", "D",
          "主机H的IPv4地址为10.0.0.10/24，默认网关为10.0.0.1；要向10.0.1.20发送IP数据报，路由选中该默认网关且ARP缓存为空。H首次ARP请求的目标IP及随后数据帧的目的MAC、IP数据报目的IP应如何选择？",
          {"A":"ARP查10.0.1.20；远端主机MAC；10.0.0.1", "B":"ARP查10.0.0.10；H的MAC；10.0.1.20", "C":"ARP查10.0.0.1；网关MAC；10.0.0.1", "D":"ARP查10.0.0.1；网关MAC；10.0.1.20"},
          "先按/24掩码判断目的10.0.1.20不在本地10.0.0.0/24网络，路由下一跳为网关10.0.0.1。ARP只解析本链路下一跳的MAC，因此查询网关；封装以太网帧时目的MAC为网关MAC，而端到端IP目的地址仍为10.0.1.20。",
          [("prefix_and_next_hop","按掩码判断不同子网并从路由确定下一跳，再查询其链路层地址。"),
           ("layer_address_trace","分别跟踪每跳MAC地址和端到端IP地址，确认网关仅替代帧目的地址。")],
          [("subnet_routing","利用网络前缀判断是否直接交付，选出默认网关。"),("arp_and_encapsulation","解析下一跳MAC并保留IP层最终目的地址。")],
          ("需要串联子网判断、路由下一跳、ARP解析与两层地址的不同作用域。",
           "先用前缀比较选择下一跳，再沿链路和IP封装分别核查目的地址。",
           "跨网段发送不会在本链路ARP查询远端主机，也不能把IP目的改为网关。",
           "训练主机向远端子网交付时的路由决策和逐层地址封装过程。"),
          ["ARP / DHCP / ICMP","下一跳","跨子网封装"]),
    ]


def independent_checks():
    import sympy as s
    import mpmath as mp
    x, y, t = s.symbols("x y t")
    f=x*x+2*x*y+3*y*y-1
    fx,fy=s.diff(f,x),s.diff(f,y)
    p=-fx/fy
    pp=s.diff(p,x)+s.diff(p,y)*p
    assert p.subs({x:1,y:0}) == -1 and pp.subs({x:1,y:0}) == -2
    sol=-s.log(1-x)
    assert s.simplify(s.diff(sol,x,2)-s.diff(sol,x)**2)==0
    assert s.simplify(sol.subs(x,s.Rational(1,2))-s.log(2))==0
    assert s.integrate(x-x*x/4,(x,0,4)) == s.Rational(8,3)
    with mp.workdps(45):
        integ=mp.quad(lambda z: mp.mpf(3) if z==1 else (mp.mpf(0) if z==0 else (z**3-1)/mp.log(z)),[0,mp.mpf('.5'),1])
        assert abs(integ-mp.log(4)) < mp.mpf('1e-35')
    assert s.Matrix([[1,0,1],[1,1,t],[0,1,1]]).det()==2-t
    assert 0x4000+0x120==0x4120 and 0x9000+0x18==0x9018
    tree={'A':('B','C'),'B':('D','E'),'C':(None,'G'),'D':(None,None),'E':('F',None),'F':(None,None),'G':(None,None)}
    stack=[];root='A';order=[];peak=0
    while root or stack:
        while root:
            stack.append(root);peak=max(peak,len(stack));root=tree[root][0]
        root=stack.pop();order.append(root);root=tree[root][1]
    assert order==list('DBFEACG') and peak==3
    edges=[('A','B',2),('A','C',3),('B','C',1),('B','D',4),('C','D',5),('C','E',6),('D','E',2),('B','E',7)]
    selected={'A'};picked=[]
    while len(selected)<5:
        u,v,w=min((e for e in edges if (e[0] in selected) != (e[1] in selected)),key=lambda e:e[2])
        selected.update((u,v));picked.append((u,v,w))
    assert sum(w for _,_,w in picked)==9 and [(u,v) for u,v,_ in picked]==[('A','B'),('B','C'),('B','D'),('D','E')]
    arcs=[(1,2,3),(1,3,2),(2,4,4),(3,4,5),(2,5,2),(4,6,3),(5,6,6)]
    ve={i:0 for i in range(1,7)}
    for v in range(2,7): ve[v]=max(ve[u]+w for u,k,w in arcs if k==v)
    vl={i:ve[6] for i in range(1,7)}
    for u in range(5,0,-1): vl[u]=min(vl[v]-w for k,v,w in arcs if k==u)
    assert ve[6]==11 and vl[4]-5-ve[3]==1
    align=lambda n,a:(n+a-1)//a*a
    b=align(1,4); c=align(b+4,2); size=align(c+2,4)
    assert (b,c,size)==(4,8,12) and (0x12345678).to_bytes(4,'big')[0]==0x12
    assert Fraction(64_000,8192)==Fraction(125,16)
    assert Fraction(8192*100,64_000_000)*100==Fraction(32,25)
    product=-100*3; encoded=product%65536; narrow=encoded%256
    assert encoded==0xFED4 and narrow-256==-44 and not(-128<=product<=127)
    assert (12//2+3,12//2+4,12//2)==(9,10,6)
    assert min(5000,4*1460)-(3700-1000)==2300
    assert Fraction(512*5,10_000_000)*1_000_000==256
    assert Fraction(2_000_000,200_000_000)*1000==10
    assert 5_000_000*Fraction(2_000_000,200_000_000)==50_000
    assert len({('10.0.0.2',50000,'10.0.0.1',443),('10.0.0.2',50001,'10.0.0.1',443),('10.0.0.3',50000,'10.0.0.1',443)})==3
    specs=candidates()
    assert len(specs)==23 and len({r['request'] for r in specs})==23
    for row in specs:
        assert all(len(v)>=20 for v in row['reason'].values()), row['request']
        assert len(set(row['output'].options.values()))==4, row['request']
        assert sum(row['truth'].values())==1 and row['truth'][row['answer']], row['request']
    return {"status":"PASS","math_symbolic_and_numeric_cases":5,"algorithm_and_exact_calculation_cases":12,
            "rule_based_cases":["spooling FIFO complete-file timeline", "work-conserving CPU/I-O timeline",
                "IPv6 router MTU and source fragmentation", "VLAN10 broadcast domain", "synchronous page fault vs asynchronous I/O interrupt", "ARP next hop with preserved IP destination"],
            "candidate_structure_cases":23,"paid_model_calls":0}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=("dry-run","apply"),default="dry-run")
    args=parser.parse_args()
    checks=independent_checks()
    if not BACKUP.is_file() or runner.sha_file(BACKUP)!=BACKUP_SHA256:
        raise SystemExit("prebatch_backup_missing_or_hash_mismatch")
    toc=subprocess.run([r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe","--list",str(BACKUP)],capture_output=True,timeout=30)
    if toc.returncode or b"TABLE DATA public questions" not in toc.stdout:
        raise SystemExit("prebatch_backup_archive_invalid")
    output=OUT_DIR/("preview.json" if args.mode=="dry-run" else "checkpoint.json")
    if output.exists(): raise SystemExit("refusing_to_overwrite_existing_output")
    runner.BACKUP,runner.BACKUP_SHA256=BACKUP,BACKUP_SHA256
    engine=create_engine(URL.create("postgresql+psycopg",username="postgres",host="127.0.0.1",port=PORT,database=DB_NAME),pool_pre_ping=True)
    try:
        with Session(engine,expire_on_commit=False) as db:
            db.begin()
            try:
                report=runner.run(db,candidate_specs=candidates(),batch_id="12")
                report['status']='DRY_RUN_ROLLED_BACK' if args.mode=='dry-run' else 'BATCH12_APPLIED'
                report['independent_checks']=checks
                report['backup']['toc_entries']=len(toc.stdout.splitlines())
                if runner.sha_file(BACKUP)!=BACKUP_SHA256: raise ValueError('prebatch_backup_changed')
                db.rollback() if args.mode=='dry-run' else db.commit()
            except BaseException:
                db.rollback(); raise
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':report['status'],'accepted':len(report['accepted']),'rejected':report['rejected'],'checkpoint':output.relative_to(ROOT).as_posix()},ensure_ascii=True))
    finally: engine.dispose()


if __name__=='__main__': main()
