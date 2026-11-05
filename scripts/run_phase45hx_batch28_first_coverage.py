"""First-coverage batch for 50 previously empty H-X knowledge nodes."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

source = ROOT / "storage/quality-audits/phase45hx-20261011/batch-27-evidence-retry"
checkpoint = json.loads((source / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_27_EVIDENCE_RETRY_COMPLETE":
    raise RuntimeError("batch27_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch27_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = source
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-28-first-coverage"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_27_EVIDENCE_RETRY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-28-first-coverage"
batch.SUCCESS_STATUS = "BATCH_28_FIRST_COVERAGE_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = [
    "-k",
    "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy",
]
batch.CODEX_PUBLIC_ORIGINALS = []

pool = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 0
}


def add(request_id, node, stem, options, answer, explanation,
        method_a, result_a, method_b, result_b, step_a, step_b, skills):
    if node not in pool:
        raise RuntimeError(f"target_not_empty_in_batch27:{node}")
    result_a = f"独立路径一（{method_a}）：{result_a}；复核所得答案为 {answer}。"
    result_b = f"独立路径二（{method_b}）：{result_b}；复核所得答案为 {answer}。"
    batch.CODEX_PUBLIC_ORIGINALS.append({
        "request_id": request_id,
        "node_code": node,
        "output": base.choice(
            stem, options, answer, explanation,
            f"independent-check:{method_a}; {method_b} -> {answer}",
        ),
        "derived_answer": answer,
        "method_evidence": [
            {"method": method_a, "result": result_a},
            {"method": method_b, "result": result_b},
        ],
        "explanation_key_steps": [
            f"第一步：{step_a}",
            f"第二步：{step_b}",
        ],
        "option_truth_table": {label: label == answer for label in options},
        "skill_tags": skills,
    })


# Mathematics II: 25 distinct leaf nodes.
add("hx28-math-homogeneous-ode", "math.exam.e1688d59990a",
    "常系数齐次方程 $y''-3y'+2y=0$ 的通解是哪一个？",
    {"A":"$C_1e^x+C_2e^{2x}$", "B":"$C_1e^{-x}+C_2e^{-2x}$", "C":"$C_1\\cos x+C_2\\sin x$", "D":"$C_1+C_2x$"}, "A",
    "特征方程 $r^2-3r+2=(r-1)(r-2)=0$，根为1和2，通解为 $C_1e^x+C_2e^{2x}$。",
    "characteristic-roots", "特征多项式分解为(r−1)(r−2)，给出两个不同实根1和2。",
    "substitution-check", "分别代入 e^x 与 e^{2x}，算子 y''−3y'+2y 均为0，且二解线性无关。",
    "求特征方程并因式分解。", "依据两个不同特征根写出两项指数解。", ["特征方程", "齐次方程通解"])
add("hx28-math-definite-area", "math.exam.b8203539e400",
    "曲线 $y=x^2$、x轴及直线 $x=0,x=2$ 围成的面积是多少？",
    {"A":"2", "B":"$8/3$", "C":"4", "D":"$16/3$"}, "B",
    "区间内 $x^2\\ge0$，面积为 $\\int_0^2x^2dx=[x^3/3]_0^2=8/3$。",
    "definite-integral-area", "由曲线在区间上非负，面积等于函数的定积分。",
    "antiderivative-evaluation", "原函数为 x³/3，端点代入得到8/3。",
    "先确定曲线在区间上位于 x 轴上方。", "计算定积分并代入上下限。", ["定积分求面积", "原函数与上下限"])
add("hx28-math-matrix-determinant", "math.exam.985c26775327",
    "矩阵 $A=\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}$ 的行列式是多少？",
    {"A":"−2", "B":"2", "C":"10", "D":"−10"}, "A",
    "$\\det A=1\\cdot4-2\\cdot3=-2$。",
    "two-by-two-determinant", "按二阶行列式公式 ad−bc 直接计算得到4−6=−2。",
    "row-elimination", "把第二行减去3倍第一行，行列式不变，得到对角元1与−2，乘积为−2。",
    "使用 ad−bc 公式计算。", "用不改变行列式的行变换复核结果。", ["二阶行列式", "行变换"])
add("hx28-math-integral-property", "math.exam.c023f0987a18",
    "计算 $\\int_0^2(x+1)\\,dx$。",
    {"A":"2", "B":"3", "C":"4", "D":"6"}, "C",
    "原函数为 $x^2/2+x$，在0到2上的差为4。",
    "antiderivative", "逐项积分得到 x²/2+x，代入2和0之差为4。",
    "geometric-area", "面积由底2上的直线 y=x+1 形成梯形，两底1和3，面积为2(1+3)/2=4。",
    "先求一个原函数。", "代入上下限相减，并用梯形面积核对。", ["定积分计算", "积分几何意义"])
add("hx28-math-first-order-linear-ode", "math.exam.d17a7d6b708b",
    "初值问题 $y'+y=0,\\ y(0)=1$ 的解在 $x=\\ln2$ 处的值是多少？",
    {"A":"2", "B":"1", "C":"$1/2$", "D":"$1/4$"}, "C",
    "方程解为 $y=e^{-x}$；代入 $x=\\ln2$ 得 $e^{-\\ln2}=1/2$。",
    "separation-of-variables", "分离变量 dy/y=−dx，积分并用 y(0)=1 得 y=e^(−x)。",
    "integrating-factor", "积分因子 e^x 使 (e^xy)'=0，初值给出 y=e^(−x)。",
    "分离变量或乘积分因子求通解。", "使用初值确定常数，再代入 ln2。", ["一阶线性方程", "初值问题"])
add("hx28-math-eigenvalue-trace", "math.exam.9bda63607d7e",
    "矩阵 $A=\\begin{pmatrix}2&0\\\\0&3\\end{pmatrix}$ 的两个特征值之和是多少？",
    {"A":"1", "B":"5", "C":"6", "D":"−1"}, "B",
    "对角矩阵的特征值就是对角元2和3，和为5；也等于矩阵的迹。",
    "diagonal-eigenvalues", "对角矩阵的特征值直接为2、3，求和为5。",
    "trace-eigenvalue-identity", "特征值之和等于迹，迹为2+3=5。",
    "读取对角矩阵的特征值。", "用迹等于特征值和的性质复核。", ["特征值", "迹与特征值关系"])
add("hx28-math-multivariable-extremum", "math.exam.ce32dc737be5",
    "函数 $f(x,y)=x^2+y^2$ 在 $\\mathbb R^2$ 上的最小值是多少？",
    {"A":"−1", "B":"0", "C":"1", "D":"不存在"}, "B",
    "$x^2+y^2\\ge0$，且在 (0,0) 取到0，因此全局最小值为0。",
    "sum-of-squares-bound", "两个平方均非负，函数值至少为0，并能同时取零。",
    "critical-point-hessian", "唯一驻点为(0,0)，Hessian 为 2I 正定，故该点为严格极小点。",
    "利用平方和非负给出下界。", "检查 (0,0) 取到下界。", ["二元函数极值", "正定 Hessian"])
add("hx28-math-adjugate-determinant", "math.exam.6df0d75f1b07",
    "若 $A$ 是 $n\\times n$ 矩阵且 $\\det A=−3$，则 $A\\operatorname{adj}(A)$ 等于什么？",
    {"A":"$−3I$", "B":"$3I$", "C":"$A^{-1}$", "D":"零矩阵"}, "A",
    "伴随矩阵恒等式为 $A\\operatorname{adj}(A)=\\det(A)I$，代入得 $−3I$。",
    "adjugate-identity", "对任意方阵，A adj(A)=det(A)I，直接代入行列式值−3。",
    "cofactor-expansion", "按余子式展开，乘积的对角元为det(A)，非对角元为重复行列式0。",
    "应用伴随矩阵基本恒等式。", "把 det(A)=−3 代入标量单位矩阵。", ["伴随矩阵", "行列式恒等式"])
add("hx28-math-quadratic-form", "math.exam.f29397bf3b27",
    "二次型 $Q(x,y)=2x^2+3y^2$ 在 (1,1) 处的值是多少？",
    {"A":"3", "B":"4", "C":"5", "D":"6"}, "C",
    "代入 x=y=1，得 $Q=2+3=5$。",
    "direct-substitution", "把 x=1、y=1 代入定义，得到2+3=5。",
    "matrix-form", "对应矩阵 diag(2,3)，向量 (1,1) 的二次型值为2+3=5。",
    "按二次型定义逐项代入。", "用矩阵表示 xᵀAx 再核对。", ["二次型", "矩阵表示"])
add("hx28-math-newton-cooling", "math.exam.51d573e440d0",
    "牛顿冷却模型 $T'=-k(T-T_a)$（$k>0$）的平衡温度 $T$ 是多少？",
    {"A":"0", "B":"$T_a$", "C":"$kT_a$", "D":"$T_a/k$"}, "B",
    "平衡状态满足 T'=0，故 $-k(T-T_a)=0$；因 k>0，得到 T=T_a。",
    "equilibrium-derivative", "平衡温度下温度不再变化，令 T′=0 解得T=T_a。",
    "ODE-right-hand-side-zero", "把平衡解代入微分方程右端，唯一使其为零的是环境温度T_a。",
    "平衡意味着状态导数为零。", "解模型右端等于零的代数方程。", ["微分方程应用", "平衡状态"])
add("hx28-math-vector-dependence", "math.exam.7d6f5725a5ab",
    "向量 $v_1=(1,0),v_2=(0,1),v_3=(1,1)$ 满足哪一个线性关系？",
    {"A":"$v_1+v_2-v_3=0$", "B":"$v_1-v_2-v_3=0$", "C":"$v_1+v_2+v_3=0$", "D":"三向量线性无关"}, "A",
    "逐分量相加得 (1,0)+(0,1)−(1,1)=(0,0)，系数不全为0，故三向量线性相关。",
    "componentwise-combination", "按两个分量分别计算，v1+v2恰为v3。",
    "rank-dimension", "三个二维向量必线性相关；显式关系给出非零系数见证。",
    "检验 v1+v2 是否等于 v3。", "得到非平凡线性组合为零。", ["线性相关", "向量组关系"])
add("hx28-math-variable-upper-limit", "math.exam.eac5b4d10863",
    "设 $F(x)=\\int_0^{x^2}t^2\\,dt$，则 $F'(1)$ 等于多少？",
    {"A":"1", "B":"2", "C":"4", "D":"8"}, "B",
    "由变上限积分求导，$F'(x)=(x^2)^2\\cdot2x=2x^5$，故 F'(1)=2。",
    "fundamental-theorem-chain-rule", "上限为x²，代入被积函数得x⁴，再乘上限导数2x。",
    "explicit-antiderivative", "F(x)=x⁶/3，直接求导为2x⁵，在x=1为2。",
    "先应用微积分基本定理与链式法则。", "用显式积分结果求导复核。", ["变限积分", "链式法则"])
add("hx28-math-total-differential", "math.exam.0bf92dbd942e",
    "函数 $f(x,y)=x^2+y^2$ 在 (1,2) 处的全微分中，$dy$ 的系数是多少？",
    {"A":"2", "B":"3", "C":"4", "D":"5"}, "C",
    "$df=f_xdx+f_ydy$，且 $f_y=2y$；在 y=2 处系数为4。",
    "partial-derivative-definition", "全微分中 dy 系数是对 y 的偏导，f_y=2y=4。",
    "linearization", "在(1,2)附近一阶线性项的 y 增量系数同样为4。",
    "分别求两个一阶偏导。", "代入点坐标写出全微分。", ["全微分", "偏导数"])
add("hx28-math-separable-ode", "math.exam.b05d65f2b0c1",
    "微分方程 $y'=xy$ 的通解是哪一个？",
    {"A":"$y=Ce^{x^2/2}$", "B":"$y=Cx^2/2$", "C":"$y=Ce^x$", "D":"$y=C+x^2$"}, "A",
    "分离变量得 dy/y=x dx，积分后 ln|y|=x²/2+C，故 y=Ce^(x²/2)。",
    "separation-and-integration", "把 dy/y 与 x dx 分离并积分得到 ln|y|=x²/2+C。",
    "substitution", "对候选 y 求导得 y'=xy，直接满足方程。",
    "分离变量并分别积分。", "将所得通解代回方程检查。", ["可分离变量", "微分方程通解"])
add("hx28-math-linear-solution-structure", "math.exam.3b91ad45ab4c",
    "对齐次线性微分方程，若 $y_1,y_2$ 都是解，则常数 $c_1y_1+c_2y_2$ 的情形是（）。",
    {"A":"对任意常数 c1,c2 仍是解", "B":"仅 c1=c2=1 时是解", "C":"必为非齐次方程解", "D":"一定不是解"}, "A",
    "线性微分算子满足叠加性，齐次方程 L[y1]=L[y2]=0，因此 L[c1y1+c2y2]=0。",
    "linearity-of-operator", "线性算子可把常数提出并分配到和上，结果为c1·0+c2·0=0。",
    "superposition-principle", "齐次线性微分方程的解集对线性组合封闭。",
    "将线性组合代入线性算子。", "利用两项各自满足齐次方程。", ["线性方程解结构", "叠加原理"])
add("hx28-math-integral-compute", "math.exam.d2336ba379ea",
    "计算 $\\int_0^1(3x^2+1)\\,dx$。",
    {"A":"1", "B":"2", "C":"3", "D":"4"}, "B",
    "原函数为 x³+x，端点差为2。",
    "termwise-antiderivative", "逐项积分得到x³+x，在0到1取差为2。",
    "geometric-area", "曲线3x²+1在区间上的积分可分为3∫x²dx+∫1dx=1+1=2。",
    "对多项式逐项积分。", "代入上下限并用积分线性性复核。", ["定积分", "积分线性性"])
add("hx28-math-double-integral-order", "math.exam.cbd48f6fb174",
    "区域 $0\\le x\\le1,\\ x\\le y\\le1$ 上，积分次序改为先对 x 后对 y 时，积分限应为（）。",
    {"A":"$0\\le y\\le1,0\\le x\\le y$", "B":"$0\\le y\\le1,y\\le x\\le1$", "C":"$0\\le x\\le1,0\\le y\\le x$", "D":"$0\\le y\\le1,0\\le x\\le1$"}, "A",
    "原区域在单位正方形中位于直线 y=x 上方；固定 y 后，x 从0到y，y从0到1。",
    "region-inequalities", "把条件x≤y与0≤x,y≤1按固定y整理，得到0≤x≤y≤1。",
    "geometric-triangle", "该区域是单位正方形上半三角形，水平截线从左边界0到斜边x=y。",
    "先把区域画成 y=x 上方的三角形。", "按固定 y 的水平截线写出 x 的范围。", ["二重积分换序", "区域表示"])
add("hx28-math-second-order-nonhom-ode", "math.exam.1d4dc7ab8919",
    "方程 $y''+y=1$ 的一个常数特解是哪一个？",
    {"A":"0", "B":"1", "C":"−1", "D":"2"}, "B",
    "取常数特解 y=C，则 y''=0，代回得 C=1。",
    "undetermined-constant", "令特解为常数C代入方程，方程左侧化为C，故C=1。",
    "direct-substitution", "将y=1及其零导数代入原式，左侧为1与右侧相等。",
    "选择常数型试探特解。", "代回方程解出并检查 C=1。", ["二阶非齐次方程", "特解"])
add("hx28-math-particular-resonance", "math.exam.d59b003eda7d",
    "方程 $y''-y=e^x$ 的一个特解是哪一个？",
    {"A":"$e^x$", "B":"$xe^x/2$", "C":"$xe^{-x}$", "D":"$e^x/2$"}, "B",
    "右端 e^x 与齐次解共振，设 $y_p=Axe^x$；代入算子得 $2Ae^x=e^x$，所以 A=1/2。",
    "resonant-undetermined-coefficient", "因特征根1对应右端指数，试探解乘x；代入确定系数A=1/2。",
    "operator-application", "计算 (D²−1)(xe^x)=2e^x，因此取其一半得到右端e^x。",
    "识别右端与齐次解共振，修正试探形式。", "代入求出系数并核验。", ["共振特解", "常系数非齐次方程"])
add("hx28-math-implicit-partial", "math.exam.84058ab2e9bb",
    "曲线 $x^2+y^2=25$ 在 (3,4) 处的隐函数导数 $dy/dx$ 是多少？",
    {"A":"$3/4$", "B":"$-3/4$", "C":"$4/3$", "D":"$-4/3$"}, "B",
    "两边对 x 求导得 2x+2y y'=0，代入(3,4) 得 y'=−3/4。",
    "implicit-differentiation", "对约束方程求导并整理 y'=−x/y，代入为−3/4。",
    "tangent-to-circle", "圆在第一象限该点的法向量为(3,4)，切线斜率满足法向量点积为零，得到−3/4。",
    "对 x 与 y 的复合关系同时求导。", "用切线与半径垂直关系独立核对。", ["隐函数求导", "圆的切线斜率"])
add("hx28-math-physics-displacement", "math.exam.ceb4bcf4246a",
    "质点速度为 $v(t)=2t\\,\\mathrm{m/s}$，从 t=0 运动到 t=3 s，位移是多少？",
    {"A":"6 m", "B":"9 m", "C":"12 m", "D":"18 m"}, "B",
    "位移为速度积分 $\\int_0^3 2t\\,dt=[t^2]_0^3=9$ m。",
    "velocity-integral", "对速度函数积分，原函数为t²，端点差为9米。",
    "triangle-area", "速度—时间图是底3高6的三角形，面积也是9米。",
    "位移等于速度对时间的定积分。", "用速度图像下的三角形面积复核。", ["定积分物理应用", "速度与位移"])
add("hx28-math-gravity-symmetry", "math.exam.0e5b36de4dd9",
    "两个相同点质量位于直线 $x=-a$ 与 $x=a$（a>0），观察点在原点。两质量产生的合引力场方向与大小为（）。",
    {"A":"向左且非零", "B":"向右且非零", "C":"为零", "D":"方向无法确定"}, "C",
    "原点到两质量距离相等，单个引力场大小相同而方向相反，向量和为零。",
    "inverse-square-vector-sum", "按万有引力反平方模型，两场大小相等且沿相反方向，合场为零。",
    "symmetry-of-potential", "系统引力势关于原点为偶函数，其在对称点原点的导数为零，场强也为零。",
    "比较两个质量到原点的距离与场强方向。", "用对称势函数的导数核对合场为零。", ["引力模型", "对称性"])
add("hx28-math-ftc-variable-limit", "math.exam.db85781e4dfc",
    "设 $F(x)=\\int_0^x e^{t^2}\\,dt$，则 $F'(1)$ 等于多少？",
    {"A":"1", "B":"e", "C":"$e^2$", "D":"2e"}, "B",
    "由微积分基本定理，$F'(x)=e^{x^2}$，所以 $F'(1)=e$。",
    "fundamental-theorem", "上限为x且被积函数连续，导数直接等于被积函数在x处的值。",
    "difference-quotient", "积分增量除以x增量的平均值在增量趋零时趋向连续被积函数e^(x²)。",
    "确认被积函数连续并使用变上限求导。", "在 x=1 处代入得到 e。", ["变上限积分求导", "微积分基本定理"])
add("hx28-math-permutation-matrix", "math.exam.f99711e0ea65",
    "由 $I_3$ 交换第1、3行得到的置换矩阵，其行列式是多少？",
    {"A":"1", "B":"0", "C":"−1", "D":"3"}, "C",
    "一次交换两行使行列式变号，$\\det I_3=1$，故新行列式为−1。",
    "row-swap-sign", "对单位矩阵实施一次行交换，行列式符号改变为−1。",
    "permutation-parity", "该置换为一个换位，奇置换的符号为−1。",
    "利用行交换对行列式的影响。", "按置换奇偶性独立核对符号。", ["置换矩阵", "行列式符号"])
add("hx28-math-adjugate-inverse", "math.exam.8b6ba0b9a789",
    "若方阵 A 可逆，则 $A^{-1}$ 与伴随矩阵的关系是哪一个？",
    {"A":"$A^{-1}=\\operatorname{adj}(A)/\\det(A)$", "B":"$A^{-1}=\\det(A)\\operatorname{adj}(A)$", "C":"$A^{-1}=A^T$", "D":"$A^{-1}=\\operatorname{adj}(A)$"}, "A",
    "由 $A\\operatorname{adj}(A)=\\det(A)I$，可逆时 det(A) 非零，两边除以 det(A) 得所示公式。",
    "adjugate-identity-rearrangement", "把伴随恒等式两侧左乘A的逆并除以非零行列式，得到公式A。",
    "two-by-two-explicit-inverse", "对一般2×2矩阵显式写出逆矩阵，分母为行列式、分子为伴随矩阵。",
    "写出 A adj(A)=det(A)I。", "使用 det(A)≠0 整理得到逆矩阵公式。", ["伴随矩阵", "逆矩阵公式"])

# Computer Science 408: 25 distinct leaf nodes.
add("hx28-408-threaded-tree-null", "cs408.ds.topic.36d6505de0b4",
    "含 n 个结点的普通二叉树共有多少个空链域？",
    {"A":"n−1", "B":"n", "C":"n+1", "D":"2n"}, "C",
    "共有2n个左右孩子指针，其中非空链域对应树边 n−1 条，空链域数为2n−(n−1)=n+1。",
    "pointer-edge-count", "每个结点有2个指针，共2n；树有n−1条边占用非空指针，余下n+1个为空。",
    "induction-on-node-count", "单结点树有2个空链域；每增加一个结点净增一个空链域，故总数n+1。",
    "先数左右孩子指针总量。", "减去连接树边的非空链域数。", ["线索二叉树", "空链域数量"])
add("hx28-408-cpu-time", "cs408.co.topic.d25446fb51a0",
    "某程序执行 $2\\times10^9$ 条指令，平均 CPI=1.5，CPU 主频为 3 GHz。CPU 执行时间是多少？",
    {"A":"0.5 s", "B":"1 s", "C":"1.5 s", "D":"3 s"}, "B",
    "CPU 时间=指令数×CPI/频率=$2\\times10^9\\times1.5/(3\\times10^9)=1$ s。",
    "instruction-cpi-frequency", "按CPU时间公式计算指令数乘CPI再除以时钟频率，结果1秒。",
    "cycle-count-method", "总时钟周期为3×10^9，除以3GHz的每秒周期数得到1秒。",
    "先求总时钟周期数。", "除以主频换算成秒。", ["CPU性能指标", "CPI与执行时间"])
add("hx28-408-contiguous-fragmentation", "cs408.os.topic.cab5d37c360d",
    "可变分区连续分配在频繁分配和释放后，最典型的空间问题是（）。",
    {"A":"外部碎片", "B":"内部碎片必然消失", "C":"页表过大", "D":"磁盘坏道"}, "A",
    "空闲空间可能分散成许多不连续小块，虽总量足够也无法满足大块请求，这称为外部碎片。",
    "free-hole-layout", "连续分区释放后留下不相邻空洞，较大连续请求可能无法满足。",
    "allocation-unit-analysis", "外部碎片描述分配区之间未使用空间分散，不是块内浪费。",
    "观察空闲区是否连续。", "把分散空洞与块内浪费区分开。", ["连续分配", "外部碎片"])
add("hx28-408-indexed-allocation", "cs408.os.topic.75525cc498b3",
    "文件采用索引分配时，最直接的优点是（）。",
    {"A":"支持按块直接访问", "B":"完全不需要索引块", "C":"文件块必须连续", "D":"只能顺序访问"}, "A",
    "索引块记录文件各数据块地址，系统可由逻辑块号定位对应物理块，因此支持直接访问。",
    "index-block-address-lookup", "索引项给出各逻辑块对应的物理地址，可直接定位指定块。",
    "sequential-versus-random-access", "与链式分配需沿指针遍历不同，索引分配可按索引项随机定位。",
    "说明索引块保存数据块地址。", "由逻辑块号查表定位而无需顺序扫描。", ["文件物理结构", "索引分配"])
add("hx28-408-directory-entry", "cs408.os.topic.a0be294e1416",
    "目录项最基本的作用是（）。",
    {"A":"把文件名与文件控制信息标识关联起来", "B":"保存文件全部数据内容", "C":"执行磁盘调度", "D":"保存进程寄存器现场"}, "A",
    "目录用于组织命名空间，目录项把文件名关联到文件控制块标识或相应元数据入口。",
    "name-to-file-control-mapping", "查找目录项由名字得到文件控制信息入口，而非读取文件全部内容。",
    "namespace-lookup", "目录解析路径组件后定位对应文件对象，体现名称到对象的映射。",
    "区分目录元数据与文件数据区。", "目录项负责名字到文件对象的查找关联。", ["目录管理", "文件名解析"])
add("hx28-408-dma", "cs408.os.topic.d5667813a1e7",
    "DMA 方式中，CPU 通常在传送开始前完成什么工作？",
    {"A":"设置传送参数并启动控制器", "B":"逐字节搬运整个数据块", "C":"替代设备控制器执行I/O", "D":"禁止传送结束中断"}, "A",
    "CPU 配置内存地址、传送方向和长度后启动DMA；数据块搬运由DMA控制器完成，结束时可中断通知CPU。",
    "dma-setup-and-transfer", "CPU配置起始地址、长度等控制信息，随后控制器自主搬运数据块。",
    "cpu-interrupt-overhead", "DMA减少CPU逐字节轮询，传送结束可用中断报告完成。",
    "区分启动配置与实际数据搬运。", "传送完成后控制器通知CPU处理结果。", ["I/O控制方式", "DMA"])
add("hx28-408-sstf-starvation", "cs408.os.topic.ec4f03dc7ff5",
    "SSTF 磁盘调度算法可能产生的主要问题是（）。",
    {"A":"远处请求长期得不到服务", "B":"磁头必定只向一个方向移动", "C":"不能选择最近请求", "D":"不适用于磁盘"}, "A",
    "SSTF 每次优先服务离当前磁头最近的请求，持续到来的近处请求可能使远处请求饥饿。",
    "nearest-request-selection", "最近优先规则可能反复选择新近请求而推迟远端请求。",
    "request-arrival-scenario", "若近处请求不断到达，磁头选择它们，远处请求等待时间可持续增长。",
    "说明SSTF每次选择距离最近的请求。", "构造近处请求不断到达的情形观察饥饿。", ["磁盘调度", "SSTF"])
add("hx28-408-tcpip-application", "cs408.cn.topic.9d2dd646a2ab",
    "TCP/IP 体系结构的应用层大体对应 OSI 参考模型的哪些层？",
    {"A":"应用、表示和会话层", "B":"传输层和网络层", "C":"数据链路层和物理层", "D":"仅表示层"}, "A",
    "TCP/IP 应用层整合了 OSI 的应用层、表示层和会话层功能。",
    "layer-function-mapping", "按两种体系结构的层功能映射，TCP/IP应用层覆盖OSI上三层。",
    "protocol-placement", "HTTP、表示编码及会话服务在TCP/IP中均归入应用层接口范围。",
    "先按OSI上三层列出功能。", "对照TCP/IP模型的应用层聚合关系。", ["网络分层", "OSI与TCP/IP映射"])
add("hx28-408-network-layer-best-effort", "cs408.cn.topic.7dfe285bb24b",
    "关于 IP 网络层提供的服务，正确的是（）。",
    {"A":"尽力而为的数据报交付，不保证端到端可靠性", "B":"保证每个分组按序无差错到达", "C":"保证带宽和时延", "D":"只负责同一主机内进程通信"}, "A",
    "IP 提供无连接、尽力而为的数据报服务；可靠性、按序和流量控制通常由更高层协议处理。",
    "ip-service-model", "IP转发不承诺丢包恢复、顺序或资源预留，符合尽力而为。",
    "transport-layer-contrast", "TCP等传输层协议可补充可靠性，说明这不是IP网络层保证。",
    "明确IP数据报服务的交付边界。", "与传输层可靠机制区分。", ["网络层功能", "IP尽力而为"])
add("hx28-408-rip-hop-limit", "cs408.cn.topic.8e7e1292d6b4",
    "RIP 中度量值 16 通常表示什么？",
    {"A":"可达且距离为16跳", "B":"不可达", "C":"默认路由", "D":"本地直连网络"}, "B",
    "RIP 将最大可用跳数限制为15，度量值16定义为无穷大，表示目的网络不可达。",
    "rip-infinity-metric", "RIP的跳数上限为15，16被协议约定为无穷大。",
    "distance-vector-update", "距离向量更新中收到16即表示该目的不可达，而不是可用16跳。",
    "记住RIP最大有效跳数15。", "把度量16解释为不可达。", ["RIP", "距离向量路由"])
add("hx28-408-tcp-congestion-slow-start", "cs408.cn.topic.b8e94d7c568d",
    "经典 TCP 慢启动阶段，在未达到慢启动阈值且无丢包时，拥塞窗口通常如何增长？",
    {"A":"每个RTT约翻倍", "B":"每个RTT减半", "C":"保持常数", "D":"线性减少"}, "A",
    "慢启动每收到确认便增加窗口，累计到每个 RTT 约翻倍，直至达到阈值或发生拥塞事件。",
    "per-ack-window-growth", "慢启动按确认逐步增大cwnd，一轮往返累计后近似倍增。",
    "round-trip-aggregation", "每个已发送窗口的数据获确认后窗口继续扩大，因此RTT级增长近似指数。",
    "说明确认到达时拥塞窗口增加。", "汇总一个RTT后的增长表现。", ["拥塞控制", "慢启动"])
add("hx28-408-arp-mapping", "cs408.cn.topic.71ab052ca21b",
    "在 IPv4 局域网中，ARP 的主要作用是什么？",
    {"A":"把已知IPv4地址解析为链路层MAC地址", "B":"把域名解析为IPv4地址", "C":"分配动态IP地址", "D":"报告端到端传输错误"}, "A",
    "ARP 在本地链路上查询目标 IPv4 地址对应的 MAC 地址；DNS、DHCP、ICMP分别承担其他功能。",
    "arp-request-reply", "ARP请求广播目标IPv4地址，拥有该地址的主机返回MAC地址。",
    "protocol-role-contrast", "区分DNS名称解析、DHCP配置和ICMP差错报告后，ARP职责是地址到链路地址映射。",
    "确定本地链路发送帧需要的MAC地址。", "通过ARP请求应答完成IPv4到MAC映射。", ["ARP", "协议功能辨析"])
add("hx28-408-router-forwarding-plane", "cs408.cn.topic.0a2961dff8db",
    "路由器的数据平面最主要执行什么工作？",
    {"A":"按转发表将到达分组转发到相应输出接口", "B":"运行所有应用程序", "C":"为主机分配文件句柄", "D":"计算CPU指令CPI"}, "A",
    "数据平面依据转发表查找目的前缀并执行分组转发；路由协议和路由计算属于控制平面。",
    "forwarding-table-lookup", "数据平面读取目的地址对应转发表项并选择输出端口。",
    "control-data-plane-separation", "控制平面形成路由信息，数据平面据此逐包转发。",
    "区分控制平面与数据平面职责。", "按转发表确定输出接口并转发。", ["路由器组成", "数据平面"])
add("hx28-408-csma-cd-backoff", "cs408.cn.topic.f4c8aca76dcc",
    "传统以太网 CSMA/CD 检测到冲突后，通常采用什么机制决定重传等待时间？",
    {"A":"二进制指数退避", "B":"固定永久延迟", "C":"令牌传递", "D":"电路交换"}, "A",
    "冲突后主机按二进制指数退避算法从扩大后的时隙范围随机选取等待时间，再尝试重传。",
    "binary-exponential-backoff", "冲突次数增加时随机退避窗口按二进制指数扩大。",
    "collision-retry-procedure", "发送端先停止并等待随机时隙，再重新竞争信道。",
    "检测冲突后停止当前发送。", "依据退避算法选择随机等待时隙后重传。", ["随机访问MAC", "CSMA/CD"])
add("hx28-408-binary-search-complexity", "cs408.ds.topic.53f56bc6fb55",
    "长度为 n 的有序数组使用二分查找时，最坏时间复杂度是多少？",
    {"A":"$O(1)$", "B":"$O(\\log n)$", "C":"$O(n)$", "D":"$O(n\\log n)$"}, "B",
    "每次比较把候选区间缩小约一半，经过约 $\\log_2 n$ 次后区间为空或命中。",
    "halving-recurrence", "区间规模满足T(n)=T(n/2)+O(1)，递归层数为log₂n。",
    "decision-tree-height", "每次比较提供二分决策，最坏比较次数不超过对数级。",
    "写出每轮候选区间长度约减半。", "计算达到常数规模所需轮数为对数级。", ["时间复杂度", "二分查找"])
add("hx28-408-stack-operations", "cs408.ds.topic.838a22b8d08d",
    "采用数组或链表实现且不考虑扩容成本时，栈顶 push 与 pop 的时间复杂度是（）。",
    {"A":"$O(1)$", "B":"$O(\\log n)$", "C":"$O(n)$", "D":"$O(n^2)$"}, "A",
    "两种操作只更新栈顶位置或首结点指针，不需遍历已有元素，故为 O(1)。",
    "top-pointer-update", "push和pop各自修改栈顶索引或首指针，操作步数为常数。",
    "linked-list-head-operation", "链栈在头部插入或删除节点，同样无需扫描其他节点。",
    "观察操作只涉及栈顶。", "确认不需要移动或遍历其余元素。", ["顺序栈", "栈操作复杂度"])
add("hx28-408-circular-queue-full", "cs408.ds.topic.e26b2753a525",
    "循环队列数组容量为 N，并采用“牺牲一个存储单元”区分空满时，队满条件是哪一个？",
    {"A":"$front=rear$", "B":"$(rear+1)\\bmod N=front$", "C":"$rear=N$", "D":"$front=0$"}, "B",
    "空队列用 front=rear 表示；牺牲一个单元时，rear 的下一个位置追上 front 即为满。",
    "one-slot-reservation", "保留一个空槽后，rear后继等于front时实际元素数达到N−1。",
    "modular-indexing", "用模N更新尾指针，下一位置为(rear+1) mod N，与front相等即满。",
    "写出循环队列中尾指针的下一位置。", "与头指针相等时判为队满。", ["循环队列", "队满条件"])
add("hx28-408-tree-reconstruction", "cs408.ds.topic.21d435b75fbc",
    "在结点关键字互异时，哪组遍历序列能够唯一确定一棵二叉树？",
    {"A":"仅前序和后序", "B":"前序和中序", "C":"仅中序", "D":"仅层序长度"}, "B",
    "前序首元素确定根；中序中根的位置把左右子树区间分开，递归后可唯一重建。",
    "root-and-inorder-split", "前序给出根，中序给出左右子树边界，递归唯一确定结构。",
    "recursive-subproblem", "每次按根划分两种遍历的对应子序列，子问题的根与区间均确定。",
    "从前序序列取得根结点。", "在中序序列定位根并划分左右子树。", ["遍历序列构树", "前序与中序"])
add("hx28-408-preorder", "cs408.ds.topic.56a82ba8b1ba",
    "二叉树的前序遍历访问结点的顺序是（）。",
    {"A":"左子树、根、右子树", "B":"根、左子树、右子树", "C":"左子树、右子树、根", "D":"根、右子树、左子树"}, "B",
    "前序遍历的定义是先访问根，再递归遍历左子树，最后遍历右子树。",
    "preorder-definition", "按先序规则根结点先于其左右子树。",
    "recursive-traversal-order", "递归过程依次调用 visit(root)、traverse(left)、traverse(right)。",
    "确认根访问位置在两棵子树之前。", "再按左子树优先于右子树展开。", ["前序遍历", "二叉树遍历"])
add("hx28-408-bst-inorder", "cs408.ds.topic.62419b290ce1",
    "含互异关键字的二叉搜索树按中序遍历得到的序列是（）。",
    {"A":"严格递增", "B":"严格递减", "C":"层序", "D":"任意顺序"}, "A",
    "BST 左子树关键字小于根，右子树关键字大于根；中序先左、再根、后右，因此严格递增。",
    "bst-order-property", "中序依次访问左子树、根和右子树，与BST大小关系吻合。",
    "induction-on-subtrees", "左右子树的中序序列各自有序且分别小于、大于根，拼接后全局有序。",
    "列出BST的左右关键字不等式。", "按中序次序拼接左右序列与根。", ["二叉搜索树", "中序遍历"])
add("hx28-408-adjacency-matrix", "cs408.ds.topic.f26de897ea89",
    "无向简单图的邻接矩阵 A 具有什么性质？",
    {"A":"A 为对称矩阵且主对角线为0", "B":"A 必为上三角矩阵", "C":"A 的每项都为1", "D":"A 必为反对称矩阵"}, "A",
    "无向边满足 i 与 j 相邻当且仅当 j 与 i 相邻，所以 Aij=Aji；简单图无自环，故对角元为0。",
    "undirected-edge-symmetry", "无向边无方向，矩阵关于主对角线对称。",
    "simple-graph-loop-rule", "简单图不含自环，因此任一顶点到自身的邻接项为0。",
    "将边的对称关系映射到矩阵下标。", "用无自环条件确定主对角线。", ["邻接矩阵", "无向图"])
add("hx28-408-adjacency-list-space", "cs408.ds.topic.0eb5ea0549e9",
    "用邻接表存储含 V 个顶点、E 条边的图，空间复杂度通常为（）。",
    {"A":"$O(V+E)$", "B":"$O(V^2)$ 必然", "C":"$O(E^2)$", "D":"$O(1)$"}, "A",
    "邻接表为每个顶点保存表头，并为边保存邻接结点；存储量与顶点数和边数成正比。",
    "vertex-heads-and-edge-nodes", "V个顶点表头与O(E)条边记录合计O(V+E)。",
    "sparse-graph-representation", "稀疏图中E远小于V²，邻接表避免存储不存在的顶点对。",
    "统计顶点表头数量。", "加上与边数成比例的邻接记录。", ["邻接表", "图存储复杂度"])
add("hx28-408-chaining-load-factor", "cs408.ds.topic.8c073162e98e",
    "采用拉链法处理冲突的散列表中，装填因子 $\\alpha=n/m$ 是否可以大于1？",
    {"A":"可以", "B":"不可以", "C":"仅m=1时不可以", "D":"必须等于1"}, "A",
    "拉链法允许多个关键字链接在同一散列地址的链表中，关键字数 n 可超过表长 m，因此装填因子可大于1。",
    "chain-length-capacity", "每个槽可挂接多项链表结点，槽数不限制总关键字个数。",
    "load-factor-definition", "n/m中n可大于m，故比值可以超过1。",
    "区分槽位数量与冲突链表结点数量。", "用装填因子定义判断其数值范围。", ["散列表拉链法", "装填因子"])
add("hx28-408-max-heap", "cs408.ds.topic.64cda87cdc82",
    "最大堆中，对任一非根结点 x 与其父结点 p，必须满足什么关系？",
    {"A":"key(p)\\ge key(x)", "B":"key(p)\\le key(x)", "C":"key(p)=key(x)", "D":"父结点关键字无约束"}, "A",
    "最大堆的堆序性质要求每个父结点关键字不小于孩子，所以根结点为全堆最大值。",
    "heap-order-invariant", "最大堆定义为父结点关键字不小于任一子结点。",
    "induction-to-root-maximum", "沿父链关键字非增，故任一结点不可能大于根。",
    "写出父子间的堆序约束。", "沿父链推出根结点保存最大关键字。", ["堆", "最大堆性质"])
add("hx28-408-critical-path-duration", "cs408.ds.topic.6d4cb688c2ee",
    "AOE 网表示的工程总工期由什么决定？",
    {"A":"最短路径长度", "B":"最长路径长度", "C":"边数最多的路径", "D":"所有活动时间的平均值"}, "B",
    "各路径上的活动需按先后完成，项目完成时间受最慢路径约束，即关键路径长度。",
    "precedence-constraint", "汇合事件必须等所有前驱活动完成，最长前驱路径决定最早完成时刻。",
    "earliest-event-time", "按拓扑序计算事件最早时间等价于取所有前驱路径长度的最大值。",
    "识别活动之间的先后依赖。", "最晚完成的路径决定工程总时间。", ["关键路径", "AOE网络"])

expected = {spec["node_code"] for spec in batch.CODEX_PUBLIC_ORIGINALS}
if len(batch.CODEX_PUBLIC_ORIGINALS) != 50 or len(expected) != 50:
    raise RuntimeError("batch28_must_target_50_unique_nodes")
if not expected.issubset(pool):
    missing = sorted(expected - set(pool))
    raise RuntimeError(f"batch28_targets_not_empty_in_checkpoint:{missing}")

if __name__ == "__main__":
    raise SystemExit(batch.main())

