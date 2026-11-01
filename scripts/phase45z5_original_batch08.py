"""Eighth offline-authored public-original batch for the isolated Z5 database."""
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

BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch07-revised/post-batch07.dump"
BACKUP_SHA256 = "B92D3098EE27365B7017511151CC42FA4DC3AA498B1888119006B002DC44E3AD"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch08"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"


def candidates():
    return [
        item("z5b8-math-newton-cooling-log-time", "math.exam.51d573e440d0", "B",
            "环境温度恒为20℃，物体按牛顿冷却定律满足T'=−k(T−20)，k>0。测得T(0)=80℃、T(2)=50℃。物体温度首次降至35℃所需时间为（ ）。",
            {"A": "2 ln 2", "B": "4", "C": "2 ln 3", "D": "6"},
            "温差θ=T−20满足θ'=-kθ，故θ(t)=60e^(−kt)。由θ(2)=30得e^(−2k)=1/2、k=ln2/2。目标温度35℃对应θ=15，即θ/60=1/4；因此e^(−kt)=1/4，t=ln4/k=2ln4/ln2=4。解单调趋近环境温度，故首次达到时间唯一。",
            [("cooling_exponential_fit", "温差解为60e^(−kt)，第二个测量值确定e^(−2k)=1/2，再代目标温差15求时刻。"),
             ("logarithmic_time_equation", "目标比值θ/60=1/4，故t=ln4/k=2ln4/ln2=4。")],
            [("initial_condition_solution", "牛顿冷却方程给T(t)=20+60e^(−kt)，代入两测量点可确定k=ln2/2。"),
             ("target_temperature_substitution", "令T=35得e^(−kt)=1/4，代入k后t=4，且温度随时间单调下降。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需先由两组温度数据识别指数衰减常数，再反解目标温度时刻。", "用温差指数解和对数方程两步核验，结果必须与选项一致。", "把温差从60降到30的时间直接套到目标温差10会误用半衰期；注意目标比值是1/6。", "把微分方程初值解、参数拟合和实际目标时刻求解串联。"),
            ["牛顿冷却定律", "一阶微分方程", "参数拟合"], difficulty="advanced"),

        item("z5b8-math-matrix-polynomial-power", "math.exam.712e07e16572", "B",
            "矩阵A满足A²−3A+2I=0。仅依据此恒等式，A⁵可化为（ ）。",
            {"A": "31A−31I", "B": "31A−30I", "C": "30A−29I", "D": "32A−31I"},
            "由A²=3A−2I递推：A³=3A²−2A=7A−6I；A⁴=7A²−6A=15A−14I；A⁵=15A²−14A=31A−30I。也可在多项式模p(x)=x²−3x+2下求x⁵的余式，余式为31x−30。",
            [("matrix_recurrence", "逐次用A²=3A−2I降幂，递推到A⁵=31A−30I。"),
             ("polynomial_remainder", "将x⁵除以x²−3x+2，余式为31x−30，再代x=A。")],
            [("induction_reduction", "若Aⁿ=uA+vI，则乘A并再次代换A²可得下一阶系数递推。"),
             ("eigenvalue_polynomial_check", "恒等式的根为1、2；余式r(x)=31x−30满足r(1)=1及r(2)=32=x⁵的值。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要使用低次矩阵多项式恒等式对高次幂反复降幂。", "通过直接递推与模多项式余式两种方式得到同一线性表达。", "代换时常数项符号易错；特征根代入只能作必要交叉检查，不能代替余式推导。", "训练矩阵多项式关系反复降阶以计算高次幂的全过程。"),
            ["矩阵恒等式", "矩阵幂", "多项式降幂"], difficulty="advanced"),

        item("z5b8-math-parameter-system-rank", "math.exam.0aad93648d60", "D",
            "方程组的系数矩阵A(λ)为[[1,1,1],[1,λ,1],[1,1,λ]]。当λ=1时，rank(A)与rank(A|b)对右端b=(1,2,2)^T分别为（ ）。",
            {"A": "3与3", "B": "2与2", "C": "1与1", "D": "1与2"},
            "λ=1时A的三行都为(1,1,1)，故rank(A)=1。增广矩阵中第一行是(1,1,1|1)，第二行是(1,1,1|2)，相减得到(0,0,0|1)，因此增广秩增加为2。由秩判据，方程组不相容。",
            [("coefficient_row_rank", "代λ=1后所有系数行相同且非零，系数秩为1。"),
             ("augmented_row_elimination", "增广行相减产生非零常数行，增广矩阵的秩因此增加为2。")],
            [("equation_consistency", "左端三式相同而右端并非相同，故至少两条独立增广行。"),
             ("rank_criterion", "系数矩阵秩1，增广矩阵秩2，满足不相容判据。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要区分系数矩阵秩和增广矩阵秩，并在奇异参数下实际化简。", "通过矩阵行秩与方程相容性两条路径核验秩差。", "det(A)=0只说明系数矩阵奇异，不能单凭行列式推出无解。", "用增广秩判断参数方程组相容性，而非只计算系数秩。"),
            ["矩阵的秩", "增广矩阵", "方程组相容性"], difficulty="medium"),

        item("z5b8-math-double-integral-order-region", "math.exam.4ea6e9d4fae7", "C",
            "设D={(x,y):0≤x≤1，x≤y≤1}。积分I=∬D(x+2y)dA的值为（ ）。",
            {"A": "1", "B": "3/4", "C": "5/6", "D": "2/3"},
            "按给定次序积分：I=∫₀¹∫ₓ¹(x+2y)dy dx。内积分为x(1−x)+(1−x²)=1+x−2x²，外积分为1+1/2−2/3=5/6。独立换序：区域改写为0≤y≤1、0≤x≤y，I=∫₀¹∫₀ʸ(x+2y)dxdy=∫₀¹(5y²/2)dy=5/6。两种次序一致，对应选项C。",
            [("direct_order_integral", "按0≤x≤1、x≤y≤1积分得∫₀¹(1+x−2x²)dx=5/6。"),
             ("reversed_order_integral", "换序为0≤y≤1、0≤x≤y，积分化为∫₀¹(5y²/2)dy=5/6。")],
            [("region_reversal", "区域是单位正方形中x≤y的上三角，换序后x从0到y。"),
             ("polynomial_moment", "分别积分x与2y的贡献：1/6+2/3=5/6。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需正确描绘三角区域并交换积分次序，同时计算二元多项式积分。", "直接按原次序和交换次序各算一次，独立得到5/6。", "区域边界y=x不能误写成y从0到x；原稿选项键应与精确积分结果一致。", "训练二重积分区域表达、次序交换与结果核对。"),
            ["二重积分", "积分次序", "区域描述"], difficulty="medium"),

        item("z5b8-math-two-variable-quadratic-extremum", "math.exam.e2de677ebe0d", "C",
            "函数f(x,y)=x²+xy+y²−3x−3y的驻点及其类型是（ ）。",
            {"A": "(1,1)为鞍点", "B": "不存在驻点", "C": "(1,1)为唯一严格全局极小点", "D": "(−1,−1)为唯一严格全局极大点"},
            "梯度方程2x+y−3=0、x+2y−3=0相减得x=y，再得x=y=1。Hessian为[[2,1],[1,2]]，特征值1、3均正，函数严格凸，因此该驻点是唯一严格全局极小点。也可写成f=(x−1)²+(x−1)(y−1)+(y−1)²−3，二次型正定且最小值−3在(1,1)取得。",
            [("gradient_and_hessian", "解梯度方程得(1,1)，Hessian特征值1、3为正。"),
             ("positive_definite_completion", "平移至驻点后得到正定二次型加常数−3，直接确认唯一全局最小。")],
            [("linear_system_solution", "两个驻点方程相减给x=y，代回得x=y=1。"),
             ("global_convexity", "Hessian在全平面正定，故函数严格凸且唯一驻点即唯一全局极小。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("题目要求先解驻点方程再判断局部/全局性质。", "通过Hessian正定和中心化配方两种方式验证全局极小。", "只凭一阶导数为零不能判别极值；还需确认二次型正定性。", "连接驻点求解、Hessian判别、严格凸与全局极值。"),
            ["多元函数极值", "Hessian", "严格凸函数"], difficulty="medium"),

        item("z5b8-math-resonant-linear-ode-particular", "math.exam.1d4dc7ab8919", "A",
            "方程y''−3y'+2y=e^x的一个特解为（ ）。",
            {"A": "−xe^x", "B": "xe^x", "C": "e^x", "D": "x²e^x"},
            "齐次特征多项式r²−3r+2=(r−1)(r−2)，右端e^x与根r=1共振。设y_p=Cxe^x。利用L(D)[e^xq]=e^xL(D+1)q，L(D+1)=D(D−1)，对q=Cx有L(D+1)q=−C；令其等于1得C=−1。直接代入也可验证y_p=−xe^x使左端为e^x。",
            [("resonance_trial", "特征根1与e^x共振，试取Cxe^x，代入算子得−Ce^x，故C=−1。"),
             ("direct_operator_substitution", "对y=−xe^x求导并代回y''−3y'+2y，化简为e^x。")],
            [("characteristic_root_multiplicity", "特征根1为单根，故试探因子需乘x一次。"),
             ("residual_check", "将−xe^x代入原算子残差为零，且右端系数为1。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需识别齐次特征根与强迫项共振并确定待定系数符号。", "先用共振试探法求系数，再逐项代回原微分算子复核。", "若忘记乘x则试探项属于齐次解；负号决定输出右端的正系数。", "训练常系数非齐次线性方程的共振特解构造。"),
            ["二阶线性微分方程", "共振特解", "待定系数法"], difficulty="medium"),

        item("z5b8-math-linear-ode-initial-combination", "math.exam.3b91ad45ab4c", "D",
            "二阶常系数齐次方程的两个线性无关解为y₁=e^x、y₂=e^(2x)。满足y(0)=3、y'(0)=4的解中，y(ln2)等于（ ）。",
            {"A": "5", "B": "6", "C": "7", "D": "8"},
            "通解y=c₁e^x+c₂e^(2x)。初值给c₁+c₂=3、c₁+2c₂=4，解得c₁=2、c₂=1。于是y(ln2)=2·2+1·4=8，对应选项D。",
            [("fundamental_solution_coefficients", "由初值线性方程组得c₁=2、c₂=1，代入x=ln2得2×2+1×4=8。"),
             ("basis_evaluation", "分别计算e^(ln2)=2与e^(2ln2)=4，按系数相加。")],
            [("initial_value_linear_system", "y(0)=3、y'(0)=4给c₁+c₂=3、c₁+2c₂=4，因此c₁=2、c₂=1。"),
             ("independent_basis_at_point", "在ln2处基函数值为2和4，合成值2·2+1·4=8。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需由一对初值确定通解基底系数，再在指定对数点计算两个指数基函数。", "解系数方程并分别代入基函数值，两个步骤相互核对。", "不能把通解系数都误读为1；一阶导初值为4而非3用于区分系数。", "运用线性微分方程解空间基底、初值唯一性与函数求值。"),
            ["线性微分方程解结构", "基本解组", "初值条件"], difficulty="medium"),

        item("z5b8-math-taylor-limit-arctan", "math.exam.a24681a8ee59", "B",
            "极限lim(x→0)[arctan x−x+x³/3]/x⁵等于（ ）。",
            {"A": "−1/5", "B": "1/5", "C": "1/7", "D": "−1/7"},
            "在0附近arctan x=x−x³/3+x⁵/5+O(x⁷)，分子为x⁵/5+O(x⁷)，除以x⁵得极限1/5。独立检查：对arctan作五阶Taylor展开，奇次项符号交替，x与x³项恰被消去，首个非零项为正的x⁵/5。",
            [("taylor_series_cancellation", "展开到五阶后低阶项抵消，首项系数为1/5。"),
             ("derivative_coefficient", "五阶Taylor系数为f⁽⁵⁾(0)/5!=24/120=1/5。")],
            [("remainder_order", "余项为O(x⁷)，除以x⁵后趋于0。"),
             ("sign_and_order_check", "反正切幂级数奇次项交替，x⁵项为正且为首个剩余阶。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需控制展开阶数并识别低阶项抵消后的首个非零阶。", "用幂级数系数和五阶导数Taylor系数分别核对。", "展开不足四阶会漏掉目标系数；分母阶为五，余项阶必须更高。", "训练反三角函数展开、阶数选择和极限系数提取。"),
            ["反三角函数", "Taylor展开", "极限"], difficulty="medium"),

        item("z5b8-math-diagonalization-matrix-power", "math.exam.0949f5ff08f9", "C",
            "矩阵A可对角化，特征值1、2的特征子空间分别由P的两列张成，且P⁻¹AP=diag(1,2)。A⁴可表示为（ ）。",
            {"A": "4A−3I", "B": "7A−6I", "C": "15A−14I", "D": "16A−15I"},
            "对特征值1、2，A⁴的对应特征值为1、16。设A⁴=αA+βI，则α+β=1、2α+β=16，解得α=15、β=−14。由对角化A=Pdiag(1,2)P⁻¹可逐特征子空间核验这一线性表达。",
            [("spectral_interpolation", "构造一次多项式r(x)=αx+β匹配r(1)=1⁴、r(2)=2⁴，得15x−14。"),
             ("diagonal_basis_calculation", "在P基底中逐项有diag(1,16)=15diag(1,2)−14I。")],
            [("eigenvalue_action", "A⁴在两特征子空间分别作用为1与16，线性表达亦须取相同值。"),
             ("polynomial_remainder", "模(x−1)(x−2)下x⁴余式15x−14，代入A成立。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需把矩阵幂在特征子空间上的作用转成低次多项式插值。", "通过特征值插值与对角化基底计算两种方式确认表达。", "矩阵幂不是将特征值直接当作矩阵项；需确定作用于整个特征基底的多项式。", "训练对角化、特征值函数与矩阵幂的多项式表示。"),
            ["矩阵对角化", "矩阵幂", "特征值插值"], difficulty="medium"),

        item("z5b8-math-gravity-rod-symmetry-integral", "math.exam.0e5b36de4dd9", "A",
            "均匀细杆沿x轴占据[−a,a]，线密度为λ；质量M位于(0,d)，a,d>0。万有引力常数为G。杆对质点的合力大小为（ ）。",
            {"A": "2GMλa/[d√(a²+d²)]", "B": "GMλ ln[(a²+d²)/d²]", "C": "GMλa/(a²+d²)", "D": "2GMλ/√(a²+d²)"},
            "对称位置x与−x的水平分力相消，竖直分力同向。距离r=√(x²+d²)，微元质量λdx的竖直引力为GMλd dx/(x²+d²)^(3/2)。总力为2GMλd∫₀ᵃdx/(x²+d²)^(3/2)。原函数为x/[d²√(x²+d²)]，故结果2GMλa/[d√(a²+d²)]。",
            [("symmetry_component_integral", "先消去奇对称水平分量，再对竖直分量在0到a积分并乘2。"),
             ("antiderivative_evaluation", "积分原函数x/(d²√(x²+d²))代入a，得到目标式。")],
            [("force_projection", "万有引力大小GMλdx/r²，竖直投影乘d/r得到GMλd dx/r³。"),
             ("dimensional_and_limit_check", "a趋0时力趋0；a趋∞时趋2GMλ/d，均与积分式一致。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需建立连续质量微元引力并利用对称性消去水平分量。", "分别按分量投影积分，再代原函数并以极限行为复核。", "力的竖直投影多一个d/r因子；忘记该因子会把被积幂次写错。", "将定积分物理建模、向量分解和对称积分用于连续质量分布。"),
            ["引力模型", "对称性", "定积分物理应用"], difficulty="advanced"),

        item("z5b8-408-end-to-end-store-forward-delay", "cs408.cn.topic.658f7cffbc1f", "C",
            "长度为12000 B的数据报从主机经一台存储转发路由器到目的主机，两条链路均为2 Mbit/s、传播时延各3 ms。路由器处理时延为1 ms；忽略排队及协议开销。端到端时延为（ ）。",
            {"A": "49 ms", "B": "97 ms", "C": "103 ms", "D": "106 ms"},
            "存储转发需完整接收后再发。数据报为96000 bit，每条链路串行化时延96000/(2×10⁶)=48 ms，两条共96 ms；传播时延6 ms，路由处理1 ms，总计103 ms。",
            [("component_delay_sum", "两次发送48ms、两段传播6ms、一次处理1ms，总计103ms。"),
             ("store_forward_formula", "单路由器存储转发总时延2L/R+2d_prop+d_proc=96+6+1=103ms。")],
            [("bit_length_conversion", "12000B×8=96000bit，除以2Mbit/s得每段48ms。"),
             ("hop_count_accounting", "两链路、两传播段和一个中间处理节点分别计数后求和。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需区分存储转发的逐链路串行化与端到端传播、处理分量。", "按分项计算，并用存储转发公式复核各链路的发送次数。", "不能只计一次数据报传输；存储转发必须在两条链路各发送一次。", "综合链路速率、分组长度、传播和处理时延计算端到端性能。"),
            ["网络性能指标", "存储转发", "端到端时延"], difficulty="medium"),

        item("z5b8-408-tcp-flow-control-send-allowance", "cs408.cn.topic.fdfe51b5d88a", "A",
            "TCP发送方当前拥塞窗口cwnd=20 KiB、接收方通告窗口rwnd=8 KiB，已有5 KiB数据未确认。忽略序号边界和应用限制，当前最多还可发送多少新数据？",
            {"A": "3 KiB", "B": "8 KiB", "C": "15 KiB", "D": "5 KiB"},
            "发送窗口受min(cwnd,rwnd)限制。两者较小为8 KiB，已有5 KiB在途，因此当前可再发送8−5=3 KiB。拥塞窗口和接收窗口是总在途上限，不是额外可用量。",
            [("min_window_available_space", "有效发送窗口为min(20,8)=8KiB，扣除5KiB在途后剩3KiB。"),
             ("flow_and_congestion_constraints", "分别检查网络拥塞约束20KiB和接收缓存约束8KiB，较紧者限制总FlightSize。")],
            [("receiver_window_accounting", "rwnd允许总未确认数据最多8KiB，已占5KiB，剩余3KiB。"),
             ("sender_window_accounting", "cwnd尚有15KiB空间，但受更小rwnd限制，故仍为3KiB。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需把接收窗口、拥塞窗口和当前在途数据分清后求可发送余量。", "先取两个总窗口的较小者，再分别由流量控制与拥塞约束核对。", "rwnd不是还能发送8KiB；已有未确认数据已占用窗口容量。", "联系TCP滑动发送窗口、接收端缓存和网络拥塞控制。"),
            ["TCP流量控制", "接收窗口", "拥塞窗口"], difficulty="medium"),

        item("z5b8-408-tcp-slow-start-rounds", "cs408.cn.topic.940692c0d533", "B",
            "TCP拥塞窗口从cwnd=1 MSS开始，ssthresh=4 MSS。忽略确认压缩和丢包：慢启动中每个新ACK使cwnd增加1 MSS（每轮约翻倍）；进入拥塞避免后每轮合计增加1 MSS。每轮开始若cwnd<ssthresh则为慢启动，否则为拥塞避免。第3轮结束时cwnd为（ ）。",
            {"A": "4 MSS", "B": "5 MSS", "C": "6 MSS", "D": "8 MSS"},
            "第1轮开始cwnd=1<4，收到1个MSS确认量后增至2；第2轮开始2<4，增至4；第3轮开始cwnd=4已达到阈值，按拥塞避免每轮约增加1 MSS，结束为5 MSS。题目把每轮确认量和状态切换规则显式给定。",
            [("round_state_trace", "逐轮为1→2、2→4、4→5 MSS，第三轮处于拥塞避免。"),
             ("threshold_transition", "达到ssthresh后线性增长，本轮只加1MSS而不再倍增。")],
            [("acknowledgment_growth", "慢启动每确认1MSS增加1MSS，整轮增量等于当轮窗口；CA每轮增1MSS。"),
             ("boundary_condition", "cwnd=4已不满足小于ssthresh，故第三轮应用线性阶段。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要按阈值逐轮跟踪拥塞窗口并在到达ssthresh时切换增长模式。", "按ACK增量递推并独立检查每轮起始状态。", "把第三轮仍按慢启动翻倍会得到8，忽视了阈值边界；题目明确定义等于阈值时进入CA。", "用轮次轨迹理解TCP慢启动与拥塞避免的离散状态切换。"),
            ["TCP拥塞控制", "慢启动", "拥塞避免"], difficulty="medium"),

        item("z5b8-408-dns-iterative-resolution", "cs408.cn.topic.7253eabb8454", "A",
            "主机把递归查询交给本地DNS解析器。解析器缓存为空，随后对根服务器、顶级域服务器和权威服务器都使用迭代查询；根与顶级域服务器返回下一级服务器引用，权威服务器返回最终地址。哪项正确描述了该解析过程？",
            {"A": "客户端等待本地解析器完成；解析器依次查询并跟随引用，最终把权威答案返回客户端", "B": "根服务器替解析器递归查询所有下级服务器", "C": "本地解析器只查询根服务器，根服务器直接返回最终主机地址", "D": "权威服务器向客户端主动建立TCP连接推送地址"},
            "客户端向本地解析器提出递归请求，因此由解析器承担完成解析并返回最终结果的责任。题设规定解析器对外采用迭代查询，根返回TLD引用、TLD返回权威服务器引用，解析器逐步跟随后取得权威应答并回复客户端。",
            [("resolver_query_trace", "按根→TLD→权威的引用链逐步查询，最后回到本地解析器。"),
             ("recursion_iteration_roles", "客户端请求递归服务，但解析器对权威层级执行迭代查询，两者并不矛盾。")],
            [("delegation_chain", "每一级只给下一层名称服务器引用，解析器继续发起后续查询。"),
             ("client_resolver_contract", "递归请求意味着本地解析器必须返回最终结果，不要求根服务器递归代劳。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需区分客户端到解析器的递归服务与解析器到权威层级的迭代查询。", "按委派引用链跟踪服务器角色，并核对递归责任主体。", "查询方式由通信双方角色决定；不能把客户端递归请求误解成根服务器代为递归。", "结合DNS委派、递归解析器与迭代查询过程解释缓存未命中。"),
            ["DNS系统", "递归查询", "迭代查询"], difficulty="medium"),

        item("z5b8-408-tdma-fdma-resource-share", "cs408.cn.topic.9a617d7c8ebe", "C",
            "一条总带宽为12 kHz的理想信道服务4个用户。方案甲为FDMA，把频带均分为4个互不重叠子带，每个用户持续占用3 kHz；方案乙为TDMA，用户轮流占用全部12 kHz且每人获得相同的四分之一时隙。在忽略保护带和开销时，单个持续有数据用户在其获配资源期间使用的带宽分别为（ ）。",
            {"A": "甲12 kHz，乙3 kHz", "B": "甲6 kHz，乙12 kHz", "C": "甲3 kHz，乙12 kHz", "D": "甲3 kHz，乙3 kHz"},
            "FDMA按频率划分，用户在整个时间内只拥有总频带的四分之一，即3 kHz。TDMA按时间划分，轮到某用户的时隙时可使用全部12 kHz频带，代价是占空比为1/4。题问的是获配期间的带宽而非长期平均带宽，因此结果为3 kHz和12 kHz。",
            [("frequency_partition", "FDMA把12kHz同时划成4个3kHz子带。"),
             ("time_partition", "TDMA每个用户轮到时独占全部12kHz，平均时间份额另为四分之一。")],
            [("resource_dimension", "FDMA分配频域资源，TDMA分配时域资源，不能把时隙占空比当带宽。"),
             ("per_active_slot_check", "乙在活动时隙瞬时带宽12kHz，甲持续子带带宽3kHz。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需区分频分子带和时分占空比，并明确题目问活动期间资源。", "分别按频域划分和时间轮转定义推导，再检查平均值与瞬时带宽区别。", "若误把TDMA四分之一时隙解释为四分之一带宽，会混淆两个正交资源维度。", "比较信道划分MAC方案中的频率资源与时间资源分配。"),
            ["信道划分", "FDMA", "TDMA"], difficulty="medium"),

        item("z5b8-408-endianness-word-value", "cs408.co.topic.236ea41712f9", "B",
            "四个连续字节地址从低到高依次存放12、34、56、78（均为十六进制），现把它们作为一个32位无符号整数读取。大端与小端机器上读出的数值分别为（ ）。",
            {"A": "0x78563412，0x12345678", "B": "0x12345678，0x78563412", "C": "0x12347856，0x56781234", "D": "两者均为0x12345678"},
            "大端把最高有效字节放在最低地址，因此内存序列12、34、56、78读作0x12345678。小端把最低有效字节放在最低地址，同一地址序列读作0x78563412。字节内部的位序不因端序改变。",
            [("byte_address_significance", "最低地址字节在大端为最高位，在小端为最低位，据此组合32位字。"),
             ("reverse_byte_order_check", "将四字节顺序反转，得到小端读取值0x78563412。")],
            [("memory_layout", "大端从低地址到高地址与通常十六进制书写顺序一致。"),
             ("little_endian_layout", "小端低地址存最低有效字节，故整体字节次序反转而字节内部不反转。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("要把地址顺序、有效字节序和数值书写顺序区分开。", "按大端定义读序，再将字节次序反转核对小端。", "端序影响多字节对象的字节排列，不会把每个字节内部的十六进制数字反转。", "理解同一内存字节序列在不同端序系统中的整数解释。"),
            ["数据对齐与大小端", "字节序", "整数表示"], difficulty="medium"),

        item("z5b8-408-forest-binary-sibling-links", "cs408.ds.topic.1d253ee449a8", "D",
            "森林有两棵树：第一棵根A，孩子依次为C、D；第二棵根B，孩子为E。采用“左孩子—右兄弟”方式转为二叉树。转换后结点A的右孩子和结点C的右孩子分别为（ ）。",
            {"A": "C，D", "B": "D，E", "C": "空，B", "D": "B，D"},
            "左孩子—右兄弟表示中，结点左指针指向第一个孩子，右指针指向下一个兄弟。森林中各树根按兄弟关系连接，因此A的右指针指向下一棵树根B；A的第一个孩子为C，C的右指针指向其兄弟D。故答案为B、D。",
            [("first_child_next_sibling_mapping", "A的第一个孩子C放左链；同层下一根B放A的右兄弟链。"),
             ("sibling_chain", "C与D为A的同级孩子，C右指针指向下一兄弟D。")],
            [("forest_root_sibling_rule", "森林各树根视为兄弟，因此二叉表示中A.right=B。"),
             ("child_sibling_rule", "第一棵树的孩子按序形成右兄弟链C.right=D。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需区分原森林的父子关系与转换后二叉树的左右指针语义。", "按首孩子映左链、后续兄弟映右链分别追踪两个目标。", "原森林中B不是A的孩子，而是下一棵树根；但二叉表示中会成为A的右兄弟链接。", "训练森林与二叉树互转时的兄弟链表示和根节点连接。"),
            ["森林与二叉树转换", "左孩子右兄弟", "树结构"], difficulty="medium"),

        item("z5b8-408-propagation-transmission-delay", "cs408.cn.topic.1a141eb77fc0", "B",
            "1500 B数据帧经长1200 km的单条链路发送，链路速率100 Mbit/s，信号传播速度2×10⁸ m/s。忽略处理及排队时延，从发送端开始发送首比特到接收端收到末比特的时间约为（ ）。",
            {"A": "0.12 ms", "B": "6.12 ms", "C": "6.00 ms", "D": "12.00 ms"},
            "帧长为12000 bit，发送时延为12000/(100×10⁶)=0.00012 s=0.12 ms。传播时延为1200 km/(2×10⁸ m/s)=0.006 s=6 ms。末比特到达时间包含整帧串行化与传播，共6.12 ms；首比特则约6 ms到达。",
            [("serialization_plus_propagation", "先算末比特离开发送端的0.12ms，再加全链路传播6ms。"),
             ("physical_rate_distance_formula", "12000bit/100Mbit/s加1.2×10⁶m/(2×10⁸m/s)，仍为6.12ms。")],
            [("bit_and_distance_units", "1500B转成12000bit，1200km转成1.2×10⁶m后代入速率。"),
             ("first_last_bit_distinction", "首比特不等整帧发送完才传播；末比特需额外经历帧发送时延。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要将帧串行化时延与介质传播时延分开计算后相加。", "用发送时间和距离/传播速度两种分项方法核对总时延。", "传播速度与链路速率是不同物理量；题目问末比特，不能只报传播时延。", "比较高带宽长距离链路中的传输时延与传播时延占比。"),
            ["传输介质", "传播时延", "发送时延"], difficulty="medium"),

        item("z5b8-408-stop-wait-duplicate-frame", "cs408.cn.topic.d702790fde46", "C",
            "停等可靠传输协议采用交替位序号0、1。发送方发出序号0的数据帧，接收方正确收到并交付一次后发回ACK1，但该确认丢失。发送方超时后重传序号0帧，接收方应（ ）。",
            {"A": "再次把数据交付上层并回ACK0", "B": "将该帧视为新帧并把接收序号重置为0", "C": "识别为重复帧，不重复交付，并重发ACK1", "D": "丢弃该帧且不发送任何确认"},
            "接收方首次收到序号0后已交付数据，并把下一期待序号改为1。ACK1丢失后，重传帧序号仍为0，与当前期待值不符，故判为旧重复帧；接收方丢弃其数据副本但重发ACK1，以帮助发送方解除等待。",
            [("alternating_bit_state_trace", "首次接收0后状态切换为期待1；超时重发0与期待值不同，判为重复。"),
             ("acknowledgment_recovery", "重复帧不再交付，但重发当前正确确认ACK1让发送方恢复同步。")],
            [("delivery_invariant", "同一序号数据只在首次正确接收时交付一次，重复副本不得重复上交。"),
             ("sender_receiver_state", "发送方未收到ACK仍重发0；接收方当前期待1，因此应重复确认1。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需追踪发送、确认丢失、超时重传以及接收方期待序号状态。", "按交付次数不变量和交替位状态机两条路径判断处理结果。", "确认丢失不意味着数据未交付；接收方必须抑制重复交付但仍重发确认。", "理解停等协议中序号、超时重传和重复帧去重的可靠性机制。"),
            ["可靠传输", "停等协议", "交替位"], difficulty="medium"),

        item("z5b8-408-threaded-tree-inorder-links", "cs408.ds.topic.36d6505de0b4", "A",
            "二叉树根D的左、右孩子分别为B、F；B的左右孩子为A、C；F的左右孩子为E、G。采用双向中序线索，结点C没有真实左、右孩子。C的左线索（前驱）与右线索（后继）分别指向（ ）。",
            {"A": "B，D", "B": "A，F", "C": "B，F", "D": "D，E"},
            "按左根右得到中序序列A、B、C、D、E、F、G。C没有真实左右孩子，因此其左线索指向中序前驱B，右线索指向中序后继D。",
            [("inorder_traversal", "按左右子树递归列出A、B、C、D、E、F、G，C相邻结点为B与D。"),
             ("thread_pointer_semantics", "无左孩子时左线索指前驱，无右孩子时右线索指后继。")],
            [("tree_structure_walk", "B的右孩子C先于根D访问，故前驱B；根D随后访问，故后继D。"),
             ("threading_rule", "题设明确C无真实孩子，双向线索分别补其空指针到相邻中序结点。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需先恢复中序序列，再根据线索定义定位指定叶结点前驱后继。", "由递归遍历和相邻结点规则两种方式核对C的线索。", "线索仅替换空指针，不覆盖真实孩子；题设已明确C的两个孩子指针均为空。", "训练线索二叉树将空指针转为中序遍历导航信息的机制。"),
            ["线索二叉树", "中序前驱", "中序后继"], difficulty="medium"),
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
                report = run_batch(db, candidate_specs=candidates(), batch_id="08")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH08_APPLIED"
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
