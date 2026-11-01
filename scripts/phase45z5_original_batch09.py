"""Ninth offline-authored public-original batch for the isolated Z5 database."""
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

BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch08/post-batch08.dump"
BACKUP_SHA256 = "BBBC67E3D49857CFF268249778C2B03DB79ED5692CAD45ACD02B4D31968C1B37"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch09"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"


def candidates():
    return [
        item("z5b9-math-rotation-volume-surface-boundary", "math.exam.9f10ce353fbd", "C",
            "平面曲线y=1/x（x≥1）与x轴围成的无界区域分别绕x轴旋转，所得旋转体体积V和旋转曲面侧面积S（不含端面）满足（ ）。",
            {"A": "V、S均有限", "B": "V发散、S有限", "C": "V有限、S发散", "D": "V、S均发散"},
            "圆盘法V=π∫₁∞x⁻²dx=π，故体积有限。侧面积S=2π∫₁∞(1/x)√(1+1/x⁴)dx。根号因子在[1,∞)介于1与√2之间，故侧面积积分与∫₁∞dx/x同敛散，发散。体积与面积具有不同幂次阈值，不能共用同一结论。",
            [("volume_p_integral", "平方半径使体积被积项为x⁻²，积分值π∫₁∞x⁻²dx=π。"),
             ("surface_area_comparison", "侧面积根号因子有正有界上下界，主阶为1/x，故与调和型积分同发散。")],
            [("geometric_formulas", "体积采用πy²，侧面积采用2πy√(1+y'²)，两者半径幂次不同。"),
             ("comparison_test", "对面积根号因子夹在1和√2之间，直接比较∫₁∞dx/x发散。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需区分旋转体体积和旋转侧面积的积分模型并检查无穷端点。", "用圆盘积分与侧面积比较判别分别核验敛散性。", "侧面积含弧长因子而非仅有y；其根号因子有界但半径1/x仍导致对数发散。", "分析同一无界曲线生成的体积与表面积具有不同收敛阈值。"),
            ["旋转体体积", "侧面积", "反常积分"], difficulty="advanced"),

        item("z5b9-math-mvt-logarithm-point", "math.exam.4586eb88acb7", "D",
            "函数f(x)=ln x在[1,e²]上应用拉格朗日中值定理，存在点c∈(1,e²)使f'(c)=[f(e²)−f(1)]/(e²−1)。该c为（ ）。",
            {"A": "e", "B": "(e²+1)/2", "C": "e²/2", "D": "(e²−1)/2"},
            "割线斜率为(2−0)/(e²−1)=2/(e²−1)，而f'(c)=1/c。故c=(e²−1)/2。该点确实位于(1,e²)：e²>3使c>1，且e²−1<2e²使c<e²。导数严格递减也说明该等式对应点唯一。",
            [("mvt_equation_solution", "把f'(c)=1/c与割线斜率2/(e²−1)相等，解得c=(e²−1)/2。"),
             ("interval_and_uniqueness", "验证1<c<e²，且1/x严格递减，因此该点在区间内部且唯一。")],
            [("secant_slope", "端点函数值差为2，横坐标差为e²−1，平均变化率为2/(e²−1)。"),
             ("derivative_match", "令1/c等于平均变化率并解出c，再检查其落在开区间。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要明确中值定理给出的导数方程并求解其内部点。", "用割线斜率方程求点，再用单调性核验存在位置与唯一性。", "不能把中值点误认为区间中点；MVT匹配的是函数值变化率而非长度平均。", "把微分中值定理、指数区间和导数单调性结合应用。"),
            ["拉格朗日中值定理", "平均变化率", "对数函数"], difficulty="medium"),

        item("z5b9-math-integral-average-value-point", "math.exam.4a56bd52caf7", "A",
            "连续函数f(x)=3x²−2x+1在[0,2]上的平均值为3。满足f(ξ)=3的点ξ∈(0,2)为（ ）。",
            {"A": "(1+√7)/3", "B": "(1−√7)/3", "C": "1", "D": "√3"},
            "平均值(1/2)∫₀²(3x²−2x+1)dx=(1/2)(8−4+2)=3。解3ξ²−2ξ+1=3，得3ξ²−2ξ−2=0，根为(1±√7)/3；负根不在(0,2)，故唯一符合区间的是(1+√7)/3。",
            [("mean_value_integral", "直接求定积分为6，再除以区间长度2得到平均值3。"),
             ("quadratic_root_interval", "解二次方程得两个根，再按0<ξ<2筛选唯一正根。")],
            [("exact_integral", "原函数x³−x²+x在0与2的差为6，除以区间长2得到3。"),
             ("intermediate_value_check", "f连续且f(0)=1、f(2)=9，存在点取到3；二次方程区间筛选给出唯一点。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需先求定积分平均值，再解函数达到平均值的内部位置。", "精确积分和均值方程两步计算，并利用区间筛掉另一根。", "定积分平均值不是中点函数值；二次方程有两个代数根但只有一个落在区间。", "把积分平均值定理与多项式等值方程和区间根筛选联系起来。"),
            ["定积分平均值", "积分中值定理", "二次方程"], difficulty="medium"),

        item("z5b9-math-piecewise-continuity-parameter", "math.exam.71a29108dd89", "B",
            "函数f_a(x)在x≤0时等于x²，在x>0时等于x²+ax。关于x=0处的连续性与可导性，正确的是（ ）。",
            {"A": "任意a均不连续", "B": "任意a均连续，且仅a=0时可导", "C": "仅a=0时连续且可导", "D": "任意a均可导"},
            "两侧函数值均趋于0且f_a(0)=0，所以所有实数a下在0连续。左导数为0；右差商为[x²+ax]/x=x+a，右极限为a。左右导数相等当且仅当a=0，故只有a=0时可导。",
            [("continuity_limit", "右侧x²+ax在x→0时趋于0，左侧x²亦趋于0，与函数值相等。"),
             ("one_sided_derivative", "左导数0、右导数a，逐侧比较得到可导条件a=0。")],
            [("difference_quotient", "在0处左差商为x→0，右差商为x+a→a。"),
             ("parameter_case", "连续不要求导数相等；只有参数a取0时两侧导数相同。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("要分别检查函数极限和左右差商，区分连续与可导条件。", "从单侧函数极限证明连续，再从左右导数求参数条件。", "含ax的右支仍趋于0故连续；可导性却受到其线性项影响。", "训练分段参数函数在拼接点的连续与可导层级判定。"),
            ["连续性", "间断点", "左右导数"], difficulty="medium"),

        item("z5b9-math-polar-half-disk-integral", "math.exam.609e58acbace", "C",
            "区域D为单位圆盘x²+y²≤1的右半圆x≥0。积分∬D x dA等于（ ）。",
            {"A": "π/4", "B": "1/3", "C": "2/3", "D": "π/2"},
            "改用极坐标x=r cosθ、dA=r dr dθ，右半圆对应0≤r≤1、−π/2≤θ≤π/2。积分为∫_{−π/2}^{π/2}∫₀¹r²cosθ dr dθ=(1/3)×2=2/3。直角坐标复核：∫₀¹2x√(1−x²)dx，令u=1−x²亦得2/3。",
            [("polar_coordinate_integral", "极坐标区域和Jacobian给r²cosθ，径向积分1/3、角向积分2。"),
             ("cartesian_substitution", "直角坐标积分为2∫₀¹x√(1−x²)dx，代换后为2/3。")],
            [("region_symmetry", "右半圆上下对称，角度区间为−π/2到π/2且cosθ非负。"),
             ("jacobian_factor", "面积元含r，故x dA含r²；遗漏Jacobian会得到错误径向幂次。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需正确表示半圆角域并在极坐标中加入面积Jacobian。", "极坐标直接积分后用直角坐标代换独立复核。", "对称区域不意味着x积分为零，因为区域仅是右半圆；面积元还需乘r。", "运用极坐标变换、区域对称和二重积分物理几何意义。"),
            ["极坐标变换", "二重积分", "区域对称性"], difficulty="medium"),

        item("z5b9-math-inflection-points-polynomial", "math.exam.79c96a83b3ff", "A",
            "设f_a(x)=x⁴−2ax²，其中a为实参数。关于拐点个数，正确的是（ ）。",
            {"A": "a>0时有2个，a≤0时没有", "B": "任意a均有1个拐点x=0", "C": "a<0时有2个，a≥0时没有", "D": "a>0时有1个拐点x=0"},
            "二阶导数为f_a''(x)=12x²−4a。若a>0，其零点为±√(a/3)，二阶导数在区间上呈正、负、正，两个零点处凹凸性均改变，故有2个拐点。若a<0，则f_a''始终为正；若a=0，则f_a''=12x²在0两侧均为正，均无凹凸性改变。因此a≤0时没有拐点，选A。",
            [("parameter_sign_partition", "对a>0解出±√(a/3)并检查f''符号为正、负、正；a≤0时f''不变号。"),
             ("inflection_definition_check", "逐一检查候选根两侧凹凸性；a=0处虽然f''=0但没有符号变化。")],
            [("second_derivative_roots", "由12x²−4a=0可知只有a>0时存在两个不同实根±√(a/3)。"),
             ("boundary_parameter_case", "a=0时二阶导数为12x²，原点两侧同为正；a<0时处处为正。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要对参数符号分类，并区分二阶导数零点和真正拐点。", "通过求根分类与凹凸性符号变化两条路径检查各参数范围。", "a=0时原点满足f''=0但不变号，不能把候选点误判为拐点。", "将参数讨论、二阶导数零点和拐点定义结合起来分析函数族。"),
            ["曲线拐点", "二阶导数", "凹凸性"], difficulty="medium"),

        item("z5b9-408-client-server-distribution-time", "cs408.cn.topic.a44bb362c00a", "B",
            "客户端/服务器模型向N=5个客户端分发大小F=1200 Mbit的文件。服务器上行速率u_s=100 Mbit/s，每个客户端下行速率均为20 Mbit/s；忽略传播与协议开销，文件分发时间下界取max(NF/u_s,F/d_min)。该下界为（ ）。",
            {"A": "12 s", "B": "60 s", "C": "100 s", "D": "600 s"},
            "服务器必须上传N份文件，上传下界NF/u_s=5×1200/100=60 s。最慢客户端接收完整文件的下界F/d_min=1200/20=60 s。两约束取最大值，故分发时间下界为60 s。该模型下可通过调度使服务器上传与客户端接收并行达到此约束下界。",
            [("server_upload_lower_bound", "服务器上传量为6000Mbit，除100Mbit/s得60s。"),
             ("slowest_client_lower_bound", "单个客户端接收1200Mbit，除20Mbit/s也需60s，取两者最大。")],
            [("workload_rate_accounting", "每个客户端都需获得完整文件，服务器承担5份上传工作量。"),
             ("max_constraint", "分发时间同时不小于总上传时间和最慢接收时间，因此取max(60,60)。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要把总体上传工作量与单个最慢客户端下载约束分开求下界。", "计算服务器总发送量及单客户端接收时间后取最大值。", "不能用F/u_s代替NF/u_s；服务器模型要求分别向N个客户端上传。", "使用客户机服务器分发模型评估上传瓶颈与末端接收瓶颈。"),
            ["客户机服务器模型", "文件分发", "吞吐率"], difficulty="medium"),

        item("z5b9-408-network-congestion-bottleneck", "cs408.cn.topic.b8e94d7c568d", "B",
            "两个独立流以7和6 Mbit/s持续进入容量为10 Mbit/s的瓶颈链路。出口缓存初始为空，容量为6 Mbit，未满前不丢包。假设输入速率和链路服务率保持不变，缓存何时填满，填满后长期平均丢弃速率为（ ）。",
            {"A": "3 s；0 Mbit/s", "B": "2 s；3 Mbit/s", "C": "6 s；3 Mbit/s", "D": "2 s；13 Mbit/s"},
            "聚合到达率为7+6=13 Mbit/s，瓶颈服务率为10 Mbit/s，因此缓存净增长率是3 Mbit/s。容量6 Mbit的空缓存经过6/3=2 s填满。稳定持续输入时链路最多服务10 Mbit/s，剩余3 Mbit/s必须被丢弃，故选B。该结论假设无流量控制反馈改变源发送速率，题干已固定输入速率。",
            [("aggregate_queue_dynamics", "到达率13减去服务率10，得到每秒增长3Mbit；6Mbit缓存需2秒填满。"),
             ("steady_state_loss_balance", "缓存满后输入仍为13而服务10，长期丢弃率由流量守恒为3Mbit/s。")],
            [("fluid_queue_model", "在缓存未满的前2秒，队列长度Q(t)=(13−10)t，Q=6时t=2秒。"),
             ("rate_conservation", "满队列稳态下到达率=服务率+丢弃率，故丢弃率=13−10=3Mbit/s。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要分析缓存未满阶段的净积累与满队列后的稳定流量守恒。", "以队列变化计算填满时间，再用稳态到达服务平衡求丢弃率。", "不能把总输入13Mbit/s当作链路输出；无反馈条件下超额流量最终丢弃。", "把网络拥塞的队列演化、缓存容量和稳态丢包率联系起来。"),
            ["网络层拥塞控制", "瓶颈链路", "排队"], difficulty="medium"),

        item("z5b9-408-communication-bandwidth-delay-product", "cs408.cn.topic.e567ffa4c80f", "A",
            "一条链路带宽为2 Mbit/s，单向传播时延25 ms，确认帧开销忽略。采用窗口为8 KiB的滑动窗口协议，且窗口内数据可以连续发送。取1 KiB=1024 B，发送方能够达到的最大有效吞吐率上界约为（ ）。",
            {"A": "1.31 Mbit/s", "B": "1.64 Mbit/s", "C": "2.00 Mbit/s", "D": "0.66 Mbit/s"},
            "往返传播时延RTT=2×25ms=0.05s。窗口限制的吞吐率上界为W/RTT=(8×1024×8 bit)/0.05s=1,310,720 bit/s≈1.31Mbit/s。链路本身容量为2Mbit/s，实际受窗口约束，故取min(2,1.31)=1.31Mbit/s，选A。满载需要约R×RTT=100kbit在途数据，当前窗口65,536bit低于该值。",
            [("window_rate_bound", "8KiB换算为65,536bit，除RTT 0.05s得1.31072Mbit/s。"),
             ("bandwidth_delay_product_check", "满载需约2Mbit/s×0.05s=100kbit在途数据，当前窗口不足。")],
            [("unit_and_rtt", "单向25ms对应RTT 50ms；8KiB按1024字节换算成65,536bit。"),
             ("minimum_constraint", "窗口约束给出1.31072Mbit/s，取它与物理链路带宽2Mbit/s的较小值。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需同时理解滑动窗口、往返传播时延和带宽时延积的约束关系。", "先换算窗口与RTT求W/RTT，再与物理链路带宽取最小值。", "窗口吞吐公式使用RTT而非单向时延；KiB与kbit也要统一换算。", "用窗口限制解释可靠传输协议无法充分利用高带宽长时延链路的原因。"),
            ["通信基础", "带宽时延积", "传播时延"], difficulty="medium"),

        item("z5b9-408-compile-link-load-relocation", "cs408.co.topic.53f5a8046fd9", "C",
            "两个分别编译的目标模块M1、M2中，M1引用M2定义的外部符号foo；链接时才确定foo在合并后程序中的地址，装入基址又可能因运行位置改变。对这一过程，正确的是（ ）。",
            {"A": "编译M1时必须已知foo最终物理地址，否则源文件不可编译", "B": "装入时只能修改源代码中的函数名，不能修改地址字段", "C": "链接器解析模块间符号引用，装入/重定位阶段再按实际装入地址调整可重定位地址", "D": "外部符号由CPU执行指令时通过ARP解析"},
            "分模块编译可先产生带外部符号引用的目标文件；链接器合并模块并解析foo的符号地址。若最终装入基址在运行时确定，装入器或重定位机制再把模块内相对地址调整为实际地址。符号解析与装入基址重定位是相关但不同阶段。",
            [("toolchain_stage_separation", "链接阶段解析模块间foo符号；装入阶段根据实际基址调整地址字段。"),
             ("relocation_arithmetic", "目标地址由模块相对偏移加实际装入基址得到，非源代码名称替换。")],
            [("separate_compilation", "外部符号可先保留在目标文件重定位项中，最终地址待链接处理。"),
             ("loader_binding", "若装入位置改变，运行时基址仍需参与地址修正，不能由编译时固定。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要区分编译、链接符号解析和装入时地址重定位三个阶段。", "按模块依赖和基址变化分别追踪地址何时确定。", "链接地址解析不等于装入基址修正；二者不能都归给源代码编译或CPU。", "理解高级语言到机器级程序的模块化翻译与地址绑定流程。"),
            ["编译与链接", "外部符号", "装入重定位"], difficulty="medium"),

        item("z5b9-408-programmed-io-polling", "cs408.co.topic.bfd3c1878167", "B",
            "采用程序查询方式输入数据时，CPU循环读取设备状态寄存器，直到状态位表明数据就绪，再读数据寄存器。若设备长时间未就绪且CPU一直执行该循环，最准确的描述是（ ）。",
            {"A": "CPU进入中断等待，不消耗处理器周期", "B": "属于忙等待，CPU主动反复查询状态，期间难以执行其他任务", "C": "设备用DMA直接写内存，CPU无需查询", "D": "状态寄存器由ARP请求更新"},
            "程序查询方式由CPU执行指令反复读取状态寄存器；设备未就绪时，处理器仍在执行轮询指令，故属于忙等待，会占用CPU周期。中断方式是设备就绪后通知CPU，DMA则由控制器直接在设备与内存间传输，均与题设过程不同。",
            [("polling_execution_semantics", "CPU循环发起状态读取，未就绪期间仍持续执行指令并占用处理器。"),
             ("interrupt_dma_contrast", "若由中断或DMA处理，CPU不必反复逐次查询状态位。")],
            [("control_flow_trace", "状态不就绪时程序跳回查询分支，直到条件改变才继续读数据。"),
             ("resource_use", "轮询指令消耗CPU时间片，因此该场景是忙等待而非阻塞休眠。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需根据控制流判断CPU在设备未就绪时是否继续执行查询。", "用轮询循环语义与中断/DMA机制对照确认。", "程序查询、程序中断和DMA是不同I/O控制方式；查询循环不会自动变成中断等待。", "评估I/O控制方式对CPU占用和设备响应的影响。"),
            ["程序查询方式", "I/O控制", "忙等待"], difficulty="medium"),

        item("z5b9-408-sorting-algorithm-stability-inplace", "cs408.ds.topic.0924b31367c4", "D",
            "对记录序列(3,a)、(1,b)、(3,c)、(2,d)升序排序，要求原地（辅助空间O(1)）且稳定。下列算法中能同时满足要求的是（ ）。",
            {"A": "归并排序", "B": "堆排序", "C": "简单选择排序", "D": "直接插入排序"},
            "直接插入排序可原地移动元素，辅助空间为O(1)；插入时只将严格大于当前关键字的记录右移，相等关键字不跨越，因此稳定。归并排序通常需要O(n)辅助空间，堆排序原地但不稳定，简单选择排序原地但可能通过远距离交换改变相等记录次序。",
            [("algorithm_property_intersection", "插入排序的空间为O(1)且稳定，满足两个条件交集。"),
             ("counterexample_elimination", "堆排序与选择排序虽原地但不稳定；归并排序稳定但常规实现非O(1)空间。")],
            [("record_identity_stability", "插入只移动更大元素，两个关键字3的a、c保持a先于c。"),
             ("space_operation_trace", "算法只在原数组内移动记录，不申请随n增长的辅助数组。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需同时判断稳定性和辅助空间，不能仅凭时间复杂度选择排序。", "用排序算法性质表交叉筛选，并追踪相等记录身份。", "归并排序的稳定性不满足O(1)辅助空间；堆与选择排序不保证稳定。", "综合排序性质、记录身份保持和空间限制选择算法。"),
            ["排序算法比较", "稳定性", "辅助空间"], difficulty="medium"),

        item("z5b9-408-lower-triangular-packed-index", "cs408.ds.topic.1b4089986d5e", "C",
            "5阶对称矩阵只存下三角（含主对角线），按行优先连续存入从0开始编号的一维数组：先存A₁₁，再存A₂₁、A₂₂，依此类推。矩阵元素A₄₂存放在数组下标（ ）。",
            {"A": "6", "B": "8", "C": "7", "D": "9"},
            "前三行分别占1、2、3个位置，共1+2+3=6个元素，零基数组下标从0开始，因此第四行首元素A₄₁下标6，接下来的A₄₂下标7。公式i(i−1)/2+(j−1)代入i=4、j=2也得7。",
            [("row_prefix_count", "A₄₂前有前三行6项及本行首项A₄₁，故零基下标7。"),
             ("triangular_storage_formula", "行优先下三角零基位置为i(i−1)/2+j−1，代入得到7。")],
            [("explicit_sequence", "数组序列至A₃₃为下标0到5，A₄₁为6，A₄₂为7。"),
             ("symmetry_storage_rule", "对称性使上三角不另存，目标元素按下三角行序唯一定位。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需计算压缩行存储的前缀元素数并处理零基下标。", "通过逐行展开与闭式位置公式两种方法核对。", "下标起点为0且第四行首项位置为6，不能把1基公式结果直接照搬。", "联系对称矩阵压缩存储、行长度和随机访问地址计算。"),
            ["特殊矩阵压缩存储", "下三角矩阵", "数组下标"], difficulty="medium"),

        item("z5b9-408-deque-operation-trace", "cs408.ds.topic.48e8e73d9928", "A",
            "双端队列初始为空，依次执行：队尾插入a、队尾插入b、队头插入c、删除队尾、队头插入d、队尾插入e、删除队头、删除队尾、队头插入f。操作结束后从队头到队尾为（ ）。",
            {"A": "f、c、a", "B": "c、a、f", "C": "f、a、c", "D": "c、a"},
            "依次记录状态：[]→[a]→[a,b]→[c,a,b]→[c,a]→[d,c,a]→[d,c,a,e]→[c,a,e]→[c,a]→[f,c,a]。所以最终队列从队头到队尾为[f,c,a]，选A。9步中有6次插入、3次删除，最终长度3，也与状态长度相符。",
            [("deque_endpoint_trace", "逐步更新两端，最终状态为[f,c,a]，顺序由队头插入f及原有c、a组成。"),
             ("operation_count_check", "6次插入和3次删除后净长度3，与逐步状态跟踪结果一致。")],
            [("state_table", "状态序列为[]、[a]、[a,b]、[c,a,b]、[c,a]、[d,c,a]、[d,c,a,e]、[c,a,e]、[c,a]、[f,c,a]。"),
             ("front_rear_semantics", "先删除尾端b，再删头端d和尾端e；剩余c、a后在头端加入f。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需在每一步明确队头、队尾位置并执行多轮交替操作。", "用逐步状态序列和插入删除计数双重追踪最终内容。", "交替端点操作容易混淆队头方向；必须区分插入端与删除端。", "训练双端队列复杂操作序列中的端点语义与状态更新。"),
            ["双端队列", "队头队尾", "操作序列"], difficulty="medium"),

        item("z5b9-408-preorder-inorder-postorder", "cs408.ds.topic.56a82ba8b1ba", "C",
            "二叉树先序序列为A、B、D、E、C、F，中序序列为D、B、E、A、F、C。其后序序列为（ ）。",
            {"A": "D、E、B、A、F、C", "B": "D、B、E、F、C、A", "C": "D、E、B、F、C、A", "D": "B、D、E、C、F、A"},
            "先序首项A为根；中序把左子树分为D、B、E，右子树为F、C。左子树根B，左右孩子D、E，后序为D、E、B；右子树根C且左孩子F，后序为F、C。最后访问根A，合并得D、E、B、F、C、A。",
            [("preorder_inorder_partition", "先序根A配合中序区间递归重建左右子树，再分别得到DEB和FC。"),
             ("postorder_composition", "后序按左、右、根拼接为DEB、FC、A。")],
            [("left_subtree_trace", "左子树根B的左右孩子D、E，其后序为D,E,B。"),
             ("right_subtree_trace", "右子树根C只有左孩子F，后序F,C，再输出A。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需用先序与中序恢复结构，再按后序访问规则递归拼接。", "从根划分左右子树并分别推导，最后做根序检查。", "中序区间决定左右归属；右子树C有左孩子F，后序必须先F再C。", "综合不同遍历序列的根定位、子树划分与后序生成。"),
            ["前序遍历", "中序遍历", "后序遍历"], difficulty="medium"),

        item("z5b9-408-insertion-sort-second-pass", "cs408.ds.topic.60bf2405e5c6", "B",
            "对数组[7,4,5,2,9]执行升序直接插入排序。第一趟将第2个元素插入有序前缀，第二趟再将第3个元素插入。第二趟结束后的数组为（ ）。",
            {"A": "[4,5,2,7,9]", "B": "[4,5,7,2,9]", "C": "[4,7,5,2,9]", "D": "[2,4,5,7,9]"},
            "初始有序前缀为[7]。第一趟插入4得到[4,7,5,2,9]。第二趟取5，在有序前缀[4,7]中右移7并插入到4之后，得到[4,5,7,2,9]。元素2与9尚未进入前两趟的插入处理。",
            [("pass_by_pass_trace", "第一趟后[4,7,5,2,9]，第二趟将5插在4与7之间。"),
             ("sorted_prefix_invariant", "第二趟结束时仅前三项有序，尾部2、9保持原相对位置。")],
            [("insertion_position", "5大于4而小于7，故插入已排序前缀中间。"),
             ("pass_count", "每趟只处理下一个元素，共两趟后前缀长度3。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要严格按趟次维护插入排序的有序前缀和未处理后缀。", "逐趟模拟移动过程并用有序前缀不变量检查状态。", "第二趟不处理元素2；也不能把最终全排序结果提前写入。", "通过记录移动过程理解直接插入排序的逐步有序化。"),
            ["直接插入排序", "排序过程", "有序前缀"], difficulty="medium"),

        item("z5b9-408-circular-list-tail-insertion", "cs408.ds.topic.6c5786034fef", "D",
            "带头结点的循环单链表非空，指针p当前指向尾结点且p.next=head。要在尾部插入新结点s，保持循环结构并继续令p指向新尾结点，正确的指针更新顺序为（ ）。",
            {"A": "p.next=s; s.next=head; p=s", "B": "s.next=p; p.next=head; p=s", "C": "s.next=head; p=head; p.next=s", "D": "s.next=head; p.next=s; p=s"},
            "新结点应先指向头结点以保持环闭合，再令旧尾结点指向s，最后把尾指针更新为s。即s.next=head; p.next=s; p=s。更新后从新尾结点沿next仍回到头结点，所有原结点链路保持不变。",
            [("tail_link_update", "将s.next设为head，再把旧尾p.next改为s，最后p=s。"),
             ("cycle_invariant", "插入后新尾的next仍为head，且旧尾到新结点的链未断。")],
            [("pointer_graph", "插入前p→head；插入后p_old→s→head，尾指针指s。"),
             ("reachability_check", "从头结点沿next仍可经过全部原结点及s并回到head。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需同时维护旧尾后继、新结点后继和尾指针角色。", "按目标指针图更新，并用循环不变量验证闭环。", "先改p.next会丢失原来指向head的信息；需让新结点先保存head。", "训练循环单链表尾插中的指针顺序与结构不变式。"),
            ["循环链表", "尾插", "指针更新"], difficulty="medium"),

        item("z5b9-408-prim-mst-total-weight", "cs408.ds.topic.b66f6167354e", "A",
            "无向连通图边权为AB=2、AC=3、BC=1、BD=4、CD=2、CE=5、DE=1。用Prim算法从A开始构造最小生成树，其总权值为（ ）。",
            {"A": "6", "B": "7", "C": "8", "D": "9"},
            "从A开始，先选最小跨割边AB=2；再从{A,B}选BC=1；从{A,B,C}选CD=2；最后从{A,B,C,D}选DE=1。五顶点生成树需4条边，总权值2+1+2+1=6。边AC=3或CE=5均不比相应已选跨割边更优。",
            [("prim_cut_trace", "逐次从已加入集合到外部选择最小边，得到AB、BC、CD、DE。"),
             ("tree_edge_weight_sum", "四条边权相加2+1+2+1=6，恰连接全部5个顶点。")],
            [("cut_minimum_check", "每轮检查跨当前生成树割的候选边，所选边分别为2、1、2、1。"),
             ("spanning_tree_invariant", "每次只加入一个新顶点，4次后覆盖5顶点且无环。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("要按Prim当前顶点集合逐步更新跨割候选边。", "记录每轮选择与边权，再用生成树边数和割最小性核对。", "不能一次性按全图边权排序；选择取决于当前已连接顶点集合。", "演示Prim贪心扩张与最小生成树权值累计。"),
            ["Prim算法", "最小生成树", "割性质"], difficulty="medium"),

        item("z5b9-408-circular-queue-capacity", "cs408.ds.topic.cd35413f05e7", "B",
            "循环队列数组长度为8，front指向队头元素，rear指向下一次入队位置，并保留一个空单元区分队满和队空。当前front=6、rear=3，队列中元素依次为p、q、r、s、t。随后连续出队2次，再依次入队u、v、w。操作完成后，队列元素个数与(front,rear)为（ ）。",
            {"A": "7；(7,6)", "B": "6；(0,6)", "C": "6；(6,0)", "D": "5；(0,5)"},
            "初始队列元素数为(3−6+8) mod 8=5，与题给序列p、q、r、s、t一致。出队2次后front从6循环到0，剩余r、s、t；入队u、v、w使rear从3前进三格到6。最终序列为[r,s,t,u,v,w]，共6项且(front,rear)=(0,6)。留空法最大容量为7，因此该状态未满。",
            [("modular_state_trace", "front 6出队两次到0；rear 3入队三次到6，均按模8更新。"),
             ("logical_length_check", "模差(rear−front+8) mod8=(6−0)=6，与剩余6个元素一致。")],
            [("explicit_contents", "出队p、q后为[r,s,t]，再入队u、v、w得到[r,s,t,u,v,w]。"),
             ("capacity_invariant", "长度6小于留空法最大容量7，front=0、rear=6表示未满且非空。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需结合循环下标更新、逻辑长度和留空判满规则分析队列状态。", "先追踪front和rear，再用序列计数和模差公式独立复核。", "物理数组8格并不代表逻辑容量8；留空单元必须纳入判满边界。", "理解循环队列的模运算、端点语义、状态迁移与容量限制。"),
            ["队列", "循环队列", "队满判定"], difficulty="medium"),

        item("z5b9-408-bubble-sort-first-pass-swaps", "cs408.ds.topic.dd68a6da9516", "C",
            "对数组[5,1,4,2,8]执行两趟从左到右的升序冒泡排序，每次比较相邻元素，逆序时交换。两趟结束后的数组与累计交换次数为（ ）。",
            {"A": "[1,2,4,5,8]；3次", "B": "[1,4,2,5,8]；4次", "C": "[1,2,4,5,8]；4次", "D": "[1,2,4,5,8]；5次"},
            "第一趟依次比较(5,1)、(5,4)、(5,2)、(5,8)，前三次交换，得[1,4,2,5,8]。第二趟在未排序前缀内比较(1,4)、(4,2)、(4,5)：仅(4,2)交换，得[1,2,4,5,8]。累计交换数3+1=4。两趟后末尾两个元素已有序，但第一趟结果不能误当作全排序。",
            [("two_pass_trace", "第一趟得到[1,4,2,5,8]并交换3次；第二趟得到[1,2,4,5,8]再交换1次。"),
             ("inversion_count", "初始逆序对为(5,1),(5,4),(5,2),(4,2)，共4个；冒泡每次交换消去一个逆序。")],
            [("pass_invariant", "第一趟最大值5到末端，第二趟次大值4到倒数第二位。"),
             ("swap_conservation", "相邻交换每次消去一个逆序，初始4个逆序经两趟全部消除。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需按趟次维护已排序后缀并累计交换，同时分析初始逆序对。", "两趟模拟与初始逆序数守恒两种方法验证结果4次交换。", "第一趟后序列仍未完全有序；不能把第一趟交换次数当作总数。", "把冒泡排序的局部执行、趟次不变量和逆序对减少联系起来。"),
            ["冒泡排序", "排序过程", "相邻交换"], difficulty="medium"),
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
                report = run_batch(db, candidate_specs=candidates(), batch_id="09")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH09_APPLIED"
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
