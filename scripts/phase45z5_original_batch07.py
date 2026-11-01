"""Seventh offline-authored public-original batch for the isolated Z5 database."""
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

BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch06-revised/post-batch06.dump"
BACKUP_SHA256 = "69C6396954F799E4B638AEAC60F39F0733EE2808420CEF966263D0508875519E"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch07-revised"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"


def candidates():
    return [
        item("z5b7-math-energy-reduction", "math.exam.66f8f7b61188", "B",
            "函数y(x)在包含0的区间上满足y''=y、y(0)=0、y'(0)=1且y'>0。利用降阶关系，y达到2时y'等于（ ）。",
            {"A": "2", "B": "√5", "C": "3", "D": "5"},
            "令p=y'并把p看作y的函数，则y''=p·dp/dy=y。于是p dp=y dy，积分并用y=0时p=1，得p²=y²+1。因题设p>0，y=2时p=√5。独立核对：初值解为y=sinh x、y'=cosh x，恒等式cosh²x−sinh²x=1给出同一结果。",
            [("reduction_of_order_first_integral", "以p(y)=y'代换后积分p dp=y dy，初值确定常数，得到p²=y²+1并选正支。"),
             ("explicit_solution_cross_check", "初值解y=sinh x、p=cosh x满足p²−y²=1；当y=2且p为正时p=√5。")],
            [("energy_identity", "由p dp/dy=y积分得p²/2=y²/2+1/2，故y=2时p²=5。"),
             ("initial_value_solution", "sinh x满足方程和两初值；cosh x为正且对应y=2时平方为5。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要把二阶自主方程按y'降阶，并由初值确定第一积分常数。", "先用p dp/dy=y积分，再用显式初值解sinh x独立复核正支。", "链式变换须含p因子；由p²=5还要依据题给y'>0选择正根。", "把自主方程降阶、初值信息和能量型第一积分用于反求斜率。"),
            ["二阶方程降阶", "自主方程", "初值第一积分"], difficulty="advanced"),

        item("z5b7-math-convex-secant-monotonicity", "math.exam.423bee85b09f", "C",
            "函数f在[a,b]上二阶可导且f''(x)>0。对x∈(a,b]定义g(x)=[f(x)−f(a)]/(x−a)。下列结论正确的是（ ）。",
            {"A": "g'(x)<0，因为凸函数图像位于切线下方", "B": "g'(x)=0，因为割线斜率固定", "C": "g'(x)>0，因为f'(x)大于区间[a,x]上的平均导数", "D": "仅能推出g连续，不能判断单调性"},
            "由微积分基本定理，f(x)−f(a)=∫ₐˣf'(t)dt。严格凸性使f'严格递增，因此当x>a时，区间平均值(1/(x−a))∫ₐˣf'(t)dt严格小于端点值f'(x)。求导得g'(x)=[(x−a)f'(x)−(f(x)−f(a))]/(x−a)²>0，故割线斜率随右端点严格增加。",
            [("integral_average_derivation", "把函数增量写成导数积分；严格递增的f'在区间内部小于其右端点值，故平均导数小于f'(x)。"),
             ("quotient_derivative_sign", "商求导分子为(x−a)乘端点导数减函数增量，按上式严格为正，分母平方为正。")],
            [("mean_value_theorem_check", "中值定理给g(x)=f'(ξ)且ξ∈(a,x)；严格递增的f'使g(x)<f'(x)，等价于g'(x)>0。"),
             ("convexity_slope_order", "严格凸函数相邻区间割线斜率递增，亦由导数单调和区间平均值直接验证。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需连接二阶导数正、导数严格递增、割线斜率和商函数导数符号。", "用导数积分的区间平均值推导，并以中值定理解释斜率位置。", "凸函数位于端点切线的关系容易混淆；分母平方为正而关键在分子严格正。", "将凸性几何直觉转成可复用的割线斜率单调证明。"),
            ["凸函数", "割线斜率", "导数平均值"], difficulty="advanced"),

        item("z5b7-math-log-rational-inequality", "math.exam.68217a446e4c", "A",
            "对x>0，比较ln(1+x)与2x/(2+x)。令h(x)=ln(1+x)−2x/(2+x)，则h(x)的符号为（ ）。",
            {"A": "恒正", "B": "恒负", "C": "先负后正且恰有一个正零点", "D": "除x=1外恒为零"},
            "先有h(0)=0。求导得h'(x)=1/(1+x)−4/(2+x)²=[(x+2)²−4(x+1)]/[(x+1)(x+2)²]=x²/[(x+1)(x+2)²]>0。故h从0开始严格递增，任意x>0均有h(x)>0。数值代入x=1得到ln2−2/3>0可作方向检查，但结论由导数证明。",
            [("derivative_difference_factorization", "通分后导数分子化为x²，分母在x>0为正，故h严格递增。"),
             ("boundary_and_monotonicity", "连续延拓h(0)=0，结合严格递增性推出所有正x上h(x)>0。")],
            [("monotonicity_proof", "直接求导与因式分解得到h'(x)=x²/((x+1)(x+2)²)>0。"),
             ("integral_representation", "h(x)=∫₀ˣ t²/((t+1)(t+2)²)dt，正区间积分严格大于0。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要比较对数与有理函数并将导数差通分因式分解。", "从边界值和严格单调性证明，再用导数积分形式交叉核验。", "单独比较两者在无穷远的增长无法排除中间变号；须证明全区间导数符号。", "把不等式证明转化为辅助函数单调性并识别严格性。"),
            ["不等式证明", "辅助函数", "单调性"], difficulty="medium"),

        item("z5b7-math-implicit-sphere-directional-second", "math.exam.84058ab2e9bb", "D",
            "方程x²+y²+z²=3在点(1,1,1)附近确定正值函数z=z(x,y)。令φ(t)=z(1+t,1+t)，则φ''(0)等于（ ）。",
            {"A": "−2", "B": "−4", "C": "−8", "D": "−6"},
            "由显式支z=√[3−(1+t)²−(1+t)²]=√(1−4t−2t²)，求导得φ'(0)=−2，二次求导得φ''(0)=−6。隐式复核：z²+2(1+t)²=3，一阶得2zz'+4(1+t)=0；二阶得2(z'²+zz'')+4=0。在t=0,z=1,z'=-2，故2(4+z'')+4=0，z''=-6。",
            [("explicit_branch_differentiation", "取题设正支后对√(1−4t−2t²)连续求导两次，代t=0得−6。"),
             ("implicit_second_derivative", "对z²+2(1+t)²=3隐式求导两次，代入z(0)=1和z'(0)=−2得−6。")],
            [("local_domain_and_branch", "根号内在t=0为1且z取正支，故局部光滑，显式二阶导数存在。"),
             ("chain_rule_terms", "二阶式含2(z')²与2zz''两项，代入后得8+2z''+4=0。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("要沿指定直线组合两个隐函数偏导并保留曲线二阶项。", "先对显式正支求导，再从原隐式方程独立求二阶导数复核。", "把方向二阶导误当单个偏导二阶导会漏掉混合项；二阶链式中还含z'平方项。", "综合隐函数定理、方向路径和二阶链式法则处理曲面局部曲率。"),
            ["隐函数偏导", "方向二阶导", "二元曲面"], difficulty="advanced"),

        item("z5b7-math-adjugate-scaled-inverse-determinant", "math.exam.8b6ba0b9a789", "C",
            "A为可逆3阶矩阵且det(A)=2。矩阵B=3A⁻¹，则det(adj(B))等于（ ）。",
            {"A": "81/4", "B": "729/8", "C": "729/4", "D": "729/2"},
            "对3阶矩阵B，det(adj B)=(det B)²。又det B=det(3A⁻¹)=3³/det A=27/2，因此det(adj B)=(27/2)²=729/4。复核也可先用adj(B)=det(B)B⁻¹逐因子取行列式，得到det(adj B)=det(B)^3 det(B⁻¹)=det(B)^2。",
            [("determinant_scaling_and_adjugate", "det(3A⁻¹)=27/2，3阶伴随矩阵行列式为其平方，得729/4。"),
             ("adjugate_identity", "由adj(B)=det(B)B⁻¹对行列式取值，得到det(adj B)=det(B)²。")],
            [("inverse_determinant", "det(A⁻¹)=1/2，三阶数乘贡献3³，故det B=27/2。"),
             ("dimension_exponent", "一般n阶有det(adj B)=det(B)^(n−1)，n=3时平方。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需联合使用数乘、逆矩阵和伴随矩阵的行列式幂次。", "先算B的行列式再用伴随恒等式，并从定义恒等式二次核验。", "三阶数乘因子为3³而非3；det(adj B)是det B平方而非立方。", "训练矩阵尺度变换与伴随矩阵恒等式在复合表达式中的顺序。"),
            ["伴随矩阵", "逆矩阵", "行列式数乘"], difficulty="medium"),

        item("z5b7-math-separable-ode-maximal-interval", "math.exam.b05d65f2b0c1", "B",
            "初值问题y'=x(1+y²)、y(0)=0的解在含0的最大实区间上存在。该区间为（ ）。",
            {"A": "(−π/2,π/2)", "B": "(−√π,√π)", "C": "(−π,π)", "D": "全实数"},
            "分离变量得dy/(1+y²)=x dx，积分并用初值可得arctan y=x²/2，故y=tan(x²/2)。实值有限解要求−π/2<x²/2<π/2，即|x|<√π。到任一端点时tan的自变量趋于π/2，解发散，不能延拓为有限实解，故最大区间为(−√π,√π)。",
            [("separation_and_inverse", "分离积分得到arctan y=x²/2，反解为tan(x²/2)。"),
             ("blowup_endpoint_analysis", "正切首次极点满足x²/2=π/2，即|x|=√π，端点发散且不能延拓。")],
            [("direct_differential_check", "对y=tan(x²/2)求导得y'=x sec²(x²/2)=x(1+y²)。"),
             ("maximality", "解的两个最近实极点位于±√π，含0连通区间不能越过极点。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("除了分离变量还要由反函数奇点确定最大解区间。", "积分反解后用原微分方程代回，并分析最近的正切极点。", "初值只给局部解；不能把显式公式误当作全实轴有限解。", "把可分离方程求解与有限时爆破解区间联系起来。"),
            ["可分离变量方程", "初值问题", "最大存在区间"], difficulty="advanced"),

        item("z5b7-math-distance-from-velocity", "math.exam.ceb4bcf4246a", "A",
            "质点在0≤t≤3上的速度为v(t)=t²−2t，初始位置不影响所求。该时间段内质点经过的路程为（ ）。",
            {"A": "8/3", "B": "0", "C": "4/3", "D": "3"},
            "速度在t=0与t=2变号。位移是∫₀³v(t)dt=0，但路程为∫₀³|v(t)|dt。原函数F=t³/3−t²，0到2的位移为−4/3，故该段路程4/3；2到3的位移为4/3，故总路程8/3。",
            [("sign_partition_absolute_integral", "按速度零点t=2拆分绝对值积分，两段路程分别为4/3和4/3。"),
             ("antiderivative_and_displacement", "原函数给总位移0及分段位移−4/3、4/3，取绝对值相加得8/3。")],
            [("velocity_sign_analysis", "v=t(t−2)，在(0,2)为负、(2,3)为正，路程必须分段取绝对值。"),
             ("unit_interval_check", "每段积分精确为4/3，合计8/3；不等于有符号位移0。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需根据速度零点分段并区分有符号位移与路程。", "先分析符号再求原函数，并与总位移交叉核验。", "直接积分速度会抵消正负段而得到位移，不能当成路程。", "将定积分物理意义、速度符号与绝对值积分结合。"),
            ["变速直线运动", "速度与路程", "绝对值定积分"], difficulty="medium"),

        item("z5b7-math-curvature-radius-parabola", "math.exam.f67ee0d0080c", "D",
            "平面曲线y=x²在点(1,1)处的曲率半径为（ ）。",
            {"A": "5/2", "B": "5√5", "C": "√5/2", "D": "5√5/2"},
            "显函数曲率κ=|y''|/(1+(y')²)^(3/2)。在x=1处y'=2、y''=2，故κ=2/5^(3/2)，曲率半径ρ=1/κ=5^(3/2)/2=5√5/2。独立核对：曲率圆半径公式直接取导数值，且曲率半径应为正，量级约5.59。",
            [("curvature_formula", "把y'=2、y''=2代入κ=|y''|/(1+y'²)^(3/2)，再取倒数。"),
             ("radius_inverse_curvature", "ρ=(1+4)^(3/2)/2=5√5/2，正值约5.59。")],
            [("derivative_values", "曲线一阶导数2x、二阶导数2，在x=1分别为2和2。"),
             ("formula_dimension_check", "分母为速度斜率因子(1+4)^(3/2)，曲率半径为其三次幂除以|y''|。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要区分曲率与曲率半径并正确使用斜率的三次幂因子。", "代入微分几何公式后求倒数，再用数值量级检查。", "把κ直接当ρ或漏掉绝对值、三次幂均会造成量纲或数值错误。", "在具体曲线中综合一阶、二阶导数解释曲线弯曲尺度。"),
            ["曲率", "曲率半径", "显函数微分几何"], difficulty="medium"),

        item("z5b7-math-hessian-flat-nonstrict-minimum", "math.exam.58a5d04a7be9", "C",
            "函数f(x,y)=(x²−y²)²在原点的Hessian矩阵为零矩阵。原点的局部极值类型为（ ）。",
            {"A": "严格局部极小", "B": "严格局部极大", "C": "非严格局部极小", "D": "鞍点"},
            "对任意(x,y)，f=(x²−y²)²≥0=f(0,0)，因此原点是局部且实际上全局非严格极小点。沿直线y=x（或y=−x），函数恒为0，任意原点邻域内存在不同于原点的点取到相同函数值，故不是严格极小。Hessian为零只说明二阶判别法不定，需回到函数值定义。",
            [("global_square_nonnegativity", "函数是平方，处处非负且原点取0，直接证明非严格全局极小。"),
             ("equality_curve_strictness_test", "沿y=x的非零点函数仍为0，排除严格极小。")],
            [("hessian_degeneracy", "原点处所有二阶偏导为0，Hessian判别法不能给出严格性。"),
             ("definition_based_classification", "函数值不低于原点且任意邻域有其他等值点，符合非严格极小定义。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需处理退化Hessian并回到函数定义检查符号与等值集。", "以平方非负性证明极小，再沿零曲线判定其非严格。", "Hessian为零不等于鞍点，也不能推出严格极值；需检查高阶项与等值方向。", "训练二元函数退化驻点分类及严格/非严格极值区分。"),
            ["Hessian判别", "退化驻点", "非严格极值"], difficulty="medium"),

        item("z5b7-math-parameter-linear-system-solvability", "math.exam.36050d277510", "B",
            "线性方程组系数矩阵A的三行为(1,1,1)、(1,λ,1)、(1,1,λ)，右端为(1,2,2)^T。关于λ，正确结论是（ ）。",
            {"A": "λ=1时唯一解，λ≠1时无解", "B": "λ≠1时唯一解；λ=1时无解", "C": "任意λ均有无穷多解", "D": "λ=1时有无穷多解，λ≠1时唯一解"},
            "行列式按第一行展开为detA=λ²−2λ+1=(λ−1)²。λ≠1时A可逆，方程组唯一可解。λ=1时三行左端相同，第一式要求x+y+z=1，而第二、三式要求x+y+z=2，矛盾，故无解。",
            [("determinant_singularity_split", "直接计算detA=(λ−1)²，区分非奇异唯一解与λ=1奇异情形。"),
             ("row_consistency_at_singular_value", "代λ=1后比较相同系数行的右端1与2，证明增广方程不相容。")],
            [("coefficient_rank", "λ≠1时行列式非零；λ=1时系数行相同，系数秩为1。"),
             ("augmented_rank", "λ=1时增广矩阵至少有不同右端，秩大于系数秩，因此无解。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要先求参数行列式零点，再单独检验奇异点的增广相容性。", "用行列式判断一般参数，并用行秩与增广秩交叉核验特殊值。", "行列式为零不能直接断言无解或无穷多解；必须检查右端相容性。", "训练含参数线性方程组中奇异参数与解的存在唯一性分类。"),
            ["矩阵方程组", "行列式参数", "相容性"], difficulty="advanced"),

        item("z5b7-408-bit-stuffing-length", "cs408.cn.topic.7507d0c4e02a", "A",
            "采用比特填充的面向比特帧以01111110为首尾标志。数据字段为1111101111110，填充规则是在数据中每连续出现5个1后插入1个0。忽略首尾标志，实际发送的数据字段长度为（ ）。",
            {"A": "15 bit", "B": "14 bit", "C": "16 bit", "D": "13 bit"},
            "原字段分为5个1、0、6个1、0，共13 bit。第一个五连1后插入0；第二段六连1在前五个1后再插入0，剩余第六个1不触发另一次填充。因此共插入2 bit，发送字段长度15 bit。标志字段自身不参与数据字段的填充计数。",
            [("run_length_scan", "逐段数连续1：长度5与长度6各触发一次插入，合计2个填充0。"),
             ("transmitted_length_accounting", "原数据13 bit加两次填充为15 bit；边界标志另计。")],
            [("bit_stuffing_state_machine", "状态计数器到五个连续1即输出数据0并清零，再继续读第六个1。"),
             ("frame_boundary_rule", "题目给定的数据字段内部共插入2个0，帧首尾标志不计入所问长度。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("必须逐段跟踪连续1计数并区分数据字段和帧标志。", "用运行长度扫描和填充状态机逐位计数，并检查字段边界。", "六连1只在前五个1后插入一次0；填充后仍需正确处理第六个1。", "把链路层透明传输与比特填充状态机应用到具体帧数据。"),
            ["数据链路层", "比特填充", "帧定界"], difficulty="medium"),

        item("z5b7-408-vlan-broadcast-scope", "cs408.cn.topic.560367fe85a6", "C",
            "交换机S1与S2由一条802.1Q中继链路连接。两交换机均有VLAN 10和VLAN 20接入口，中继允许这两个VLAN。主机H1从S1的VLAN 10端口发送广播，交换表无相关单播项。下列转发范围正确的是（ ）。",
            {"A": "S1把广播复制到本机所有接入口，S2再复制到所有接入口", "B": "广播只留在S1，VLAN广播不能通过中继链路", "C": "S1在本地VLAN 10端口及中继上转发，S2仅向VLAN 10接入口泛洪", "D": "S1把广播改成单播后仅发给VLAN 20端口"},
            "二层广播泛洪限制在入端口所属VLAN。S1将帧复制到其他VLAN 10接入口及承载VLAN 10的中继；中继帧携带VLAN标记。S2收到后仍按VLAN 10处理，仅向本地VLAN 10接入口泛洪，不会泄漏到VLAN 20。",
            [("vlan_scoped_flooding", "交换机只在入端口所在广播域内泛洪，排除同机VLAN 20端口。"),
             ("trunk_tag_preservation", "允许VLAN 10的中继携带标识，另一端据标签仍限制在VLAN 10。")],
            [("broadcast_domain_definition", "VLAN 10与VLAN 20是不同广播域，二层广播不会跨VLAN传播。"),
             ("port_by_port_trace", "S1输出本地同VLAN口和中继；S2只输出其同VLAN接入口。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需沿两台交换机逐跳跟踪广播域和中继允许列表。", "分别按VLAN广播域定义和端口转发表过程核对输出集合。", "中继不是三层路由；它传递带标签的VLAN帧，但不合并各VLAN广播域。", "在多交换机场景中理解802.1Q VLAN隔离和广播泛洪边界。"),
            ["VLAN", "802.1Q中继", "广播域"], difficulty="medium"),

        item("z5b7-408-wireless-dcf-freeze-resume", "cs408.cn.topic.1351211c91cf", "D",
            "IEEE 802.11 DCF中，A、B均在空闲DIFS后开始退避，时隙计数分别为2和5。A先到0并占用信道发送数据，B在信道忙时冻结计数；A随后收到ACK，信道再次空闲并满足DIFS后，无其他站点竞争。B恢复退避时还需等待多少个时隙才可发送？",
            {"A": "0", "B": "2", "C": "5", "D": "3"},
            "在A开始发送前，A和B的退避计数均同步递减2个空闲时隙。A计数归零发送，B的剩余计数为5−2=3。信道忙时B冻结计数，收到ACK并再次经过DIFS后继续从3递减，故还需3个时隙。",
            [("backoff_countdown_trace", "共同空闲阶段消耗2个时隙，B由5降到3后因信道忙冻结。"),
             ("medium_idle_resume_rule", "ACK后重新等待DIFS，随后B从剩余计数3继续退避。")],
            [("station_state_machine", "DCF计数只在介质空闲时递减，介质忙时保持剩余值不变。"),
             ("arithmetic_cross_check", "B初值5减去A获胜前共享的2个空闲时隙，剩余3。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要把退避计数、介质忙冻结和ACK后的DIFS恢复连成状态过程。", "逐时隙跟踪站点计数，并用DCF空闲/忙状态机核对。", "B不是在A发送期间继续倒数；信道忙期间冻结而非清零。", "训练无线局域网竞争接入中退避计数的并发状态演化。"),
            ["无线局域网", "DCF", "退避冻结"], difficulty="medium"),

        item("z5b7-408-nyquist-shannon-minimum-bound", "cs408.cn.topic.1e611d5e4eb0", "B",
            "带宽B=3 kHz的带通信道采用4电平信号，接收信噪比S/N=15（线性值）。按理想Nyquist与Shannon上界分别计算，两者共同允许的最大数据率为（ ）。",
            {"A": "6 kbit/s", "B": "12 kbit/s", "C": "24 kbit/s", "D": "48 kbit/s"},
            "Nyquist上界为2B log₂M=2×3000×log₂4=12000 bit/s。Shannon容量为B log₂(1+S/N)=3000×log₂16=12000 bit/s。实际数据率不能超过任何一个上界，因此共同上限为二者较小值12 kbit/s。",
            [("nyquist_symbol_level_bound", "4电平每符号携带2 bit，最高2B log₂M=12 kbit/s。"),
             ("shannon_noise_capacity", "线性信噪比15使1+S/N=16，容量B log₂16=12 kbit/s。")],
            [("formula_units_check", "Hz乘bit/s/Hz得到bit/s，两条上界均为12000 bit/s。"),
             ("joint_constraint", "受Nyquist和Shannon同时约束，取较小上界，结果仍为12 kbit/s。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("要分别应用多电平码元率和含噪信道容量公式再合并约束。", "独立算出Nyquist与Shannon上界，并检查单位与SNR线性值。", "S/N=15已是线性值而非dB；两条上界都必须满足，不能取较大值。", "比较调制级数、带宽与噪声对可达数据率的双重限制。"),
            ["编码与调制", "Nyquist准则", "Shannon容量"], difficulty="medium"),

        item("z5b7-408-selective-repeat-window-trace", "cs408.cn.topic.6e5dd5812d0e", "C",
            "选择重传ARQ使用3 bit序号，发送窗口和接收窗口大小均为4。初始接收窗口为{0,1,2,3}，成功按序交付这4帧后窗口滑到{4,5,6,7}。此时迟到的旧帧0到达，接收方应（ ）。",
            {"A": "把旧帧0作为新数据交付，因为序号可循环使用", "B": "清空接收窗口并重置序号", "C": "将帧0识别为窗口外旧重复帧并丢弃，不重复交付", "D": "把帧0改标为序号8后交付"},
            "3 bit序号模8循环。窗口从{0,1,2,3}滑到{4,5,6,7}后，序号0不属于当前接收窗口，因此迟到帧0是旧重复帧，应丢弃且不再次交付。窗口大小4不超过序号空间一半，保证新旧窗口不重叠，避免把旧0误判为下一轮新0。",
            [("modular_window_membership", "当前窗口为4、5、6、7，模8序号0不在窗口内，故丢弃。"),
             ("half_space_ambiguity_bound", "3 bit序号空间为8，SR窗口最大4；新旧窗口边界不重叠。")],
            [("receiver_window_state", "按已交付4帧更新接收窗口，当前期待4到7。"),
             ("duplicate_suppression", "窗口外旧帧即便序号与未来轮次相同，也不能在当前状态下重新交付。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要跟踪模序号窗口滑动并处理迟到重复帧。", "用当前窗口成员判定，再用SR半序号空间约束解释无歧义性。", "序号循环不意味着每个旧帧都可当新帧；接收状态和窗口位置决定语义。", "把选择重传缓冲、模序号和旧重复抑制放到同一轨迹中判断。"),
            ["选择重传", "滑动窗口", "序号回绕"], difficulty="advanced"),

        item("z5b7-408-gbn-loss-retransmission-count", "cs408.cn.topic.ab43d1fb00a1", "A",
            "后退N帧协议使用3 bit序号，发送窗口允许发送序号0至4。接收方期望0；发送中帧2丢失，帧0、1、3、4均到达。忽略确认丢失，帧2超时后发送方必须重传哪些帧？",
            {"A": "2、3、4，共3帧", "B": "仅2，共1帧", "C": "0至4，共5帧", "D": "3、4，共2帧"},
            "后退N帧接收方只按序接收。帧0、1交付后期待2；帧2丢失使期待序号保持2，随后到达的3、4被丢弃并重复确认当前期待值。发送方收到累计确认后仍需等待2超时，按GBN回退并从2重传所有未获确认帧2、3、4，共3帧。",
            [("receiver_expected_sequence_trace", "帧2缺失后接收方仍期待2，帧3和4不缓存而被丢弃。"),
             ("sender_go_back_n_timeout", "超时后从最早未确认帧2开始重传窗口中未确认的2、3、4。")],
            [("cumulative_ack_state", "累计确认只确认连续前缀0、1，不能越过丢失的2确认3、4。"),
             ("retransmission_set", "GBN回退集合为所有未确认帧，恰为2至4。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("题目要求同时跟踪接收方累计确认和发送方超时回退窗口。", "按接收期望序号推演，再按GBN未确认帧集合计算重发量。", "GBN不像SR缓存乱序帧；选择重传仅重发丢失帧的结论不适用。", "比较累计确认、乱序丢弃与后退N帧重传机制的状态语义。"),
            ["后退N帧", "累计确认", "超时重传"], difficulty="medium"),

        item("z5b7-408-ipv4-fragment-offsets", "cs408.cn.topic.7dfe285bb24b", "D",
            "IPv4数据报总长度4000 B（含20 B首部），经MTU=1500 B链路转发；无选项，允许分片。第二片的片偏移字段（以8 B为单位）和最后一片总长度分别为（ ）。",
            {"A": "185，1020 B", "B": "180，1040 B", "C": "370，1040 B", "D": "185，1040 B"},
            "原数据净荷为4000−20=3980 B。每个非末片最多装1500−20=1480 B净荷且1480可被8整除。第二片起始净荷字节偏移1480，因此片偏移为1480/8=185。前两片各装1480 B，剩余净荷3980−2960=1020 B；最后一片总长度为1020+20=1040 B。",
            [("mtu_payload_partition", "每个满片净荷1480 B，剩余1020 B，末片总长1040 B。"),
             ("fragment_offset_units", "第二片起始字节偏移1480除以8，字段值为185。")],
            [("byte_conservation", "三片净荷1480+1480+1020=3980 B，首部各20 B。"),
             ("offset_alignment", "前片净荷满足8字节对齐，第二片偏移以8 B单位编码为185。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需同时处理原始首部、MTU净荷上限、8字节片偏移和末片长度。", "按净荷分块计算，再用字节守恒和偏移单位独立复核。", "偏移字段不是字节数；总长度包含首部，末片不要求净荷为8的倍数。", "在IPv4分片中综合MTU约束、片偏移编码与重组位置。"),
            ["IPv4分片", "MTU", "片偏移"], difficulty="advanced"),

        item("z5b7-408-dijkstra-route-choice", "cs408.cn.topic.a2e54e0115b9", "B",
            "无向带权网络仅含边AB=4、AC=1、BC=2、BD=1、CD=5、CE=8、DE=3，边权均为正。以A为源运行Dijkstra算法，到D的最短距离及其前驱结点为（ ）。",
            {"A": "5，前驱为B", "B": "4，前驱为B", "C": "6，前驱为C", "D": "4，前驱为C"},
            "从A出发初始距离B=4、C=1。确定C后，经C更新B为1+2=3（优于4），D为1+5=6。随后确定B的距离3，经B更新D为3+1=4。经E的路径至少更长，故D的最短距离为4，最短路径A−C−B−D的前驱是B。",
            [("dijkstra_relaxation_trace", "依次确定C=1、B=3，再经B松弛D到4。"),
             ("alternative_path_bound", "A−B−D为5、A−C−D为6；正权边与E路径不可能小于4。")],
            [("priority_queue_state", "松弛后候选B=3小于直达4，随后D从6更新为4。"),
             ("path_reconstruction", "前驱链D←B←C←A，路径权重1+2+1=4。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需按Dijkstra逐次选择当前最小未确定点并执行松弛。", "完整列出距离更新，再由前驱链与候选替代路径核验。", "不能先锁定直达B=4；经C的较短路会先更新B，再影响D。", "训练正权图最短路的贪心确定顺序、松弛和路径恢复。"),
            ["Dijkstra算法", "最短路径", "边松弛"], difficulty="medium"),

        item("z5b7-408-arp-next-hop-resolution", "cs408.cn.topic.71ab052ca21b", "C",
            "主机H的IPv4地址为192.168.10.20/24，默认网关为192.168.10.1，ARP缓存为空。H要向同网段外的8.8.8.8发送首个IPv4数据报；忽略代理ARP。第一帧以太网帧的目的MAC应解析为（ ）。",
            {"A": "8.8.8.8对应主机的MAC", "B": "广播MAC，数据帧也直接交给广播域", "C": "默认网关192.168.10.1接口的MAC", "D": "DNS服务器的MAC"},
            "H先用子网掩码判断8.8.8.8不在本地/24网段，因此IP数据报的下一跳是默认网关。以太网只需把当前一跳交付给网关，故通过ARP解析192.168.10.1的MAC，而不是远端目标的MAC。ARP请求本身使用广播帧，收到应答后承载IP数据报的单播帧目的MAC为网关MAC。",
            [("subnet_and_next_hop", "按/24网络前缀比较确定目的地址异网，路由下一跳为默认网关。"),
             ("arp_target_selection", "ARP查询针对下一跳IPv4 192.168.10.1，返回帧目的MAC。")],
            [("layer_separation", "IP目的地址仍是8.8.8.8，但本链路目的MAC是网关接口。"),
             ("request_reply_sequence", "广播ARP请求只用于解析；之后数据报以解析到的网关MAC单播发送。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要先按子网判断本地/异网，再区分IP终点与链路下一跳。", "用路由下一跳规则和ARP请求/应答过程双重核验目的MAC。", "远端主机MAC不会跨路由器直接解析；ARP广播请求不代表数据帧也广播。", "联系IPv4路由决策、默认网关与ARP地址解析的分层职责。"),
            ["ARP", "IPv4子网", "默认网关"], difficulty="medium"),

        item("z5b7-408-ftp-passive-data-initiator", "cs408.cn.topic.d8296e4021b3", "A",
            "FTP客户端已通过TCP连接到服务器控制端口21。客户端发送PASV命令，服务器返回监听数据端口P；随后传输一个文件。按照被动模式，谁发起新的数据TCP连接？",
            {"A": "客户端向服务器公布的端口P发起连接", "B": "服务器从端口20主动连接客户端", "C": "客户端复用控制TCP连接传输文件，不建立数据连接", "D": "服务器向客户端随机端口发起连接，控制连接关闭"},
            "PASV使服务器在其侧选择并监听数据端口P，并把地址端口告知客户端。客户端随后主动建立第二条TCP数据连接到服务器P；控制连接仍用于命令，数据连接承载文件。服务器端主动向客户端连接属于传统主动模式的特征，不是PASV。",
            [("passive_mode_socket_roles", "服务器在P监听，客户端作为主动打开方connect到服务器P。"),
             ("control_data_separation", "控制连接与数据连接分离，文件不复用21端口控制连接。")],
            [("protocol_state_trace", "PASV响应先给服务器被动监听端点，客户端再建立数据连接。"),
             ("active_passive_contrast", "服务器端口20主动回连是主动模式的典型方式，与题设PASV相反。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需依据PASV的监听方和连接发起方区分控制与数据通道。", "按命令—服务器监听—客户端连接状态顺序推演，并与主动模式对照。", "不能把传统主动FTP的服务器回连或端口20行为误套到被动模式。", "在防火墙/NAT常见场景中理解FTP双连接及主动被动模式差异。"),
            ["FTP", "主动与被动模式", "控制连接与数据连接"], difficulty="medium"),

        item("z5b7-408-ethernet-binary-exponential-backoff", "cs408.cn.topic.bcfe8d79341e", "D",
            "共享式以太网按二进制指数退避工作，某站在第3次碰撞后按K∈[0,2³−1]随机选择K=5。冲突后退避时隙长度为512 bit time，链路速率10 Mbit/s。该站至少等待多长时间才重新尝试？",
            {"A": "25.6 μs", "B": "51.2 μs", "C": "128 μs", "D": "256 μs"},
            "每时隙512 bit time，链路速率10^7 bit/s，因此时隙时长512/10^7 s=51.2 μs。选K=5后等待5个时隙，即256 μs。退避时间在碰撞处理后计，不包含未给定的检测、Jam或其他介质延迟。",
            [("slot_time_conversion", "512 bit除以10 Mbit/s得51.2 μs每时隙。"),
             ("random_backoff_product", "K=5时等待5×51.2 μs=256 μs，与bit time乘积核算一致。")],
            [("bit_time_definition", "bit time是发送1 bit所需时间，512 bit time即512/R。"),
             ("dimensional_cross_check", "5×512 bit÷10^7 bit/s=0.000256 s=256 μs。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要把二进制指数退避选取的时隙数转换为链路时间。", "按bit-time定义计算时隙，再按随机K倍乘并用量纲核对。", "退避槽数不是指数值本身；K=5要等待五个槽而非一个槽。", "将CSMA/CD碰撞退避状态与信道速率、时隙长度相联系。"),
            ["以太网", "CSMA/CD", "二进制指数退避"], difficulty="medium"),
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
                report = run_batch(db, candidate_specs=candidates(), batch_id="07")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH07_APPLIED"
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
