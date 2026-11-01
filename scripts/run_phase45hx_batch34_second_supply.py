"""Batch 34: second distinct public question for 50 one-question topics."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-33-retry-two"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_33_RETRY_TWO_COMPLETE":
    raise RuntimeError("batch33_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch33_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-34-second-supply"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_33_RETRY_TWO_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-34-second-supply"
batch.SUCCESS_STATUS = "BATCH_34_SECOND_SUPPLY_COMPLETE"
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


# Mathematics II: a second, different core task for 25 current single-question nodes.
add("hx34-math-extremum-definition", "math.exam.bc1427755983",
    "函数 f 在定义域内点 x₀ 取得局部最大值的定义条件是哪一项？",
    ["存在 δ>0，使 |x−x₀|<δ 的定义域内各点均有 f(x)≤f(x₀)",
     "对所有定义域内 x 都有 f(x)≤f(x₀)", "必须有 f''(x₀)<0", "f 在整个定义域递减"], "A",
    "局部最大值只要求在 x₀ 的某个邻域内不超过 f(x₀)，不要求全局最大，也不要求二阶导数存在。",
    "local-extremum-definition", "按局部最大值定义，只需存在邻域使函数值不超过 f(x₀)。",
    "counterexample-to-global", "局部邻域条件不蕴含全定义域最大或全局单调。",
    "区分局部邻域与全定义域。", "检查定义是否依赖可导或二阶导。", ["局部极值定义", "邻域条件"])
add("hx34-math-convex-secant", "math.exam.423bee85b09f",
    "函数 f(x)=x²。区间 [0,1] 与 [1,2] 上两条割线的斜率相比，正确结论是（）。",
    ["前者为1、后者为3，后者较大", "前者为3、后者为1，前者较大", "两者相等", "后者为0"], "A",
    "斜率分别为 (1−0)/(1−0)=1 与 (4−1)/(2−1)=3；凸函数向右的割线斜率增大。",
    "direct-secant-calculation", "两段斜率按端点函数值计算为1和3。",
    "convex-slope-order", "f''=2>0，斜率随区间右移递增，符合3大于1。",
    "代入四个端点函数值。", "用二阶导数符号核验斜率顺序。", ["凸函数", "割线斜率单调性"])
add("hx34-math-inverse-derivative", "math.exam.3e373cbe2c92",
    "设 f(x)=x³+2x。反函数在 y=3 处的导数 (f⁻¹)'(3) 为多少？",
    ["1/3", "1/5", "3", "5"], "B",
    "f(1)=3 且 f'(1)=3·1²+2=5，故反函数导数为 1/f'(1)=1/5。",
    "inverse-derivative-formula", "x=f⁻¹(3)=1，代入倒数导数公式得1/5。",
    "differentiate-composition", "由 f(f⁻¹(y))=y 求导，f'(1)(f⁻¹)'(3)=1。",
    "先求满足 f(x)=3 的 x。", "对复合恒等式求导并代入。", ["反函数", "反函数求导"])
add("hx34-math-limit-cosine", "math.exam.547ca6df680c",
    "求极限 lim(x→0) (1−cos 2x)/x²。",
    ["0", "1", "2", "4"], "C",
    "利用 1−cos u∼u²/2，取 u=2x，分子∼2x²，极限为2。",
    "standard-trigonometric-limit", "将 u=2x 代入 (1−cos u)/u²→1/2，再乘4得2。",
    "Taylor-expansion", "cos2x=1−2x²+o(x²)，商的极限为2。",
    "作变量代换 u=2x。", "用二阶展开核对系数。", ["三角函数极限", "等价无穷小"])
add("hx34-math-taylor-third-order", "math.exam.c1948d9cc280",
    "求极限 lim(x→0) [eˣ−1−x−x²/2]/x³。",
    ["0", "1/6", "1/2", "1"], "B",
    "eˣ 的 Taylor 展开为 1+x+x²/2+x³/6+o(x³)，故商趋于1/6。",
    "Taylor-coefficient", "三阶项系数为1/3!=1/6。",
    "lHopital-three-times", "连续求导至分子三阶导趋于1，分母三阶导为6，商为1/6。",
    "展开指数函数至三阶。", "检查余项除以 x³ 趋于0。", ["Taylor 展开", "等价无穷小"])
add("hx34-math-curvature-radius", "math.exam.f67ee0d0080c",
    "曲线 y=x² 在原点处的曲率半径是多少？",
    ["2", "1", "1/2", "0"], "C",
    "曲率 κ=|y''|/(1+y'²)^(3/2)。原点 y'=0、y''=2，故 κ=2，曲率半径 ρ=1/κ=1/2。",
    "curvature-formula", "代入曲率公式得κ=2，半径为其倒数1/2。",
    "osculating-circle-radius", "抛物线顶点曲率半径为 1/(2a)，此处 a=1，故1/2。",
    "先求一阶和二阶导数。", "区分曲率与曲率半径并取倒数。", ["曲率", "曲率半径"])
add("hx34-math-inflection-shift", "math.exam.79c96a83b3ff",
    "函数 f(x)=x³+3x² 的拐点横坐标是多少？",
    ["−1", "0", "1", "不存在"], "A",
    "f''(x)=6x+6，在 x=−1 变号；对应函数点为拐点，横坐标−1。",
    "second-derivative-sign", "二阶导数零点为−1且线性变号。",
    "concavity-intervals", "x<−1 时凹、x>−1 时凸，凹凸性改变于−1。",
    "求二阶导数并解零点。", "检查零点两侧符号变化。", ["拐点", "凹凸性"])
add("hx34-math-nonhomogeneous-ode", "math.exam.f0de5da26b80",
    "方程 y''−3y'+2y=2e³ˣ 的一个特解是哪一个？",
    ["eˣ", "e²ˣ", "e³ˣ", "2e³ˣ"], "C",
    "对试探函数 e³ˣ，左端乘以特征多项式 3²−3·3+2=2，恰等于右端2e³ˣ。",
    "characteristic-operator", "P(3)=9−9+2=2，取 e³ˣ 后左端为2e³ˣ。",
    "direct-substitution", "y=e³ˣ 时 y'=3e³ˣ、y''=9e³ˣ，左端系数为2。",
    "将指数函数代入微分算子。", "逐项计算导数并核对右端系数。", ["二阶常系数线性微分方程", "特解"])
add("hx34-math-partial-derivative", "math.exam.7d287abb612e",
    "设 z=x²y+xy²，求 ∂z/∂x 在 (1,2) 处的值。",
    ["6", "8", "10", "12"], "B",
    "对 x 求偏导时 y 固定：z_x=2xy+y²。代入 (1,2) 得4+4=8。",
    "partial-differentiation", "固定 y 对 x 求导得到2xy+y²=8。",
    "increment-linear-term", "x 的线性增量系数为2xy+y²，在给定点等于8。",
    "把 y 视为常数求导。", "代入坐标并分项计算。", ["偏导数", "偏导计算"])
add("hx34-math-similarity-trace", "math.exam.08a5efb8a98d",
    "矩阵 B=P⁻¹AP，其中 P 可逆。若 tr(A)=7，则 tr(B) 等于多少？",
    ["−7", "0", "7", "无法确定"], "C",
    "相似矩阵保持迹；由 tr(P⁻¹AP)=tr(APP⁻¹)=tr(A)=7。",
    "cyclic-trace-property", "利用 tr(XY)=tr(YX) 把 P 与 P⁻¹ 抵消，得到7。",
    "similarity-invariant", "迹是相似不变量，因此 tr(B)=tr(A)。",
    "使用迹的循环置换性质。", "确认 P 可逆后识别相似变换。", ["矩阵相似", "迹不变量"])
add("hx34-math-homogeneous-ode", "math.exam.e1688d59990a",
    "常系数齐次方程 y''+4y=0 的通解是哪一个？",
    ["C₁e²ˣ+C₂e⁻²ˣ", "C₁cos2x+C₂sin2x", "C₁+C₂x", "C₁eˣ+C₂xeˣ"], "B",
    "特征方程 r²+4=0 的根为 ±2i，故通解为 C₁cos2x+C₂sin2x。",
    "characteristic-roots", "特征根为±2i，对应实解为正弦余弦组合。",
    "substitution-basis", "cos2x 与 sin2x 各自满足 y''+4y=0，且线性无关。",
    "求特征方程的根。", "代入正弦余弦验证基解。", ["齐次线性微分方程", "特征方程"])
add("hx34-math-integral-work", "math.exam.b8203539e400",
    "变力 F(x)=2x（单位为牛顿）沿 x 轴将物体从 x=0 移至 x=3，所做功是多少？",
    ["3 J", "6 J", "9 J", "18 J"], "C",
    "功为力对位移的积分 ∫₀³2x dx=[x²]₀³=9 J。",
    "work-integral", "直接积分得到9焦耳。",
    "area-under-force-curve", "力—位移图下三角形面积为底3乘高6的一半，即9。",
    "确定功的积分区间和被积函数。", "用几何面积独立核算。", ["定积分应用", "变力做功"])
add("hx34-math-matrix-product-dimension", "math.exam.985c26775327",
    "若 A 为 2×3 矩阵、B 为 3×4 矩阵，则 AB 的阶数为多少？",
    ["2×4", "3×3", "4×2", "乘积不存在"], "A",
    "A 的列数3等于 B 的行数3，乘积存在，结果行数取 A 的2、列数取 B 的4。",
    "matrix-dimension-rule", "内维3相同可乘，外维为2×4。",
    "row-column-entry-count", "AB 有2行，每行与B的4列形成4个分量，所以为2×4。",
    "检查内维是否相等。", "按外维确定结果矩阵阶数。", ["矩阵乘法", "矩阵阶数"])
add("hx34-math-integral-linearity", "math.exam.c023f0987a18",
    "已知 ∫₀¹f(x)dx=3、∫₀¹g(x)dx=−1，则 ∫₀¹[2f(x)−g(x)]dx 为多少？",
    ["5", "6", "7", "−7"], "C",
    "利用定积分线性性，结果为2·3−(−1)=7。",
    "integral-linearity", "将常数因子和差拆开计算得7。",
    "linearity-check", "积分对函数线性，按已知两个积分组合为7。",
    "把积分拆成两项。", "注意 g 的积分为负数。", ["定积分性质", "线性性"])
add("hx34-math-first-order-ode", "math.exam.d17a7d6b708b",
    "初值问题 y'−2y=0、y(0)=3 的解在 x=ln2 处的值是多少？",
    ["6", "8", "12", "24"], "C",
    "方程解为 y=3e²ˣ；代入 x=ln2 得3·e^(2ln2)=3·4=12。",
    "separable-ode", "y'/y=2 积分得 y=Ce²ˣ，初值给 C=3，结果12。",
    "direct-solution-substitution", "y=3e²ˣ 满足方程和初值，代点为12。",
    "分离变量求通解。", "使用初值并代入对数点。", ["一阶线性微分方程", "初值问题"])
add("hx34-math-linear-system-unique", "math.exam.c106a40cda48",
    "二元线性方程组的系数矩阵行列式不为0，关于解的结论是什么？",
    ["无解", "有唯一解", "有无穷多解", "必有两个相同解"], "B",
    "系数矩阵可逆，任意常数右端向量都有唯一解。",
    "invertible-matrix-criterion", "行列式非零等价于系数矩阵可逆，解唯一。",
    "rank-criterion", "系数矩阵秩为2且增广矩阵秩不超过2，故秩相等并为未知数数目。",
    "把非零行列式转为可逆性。", "用秩判据确认解的个数。", ["线性方程组", "唯一解条件"])
add("hx34-math-eigenvector", "math.exam.9bda63607d7e",
    "矩阵 A=[[1,1],[0,1]] 属于特征值 λ=1 的特征向量所张成的空间是哪一个？",
    ["整个 R²", "由 (1,0) 张成的一维空间", "由 (0,1) 张成的一维空间", "零空间只有零向量"], "B",
    "A−I=[[0,1],[0,0]]，方程 (A−I)v=0 给出 y=0，故特征向量为 (x,0)，特征空间由(1,0)张成。",
    "solve-eigenspace", "解 (A−I)(x,y)=0 得 y=0，空间为 span{(1,0)}。",
    "matrix-action", "A(1,0)=(1,0)，而一般向量成为(x+y,y)，需 y=0 才保持特征值1。",
    "写出齐次方程 (A−I)v=0。", "确认空间维数为1且给出生成向量。", ["特征值", "特征向量", "特征空间"])
add("hx34-math-multivariable-extremum", "math.exam.ce32dc737be5",
    "函数 f(x,y)=x²+4y²−2x+8y 在 R² 上的最小值是多少？",
    ["−5", "−4", "−1", "0"], "A",
    "配方得 f=(x−1)²+4(y+1)²−5，平方项非负，最小值为−5。",
    "complete-squares", "分别配方后最小常数项为−5。",
    "critical-point-Hessian", "梯度零点为(1,−1)，Hessian diag(2,8)正定，代入值−5。",
    "对 x、y 项分别配方。", "用驻点与正定 Hessian 核验全局最小。", ["多元函数极值", "配方法"])
add("hx34-math-adjugate-det", "math.exam.6df0d75f1b07",
    "若 A 为 3 阶方阵且 det(A)=−2，则 det(adj(A)) 为多少？",
    ["−4", "−2", "2", "4"], "D",
    "n 阶矩阵满足 det(adj A)=(det A)^(n−1)，故此处为(−2)²=4。",
    "adjugate-determinant-identity", "三阶时 det(adj A)=det(A)²=4。",
    "cofactor-scaling", "伴随矩阵的行列式是原行列式的二次方，符号因此为正4。",
    "应用 n 阶伴随矩阵行列式公式。", "代入阶数3和 det(A)=−2。", ["伴随矩阵", "行列式"])
add("hx34-math-quadratic-positive", "math.exam.f29397bf3b27",
    "二次型 Q(x,y)=x²−2xy+2y² 的正定性如何？",
    ["正定", "负定", "半正定但非正定", "不定"], "A",
    "Q=(x−y)²+y²；除 (0,0) 外至少一项为正，故正定。",
    "sum-of-squares", "平方和在非零向量处严格为正。",
    "Sylvester-criterion", "对称矩阵 [[1,−1],[−1,2]] 的顺序主子式为1和1，均正。",
    "将表达式整理为平方和。", "用顺序主子式再次判断。", ["二次型", "正定性"])
add("hx34-math-ode-decay", "math.exam.51d573e440d0",
    "某放射性物质半衰期为5年，按指数衰变模型，10年后剩余量占初始量的比例是多少？",
    ["1/2", "1/4", "1/5", "1/10"], "B",
    "10年经历两个半衰期，剩余比例为(1/2)²=1/4。",
    "half-life-count", "10/5=2个半衰期，比例1/4。",
    "exponential-decay", "衰变模型 N(t)=N₀e^(−kt)，且 e^(−5k)=1/2，故 e^(−10k)=1/4。",
    "计算经过的半衰期数。", "用指数模型独立核对。", ["微分方程应用", "指数衰变"])
add("hx34-math-vector-dependence", "math.exam.7d6f5725a5ab",
    "在 R³ 中给出4个向量，无论向量具体取值如何，必然结论是什么？",
    ["它们必线性相关", "它们必两两正交", "它们必张成 R³", "其中必有零向量"], "A",
    "R³ 的维数为3，任意多于3个向量必线性相关。",
    "dimension-theorem", "向量数4大于空间维数3，故线性相关。",
    "rank-bound", "由矩阵秩不超过3，4列向量必存在非零线性关系。",
    "比较向量个数与空间维数。", "用列秩上界说明存在非平凡关系。", ["向量组", "线性相关"])
add("hx34-math-variable-limit-integral", "math.exam.eac5b4d10863",
    "设 F(x)=∫₁^(sin x) √(1+t²)dt，求 F'(0)。",
    ["0", "1", "√2", "2"], "B",
    "由变上限积分求导，F'(x)=√(1+sin²x)cos x，故 F'(0)=1。",
    "fundamental-theorem-chain-rule", "被积函数在上限0处为1，乘上限导数cos0=1，结果1。",
    "local-integral-difference-quotient", "积分增量近似为 integrand(0)·(sin h−0)，除以h趋于1。",
    "用微积分基本定理与链式法则。", "用积分差商和 sin h/h 极限核验。", ["变限积分", "链式法则"])
add("hx34-math-integral-compute", "math.exam.c431f98f817c",
    "计算定积分 ∫₀¹(3x²+2x)dx。",
    ["1", "2", "3", "4"], "B",
    "原函数为 x³+x²，代入0与1得到2。",
    "antiderivative", "[x³+x²]₀¹=2。",
    "termwise-integral", "3∫₀¹x²dx+2∫₀¹x dx=1+1=2。",
    "分别求两项的原函数。", "按线性性拆分并计算。", ["定积分计算", "幂函数积分"])
add("hx34-math-total-differential", "math.exam.0bf92dbd942e",
    "设 z=eˣy²。求 z 在点 (0,1) 处的全微分 dz。",
    ["dz=dx+2dy", "dz=2dx+dy", "dz=dx+dy", "dz=2dx+2dy"], "A",
    "z_x=eˣy²、z_y=2yeˣ；代入(0,1)得到系数1和2，故 dz=dx+2dy。",
    "partial-derivatives", "计算两个偏导并在点处取值为1、2。",
    "linearization", "一阶线性增量为 e⁰·1²dx+2·1·e⁰dy。",
    "计算 z_x 与 z_y。", "代入指定点写出 dz。", ["全微分", "偏导数"])

# Computer Science 408: a second, non-paraphrased task for 25 current one-question nodes.
add("hx34-cs-thread-private-state", "cs408.os.topic.debb39552f0f",
    "同一进程中的两个线程并发运行。下列状态通常属于各线程私有而不由同进程线程共享的是（）。",
    ["代码段", "全局数据区", "进程地址空间", "程序计数器和寄存器现场"], "D",
    "同进程线程共享代码、数据和地址空间；每个线程需要独立的程序计数器、寄存器现场和栈。",
    "thread-context-model", "线程切换必须保存各自寄存器与程序计数器，因此它们私有。",
    "address-space-sharing", "代码及全局数据属于进程地址空间而共享，执行现场按线程区分。",
    "区分进程资源与线程执行上下文。", "逐项判断是否属于共享地址空间。", ["进程与线程", "线程私有资源"])
add("hx34-cs-blocked-ready", "cs408.os.topic.ad106d393729",
    "进程因等待磁盘读而处于阻塞态；磁盘读完成且数据已就绪后，通常首先转入哪种状态？",
    ["就绪态", "运行态", "新建态", "终止态"], "A",
    "等待事件完成后，进程具备运行条件并进入就绪队列；是否立刻运行由调度器决定。",
    "state-transition-rule", "阻塞等待事件完成后转为就绪，而不是直接占用CPU。",
    "scheduler-separation", "事件完成只解除等待，运行态还需被调度器选中。",
    "识别阻塞态的等待事件已发生。", "区分就绪与运行这两个状态。", ["进程状态", "状态转换"])
add("hx34-cs-anonymous-pipe", "cs408.os.topic.8fc713e5b56b",
    "在传统 UNIX 进程通信中，普通匿名管道最典型的通信形式是（）。",
    ["无方向的消息广播", "单向字节流", "跨主机可靠数据报", "只传递信号量数值"], "B",
    "普通匿名管道提供有方向的字节流通信；双向交流通常需要两个管道或其他IPC机制。",
    "pipe-interface", "匿名管道读写端有方向，传递连续字节流。",
    "IPC-semantics", "它不提供消息边界或跨主机数据报服务，符合单向字节流特征。",
    "辨析管道的基本抽象。", "排除消息队列、套接字和同步原语的语义。", ["进程间通信", "匿名管道"])
add("hx34-cs-counting-semaphore", "cs408.os.topic.86089b973451",
    "计数信号量 S 初值为3，三个不同进程依次各成功执行一次 P(S)，期间没有执行 V(S)。此后 S 的值为多少？",
    ["0", "1", "3", "−1"], "A",
    "每次成功执行 P 都使可用计数减1，三次后 S=3−3=0。",
    "semaphore-arithmetic", "初值3减去三次P操作，得到0。",
    "resource-count", "三个初始资源各被一个进程取得，剩余可用资源数为0。",
    "按P操作定义逐次更新计数。", "用可用资源数交叉核对。", ["信号量", "P/V 操作"])
add("hx34-cs-preemptive-priority", "cs408.os.topic.2ab87b48f0f9",
    "采用可抢占优先级调度时，当前运行进程优先级较低，新到达的高优先级进程通常会导致什么？",
    ["当前进程立即永久终止", "当前进程被抢占并转入就绪状态", "新进程被强制阻塞", "所有进程优先级变相同"], "B",
    "可抢占优先级调度允许高优先级就绪进程夺取CPU，原运行进程通常回到就绪队列。",
    "preemption-rule", "新就绪进程优先级更高时，调度器触发抢占。",
    "state-transition", "被抢占进程仍可继续执行，状态从运行变为就绪而非终止。",
    "比较两个进程的优先级。", "确定被抢占进程的后续状态。", ["CPU 调度", "抢占式优先级"])
add("hx34-cs-sjf-waiting", "cs408.os.topic.bc235cd7a2fb",
    "三个进程同时到达，采用非抢占 SJF，CPU 服务时间依次为 P1=6、P2=2、P3=4。平均等待时间是多少？",
    ["2", "8/3", "4", "6"], "B",
    "执行顺序为 P2、P3、P1，等待时间分别为0、2、6，平均值为8/3。",
    "schedule-order-and-wait", "SJF排序后等待时间0、2、6，总和8，除以3得8/3。",
    "completion-start-times", "各任务开始时刻为0、2、6，即等待时间，平均8/3。",
    "按服务时间升序排列。", "计算每个进程开始前累计的服务时间。", ["CPU 调度算法", "SJF", "等待时间"])
add("hx34-cs-mutex-fairness", "cs408.os.topic.748b24075a8c",
    "互斥锁保证临界区同一时刻至多一个线程进入，但若锁不承诺公平排队，还不能据此保证什么？",
    ["互斥性", "不会发生数据竞争", "每个等待线程都在有限时间内获得锁", "持锁线程退出临界区"], "C",
    "互斥不等于公平；若调度或锁实现允许持续插队，某等待线程仍可能饥饿。",
    "mutual-exclusion-versus-fairness", "互斥约束并发进入数量，不限定等待者获得锁的顺序或上界。",
    "starvation-counterexample", "一个线程反复抢先取得锁即可使另一线程长期等待而不违反互斥。",
    "区分安全性与公平性。", "构造一个等待者持续被越过的情形。", ["同步与互斥", "公平性", "饥饿"])
add("hx34-cs-compaction", "cs408.os.topic.cab5d37c360d",
    "可变分区连续分配中，通过移动已分配分区把分散空闲区合并为较大空闲区，这种技术主要缓解什么？",
    ["外部碎片", "页内偏移变化", "内部碎片", "磁盘坏道"], "A",
    "移动分区并合并不连续空闲空间，可形成较大的连续空闲块，主要缓解外部碎片。",
    "fragmentation-definition", "分散空闲块合并后外部碎片减少。",
    "allocation-requirement", "连续分配需要足够大的连续块，压缩正是整理空闲区以满足这一条件。",
    "识别空闲区分散的问题。", "将连续分配与页内内部碎片区分。", ["连续分配", "紧凑", "外部碎片"])
add("hx34-cs-page-address-bits", "cs408.os.topic.27116033ab0c",
    "32 位虚拟地址采用 4 KiB 页面。页内偏移占多少位，虚页号又占多少位？",
    ["偏移10位、页号22位", "偏移12位、页号20位", "偏移20位、页号12位", "偏移4位、页号28位"], "B",
    "4 KiB=4096=2¹² 字节，页内偏移12位；剩余32−12=20位表示虚页号。",
    "page-size-log2", "log₂(4096)=12位偏移，剩下20位页号。",
    "address-decomposition", "32位虚拟地址拆分为偏移和页号，二者位数之和为32。",
    "把页面大小换算为2的幂。", "从地址总位数中减去偏移位数。", ["页式管理", "地址划分"])
add("hx34-cs-open-file-offset", "cs408.os.topic.cb972030e503",
    "同一普通文件由同一进程执行两次独立 open，分别取得文件描述符 fd1、fd2。未使用 dup 或共享打开文件描述，关于文件偏移量哪项正确？",
    ["两个描述符必共享一个偏移量", "两个独立打开通常拥有各自偏移量", "每次读操作都会重置文件", "文件偏移量存储在目录项中"], "B",
    "两次独立 open 创建不同的打开文件描述，文件偏移量分别维护；dup 才会共享同一打开文件描述。",
    "open-file-description-model", "独立open产生两个打开文件描述，因此offset分别保存。",
    "contrast-dup", "若fd2由dup(fd1)产生才共享offset；题干明确为两次独立open。",
    "区分文件本身与打开文件描述。", "利用dup的对照规则确认结论。", ["文件基本概念", "文件描述符", "文件偏移"])
add("hx34-cs-indexed-allocation", "cs408.os.topic.75525cc498b3",
    "某文件采用索引分配，索引块能够列出各数据块地址。与链式分配相比，这一机制最直接支持什么访问方式？",
    ["通过索引定位指定逻辑块", "只能从文件首块顺序遍历", "要求所有数据块连续", "不需要保存数据块地址"], "A",
    "索引块保存逻辑块到物理块的地址表，可直接按逻辑块号定位数据块。",
    "index-lookup", "根据逻辑块号查索引项即可得到目标数据块地址。",
    "allocation-contrast", "链式分配需沿指针遍历，索引分配可直接访问索引表项。",
    "识别索引块保存的内容。", "对照链式分配的访问路径。", ["文件物理结构", "索引分配", "直接访问"])
add("hx34-cs-hardlink-unlink", "cs408.os.topic.a0be294e1416",
    "在支持硬链接的类 UNIX 文件系统中，删除一个硬链接目录项后，文件数据通常何时才可回收？",
    ["删除任意一个名字后立即回收", "链接计数为0且没有进程仍打开该文件时", "目录为空时", "下一次系统启动时必定回收"], "B",
    "目录项删除使链接计数减一；当链接计数为0且无打开引用后，文件对象才可回收。",
    "link-count-rule", "仍有硬链接时链接计数大于0，删除一个名字不会清除数据。",
    "open-reference-rule", "即使最后一个名字删除，已打开文件仍可使用至最后引用关闭。",
    "跟踪目录项删除对链接计数的影响。", "再检查打开引用是否仍存在。", ["目录管理", "硬链接", "链接计数"])
add("hx34-cs-interrupt-io", "cs408.os.topic.d5667813a1e7",
    "中断驱动 I/O 中，CPU 发出启动命令后通常如何获知设备操作完成？",
    ["持续逐条查询设备状态", "设备完成后向 CPU 发出中断", "DMA 自动修改程序计数器", "CPU 永久停止执行"], "B",
    "设备完成操作后产生中断，CPU 在中断处理程序中检查结果；这不同于程序查询式忙等。",
    "interrupt-completion", "完成事件由设备中断通知处理器。",
    "polling-contrast", "持续查询是程序控制I/O的轮询特征，并非中断驱动。",
    "按中断驱动的事件通知机制判断。", "与程序查询方式对比。", ["I/O 控制方式", "中断驱动 I/O"])
add("hx34-cs-sstf-first", "cs408.os.topic.ec4f03dc7ff5",
    "磁头当前位置为45号柱面，待处理请求为40、10、51号柱面。SSTF算法下一步选择哪个请求？",
    ["10号", "40号", "51号", "三个距离相同"], "B",
    "到40号距离5、到51号距离6、到10号距离35，最近且唯一的是40号。",
    "absolute-distance", "|40−45|=5、|51−45|=6、|10−45|=35，最小值唯一为5。",
    "nearest-request", "按SSTF选择当前寻道距离最短请求，故选择40号。",
    "分别计算三个请求的寻道距离。", "确认最小距离没有并列。", ["磁盘调度", "SSTF"])
add("hx34-cs-lru-faults", "cs408.os.topic.006da51a6b0f",
    "采用 LRU 页面置换，初始3个页框为空，访问序列为 1,2,3,1,4,2,5。缺页次数是多少？",
    ["4", "5", "6", "7"], "C",
    "1、2、3首次访问缺页；1命中；4替换最久未用的2；随后2、5又各缺页，合计6次。",
    "reference-string-simulation", "逐次状态：123→123→123→1替2→2替3→5替1，共6次缺页。",
    "recency-order", "第4步更新1为最新；4淘汰2，之后2淘汰3，5淘汰1，总数6。",
    "逐项维护页框和最近使用次序。", "核对命中仅发生在第4次引用。", ["页面置换", "LRU", "缺页次数"])
add("hx34-cs-http-layer", "cs408.cn.topic.9d2dd646a2ab",
    "HTTP 协议在 TCP/IP 体系结构中通常属于哪一层？",
    ["应用层", "传输层", "网络层", "网络接口层"], "A",
    "HTTP定义Web应用的请求与响应语义，依赖传输层服务，属于应用层协议。",
    "protocol-function", "请求资源和表示应用数据属于应用层职责。",
    "encapsulation-stack", "HTTP报文由TCP承载，TCP位于其下层，所以HTTP属于应用层。",
    "判断协议是否定义应用语义。", "按协议封装层次与TCP区分。", ["网络分层", "TCP/IP 应用层", "HTTP"])
add("hx34-cs-propagation-delay", "cs408.cn.topic.658f7cffbc1f",
    "信号在一条长6000 km的链路上传播，传播速度为 2×10⁸ m/s。单向传播时延是多少？",
    ["3 ms", "30 ms", "300 ms", "3 s"], "B",
    "距离为6×10⁶ m，传播时延=距离/速度=0.03 s=30 ms。",
    "distance-over-speed", "6×10⁶/(2×10⁸)=3×10⁻²秒。",
    "unit-conversion", "0.03秒乘1000为30毫秒。",
    "把公里换成米后求比值。", "将秒换算成毫秒检查数量级。", ["网络性能指标", "传播时延"])
add("hx34-cs-ip-layer-service", "cs408.cn.topic.7dfe285bb24b",
    "IP 网络层的基本数据报服务通常具有哪项特征？",
    ["尽力交付，但不保证端到端可靠和按序", "保证所有分组按序且无差错", "为每条连接预留固定带宽", "直接实现应用进程间消息语义"], "A",
    "IP提供无连接尽力而为的数据报服务，可靠传输、排序等通常由端到端传输层处理。",
    "IP-service-model", "IP头部和转发机制不承诺可靠送达或按序交付。",
    "layer-responsibility", "可靠有序字节流是TCP等传输层协议的功能，不是IP保证。",
    "识别IP数据报的服务模型。", "区分网络层与传输层职责。", ["网络层功能", "尽力而为服务"])
add("hx34-cs-distance-vector", "cs408.cn.topic.a2e54e0115b9",
    "距离向量路由中，本机到邻居 N 的代价为1；N通告其到目的 D 的距离为4。经 N 到 D 的候选距离是多少？",
    ["3", "4", "5", "无法计算"], "C",
    "距离向量更新按“本机到邻居代价 + 邻居通告距离”计算，候选值为1+4=5。",
    "bellman-ford-update", "候选距离 d(self,N)+d(N,D)=1+4=5。",
    "path-cost-sum", "路径由两段组成，总代价为两段代价之和5。",
    "写出距离向量的邻居更新式。", "将两段代价相加。", ["路由算法", "距离向量"])
add("hx34-cs-rip-max-hop", "cs408.cn.topic.8e7e1292d6b4",
    "RIP 的跳数度量中，最大可达距离是多少跳？",
    ["14跳", "15跳", "16跳", "255跳"], "B",
    "RIP将16定义为无穷大/不可达，因此最大可达跳数为15。",
    "rip-infinity-value", "16表示不可达，故可达上限为15。",
    "metric-range", "合法可达度量为1至15，达到16即视为无穷大。",
    "记住RIP的不可达度量。", "由不可达值推出最大可达值。", ["RIP", "路由度量"])
add("hx34-cs-aimd", "cs408.cn.topic.b8e94d7c568d",
    "TCP拥塞避免阶段采用加性增大、乘性减小时，在无拥塞丢包的稳定阶段，拥塞窗口大致如何增长？",
    ["每个 RTT 约增加一个 MSS", "每个 RTT 翻倍", "每个 RTT 减半", "保持恒定"], "A",
    "拥塞避免的加性增大使拥塞窗口近似每 RTT 增加一个 MSS；慢启动才近似指数增长。",
    "AIMD-definition", "AIMD中的加性增大对应每RTT约加1 MSS。",
    "slow-start-contrast", "每RTT翻倍属于慢启动特征，不是拥塞避免阶段。",
    "解释 additive increase 的含义。", "与慢启动指数增长区分。", ["拥塞控制", "AIMD", "拥塞避免"])
add("hx34-cs-dhcp-dora", "cs408.cn.topic.71ab052ca21b",
    "DHCP客户端首次获取租约时，DORA交互的典型顺序是什么？",
    ["Discover、Offer、Request、Ack", "Offer、Discover、Ack、Request", "Request、Ack、Discover、Offer", "Ack、Request、Offer、Discover"], "A",
    "客户端先发现服务器，服务器提供配置，客户端请求该配置，服务器确认租约。",
    "message-role-sequence", "D/O/R/A分别为发现、提供、请求、确认，顺序为Discover→Offer→Request→Ack。",
    "client-server-roles", "客户端发起Discover和Request，服务器回复Offer和Ack。",
    "按首字母展开四个消息角色。", "检查客户端与服务器的交替方向。", ["ARP/DHCP/ICMP", "DHCP", "DORA"])
add("hx34-cs-router-components", "cs408.cn.topic.0a2961dff8db",
    "路由器的路由处理器与数据平面转发部件之间，哪项职责划分正确？",
    ["路由处理器维护控制信息，转发部件按转发表处理到达分组", "转发部件运行用户浏览器", "路由处理器逐位计算每个应用程序", "两者职责完全相同"], "A",
    "控制平面运行路由协议并形成转发表；数据平面依据转发表将分组送往输出端口。",
    "control-data-plane", "路由处理器属控制功能，转发部件承担高速逐包处理。",
    "forwarding-table-use", "路由计算形成状态，数据平面依此状态转发每个分组。",
    "区分控制平面和数据平面。", "把路由决策结果与逐包动作对应起来。", ["路由器组成", "控制平面", "数据平面"])
add("hx34-cs-tcp-send-window", "cs408.cn.topic.fdfe51b5d88a",
    "某TCP发送方当前接收窗口 rwnd=8 KiB、拥塞窗口 cwnd=12 KiB，忽略其他限制时，允许在途的发送窗口上限是多少？",
    ["4 KiB", "8 KiB", "12 KiB", "20 KiB"], "B",
    "发送窗口受流量控制和拥塞控制共同限制，取 min(rwnd,cwnd)=8 KiB。",
    "window-min-rule", "min(8,12)=8 KiB。",
    "dual-constraint", "不能超过接收方缓冲许可8，也不能超过拥塞许可12，因此上限8。",
    "列出接收方与网络两项约束。", "取较小窗口。", ["TCP 流量控制", "接收窗口", "拥塞窗口"])
add("hx34-cs-dns-cname", "cs408.cn.topic.7253eabb8454",
    "DNS 的 CNAME 资源记录主要表示什么？",
    ["把别名映射到规范主机名", "把主机名映射到 IPv4 地址", "指定邮件交换服务器", "把 IPv6 地址反向映射到名称"], "A",
    "CNAME记录表示别名到规范名称的映射；IPv4地址通常由A记录给出。",
    "dns-record-semantics", "CNAME的记录值是目标规范名称。",
    "record-type-contrast", "A对应IPv4，MX对应邮件，PTR用于反向查询，故CNAME选A项。",
    "识别CNAME中的 canonical name 含义。", "与A、MX、PTR记录作用对照。", ["DNS", "资源记录", "CNAME"])

if len(batch.CODEX_PUBLIC_ORIGINALS) != 50:
    raise RuntimeError(f"batch34_requires_50_unique_targets:{len(batch.CODEX_PUBLIC_ORIGINALS)}")
if len({x["node_code"] for x in batch.CODEX_PUBLIC_ORIGINALS}) != 50:
    raise RuntimeError("batch34_target_nodes_not_unique")

if __name__ == "__main__":
    raise SystemExit(batch.main())
