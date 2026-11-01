"""Batch 40: third distinct item for the next 25 math and 25 mixed 408 leaves."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-39-third-supply"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_39_THIRD_SUPPLY_COMPLETE":
    raise RuntimeError("batch39_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch39_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-40-third-supply"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_39_THIRD_SUPPLY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-40-third-supply"
batch.SUCCESS_STATUS = "BATCH_40_THIRD_SUPPLY_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []

MATH_NODES = [
    "math.exam.58a5d04a7be9", "math.exam.59e1e05f1c94", "math.exam.5af66b782c26",
    "math.exam.609e58acbace", "math.exam.61b15cc0e52c", "math.exam.66f8f7b61188",
    "math.exam.68217a446e4c", "math.exam.6dcf2377bdd4", "math.exam.6df0d75f1b07",
    "math.exam.712e07e16572", "math.exam.71a29108dd89", "math.exam.79c96a83b3ff",
    "math.exam.7af99f485eff", "math.exam.7d287abb612e", "math.exam.7d6f5725a5ab",
    "math.exam.84058ab2e9bb", "math.exam.8b6ba0b9a789", "math.exam.8d8ad14b2a44",
    "math.exam.8eaf1a6aeb50", "math.exam.90bbbeb58b4a", "math.exam.936d8c834760",
    "math.exam.9578b3defcb0", "math.exam.985c26775327", "math.exam.9a1731a929ab",
    "math.exam.9bda63607d7e",
]
CS408_NODES = [
    "cs408.cn.topic.a44bb362c00a", "cs408.cn.topic.aa75b70d073a",
    "cs408.cn.topic.ab43d1fb00a1", "cs408.cn.topic.b6784d3204ca",
    "cs408.cn.topic.b8e94d7c568d", "cs408.cn.topic.bcfe8d79341e",
    "cs408.cn.topic.cbb222f5869a", "cs408.cn.topic.d702790fde46",
    "cs408.cn.topic.d8296e4021b3", "cs408.cn.topic.e09a336289ea",
    "cs408.cn.topic.e567ffa4c80f", "cs408.cn.topic.f4c8aca76dcc",
    "cs408.cn.topic.fdfe51b5d88a", "cs408.co.topic.0d0cb51a5974",
    "cs408.co.topic.0eeff5219603", "cs408.co.topic.0efeb18eeae7",
    "cs408.co.topic.1401561f15d5", "cs408.co.topic.236ea41712f9",
    "cs408.co.topic.279ec6c06fe1", "cs408.co.topic.27cae453c58a",
    "cs408.co.topic.2d6ca0bb88eb", "cs408.co.topic.2f989eb277fa",
    "cs408.co.topic.3b93ddd0af00", "cs408.co.topic.3f6ede8e6fb2",
    "cs408.co.topic.4497bb39baed",
]
TARGETS = set(MATH_NODES + CS408_NODES)
eligible = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 2 and ".family." not in row["node_code"]
}
if not TARGETS.issubset(eligible):
    raise RuntimeError(f"batch40_targets_not_exactly_two_eligible:{sorted(TARGETS-set(eligible))}")


def add(req, node, stem, choices, answer, explanation, method1, result1,
        method2, result2, step1, step2, skills):
    if node not in TARGETS:
        raise RuntimeError(f"unexpected_batch40_node:{node}")
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


# Mathematics II: third items use different functions, parameters or operations.
add("hx40-math-hessian-positive", "math.exam.58a5d04a7be9",
    r"函数$f(x,y)=x^2+xy+y^2$在原点的Hessian判别结论是什么？",
    ["严格极大点", "严格极小点", "鞍点", "Hessian退化且不能判别"], "B",
    "Hessian为[[2,1],[1,2]]，特征值为1、3均正，故原点为严格极小点。",
    "Hessian-eigenvalues", "矩阵特征值1、3均正定。",
    "principal-minors", "顺序主子式2>0且行列式3>0，Hessian正定。",
    "求驻点并写出Hessian矩阵。", "检查正定性并判别极值类型。", ["Hessian判别法", "正定极值"])
add("hx40-math-indefinite-integral", "math.exam.59e1e05f1c94",
    r"计算不定积分$\int(3x^2-2x+1)\,dx$。",
    ["$x^3-x^2+x+C$", "$x^3+x^2+x+C$", "$3x^3-2x^2+x+C$", "$x^3-x+1+C$"], "A",
    "逐项积分得到$x^3-x^2+x+C$。",
    "termwise-integration", "3x²积分为x³，−2x积分为−x²，1积分为x。",
    "differentiate-antiderivative", "对候选A求导还原3x²−2x+1。",
    "按积分线性逐项求原函数。", "求导核验所得表达式。", ["不定积分的计算", "线性性质"])
add("hx40-math-double-integral-mass", "math.exam.5af66b782c26",
    r"矩形薄片$D=[0,1]\times[0,2]$的面密度为$\rho(x,y)=1+x$，其总质量是多少？",
    ["2", "5/2", "3", "4"], "C",
    r"质量为$\int_0^1\int_0^2(1+x)\,dy\,dx=2\int_0^1(1+x)dx=3$。",
    "iterated-integral", "先对y积分得2(1+x)，再对x积分为3。",
    "average-density", "区域面积2，平均密度为1.5，质量为3。",
    "用面密度在区域上作二重积分。", "直接积分并以面积乘平均密度复核。", ["二重积分的应用", "薄片质量"])
add("hx40-math-half-disk-polar", "math.exam.609e58acbace",
    r"半圆域$D=\{(x,y):x^2+y^2\le4,\ x\ge0\}$的面积用极坐标计算，结果是多少？",
    [r"$\pi$", r"$2\pi$", r"$4\pi$", r"$\pi/2$"], "B",
    r"极坐标中$-\pi/2\le\theta\le\pi/2,0\le r\le2$，面积积分为$\int_{-\pi/2}^{\pi/2}\int_0^2r\,dr\,d\theta=2\pi$。",
    "polar-jacobian", "半径2的整圆面积4π，取一半得2π。",
    "integral-bounds", "角度区间长度π，径向积分为2，总面积2π。",
    "根据区域确定角度和半径范围。", "记得面积元包含Jacobian因子r。", ["极坐标变换", "积分区域对称性"])
add("hx40-math-monotone-sequence", "math.exam.61b15cc0e52c",
    r"数列$a_n=1-\frac1n$（$n\ge1$）的极限是多少？",
    ["0", "1", "不存在", r"$+\infty$"], "B",
    r"$1/n\to0$，故$a_n\to1$；且数列单调递增并有上界1。",
    "limit-laws", "常数1减去趋于0的数列，极限1。",
    "monotone-bounded", "a_n递增且小于1，极限由显式表达得1。",
    "拆分常数项与趋零项。", "用单调有界性质辅助理解其收敛。", ["数列敛散性", "数列极限"])
add("hx40-math-order-reduction", "math.exam.66f8f7b61188",
    r"初值问题$y''=2y'$，$y(0)=0,y'(0)=1$。求$y(\frac{\ln2}{2})$。",
    ["$1/2$", "1", "2", "$3/2$"], "A",
    "令$p=y'$，则$p'=2p,p(0)=1$，所以$p=e^{2x}$；积分并用$y(0)=0$得$y=(e^{2x}-1)/2$，所求为1/2。",
    "order-reduction", "一阶方程p'=2p解得p=e²ˣ，再积分得到y。",
    "substitution-check", "在x=ln2/2处e²ˣ=2，y=(2−1)/2=1/2。",
    "以y'作为新未知函数降低方程阶数。", "先求y'再积分，并代入两个初值。", ["降阶代换", "初值条件"])
add("hx40-math-amgm-inequality", "math.exam.68217a446e4c",
    r"若正数$a,b,c$满足$abc=1$，则$a+b+c$的最小值是多少？",
    ["1", "2", "3", "4"], "C",
    r"由AM-GM，$(a+b+c)/3\ge\sqrt[3]{abc}=1$，等号在$a=b=c=1$时取得。",
    "AM-GM", "三数算术平均不小于几何平均1。",
    "equality-case", "取a=b=c=1满足约束并取得和3。",
    "对三个正数应用算术几何平均不等式。", "检查等号条件是否可满足约束。", ["不等式的证明", "AM-GM"])
add("hx40-math-composite-differential", "math.exam.6dcf2377bdd4",
    r"设$f(x,y)=x^2+y^2$，$g(t)=f(2t,t^2)$。求$g'(1)$。",
    ["8", "10", "12", "16"], "C",
    "$g(t)=4t^2+t^4$，故$g'(t)=8t+4t^3$，$g'(1)=12$。",
    "chain-rule", "$f_x=2x,f_y=2y$，乘以$x'=2,y'=2t$后在1处为8+4。",
    "explicit-composition", "直接化为4t²+t⁴并求导得12。",
    "先用复合函数链式法则组织导数。", "将表达式展开后直接求导复核。", ["全微分与复合函数求导", "链式法则"])
add("hx40-math-adjugate-2x2", "math.exam.6df0d75f1b07",
    r"矩阵$A=\begin{pmatrix}3&1\\2&1\end{pmatrix}$的伴随矩阵$\operatorname{adj}(A)$是哪一个？",
    [r"$\begin{pmatrix}1&-1\\-2&3\end{pmatrix}$", r"$\begin{pmatrix}1&-2\\-1&3\end{pmatrix}$", r"$\begin{pmatrix}3&-1\\-2&1\end{pmatrix}$", r"$\begin{pmatrix}1&1\\2&3\end{pmatrix}$"], "A",
    "二阶矩阵[[a,b],[c,d]]的伴随矩阵为[[d,−b],[−c,a]]，故结果为[[1,−1],[−2,3]]。",
    "adjugate-formula", "交换主对角元并将非对角元变号。",
    "product-check", "A乘候选A得到[[1,0],[0,1]]=det(A)I，detA=1。",
    "应用二阶伴随矩阵公式。", r"利用$A\operatorname{adj}(A)=\det(A)I$检验。", ["伴随矩阵", "可逆矩阵"])
add("hx40-math-commutator", "math.exam.712e07e16572",
    r"给定$A=\begin{pmatrix}1&1\\0&1\end{pmatrix}$、$B=\begin{pmatrix}1&0\\1&1\end{pmatrix}$，则$AB-BA$等于哪一个矩阵？",
    [r"$\begin{pmatrix}1&0\\0&-1\end{pmatrix}$", "$O$", r"$\begin{pmatrix}0&1\\-1&0\end{pmatrix}$", "$I$"], "A",
    "相乘得AB=[[2,1],[1,1]]、BA=[[1,1],[1,2]]，相减为[[1,0],[0,−1]]。",
    "matrix-products", "逐行乘列分别算出AB和BA。",
    "noncommutativity", "两乘积不相等，差矩阵为对角元1、−1。",
    "分别计算AB与BA。", "按对应元素相减。", ["矩阵恒等式", "矩阵乘法不交换"])
add("hx40-math-jump-discontinuity", "math.exam.71a29108dd89",
    r"函数$f(x)=0$（$x<0$），$f(x)=1$（$x\ge0$）在$x=0$处属于哪类间断？",
    ["可去间断", "跳跃间断", "无穷间断", "连续点"], "B",
    "左极限为0、右极限为1，两个有限单侧极限不等，因此为跳跃间断。",
    "one-sided-limits", "lim左=0而lim右=1。",
    "classification", "两侧极限有限但不相等即跳跃间断。",
    "分别计算左右极限。", "根据单侧极限关系分类。", ["连续性与间断点类型", "跳跃间断"])
add("hx40-math-no-inflection-x4", "math.exam.79c96a83b3ff",
    r"函数$f(x)=x^4$满足$f''(0)=0$。点$x=0$是不是拐点？",
    ["是，二阶导为0必为拐点", "不是，函数在0两侧凹凸性没有改变", "是，函数值为0即可", "无法定义函数"], "B",
    r"$f''(x)=12x^2\ge0$，在0两侧均向上凹，凹凸性不变，所以0不是拐点。",
    "second-derivative-sign", "除0外两侧二阶导均为正。",
    "definition-of-inflection", "拐点要求凹凸性发生改变，单有f''(0)=0不足够。",
    "检查二阶导数在0两侧的符号。", "依据凹凸性改变的定义作判断。", ["曲线拐点", "凹凸性变化"])
add("hx40-math-inertia-example", "math.exam.7af99f485eff",
    r"二次型$Q(x,y,z)=x^2-4y^2+z^2$的正惯性指数、负惯性指数和零惯性指数依次是多少？",
    ["(1,1,1)", "(2,1,0)", "(1,2,0)", "(2,0,1)"], "B",
    "标准对角形式已有两个正平方项、一个负平方项，没有零系数，惯性指数为(2,1,0)。",
    "diagonal-coefficients", "系数1、−4、1中两正一负且全非零。",
    "Sylvester-inertia", "对角二次型直接读出正负零指数。",
    "按平方项系数判断正负方向。", "计数正、负及零系数项。", ["合同变换与规范形", "惯性指数"])
add("hx40-math-partial-x", "math.exam.7d287abb612e",
    r"设$z=x^2y+y^3$，求$\partial z/\partial x$在$(x,y)=(2,1)$处的值。",
    ["2", "4", "7", "12"], "B",
    "对x求偏导时将y视为常数，$z_x=2xy$，代入(2,1)得4。",
    "partial-derivative", r"$\partial(x^2y)/\partial x=2xy$且$y^3$偏导为0。",
    "substitution", "2×2×1=4。",
    "对x求偏导并固定y。", "代入给定点坐标。", ["偏导数的概念与计算", "偏导"])
add("hx40-math-vector-independent", "math.exam.7d6f5725a5ab",
    r"向量$v_1=(1,0,1)$、$v_2=(0,1,1)$、$v_3=(1,1,0)$在$\mathbb R^3$中是否线性无关？",
    ["线性无关", "线性相关且秩为2", "线性相关且秩为1", "无法判断"], "A",
    "以三向量为列组成矩阵，其行列式为−2非零，故三向量线性无关。",
    "determinant", "列矩阵行列式−2≠0。",
    "linear-combination", "解系数齐次方程只有零解。",
    "把向量作为矩阵列向量。", "检验行列式是否为零。", ["向量组线性相关性", "线性无关"])
add("hx40-math-implicit-partial", "math.exam.84058ab2e9bb",
    r"曲面由$F(x,y,z)=x^2+y^2+z^2-3=0$确定，在点$(1,1,1)$附近视$z=z(x,y)$。求$\partial z/\partial x$。",
    ["−1", "0", "1", "2"], "A",
    "隐函数求导得$F_x+F_z z_x=0$；在(1,1,1)处两偏导均为2，因此$z_x=-1$。",
    "implicit-function-theorem", "$z_x=-F_x/F_z=-2/2=-1$。",
    "differentiate-relation", "对x求偏导并保持y固定，解出z_x。",
    "对隐式方程关于x求偏导。", r"代入点坐标并检查$F_z\ne0$。", ["隐函数确定的二元函数偏导数", "隐式偏导"])
add("hx40-math-adjugate-inverse", "math.exam.8b6ba0b9a789",
    r"若$A=\begin{pmatrix}1&2\\3&4\end{pmatrix}$，则$A^{-1}$是哪一个？",
    [r"$\begin{pmatrix}-2&1\\3/2&-1/2\end{pmatrix}$", r"$\begin{pmatrix}4&-2\\-3&1\end{pmatrix}$", r"$\begin{pmatrix}2&-1\\-3/2&1/2\end{pmatrix}$", "$A$不可逆"], "A",
    r"$\det A=−2$，伴随矩阵为[[4,−2],[−3,1]]，除以−2得到选项A。",
    "inverse-formula", r"$A^{-1}=\operatorname{adj}(A)/\det A$。",
    "product-check", "A乘选项A得单位矩阵。",
    "计算行列式和伴随矩阵。", "除以行列式并用矩阵乘积核验。", ["伴随矩阵与逆矩阵", "逆矩阵"])
add("hx40-math-maximal-independent", "math.exam.8d8ad14b2a44",
    "向量$v_1=(1,2,0)$、$v_2=(2,4,0)$、$v_3=(0,1,1)$的秩及一个极大无关组是什么？",
    ["秩2，{v₁,v₃}", "秩3，{v₁,v₂,v₃}", "秩1，{v₁}", "秩2，{v₂,v₃}且v₂,v₃相关"], "A",
    "$v_2=2v_1$，而$v_1,v_3$不成比例，故秩为2，{v₁,v₃}可作极大无关组。",
    "linear-dependence", "$v_2$由$v_1$线性表示，秩至多2。",
    "independent-pair", "$v_1,v_3$不成比例，故独立，秩至少2。",
    "找出明显的倍数关系。", "验证所选两向量独立并确定秩。", ["向量组秩", "极大无关组"])
add("hx40-math-parameter-integral", "math.exam.8eaf1a6aeb50",
    r"设$F(a)=\int_0^1 e^{a x^2}\,dx$，求$F'(0)$。",
    ["0", "$1/3$", "$1/2$", "1"], "B",
    r"在可微条件下对参数求导，$F'(a)=\int_0^1x^2e^{ax^2}dx$，故$F'(0)=1/3$。",
    "differentiate-under-integral", r"$\partial e^{ax²}/\partial a=x²e^{ax²}$。",
    "direct-integral", r"$\int_0^1x²dx=1/3$。",
    "将导数移入积分号并对a求偏导。", "令a=0后计算幂函数积分。", ["含参积分求导", "积分号下求导"])
add("hx40-math-nilpotent-inverse", "math.exam.90bbbeb58b4a",
    r"矩阵$N$满足$N^2=O$。矩阵$I+N$的逆矩阵是什么？",
    ["$I+N$", "$I-N$", "$N$", "不存在"], "B",
    "$(I+N)(I-N)=I-N^2=I$，反向乘积同样为I，因此逆矩阵为$I-N$。",
    "finite-geometric-series", r"幂零条件使几何逆级数$I-N+N²-\cdots$在第二项后截断。",
    "two-sided-product", "左右相乘均为I−N²=I。",
    "利用矩阵乘法展开候选乘积。", "检查左右乘均得到单位矩阵。", ["幂零矩阵", "逆矩阵"])
add("hx40-math-triangle-double-integral", "math.exam.936d8c834760",
    r"计算二重积分$\int_0^1\int_0^{1-x}(x+y)\,dy\,dx$。",
    ["$1/6$", "$1/4$", "$1/3$", "$1/2$"], "C",
    r"内层积分为$\frac12-\frac{x^2}{2}$，再在[0,1]积分得$1/2-1/6=1/3$。",
    "iterated-integration", "先对y积分再对x积分得1/3。",
    "symmetry-and-average", "三角区域面积1/2，x+y平均值2/3，积分为1/3。",
    "按给定上下限完成内层积分。", "对结果作外层积分并复核。", ["二重积分", "三角区域"])
add("hx40-math-optimize-x-ln-x", "math.exam.9578b3defcb0",
    r"函数$f(x)=x-\ln x$在$x>0$上的最小值是多少？",
    ["0", "1", "2", "不存在"], "B",
    "$f'(x)=1-1/x$在x=1变号由负到正，故最小值$f(1)=1$。",
    "critical-point", "唯一驻点x=1且为极小点。",
    "AM-GM-log", "令t=1/x>0或用ln x≤x−1可得x−lnx≥1。",
    "求导并分析导数符号。", "用标准对数不等式对全局下界复核。", ["导数的应用", "最值"])
add("hx40-math-matrix-product", "math.exam.985c26775327",
    r"计算$\begin{pmatrix}1&2\\0&1\end{pmatrix}\begin{pmatrix}2&0\\1&3\end{pmatrix}$。",
    [r"$\begin{pmatrix}4&6\\1&3\end{pmatrix}$", r"$\begin{pmatrix}2&4\\3&1\end{pmatrix}$", r"$\begin{pmatrix}4&3\\1&6\end{pmatrix}$", r"$\begin{pmatrix}3&6\\2&1\end{pmatrix}$"], "A",
    "按行乘列得到第一行(4,6)、第二行(1,3)。",
    "row-column-products", "逐项点积计算四个位置。",
    "dimension-and-check", "结果仍为2×2，乘回任意向量也符合线性变换复合。",
    "按矩阵乘法规则计算各元素。", "核对维数与行列位置。", ["矩阵的运算与变换", "矩阵乘法"])
add("hx40-math-vector-coordinates", "math.exam.9a1731a929ab",
    r"将向量$(2,1,3)$表示为$a(1,0,1)+b(0,1,1)+c(1,1,0)$，则$(a,b,c)$是多少？",
    ["(2,1,0)", "(1,2,1)", "(0,1,2)", "(3,0,1)"], "A",
    "分量方程为a+c=2、b+c=1、a+b=3，解得c=0、a=2、b=1。",
    "coordinate-system", "联立三个坐标方程求出(2,1,0)。",
    "substitution", "2(1,0,1)+1(0,1,1)+0(1,1,0)=(2,1,3)。",
    "逐坐标建立线性方程组。", "代回基向量组合核验。", ["向量组线性表示", "坐标"])
add("hx40-math-eigenvector", "math.exam.9bda63607d7e",
    r"矩阵$A=\begin{pmatrix}4&1\\0&2\end{pmatrix}$属于特征值$\lambda=4$的特征向量所张成的空间是哪一个？",
    [r"$\operatorname{span}\{(1,0)^T\}$", r"$\operatorname{span}\{(0,1)^T\}$", r"$\operatorname{span}\{(1,1)^T\}$", r"$\{0\}$"], "A",
    "解$(A-4I)v=0$得第二分量为0、第一分量任意非零，故特征空间为span{(1,0)}。",
    "nullspace", "$A-4I=[[0,1],[0,-2]]$，要求y=0。",
    "direct-eigenvector", "A(1,0)^T=(4,0)^T=4(1,0)^T。",
    "构造$A-4I$并求其零空间。", "直接代入候选向量核对特征关系。", ["特征值与特征向量", "特征空间"])

# 408: mixed networking and computer-organization targets.
add("hx40-cn-p2p-role", "cs408.cn.topic.a44bb362c00a",
    "在典型P2P应用中，一个普通节点最可能同时承担哪两类角色？",
    ["只发布路由且不运行应用", "既请求资源也向其他节点提供资源", "仅作为DNS根服务器", "只负责物理层信号再生"], "B",
    "P2P节点通常既是资源消费者，也可作为资源提供者。",
    "peer-role", "各对等节点可同时请求和提供服务。",
    "architecture-contrast", "这与只提供服务的中心服务器模型不同。",
    "识别对等通信中节点的对称性。", "对照客户机/服务器角色划分。", ["网络应用模型", "P2P"])
add("hx40-cn-crc-remainder", "cs408.cn.topic.aa75b70d073a",
    "数据位串$M=1101$采用生成位串$G=1011$（次数3）计算CRC。按模2除法，附加的3位余数是多少？",
    ["001", "010", "101", "111"], "A",
    "将M后补3个0得到1101000，用1011作模2长除法，余数为001。",
    "polynomial-division", "1101000异或1011000、0101100、0010110、0001011后余001。",
    "remainder-verification", "把001附加至1101后可被1011整除。",
    "按生成多项式进行异或长除。", "用最终码字整除结果复核余数。", ["差错控制", "CRC模2除法"])
add("hx40-cn-gbn-out-of-order", "cs408.cn.topic.ab43d1fb00a1",
    "GBN接收方当前期待序号6，却收到无差错的序号7帧。按接收窗口大小为1的规则，通常如何处理？",
    ["缓存7并逐帧独立确认", "丢弃7并重复确认最后按序收到的序号5", "把期待序号改为8", "立即重置连接"], "B",
    "GBN接收窗口为1，只接受当前期待序号；失序帧被丢弃并重发对最后按序帧的累计确认。",
    "receiver-window", "期待6时序号7不在大小为1的接收窗口内。",
    "cumulative-ack", "最后按序收到的是5，重复确认可促使发送方重传。",
    "确定接收方当前期待的序号。", "按GBN的接收窗口与累计确认规则处理。", ["后退N帧", "失序帧"])
add("hx40-cn-udp-ports", "cs408.cn.topic.b6784d3204ca",
    "主机收到UDP数据报后，传输层主要依据首部中的哪项信息将数据交给对应应用套接字？",
    ["源与目的端口号", "IP TTL和分片偏移", "以太网FCS", "DNS缓存时间"], "A",
    "UDP端口号用于标识发送和接收端应用进程，实现复用与分用。",
    "demultiplexing", "目的端口号帮助接收主机把数据报交付到正确套接字。",
    "transport-header", "UDP首部包含源端口和目的端口字段。",
    "区分网络层主机地址与传输层进程标识。", "按目的端口完成套接字分用。", ["UDP协议", "端口复用"])
add("hx40-cn-congestion-definition", "cs408.cn.topic.b8e94d7c568d",
    "网络中的拥塞通常最直接地表现为哪种情况？",
    ["网络负载超过部分资源的处理能力，队列增长并可能丢包", "所有链路利用率恒为0", "只有应用层域名无法解析", "每个数据帧自动变成广播"], "A",
    "当到达流量持续超过瓶颈链路或路由器的服务能力时，队列累积、时延升高并可能溢出丢包。",
    "queue-dynamics", "到达率大于服务率时积压队列增长。",
    "resource-bottleneck", "瓶颈缓存有限，积压过大导致丢弃。",
    "比较流量到达率与网络资源服务能力。", "联系队列和缓冲区解释延迟/丢包。", ["拥塞控制", "瓶颈与队列"])
add("hx40-cn-ethernet-min-frame", "cs408.cn.topic.bcfe8d79341e",
    "经典以太网帧从目的MAC地址字段到FCS字段计（不含前导码和帧间隙）的最小长度是多少？",
    ["46字节", "60字节", "64字节", "72字节"], "C",
    "最小帧长为64字节，其中包括4字节FCS；前导码/SFD与帧间隙不计入。",
    "frame-field-sum", "目的地址6+源地址6+类型/长度2+最小数据填充46+FCS4=64。",
    "standard-bound", "以太网碰撞检测最小帧长标准为64字节。",
    "按题设确定帧长统计边界。", "将各字段长度相加核对标准最小值。", ["以太网", "帧格式", "最小帧长"])
add("hx40-cn-stopwait-utilization", "cs408.cn.topic.cbb222f5869a",
    "停等协议中数据帧发送时间为1 ms，题设给出的往返时间RTT为9 ms（ACK发送时间忽略）。若无误码，发送方利用率约为多少？",
    ["5%", "10%", "50%", "90%"], "B",
    "一轮周期约为发送1 ms加等待RTT 9 ms，利用率为1/10=10%。",
    "cycle-time", "每帧有效发送时间1ms，总周期10ms。",
    "utilization-ratio", "1ms/10ms=0.1。",
    "计算停等一轮的发送与等待总时间。", "用有效发送时间除以总周期。", ["停止-等待协议", "链路利用率"])
add("hx40-cn-cumulative-ack", "cs408.cn.topic.d702790fde46",
    "可靠传输协议采用累计确认，且题目约定ACK字段表示接收方下一个期望收到的分组序号。接收方已按序收到10、11、12，下一个期望序号是13。此时ACK字段值是多少？",
    ["10", "12", "13", "14"], "C",
    "题干已明确ACK字段表示下一个期望序号；既然接收方期待13，ACK字段值就是13。",
    "next-expected-semantics", "下一个期望序号为13，因此ACK=13。",
    "sequence-check", "连续收到10至12后，下一个未收到分组为13。",
    "读取题干给定的ACK编号约定。", "直接用下一个期望序号确定ACK字段值。", ["流量控制与可靠传输", "累计确认"])
add("hx40-cn-ftp-port", "cs408.cn.topic.d8296e4021b3",
    "经典FTP服务器默认用于控制连接监听的TCP端口号是多少？",
    ["20", "21", "23", "25"], "B",
    "FTP控制连接默认使用TCP端口21；传统主动模式数据连接通常使用服务器端口20。",
    "well-known-port", "FTP control的知名端口为TCP/21。",
    "control-data-distinction", "端口20与传统主动模式数据连接相关，不是控制端口。",
    "区分控制连接和数据连接。", "选择FTP控制服务的默认知名端口。", ["FTP协议", "控制端口"])
add("hx40-cn-shannon-snr", "cs408.cn.topic.e09a336289ea",
    "按香农公式，带宽4 kHz的理想信道要达到12 kbit/s容量，所需信噪比（线性值）至少是多少？",
    ["3", "7", "8", "15"], "B",
    r"$C=B\log_2(1+S/N)$，故$12/4=3=\log_2(1+S/N)$，得到S/N=7。",
    "solve-shannon", "2³−1=7。",
    "capacity-substitution", "带宽单位相消后频谱效率为3 bit/s/Hz。",
    "代入容量与带宽求频谱效率。", "反解香农公式得到线性信噪比。", ["奈奎斯特与香农定理", "香农容量"])
add("hx40-cn-full-duplex", "cs408.cn.topic.e567ffa4c80f",
    "一条全双工通信链路的定义特征是什么？",
    ["两个方向可以同时传输", "只能单向传输", "双方必须轮流使用同一时隙", "只允许传输控制信号"], "A",
    "全双工支持两个方向同时通信；半双工则双向但不能同时。",
    "direction-concurrency", "两个发送方向在时间上可以重叠。",
    "duplex-classification", "同一链路可同时收发而非轮流占用。",
    "区分方向数和同时性。", "按双向通信是否可并行分类。", ["通信基础", "全双工"])
add("hx40-cn-binary-exponential-backoff", "cs408.cn.topic.f4c8aca76dcc",
    r"采用二进制指数退避的CSMA/CD中，发生第2次碰撞后，按$k=\min(n,10)$且$n$为碰撞次数，随机退避槽数r的候选范围是什么？",
    ["0至1", "0至2", "0至3", "0至7"], "C",
    "第2次碰撞时k=2，退避整数从$[0,2^k-1]=[0,3]$中随机选择。",
    "backoff-window", "n=2所以指数窗口大小为4个整数。",
    "slot-range", "闭区间0..3恰有4个候选槽数。",
    "先按题设求k。", "计算2^k−1并写出闭区间。", ["随机访问MAC", "二进制指数退避"])
add("hx40-cn-window-update", "cs408.cn.topic.fdfe51b5d88a",
    "TCP接收应用从缓冲区读取数据后腾出了空间，接收方要使发送方获知可用接收窗口增大，通常通过什么信息通知？",
    ["在TCP报文中通告更新后的接收窗口rwnd", "修改发送方的拥塞窗口cwnd", "发送ARP应答", "重置TCP序号为0"], "A",
    "接收方通过后续TCP首部中的窗口字段通告新的rwnd，发送端据此更新流量控制上限。",
    "advertised-window", "rwnd由接收方通告并反映可用接收缓存。",
    "window-update", "接收缓存释放后，窗口更新可允许发送方继续发送。",
    "区分由接收方控制的rwnd和由网络拥塞控制的cwnd。", "说明更新窗口如何反馈给发送方。", ["TCP流量控制", "接收窗口"])
add("hx40-co-risc-register-ops", "cs408.co.topic.0d0cb51a5974",
    "在典型load-store型RISC设计中，普通算术逻辑指令的操作数通常来自哪里？",
    ["通用寄存器，访存由load/store指令完成", "任意两个内存地址且不需寄存器", "只来自I/O端口", "只能来自指令计数器"], "A",
    "load-store结构要求算术逻辑操作在寄存器间进行，显式load/store负责内存访问。",
    "instruction-class", "算术指令通常读写寄存器而不直接操作内存操作数。",
    "memory-access", "数据从主存进入寄存器需load，结果写回需store。",
    "区分算术指令与访存指令类别。", "按load-store架构说明数据路径。", ["CISC与RISC", "load-store"])
add("hx40-co-base-displacement", "cs408.co.topic.0eeff5219603",
    "基址寄存器内容为$0x1000$，指令中的位移量为$0x24$。若采用基址加位移寻址，有效地址是多少？",
    ["$0x1000", "$0x1024", "$0x2400", "$0x0FDC"], "B",
    "有效地址为基址加位移：$0x1000+0x24=0x1024$。",
    "effective-address", "基址寄存器值与位移相加。",
    "hex-addition", "$0x1000+0x0024=0x1024$。",
    "写出基址加位移的寻址公式。", "按十六进制相加。", ["寻址方式", "基址加位移"])
add("hx40-co-unsigned-product", "cs408.co.topic.0efeb18eeae7",
    "无符号二进制数$1110_2$与$11_2$的乘积是多少？",
    ["$101010_2$", "$100110_2$", "$11110_2$", "$110011_2$"], "A",
    "$1110_2=14$、$11_2=3$，乘积42，转换为二进制为$101010_2$。",
    "decimal-check", "14×3=42。",
    "binary-partials", r"$1110_2+(1110_2\ll1)=1110_2+11100_2=101010_2$。",
    "把两个因数换成十进制或按部分积计算。", "将结果转换并核对二进制位。", ["整数乘除运算", "无符号乘法"])
add("hx40-co-interrupt-boundary", "cs408.co.topic.1401561f15d5",
    "可屏蔽外部中断被CPU接受后，处理器通常在何时响应并转入中断处理流程？",
    ["执行当前指令到允许的指令边界后", "任意机器周期中间立即破坏指令", "只在系统关机时", "仅在用户写磁盘文件时"], "A",
    "可屏蔽中断通常在当前指令完成后由CPU检查并响应，以维持指令执行的体系结构边界。",
    "instruction-atomicity", "当前指令先完成，保存现场后再转入处理程序。",
    "interrupt-check", "处理器在规定的指令边界检查中断请求与屏蔽状态。",
    "区分异常与可屏蔽外部中断。", "按中断响应边界说明处理顺序。", ["程序中断方式", "中断响应"])
add("hx40-co-big-endian", "cs408.co.topic.236ea41712f9",
    "将32位整数$0x12345678$按大端方式存入按字节编址的内存，最低地址处的字节是什么？",
    ["$0x12$", "$0x34$", "$0x56$", "$0x78$"], "A",
    "大端方式将最高有效字节存放在最低地址，因此首先存放0x12。",
    "byte-order", "大端顺序为12、34、56、78。",
    "address-order", "最低地址对应最高位字节0x12。",
    "把32位字拆分为四个字节。", "按大端地址顺序排列。", ["数据对齐与大小端", "大端"])
add("hx40-co-tlb-miss-present", "cs408.co.topic.279ec6c06fe1",
    "TLB未命中，但页表项显示该虚拟页已在主存且权限允许。通常接下来会发生什么？",
    ["缺页调入磁盘页", "查页表取得物理页号并继续访问", "立即终止进程", "刷新整个磁盘缓存"], "B",
    "TLB未命中只表示快表没有映射；若页表项有效且权限正确，查表后建立/填充TLB并继续。",
    "translation-path", "主存页表给出物理页号，无需磁盘调页。",
    "TLB-vs-page-fault", "快表未命中与页面不在主存是不同事件。",
    "先区分TLB缓存状态和页表有效位。", "按有效页表项完成地址转换。", ["虚拟存储器", "TLB未命中"])
add("hx40-co-address-bus", "cs408.co.topic.27cae453c58a",
    "按字节编址的计算机有20根地址线，忽略保留区域，可直接寻址的字节数是多少？",
    ["64 KiB", "1 MiB", "16 MiB", "20 MiB"], "B",
    "20位地址可表示$2^{20}$个不同字节地址，即1 MiB。",
    "address-count", "地址组合数为2^20。",
    "unit-conversion", "$2^{20}$字节=1 MiB。",
    "计算地址线的不同组合数。", "利用按字节编址把地址数换算成字节容量。", ["总线基本概念与组成", "地址总线"])
add("hx40-co-flash-nonvolatile", "cs408.co.topic.2d6ca0bb88eb",
    "断电后仍能保留所存数据、且通常需要按块擦除后再编程的半导体存储器是哪一种？",
    ["SRAM", "DRAM", "Flash", "CPU寄存器"], "C",
    "Flash为非易失存储器，常见闪存需按页编程、按块擦除。",
    "volatility", "SRAM和DRAM均为易失性，Flash断电保持数据。",
    "erase-granularity", "闪存擦除粒度通常大于写入粒度，常按块擦除。",
    "按断电保持性区分存储器。", "结合编程与擦除粒度识别Flash。", ["半导体存储器", "Flash"])
add("hx40-co-data-bus-transfers", "cs408.co.topic.2f989eb277fa",
    "CPU一次需要读取32位数据，主存数据总线宽度为16位；假定每个总线周期传输一次且无突发，至少需要几个数据传送周期？",
    ["1个", "2个", "4个", "16个"], "B",
    "32位数据需分成两个16位传输单元，因此至少两个总线数据周期。",
    "width-ratio", "32/16=2个总线字。",
    "transfer-accounting", "每周期最多传16位，首周期后仍有16位待传。",
    "比较所需数据宽度与总线宽度。", "计算完成一次读取所需的传送次数。", ["主存与CPU连接", "数据总线"])
add("hx40-co-writeback-dirty", "cs408.co.topic.3b93ddd0af00",
    "Cache采用写回策略时，CPU写命中通常先更新何处；修改后的块何时写回主存？",
    ["先更新Cache，块被替换或按策略回写时再写主存", "每次写命中都立即同时更新主存", "只更新主存而不更新Cache", "写命中时清空整个Cache"], "A",
    "写回策略先修改Cache并置脏位，主存通常在脏块被替换时更新。",
    "policy-definition", "写回与写直达的关键区别是主存更新延迟。",
    "dirty-bit", "脏位记录Cache块与主存副本不一致。",
    "描述写命中时的数据更新位置。", "说明脏块何时需要回写主存。", ["Cache写策略", "写回", "脏位"])
add("hx40-co-isa-compatibility", "cs408.co.topic.3f6ede8e6fb2",
    "两台计算机采用相同指令集体系结构（ISA），但微体系结构实现不同。只要操作系统和程序符合该ISA，通常能够保证什么？",
    ["同一机器指令程序具有体系结构层面的兼容性", "两台机器时钟频率必相同", "Cache容量必须相同", "所有指令执行周期数必须相同"], "A",
    "ISA定义软件可见的指令与状态约定；不同微体系结构可用不同性能实现相同ISA。",
    "interface-contract", "机器码按共同ISA语义解释。",
    "implementation-separation", "流水线、Cache等微体系结构细节可不同而保持指令语义。",
    "区分软件可见接口和内部实现。", "排除频率、Cache和周期数相同的误解。", ["计算机系统层次结构", "ISA", "兼容性"])
add("hx40-co-disk-average-rotation", "cs408.co.topic.4497bb39baed",
    "磁盘转速为6000 r/min，假设匀速旋转且请求到达相位均匀，平均旋转等待时间约是多少？",
    ["2.5 ms", "5 ms", "10 ms", "20 ms"], "B",
    "一圈时间为60/6000秒=10 ms，平均等待半圈，约5 ms。",
    "rotation-period", "6000转/分=100转/秒，周期10ms。",
    "uniform-phase-average", "均匀随机相位的平均等待为半个旋转周期。",
    "先求一整圈时间。", "平均旋转等待为半圈并换算单位。", ["磁盘存储器", "平均旋转延迟"])

if len(batch.CODEX_PUBLIC_ORIGINALS) != 50:
    raise RuntimeError(f"batch40_requires_50_unique_targets:{len(batch.CODEX_PUBLIC_ORIGINALS)}")
actual_nodes = {x["node_code"] for x in batch.CODEX_PUBLIC_ORIGINALS}
if len(actual_nodes) != 50 or actual_nodes != TARGETS:
    raise RuntimeError("batch40_target_nodes_not_exactly_the_selected_25_plus_25")
if len({x["request_id"] for x in batch.CODEX_PUBLIC_ORIGINALS}) != 50:
    raise RuntimeError("batch40_request_ids_not_unique")

if __name__ == "__main__":
    raise SystemExit(batch.main())
