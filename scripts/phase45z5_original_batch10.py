"""Tenth offline-authored public-original batch for the isolated Z5 database."""
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

BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch09/post-batch09.dump"
BACKUP_SHA256 = "D8B0B9AD6FD745722BBA2CDB123043CA365E0C3AFAC14536DBB542F4221376C4"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch10"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"


def candidates():
    return [
        item("z5b10-math-linear-ode-integrating-factor", "math.exam.21e0818406c9", "A",
            "在区间(−π/2,π/2)上，函数y满足y'+y tan x=sin x且y(0)=0。y(π/3)等于（ ）。",
            {"A": "(ln 2)/2", "B": "ln 2", "C": "1/(2 ln 2)", "D": "0"},
            "积分因子为exp(∫tan x dx)=sec x，于是(y sec x)'=tan x。积分得y sec x=−ln(cos x)+C；由y(0)=0知C=0。故y=−cos x ln(cos x)，代入π/3得到(ln2)/2。直接把原方程当作可分离方程会遗漏积分因子。",
            [("integrating_factor_derivation", "乘以sec x后左侧成为(y sec x)'，积分并代入初值确定常数。"),
             ("substitution_check", "将y=−cos x ln(cos x)求导代回原方程，并验证y(0)=0。")],
            [("linear_ode_formula", "线性方程积分因子μ=sec x，(μy)'=μ sin x=tan x，积分得到解族。"),
             ("initial_value_and_endpoint", "初值令积分常数为0；cos(π/3)=1/2，故端点值为(ln2)/2。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要识别一阶线性方程并构造非平凡积分因子，再处理初值。", "通过积分因子解方程并代回原式两种路径核验函数。", "积分因子是sec x而不是cos x；最后还需代入给定端点。", "把变系数线性微分方程、初值确定和函数端点计算连在一起。"),
            ["一阶线性微分方程", "积分因子", "初值问题"], difficulty="medium"),

        item("z5b10-math-order-reduction-initial-value", "math.exam.66f8f7b61188", "C",
            "在x>0上求解初值问题x y''−y'=0，y(1)=1，y'(1)=2。函数y(2)为（ ）。",
            {"A": "2", "B": "3", "C": "4", "D": "5"},
            "令v=y'降阶，方程化为xv'−v=0。分离得v'/v=1/x，因此v=Cx；由y'(1)=2知C=2。积分得y=x²+D，再由y(1)=1知D=0，故y(2)=4。若直接将y当作v处理，会错过降阶结构。",
            [("order_reduction", "令v=y'后解一阶方程，得到y'=Cx，再积分恢复y。"),
             ("initial_condition_substitution", "先用导数初值确定C=2，再用函数初值确定积分常数D=0。")],
            [("separation_check", "从xv'−v=0得v'/v=1/x，故v=Cx；代入原方程可验证。"),
             ("integrated_solution", "y'=2x给出y=x²+D，两个初值唯一确定D并得到端点值4。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("通过令v=y'把二阶方程降为一阶，并依次使用两类初值。", "降阶求解与把最终函数代回方程和初值两种方式复核。", "两个初值分别确定导数积分常数和函数积分常数，不能混用。", "训练降阶代换与初值条件共同确定二阶方程特解。"),
            ["降阶法", "初值条件", "微分方程"], difficulty="medium"),

        item("z5b10-math-nonlinear-ode-first-integral", "math.exam.ec75fe95fe0f", "D",
            "函数y在含x=0与x=1的区间上保持正值，满足y y''+(y')²=0，且y(1)=1、y'(1)=−1。则y(0)=（ ）。",
            {"A": "1/2", "B": "1", "C": "√2", "D": "√3"},
            "左侧是(yy')'，故yy'为常数。由x=1处条件得yy'=−1，于是(y²)'=−2。积分并代入y(1)=1，得y²=3−2x。y保持正值，因此y(0)=√3。代回可见yy'恒为−1，原方程成立。",
            [("first_integral", "识别(yy')'=yy''+(y')²，结合初值积分得到yy'=−1。"),
             ("positive_branch_solution", "继续积分得到y²=3−2x，利用题设正值条件选择正平方根。")],
            [("differentiate_product", "将方程写成(yy')'=0并用x=1的斜率值确定常数。"),
             ("initial_value_check", "函数初值确定y²的积分常数；正值分支给出y(0)=√3。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需发现非线性方程的乘积导数结构并连续积分两次。", "第一积分和对平方函数积分两步推导，并代回检验。", "仅取平方方程会有正负分支；题设y>0决定唯一分支。", "训练通过一阶积分降阶处理含y与y'乘积结构的非线性二阶方程。"),
            ["二阶非线性微分方程", "一阶积分", "初值问题"], difficulty="medium"),

        item("z5b10-math-upper-limit-composite-derivative", "math.exam.3504d885999b", "B",
            "设F(x)=∫₀^{x²} e^{−t²}dt+∫₁^x t ln(1+t)dt（x在1附近）。F'(1)等于（ ）。",
            {"A": "2/e", "B": "2/e+ln2", "C": "1/e+ln2", "D": "2e+ln2"},
            "由变上限积分求导并使用链式法则，第一项导数为e^{−(x²)²}·2x=2x e^{−x⁴}。第二项导数为x ln(1+x)。因此F'(1)=2/e+ln2。注意第一项被积函数要在上限x²处取值，指数为−x⁴。",
            [("fundamental_theorem_chain_rule", "第一项按上限x²求导得到2xe^(−x⁴)，第二项按微积分基本定理得到xln(1+x)。"),
             ("difference_quotient_local_check", "用小增量下积分区间长度乘端点被积函数并计入上限变化，得到同一端点导数。")],
            [("upper_endpoint_substitution", "先代入t=x²再乘上限导数2x，不能遗漏链式因子。"),
             ("endpoint_evaluation", "在x=1处两项分别为2/e和ln2，相加得2/e+ln2。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("结合变上限积分求导、复合上限链式因子及两积分求导规则。", "微积分基本定理逐项求导，并以局部差商解释复合端点因子。", "第一积分的上限是x²，代入被积函数后为e^(−x⁴)，且必须乘2x。", "综合检查变上限函数中复合端点、被积函数和端点代值。"),
            ["变上限积分", "微积分基本定理", "链式法则"], difficulty="medium"),

        item("z5b10-math-vector-linear-representation-unique", "math.exam.9a1731a929ab", "A",
            "向量u=(1,1,0)、v=(0,1,1)、w=(1,0,1)构成R³的一组向量。向量b=(3,2,1)在该组向量下的线性表示系数(α,β,γ)为（ ）。",
            {"A": "(2,0,1)", "B": "(1,1,1)", "C": "(3,−1,0)", "D": "(1,0,2)"},
            "解αu+βv+γw=b，逐坐标得到α+γ=3、α+β=2、β+γ=1。由后两式得α=2−β、γ=1−β，代入第一式得到β=0，进而α=2、γ=1。系数唯一，因为系数矩阵行列式为2≠0。",
            [("coordinate_system", "按三个坐标列出方程组，消元得到α=2、β=0、γ=1。"),
             ("determinant_uniqueness", "系数矩阵行列式为2，非零说明表示存在且唯一。")],
            [("substitution_check", "计算2u+0v+w=(3,2,1)，逐分量与b相同。"),
             ("linear_independence", "三向量矩阵行列式为2≠0，故构成基并保证系数唯一。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要把向量表示转化为线性方程组并处理唯一性。", "逐坐标消元求系数，并用行列式非零与回代验证唯一解。", "注意w的坐标是(1,0,1)，不能误写成u+v的坐标。", "连接向量组线性表示、坐标方程组求解和线性无关判定。"),
            ["向量组线性表示", "线性方程组", "线性无关"], difficulty="medium"),

        item("z5b10-math-extrema-classification-quartic", "math.exam.bc1427755983", "C",
            "函数f(x)=x⁴−4x²在实数范围内的极值情况及函数值是（ ）。",
            {"A": "仅x=0处有极小值0", "B": "x=0处极小，x=±√2处极大", "C": "x=0处极大值0，x=±√2处极小值−4", "D": "三个驻点均为极小值"},
            "f'(x)=4x(x²−2)，驻点为0和±√2。二阶导数f''(x)=12x²−8；f''(0)=−8<0，故0处为极大值且f(0)=0；f''(±√2)=16>0，故两处为极小值且函数值4−8=−4。",
            [("critical_point_and_second_derivative", "求导列出三个驻点，用二阶导数符号分类极值类型。"),
             ("function_value_substitution", "将驻点代回原函数，得到中心值0和两侧值−4。")],
            [("first_derivative_sign", "f'在各驻点间符号交替为负、正、负、正，确认中间升降变化。"),
             ("symmetry_and_values", "偶函数使±√2的极小值相同；直接代入得到−4。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需先求完整驻点集合，再区分极大极小并计算函数值。", "二阶导数判别与一阶导数符号变化分别验证极值类型。", "驻点并不都为极小值；函数偶对称也不意味着中心是最小值。", "综合多项式求导、极值分类、函数值计算与偶函数对称性。"),
            ["极值定义", "驻点", "二阶导数判别"], difficulty="medium"),

        item("z5b10-math-nonhomogeneous-ode-initial-data", "math.exam.d59b003eda7d", "B",
            "初值问题y''−3y'+2y=e^x，y(0)=0，y'(0)=1的解为（ ）。",
            {"A": "(x−2)e^x+2e^{2x}", "B": "−(x+2)e^x+2e^{2x}", "C": "(2−x)e^x−2e^{2x}", "D": "−(x+1)e^x+2e^{2x}"},
            "齐次特征根为1、2。因右端e^x与根1共振，取特解−xe^x（代入算子可得e^x），故通解y=C₁e^x+C₂e^{2x}−xe^x。初值给C₁+C₂=0、C₁+2C₂−1=1，解得C₁=−2、C₂=2，因此y=2e^{2x}−(x+2)e^x。",
            [("characteristic_and_resonance", "特征多项式为(r−1)(r−2)，对e^x共振时试取axe^x并确定a=−1。"),
             ("initial_condition_system", "代入y(0)、y'(0)解两常数，得到C₁=−2、C₂=2。")],
            [("operator_substitution", "将−xe^x代入D²−3D+2可得e^x，验证特解系数符号。"),
             ("differentiate_final_solution", "对最终表达式求导并代入x=0，分别得到y(0)=0、y'(0)=1。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要组合常系数齐次解、共振特解和两条初值条件。", "特征方程/待定系数解法后，以算子代入和初值直接复核。", "共振需乘x，且特解符号由算子作用决定，不能沿用齐次项。", "训练非齐次线性方程特解结构与初值确定通解常数。"),
            ["特解与对应齐次方程通解", "常系数线性微分方程", "共振"], difficulty="medium"),

        item("z5b10-math-change-of-basis-coordinates", "math.exam.f99711e0ea65", "B",
            "平面的一组基为c₁=(1,1)、c₂=(1,−1)。向量x在标准基下的坐标为(5,1)，则x在基(c₁,c₂)下的坐标为（ ）。",
            {"A": "(5,1)", "B": "(3,2)", "C": "(2,3)", "D": "(1,4)"},
            "设[x]_C=(a,b)，则x=a(1,1)+b(1,−1)=(a+b,a−b)=(5,1)。联立得2a=6、2b=4，因此a=3、b=2。若以基向量为列组成P，则[x]_E=P[x]_C，解该坐标变换方程得到相同结果。",
            [("basis_column_equation", "写出P=[[1,1],[1,−1]]并解P(a,b)^T=(5,1)^T。"),
             ("inverse_transform", "det(P)=−2，求逆变换将标准坐标映为(3,2)。")],
            [("linear_combination", "检查3c₁+2c₂=(5,1)，确认该坐标表示正确。"),
             ("basis_independence", "基变换矩阵行列式非零，坐标唯一；不能把标准坐标直接当新基坐标。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需区分标准坐标和非标准基坐标并正确处理变换方向。", "由线性组合方程求解，再用基向量矩阵逆变换复核。", "关系是标准坐标=P乘新基坐标，直接把P方向倒置会得错值。", "理解基向量矩阵、坐标列向量和换基矩阵之间的乘法关系。"),
            ["置换矩阵", "基与坐标", "坐标变换"], difficulty="medium"),

        item("z5b10-math-density-centroid-triangle", "math.exam.5af66b782c26", "C",
            "三角区域D={(x,y):x≥0,y≥0,x+y≤1}上的面密度为ρ(x,y)=x+y。该薄片质心的横坐标为（ ）。",
            {"A": "1/4", "B": "1/3", "C": "3/8", "D": "1/2"},
            "质量M=∬_D(x+y)dA。按0≤x≤1、0≤y≤1−x积分，内积后M=∫₀¹(1/2−x²/2)dx=1/3。对y轴的矩M_y=∬_D x(x+y)dA=∫₀¹(x/2−x³/2)dx=1/8。故质心横坐标x̄=M_y/M=(1/8)/(1/3)=3/8。对称性还给出纵坐标相同。",
            [("mass_and_moment_integrals", "分别计算质量1/3及关于y轴的矩1/8，取比得到3/8。"),
             ("symmetry_transform", "区域与密度在交换x、y下对称，质心两坐标相同；直接积分确认横坐标数值。")],
            [("iterated_integral", "按三角区域上下限先积y再积x，得到M=1/3、M_y=1/8。"),
             ("centroid_definition", "质心坐标为一阶矩除以总质量，(1/8)/(1/3)=3/8。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需根据非均匀密度分别计算质量与一阶矩，并留意三角区域积分限。", "迭代积分求质量和矩，再由质心定义取商并用对称性检查。", "质心不是几何质心(1/3,1/3)，因为密度随坐标增大而变化。", "将二重积分、变密度质量分布、对称性和质心应用连起来。"),
            ["二重积分的应用", "质量与质心", "一阶矩"], difficulty="medium"),

        item("z5b10-math-hessian-parameter-positive-definite", "math.exam.58a5d04a7be9", "A",
            "二元函数f_b(x,y)=x²+2bxy+3y²在原点处梯度为零。参数b满足何条件时，原点为严格局部极小点？",
            {"A": "|b|<√3", "B": "|b|≤√3", "C": "|b|>√3", "D": "任意实数b"},
            "Hessian矩阵为[[2,2b],[2b,6]]。二阶型正定的Sylvester条件是首顺序主子式2>0且行列式12−4b²>0，等价于|b|<√3。等号时二次型半正定并沿某非零方向恒为0，故原点不是严格局部极小；更大时行列式负、原点为鞍点。",
            [("hessian_sylvester", "用顺序主子式条件2>0和12−4b²>0得到严格条件|b|<√3。"),
             ("complete_square", "二次型可写为(x+by)²+(3−b²)y²，严格正定当且仅当3−b²>0。")],
            [("principal_minor_test", "二阶主子式行列式为12−4b²，正定须与首主子式同时为正。"),
             ("boundary_case", "|b|=√3时存在非零零方向，函数沿该方向不增不减且取0，排除严格极小。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("通过Hessian正定性与严格局部极值定义处理参数边界。", "Sylvester顺序主子式与边界零方向分析两路验证严格不等号。", "半正定只保证非严格极小；边界等号不能纳入严格极小条件。", "连接多元二阶判别、参数分类、二次型正定和边界退化情形。"),
            ["Hessian判别法", "二次型正定", "参数讨论"], difficulty="medium"),

        item("z5b10-408-semaphore-producer-consumer-deadlock", "cs408.os.topic.86089b973451", "C",
            "有界缓冲区容量已满，生产者按wait(mutex)、wait(empty)、写入、signal(mutex)、signal(full)执行；消费者需先wait(mutex)才能取出元素。生产者阻塞在wait(empty)时仍持有mutex。下列判断正确的是（ ）。",
            {"A": "不会阻塞，因为empty会自动增加", "B": "消费者可以忽略mutex并安全取数据", "C": "形成死锁；应先wait(empty)再wait(mutex)，消费者也先wait(full)再wait(mutex)", "D": "只要把signal(full)移到wait(empty)之前即可"},
            "缓冲区已满时empty=0。生产者先获得mutex后在wait(empty)永久等待，却没有释放mutex；消费者即使有full，也会在wait(mutex)处等待，因此双方互相阻塞。标准顺序应先等待各自的资源计数信号量(empty或full)，再竞争互斥量，临界区结束后释放mutex并更新另一计数信号量。",
            [("wait_for_graph", "生产者等待empty但持有mutex；消费者等待mutex而持有可用full，等待形成环。"),
             ("semaphore_order_invariant", "把资源计数等待放在互斥量等待之前，避免阻塞时占有唯一互斥锁。")],
            [("deadlock_conditions", "缓冲区满使empty=0，生产者持锁等待；消费者不能获锁释放空槽。"),
             ("corrected_order", "P先wait(empty)后wait(mutex)；C先wait(full)后wait(mutex)，离开临界区再signal。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要结合信号量初值、缓冲区满状态和临界区锁持有关系推演阻塞链。", "等待图与正确P/V顺序分别揭示死锁和预防方式。", "仅有可用full并不足够；消费者被mutex阻塞，无法制造empty。", "分析生产者—消费者同步中的资源计数与互斥锁顺序导致的死锁。"),
            ["信号量", "生产者消费者", "死锁"], difficulty="medium"),

        item("z5b10-408-memory-mapped-shared-private", "cs408.os.topic.ad1f1d04dbc6", "D",
            "进程P与Q将同一文件区间映射到虚拟地址，P修改映射页中的一个字节。若P采用共享映射而Q采用私有映射，下列描述最准确的是（ ）。",
            {"A": "两种映射都会立即修改文件且彼此可见", "B": "私有映射总会阻止P写入", "C": "共享映射只在进程P内部可见，私有映射自动同步文件", "D": "共享映射的修改可通过同一文件页缓存对其他共享映射可见并可回写文件；私有映射写时复制，不把私有修改作为共享文件更新"},
            "共享映射对应文件的共享页，修改可被同一文件区域的其他共享映射观察，并最终回写文件；若要求持久化时点有保证，还需使用同步机制。私有映射写入采用写时复制，修改属于本进程私有副本，不作为共享文件内容更新。题干分别说明P共享、Q私有，因此Q的私有页不应被当成共享更新通道。",
            [("mapping_semantics", "对比共享页映射和私有写时复制，确定文件回写及进程可见范围。"),
             ("persistence_vs_visibility", "共享修改可见性与落盘持久化是不同保证；同步调用解决后者时点。")],
            [("shared_mapping_case", "MAP_SHARED类语义把修改关联到文件共享页，其他共享映射可观察更新。"),
             ("private_mapping_case", "私有写入触发副本，既不修改共享页也不自动回写原文件。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需区分共享映射、私有写时复制、跨进程可见性和文件持久化。", "分别追踪共享页与私有副本，并说明同步落盘的不同语义。", "不能把映射可见性直接等同于立即持久化；私有映射写入也不共享。", "理解内存映射文件把文件I/O、页缓存和进程虚拟内存结合的机制。"),
            ["内存映射文件", "虚拟内存", "共享与私有映射"], difficulty="medium"),

        item("z5b10-408-interrupt-exception-synchronous", "cs408.os.topic.4ac423ec47e2", "B",
            "某CPU运行用户进程时发生三件事：①外部时钟设备发出定时信号；②当前指令执行整数除法且除数为0；③用户程序执行系统调用指令。按事件与当前指令流关系分类，正确的是（ ）。",
            {"A": "①同步异常，②外部中断，③仅为普通函数调用", "B": "①异步外部中断，②同步异常，③由指令主动引发的同步陷入/系统调用", "C": "三者均为异步外部中断", "D": "①普通指令，②系统调用，③硬件故障中断"},
            "定时器在与当前指令无关的时刻发出请求，属于异步外部中断。除零由当前指令执行结果触发，与指令流同步，属于同步异常。系统调用也由程序执行特定指令主动请求内核服务，通常作为同步陷入处理，不是普通用户态函数调用。",
            [("event_causality", "根据事件是否由正在执行的指令触发，区分外部中断和同步异常/陷入。"),
             ("control_transition", "系统调用需要保存用户态上下文并进入内核态，由陷入机制完成特权级转换。")],
            [("asynchronous_timer", "外设/时钟请求可在任意指令边界到达，独立于当前指令结果。"),
             ("synchronous_fault_and_trap", "除零由指令执行触发；系统调用由专门指令主动请求，两者都与程序流同步。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("依据触发源和与当前指令流的因果关系分类三种控制转移。", "从外部异步性、指令执行故障及主动系统调用逐项核对。", "系统调用会切换到内核态，不等同于普通函数调用；除零也不是外设中断。", "从操作系统视角掌握中断、异常和系统调用的边界。"),
            ["中断与异常", "系统调用", "用户态内核态"], difficulty="medium"),

        item("z5b10-408-tlb-effective-access-time", "cs408.os.topic.db2a9445e210", "A",
            "某系统采用分页和TLB，TLB查找耗时1 ns，主存访问耗时100 ns。TLB命中率为0.8；未命中时需先访问一次主存页表，再访问目标数据。忽略页故障和其他开销，平均访问时间为（ ）。",
            {"A": "121 ns", "B": "101 ns", "C": "120 ns", "D": "201 ns"},
            "命中时耗时为1+100=101ns；未命中时为1+100+100=201ns。按命中率加权EAT=0.8×101+0.2×201=80.8+40.2=121ns。页表访问只在TLB未命中时额外发生一次，题目没有多级页表或页故障开销。",
            [("conditional_access_time", "分别列出命中101ns与未命中201ns，再按0.8/0.2加权。"),
             ("event_tree", "将TLB查找固定成本与未命中条件下两次主存访问分层求期望。")],
            [("expected_value", "EAT=0.8(1+100)+0.2(1+100+100)=121ns。"),
             ("boundary_sanity", "命中率趋近1时结果趋于101ns，趋近0时趋于201ns，121ns位于其间。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要按TLB命中与未命中分支建立条件访问时延模型。", "分支加权期望与事件树逐层计数两种方式求得121ns。", "TLB未命中需访问页表和数据两次主存，不能只算一次主存。", "量化TLB命中率对分页系统平均访存时间的影响。"),
            ["内存管理基础", "TLB", "平均访存时间"], difficulty="medium"),

        item("z5b10-408-vfs-mount-namespace", "cs408.os.topic.4b8b4cf18f4d", "C",
            "文件系统F2挂载到F1中已有目录/mnt/data。挂载完成后，进程按路径/mnt/data/report.txt查找文件。关于路径解析及卸载后的行为，正确的是（ ）。",
            {"A": "路径仍直接访问F1中原目录内容，挂载点只作标签", "B": "挂载会把F2所有文件复制进F1的/mnt/data", "C": "路径跨过挂载点后进入F2根目录；挂载期间原挂载点下层内容被遮蔽，卸载后重新可见", "D": "只能用设备号访问F2，不能通过路径名访问"},
            "挂载把另一个文件系统的根接到目录树的挂载点上。解析到/mnt/data时转入F2，从其根目录继续查找report.txt；不是复制文件。挂载期间F1原/mnt/data中的内容仍存在但被遮蔽，正常卸载F2后该底层目录内容再次可见。",
            [("mount_tree_walk", "逐段解析路径，在/mnt/data处切换到F2根，再查找report.txt。"),
             ("underlying_directory_state", "挂载改变目录树可见路径而非删除或复制底层目录内容。")],
            [("namespace_transition", "挂载点形成文件系统命名空间连接，后续路径操作针对被挂载文件系统。"),
             ("unmount_reversibility", "卸载移除连接后，原文件系统目录内容恢复可见。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需追踪目录树挂载连接并区分路径可见性与底层数据复制。", "沿路径解析跨越挂载点，并比较挂载/卸载前后的命名空间。", "挂载不会清空挂载点下层文件；它们只是被上层文件系统暂时遮蔽。", "理解虚拟文件系统用统一目录树组织多个文件系统的机制。"),
            ["虚拟文件系统与挂载", "文件系统", "路径解析"], difficulty="medium"),

        item("z5b10-408-sequential-search-expected-comparisons", "cs408.ds.topic.d6d83159a7e3", "D",
            "长度为8的无序表采用从头到尾的顺序查找。查找成功时目标等概率出现在8个位置之一；查找失败概率与成功概率各为1/2，失败时必须比较全部8项。一次查找的平均关键字比较次数为（ ）。",
            {"A": "4.5", "B": "5.0", "C": "6.0", "D": "6.25"},
            "成功时平均比较次数为(1+2+…+8)/8=36/8=4.5；失败时需比较8次。按成功、失败各1/2加权，E=0.5×4.5+0.5×8=6.25。失败概率不能忽略，也不能把成功平均值直接当总体平均值。",
            [("success_failure_conditioning", "成功/失败条件期望分别为4.5与8，再按概率各一半加权。"),
             ("comparison_sum", "成功位置的比较总数为等差和36，除8得4.5。")],
            [("expected_value_formula", "E=ΣP(i)C_i，成功部分4.5、失败部分8，合并为6.25。"),
             ("bounds_check", "总体期望应位于4.5和8之间，6.25满足并偏向失败成本。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要分别建立查找成功与失败的条件成本，再按事件概率汇总。", "条件期望加权与成功比较次数等差和两条路径一致。", "成功和失败概率不相等于位置概率；失败分支固定执行8次。", "评估无序表顺序查找在混合命中率下的平均比较代价。"),
            ["顺序查找", "平均查找长度", "期望分析"], difficulty="medium"),

        item("z5b10-408-adjacency-matrix-degree", "cs408.ds.topic.f26de897ea89", "B",
            "有向图顶点次序为A、B、C、D、E，边集为A→B、A→D、B→D、C→A、C→D、D→C。用邻接矩阵表示时，顶点D的出度和入度分别为（ ）。",
            {"A": "3，1", "B": "1，3", "C": "1，2", "D": "2，3"},
            "按顶点顺序A、B、C、D、E构造邻接矩阵。第D行只有D→C对应的一个1，因此出度为1；第D列对应A→D、B→D、C→D三条入边，因此入度为3。图中没有D→D自环，行列统计无需再调整。",
            [("matrix_row_column", "有向图邻接矩阵中第D行计出边为1，第D列计入边为3。"),
             ("edge_list_count", "直接从边集枚举D的出边集合{C}和入边集合{A,B,C}。")],
            [("matrix_construction", "按顶点序列将每条弧写入矩阵对应行列，再统计D行、D列。"),
             ("degree_semantics", "有向图出度数尾端弧，入度数头端弧；不把行列概念颠倒。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要将有向边集合映射为邻接矩阵的行列并区分入出度。", "矩阵行列计数与弧集合枚举两种表示互相核对。", "有向图行表示弧尾、列表示弧头；本题D列有三条而非两条入边。", "联系图的边集、邻接矩阵和顶点度数统计及算法建模。"),
            ["邻接矩阵", "有向图", "入度与出度"], difficulty="medium"),

        item("z5b10-408-thread-state-transition", "cs408.os.topic.e8dd56864fdc", "A",
            "某多线程进程中，线程T1正在用户态运行；T2已就绪；T3因等待磁盘I/O而阻塞。磁盘I/O完成后，T3进入何种状态？若此时T1仍占用CPU，T3能否立即运行？",
            {"A": "T3由阻塞转为就绪，等待调度；不一定立即运行", "B": "T3直接由阻塞转为运行并抢占T1", "C": "T3终止，需重新创建", "D": "T1自动阻塞，T3成为就绪但进程整体终止"},
            "I/O完成解除T3的等待条件，使其从阻塞态转入就绪态。就绪只表示具备运行条件，是否立即获得CPU取决于调度策略和抢占条件；题干没有给出必然抢占规则，因此不能断言T3立即运行。T1继续占用CPU与T3就绪可同时成立。",
            [("state_transition", "I/O完成事件使等待条件满足，状态转换为阻塞→就绪。"),
             ("scheduler_separation", "就绪态只表示可被选中，CPU分配仍由调度器决定。")],
            [("event_state_table", "阻塞等待I/O期间不具备运行资格；完成后才进入就绪队列。"),
             ("nonpreemptive_counterexample", "在非抢占或优先级不足条件下，T1可继续运行，说明就绪不等于立即执行。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要区分阻塞解除、就绪队列和实际CPU调度三个不同阶段。", "状态转换与调度器决策分离推导，不假定题干未给出的抢占策略。", "I/O完成不会直接赋予CPU，也不会让其他线程自动阻塞或终止。", "理解线程状态迁移以及并发执行中事件与调度的边界。"),
            ["线程实现", "线程状态", "调度"], difficulty="medium"),

        item("z5b10-408-adjacency-multilist-degree", "cs408.ds.topic.ea735e877597", "B",
            "无向图采用邻接多重表存储，顶点集合为A、B、C、D，边集为{AB、AC、BC、BD、CD}。每条边结点只存一次，并分别链接到它的两个端点关联边链表。顶点B的度以及全图边结点数分别为（ ）。",
            {"A": "2，6", "B": "3，5", "C": "4，5", "D": "3，4"},
            "与B关联的边为AB、BC、BD，共3条，所以deg(B)=3。邻接多重表中无向边结点只保存一次，边集共有5条，故边结点数为5；不能像邻接表那样把每条边在两个顶点链中重复视作两个边结点。",
            [("incident_edge_chain", "逐条筛出AB、BC、BD并计数，得到B的度为3。"),
             ("edge_node_storage", "多重表每条无向边只有一个边结点，边结点总数等于边数5。")],
            [("degree_edge_set", "无向图顶点度等于关联边数，B关联三条不同边。"),
             ("storage_structure", "每个边结点通过两个端点链接复用，不因双端链接而复制边记录。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要区分顶点关联边计数与邻接多重表边结点的唯一存储。", "从端点集合求度并从结构定义求记录数两路核验。", "边结点链入两个端点不代表存两份；全图边结点数仍为5。", "理解邻接多重表利用一份边记录同时组织无向图两个端点。"),
            ["邻接多重表", "无向图", "顶点度"], difficulty="medium"),

        item("z5b10-408-io-controller-registers", "cs408.os.topic.feae17c9ece4", "D",
            "CPU通过设备控制器与字符输入设备通信。控制器提供数据、状态和命令寄存器：CPU向命令寄存器写入启动位后，设备异步完成输入并置位ready；采用中断方式时，CPU后续如何取得输入数据最符合该机制？",
            {"A": "CPU必须持续读取数据寄存器直到数据到达", "B": "设备直接把数据写入任意用户变量且不经过控制器", "C": "命令寄存器自动保存所有输入字节并替代数据寄存器", "D": "设备就绪后向CPU发中断，CPU进入服务程序读取控制器数据寄存器并清除/确认状态"},
            "CPU先通过控制器命令寄存器启动设备；设备完成后置ready并提出中断请求。CPU响应中断后执行相应服务程序，从控制器数据寄存器读取数据，并按设备协议清除或确认状态。若CPU一直循环读取状态，则属于程序查询而非中断方式。",
            [("controller_register_roles", "命令寄存器启动设备、状态寄存器报告ready、数据寄存器承载输入数据。"),
             ("interrupt_service_flow", "完成事件触发中断，CPU在服务程序中读数据并确认状态。")],
            [("event_sequence", "启动命令→设备异步完成→置ready并中断→ISR读数据和应答。"),
             ("polling_contrast", "持续循环读取状态属于程序查询，不符合题设中断方式。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需把设备控制器三个寄存器职责与中断服务流程按时间顺序结合。", "寄存器角色映射和事件时序两条路径核对数据读取位置。", "中断方式不是不停查询；ready状态、数据寄存器和命令寄存器职责不同。", "理解CPU、设备控制器和异步I/O事件之间的交互边界。"),
            ["I/O设备分类与接口", "设备控制器", "中断I/O"], difficulty="medium"),
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
                report = run_batch(db, candidate_specs=candidates(), batch_id="10")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH10_APPLIED"
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
