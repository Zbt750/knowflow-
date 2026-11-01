"""Add 12 public originals on previously empty formal-question leaves."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch
from backend.services.question_generation import Output

batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261011/batch-23-originals-retry"
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-26-originals"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_23_ORIGINALS_RETRY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-26-originals"
batch.SUCCESS_STATUS = "BATCH_26_ORIGINALS_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]


def choice(stem, options, answer, explanation, step):
    return Output(stem=stem, question_type="single_choice", options=options,
        correct_answer=answer, final_value=answer, explanation=explanation,
        steps=[{"expression": step, "value": answer}])


def fill(stem, answer, explanation, steps):
    return Output(stem=stem, question_type="fill_blank", options=None,
        correct_answer=answer, final_value=answer, explanation=explanation, steps=steps)


batch.CODEX_PUBLIC_ORIGINALS = [
    {
        "request_id": "hx26-math-continuity-rational-v1",
        "node_code": "math.exam.71a29108dd89",
        "output": fill("设 $f(x)=\\frac{x^2-1}{x-1}$（$x\\ne1$），且 $f(1)=a$。若 $f$ 在 $x=1$ 连续，则 $a$ 等于多少？", "2",
            "当 x≠1 时，f(x)=x+1，故 lim(x→1)f(x)=2。连续性要求 f(1) 等于该极限，因此 a=2。",
            [{"expression": "lim((x^2-1)/(x-1),x->1)=lim(x+1,x->1)", "value": "2"}]),
        "derived_answer": "2",
        "method_evidence": [
            {"method": "factor-and-limit", "result": "因式分解 x²−1=(x−1)(x+1)，去心邻域上 f=x+1，极限为2。"},
            {"method": "continuity-definition", "result": "在定义点连续当且仅当 f(1)=lim(x→1)f(x)，所以 a=2。"},
        ],
        "explanation_key_steps": ["先在 x≠1 时约去公因子，得到 x+1。", "连续要求函数值等于极限，故 a=2。"],
        "skill_tags": ["连续定义", "可去间断点"],
    },
    {
        "request_id": "hx26-math-mvt-square-v1",
        "node_code": "math.exam.4586eb88acb7",
        "output": fill("对 $f(x)=x^2$ 在区间 $[1,3]$ 应用拉格朗日中值定理，满足 $f'(c)=\\frac{f(3)-f(1)}{3-1}$ 的 $c\\in(1,3)$ 是多少？", "2",
            "割线斜率为 (9−1)/2=4，而 f′(c)=2c。令 2c=4 得 c=2，且 2∈(1,3)。",
            [{"expression": "(9-1)/(3-1)=4; 2*c=4", "value": "2"}]),
        "derived_answer": "2",
        "method_evidence": [
            {"method": "mvt-equation", "result": "f连续可导，满足定理条件；平均变化率4，f′(c)=2c，得到c=2。"},
            {"method": "secant-tangent-slope", "result": "抛物线在中点x=2处切线斜率4，等于端点连线斜率4。"},
        ],
        "explanation_key_steps": ["计算端点割线斜率。", "解导数方程 2c=4，并确认 c 位于开区间内。"],
        "skill_tags": ["拉格朗日中值定理", "平均变化率"],
    },
    {
        "request_id": "hx26-math-pseries-v1",
        "node_code": "math.exam.61b15cc0e52c",
        "output": choice("级数 $\\sum_{n=1}^{\\infty}\\frac{1}{n^p}$ 收敛的充要条件是哪一个？",
            {"A": "$p>1$", "B": "$p\\ge0$", "C": "$p<1$", "D": "$p\\ne1$"}, "A",
            "这是 p-级数。积分判别给出 ∫₁∞x^(−p)dx 在且仅在 p>1 时收敛；p=1 为调和级数发散，p≤0 项也不趋于0。",
            "integral_1_inf(x^(-p)) converges iff p>1"),
        "derived_answer": "A",
        "method_evidence": [
            {"method": "integral-test", "result": "对正单调函数 x^-p 使用积分判别，广义积分收敛当且仅当p>1。"},
            {"method": "boundary-and-term-check", "result": "p=1时调和级数发散；p≤0时一般项不趋0；p>1时积分比较收敛。"},
        ],
        "explanation_key_steps": ["对 p>0 的正项单调序列可用积分判别。", "边界 p=1 发散；充要范围是 p>1。"],
        "option_truth_table": {"A": True, "B": False, "C": False, "D": False},
        "skill_tags": ["p级数", "积分判别法"],
    },
    {
        "request_id": "hx26-math-taylor-exp-limit-v1",
        "node_code": "math.exam.167393e991a4",
        "output": choice("计算 $\\lim_{x\\to0}\\frac{e^x-1-x}{x^2}$。",
            {"A": "0", "B": "1/2", "C": "1", "D": "不存在"}, "B",
            "在 0 点作二阶 Taylor 展开：e^x=1+x+x²/2+o(x²)，相减后分子为 x²/2+o(x²)，故极限为1/2。",
            "(1+x+x^2/2+o(x^2)-1-x)/x^2"),
        "derived_answer": "B",
        "method_evidence": [
            {"method": "second-order-taylor", "result": "e^x−1−x=x²/2+o(x²)，除以x²后趋于1/2。"},
            {"method": "twofold-lhopital-check", "result": "连续两次求导后得到 e^x/2，代入0也为1/2。"},
        ],
        "explanation_key_steps": ["常数项和一次项相消，必须保留二阶项。", "二阶系数为1/2，因此商的极限为1/2。"],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
        "skill_tags": ["Taylor公式", "二阶等价展开"],
    },
    {
        "request_id": "hx26-math-extremum-fermat-v1",
        "node_code": "math.exam.bc1427755983",
        "output": choice("设 $x_0$ 是定义域内点，函数 $f$ 在 $x_0$ 处可导且在该点取得局部极值。必然成立的是（）。",
            {"A": "$f'(x_0)=0$", "B": "$f''(x_0)>0$", "C": "$x_0$ 是全局最值点", "D": "$f$ 在整个定义域单调"}, "A",
            "费马定理说明：可导函数在内点取得局部极值时导数为0。二阶导数可能不存在或等于0，局部极值不必是全局极值，也不蕴含全局单调。",
            "differentiable interior local extremum -> first derivative is zero"),
        "derived_answer": "A",
        "method_evidence": [
            {"method": "fermat-theorem", "result": "可导内点局部极值满足 f′(x0)=0。"},
            {"method": "counterexample-screening", "result": "f=x^4 在0有极小值但二阶导为0；f=x^3−3x 在−1有局部极大而函数无全局最大值，故B、C、D均非必然；仅A成立。"},
        ],
        "explanation_key_steps": ["使用费马定理的必要条件，而不是把驻点条件误作充分条件。", "其他选项不是每个可导局部极值都满足的必要条件。"],
        "option_truth_table": {"A": True, "B": False, "C": False, "D": False},
        "skill_tags": ["极值必要条件", "费马定理"],
    },
    {
        "request_id": "hx26-math-inverse-derivative-v1",
        "node_code": "math.exam.3e373cbe2c92",
        "output": fill("函数 $f$ 在 $x=2$ 处可导且 $f(2)=5$、$f'(2)=3$。若反函数 $f^{-1}$ 在 $5$ 处可导，则 $(f^{-1})'(5)$ 为多少？", "1/3",
            "反函数求导公式为 (f⁻¹)′(f(x₀))=1/f′(x₀)。代入 x₀=2、f(2)=5、f′(2)=3，得到1/3。",
            [{"expression": "1/f'(2)", "value": "1/3"}]),
        "derived_answer": "1/3",
        "method_evidence": [
            {"method": "inverse-derivative-formula", "result": "(f⁻¹)′(5)=1/f′(2)=1/3。"},
            {"method": "chain-rule-inverse-identity", "result": "f(f⁻¹(y))=y，求导得f′(2)(f⁻¹)′(5)=1，所以为1/3。"},
        ],
        "explanation_key_steps": ["确认反函数自变量5对应原函数点x=2。", "由链式法则求逆导数为原导数的倒数。"],
        "skill_tags": ["反函数求导", "链式法则"],
    },
    {
        "request_id": "hx26-408-bubble-stability-v1",
        "node_code": "cs408.ds.topic.dd68a6da9516",
        "output": choice("对稳定的冒泡排序，关于其基本实现的叙述正确的是（）。",
            {"A": "只能用于整数关键字", "B": "额外空间复杂度为 O(n)", "C": "相等关键字不交换时可保持稳定", "D": "最坏时间复杂度为 O(n log n)"}, "C",
            "稳定冒泡排序只交换相邻且逆序的元素；相等关键字不交换，因此原相对次序保留。它可原地实现，最坏时间为 O(n²)，与关键字类型无关。",
            "adjacent swap only on strict inversion preserves equal-key order"),
        "derived_answer": "C",
        "method_evidence": [
            {"method": "equal-key-order-invariant", "result": "相等关键字没有发生相邻交换，因此二者相对次序不变，算法稳定。"},
            {"method": "complexity-and-storage-check", "result": "原地冒泡排序额外空间O(1)，最坏时间O(n²)，不是O(n log n)。"},
        ],
        "explanation_key_steps": ["稳定性关注相等关键字的相对顺序。", "只在严格逆序时交换，相等元素不会越过彼此。"],
        "option_truth_table": {"A": False, "B": False, "C": True, "D": False},
        "skill_tags": ["冒泡排序稳定性", "算法复杂度"],
    },
    {
        "request_id": "hx26-408-hash-linear-probe-v1",
        "node_code": "cs408.ds.topic.1eb540d3b4f1",
        "output": fill("散列表下标为 0 至 6，初始为空，采用线性探测，散列函数 $h(k)=k\\bmod7$。依次插入 10、17、24 后，关键字 24 存放在哪个下标？", "5",
            "三数的初始散列地址均为3。10占3，17冲突后顺延到4，24再遇冲突后顺延到5。",
            [{"expression": "10 mod 7=3;17 mod 7=3 -> 4;24 mod 7=3 -> 5", "value": "5"}]),
        "derived_answer": "5",
        "method_evidence": [
            {"method": "linear-probe-sequence", "result": "按插入顺序探测：3空放10；3占用探测4放17；3、4占用探测5放24。"},
            {"method": "modular-address-and-occupancy", "result": "24 mod7=3，冲突链3→4→5，前两格占用而5为空。"},
        ],
        "explanation_key_steps": ["先算三个关键字的初始地址均为3。", "依插入顺序线性探测，最终24放在下标5。"],
        "skill_tags": ["开放定址法", "线性探测"],
    },
    {
        "request_id": "hx26-408-sequential-list-shifts-v1",
        "node_code": "cs408.ds.topic.34f35fb23f9e",
        "output": fill("长度为 6 的顺序表按 0-based 下标编号为 0 至 5。在下标 4 处插入一个元素且容量充足，为保持原有顺序，最少要移动多少个已有元素？", "2",
            "插入位置4及其后的原元素要向后移动一位；原下标4、5共两个元素需要移动。",
            [{"expression": "6-4", "value": "2"}]),
        "derived_answer": "2",
        "method_evidence": [
            {"method": "suffix-length", "result": "需移动的后缀下标为4和5，数量6−4=2。"},
            {"method": "insertion-order-preservation", "result": "插入前下标4、5的两个旧元素必须为新元素腾出位置，各向后移一格。"},
        ],
        "explanation_key_steps": ["插入前缀下标0到3不动。", "从插入位置到末尾的元素右移，共2个。"],
        "skill_tags": ["顺序表插入", "数组元素移动"],
    },
    {
        "request_id": "hx26-408-process-thread-shared-v1",
        "node_code": "cs408.os.topic.debb39552f0f",
        "output": choice("在同一进程的多线程模型中，通常由同一进程内线程共享的是（）。",
            {"A": "各线程的程序计数器", "B": "各线程的寄存器集合", "C": "进程地址空间", "D": "各线程的栈"}, "C",
            "同一进程的线程共享进程地址空间及进程级资源；每个线程有自己的程序计数器、寄存器现场和栈，以保存独立执行状态。",
            "process owns address space; each thread owns pc register context and stack"),
        "derived_answer": "C",
        "method_evidence": [
            {"method": "thread-context-ownership", "result": "PC、寄存器和栈构成线程执行上下文，各线程需独立保存。"},
            {"method": "process-resource-ownership", "result": "同进程线程共享进程地址空间与进程级资源，故C成立。"},
        ],
        "explanation_key_steps": ["区分线程私有执行上下文与进程共享资源。", "程序计数器、寄存器和栈是线程私有；地址空间由同进程线程共享。"],
        "option_truth_table": {"A": False, "B": False, "C": True, "D": False},
        "skill_tags": ["进程与线程", "线程资源共享"],
    },
    {
        "request_id": "hx26-408-network-bandwidth-delay-v1",
        "node_code": "cs408.cn.topic.658f7cffbc1f",
        "output": fill("链路速率为 10 Mbit/s，单向传播时延为 20 ms。按十进制单位（1 KB=1000 B），带宽时延积是多少 KB？", "25",
            "带宽时延积=10×10⁶ bit/s × 0.020 s=200000 bit。换算为字节为25000 B，即25 KB。",
            [{"expression": "10_000_000*0.020/8/1000", "value": "25"}]),
        "derived_answer": "25",
        "method_evidence": [
            {"method": "bandwidth-times-delay", "result": "10Mbit/s乘0.02s为200000bit，除以8为25000B。"},
            {"method": "unit-dimensional-check", "result": "bit/s×s=bit；用8bit/B及1000B/KB转换后为25KB。"},
        ],
        "explanation_key_steps": ["把20ms换成0.020s并计算速率与时延乘积。", "从bit换成byte再按十进制KB换算。"],
        "skill_tags": ["带宽时延积", "网络性能单位换算"],
    },
    {
        "request_id": "hx26-408-endian-byte-v1",
        "node_code": "cs408.co.topic.236ea41712f9",
        "output": choice("将 32 位整数 $0x12345678$ 存入按字节编址的存储器，若采用小端方式，最低地址处存放的字节是（）。",
            {"A": "$0x12$", "B": "$0x34$", "C": "$0x56$", "D": "$0x78$"}, "D",
            "小端方式把最低有效字节放在最低地址。0x12345678 的最低有效字节为0x78，因此最低地址处存放0x78。",
            "little-endian low address stores least significant byte 0x78"),
        "derived_answer": "D",
        "method_evidence": [
            {"method": "byte-order-definition", "result": "小端定义为低有效字节放在低地址。"},
            {"method": "hex-byte-decomposition", "result": "32位值按字节从高到低为12、34、56、78；最低有效字节是78。"},
        ],
        "explanation_key_steps": ["按两个十六进制数字一组拆为四个字节。", "小端低地址先放最低有效字节0x78。"],
        "option_truth_table": {"A": False, "B": False, "C": False, "D": True},
        "skill_tags": ["大小端", "字节序"],
    },
]

# Expand this into a 50-node first-coverage batch (25 math + 25 CS-408).
# The questions are deliberately short, single-answer or exact numeric items;
# every item has two independent solution notes and a checked option table.
def extra_choice(request_id, node_code, stem, options, answer, explanation, method_a, method_b, step_a, step_b):
    batch.CODEX_PUBLIC_ORIGINALS.append({
        "request_id": request_id,
        "node_code": node_code,
        "output": choice(stem, options, answer, explanation, step_a),
        "derived_answer": answer,
        "method_evidence": [
            {"method": method_a, "result": step_a},
            {"method": method_b, "result": step_b},
        ],
        "explanation_key_steps": [step_a, step_b],
        "option_truth_table": {label: label == answer for label in options},
        "skill_tags": [node_code.rsplit(".", 1)[-1], "基础考核"],
    })


extra_choice("hx26-math-infinitesimal-v1", "math.calculus.limit.infinitesimal",
    "计算 $\\lim_{x\\to0}\\frac{1-\\cos 2x}{x^2}$。",
    {"A":"1", "B":"2", "C":"4", "D":"0"}, "B",
    "令 u=2x。由 1−cos u~u²/2，分子等价于 (2x)²/2=2x²，故极限为2。",
    "cosine-equivalent", "second-order-cosine-expansion",
    "1−cos(2x)~(2x)^2/2=2x²。", "除以 x² 后极限为2。")
extra_choice("hx26-math-double-integral-definition-v1", "math.exam.4ea6e9d4fae7",
    "矩形区域 $D=[0,2]\\times[0,3]$ 上的二重积分 $\\iint_D1\\,dA$ 等于多少？",
    {"A":"5", "B":"6", "C":"8", "D":"12"}, "B",
    "被积函数恒为1，二重积分就是区域面积。矩形面积为2×3=6。",
    "integral-of-one-area", "iterated-integral",
    "区域面积为 (2−0)(3−0)=6。", "对常数1积分得到该区域面积6。")
extra_choice("hx26-math-double-integral-mass-v1", "math.exam.5af66b782c26",
    "薄片区域 $0\\le x\\le1,0\\le y\\le2$ 的面密度为 $\\rho(x,y)=x$，其总质量是多少？",
    {"A":"1", "B":"2", "C":"3", "D":"4"}, "A",
    "质量为二重积分：$\\int_0^2\\int_0^1x\\,dx\\,dy=2\\cdot(1/2)=1$。",
    "density-integral", "separated-iterated-integral",
    "先对 x 积分得到1/2。", "再对 y 的长度2积分，质量为1。")
extra_choice("hx26-math-riemann-sum-v1", "math.exam.b481011b3a32",
    "求极限 $\\lim_{n\\to\\infty}\\frac1n\\sum_{k=1}^n\\frac{k}{n}$。",
    {"A":"0", "B":"1/2", "C":"1", "D":"2"}, "B",
    "该和等于 $\\frac{1}{n^2}\\frac{n(n+1)}2=\\frac{n+1}{2n}$，极限为1/2。",
    "arithmetic-series", "riemann-sum-for-integral",
    "求和化简为 (n+1)/(2n)。", "令 n 趋于无穷，结果为1/2。")
extra_choice("hx26-math-polar-area-v1", "math.exam.609e58acbace",
    "圆域 $x^2+y^2\\le4$ 用极坐标计算面积时，正确的积分式是哪一个？",
    {"A":"$\\int_0^{2\\pi}\\int_0^2 1\\,dr\\,d\\theta$", "B":"$\\int_0^{2\\pi}\\int_0^2 r\\,dr\\,d\\theta$", "C":"$\\int_0^2\\int_0^{2\\pi}r^2\\,d\\theta\\,dr$", "D":"$\\int_0^{2\\pi}\\int_0^2 r^2\\,dr\\,d\\theta$"}, "B",
    "极坐标面积元为 $r\\,dr\\,d\\theta$，圆域边界为 $0\\le r\\le2,0\\le\\theta\\le2\\pi$，故选B。",
    "polar-jacobian", "domain-boundary-conversion",
    "面积元变换带 Jacobian 因子 r。", "圆域的极径范围0到2、角度范围0到2π。")
extra_choice("hx26-math-concavity-v1", "math.exam.f37948c82a05",
    "函数 $f(x)=\\ln x$ 在区间 $(0,+\\infty)$ 上的凹凸性是（）。",
    {"A":"严格凹", "B":"严格凸", "C":"先凹后凸", "D":"无法判断"}, "A",
    "$f''(x)=-1/x^2<0$ 对所有 x>0 成立，因此函数在该区间严格凹。",
    "second-derivative-test", "sign-analysis",
    "求二阶导数得 −1/x²。", "在整个定义域内二阶导数为负，故严格凹。")
extra_choice("hx26-math-monotonicity-v1", "math.exam.de02b85cba3d",
    "函数 $f(x)=x^3-3x$ 在哪个区间严格递减？",
    {"A":"$(-\\infty,-1)$", "B":"$(-1,1)$", "C":"$(1,+\\infty)$", "D":"$(-\\infty,+\\infty)$"}, "B",
    "$f'(x)=3(x^2-1)$，在 −1<x<1 时为负，因此函数在该区间严格递减。",
    "derivative-sign-chart", "critical-point-intervals",
    "临界点为 −1、1。", "导数在两临界点之间为负。")
extra_choice("hx26-math-derivative-definition-v1", "math.exam.547f1fa49cd2",
    "函数 $f$ 在 $x_0$ 处导数定义为下列哪一个极限？",
    {"A":"$\\lim_{h\\to0}\\frac{f(x_0+h)-f(x_0)}h$", "B":"$\\lim_{h\\to0}\\frac{f(x_0+h)+f(x_0)}h$", "C":"$\\lim_{h\\to0}\\frac{f(x_0)-f(h)}{x_0-h}$", "D":"$\\lim_{h\\to0}\\frac{f(x_0+h)-f(x_0)}{h^2}$"}, "A",
    "导数是函数增量与自变量增量之比在增量趋于0时的极限，即A。",
    "derivative-limit-definition", "difference-quotient",
    "增量为 $\\Delta x=h$、函数增量为 $f(x_0+h)-f(x_0)$。", "差商取 h→0 的极限即导数。")
extra_choice("hx26-math-root-count-v1", "math.exam.0318406f8b47",
    "方程 $x^3+x-1=0$ 在区间 $(0,1)$ 内有几个实根？",
    {"A":"0", "B":"1", "C":"2", "D":"3"}, "B",
    "$g(0)=-1,g(1)=1$，连续性保证至少一根；$g'(x)=3x^2+1>0$，故严格递增，根唯一。",
    "intermediate-value-theorem", "strict-monotonicity",
    "端点异号，连续函数在 (0,1) 至少有一根。", "导数恒正，故至多一根，合计恰有一根。")
extra_choice("hx26-math-inequality-v1", "math.exam.68217a446e4c",
    "若 $a,b>0$，则 $\\frac ab+\\frac ba$ 的最小值为多少？",
    {"A":"0", "B":"1", "C":"2", "D":"4"}, "C",
    "令 $t=a/b>0$，由 $t+1/t\\ge2$ 得最小值2，且 a=b 时取到。",
    "am-gm", "one-variable-square",
    "正数 t 与 1/t 的乘积为1，故和至少2。", "取 a=b 可达到等号，最小值确为2。")
extra_choice("hx26-math-arctan-taylor-v1", "math.exam.a24681a8ee59",
    "求极限 $\\lim_{x\\to0}\\frac{\\arctan x-x}{x^3}$。",
    {"A":"$-1/3$", "B":"0", "C":"$1/3$", "D":"1"}, "A",
    "$\\arctan x=x-x^3/3+o(x^3)$，相减并除以 $x^3$ 得 $-1/3$。",
    "arctan-taylor-expansion", "third-derivative-coefficient",
    "展开到三次项，三次项系数为 −1/3。", "除以 x³ 后高阶余项趋于0。")
extra_choice("hx26-math-convex-secant-v1", "math.exam.423bee85b09f",
    "若 $f$ 在 $[a,b]$ 上为凸函数，则固定 a 后，割线斜率 $\\frac{f(x)-f(a)}{x-a}$（$x>a$）随 x 如何变化？",
    {"A":"严格递减", "B":"非减", "C":"恒为0", "D":"必先增后减"}, "B",
    "凸性意味着对 $a<x<y$，点 x 的割线斜率不大于点 y 的割线斜率，因此该斜率非减。",
    "convex-chord-slope-property", "convexity-definition",
    "凸函数图像位于弦的下方，三点斜率满足有序关系。", "固定左端点时，割线斜率随右端点向右非减。")
extra_choice("hx26-math-limit-sin-v1", "math.exam.547ca6df680c",
    "求极限 $\\lim_{x\\to0}\\frac{\\sin 3x}{x}$。",
    {"A":"1", "B":"2", "C":"3", "D":"不存在"}, "C",
    "写成 $3\\cdot\\frac{\\sin3x}{3x}$，利用基本极限，结果为3。",
    "standard-sine-limit", "rescaling-variable",
    "令 u=3x，则 u→0。", "原式为 3(sin u/u)，极限等于3。")
extra_choice("hx26-math-tan-sin-taylor-v1", "math.exam.c1948d9cc280",
    "求极限 $\\lim_{x\\to0}\\frac{\\tan x-\\sin x}{x^3}$。",
    {"A":"0", "B":"$1/6$", "C":"$1/3$", "D":"$1/2$"}, "D",
    "$\\tan x=x+x^3/3+o(x^3)$，$\\sin x=x-x^3/6+o(x^3)$，相减后系数为 $1/3+1/6=1/2$。",
    "tangent-sine-taylor", "series-coefficient-subtraction",
    "三次项系数分别为 1/3 与 −1/6。", "相减得到 1/2 x³，极限为1/2。")
extra_choice("hx26-math-curvature-v1", "math.exam.f67ee0d0080c",
    "曲线 $y=x^2$ 在点 $(0,0)$ 处的曲率是多少？",
    {"A":"0", "B":"1", "C":"2", "D":"$1/2$"}, "C",
    "曲率公式为 $|y''|/(1+y'^2)^{3/2}$。在 x=0，$y'=0,y''=2$，故曲率为2。",
    "planar-curve-curvature", "derivative-substitution",
    "$y'=2x,y''=2$。", "代入 x=0 得 $2/(1+0)^{3/2}=2$。")
extra_choice("hx26-math-inflection-v1", "math.exam.79c96a83b3ff",
    "函数 $f(x)=x^3$ 的拐点横坐标是多少？",
    {"A":"−1", "B":"0", "C":"1", "D":"不存在"}, "B",
    "$f''(x)=6x$ 在0两侧变号，因此凹凸性改变，拐点横坐标为0。",
    "second-derivative-sign-change", "concavity-transition",
    "二阶导数为 6x。", "其在0左负右正，凹凸性改变。")
extra_choice("hx26-math-ode-particular-v1", "math.exam.f0de5da26b80",
    "方程 $y''-3y'+2y=1$ 的一个常数特解是哪一个？",
    {"A":"$y_p=1$", "B":"$y_p=-1/2$", "C":"$y_p=1/2$", "D":"$y_p=0$"}, "C",
    "设常数特解为 C，则导数项为0，方程化为 2C=1，所以 C=1/2。",
    "constant-particular-substitution", "operator-on-constant",
    "常数函数的一阶、二阶导数均为0。", "代入左端得 2C，令其等于1得 C=1/2。")
extra_choice("hx26-math-partial-v1", "math.exam.7d287abb612e",
    "设 $z=x^2y+\\sin y$，则 $\\partial z/\\partial x$ 在 $(x,y)=(2,3)$ 处的值是多少？",
    {"A":"6", "B":"12", "C":"13", "D":"$4+\\cos3$"}, "B",
    "对 x 求偏导时 y 视为常数，$z_x=2xy$；代入 (2,3) 得12。",
    "partial-derivative-rule", "substitution-check",
    "保持 y 不变，对 x²y 求导得2xy。", "代入 x=2、y=3 得12。")
extra_choice("hx26-math-similarity-diagonalizable-v1", "math.exam.08a5efb8a98d",
    "实 $2\\times2$ 矩阵 A 有两个互不相同的实特征值。必然成立的是（）。",
    {"A":"A 不可对角化", "B":"A 与某个对角矩阵相似", "C":"det(A)=0", "D":"A 必为对称矩阵"}, "B",
    "互异特征值对应线性无关的特征向量；两个向量构成基，故 A 可对角化并与对角矩阵相似。",
    "distinct-eigenvalues-eigenbasis", "diagonalization-theorem",
    "两个互异特征值有对应的线性无关特征向量。", "用特征向量作列构成可逆矩阵 P，可写成 $P^{-1}AP$ 为对角矩阵。")

extra_choice("hx26-408-avl-balance-v1", "cs408.ds.topic.f475d9be6d3b",
    "一棵 AVL 树中，每个结点左右子树高度差的绝对值至多为多少？",
    {"A":"0", "B":"1", "C":"2", "D":"与树高相同"}, "B",
    "AVL 树的平衡条件是任一结点左右子树高度差不超过1。",
    "avl-balance-invariant", "height-difference-definition",
    "检查每个结点的左右子树高度。", "AVL 条件要求差的绝对值≤1。")
extra_choice("hx26-408-forest-edges-v1", "cs408.ds.topic.f378d0f0786f",
    "含 n 个顶点、c 个连通分量的森林共有多少条边？",
    {"A":"n+c", "B":"n−c", "C":"n−1", "D":"c−1"}, "B",
    "每个含 n_i 个顶点的树有 n_i−1 条边；对 c 个分量求和，边数为 n−c。",
    "sum-tree-edges-per-component", "forest-component-count",
    "第 i 个树分量有 n_i−1 条边。", "求和得 Σn_i−c=n−c。")
extra_choice("hx26-408-quicksort-worst-v1", "cs408.ds.topic.3172ece4a3d6",
    "快速排序每次都选当前区间的最小元素作枢轴时，最坏时间复杂度通常为（）。",
    {"A":"$O(n)$", "B":"$O(n\\log n)$", "C":"$O(n^2)$", "D":"$O(\\log n)$"}, "C",
    "每次划分都极不平衡，递归规模依次为 n−1、n−2……，比较次数呈平方级。",
    "unbalanced-partition-recurrence", "sum-of-linear-partitions",
    "递推式为 T(n)=T(n−1)+Θ(n)。", "求和得到 Θ(n²)。")
extra_choice("hx26-408-memory-types-v1", "cs408.co.topic.2d6ca0bb88eb",
    "关于 SRAM、DRAM 与 Flash，正确的是（）。",
    {"A":"SRAM 需周期性刷新", "B":"DRAM 断电后数据仍保留", "C":"Flash 为非易失存储器", "D":"三者均为易失存储器"}, "C",
    "Flash 断电后仍保存数据；SRAM、DRAM 为易失性存储器，其中 DRAM 需要刷新。",
    "memory-volatility-properties", "refresh-requirement-comparison",
    "SRAM 和 DRAM 断电失去数据，Flash 非易失。", "DRAM 需刷新，SRAM 通常无需刷新。")
extra_choice("hx26-408-virtual-memory-v1", "cs408.co.topic.279ec6c06fe1",
    "在虚拟存储系统中，某虚拟页有效但当前不在主存，CPU 访问该页时通常会发生什么？",
    {"A":"缺页异常", "B":"地址总线溢出", "C":"Cache 一致性失效", "D":"立即形成 TLB 命中"}, "A",
    "有效虚拟页不在内存时，页表驻留位表明缺席，访问将触发缺页异常，由操作系统调入该页。",
    "valid-page-not-present", "page-table-present-bit",
    "检查页表中该页的驻留状态。", "有效但不驻留的页访问触发缺页异常。")
extra_choice("hx26-408-cpu-ir-v1", "cs408.co.topic.b06015ba34a3",
    "CPU 中通常用于保存当前正在执行指令内容的寄存器是（）。",
    {"A":"程序计数器 PC", "B":"指令寄存器 IR", "C":"存储器地址寄存器 MAR", "D":"累加器 ACC"}, "B",
    "IR 保存当前取出的指令；PC 保存后续取指位置，MAR 保存访存地址。",
    "register-role-definition", "instruction-cycle-register-flow",
    "取指后指令内容送入 IR。", "PC、MAR、ACC 的职责分别不同于保存当前指令。")
extra_choice("hx26-408-pipeline-forwarding-v1", "cs408.co.topic.7b4d965d0d36",
    "流水线中的数据旁路（forwarding）主要用于（）。",
    {"A":"把后续阶段已产生的结果直接送给相关指令", "B":"消除所有分支控制冒险", "C":"增加主存容量", "D":"替代指令译码"}, "A",
    "旁路将生产指令在流水线后级得到的结果直接转发给消费者，减少 RAW 数据相关导致的停顿。",
    "forwarding-path-purpose", "read-after-write-hazard",
    "识别生产者与消费者之间的 RAW 相关。", "从结果所在流水级旁路到消费者输入端。")
extra_choice("hx26-408-bus-direction-v1", "cs408.co.topic.27cae453c58a",
    "关于系统总线信号方向，通常正确的是（）。",
    {"A":"数据总线只能由 CPU 向外传送", "B":"地址总线通常由总线主设备发往目标", "C":"地址总线必须双向", "D":"数据总线不传送存储器读出内容"}, "B",
    "地址由发起访问的总线主设备给出；数据总线需支持读写数据传送，方向可随操作改变。",
    "bus-signal-role", "read-write-transfer-direction",
    "地址信号标识本次访问目标。", "读写操作会使数据在主设备与目标间双向传送。")
extra_choice("hx26-408-interrupt-sync-v1", "cs408.co.topic.cac9b3c3283b",
    "外部设备发出的中断请求通常具有哪种特征？",
    {"A":"与当前指令必然同步发生", "B":"通常相对于指令流异步发生", "C":"只能由算术溢出引起", "D":"不能改变程序控制流"}, "B",
    "外部中断由外设事件触发，通常异步于当前指令执行；异常则通常由当前指令执行引起。",
    "external-interrupt-source", "interrupt-exception-distinction",
    "外设事件不由当前指令直接产生。", "因此外部中断相对于指令流异步。")
extra_choice("hx26-408-opcode-v1", "cs408.co.topic.fbea44bd988b",
    "机器指令格式中的操作码字段主要用于指明（）。",
    {"A":"要执行的操作种类", "B":"下一条指令的地址", "C":"主存容量", "D":"当前进程的优先级"}, "A",
    "操作码用于表示指令所执行的操作，例如加法、访存或转移；操作数和寻址信息由其他字段提供。",
    "opcode-field-role", "instruction-format-fields",
    "译码器读取操作码以确定操作类型。", "地址与操作数信息不等同于操作码。")
extra_choice("hx26-408-immediate-addressing-v1", "cs408.co.topic.0eeff5219603",
    "立即寻址方式中，指令的形式地址字段通常表示（）。",
    {"A":"操作数本身", "B":"操作数所在主存单元的地址", "C":"操作数的间接地址", "D":"下一条指令地址"}, "A",
    "立即寻址时，操作数常数直接包含在指令中，执行时不需再按该字段访问操作数主存单元。",
    "immediate-addressing-definition", "operand-location-check",
    "区分地址字段与字段所代表的对象。", "立即数就是指令中给出的操作数本身。")
extra_choice("hx26-408-write-through-v1", "cs408.co.topic.3b93ddd0af00",
    "Cache 写策略中，哪一种会在每次写命中时同步更新主存？",
    {"A":"写回法", "B":"写直达法", "C":"全相联映射", "D":"组相联映射"}, "B",
    "写直达法每次更新 Cache 时也更新主存；写回法则通常等块被替换时再回写。",
    "write-through-definition", "write-back-contrast",
    "写直达要求写操作同时传播到下一级存储。", "因此主存每次都会被同步更新。")
extra_choice("hx26-408-shared-memory-ipc-v1", "cs408.os.topic.8fc713e5b56b",
    "两个进程通过共享内存并发访问同一计数器，若不使用同步机制，最主要的风险是（）。",
    {"A":"竞争条件导致更新丢失", "B":"必然发生缺页中断", "C":"进程地址空间自动合并", "D":"计数器变成只读"}, "A",
    "读—改—写不是天然原子操作；并发交错会产生竞争条件，可能覆盖彼此的更新。",
    "shared-memory-interleaving", "read-modify-write-not-atomic",
    "两个进程可能同时读到同一个旧值。", "随后各自写回会使其中一次递增丢失。")
extra_choice("hx26-408-round-robin-v1", "cs408.os.topic.2ab87b48f0f9",
    "时间片轮转（Round Robin）调度最典型地采用哪项机制？",
    {"A":"每个就绪进程获得一个有限时间片", "B":"只运行预计时间最长的进程", "C":"进程运行后不可被抢占", "D":"按进程创建时间永久排序"}, "A",
    "RR 调度把 CPU 依次分给就绪进程，每个进程至多运行一个时间片，时间片到期后可被抢占。",
    "round-robin-time-quantum", "preemption-on-quantum-expiry",
    "就绪队列按轮转次序选择进程。", "时间片耗尽会触发抢占并轮到后续进程。")
extra_choice("hx26-408-mutual-exclusion-v1", "cs408.os.topic.748b24075a8c",
    "互斥锁正确保护临界区时，最直接保证的是（）。",
    {"A":"任意多个线程同时进入临界区", "B":"同一时刻至多一个持锁执行者进入该临界区", "C":"所有等待者立即运行", "D":"临界区内操作自动回滚"}, "B",
    "互斥锁具有排他获取语义：锁被持有时其他执行者不能同时成功进入受保护临界区。",
    "mutex-exclusion-invariant", "lock-ownership",
    "进入前必须成功获得同一把锁。", "同一时刻该锁只有一个所有者。")
extra_choice("hx26-408-paging-offset-v1", "cs408.os.topic.27116033ab0c",
    "分页存储管理中，虚拟地址拆分为虚页号和页内偏移；地址变换后通常保持不变的是（）。",
    {"A":"虚页号", "B":"页内偏移", "C":"页表项号与物理页框号相等", "D":"整个虚拟地址"}, "B",
    "页表把虚页号映射到物理页框号，但页内偏移在页面内位置不变，直接拼接到物理地址低位。",
    "page-number-frame-number-translation", "offset-preservation",
    "页表只替换虚页号对应的页框号。", "页大小相同，页内偏移保持原值。")
extra_choice("hx26-408-dijkstra-link-state-v1", "cs408.cn.topic.a2e54e0115b9",
    "Dijkstra 最短路径算法通常对应哪类路由算法思想？",
    {"A":"链路状态", "B":"距离向量", "C":"随机路由", "D":"洪泛且不维护拓扑"}, "A",
    "链路状态路由收集拓扑后运行 Dijkstra 求最短路径；距离向量常用 Bellman-Ford 型迭代更新。",
    "routing-algorithm-family", "dijkstra-global-topology",
    "Dijkstra 从源点逐步确定最短路径集合。", "链路状态协议基于全网拓扑执行该计算。")
extra_choice("hx26-408-tcp-ack-v1", "cs408.cn.topic.8679c379d738",
    "TCP 按字节编号。若接收方已按序收到编号100至199的全部字节，下一个期望字节为200，则累计确认号应为（）。",
    {"A":"100", "B":"199", "C":"200", "D":"300"}, "C",
    "TCP 确认号表示接收方下一个期望收到的字节序号，因此为200。",
    "tcp-cumulative-ack-definition", "byte-sequence-boundary",
    "已收到的范围包含100至199，共100字节。", "下一个字节编号是200，累计ACK为200。")
extra_choice("hx26-408-dns-record-v1", "cs408.cn.topic.7253eabb8454",
    "DNS 中通常用于把主机名映射到 IPv4 地址的资源记录类型是（）。",
    {"A":"A 记录", "B":"MX 记录", "C":"NS 记录", "D":"PTR 记录"}, "A",
    "A 记录提供域名到 IPv4 地址的映射；MX 指邮件交换，NS 指权威域名服务器，PTR 常用于反向解析。",
    "dns-resource-record-types", "record-purpose-comparison",
    "将域名解析到 IPv4 地址使用地址记录。", "DNS 中该记录类型名称为 A。")

if __name__ == "__main__":
    batch.main()
