"""Batch 36: second distinct item for the next 50 one-question topics."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-35-second-supply"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_35_SECOND_SUPPLY_COMPLETE":
    raise RuntimeError("batch35_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch35_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-36-second-supply"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_35_SECOND_SUPPLY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-36-second-supply"
batch.SUCCESS_STATUS = "BATCH_36_SECOND_SUPPLY_COMPLETE"
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


# Mathematics II: 25 single-question leaves.
add("hx36-math-separable-ivp", "math.exam.b05d65f2b0c1",
    "初值问题 y'=xy，y(0)=2。求 y 在 x=√(2 ln 3) 处的值。",
    ["2", "3", "4", "6"], "D",
    "分离变量得 y=Ce^(x²/2)，初值给 C=2；代入 x²/2=ln3，得到6。",
    "separation-of-variables", "ln y=x²/2+C，使用初值后 y=2e^(x²/2)=6。",
    "substitute-solution", "y=2e^(x²/2)满足方程和初值，指定点指数因子为3。",
    "分离变量并积分。", "用初值确定常数后代入指定点。", ["可分离变量", "初值问题"])
add("hx36-math-linear-solution-structure", "math.exam.3b91ad45ab4c",
    "方程 y''−y=0 满足 y(0)=2、y'(0)=0。其解在 x=ln2 处的值是多少？",
    ["2", "5/2", "3", "4"], "B",
    "通解 y=C₁eˣ+C₂e⁻ˣ。初值给 C₁=C₂=1，故 y(ln2)=2+1/2=5/2。",
    "characteristic-equation", "特征根±1，初值联立得到两个系数均为1，代入为5/2。",
    "linear-combination-and-ivp", "两线性无关解按初值组合成 eˣ+e⁻ˣ，在ln2处为2+1/2。",
    "求特征方程的两个根。", "用两个初值确定线性组合系数。", ["线性微分方程解结构", "通解"])
add("hx36-math-integral-composite", "math.exam.d2336ba379ea",
    "计算定积分 ∫₀¹(x²+2x+1)dx。",
    ["5/3", "2", "7/3", "3"], "C",
    "逐项积分得 1/3+1+1=7/3。",
    "termwise-antiderivative", "原函数 x³/3+x²+x，端点差为7/3。",
    "integral-linearity", "三项积分分别为1/3、1、1，总和7/3。",
    "利用积分线性拆项。", "逐项代入上下限并求和。", ["一元积分综合", "定积分计算"])
add("hx36-math-reverse-order", "math.exam.cbd48f6fb174",
    "将区域上的累次积分 ∫₀²∫₀^(y/2) f(x,y)dx dy 改为先对 y 积分，积分限应为哪一项？",
    ["0≤x≤1，2x≤y≤2", "0≤x≤2，0≤y≤x/2", "0≤y≤1，0≤x≤2y", "0≤x≤2，x≤y≤2"], "A",
    "原区域满足0≤y≤2且0≤x≤y/2，等价于0≤x≤1、2x≤y≤2。",
    "inequality-reversal", "x≤y/2改写为y≥2x；结合y≤2得x≤1。",
    "region-projection", "区域投影到x轴为[0,1]，固定x后y从2x到2。",
    "把 x≤y/2 改写为 y 的下界。", "求区域在 x 轴上的投影。", ["二次积分", "变换积分次序"])
add("hx36-math-piecewise-antiderivative", "math.exam.59e1e05f1c94",
    "设 f(x)=1（x<0），f(x)=2x（x≥0）。若 F'(x)=f(x) 且 F(0)=3，则 F(1) 等于多少？",
    ["3", "4", "5", "6"], "B",
    "在 x≥0 上 F(x)=x²+C，由 F(0)=3 得 C=3，因此 F(1)=4。",
    "integrate-right-branch", "对2x积分得x²+C，连续取F(0)=3后F(1)=4。",
    "derivative-check", "F=x²+3在右侧导数为2x且满足给定初值，代入1得4。",
    "只在 x≥0 的分支积分。", "用 F(0) 确定积分常数。", ["不定积分", "分段函数原函数"])
add("hx36-math-rank-matrix", "math.exam.0aad93648d60",
    "矩阵 A=[[1,2,3],[2,4,6],[0,1,1]] 的秩是多少？",
    ["1", "2", "3", "0"], "B",
    "第二行是第一行的2倍；第三行不与第一行成比例，故秩为2。",
    "row-dependence", "两行相关，秩至多2；第一、三行独立，秩至少2。",
    "minor-check", "例如第一、二列构成的子式1·1−2·0=1非零，秩至少2。",
    "找出明显的相关行。", "寻找一个非零二阶子式。", ["矩阵的秩", "行相关性"])
add("hx36-math-first-order-ode", "math.exam.21e0818406c9",
    "初值问题 y'+3y=6、y(0)=1 的解在 x=ln2 处取值多少？",
    ["7/8", "1", "15/8", "2"], "C",
    "解为 y=2−e^(−3x)。在 x=ln2 时 e^(−3x)=1/8，故 y=15/8。",
    "integrating-factor", "乘积分因子e^(3x)得(ye^(3x))'=6e^(3x)，结合初值解出2−e^(−3x)。",
    "equilibrium-plus-transient", "平衡解为2，偏差初值−1按e^(−3x)衰减，指定点得15/8。",
    "求齐次解与常数特解。", "应用初值并代入对数点。", ["一阶线性方程", "积分因子"])
add("hx36-math-resonant-ode", "math.exam.1d4dc7ab8919",
    "方程 y''+4y=cos2x 的一个特解是哪一个？",
    ["cos2x", "x sin2x/4", "x cos2x", "sin2x/2"], "B",
    "右端与齐次解共振；代入可验证 y_p=(x/4)sin2x 满足 y_p''+4y_p=cos2x。",
    "resonance-ansatz", "对共振项取x乘常规试探解，系数取1/4后算子输出cos2x。",
    "direct-differentiation", "令y=x sin2x/4，二阶导加4y后交叉项抵消，剩cos2x。",
    "识别齐次方程含 sin2x、cos2x。", "采用共振特解并代回核对。", ["二阶非齐次线性方程", "共振特解"])
add("hx36-math-resonant-negative", "math.exam.d59b003eda7d",
    "方程 y''−y=e^(−x) 的一个特解是哪一个？",
    ["e^(−x)", "−(x/2)e^(−x)", "(x/2)e^(−x)", "−e^(−x)"], "B",
    "特征根−1与右端指数共振，取 y_p=Cxe^(−x)；代入得到 C=−1/2。",
    "resonant-operator", "P(r)=r²−1，P'(−1)=−2，C=1/P'(−1)=−1/2。",
    "direct-substitution", "y_p=−xe^(−x)/2代入 y''−y 后得到e^(−x)。",
    "检查右端指数是否为特征根。", "用共振公式或直接代入确定系数。", ["特解", "对应齐次方程", "共振"])
add("hx36-math-implicit-derivative", "math.exam.84058ab2e9bb",
    "曲线 x²+xy+y²=7 在点 (1,2) 处的隐函数导数 dy/dx 是多少？",
    ["−4/5", "−5/4", "4/5", "5/4"], "A",
    "隐式求导得2x+y+(x+2y)y'=0，代入(1,2)为4+5y'=0，故 y'=−4/5。",
    "implicit-differentiation", "对x求导得到2x+y+(x+2y)y'=0，解得−4/5。",
    "gradient-tangent", "梯度(4,5)垂直切向量，切线斜率为−4/5。",
    "对含 y 的项使用链式法则。", "代入点坐标并解线性方程。", ["隐函数", "二元函数偏导"])
add("hx36-math-displacement", "math.exam.ceb4bcf4246a",
    "质点速度 v(t)=3t²+1（m/s），从 t=0 运动至 t=2 s。其位移是多少？",
    ["8 m", "9 m", "10 m", "12 m"], "C",
    "位移为速度积分 ∫₀²(3t²+1)dt=[t³+t]₀²=10 m。",
    "velocity-integral", "积分得t³+t，在2处为8+2=10。",
    "separate-components", "3t²项贡献8米，常速度1项贡献2米，总计10米。",
    "确定位移是速度对时间的定积分。", "拆分两项核算。", ["定积分物理应用", "位移"])
add("hx36-math-gravity-asymmetry", "math.exam.0e5b36de4dd9",
    "两点质量分别为 m 和 2m，位于 x=−a 和 x=a（a>0）；原点处合引力场指向何方，大小是多少？",
    ["向左，Gm/a²", "向右，Gm/a²", "为零", "向右，3Gm/a²"], "B",
    "右侧质量2m产生向右场2Gm/a²，左侧m产生向左场Gm/a²，合场向右且大小Gm/a²。",
    "vector-superposition", "两方向相反，大小相减2Gm/a²−Gm/a²=Gm/a²，方向向右。",
    "symmetry-break", "质量不相等打破对称抵消，较大质量一侧主导。",
    "分别求两质量产生的场强大小和方向。", "按向量方向相减。", ["引力模型", "对称性", "场强叠加"])
add("hx36-math-moving-bounds", "math.exam.db85781e4dfc",
    "设 F(x)=∫ₓ^(2x)t dt，求 F'(1)。",
    ["1", "2", "3", "4"], "C",
    "莱布尼茨公式给 F'(x)=2·(2x)−x=3x，因此 F'(1)=3。",
    "Leibniz-rule", "上限贡献4x，下限贡献−x，结果3x。",
    "evaluate-antiderivative", "F(x)=((2x)²−x²)/2=3x²/2，导数3x，在1处为3。",
    "分别处理上限和下限变化。", "用原函数表达式复算。", ["变上限积分求导", "上下限均变化"])
add("hx36-math-permutation-sign", "math.exam.f99711e0ea65",
    "置换矩阵 P 将 I₃ 的三行循环置换一次（1→2、2→3、3→1），det(P) 等于多少？",
    ["−1", "0", "1", "3"], "C",
    "三循环可分解为两个对换，是偶置换，因此行列式为+1。",
    "cycle-parity", "长度3循环的符号为(−1)^(3−1)=+1。",
    "row-swap-count", "完成该循环需要偶数次行交换，行列式符号不变。",
    "将三循环写成对换乘积。", "按交换次数判断置换矩阵行列式符号。", ["置换矩阵", "置换奇偶性"])
add("hx36-math-inverse-concrete", "math.exam.8b6ba0b9a789",
    "矩阵 A=[[2,1],[1,1]] 的逆矩阵是哪一个？",
    ["[[1,−1],[−1,2]]", "[[1,1],[1,2]]", "[[2,−1],[−1,1]]", "不存在"], "A",
    "det(A)=1，按二阶逆矩阵公式交换对角元、非对角元变号，得到[[1,−1],[−1,2]]。",
    "2x2-inverse-formula", "adj(A)=[[1,−1],[−1,2]]且detA=1。",
    "matrix-product-check", "A乘候选矩阵得到单位矩阵，确认其为逆矩阵。",
    "计算行列式。", "构造伴随矩阵并检查乘积。", ["伴随矩阵", "逆矩阵"])
add("hx36-math-matrix-equation-row", "math.exam.36050d277510",
    "矩阵方程 [[1,0],[0,0]]X=B 有解时，B 必须满足什么条件？",
    ["B 的第二行全为0", "B 的第一行全为0", "B 必须是单位矩阵", "B 必须可逆"], "A",
    "左乘矩阵的第二行恒为零，因此 AX 的第二行必为零；B 必须具有零第二行。",
    "row-space-condition", "AX每一列均属于A的列空间，列空间由(1,0)张成，故第二分量为0。",
    "direct-multiplication", "AX=[[X₁₁,X₁₂],[0,0]]，所以B第二行必须全零。",
    "观察系数矩阵的零行。", "直接写出 AX 的行结构。", ["矩阵方程", "相容条件"])
add("hx36-math-vector-representation", "math.exam.9a1731a929ab",
    "将向量 (4,2) 表示为 a(1,1)+b(1,−1)，则 (a,b) 等于多少？",
    ["(3,1)", "(1,3)", "(2,2)", "(4,−2)"], "A",
    "分量方程 a+b=4、a−b=2，相加得2a=6，故 a=3、b=1。",
    "coordinate-equations", "解线性方程组得a=3、b=1。",
    "basis-matrix-inverse", "以两基向量为列组成矩阵，解系数向量得到(3,1)。",
    "按坐标列出方程。", "联立求解并代回核验。", ["向量组线性表示", "坐标"])
add("hx36-math-transpose-product", "math.exam.712e07e16572",
    "对任意可乘矩阵 A、B，矩阵乘积的转置满足哪一恒等式？",
    ["(AB)ᵀ=AᵀBᵀ", "(AB)ᵀ=BᵀAᵀ", "(AB)ᵀ=AB", "(AB)ᵀ=A+B"], "B",
    "矩阵乘积转置时因子次序反转，(AB)ᵀ=BᵀAᵀ。",
    "entrywise-definition", "(AB)ᵀ的(i,j)项为AB的(j,i)项，展开后对应BᵀAᵀ。",
    "dimension-check", "只有反转后BᵀAᵀ的维度为B列数×A行数，与(AB)ᵀ一致。",
    "用矩阵元素定义展开。", "用维数和因子顺序核对。", ["矩阵恒等式", "转置"])
add("hx36-math-nilpotent-rank", "math.exam.90bbbeb58b4a",
    "3×3 矩阵 N 满足 N²=0。其秩最大可能是多少？",
    ["0", "1", "2", "3"], "B",
    "im(N)包含于ker(N)，故 r(N)≤3−r(N)，从而 r(N)≤1.5，秩最大为1。",
    "image-kernel-inclusion", "N²=0意味着N作用于imN为零，imN⊆kerN，推出2r≤3。",
    "rank-nullity", "r+nullity=3且imN⊆kerN，故r≤nullity=3−r，整数最大1。",
    "将 N²=0 改写为像空间包含关系。", "用秩—零度定理得到上界。", ["幂零矩阵", "矩阵的秩"])
add("hx36-math-log-improper", "math.exam.352fcf1392ad",
    "反常积分 ∫₀¹xᵖ ln x dx 在 0 点收敛的参数条件是什么？",
    ["p>−1", "p≥−1", "p<−1", "所有实数 p"], "A",
    "幂次 xᵖ 在0点可积需 p>−1；对数因子只带来缓慢增长，不改变严格幂次门槛。",
    "power-log-test", "令x=e^(−u)，积分尾部等价于 u e^(−(p+1)u)，仅当p+1>0收敛。",
    "integration-by-parts-limit", "原函数边界项 x^(p+1)lnx/(p+1) 在0趋零当且仅当p>−1。",
    "识别对数因子与幂次主导关系。", "检查下端边界极限。", ["反常积分", "对数因子", "敛散性"])
add("hx36-math-endpoint-parameter", "math.exam.a62c828f6537",
    "反常积分 ∫₀¹(1−cos x)/xᵖ dx 在 x=0 附近收敛的条件是什么？",
    ["p<1", "p<2", "p<3", "p>3"], "C",
    "1−cosx∼x²/2，被积函数等价于 x^(2−p)，在0点可积需2−p>−1，即p<3。",
    "Taylor-comparison", "二阶展开化为幂函数积分，收敛条件p<3。",
    "limit-comparison", "比值(1−cosx)/(x²/2)趋于1，故与x^(2−p)同敛散。",
    "求分子在0点的首个非零阶。", "应用幂函数端点积分判据。", ["端点比较", "参数范围"])
add("hx36-math-composite-differential", "math.exam.6dcf2377bdd4",
    "设 f(x,y)=x²+xy，g(t)=f(t+1,eᵗ)。求 g'(0)。",
    ["2", "3", "4", "5"], "C",
    "在 t=0 时 (x,y)=(1,1)，f_x=2x+y=3、f_y=x=1，且 x'=y'=1，故 g'(0)=4。",
    "chain-rule-gradient", "梯度(3,1)与速度(1,1)点积为4。",
    "direct-composition", "g(t)=(t+1)²+(t+1)eᵗ，求导后在0处为2+2=4。",
    "先求 f 的两个偏导。", "用链式法则合成或直接展开求导。", ["全微分", "复合函数求导"])
add("hx36-math-integral-average", "math.exam.4a56bd52caf7",
    "连续函数 f(x)=x² 在区间 [0,3] 上的积分平均值是多少？",
    ["1", "2", "3", "9"], "C",
    "平均值为(1/3)∫₀³x²dx=(1/3)·9=3。",
    "integral-mean", "定积分为9，区间长度3，平均值3。",
    "antiderivative", "[x³/3]₀³=9，除以3得到3。",
    "先算定积分。", "再除以区间长度。", ["定积分平均值", "积分中值"])
add("hx36-math-inertia-count", "math.exam.7af99f485eff",
    "二次型 Q(x,y,z)=x²−2y² 的正、负、零惯性指数分别是多少？",
    ["(1,1,1)", "(1,1,0)", "(2,1,0)", "(1,2,0)"], "A",
    "对角形式有一个正平方项、一个负平方项和一个不出现的变量，惯性指数为(1,1,1)。",
    "canonical-diagonal-form", "系数1为正、−2为负、z方向为零，三指数分别1、1、1。",
    "rank-sign-count", "二次型秩2，正负各一个，余下一个零方向。",
    "读取对角系数符号。", "用秩与正负项计数核对零指数。", ["合同变换", "惯性指数", "规范形"])
add("hx36-math-parameter-integral", "math.exam.8eaf1a6aeb50",
    "设 F(a)=∫₀¹e^(ax)x²dx。求 F'(0)。",
    ["1/5", "1/4", "1/3", "1/2"], "B",
    "可在积分号下求导：F'(a)=∫₀¹x³e^(ax)dx，故 F'(0)=∫₀¹x³dx=1/4。",
    "differentiate-under-integral", "被积函数对a的导数为x³e^(ax)，在a=0积分为1/4。",
    "Taylor-coefficient", "F(a)展开的一次项系数为∫₀¹x³dx=1/4。",
    "对参数求导并检查被积函数。", "代入 a=0 后积分幂函数。", ["含参积分", "积分号下求导"])

# Computer Science 408: 25 current single-question leaves.
add("hx36-cs-tcp-duplicate-ack", "cs408.cn.topic.8679c379d738",
    "TCP接收方收到乱序字节段但缺少当前累计确认号所指的字节时，通常重复发送的累计确认号表示什么？",
    ["下一个按序期望的字节序号", "刚收到乱序段的最后字节", "接收缓存总容量", "连接建立时的初始序号"], "A",
    "TCP累计确认号指向下一个按序期望字节；缺口未填补时可能重复确认同一序号。",
    "cumulative-ack-semantics", "ACK值是下一个期待按序到达的字节编号。",
    "gap-detection", "缺失字节造成序列缺口，乱序段不能推进累计ACK。",
    "区分累计确认与选择确认。", "检查缺口未填补时确认号是否前移。", ["TCP 可靠传输", "累计确认", "乱序段"])
add("hx36-cs-bfs-level-order", "cs408.ds.topic.525fc6e99b95",
    "从源顶点 s 进行 BFS；某顶点 v 首次被发现时的层数是多少？",
    ["从 s 到 v 的最短路径边数", "从 s 到 v 的最小权值和", "v 的编号", "v 的出度"], "A",
    "BFS按非递减层数扩展，首次发现 v 时经过的边数就是无权网络中的最短距离。",
    "queue-layer-invariant", "队列按层先进先出，首次到达层次即最少边数。",
    "induction-on-distance", "第k层由第k−1层首次扩展，故所有更短路径已先检查。",
    "利用队列的层次顺序。", "说明更短路径若存在会更早发现。", ["广度优先搜索", "层次", "无权最短路"])
add("hx36-cs-dijkstra-settle", "cs408.ds.topic.a52e1bedea58",
    "Dijkstra算法从未确定的顶点中选出暂定距离最小的顶点 u 后，标准算法通常对 u 做什么？",
    ["将 u 的最短距离确定并松弛其出边", "立即删除 u 及所有邻边", "把所有其他距离设为0", "重新初始化全部路径"], "A",
    "在边权非负前提下，当前最小暂定距离不会再被更短路径改写，可将u标记确定并进行松弛。",
    "greedy-invariant", "非负边保证未确定点不能经更远路径回到更短距离。",
    "relaxation-step", "确定u后尝试用dist[u]+w(u,v)改进其邻接点。",
    "应用非负权下的贪心性质。", "说明确定点之后的边松弛步骤。", ["Dijkstra", "顶点确定", "松弛"])
add("hx36-cs-prim-total", "cs408.ds.topic.b66f6167354e",
    "三顶点连通带权网络的边权为 w(A,B)=1、w(B,C)=2、w(A,C)=4。最小生成树总权值是多少？",
    ["2", "3", "5", "7"], "B",
    "取权值最小的 AB、BC 两边即可连接全部顶点且不成环，总权值为3。",
    "cut-choice", "Prim逐步选取连接树与外部的最小边，依次权值1和2。",
    "edge-subset-enumeration", "三种两边组合总权分别3、5、6，最小为3。",
    "选择两条连接三个顶点的边。", "比较候选生成树总权值。", ["Prim", "最小生成树", "权值"])
add("hx36-cs-kruskal-total", "cs408.ds.topic.285e8e87a0cf",
    "三顶点连通带权网络的边权为 w(A,B)=1、w(B,C)=2、w(A,C)=3。Kruskal算法得到的最小生成树总权值是多少？",
    ["2", "3", "4", "6"], "B",
    "按权值递增取 AB=1、BC=2，两边已连通三个顶点，总权值3。",
    "sort-and-union", "按1、2、3处理，前两边不成环且已连通，和为3。",
    "spanning-tree-enumeration", "三种两边树权值分别3、4、5，最小为3。",
    "按权值从小到大处理边。", "确认选取两边后已连通并求和。", ["Kruskal", "最小生成树"])
add("hx36-cs-btree-order", "cs408.ds.topic.ee1ca2a45d19",
    "若一棵 B 树的阶 m 定义为结点最多含 m 个孩子，则非根内部结点至少含多少个孩子？",
    ["⌈m/2⌉", "m−1", "2m", "1"], "A",
    "按常见阶 m 定义，非根结点至少有⌈m/2⌉个孩子，根结点另有较弱下界。",
    "B-tree-occupancy", "B树通过最小占用率保持平衡，高度非根节点下界为ceil(m/2)。",
    "order-definition", "阶是最大孩子数，节点孩子数需满足上界m和下界ceil(m/2)。",
    "确认题目采用的阶定义。", "区分根与非根结点下界。", ["B 树", "阶", "结点占用"])
add("hx36-cs-insertion-best", "cs408.ds.topic.60bf2405e5c6",
    "直接插入排序处理已经按非降序排列的 n 个关键字时，时间复杂度通常为多少？",
    ["O(1)", "O(log n)", "O(n)", "O(n²)"], "C",
    "已排序时每个新关键字只需一次边界比较，外层执行 n−1 次，故最好情形为O(n)。",
    "best-case-count", "每轮仅作常数次检查，总操作数与n成正比。",
    "insertion-invariant", "前缀始终有序，下一元素无需向前移动，整体线性扫描。",
    "逐轮分析已排序输入。", "累计 n−1 次常数检查。", ["直接插入排序", "最好时间复杂度"])
add("hx36-cs-mergesort-space", "cs408.ds.topic.b5b80cd56cd5",
    "对 n 个元素的数组实现归并排序，通常用于合并的辅助数组空间复杂度是多少？",
    ["O(1)", "O(log n)", "O(n)", "O(n²)"], "C",
    "数组归并需要存放与输入规模同阶的暂存元素，辅助空间为O(n)。",
    "merge-buffer-size", "归并阶段需要最多n个位置暂存元素。",
    "recurrence-space", "递归栈为O(logn)，但合并缓冲区O(n)占主导。",
    "检查合并操作是否原地完成。", "区分递归栈和辅助数组空间。", ["归并排序", "空间复杂度"])
add("hx36-cs-delete-after-node", "cs408.ds.topic.d5b72e4fbe7b",
    "已知单链表结点 p 及其非空后继 q=p.next。删除 q 只需进行哪种核心指针修改？",
    ["令 p.next=q.next", "从头结点重新搜索 p 的前驱", "反转整个链表", "把 p.next 设为 p"], "A",
    "已知待删结点的前驱p时，绕过q令p.next=q.next即可完成链接删除。",
    "pointer-bypass", "单链表删除通过前驱指针跳过待删结点。",
    "operation-count", "只需常数次指针读取/赋值，时间O(1)。",
    "定位待删结点q的前驱。", "把前驱链接到q的后继。", ["单链表", "删除结点"])
add("hx36-cs-controller-command", "cs408.co.topic.a1e3b44f8513",
    "CPU 要求 I/O 控制器开始一次设备操作时，通常向控制器提供什么？",
    ["操作命令及必要参数", "操作系统源代码", "磁盘目录树", "网络路由协议"], "A",
    "控制器接收设备命令和参数，协调总线与设备执行相应I/O。",
    "control-register-interface", "CPU通过命令/控制寄存器启动控制器操作。",
    "device-command-flow", "设备控制器根据命令参数启动具体设备动作并报告状态。",
    "区分控制器接口与设备数据本身。", "按一次I/O启动过程识别命令输入。", ["I/O 控制器", "命令寄存器"])
add("hx36-cs-data-register", "cs408.co.topic.e31ff79f7b2e",
    "I/O 接口的数据寄存器最主要用于哪项功能？",
    ["暂存 CPU 与外设交换的数据", "保存进程的页表基址", "记录磁盘文件名", "存放路由器转发表"], "A",
    "数据寄存器在接口侧暂存输入或输出数据，状态寄存器和控制寄存器分别承担其他功能。",
    "register-role", "数据寄存器承载具体数据字节/字。",
    "interface-transfer", "CPU或DMA在设备接口处读取/写入数据寄存器完成交换。",
    "区分数据、状态和控制三类寄存器。", "跟踪数据从设备接口进入系统的路径。", ["I/O 接口", "数据寄存器"])
add("hx36-cs-thread-context-switch", "cs408.os.topic.e73a5b633dc7",
    "同一进程内两个线程切换时，与切换到另一进程相比，通常可避免哪项较重的变化？",
    ["切换到另一进程地址空间", "保存当前线程寄存器", "切换程序计数器", "选择下一个可运行线程"], "A",
    "同进程线程共享地址空间，因此线程切换通常不必更换进程页表/地址空间；寄存器等线程上下文仍需切换。",
    "shared-address-space", "同一进程线程共享内存映射，切换时地址空间保持不变。",
    "context-components", "每线程执行现场仍不同，但进程级内存上下文可复用。",
    "区分线程级与进程级上下文。", "判断页表/地址空间是否需要切换。", ["上下文切换", "线程切换"])
add("hx36-cs-protection-fault", "cs408.os.topic.fac871808395",
    "页表项显示某虚拟页已驻留内存但仅允许读，进程对该页执行写操作时通常发生什么？",
    ["写保护异常", "普通缺页调入", "磁盘寻道完成", "地址转换无需检查权限"], "A",
    "页面已驻留，故不是缺页；写权限不满足，MMU触发保护异常。",
    "present-versus-permission", "页存在位有效而写权限不足，应报保护错误而非调入页面。",
    "access-control", "存储管理硬件检查访问类型与页权限，禁止写操作。",
    "先检查页面是否驻留。", "再检查访问权限与操作类型。", ["虚拟内存", "页面保护", "保护异常"])
add("hx36-cs-ethernet-propagation", "cs408.cn.topic.bcfe8d79341e",
    "共享式以太网要求发送站能够在发送期间检测碰撞。若单程传播时延为 τ，最短帧发送时间至少应满足什么条件？",
    ["小于 τ", "不小于 2τ", "等于 τ/2", "与传播时延无关"], "B",
    "最坏情况下碰撞信息需往返传播约2τ，发送端必须仍在发送才能检测，因此帧发送时间至少2τ。",
    "collision-round-trip", "碰撞最迟约在往返传播时间2τ内反馈。",
    "minimum-frame-time", "发送持续时间≥2τ才确保最远端碰撞在发送结束前被检测。",
    "考虑最远端发送冲突的最坏传播情形。", "比较帧发送时间与往返时延。", ["IEEE 802.3", "最小帧长", "碰撞检测"])
add("hx36-cs-stop-and-wait-utilization", "cs408.cn.topic.d702790fde46",
    "停等协议在一个往返时间内最多允许一个数据帧未确认。若帧发送时间远小于 RTT 且无流水线，链路利用率通常会怎样？",
    ["较低，发送方大部分时间等待确认", "必为100%", "与 RTT 无关", "超过链路物理速率"], "A",
    "发送完一帧后需等待确认才发下一帧；当发送时间相对RTT很短，等待占比大，利用率低。",
    "cycle-time", "一轮耗时约发送时间+RTT，有效发送仅占其中很小部分。",
    "window-size", "停等窗口大小为1，不能填满长传播时延链路。",
    "比较发送时间与确认往返等待时间。", "根据窗口大小判断是否能流水传输。", ["流量控制", "停等协议", "链路利用率"])
add("hx36-cs-gbn-window", "cs408.cn.topic.ab43d1fb00a1",
    "GBN 使用 k=3 位序号，序号空间大小为8。为避免序号回绕歧义，发送窗口最大值是多少？",
    ["3", "4", "7", "8"], "C",
    "GBN发送窗口最大可为序号空间大小减1，即2³−1=7。",
    "GBN-window-bound", "GBN接收窗口为1，发送窗口满足W≤N−1=7。",
    "wraparound-check", "窗口若为8会使序号回绕后旧帧与新帧混淆，故最大7。",
    "计算序号空间N。", "应用GBN的发送窗口边界N−1。", ["GBN", "发送窗口", "序号空间"])
add("hx36-cs-imap-retrieval", "cs408.cn.topic.64b2c1c54cf3",
    "希望邮件长期保存在服务器并在多个设备间同步已读状态和文件夹，通常更适合使用哪种邮件访问协议？",
    ["IMAP", "SMTP", "ARP", "ICMP"], "A",
    "IMAP支持服务器端邮件管理与多客户端同步；SMTP主要用于邮件提交和转发。",
    "protocol-role", "服务器端文件夹和状态同步属于IMAP访问功能。",
    "multi-device-model", "状态保存在服务器，多设备可看到一致的已读和文件夹信息。",
    "区分发送协议与收取/管理协议。", "结合多设备同步需求选协议。", ["电子邮件", "IMAP"])
add("hx36-cs-radix-pass-count", "cs408.ds.topic.b901c6e9e751",
    "对最大值不超过9999的非负四位十进制整数，采用按十进制位的 LSD 基数排序，最多需要处理几趟？",
    ["2", "3", "4", "10"], "C",
    "最多有个位、十位、百位、千位四个有效位置，LSD按位处理共4趟。",
    "digit-count", "9999包含4位十进制数，逐位一趟为4趟。",
    "LSD-order", "从个位到千位依次处理每一位，故需要4趟。",
    "确定最大关键字的位数。", "按最低位优先逐位计数。", ["基数排序", "LSD", "趟数"])
add("hx36-cs-linear-unsuccessful", "cs408.ds.topic.d6d83159a7e3",
    "在含 n 个元素的线性表中进行顺序查找，若查找失败，需要比较多少次关键字？",
    ["1", "⌈log₂n⌉", "n", "n/2"], "C",
    "失败意味着目标不在表中，算法必须检查完全部 n 个元素才能确定不存在。",
    "termination-condition", "只有逐个检查所有位置后才可报告失败。",
    "worst-case-count", "每个元素均需比较一次，总计n次。",
    "判断算法何时能证明目标不存在。", "统计最坏且必需的比较次数。", ["顺序查找", "失败查找"])
add("hx36-cs-binary-linked-list", "cs408.ds.topic.d4f941ee9608",
    "即使链表中的关键字有序，普通单链表也难以像顺序表一样实现 O(log n) 折半查找，主要原因是什么？",
    ["不能按下标 O(1) 随机访问中间结点", "链表结点必须全部相等", "链表不允许比较关键字", "链表只能存放字符"], "A",
    "折半查找每轮需直接定位中间元素；单链表访问该位置需沿指针遍历，不能维持每轮常数定位成本。",
    "random-access-requirement", "二分查找要求常数时间取中点，链表不具备按下标随机访问。",
    "pointer-traversal-cost", "从头走到中点本身需O(n)指针访问，破坏对数查找优势。",
    "识别折半查找每轮需要的操作。", "比较数组与链表的定位成本。", ["查找算法比较", "随机访问"])
add("hx36-cs-parity-even-errors", "cs408.co.topic.e2880988de52",
    "偶校验系统中，若传输期间恰有2个数据位同时翻转，接收端只检查总1的奇偶性时通常会怎样？",
    ["一定检测到两个错误", "可能无法检测到该偶数位错误", "自动定位并纠正两个错误", "必然产生第三个翻转"], "B",
    "两个位同时翻转保持总奇偶性不变，单奇偶校验可能漏检偶数个比特错误。",
    "parity-invariance", "翻转两个位使1的个数变化为偶数，奇偶性保持。",
    "error-detection-limit", "单个校验位只能检测奇数位翻转，不能保证检测偶数位错误。",
    "跟踪总1的奇偶性变化。", "区分检错能力与纠错能力。", ["校验码", "奇偶校验", "检错边界"])
add("hx36-cs-disk-rotation-period", "cs408.co.topic.4497bb39baed",
    "磁盘转速为7200 r/min，假设匀速旋转，一整圈所需时间约为多少？",
    ["4.17 ms", "8.33 ms", "16.67 ms", "60 ms"], "B",
    "7200 r/min=120转/s，单圈时间为1/120 s≈8.33 ms。",
    "rpm-to-rps", "7200除60得120转/秒，周期8.33毫秒。",
    "rotation-period", "每转所需秒数1/120，换算为毫秒约8.33。",
    "把每分钟转数换成每秒转数。", "对转速取倒数并换算单位。", ["磁盘存储器", "旋转周期"])
add("hx36-cs-interrupt-vector", "cs408.co.topic.1401561f15d5",
    "中断控制器提供中断类型号后，处理器通常据此查找什么以转入相应处理程序？",
    ["中断向量表中的入口地址", "文件分配表", "散列表桶", "磁盘分区表"], "A",
    "中断类型号索引中断向量表，取得对应中断服务程序入口。",
    "vector-lookup", "向量号映射到服务例程地址。",
    "control-transfer", "处理器保存现场后按向量入口转移执行中断处理程序。",
    "区分中断号与处理程序地址。", "说明中断向量表的索引作用。", ["程序中断方式", "中断向量"])
add("hx36-cs-dma-path", "cs408.co.topic.720a4a057b28",
    "DMA 进行内存与外设之间的数据块传输时，CPU 相比程序控制 I/O 最主要减少了哪项工作？",
    ["逐字或逐字节搬运数据", "启动传输前配置参数", "处理传输完成中断", "执行用户程序"], "A",
    "DMA控制器在启动后直接搬运数据，CPU无需为每个字或字节执行读写搬运指令。",
    "transfer-agent", "DMA控制器作为总线主设备执行块传输。",
    "CPU-intervention-count", "CPU仍负责配置和完成通知，但不介入每个数据单元的复制。",
    "区分初始化与传输阶段。", "确定 DMA 减少的是逐单元 CPU 搬运。", ["DMA", "直接存储器访问"])
add("hx36-cs-page-fault-sync", "cs408.os.topic.4ac423ec47e2",
    "进程执行一条加载指令时访问不存在的虚拟页并引发缺页异常，该异常相对于当前指令流属于什么？",
    ["同步异常", "异步外部中断", "设备完成中断", "软件定时器"], "A",
    "缺页由当前指令的访存行为直接触发，异常与该指令同步。",
    "fault-causality", "没有这条访存指令就不会发生该缺页，因此是同步事件。",
    "interrupt-versus-exception", "外部设备中断异步到达，缺页异常与当前指令相关联。",
    "找出事件由谁触发。", "按同步异常与异步中断的定义分类。", ["中断与异常", "同步异常", "缺页"])

if len(batch.CODEX_PUBLIC_ORIGINALS) != 50:
    raise RuntimeError(f"batch36_requires_50_unique_targets:{len(batch.CODEX_PUBLIC_ORIGINALS)}")
if len({x["node_code"] for x in batch.CODEX_PUBLIC_ORIGINALS}) != 50:
    raise RuntimeError("batch36_target_nodes_not_unique")

if __name__ == "__main__":
    raise SystemExit(batch.main())
