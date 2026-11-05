"""Batch 39: third distinct item for 25 math and 25 networking leaves."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-38-asset-guard-retry"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_38_ASSET_GUARD_RETRY_COMPLETE":
    raise RuntimeError("batch38_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch38_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-39-third-supply"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_38_ASSET_GUARD_RETRY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-39-third-supply"
batch.SUCCESS_STATUS = "BATCH_39_THIRD_SUPPLY_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []

MATH_NODES = [
    "math.calculus.differential.implicit", "math.calculus.limit.infinitesimal",
    "math.calculus.limit.lhopital", "math.calculus.series.geometric",
    "math.exam.0318406f8b47", "math.exam.08a5efb8a98d", "math.exam.0949f5ff08f9",
    "math.exam.0aad93648d60", "math.exam.0bf92dbd942e", "math.exam.0e5b36de4dd9",
    "math.exam.167393e991a4", "math.exam.1d4dc7ab8919", "math.exam.21e0818406c9",
    "math.exam.3504d885999b", "math.exam.352fcf1392ad", "math.exam.36050d277510",
    "math.exam.3b91ad45ab4c", "math.exam.3e373cbe2c92", "math.exam.423bee85b09f",
    "math.exam.4586eb88acb7", "math.exam.4a56bd52caf7", "math.exam.4ea6e9d4fae7",
    "math.exam.51d573e440d0", "math.exam.547ca6df680c", "math.exam.547f1fa49cd2",
]
NETWORK_NODES = [
    "cs408.cn.topic.0a2961dff8db", "cs408.cn.topic.1351211c91cf",
    "cs408.cn.topic.1a141eb77fc0", "cs408.cn.topic.1e611d5e4eb0",
    "cs408.cn.topic.1e841423f29c", "cs408.cn.topic.201ce80c4dd6",
    "cs408.cn.topic.415100bf0700", "cs408.cn.topic.4ca2f6021eeb",
    "cs408.cn.topic.560367fe85a6", "cs408.cn.topic.64b2c1c54cf3",
    "cs408.cn.topic.658f7cffbc1f", "cs408.cn.topic.6bb96577c0c4",
    "cs408.cn.topic.6e5dd5812d0e", "cs408.cn.topic.71ab052ca21b",
    "cs408.cn.topic.7253eabb8454", "cs408.cn.topic.7507d0c4e02a",
    "cs408.cn.topic.76b87a32829d", "cs408.cn.topic.7789c3d9d6f7",
    "cs408.cn.topic.7dfe285bb24b", "cs408.cn.topic.8679c379d738",
    "cs408.cn.topic.8e7e1292d6b4", "cs408.cn.topic.940692c0d533",
    "cs408.cn.topic.9a617d7c8ebe", "cs408.cn.topic.9d2dd646a2ab",
    "cs408.cn.topic.a2e54e0115b9",
]
TARGETS = set(MATH_NODES + NETWORK_NODES)
eligible = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 2 and ".family." not in row["node_code"]
}
if not TARGETS.issubset(eligible):
    raise RuntimeError(f"batch39_targets_not_exactly_two_eligible:{sorted(TARGETS-set(eligible))}")


def add(req, node, stem, choices, answer, explanation, method1, result1,
        method2, result2, step1, step2, skills):
    if node not in TARGETS:
        raise RuntimeError(f"unexpected_batch39_node:{node}")
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


# Mathematics II: new parameters or a different operation from the existing two items.
add("hx39-math-implicit-second-derivative", "math.calculus.differential.implicit",
    "圆 $x^2+y^2=25$ 在上半圆点 $(3,4)$ 附近写成 $y=y(x)$。求该点的二阶导数 $y''$。",
    ["−25/64", "−3/4", "25/64", "−4/25"], "A",
    "两次隐式求导：$x+yy'=0$，再得 $1+(y')^2+yy''=0$；该点 $y'=-3/4$，所以 $y''=−25/64$。",
    "implicit-second-derivative", "代入 y=4、y'=−3/4 得 y''=−(1+9/16)/4=−25/64。",
    "differentiate-circle-curvature", "圆的上半支 y=√(25−x²)，二阶导数在x=3处也是−25/64。",
    "先求一阶导数并在给定点取值。", "再对隐式关系求导一次并代入。", ["隐函数求导", "二阶导数"])
add("hx39-math-exp-second-order", "math.calculus.limit.infinitesimal",
    r"计算极限 $\lim_{x\to0}\frac{e^{2x}-1-2x}{x^2}$。",
    ["1", "2", "4", "不存在"], "B",
    "展开 $e^{2x}=1+2x+2x^2+o(x^2)$，分子主项为 $2x^2$，极限为2。",
    "Taylor-leading-term", "二阶Taylor项(2x)^2/2=2x²。",
    "LHopital-twice", "一次求导后分子2e^{2x}−2、分母2x；再求导得4/2=2。",
    "写出指数函数在0点的二阶展开。", "保留分子首个非零项并与分母比较。", ["等价无穷小替换", "二阶展开"])
add("hx39-math-lhopital-cubic", "math.calculus.limit.lhopital",
    r"利用洛必达法则或等价展开，求 $\lim_{x\to0}\frac{\sin x-x}{x^3}$。",
    ["−1/3", "−1/6", "1/6", "0"], "B",
    r"$\sin x=x−x^3/6+o(x^3)$，故商的极限为−1/6；连续三次使用洛必达也得到该值。",
    "Taylor-expansion", "分子首个非零项为−x³/6。",
    "LHopital-three-times", "连续求导三次后为−cos x/6，x→0得−1/6。",
    "确认分子在x=0处至少消失到二阶。", "求首个非零项或连续求导至非零极限。", ["洛必达法则", "高阶型极限"])
add("hx39-math-alt-geometric-sum", "math.calculus.series.geometric",
    r"求级数 $\frac23-\frac49+\frac8{27}-\frac{16}{81}+\cdots$ 的和。",
    ["2/5", "2/3", "1/5", "6/5"], "A",
    "首项为2/3、公比为−2/3，且公比绝对值小于1，和为 $(2/3)/(1+2/3)=2/5$。",
    "geometric-series-formula", "a=2/3、r=−2/3，S=a/(1−r)=2/5。",
    "partial-sum-limit", "有限和趋于(2/3)(1−(−2/3)^n)/(1+2/3)，极限2/5。",
    "识别首项、公比并判断绝对收敛。", "代入无穷等比级数求和公式。", ["等比级数", "敛散性", "求和"])
add("hx39-math-root-unique", "math.exam.0318406f8b47",
    "方程 $x^5+x-1=0$ 在实数范围内有几个实根？",
    ["0个", "1个", "2个", "5个"], "B",
    "函数导数 $5x^4+1>0$，故严格递增；且两端极限异号，恰有一个实根（并位于(0,1)）。",
    "monotonicity-and-IVT", "严格递增保证至多一个根，f(0)=−1、f(1)=1保证至少一个根。",
    "derivative-sign", "f'(x)>0对所有实数成立，因此根唯一。",
    "先用导数确定函数全局单调性。", "再用端点异号和介值定理证明存在。", ["方程根的存在性与个数", "单调性", "介值定理"])
add("hx39-math-similarity-det", "math.exam.08a5efb8a98d",
    r"若 $B=P^{-1}AP$ 且 $P$ 可逆，已知 $\det(A)=-3$，则 $\det(B)$ 等于多少？",
    ["−3", "3", "−1/3", "不能确定"], "A",
    r"相似矩阵行列式不变：$\det(P^{-1}AP)=\det(P^{-1})\det(A)\det(P)=\det(A)=-3$。",
    "multiplicativity", "det(P⁻¹)det(P)=1，剩余det(A)=−3。",
    "similarity-invariant", "相似变换保持特征多项式及行列式。",
    "利用行列式乘法公式展开。", "说明可逆变换前后的行列式不变。", ["矩阵相似", "行列式不变量"])
add("hx39-math-idempotent-power", "math.exam.0949f5ff08f9",
    r"矩阵 $P$ 满足 $P^2=P$。对任意整数 $n\ge1$，$P^n$ 等于什么？",
    ["$P$", "$P^2$ 但不一定等于 $P$", "$I$", "$O$"], "A",
    "由幂的递推，若 $P^n=P$，则 $P^{n+1}=P^nP=P^2=P$；结合 $n=1$ 得所有正整数幂均为P。",
    "induction", "基例P¹=P，归纳步再乘P仍为P²=P。",
    "idempotent-reduction", "每出现连续两个P即可用P²=P约简到P。",
    "从题设等式识别幂等矩阵。", "用归纳或逐次约简求任意正整数幂。", ["矩阵幂", "幂等矩阵"])
add("hx39-math-rank-dependent-row", "math.exam.0aad93648d60",
    r"矩阵 $A=\begin{pmatrix}1&2&0\\0&1&1\\1&3&1\end{pmatrix}$ 的秩是多少？",
    ["1", "2", "3", "0"], "B",
    "第三行是前两行之和，秩至多2；前两行线性无关，因此秩恰为2。",
    "row-dependence", "R₃=R₁+R₂给出三行相关。",
    "nonzero-minor", "左上二阶子式为1，故秩至少2。",
    "找出行向量之间的关系。", "用非零二阶子式给出秩的下界。", ["矩阵的秩", "行向量相关性"])
add("hx39-math-total-differential-increment", "math.exam.0bf92dbd942e",
    "设 $f(x,y)=x^2+xy$。在点 $(1,2)$ 处，当 $dx=0.02,dy=-0.01$ 时，全微分 $df$ 为多少？",
    ["0.03", "0.05", "0.07", "0.09"], "C",
    "$f_x=2x+y=4$、$f_y=x=1$，所以 $df=4(0.02)+1(-0.01)=0.07$。",
    "partial-derivative-formula", "在(1,2)处梯度为(4,1)，与增量点积为0.07。",
    "linear-approximation", "一阶线性主部4dx+dy=0.08−0.01=0.07。",
    "计算两个偏导数并在给定点取值。", "按全微分线性式代入增量。", ["全微分", "线性近似"])
add("hx39-math-gravity-single-source", "math.exam.0e5b36de4dd9",
    "点质量 $M$ 位于原点。按万有引力场强定义，位置 $x=2a$（$a>0$）处的场强方向与大小是什么？",
    ["向右，$GM/(4a^2)$", "向左，$GM/(4a^2)$", "向左，$GM/(2a^2)$", "为零"], "B",
    "场强指向吸引源原点，距离为2a，大小 $GM/(2a)^2=GM/(4a^2)$。",
    "inverse-square-law", "按反平方定律计算距离平方为4a²。",
    "direction-and-magnitude", "引力场方向指向质量M所在位置，即向左。",
    "计算观察点与质量源之间的距离。", "分别确定方向和反平方大小。", ["引力模型", "反平方定律"])
add("hx39-math-taylor-ln", "math.exam.167393e991a4",
    r"函数 $\ln x$ 在 $x=1$ 处的二阶 Taylor 多项式是哪一个？",
    ["$(x-1)+(x-1)^2/2$", "$(x-1)-(x-1)^2/2$", "$1+(x-1)-(x-1)^2/2$", "$-(x-1)+(x-1)^2/2$"], "B",
    "$f(1)=0,f'(1)=1,f''(1)=-1$，故二阶多项式为 $(x-1)-(x-1)^2/2$。",
    "Taylor-coefficients", "按f(a)、f'(a)、f''(a)/2!逐项求系数。",
    "derivative-check", "对候选多项式在1处核对函数值、一阶和二阶导数。",
    "计算函数在中心点的前两阶导数。", "按Taylor公式写出二阶多项式。", ["泰勒公式", "局部展开"])
add("hx39-math-resonant-ode", "math.exam.1d4dc7ab8919",
    "方程 $y''-4y=e^{2x}$ 的一个特解是哪一个？",
    [r"$e^{2x}$", r"$\frac{x}{4}e^{2x}$", r"$-\frac{x}{4}e^{2x}$", r"$\frac14e^{2x}$"], "B",
    "右端与齐次解中的 $e^{2x}$ 共振，取 $y_p=Cxe^{2x}$；直接代入得 $4C e^{2x}=e^{2x}$，故C=1/4。",
    "resonant-operator", "特征多项式P(r)=r²−4，P'(2)=4，系数为1/P'(2)=1/4。",
    "direct-substitution", "对(x/4)e²ˣ求导两次并代回，结果为e²ˣ。",
    "检查右端指数是否为齐次特征根。", "采用共振试探形式并代回确定系数。", ["二阶非齐次线性微分方程", "共振特解"])
add("hx39-math-separable-ivp", "math.exam.21e0818406c9",
    r"初值问题 $y'=y^2,\ y(0)=1$ 的解在 $x=1/2$ 处的值是多少？",
    ["1", "2", "3", "4"], "B",
    "分离变量得 $-1/y=x+C$；由初值得 $C=-1$，所以 $y=1/(1-x)$，在1/2处为2。",
    "separation", "$dy/y²=dx$积分后得到$-1/y=x-1$。",
    "substitution", "$y=1/(1-x)$满足方程及初值，代入x=1/2得2。",
    "分离变量并积分。", "使用初值定常数，再代入所求点。", ["其他方程", "可分离变量初值问题"])
add("hx39-math-integral-jump-derivative", "math.exam.3504d885999b",
    r"令 $f(t)=1$（$t<0$），$f(t)=2$（$t\ge0$），并定义 $F(x)=\int_0^x f(t)\,dt$。$F'(0)$ 是否存在？",
    ["存在且等于1", "存在且等于2", "存在且等于3/2", "不存在"], "D",
    "左导数为1、右导数为2，二者不相等，因此F在0点不可导。",
    "one-sided-integrals", "$x<0$时F(x)=x，左导数1；x>0时F(x)=2x，右导数2。",
    "FTC-continuity-condition", "被积函数在0处跳跃，直接按差商左右极限也得1与2。",
    "分别写出0左、右侧的积分表达式。", "比较两侧导数是否相等。", ["积分上限变化", "导数连续性", "单侧导数"])
add("hx39-math-log-improper", "math.exam.352fcf1392ad",
    r"反常积分 $\int_e^{\infty}\frac{dx}{x(\ln x)^p}$ 收敛的充要条件是什么？",
    [r"$p>1$", r"$p\ge0$", r"$p<1$", "任意实数p"], "A",
    r"令 $u=\ln x$，积分化为 $\int_1^{\infty}u^{-p}du$，其收敛当且仅当p>1。",
    "substitution", "$du=dx/x$，转成p型无穷积分。",
    "antiderivative-boundary", r"p≠1时原函数为$(\ln x)^{1-p}/(1-p)$，无穷端仅p>1有限。",
    "用对数变量替换消去dx/x。", "应用无穷端p积分判别条件。", ["反常积分敛散性", "对数型比较"])
add("hx39-math-matrix-equation-columns", "math.exam.36050d277510",
    r"矩阵方程 $AX=B$ 中 $A=\begin{pmatrix}1&1\\2&2\end{pmatrix}$，$B=\begin{pmatrix}a&b\\c&d\end{pmatrix}$。该方程有解的充要条件是什么？",
    [r"$a=b=0$", r"$c=2a$ 且 $d=2b$", r"$a=c$ 且 $b=d$", r"$\det B\ne0$"], "B",
    "AX的每一列必须属于A的列空间span{(1,2)}，所以B第二行的每个分量都等于第一行相应分量的2倍。",
    "column-space", "A的列空间为一维直线{(t,2t)}。",
    "column-by-column", "对B的两列分别要求右端兼容，得到c=2a、d=2b。",
    "先确定A的列空间。", "逐列施加右端向量属于列空间的条件。", ["矩阵方程有解条件", "列空间"])
add("hx39-math-difference-solutions", "math.exam.3b91ad45ab4c",
    "若 $y_1,y_2$ 都是同一非齐次线性方程 $y''+p(x)y'+q(x)y=g(x)$ 的解，则 $y_1-y_2$ 满足什么方程？",
    ["$y''+py'+qy=g(x)$", "$y''+py'+qy=0$", "$y'=g(x)$", "必为零函数"], "B",
    "将两解代入方程相减，右端g(x)抵消，差满足对应齐次方程。",
    "linearity-subtraction", "L[y1]−L[y2]=g−g=0。",
    "operator-view", "线性微分算子L作用于差等于差的算子值，结果为0。",
    "对两条方程逐项相减。", "识别右端抵消后得到的齐次方程。", ["线性微分方程解结构", "非齐次方程"])
add("hx39-math-inverse-derivative", "math.exam.3e373cbe2c92",
    "函数$f$在$a$处可导，且$f(a)=b$、$f'(a)=-4$。若反函数在$b$处可导，则$(f^{-1})'(b)$是多少？",
    ["4", "−4", "1/4", "−1/4"], "D",
    "反函数求导公式为$(f^{-1})'(b)=1/f'(a)$，故为−1/4。",
    "inverse-function-rule", "代入a、b对应关系取原导数倒数。",
    "chain-rule", "$f^{-1}(f(x))=x$求导给$(f^{-1})'(b)f'(a)=1$。",
    "写出反函数与原函数导数的关系。", "代入已知斜率并保留负号。", ["反函数及其导数", "链式法则"])
add("hx39-math-convex-secant", "math.exam.423bee85b09f",
    "函数 $f(x)=x^3$ 在 $[0,2]$ 上为凸函数。以固定端点0作割线，$[0,1]$ 与 $[0,2]$ 对应的割线斜率分别是多少？",
    ["1与4，后者较大", "1与2，相等", "3与6，前者较大", "0与0，相等"], "A",
    "斜率$f(x)/x=x^2$；在x=1、2时分别为1、4，随x增大。",
    "direct-slope", "割线斜率分别为(1−0)/(1−0)=1和(8−0)/2=4。",
    "convexity-check", r"$f''(x)=6x\ge0$，斜率递增性质与数值一致。",
    "计算两个端点割线的差商。", "比较数值并用凸性复核趋势。", ["凹凸函数", "割线斜率"])
add("hx39-math-lagrange-log", "math.exam.4586eb88acb7",
    r"对 $f(x)=\ln x$ 在 $[1,e]$ 应用拉格朗日中值定理，满足 $f'(c)=\frac{f(e)-f(1)}{e-1}$ 的 $c$ 是多少？",
    [r"$e-1$", r"$\sqrt e$", "1", "$e$"], "A",
    "平均变化率为1/(e−1)，而f'(c)=1/c，故c=e−1，且1<c<e。",
    "MVT-equation", "1/c=1/(e−1)直接得c=e−1。",
    "interval-check", "e−1约1.718，确在(1,e)内。",
    "计算区间上的平均变化率。", "令导数等于该变化率并检查区间。", ["微分中值定理", "拉格朗日中值定理"])
add("hx39-math-integral-average-sine", "math.exam.4a56bd52caf7",
    r"函数$f(x)=\sin x$在区间$[0,\pi]$上的积分平均值是多少？",
    [r"$1/\pi$", r"$2/\pi$", "1", "2"], "B",
    r"积分平均值为$\frac1\pi\int_0^\pi\sin xdx=2/\pi$。",
    "integrate", "原函数−cosx，端点差为2，再除以区间长度π。",
    "mean-value-formula", "平均值公式等于面积/宽度=2/π。",
    "先计算定积分。", "再除以区间长度。", ["定积分平均值公式", "积分平均值"])
add("hx39-math-double-integral-average", "math.exam.4ea6e9d4fae7",
    r"在矩形$D=[0,1]\times[0,2]$上，函数$f(x,y)=x+2y$的平均值是多少？",
    ["3/2", "2", "5/2", "3"], "C",
    "矩形面积为2；平均值等于中心点值$f(1/2,1)=5/2$，也可由积分除以面积得到。",
    "integral-over-rectangle", r"$\iint_D(x+2y)dA=1+4=5$，除以面积2得5/2。",
    "symmetry-average", "线性函数在矩形上的平均值等于中心点值1/2+2=5/2。",
    "按定义计算二重积分和区域面积。", "相除求平均值并用中心点性质核对。", ["二重积分的概念与性质", "平均值"])
add("hx39-math-population-ode", "math.exam.51d573e440d0",
    "某群体按指数模型$P'=kP$增长，已知$P(0)=100$且$P(2)=200$。在同一模型下$P(4)$是多少？",
    ["200", "300", "400", "800"], "C",
    "指数模型每经过相同的2年时间乘以相同倍数；从100增至200，再经历2年为400。",
    "exponential-solution", "$P(t)=100e^{kt}$，$e^{2k}=2$，故$P(4)=100e^{4k}=400$。",
    "doubling-interval", "已知两年翻倍，下一同长区间再次翻倍。",
    "写出指数增长通解并用P(2)确定增长因子。", "将同一因子应用到第二个2年区间。", ["微分方程的应用", "指数增长模型"])
add("hx39-math-rational-limit", "math.exam.547ca6df680c",
    r"计算极限 $\lim_{x\to2}\frac{x^3-8}{x-2}$。",
    ["4", "8", "12", "16"], "C",
    "$x^3-8=(x-2)(x^2+2x+4)$，约去后在x=2处得12。",
    "factorization", "因式分解后极限为4+4+4=12。",
    "derivative-definition", "该极限等于函数x³在2处导数3·2²=12。",
    "因式分解分子中的立方差。", "约去可去因子并代入。", ["极限计算", "因式分解"])
add("hx39-math-abs-differentiability", "math.exam.547f1fa49cd2",
    "函数$f(x)=|x|$在$x=0$处的性质是哪一项？",
    ["连续且可导", "连续但不可导", "不连续但可导", "既不连续也不可导"], "B",
    "$|x|$在0点左右极限和值均为0，故连续；左右导数分别为−1和1，故不可导。",
    "continuity", "lim(x→0)|x|=0=f(0)。",
    "one-sided-derivatives", "左导数−1，右导数1，不相等。",
    "先检查函数值与极限。", "再比较左右差商极限。", ["导数与微分的概念", "连续性与可导性"])

# Computer Networks: move from recall to a small calculation or protocol trace.
add("hx39-cn-longest-prefix", "cs408.cn.topic.0a2961dff8db",
    r"路由表有三条匹配目的地址$10.1.2.9$的路由：$10.0.0.0/8\to P_1$、$10.1.0.0/16\to P_2$、$10.1.2.0/24\to P_3$。应选择哪个出口？",
    ["$P_1$", "$P_2$", "$P_3$", "按路由表出现顺序随机选择"], "C",
    "三条前缀均匹配，最长前缀/24最具体，因此选$P_3$。",
    "prefix-match", "10.1.2.9符合三个范围，其中最长公共网络前缀为/24。",
    "forwarding-rule", "IP转发采用最长前缀匹配选择最具体路由。",
    "逐条确认目的地址是否匹配前缀。", "在匹配项中选前缀长度最大者。", ["路由器组成与功能", "最长前缀匹配"])
add("hx39-cn-hidden-terminal", "cs408.cn.topic.1351211c91cf",
    "无线局域网中，站点A和C彼此听不到，但都能与接入点B通信；A、C同时向B发送可能发生碰撞。哪种机制可帮助缓解该隐藏终端问题？",
    ["RTS/CTS预约信道", "DNS递归查询", "TCP三次握手", "ARP免费公告"], "A",
    "RTS/CTS使发送方先预约，接收方CTS可通知隐藏站点暂缓发送。",
    "hidden-node-topology", "A、C互相不可侦听，载波侦听不能避免二者同时发往B。",
    "virtual-carrier-sense", "CTS携带持续时间信息，使周边站点设置NAV。",
    "确定冲突发生在共同接收点B。", "说明控制帧如何使隐藏站点感知信道预约。", ["无线局域网", "隐藏终端", "RTS/CTS"])
add("hx39-cn-fiber-immunity", "cs408.cn.topic.1a141eb77fc0",
    "在强电磁干扰环境中，以下哪种导向传输介质通常最不受电磁干扰影响？",
    ["非屏蔽双绞线", "同轴电缆", "光纤", "无线电波"], "C",
    "光纤以光信号传输，不依赖导体中的电信号，通常不受电磁干扰影响。",
    "transmission-medium-physics", "光纤传输载体是光而非电流。",
    "guided-medium-classification", "光纤属于导向介质且对外部电磁噪声免疫。",
    "区分电信号介质和光信号介质。", "结合题设的电磁干扰选择介质。", ["传输介质", "光纤", "抗电磁干扰"])
add("hx39-cn-qam-rate", "cs408.cn.topic.1e611d5e4eb0",
    "某16-QAM系统每个信号符号携带4 bit，符号率为2400 Baud。忽略编码开销，数据率是多少？",
    ["2400 bit/s", "4800 bit/s", "9600 bit/s", "38400 bit/s"], "C",
    r"每符号$\log_2 16=4$ bit，故比特率为2400×4=9600 bit/s。",
    "constellation-bits", "16个可区分状态需要4位二进制选择。",
    "baud-times-bits", "2400符号/s×4 bit/符号=9600 bit/s。",
    "计算每个符号携带的比特数。", "乘以符号率并标注单位。", ["编码与调制", "QAM", "比特率"])
add("hx39-cn-network-edge", "cs408.cn.topic.1e841423f29c",
    "在互联网体系中，通常运行用户应用程序并作为通信端点的设备属于哪一部分？",
    ["网络边缘的端系统", "只负责逐跳转发的核心路由器", "链路层交换芯片", "物理传输介质"], "A",
    "端系统位于网络边缘并运行应用程序；路由器和链路构成转发基础设施。",
    "architecture-role", "用户主机产生或消费应用数据，是通信端点。",
    "forwarding-versus-endpoint", "核心路由器转发分组而非运行最终用户应用端点。",
    "区分应用端点和中间转发设备。", "按设备在网络体系中的位置和职责判断。", ["网络概念组成与功能", "端系统"])
add("hx39-cn-unknown-unicast", "cs408.cn.topic.201ce80c4dd6",
    "二层交换机在某VLAN内收到单播帧，但目的MAC地址不在转发表中。通常如何处理该帧？",
    ["仅丢弃该帧", "向该VLAN除入端口外的其他端口泛洪", "发送给默认网关后不再查表", "改写目的MAC为交换机地址"], "B",
    "未知单播通常在所属VLAN内泛洪到除接收端口外的其他端口。",
    "forwarding-table-miss", "目的MAC没有表项，交换机无法确定唯一出口。",
    "VLAN-scoped-flood", "交换机在相同VLAN范围泛洪，但不从入端口回送。",
    "识别目的地址查表未命中。", "应用未知单播的VLAN内泛洪规则。", ["以太网交换机", "未知单播"])
add("hx39-cn-http-cookie", "cs408.cn.topic.415100bf0700",
    "HTTP本身通常不在协议中保存多个请求之间的会话状态。网站常用哪种机制在后续请求中携带会话标识？",
    ["Cookie", "ARP缓存", "以太网FCS", "IP TTL"], "A",
    "HTTP请求相互独立；服务器可通过Set-Cookie让客户端在后续请求中携带Cookie标识状态。",
    "statelessness", "协议请求默认不自动保留应用会话状态。",
    "cookie-roundtrip", "服务器发Set-Cookie，浏览器后续请求回送Cookie。",
    "区分HTTP协议状态与应用层会话管理。", "跟踪Cookie在响应和后续请求中的往返。", ["WWW 与 HTTP", "无状态", "Cookie"])
add("hx39-cn-udp-guarantees", "cs408.cn.topic.4ca2f6021eeb",
    "UDP向应用提供的传输服务不保证什么？",
    ["端口复用", "数据报边界", "可靠交付和按序到达", "进程到进程通信"], "C",
    "UDP提供无连接数据报及端口复用，但不保证可靠交付、重传或按序交付。",
    "service-contract", "UDP没有TCP式确认、重传与序号重组保证。",
    "datagram-interface", "UDP保留数据报边界和端口识别，但可靠性由应用自建。",
    "列出UDP提供的基本接口。", "排除题目所问的不保证属性。", ["传输层功能", "UDP服务"])
add("hx39-cn-intervlan-routing", "cs408.cn.topic.560367fe85a6",
    "两个主机分别处于同一交换机上的不同VLAN；在没有桥接配置的情况下，要进行三层IP通信通常还需要什么？",
    ["路由器或三层交换机执行VLAN间路由", "只增加一条二层trunk即可", "将两个主机MAC改成相同", "关闭所有交换机端口"], "A",
    "不同VLAN是不同二层广播域，跨VLAN通信需三层设备转发。",
    "broadcast-domain-boundary", "二层交换不会跨越VLAN隔离边界转发帧。",
    "network-layer-forwarding", "路由器或三层交换机根据IP网络在VLAN间路由。",
    "识别不同VLAN之间的二层隔离。", "补充完成跨网通信所需的三层转发。", ["VLAN", "VLAN间路由"])
add("hx39-cn-mime", "cs408.cn.topic.64b2c1c54cf3",
    "电子邮件系统为了在邮件中承载图片、音频等非ASCII数据，通常使用哪种扩展机制？",
    ["MIME", "ARP", "RIP", "CSMA/CD"], "A",
    "MIME通过内容类型与编码等机制扩展电子邮件以承载多媒体和附件。",
    "content-type", "MIME标注媒体类型并定义传输编码。",
    "mail-format", "邮件正文可组织为多部分，承载文本和非文本数据。",
    "辨认邮件格式扩展而非网络控制协议。", "说明内容类型与编码如何支持附件。", ["电子邮件", "MIME", "多媒体附件"])
add("hx39-cn-bdp", "cs408.cn.topic.658f7cffbc1f",
    "链路速率为1 Gbit/s，单向传播时延为2 ms。按十进制单位，链路带宽时延积约为多少？",
    ["125 KB", "250 KB", "500 KB", "2000 KB"], "B",
    "带宽时延积=10^9 bit/s×0.002 s=2×10^6 bit=250,000 B，即250 KB。",
    "bits-in-flight", "时延内可发送2,000,000 bit。",
    "unit-conversion", "除以8得到250,000字节，按十进制为250 KB。",
    "把毫秒换算成秒并乘链路速率。", "将在途比特数换算为十进制KB。", ["网络性能指标", "带宽时延积"])
add("hx39-cn-tcp-fin-wait2", "cs408.cn.topic.6bb96577c0c4",
    "TCP主动关闭方发送FIN后收到对端对该FIN的ACK，但尚未收到对端FIN。此时通常处于什么状态？",
    ["CLOSED", "FIN_WAIT_2", "TIME_WAIT", "LISTEN"], "B",
    "主动关闭方的FIN先被确认后进入FIN_WAIT_2，继续等待对端的FIN。",
    "state-transition", "FIN_WAIT_1收到ACK且尚无对端FIN后迁移到FIN_WAIT_2。",
    "four-way-close", "对端仍可发送数据，直到其关闭方向发送FIN。",
    "沿主动关闭方的TCP状态机跟踪本端FIN。", "区分等待对端FIN和TIME_WAIT。", ["TCP连接管理", "FIN_WAIT_2"])
add("hx39-cn-sr-ack-sliding", "cs408.cn.topic.6e5dd5812d0e",
    "选择重传发送方当前发送基序号为5，序号6的帧已收到独立ACK但序号5未确认。发送窗口基序号通常会怎样？",
    ["立即移到7", "仍为5，待5确认后再越过已确认的6滑动", "移到6且丢弃5", "回到0"], "B",
    "SR可缓存失序确认，但发送窗口基序号只越过连续已确认序号；5未确认时仍停在5。",
    "selective-ack-state", "ACK6只标记6已确认，不填补5的空缺。",
    "base-advance-condition", "基序号需要当前base=5也确认后才能连续前移。",
    "区分单帧确认和窗口基序号。", "判断未确认的最早帧对窗口滑动的约束。", ["选择重传", "发送窗口", "独立确认"])
add("hx39-cn-icmp-ttl", "cs408.cn.topic.71ab052ca21b",
    "IPv4分组的TTL在途中减至0并被路由器丢弃时，路由器通常向源主机返回哪类ICMP消息？",
    ["Echo Reply", "Time Exceeded", "Redirect", "Address Mask Reply"], "B",
    "TTL耗尽对应ICMP Time Exceeded，traceroute利用该响应探测逐跳路径。",
    "ttl-processing", "每个路由器转发前递减TTL，变为0时丢弃。",
    "icmp-type", "TTL超时的错误报告为ICMP时间超过。",
    "跟踪TTL在逐跳转发中的变化。", "将TTL耗尽映射到对应ICMP差错类型。", ["ARP / DHCP / ICMP", "ICMP", "TTL"])
add("hx39-cn-dns-recursion", "cs408.cn.topic.7253eabb8454",
    "客户端向本地DNS服务器发出递归查询时，该服务器通常应如何响应？",
    ["只返回一个上级服务器地址并立即结束", "代替客户端继续查询并返回最终答案或解析失败", "把查询广播给所有终端", "返回域名对应的MAC地址"], "B",
    "递归查询要求被询问服务器代为完成解析并返回最终结果或错误。",
    "query-semantics", "递归请求的服务器承担后续查询工作。",
    "iterative-contrast", "只给转介地址是迭代式响应的典型行为。",
    "区分递归查询与迭代转介。", "说明本地解析器最终应返回的结果。", ["DNS 系统", "递归查询"])
add("hx39-cn-bit-stuffing", "cs408.cn.topic.7507d0c4e02a",
    "采用标志比特串01111110定界的比特组帧方法中，为避免数据误含标志模式，数据字段连续出现5个1后发送方通常插入什么？",
    ["插入一个0", "插入一个1", "删除全部5个1", "立即结束当前帧"], "A",
    "比特填充规则在数据中连续5个1之后插入0，接收方再删除该填充0。",
    "flag-prevention", "插入0可阻止数据形成标志中的连续六个1。",
    "receiver-destuff", "接收端识别五个1后的填充0并移除。",
    "识别帧标志中的危险比特模式。", "按比特填充规则插入并说明接收端反操作。", ["数据链路层功能与组帧", "比特填充"])
add("hx39-cn-ipv6-no-broadcast", "cs408.cn.topic.76b87a32829d",
    "IPv6不使用IPv4式广播地址。需要向一个链路上的一组指定接口发送数据时，通常使用什么地址机制？",
    ["多播", "任意IPv4广播", "MAC源地址替代", "TCP端口号"], "A",
    "IPv6以多播支持向接口组发送，不定义IPv4式链路广播。",
    "addressing-model", "IPv6组播地址标识一组接收接口。",
    "broadcast-contrast", "IPv6协议没有广播地址语义。",
    "辨认IPv6中一对多通信的地址类型。", "区分多播与广播机制。", ["IPv6", "多播"])
add("hx39-cn-subnet-network-address", "cs408.cn.topic.7789c3d9d6f7",
    "IPv4地址192.168.1.130/26所属子网的网络地址是什么？",
    ["192.168.1.0", "192.168.1.64", "192.168.1.128", "192.168.1.192"], "C",
    "/26每个子网块大小为64；最后一段130落在128至191区间，网络地址为192.168.1.128。",
    "block-size", "256−192=64，子网边界为0、64、128、192。",
    "bitwise-mask", "130与掩码255.255.255.192按位与得128。",
    "根据前缀长度求子网块大小。", "定位地址所在区间或按位与掩码。", ["子网划分", "网络地址", "CIDR"])
add("hx39-cn-ipv4-df-mtu", "cs408.cn.topic.7dfe285bb24b",
    "路由器收到一个长度1500字节的IPv4分组，出口MTU为1000字节，且分组DF标志置1。按IPv4处理规则，路由器通常怎样处理？",
    ["仍直接发送完整分组", "分片后转发", "丢弃并返回ICMP需要分片类差错", "改用TCP重传"], "C",
    "分组超过出口MTU且DF=1禁止分片，路由器丢弃并返回需要分片的ICMP差错。",
    "MTU-condition", "1500>1000，单个链路帧不能承载该分组。",
    "DF-semantics", "DF置位禁止路由器分片，因此不能按片转发。",
    "比较分组长度与出口MTU。", "结合DF位选择分片或差错处理。", ["网络层功能", "IPv4分片", "MTU"])
add("hx39-cn-tcp-fast-retransmit", "cs408.cn.topic.8679c379d738",
    "经典TCP Reno发送方收到3个重复ACK后，通常会采取哪项动作？",
    ["等待连接超时后才重传", "立即快速重传最早未确认段", "立刻关闭连接", "把累计ACK改写为对端通告窗口"], "B",
    "三个重复ACK表明后续数据已到达而中间段可能丢失，Reno触发快速重传而不等待RTO。",
    "duplicate-ack-signal", "重复ACK说明有序号间隙但网络仍在传送后续段。",
    "fast-retransmit-rule", "经典快速重传门限为三个重复ACK。",
    "解释重复ACK反映的接收序列状态。", "按Reno规则判断触发的恢复动作。", ["TCP可靠传输", "快速重传"])
add("hx39-cn-bgp-path-vector", "cs408.cn.topic.8e7e1292d6b4",
    "BGP在不同自治系统之间传播可达性信息时，通常采用哪类路由信息和策略？",
    ["路径向量并结合自治系统路径与策略", "只按物理距离选择最短链路", "完全忽略自治系统边界", "仅广播MAC地址表"], "A",
    "BGP是域间路径向量协议，通告包含AS路径等属性，并允许按策略选路。",
    "route-attribute", "AS_PATH记录经过的自治系统序列。",
    "interdomain-policy", "域间路由选择不仅由链路距离决定，还受管理策略影响。",
    "区分域内链路状态和域间自治系统路由。", "识别路径向量属性及策略性选路。", ["路由协议", "BGP", "路径向量"])
add("hx39-cn-congestion-avoidance", "cs408.cn.topic.940692c0d533",
    "TCP处于拥塞避免阶段且一个RTT内无丢包时，拥塞窗口通常近似增加多少？",
    ["约1 MSS/ACK", "约1 MSS/RTT", "每个ACK减半", "固定变为接收窗口大小"], "B",
    "加性增大使拥塞避免阶段约每个RTT增加1 MSS。",
    "additive-increase", "每个ACK增加约MSS²/cwnd，合计一个RTT约增加1 MSS。",
    "window-growth", "与慢启动每RTT指数增长不同，拥塞避免近似线性增长。",
    "区分拥塞避免和慢启动的增长形态。", "按加性增大规则写出每RTT的窗口增量。", ["TCP拥塞控制", "拥塞避免", "加性增大"])
add("hx39-cn-cdma-code", "cs408.cn.topic.9a617d7c8ebe",
    "CDMA允许多个用户共享同一频带并在时间上重叠发送，接收端主要依据什么区分用户信号？",
    ["各用户分配的扩频码", "不同的以太网MAC地址前缀", "专用TCP端口", "IP分片偏移量"], "A",
    "CDMA以不同扩频码区分用户，接收端使用相应码相关解扩。",
    "multiple-access-resource", "CDMA分配码资源而非独占时隙或频带。",
    "correlation", "匹配扩频码的相关器提取目标用户信号。",
    "比较码分与频分、时分的资源划分方式。", "说明接收端按码分离用户。", ["信道划分 MAC", "CDMA", "扩频码"])
add("hx39-cn-encapsulation", "cs408.cn.topic.9d2dd646a2ab",
    "发送端把应用数据逐层交给传输层、网络层和链路层时，各层通常如何处理数据单元？",
    ["每层可添加本层控制信息形成封装", "每层必须删除所有上层内容", "只有物理层添加HTTP头", "网络层直接将数据写入文件系统"], "A",
    "协议栈发送过程通过逐层封装添加首部（部分还加尾部）；接收端按层解封装。",
    "layer-service", "每层把上层PDU作为本层数据并附加自身控制信息。",
    "receiver-reversal", "接收端反向移除各层封装并上交载荷。",
    "按发送方向追踪应用数据下行。", "区分封装与解封装方向。", ["网络分层与参考模型", "封装"])
add("hx39-cn-split-horizon", "cs408.cn.topic.a2e54e0115b9",
    "距离向量路由中，路由器R从邻居N学到到目的地D的路由。采用水平分割时，R通常如何向N通告该目的地？",
    ["仍以原距离通告给N", "不向N通告该路由，或按规则通告为不可达", "把下一跳改为N", "广播到所有物理网络且不带目的地"], "B",
    "水平分割避免把从某邻居学到的路由再通告回该邻居，以减少环路。",
    "learned-from-neighbor", "该路由的下一跳来源为N，回告N会诱发错误反向路径。",
    "loop-prevention", "抑制回告降低距离向量环路和计数到无穷风险。",
    "确定R学习路由的来源邻居。", "应用不向来源邻居回告的规则。", ["路由算法", "距离向量", "水平分割"])

if len(batch.CODEX_PUBLIC_ORIGINALS) != 50:
    raise RuntimeError(f"batch39_requires_50_unique_targets:{len(batch.CODEX_PUBLIC_ORIGINALS)}")
actual_nodes = {x["node_code"] for x in batch.CODEX_PUBLIC_ORIGINALS}
if len(actual_nodes) != 50 or actual_nodes != TARGETS:
    raise RuntimeError("batch39_target_nodes_not_exactly_the_25_math_and_25_network_nodes")
if len({x["request_id"] for x in batch.CODEX_PUBLIC_ORIGINALS}) != 50:
    raise RuntimeError("batch39_request_ids_not_unique")

if __name__ == "__main__":
    raise SystemExit(batch.main())
