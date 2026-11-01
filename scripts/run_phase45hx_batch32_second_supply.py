"""Batch 32: second, distinct practice item for 50 currently single-question topics."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-31-remaining-topics"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_31_REMAINING_TOPICS_COMPLETE":
    raise RuntimeError("batch31_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch31_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-32-second-supply"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_31_REMAINING_TOPICS_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-32-second-supply"
batch.SUCCESS_STATUS = "BATCH_32_SECOND_SUPPLY_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []
single = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 1
}


def add(req, node, stem, choices, answer, explanation, method1, result1,
        method2, result2, step1, step2, skills):
    if node not in single:
        raise RuntimeError(f"target_not_single_question_node:{node}")
    batch.CODEX_PUBLIC_ORIGINALS.append({
        "request_id": req,
        "node_code": node,
        "output": base.choice(
            stem, {chr(65 + i): value for i, value in enumerate(choices)},
            answer, explanation, f"independent-check:{method1}; {method2} -> {answer}",
        ),
        "derived_answer": answer,
        "method_evidence": [
            {"method": method1, "result": f"路径一（{method1}）：{result1}；得 {answer}。"},
            {"method": method2, "result": f"路径二（{method2}）：{result2}；复核为 {answer}。"},
        ],
        "explanation_key_steps": [f"第一步：{step1}", f"第二步：{step2}"],
        "option_truth_table": {chr(65 + i): chr(65 + i) == answer for i in range(4)},
        "skill_tags": skills,
    })


# Math II: another problem, not a paraphrase of the current one, for 25 low-supply topics.
add("hx32-math-implicit", "math.calculus.differential.implicit",
    "曲线 x²+xy+y²=7 在点 (1,2) 处的切线斜率 dy/dx 为多少？",
    ["−4/5", "−5/4", "4/5", "5/4"], "A",
    "隐式求导得 2x+y+x y'+2y y'=0，故 y'=−(2x+y)/(x+2y)；代入(1,2)为−4/5。",
    "implicit-differentiation", "对关系式逐项求导并整理出 y'=−(2x+y)/(x+2y)，代点得−4/5。",
    "tangent-condition", "曲线梯度为(2x+y,x+2y)=(4,5)，切向量斜率为−4/5。",
    "对 x 与 y 的复合项同时求导。", "代入点坐标并用梯度正交关系核验。", ["隐函数求导", "切线斜率"])
add("hx32-math-geometric-series", "math.calculus.series.geometric",
    "无穷等比级数 3−1+1/3−1/9+… 的和是多少？",
    ["9/4", "3/2", "2", "发散"], "A",
    "首项为3、公比为−1/3且绝对值小于1，和为 3/(1+1/3)=9/4。",
    "geometric-sum", "用 a/(1−r) 得 3/(1+1/3)=9/4。",
    "partial-sum-limit", "有限和公式中 r 的幂趋零，极限同为9/4。",
    "识别首项和公比。", "检查公比模小于1后取无穷和。", ["等比级数", "收敛与求和"])
add("hx32-math-determinant-row-scale", "math.linear-algebra.determinant.properties",
    "若 3 阶矩阵 A 的行列式为 5，把 A 的一行乘以 −2 得 B，则 det(B) 为多少？",
    ["−10", "−5", "5", "10"], "A",
    "行列式对单行数乘呈一次齐次，某一行乘−2使行列式也乘−2，结果−10。",
    "row-linearity", "按一行的线性性把因子−2提出行列式，得−2×5。",
    "multilinearity", "其余两行不变，仅一行缩放，整体行列式按该比例缩放。",
    "确定只有一个行被缩放。", "将该行的比例因子提出行列式。", ["行列式性质", "行数乘"])
add("hx32-math-lhopital", "math.calculus.limit.lhopital",
    "极限 lim(x→0) (e^(2x)−1)/x 的值是多少？",
    ["1", "2", "0", "不存在"], "B",
    "分子分母均趋于0，可用洛必达法则；导数之比为 2e^(2x)，极限为2。",
    "lhopital-derivatives", "对分子分母分别求导后取 x→0，得到2。",
    "exponential-equivalent", "e^(2x)−1 与 2x 等价，原比值趋于2。",
    "确认属于 0/0 型。", "求导并以等价无穷小独立核验。", ["洛必达法则", "指数极限"])
add("hx32-math-equivalent-infinitesimal", "math.calculus.limit.infinitesimal",
    "极限 lim(x→0) sin(3x)/sin(5x) 等于多少？",
    ["3/5", "5/3", "1", "0"], "A",
    "当 x→0 时 sin(kx) 与 kx 等价，商趋于 3x/5x=3/5。",
    "sine-equivalence", "分别用 sin(3x)~3x 与 sin(5x)~5x 替换，得3/5。",
    "standard-sine-limit", "拆成 sin(3x)/(3x) 与 sin(5x)/(5x) 的比值并乘3/5。",
    "确认两个正弦自变量都趋于0。", "用等价无穷小或标准正弦极限求比。", ["等价无穷小", "正弦极限"])
add("hx32-math-double-integral-properties", "math.exam.4ea6e9d4fae7",
    "在单位正方形 [0,1]×[0,1] 上，二重积分 ∬(x+y) dA 的值是多少？",
    ["1/2", "1", "3/2", "2"], "B",
    "利用积分线性性，∫∫x dA=1/2，∫∫y dA=1/2，总和为1。",
    "separable-integrals", "分别对x与y积分，两项各为1/2。",
    "symmetry-average", "正方形内x与y的平均值均为1/2，面积为1，故积分为1。",
    "利用被积函数的和分拆积分。", "用区域对称性复核两项贡献。", ["二重积分概念", "积分线性性"])
add("hx32-math-double-integral-compute", "math.exam.a0d6b80898e3",
    "计算 ∫(x=0到1)∫(y=0到x) y dy dx。",
    ["1/8", "1/6", "1/4", "1/3"], "B",
    "内层积分为 x²/2，外层积分为 ∫₀¹x²/2 dx=1/6。",
    "iterated-integration", "先积y得x²/2，再对x积分得1/6。",
    "triangle-moment", "对三角区域按高度y积分，∫₀¹ y(1−y)dy=1/2−1/3=1/6。",
    "先处理内层关于 y 的积分。", "再对 x 积分并用区域换序核对。", ["二重积分计算", "累次积分"])
add("hx32-math-double-integral-application", "math.exam.5af66b782c26",
    "区域 x≥0、y≥0、x+y≤1 上，曲面 z=x+y 与 xy 平面围成的体积是多少？",
    ["1/6", "1/4", "1/3", "1/2"], "C",
    "体积为 ∬(x+y)dA；按 0≤x≤1、0≤y≤1−x 积分，结果为1/3。",
    "iterated-volume", "内层积分得 x(1−x)+(1−x)²/2=(1−x²)/2，外层积分为1/3。",
    "symmetry-and-area", "区域面积为1/2且x、y对称，平均x+y的值为2/3，乘积为1/3。",
    "把体积表达为非负高度的二重积分。", "积分并用区域对称平均值核验。", ["二重积分应用", "曲面体积"])
add("hx32-math-double-symmetry", "math.exam.b481011b3a32",
    "利用对称性计算 ∬_R x³ dA，其中 R=[−1,1]×[0,2]，结果为（）。",
    ["0", "1", "2", "4"], "A",
    "区域关于 y 轴对称，被积函数 x³ 关于 x 为奇函数，正负两侧积分抵消。",
    "odd-function-cancellation", "∫_{−1}^1 x³ dx=0，再乘y方向长度2仍为0。",
    "reflection-substitution", "令 x→−x，区域不变而被积函数变号，积分等于其相反数，只能为0。",
    "检查区域关于 x=0 对称。", "应用奇函数的反射抵消。", ["二重积分对称性", "奇函数"])
add("hx32-math-polar", "math.exam.609e58acbace",
    "圆域 x²+y²≤4 的面积用极坐标计算为（）。",
    ["2π", "4π", "8π", "π"], "B",
    "极坐标中 0≤r≤2、0≤θ≤2π，面积积分为 ∫∫r dr dθ=4π。",
    "polar-jacobian", "Jacobian因子r，径向积分为2、角向长度2π，乘积4π。",
    "circle-area", "半径2圆面积πr²=4π，与极坐标积分一致。",
    "将圆域改写为半径和角度范围。", "记入极坐标面积元中的 r 因子。", ["极坐标变换", "积分区域"])
add("hx32-math-continuity-piecewise", "math.exam.71a29108dd89",
    "函数 f(x)=(x²−1)/(x−1)（x≠1），且 f(1)=2，在 x=1 处（）。",
    ["连续", "可去间断但不连续", "跳跃间断", "无穷间断"], "A",
    "对 x≠1 化简为 x+1，极限为2且函数值也是2，所以在1处连续。",
    "factorization-limit", "分子分解为(x−1)(x+1)，去心邻域函数等于x+1，极限2。",
    "continuity-definition", "函数值f(1)=2与邻域极限2相等，满足连续定义。",
    "计算去心邻域内的极限。", "比较极限与指定函数值。", ["连续性", "间断点"])
add("hx32-math-derivative-application", "math.exam.9578b3defcb0",
    "函数 f(x)=x³−3x 在闭区间 [0,2] 上的最小值是多少？",
    ["−2", "−1", "0", "2"], "A",
    "f'(x)=3(x²−1)，区间内临界点为1；比较f(0)=0、f(1)=−2、f(2)=2，最小值−2。",
    "critical-point-test", "求驻点并将驻点与两个端点函数值比较，最小值为−2。",
    "monotonicity-intervals", "导数在(0,1)负、(1,2)正，函数先降后升，最低点x=1值−2。",
    "求闭区间内部临界点。", "比较端点与驻点的函数值。", ["导数应用", "闭区间最值"])
add("hx32-math-concavity-asymptote", "math.exam.f37948c82a05",
    "函数 y=1/(x−2) 的垂直渐近线方程是（）。",
    ["x=2", "y=2", "x=0", "y=0"], "A",
    "当 x→2 时分母趋于0而函数无界，因此 x=2 为垂直渐近线。",
    "denominator-zero", "分母在2为零且分子非零，函数在该点附近无界。",
    "one-sided-limits", "左右极限分别趋向相反无穷，确定竖直渐近线x=2。",
    "寻找函数定义域边界处的分母零点。", "检查单侧极限是否无界。", ["渐近线", "函数图形"])
add("hx32-math-monotonic-extremum", "math.exam.de02b85cba3d",
    "函数 f(x)=x²−4x 在全体实数上的最小值为（）。",
    ["−4", "−2", "0", "4"], "A",
    "配方 f(x)=(x−2)²−4，平方项非负，故最小值−4在x=2取得。",
    "complete-square", "配方直接给出下界−4并由x=2达到。",
    "derivative-critical-point", "导数2x−4在x=2为零且二阶导为2正，函数取最小值−4。",
    "将二次函数配方。", "用导数判别驻点性质复核。", ["单调性", "极值与最值"])
add("hx32-math-mvt", "math.exam.4586eb88acb7",
    "对 f(x)=x² 在 [0,2] 应用拉格朗日中值定理，满足 f'(c)=(f(2)−f(0))/2 的 c 为（）。",
    ["1", "1/2", "2", "不存在"], "A",
    "区间平均变化率为2，导数f'(x)=2x，方程2c=2给出c=1。",
    "secant-slope", "端点割线斜率为(4−0)/2=2，切线斜率2c相等于c=1。",
    "theorem-hypotheses", "多项式在闭区间连续、开区间可导，定理适用且c=1在(0,2)。",
    "计算区间平均变化率。", "令导数等于平均变化率并验证 c 在开区间。", ["微分中值定理", "拉格朗日中值定理"])
add("hx32-math-limit-parameter", "math.exam.e90535214807",
    "若 lim(x→0) (e^(ax)−1)/x=2，则参数 a 等于（）。",
    ["1", "2", "−2", "0"], "B",
    "利用 e^(ax)−1 与 ax 等价，极限为a，因此a=2。",
    "exponential-derivative", "该极限是函数e^(ax)在0处的导数，等于a。",
    "series-expansion", "展开 e^(ax)=1+ax+O(x²)，相除后极限a。",
    "辨认指数函数差商。", "用导数定义或展开式求极限。", ["极限参数", "指数极限"])
add("hx32-math-derivative-definition", "math.exam.547f1fa49cd2",
    "用导数定义求 f(x)=x² 在 x=3 处的导数，结果为（）。",
    ["3", "6", "9", "12"], "B",
    "差商 ((3+h)²−9)/h=6+h，令h→0得到6。",
    "difference-quotient", "按导数定义展开差商并取极限为6。",
    "power-rule-check", "幂函数求导得到2x，代入x=3为6。",
    "写出 x=3 处差商。", "化简后取 h 趋零极限并用求导公式核验。", ["导数定义", "导数计算"])
add("hx32-math-root-count", "math.exam.0318406f8b47",
    "方程 x³+x−1=0 在实数范围内有几个根？",
    ["0个", "1个", "2个", "3个"], "B",
    "函数导数3x²+1恒正，故严格递增；f(0)=−1、f(1)=1，介值定理给出且仅给出一个根。",
    "monotonicity-and-IVT", "连续且严格递增，并在0与1异号，因此恰有一个根。",
    "derivative-sign", "导数对所有实数为正，至多一个根；端点异号保证至少一个根。",
    "用导数证明严格单调。", "用异号与连续性证明存在根。", ["方程根的存在性", "根的个数"])
add("hx32-math-function-limit", "math.exam.c5c672022b7f",
    "极限 lim(x→0) sin(2x)/x 等于多少？",
    ["0", "1", "2", "不存在"], "C",
    "拆为2·sin(2x)/(2x)，标准正弦极限为1，所以结果2。",
    "standard-limit", "使用 lim(u→0)sin u/u=1，取u=2x后乘2。",
    "sine-equivalence", "sin(2x)与2x等价，商趋于2。",
    "构造标准正弦极限形式。", "应用等价无穷小复核。", ["函数极限", "标准极限"])
add("hx32-math-sequence", "math.exam.61b15cc0e52c",
    "数列 a_n=(−1)^n/n 的极限是多少？",
    ["−1", "0", "1", "发散"], "B",
    "绝对值 |a_n|=1/n 趋于0，故无论正负交替，a_n也趋于0。",
    "squeeze-theorem", "有−1/n≤a_n≤1/n且两侧均趋于0，夹逼得极限0。",
    "absolute-value", "数列项绝对值趋零直接推出数列项趋零。",
    "控制数列项绝对值。", "用夹逼定理确定极限。", ["数列敛散性", "极限"])
add("hx32-math-inequality", "math.exam.68217a446e4c",
    "对任意 x>0，x+1/x 的最小值为（）。",
    ["1", "2", "0", "不存在"], "B",
    "由均值不等式 x+1/x≥2√(x·1/x)=2，且x=1取等号。",
    "AM-GM", "两个正数x与1/x的算术平均至少为其几何平均2，故和至少2。",
    "square-nonnegative", "x+1/x−2=(x−1)²/x≥0，等号在x=1成立。",
    "检查变量正性后使用均值不等式。", "用平方非负写出等价证明。", ["不等式证明", "均值不等式"])
add("hx32-math-infinitesimal-order", "math.exam.cdaedae1e143",
    "当 x→0 时，1−cos x 与 x 的平方相比属于（）。",
    ["高阶无穷小，且 (1−cos x)/x²→1/2", "同阶且比值趋1", "与x等价", "不趋于0"], "A",
    "由 1−cos x=2sin²(x/2) 及 sin u~u，得到 1−cos x~x²/2。",
    "trigonometric-identity", "使用半角恒等式并对 sin(x/2) 作等价替换。",
    "Taylor-expansion", "cos x=1−x²/2+o(x²)，故差为x²/2的主项。",
    "用半角恒等式重写余弦差。", "取与 x² 的比值并用标准极限核验。", ["无穷小量", "无穷小阶数"])
add("hx32-math-determinant", "math.exam.f4e5ed0360ea",
    "计算三阶行列式 det([[1,0,2],[0,3,0],[4,0,1]])。",
    ["−21", "−9", "9", "21"], "A",
    "按第二行展开，得3·det([[1,2],[4,1]])=3(1−8)=−21。",
    "cofactor-expansion", "沿含两个零的第二行展开直接得−21。",
    "block-reordering", "按第2行第2列独立块分解，剩余子式为−7，乘3得−21。",
    "选择含零较多的行展开。", "计算二阶子式并乘展开元素。", ["行列式", "三阶行列式"])
add("hx32-math-taylor", "math.exam.167393e991a4",
    "函数 e^x 在 x=0 处的二阶 Taylor 多项式是（）。",
    ["1+x+x²/2", "1+x²", "x+x²/2", "1−x+x²/2"], "A",
    "e^x 在0处各阶导数均为1，因此二阶 Taylor 多项式为1+x+x²/2。",
    "derivative-coefficients", "将f(0)=f'(0)=f''(0)=1代入Taylor公式。",
    "series-definition", "指数函数麦克劳林级数前3项即1+x+x²/2。",
    "计算函数及前两阶导数在0处取值。", "代入二阶 Taylor 公式并与级数核对。", ["Taylor公式", "Maclaurin展开"])
add("hx32-math-arctan-taylor", "math.exam.a24681a8ee59",
    "arctan x 在 x=0 附近到三次项的 Taylor 展开为（）。",
    ["x−x³/3+o(x³)", "x+x²+o(x³)", "1+x−x³/3", "x³/3+o(x³)"], "A",
    "由 arctan x 的导数 1/(1+x²)=1−x²+… 积分得 x−x³/3+…。",
    "integrate-geometric-series", "展开1/(1+x²)并逐项积分，得到x−x³/3的前三次项。",
    "Taylor-derivatives", "在0处一阶导为1、二阶导为0、三阶导为−2，三次系数为−1/3。",
    "展开导函数的几何级数。", "逐项积分并用导数系数核验。", ["反三角函数", "Taylor展开"])

# Computer Science 408: 25 additional, non-identical topics.
add("hx32-408-deque", "cs408.ds.topic.48e8e73d9928",
    "双端队列与普通队列相比，典型地允许在何处插入和删除？",
    ["仅队尾插入、队头删除", "两端均可插入和删除", "仅队头插入、队尾删除", "任意中间位置均可常数时间插入"], "B",
    "双端队列允许在队头和队尾两端执行插入、删除操作。",
    "operation-definition", "检查双端队列两端均支持进队和出队。",
    "endpoint-model", "与单端队列受限的入队端和出队端比较可得两端操作。",
    "识别两端各自允许的操作。", "排除中间位置操作的额外链表/数组成本。", ["双端队列", "线性结构"])
add("hx32-408-postorder", "cs408.ds.topic.de07cf385c9a",
    "二叉树后序遍历访问结点的顺序是（）。",
    ["根、左、右", "左、根、右", "左、右、根", "右、根、左"], "C",
    "后序遍历先访问左子树，再访问右子树，最后访问根结点。",
    "traversal-definition", "按照后序定义得到左—右—根。",
    "recursive-order", "两个子递归返回后才访问当前根。",
    "确定根结点访问时机。", "排列左右子树递归顺序。", ["后序遍历", "二叉树遍历"])
add("hx32-408-threaded-tree", "cs408.ds.topic.36d6505de0b4",
    "中序线索二叉树中，原本为空的右孩子链域可用于指向该结点的（）。",
    ["中序后继", "中序前驱", "父结点", "根结点"], "A",
    "右线索通常指向结点在指定遍历次序中的后继；中序线索树的右线索指向中序后继。",
    "thread-tag-semantics", "右空链域若标记为线索，存储遍历次序后继。",
    "inorder-successor", "按中序左根右顺序，右线索所跳转的后继是中序后继。",
    "区分孩子链与线索链。", "按中序次序确定右线索的目标。", ["线索二叉树", "中序后继"])
add("hx32-408-avl-balance", "cs408.ds.topic.f475d9be6d3b",
    "平衡二叉树 AVL 中，任一结点左右子树高度差的绝对值至多为（）。",
    ["0", "1", "2", "树高"], "B",
    "AVL平衡条件要求每个结点的左右子树高度差不超过1。",
    "balance-factor", "平衡因子取−1、0、1，绝对值最大为1。",
    "recursive-invariant", "对子树递归维持高度差限制可保证树高为对数级。",
    "写出平衡因子范围。", "转换为高度差绝对值上界。", ["AVL树", "平衡因子"])
add("hx32-408-forest-edges", "cs408.ds.topic.f378d0f0786f",
    "一个森林共有 n 个结点和 m 棵互不相交的树，则边数为（）。",
    ["n−m", "n+m", "n−1", "nm"], "A",
    "每棵树有结点数减1条边，求和得到所有结点数n减树的棵数m。",
    "sum-tree-edges", "各树边数求和为Σ(n_i−1)=Σn_i−m=n−m。",
    "acyclic-components", "森林是含m个连通分量的无环图，边数=顶点数−连通分量数。",
    "分别计算每棵树的边数。", "按森林连通分量公式复核。", ["树与森林", "边数"])
add("hx32-408-connected-graph", "cs408.ds.topic.48968798d156",
    "无向图中任意两个顶点之间都存在路径时，该图称为（）。",
    ["连通图", "完全图", "二分图", "有向无环图"], "A",
    "无向图连通的定义是任意一对顶点之间存在路径。",
    "connectivity-definition", "直接应用连通图的顶点对路径定义。",
    "component-count", "连通等价于图只有一个连通分量。",
    "选取任意一对顶点。", "判断其是否属于同一连通分量。", ["图基本概念", "连通图"])
add("hx32-408-topological-dag", "cs408.ds.topic.8ea0de0d75f4",
    "有向图存在拓扑序列的充要条件之一表述为该图必须（）。",
    ["无有向环", "是完全图", "所有顶点入度均为1", "边数为顶点数"], "A",
    "有向图有拓扑序当且仅当它是有向无环图；有环时环上约束无法线性排序。",
    "indegree-removal", "若拓扑删除过程剩余顶点非空，则剩余子图含环。",
    "precedence-cycle", "环上每个顶点都要求排在下一个之前，形成矛盾。",
    "观察拓扑排序的入度为零删除过程。", "说明有向环为何不能满足先后次序。", ["拓扑排序", "有向无环图"])
add("hx32-408-binary-search-count", "cs408.ds.topic.8b04b55a0408",
    "有序表长度为15，成功折半查找时，目标恰在第一次比较的中间位置，需要比较几次？",
    ["1次", "2次", "3次", "4次"], "A",
    "第一次比较的位置就是当前中间元素，目标相等即结束，故只比较一次。",
    "search-trace", "首轮比较后相等，不再进入子区间。",
    "termination-condition", "折半查找在命中中点时立即成功返回。",
    "确定首轮中点元素。", "按查找成功终止条件计数。", ["二分查找", "比较次数"])
add("hx32-408-quicksort-worst", "cs408.ds.topic.3172ece4a3d6",
    "快速排序每次都选到当前区间最小元素作为枢轴时，递归规模与最坏时间复杂度分别为（）。",
    ["两边约各一半，O(n log n)", "一边 n−1、另一边0，O(n²)", "两边均为空，O(n)", "固定一边1个，O(log n)"], "B",
    "极端枢轴每趟只减少一个元素，递推成本为 n+(n−1)+…+1，数量级n²。",
    "partition-sizes", "最小枢轴划分出空区间与剩余n−1元素区间。",
    "recurrence-sum", "递归深度为n且每层扫描规模递减，和为平方级。",
    "根据枢轴位置确定划分规模。", "累加各层划分扫描成本。", ["快速排序", "最坏复杂度"])
add("hx32-408-bubble-stability", "cs408.ds.topic.dd68a6da9516",
    "标准冒泡排序仅在相邻关键字严格逆序时交换，通常具有什么性质？",
    ["稳定", "不稳定", "不能原地排序", "必须递归实现"], "A",
    "相同关键字不会因严格大于条件而互换相对次序，故标准冒泡排序稳定。",
    "equal-key-order", "只有前项大于后项才交换，相等元素维持原相对顺序。",
    "adjacent-swap-invariant", "每次只交换逆序相邻项，不会越过相等关键字。",
    "跟踪两个相等关键字元素。", "判断它们是否可能交换相对位置。", ["冒泡排序", "稳定性"])
add("hx32-408-open-addressing", "cs408.ds.topic.1eb540d3b4f1",
    "采用开放定址法处理冲突时，所有关键字通常存储在（）。",
    ["散列表自身的槽位中", "单独的冲突链表中", "二叉树叶结点中", "顺序文件尾部"], "A",
    "开放定址在表内探查其他空槽安置关键字，不使用独立链表保存冲突项。",
    "collision-resolution", "冲突后按探查序列在散列表内部寻找空单元。",
    "storage-location", "表外链表属于拉链法而非开放定址。",
    "检查发生冲突后的探查位置。", "区分表内探查与表外链接。", ["开放定址散列", "冲突处理"])
add("hx32-408-sequential-list", "cs408.ds.topic.34f35fb23f9e",
    "在含 n 个元素的顺序表表头插入一个元素，最坏需要移动多少个原有元素？",
    ["0", "1", "n", "n²"], "C",
    "为表头腾出位置，所有n个原元素均需后移一位。",
    "array-shift", "数组连续存储要求将下标0到n−1的元素逐一右移。",
    "operation-count", "最坏移动数随现有元素数线性增长，为n。",
    "确定插入位置为下标0。", "统计其后所有元素的位移。", ["顺序表", "插入操作"])
add("hx32-408-performance", "cs408.co.topic.d25446fb51a0",
    "某程序执行 1.2×10⁹ 条指令，平均 CPI 为2，CPU 主频为3 GHz，CPU 时间为多少？",
    ["0.2 s", "0.4 s", "0.8 s", "1.2 s"], "C",
    "CPU时间=指令数×CPI/时钟频率=1.2×10⁹×2/(3×10⁹)=0.8秒。",
    "performance-equation", "代入标准CPU性能公式得到0.8秒。",
    "cycle-count", "总周期数为2.4×10⁹，以每秒3×10⁹周期执行耗时0.8秒。",
    "先求总时钟周期数。", "除以主频并检查单位。", ["计算机性能指标", "CPU时间"])
add("hx32-408-integer-overflow", "cs408.co.topic.675363fe6912",
    "n 位补码加法中，两个同号操作数相加而结果符号与操作数相反，表示（）。",
    ["发生溢出", "一定没有进位", "结果必为零", "发生浮点下溢"], "A",
    "有符号补码加法溢出条件之一是同号数相加得到异号结果。",
    "sign-rule", "检查两个操作数符号与结果符号，按补码溢出判据为溢出。",
    "range-bound", "同号数的数学和超出n位有符号表示范围时发生回绕，符号反转可检测。",
    "区分最高位进位与符号关系。", "应用同号相加的溢出判定规则。", ["整数加减运算", "补码溢出"])
add("hx32-408-memory-buses", "cs408.co.topic.2f989eb277fa",
    "CPU 与主存连接时，数据总线的典型方向特征是（）。",
    ["双向传送", "只能由 CPU 单向传出", "只能由主存单向传出", "只传送地址而不传数据"], "A",
    "读操作时数据从主存到CPU，写操作时数据从CPU到主存，所以数据总线双向。",
    "read-write-directions", "读写两种操作的数据方向相反，需双向数据通路。",
    "bus-role", "数据总线承载数据本身，不同于通常由CPU给出的地址信息。",
    "分别跟踪主存读与写的数据方向。", "概括为数据总线的双向特性。", ["主存与CPU连接", "数据总线"])
add("hx32-408-sram-dram", "cs408.co.topic.2d6ca0bb88eb",
    "与 DRAM 相比，SRAM 的典型特点是（）。",
    ["无需周期性刷新，速度较快但集成度较低", "必须逐行刷新且容量密度最高", "断电后仍永久保存数据", "只能作为磁盘使用"], "A",
    "SRAM用双稳态电路保存位，不需周期刷新；其单元较复杂，常用于高速缓存。",
    "cell-circuit", "静态触发器保持状态，只要供电无需刷新。",
    "memory-hierarchy", "SRAM较快但面积成本较高，DRAM密度高用于主存。",
    "区分静态存储单元与电容存储单元。", "联系速度、刷新和应用层次。", ["半导体存储器", "SRAM", "DRAM"])
add("hx32-408-tlb", "cs408.co.topic.279ec6c06fe1",
    "分页虚拟存储系统中，TLB 命中通常可以避免（）。",
    ["为本次地址转换再访问主存中的页表项", "访问目标数据本身", "进行任何地址检查", "使用页内偏移"], "A",
    "TLB缓存近期页表项，命中即可获得物理页框号，减少一次内存页表访问；之后仍要访问数据。",
    "translation-cache", "命中直接返回页框号和权限信息，不需查主存页表。",
    "memory-access-sequence", "地址转换后仍需访问目标数据，故仅省去页表访存。",
    "区分地址转换与目标数据访问。", "追踪 TLB 命中时的访存序列。", ["虚拟存储器", "TLB"])
add("hx32-408-datapath-fetch", "cs408.co.topic.b06015ba34a3",
    "指令取指阶段，指令存储器读出的当前指令通常暂存于（）。",
    ["指令寄存器 IR", "程序状态字 PSW 的算术标志位", "数据地址寄存器 MAR 永久区", "Cache 替换计数器"], "A",
    "取出的指令送入指令寄存器IR供译码控制器分析。",
    "fetch-datapath", "从指令存储器输出的指令被锁存到IR。",
    "instruction-lifecycle", "译码阶段以IR中的指令字段为输入。",
    "跟踪取指输出的去向。", "确认译码器读取当前指令寄存器。", ["CPU数据通路", "取指", "IR"])
add("hx32-408-pipeline-throughput", "cs408.co.topic.7b4d965d0d36",
    "指令流水线通过重叠多条指令的不同阶段，主要提高（）。",
    ["单位时间完成的指令吞吐率", "单条指令必然减少的逻辑工作量", "主存容量", "指令集编码位数"], "A",
    "流水线重叠阶段提高稳态吞吐率，但单条指令延迟不必然缩短。",
    "stage-overlap", "不同指令同时占据不同流水段，提高并行利用率。",
    "latency-throughput", "流水线主要改善吞吐率，阶段总延迟和冒险会影响单条延迟。",
    "区分一条指令的延迟与连续指令完成速率。", "从各阶段重叠解释吞吐率提升。", ["指令流水线", "吞吐率"])
add("hx32-408-bus-bandwidth", "cs408.co.topic.27cae453c58a",
    "总线宽度为32 bit、时钟频率100 MHz，假定每周期传送一次且无额外开销，理论带宽为（）。",
    ["100 MB/s", "200 MB/s", "400 MB/s", "800 MB/s"], "C",
    "每次传送4字节，每秒10⁸次，带宽为4×10⁸字节/秒，即400 MB/s。",
    "width-frequency", "32 bit=4 byte，乘100 MHz得400 MB/s。",
    "unit-conversion", "4×10⁸ byte/s换算为400 MB/s。",
    "把总线宽度换算为字节。", "乘每秒传输次数并换算单位。", ["总线概念", "总线带宽"])
add("hx32-408-external-interrupt", "cs408.co.topic.cac9b3c3283b",
    "可屏蔽外部中断请求通常在处理器的什么时机被响应？",
    ["当前指令执行完成后检查并响应", "任意机器周期中途破坏当前指令", "仅系统关机时", "只在执行浮点乘法时"], "A",
    "处理器通常在指令边界检查可屏蔽中断，保存断点后转入中断服务程序。",
    "instruction-boundary", "外部请求异步到达，但处理器在指令边界进行架构级响应。",
    "precise-state", "在指令完成后响应有助于保存精确可恢复的程序状态。",
    "区分请求到达与CPU实际接收时机。", "从精确保存现场说明指令边界响应。", ["异常与中断", "中断响应时机"])
add("hx32-408-instruction-format", "cs408.co.topic.fbea44bd988b",
    "机器指令格式中的操作码字段主要用于指明（）。",
    ["要执行的操作类型", "主存中空闲块数量", "当前网络目的地址", "Cache 替换算法"], "A",
    "操作码编码指令执行的操作，如加法、访存或转移。",
    "decode-function", "控制器译码操作码以产生相应控制信号。",
    "field-role", "操作数地址和寄存器字段与操作码字段职责不同。",
    "识别指令中描述运算类型的字段。", "区分操作码与操作数定位字段。", ["指令格式", "操作码"])
add("hx32-408-indirect-address", "cs408.co.topic.0eeff5219603",
    "在一次间接寻址中，若指令地址字段为 A，则有效地址通常为（）。",
    ["主存单元 A 中存放的地址", "A 本身且不再访存", "操作码的二进制值", "程序计数器的固定初值"], "A",
    "间接寻址通过地址字段指向的存储单元读取有效地址，即 EA=M[A]。",
    "address-chain", "先用A访问存储器取出地址，再用该地址访问操作数。",
    "effective-address-definition", "与直接寻址EA=A不同，间接方式EA由M[A]给出。",
    "区分指令字段与操作数有效地址。", "按间接寻址多一级地址读取确定EA。", ["寻址方式", "间接寻址"])
add("hx32-408-cache-write-through", "cs408.co.topic.3b93ddd0af00",
    "Cache 写直达（write-through）策略下，CPU 对命中缓存块写数据时通常会（）。",
    ["同时更新 Cache 与下一级存储", "只更新 Cache 且永不回写", "立即清空 Cache", "把数据写到指令寄存器"], "A",
    "写直达在写操作时同步更新缓存和下一级存储，保持主存副本最新。",
    "write-policy-definition", "write-through按定义把每次写传播到下一级存储。",
    "consistency-state", "主存随每次缓存写更新，不需等待该块替换回写。",
    "追踪命中写操作对缓存的影响。", "检查下一级存储副本何时更新。", ["Cache写策略", "写直达"])
add("hx32-408-system-call", "cs408.os.topic.05dcc6b2951b",
    "用户程序执行系统调用时，通常通过什么机制受控地进入内核服务？",
    ["陷入/系统调用异常并切换到内核态", "普通函数返回到用户态且无特权级变化", "磁盘中断固定代替系统调用", "修改网卡MAC地址"], "A",
    "系统调用指令触发受控陷入，处理器切换到内核态并由内核分派服务。",
    "trap-entry", "陷入保存用户现场并转到预定内核入口。",
    "privilege-transition", "处理器特权级切换后才允许内核执行受保护操作。",
    "确定系统调用为何不能只是普通用户函数。", "跟踪陷入入口与特权级变化。", ["系统调用", "用户态与内核态"])

expected = {spec["node_code"] for spec in batch.CODEX_PUBLIC_ORIGINALS}
if len(batch.CODEX_PUBLIC_ORIGINALS) != 50 or len(expected) != 50:
    raise RuntimeError("batch32_must_target_50_unique_nodes")
if not expected.issubset(single):
    raise RuntimeError(f"batch32_targets_not_single_question_nodes:{sorted(expected-set(single))}")
if sum(code.startswith("math.") for code in expected) != 25:
    raise RuntimeError("batch32_math_count_mismatch")
if sum(code.startswith("cs408.") for code in expected) != 25:
    raise RuntimeError("batch32_408_count_mismatch")

if __name__ == "__main__":
    raise SystemExit(batch.main())
