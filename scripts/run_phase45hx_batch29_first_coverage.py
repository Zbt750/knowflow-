"""Batch 29: first qualified public-original coverage for the next 50 empty nodes."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-28-first-coverage"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_28_FIRST_COVERAGE_COMPLETE":
    raise RuntimeError("batch28_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch28_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-29-first-coverage"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_28_FIRST_COVERAGE_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-29-first-coverage"
batch.SUCCESS_STATUS = "BATCH_29_FIRST_COVERAGE_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = [
    "-k",
    "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy",
]
batch.CODEX_PUBLIC_ORIGINALS = []

empty = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 0
}


def add(req, node, stem, choices, answer, explanation,
        method1, result1, method2, result2, step1, step2, skills):
    if node not in empty:
        raise RuntimeError(f"target_not_empty_in_batch28:{node}")
    batch.CODEX_PUBLIC_ORIGINALS.append({
        "request_id": req,
        "node_code": node,
        "output": base.choice(
            stem, {chr(65 + i): value for i, value in enumerate(choices)},
            answer, explanation, f"independent-check:{method1}; {method2} -> {answer}",
        ),
        "derived_answer": answer,
        "method_evidence": [
            {"method": method1, "result": f"独立路径一（{method1}）：{result1}；核得答案 {answer}。"},
            {"method": method2, "result": f"独立路径二（{method2}）：{result2}；复核答案 {answer}。"},
        ],
        "explanation_key_steps": [f"第一步：{step1}", f"第二步：{step2}"],
        "option_truth_table": {chr(65 + i): chr(65 + i) == answer for i in range(4)},
        "skill_tags": skills,
    })


# The Math II inventory has 19 empty assessable topics remaining.
add("hx29-math-other-ode", "math.exam.21e0818406c9",
    r"初值问题 $y'+2y=0,\\ y(0)=4$ 的解在 $x=\\ln2$ 处等于多少？",
    ["1", "2", "4", "8"], "A",
    r"积分因子为 $e^{2x}$，故 $y=4e^{-2x}$；代入 $x=\ln2$ 得 $4/4=1$。",
    "integrating-factor", "乘以 $e^{2x}$ 后 $(e^{2x}y)'=0$，由初值解得 $y=4e^{-2x}$。",
    "direct-substitution", r"将 $y=4e^{-2x}$ 代回方程满足初值，再代 $x=\ln2$ 得1。",
    "求积分因子并解出通解。", "用初值定常数并代入指定自变量。", ["一阶微分方程", "初值问题"])
add("hx29-math-matrix-equation-condition", "math.exam.36050d277510",
    r"线性方程组 $\begin{pmatrix}1&2\\2&4\end{pmatrix}\binom{x}{y}=\binom{1}{k}$ 有解的条件是（）。",
    ["$k=0$", "$k=1$", "$k=2$", "任意实数 k"], "C",
    "第二行是第一行的2倍，因此右端也必须满足第二个分量等于第一个分量的2倍，即 $k=2$。",
    "row-dependence", "系数矩阵第二行等于第一行的2倍，增广列必须保持同一线性关系，故 $k=2$。",
    "rank-consistency", "当 $k=2$ 时两行方程一致且可解；否则系数行相关而增广常数不相容。",
    "比较两行系数的倍数关系。", "用增广矩阵秩与系数矩阵秩相等条件核对。", ["线性方程组", "有解条件"])
add("hx29-math-vector-representation", "math.exam.9a1731a929ab",
    "向量 $(3,2)$ 表示为 $a(1,0)+b(1,1)$，则 $(a,b)$ 等于（）。",
    ["$(1,2)$", "$(2,1)$", "$(3,2)$", "$(1,3)$"], "A",
    "比较第二分量得 $b=2$，第一分量给出 $a+b=3$，所以 $a=1$。",
    "coordinate-equations", "分量比较给出 $a+b=3$ 与 $b=2$，解得 $(a,b)=(1,2)$。",
    "basis-matrix-inverse", "系数矩阵列向量组成上三角矩阵，解其线性方程同样得到 $a=1,b=2$。",
    "按坐标写出两个标量方程。", "先由第二坐标求 b，再回代求 a。", ["向量线性表示", "坐标方程"])
add("hx29-math-matrix-identity", "math.exam.712e07e16572",
    r"设 $A=\begin{pmatrix}1&1\\0&1\end{pmatrix}$，则 $A^2$ 等于（）。",
    [r"$\begin{pmatrix}1&2\\0&1\end{pmatrix}$", r"$\begin{pmatrix}1&1\\0&1\end{pmatrix}$", "$I$", r"$\begin{pmatrix}2&2\\0&2\end{pmatrix}$"], "A",
    r"按矩阵乘法，$A^2=\begin{pmatrix}1&1\\0&1\end{pmatrix}\begin{pmatrix}1&1\\0&1\end{pmatrix}=\begin{pmatrix}1&2\\0&1\end{pmatrix}$。",
    "matrix-product", "逐项计算矩阵乘积得到对角元1、右上元2、左下元0。",
    "nilpotent-decomposition", "写成 $A=I+N$ 且 $N^2=0$，于是 $A^2=I+2N$，与A选项一致。",
    "按行乘列计算四个元素。", "用幂零矩阵分解作独立复核。", ["矩阵乘法", "矩阵幂"])
add("hx29-math-nilpotent-eigenvalues", "math.exam.90bbbeb58b4a",
    r"若矩阵 $N$ 满足 $N^2=0$，则其任一特征值 $\lambda$ 必满足什么条件？",
    [r"$\lambda=0$", r"$\lambda=1$", r"$\lambda^2=1$", "任意复数"], "A",
    r"若 $Nv=\lambda v$ 且 $v\ne0$，则 $0=N^2v=\lambda^2v$，故 $\lambda=0$。",
    "eigenvector-substitution", r"由 $N^2v=\lambda^2v=0$ 且特征向量非零，推出 $\lambda^2=0$。",
    "nilpotent-polynomial", "特征值必须是多项式 $t^2$ 的根，唯一根为0。",
    "将特征值定义代入 $N^2=0$。", "由零化多项式 $t^2$ 推出特征值范围。", ["幂零矩阵", "特征值"])
add("hx29-math-improper-p-integral", "math.exam.352fcf1392ad",
    r"反常积分 $\int_1^{\infty}x^{-p}\,dx$ 收敛的充要条件是（）。",
    ["$p<0$", r"$p\le1$", "$p>1$", "任意 p"], "C",
    r"当 $p\ne1$ 时积分截断值为 $(R^{1-p}-1)/(1-p)$；仅 $p>1$ 时 $R\to\infty$ 有有限极限。$p=1$ 时发散。",
    "truncated-antiderivative-limit", "计算到 R 的积分并令 R 趋于无穷，有限极限当且仅当 $p>1$。",
    "comparison-test", "幂函数尾部可积判别给出指数必须严格大于1，临界 $1/x$ 发散。",
    "先写有限上限 R 的积分。", "检查 $p=1$ 临界情形并取无穷极限。", ["反常积分", "p积分判别"])
add("hx29-math-endpoint-comparison", "math.exam.a62c828f6537",
    r"反常积分 $\int_0^1x^\alpha\,dx$ 在 0 点收敛的条件是（）。",
    [r"$\alpha>-1$", r"$\alpha\ge-1$", r"$\alpha< -1$", "任意实数"], "A",
    r"当 $\alpha\ne-1$ 时截断积分为 $1/(\alpha+1)-\varepsilon^{\alpha+1}/(\alpha+1)$，极限有限当且仅当 $\alpha>-1$；$\alpha=-1$ 对数发散。",
    "truncated-integral", r"直接求 $\varepsilon$ 到1的原函数差并令 $\varepsilon\to0^+$。",
    "endpoint-comparison", "在端点附近幂次可积条件为指数严格大于−1，临界指数−1发散。",
    r"对 $\alpha\ne-1$ 计算原函数。", r"单独检查对数临界项 $\alpha=-1$。", ["反常积分", "端点比较", "参数范围"])
add("hx29-math-integral-mean-value", "math.exam.4a56bd52caf7",
    r"连续函数 $f(x)=2x$ 在 $[0,1]$ 上的积分平均值 $\int_0^1f(x)dx/(1-0)$ 是多少？",
    ["0", "$1/2$", "1", "2"], "C",
    "积分为 $[x^2]_0^1=1$，区间長度为1，积分平均值为1。",
    "integral-evaluation", "逐项求积分得到1，再除以区间长度1仍为1。",
    "linear-function-average", "线性函数在区间上的平均值等于端点函数值平均数，$(0+2)/2=1$。",
    "计算定积分。", "除以区间长度并用线性平均值复核。", ["定积分平均值", "积分平均值公式"])
add("hx29-math-congruence-inertia", "math.exam.7af99f485eff",
    "实对称矩阵对应二次型作可逆合同变换后，正、负惯性指数如何变化？",
    ["均保持不变", "只保持正惯性指数", "只保持负惯性指数", "都可任意变化"], "A",
    "实对称二次型的正、负、零惯性指数在可逆合同变换下保持不变，这是惯性定理。",
    "law-of-inertia", "合同变换是可逆变量替换，不改变二次型正定子空间的最大维数及相应负维数。",
    "canonical-diagonal-form", "两种可逆合同变换得到的标准对角形具有相同正负平方项数。",
    "明确合同变换对应可逆线性变量替换。", "用实对称二次型惯性定理核对不变量。", ["二次型", "合同变换", "惯性指数"])
add("hx29-math-parameter-integral-derivative", "math.exam.8eaf1a6aeb50",
    r"设 $F(a)=\int_0^1 e^{ax}\,dx$，则 $F'(0)$ 等于多少？",
    ["0", "$1/2$", "1", "e"], "B",
    r"在有限区间上可对参数求导，$F'(a)=\int_0^1xe^{ax}dx$，故 $F'(0)=\int_0^1x dx=1/2$。",
    "differentiate-under-integral", "被积函数及参数导数在紧区间连续，积分与求导可交换，代a=0得1/2。",
    "closed-form-limit", r"$F(a)=(e^a-1)/a$，在a=0处用级数 $1+a/2+\cdots$ 得导数1/2。",
    "验证连续参数求导条件并求导。", "用闭式表达在零点的展开复核。", ["含参积分", "积分求导"])
add("hx29-math-integral-upper-continuity", "math.exam.3504d885999b",
    r"若 $f$ 在区间上连续且 $F(x)=\int_0^xf(t)dt$，则关于 $F'$ 的结论是哪一个？",
    ["$F'(x)=f(x)$ 且连续", "$F'(x)=0$", "$F$ 必为常数", "$F'$ 不存在"], "A",
    "微积分基本定理给出 $F'(x)=f(x)$；因 f 连续，F' 也连续。",
    "fundamental-theorem", "连续被积函数的变上限积分可导，导数等于上限处被积函数。",
    "continuity-transfer", "由等式 $F'=f$ 以及 f 连续直接得导函数连续。",
    "应用微积分基本定理。", "利用 f 的连续性判断 F' 的连续性。", ["变上限积分", "导数连续性"])
add("hx29-math-two-variable-extremum", "math.exam.e2de677ebe0d",
    r"函数 $f(x,y)=x^2+2y^2$ 在 $\mathbb R^2$ 上的最小值及取值点为（）。",
    ["最小值0，在(0,0)", "最小值1，在(1,0)", "无最小值", "最小值−2，在(0,1)"], "A",
    r"两个平方项系数为正，所以 $f\ge0$；仅在 x=y=0 时取0。",
    "positive-sum-of-squares", "逐项非负，和不小于0且原点达到0。",
    "critical-point-and-Hessian", "唯一驻点为原点，Hessian为正定矩阵 diag(2,4)，故为全局最小点。",
    "用平方项符号给出全局下界。", "求驻点并用正定 Hessian 复核。", ["二元函数极值", "正定性"])
add("hx29-math-hessian-test", "math.exam.58a5d04a7be9",
    "函数 $f(x,y)=x^2+y^2$ 在原点的 Hessian 矩阵及其判别结果为（）。",
    ["$2I$，正定，原点为严格极小点", "$0$，无法判别", "$-2I$，严格极大点", "不定，鞍点"], "A",
    "二阶偏导为 $f_{xx}=2,f_{yy}=2,f_{xy}=0$，Hessian为 $2I$ 正定，且原点为严格极小点。",
    "second-derivatives", "直接求 Hessian 得 diag(2,2)，两个特征值均正。",
    "quadratic-growth", "$f(x,y)-f(0,0)=x^2+y^2>0$ 对任意非零邻近点成立。",
    "计算二阶偏导组成 Hessian。", "用正定性和函数增量判断极小性质。", ["Hessian判别法", "二元函数极值"])
add("hx29-math-solid-of-revolution", "math.exam.9f10ce353fbd",
    r"曲线 $y=x$、$0\le x\le1$ 绕 x 轴旋转所得旋转体体积为（）。",
    [r"$\pi/3$", r"$\pi/2$", r"$\pi$", r"2$\pi/3$"], "A",
    r"圆盘法得 $V=\pi\int_0^1x^2dx=\pi/3$。",
    "disk-method", r"截面面积为 $\pi x^2$，沿0到1积分为$\pi/3$。",
    "conical-volume", r"所得为底半径1、高1的圆锥，体积$\pi r^2h/3=\pi/3$。",
    "写出垂直 x 轴的圆盘截面积。", "积分并用圆锥几何体积公式复核。", ["旋转体体积", "定积分应用"])
add("hx29-math-nonlinear-second-order", "math.exam.ec75fe95fe0f",
    "方程 $y''+(y')^2=0$ 满足 $y(0)=0,y'(0)=1$，则 $y(1)$ 等于（）。",
    [r"$\ln2$", "1", "$e-1$", "2"], "A",
    r"令 $p=y'$，则 $p'+p^2=0,p(0)=1$，解得 $p=1/(x+1)$；积分并用 $y(0)=0$ 得 $y=\ln(1+x)$。",
    "reduce-order", "令p=y'把方程降为可分离方程$p'=-p^2$，初值得$p=1/(1+x)$。",
    "direct-substitution", r"$y=\ln(1+x)$ 时 $y'=1/(1+x),y''=-1/(1+x)^2$，原方程左侧为0。",
    "令一阶导数为新变量降低阶数。", "用初值积分并代回原方程核验。", ["二阶非线性方程", "降阶"])
add("hx29-math-reduction-initial-values", "math.exam.66f8f7b61188",
    "方程 $y''=2$ 且 $y(0)=0,y'(0)=1$，则 $y(1)$ 等于多少？",
    ["1", "2", "3", "4"], "B",
    "积分得 $y'=2x+C_1$，由 $y'(0)=1$ 得C1=1；再积分并用y(0)=0，得$y=x^2+x$，故y(1)=2。",
    "integrate-twice", "对二阶方程连续积分两次，再依次代入两个初值，得到y(1)=2。",
    "candidate-substitution", "$y=x^2+x$ 的二阶导数为2且满足两个初值，直接验证y(1)=2。",
    "积分一次并用导数初值确定常数。", "再积分并用函数初值确定常数。", ["降阶与积分", "初值条件"])
add("hx29-math-rank-maximal-independent", "math.exam.8d8ad14b2a44",
    "向量 $v_1=(1,0),v_2=(0,1),v_3=(1,1)$ 的秩及一个极大无关组是（）。",
    ["秩2，{v1,v2}", "秩3，{v1,v2,v3}", "秩1，{v3}", "秩0，空集"], "A",
    r"$v_1,v_2$ 线性无关并张成 $\mathbb R^2$，且 $v_3=v_1+v_2$，所以秩为2。",
    "linear-relation", "检验 $v_3=v_1+v_2$，三向量秩不超过2，而前两者独立，故秩2。",
    "determinant-minor", "以v1、v2为列的二阶行列式为1非零，证明秩至少2；空间维数给出至多2。",
    "找出向量间线性关系。", "用非零二阶子式确定秩下界。", ["向量组秩", "极大无关组"])
add("hx29-math-matrix-power", "math.exam.0949f5ff08f9",
    r"设 $A=\begin{pmatrix}1&1\\0&1\end{pmatrix}$，则 $A^4$ 等于（）。",
    [r"$\begin{pmatrix}1&4\\0&1\end{pmatrix}$", r"$\begin{pmatrix}4&4\\0&4\end{pmatrix}$", "$I$", r"$\begin{pmatrix}1&1\\0&1\end{pmatrix}$"], "A",
    r"写成 $A=I+N$ 且 $N^2=0$，二项式展开得 $A^4=I+4N=\begin{pmatrix}1&4\\0&1\end{pmatrix}$。",
    "nilpotent-binomial", "因为N平方为0，展开中二次及以上项消失，剩I+4N。",
    "recurrence-multiplication", "逐次乘A可得右上角元素每次增加1，四次后为4。",
    "分离单位矩阵与幂零部分。", "用连续矩阵乘法的递推关系复核。", ["矩阵分解", "矩阵幂"])
add("hx29-math-double-integral", "math.exam.936d8c834760",
    r"计算 $\int_0^1\int_0^x1\,dy\,dx$。",
    ["$1/4$", "$1/2$", "1", "2"], "B",
    "先对 y 积分得到x，再对x从0到1积分，结果为$1/2$。",
    "iterated-integration", r"内层积分长度为x，外层为$\int_0^1x dx=1/2$。",
    "triangular-region-area", r"积分等于区域$0\le y\le x\le1$面积，该三角形面积为1/2。",
    "完成内层积分。", "外层积分并以区域几何面积复核。", ["二重积分", "累次积分"])

# 31 further concrete Computer Science 408 topics; family-summary nodes are excluded.
add("hx29-408-programmed-io", "cs408.co.topic.bfd3c1878167",
    "程序查询（轮询）方式下，CPU 通常如何判断设备是否可以继续传送？",
    ["反复读取设备状态寄存器", "等待设备发中断后才检查", "由 DMA 完全代替 CPU 执行查询", "只在系统启动时检查一次"], "A",
    "程序查询由CPU主动轮询设备状态，满足条件后执行相应数据传送。",
    "poll-status", "轮询方式的定义就是CPU反复读取状态寄存器直到设备就绪。",
    "control-flow", "控制流程由CPU检查状态并决定是否进入数据传输，不依赖中断通知。",
    "查看程序查询的状态检测步骤。", "区分主动轮询与中断驱动方式。", ["程序查询", "I/O控制方式"])
add("hx29-408-cpu-modes", "cs408.os.topic.ca43cc94bc12",
    "在用户态运行的程序若尝试执行只能由操作系统执行的特权指令，通常会发生什么？",
    ["触发保护异常并转入内核处理", "指令自动忽略且继续执行", "CPU 自动切换到用户态", "仅清空高速缓存"], "A",
    "特权指令只能在内核态执行，用户态执行会触发异常，由操作系统接管处理。",
    "privilege-check", "处理器检查当前特权级，不满足时产生保护异常。",
    "mode-transition", "异常入口保存现场并切至内核态，内核再决定进程处置。",
    "检查指令的特权级要求。", "沿异常处理路径说明用户态如何进入内核处理。", ["CPU运行模式", "特权指令"])
add("hx29-408-io-software-layers", "cs408.os.topic.7f10bf9cb4e0",
    "操作系统设备无关 I/O 软件层的典型职责是（）。",
    ["提供统一设备命名与缓冲等通用服务", "直接执行每种设备的电气信号时序", "替代中断控制器", "决定所有磁盘扇区的物理布局"], "A",
    "设备无关层提供通用接口、设备命名、保护、缓冲和错误处理等，不负责设备专有时序。",
    "layer-responsibility", "把设备共性服务放在设备无关层，具体硬件操作下沉至驱动程序。",
    "abstraction-boundary", "统一接口让上层不必了解设备型号与寄存器细节。",
    "区分通用功能与设备专用控制。", "按 I/O 软件层次确定设备无关层的抽象职责。", ["I/O软件层次", "设备无关层"])
add("hx29-408-deadlock-four-conditions", "cs408.os.topic.630c531fe924",
    "经典死锁发生的必要条件中，不包括哪一项？",
    ["互斥", "请求并保持", "可剥夺资源", "循环等待"], "C",
    "四个必要条件为互斥、请求并保持、不可剥夺、循环等待；可剥夺资源与必要条件中的不可剥夺相反。",
    "coffman-conditions", "Coffman四条件明确要求资源不可剥夺，因此“可剥夺”不是所列必要条件。",
    "condition-complement", "其余三项均为四条件中的条目，第四项应为不可剥夺而非可剥夺。",
    "列举死锁四个必要条件。", "逐项对照选项中的相反条件。", ["死锁", "必要条件"])
add("hx29-408-frame-reclaim", "cs408.os.topic.58a4bb84b898",
    "采用私有页框分配的进程终止后，其占用的物理页框通常如何处理？",
    ["归还空闲页框池供后续分配", "永久保留给已终止进程", "直接写入交换区并禁止复用", "转为文件目录项"], "A",
    "进程终止后其地址空间失效，内核回收其页框并放回可分配的空闲物理页框集合。",
    "resource-lifecycle", "进程退出释放其内存资源，页框管理器将页框标记为空闲。",
    "allocation-accounting", "回收后这些页框可被其他进程重新映射，符合物理内存复用机制。",
    "确认页框归属于进程的生命周期。", "按操作系统资源回收流程确定后续状态。", ["页框分配", "页框回收"])
add("hx29-408-logical-physical-address", "cs408.os.topic.db2a9445e210",
    "在分页存储管理中，CPU 生成的逻辑地址通常由谁转换为物理地址？",
    ["MMU 根据页表完成地址转换", "磁盘调度器", "文件目录模块", "网卡控制器"], "A",
    "内存管理单元MMU依据页表把逻辑页号映射为物理块号，并保留页内偏移组成物理地址。",
    "page-table-translation", "页表提供逻辑页到物理页框的映射，MMU执行查表与地址拼接。",
    "address-component", "逻辑地址分解为页号和偏移，转换页号后偏移不变。",
    "分解逻辑地址中的页号与页内偏移。", "用页表映射页号并由MMU形成物理地址。", ["内存管理", "地址转换", "MMU"])
add("hx29-408-buffer-purpose", "cs408.os.topic.4daa9addd7e4",
    "操作系统在设备 I/O 中使用缓冲区，主要是为了（）。",
    ["缓和 CPU 与设备之间的速度差异并支持数据暂存", "永久提高设备的物理传输速率", "保证任何 I/O 永不阻塞", "取代设备驱动程序"], "A",
    "缓冲区暂存数据并平滑生产者与消费者速率差异，但不会改变设备本身的物理速度。",
    "producer-consumer-decoupling", "缓冲让快慢不同的两端在一定范围内解耦。",
    "buffer-semantics", "缓冲是暂存空间而非硬件加速或驱动替代机制。",
    "说明数据在两端之间如何暂存。", "排除缓冲区无法提供的硬件性能保证。", ["缓冲区管理", "I/O缓冲"])
add("hx29-408-symbol-rate", "cs408.cn.topic.e567ffa4c80f",
    "某链路符号率为 1000 Baud，每个信号符号可表示 4 bit，忽略编码开销时比特率为多少？",
    ["1000 bit/s", "2000 bit/s", "4000 bit/s", "8000 bit/s"], "C",
    r"比特率等于符号率乘以每符号比特数，即 $1000\times4=4000$ bit/s。",
    "rate-unit-conversion", "每秒1000个符号，每符号4 bit，相乘得4000 bit/s。",
    "dimensional-analysis", "Baud量纲为符号/秒，乘bit/符号后得到bit/秒，数值4000。",
    "确定每秒符号数与每符号携带位数。", "用量纲相消计算比特率。", ["通信基础", "波特率", "比特率"])
add("hx29-408-selective-repeat", "cs408.cn.topic.6e5dd5812d0e",
    "选择重传（SR）ARQ 收到窗口内的失序正确帧时，接收方通常如何处理？",
    ["缓存该帧并可单独确认", "一律丢弃且只确认累计前缀", "重置整个连接", "把该帧当作校验错误"], "A",
    "SR允许窗口内失序帧被接收并缓存，可对各帧分别确认，缺失帧之后再补齐。",
    "receiver-window-rule", "SR接收窗口中合法序号的帧可暂存，不必等前序到达。",
    "acknowledgment-granularity", "SR使用逐帧确认与选择性重传，而非仅累计确认。",
    "检查序号是否落在接收窗口中。", "按选择重传的缓存和确认规则处理失序帧。", ["选择重传", "滑动窗口协议"])
add("hx29-408-tcp-three-way-handshake", "cs408.cn.topic.6bb96577c0c4",
    "TCP 建立连接的三次握手中，客户端收到服务器的 SYN+ACK 后通常发送什么？",
    ["ACK 确认段", "FIN 释放段", "RST 复位段", "不再发送任何报文"], "A",
    "第三次握手由客户端发送ACK确认服务器的SYN，使双方的发送与接收序号同步。",
    "handshake-state-transition", "客户端收到SYN+ACK后进入已发送ACK的状态，连接建立。",
    "sequence-acknowledgment", "ACK确认号为服务器初始序号加1，确认SYN占用一个序号。",
    "列出 SYN、SYN+ACK 两步。", "确定客户端对服务器 SYN 的确认响应。", ["TCP连接管理", "三次握手"])
add("hx29-408-bfs-shortest-path", "cs408.ds.topic.525fc6e99b95",
    "对无权图从源点进行广度优先搜索，首次发现某顶点时得到的路径具有何种性质？",
    ["边数最少", "权值和必最小", "顶点编号最小", "必为唯一简单路径"], "A",
    "BFS按距离层次扩展，队列先处理较少边数的顶点，因此首次发现时的边数距离最短。",
    "level-order", "每层对应从源点出发的边数距离，按层递增遍历。",
    "queue-invariant", "FIFO保证所有深度d顶点先于深度d+1顶点处理。",
    "按从源点的边数划分层次。", "利用 FIFO 队列证明首次发现的层数最小。", ["广度优先搜索", "无权最短路径"])
add("hx29-408-dijkstra-nonnegative", "cs408.ds.topic.a52e1bedea58",
    "Dijkstra 单源最短路径算法的标准正确性条件要求边权满足什么？",
    ["所有边权非负", "必须所有边权相等", "至少存在一条负权边", "图必须是完全图"], "A",
    "算法每次永久确定当前最小暂定距离顶点；非负边权保证之后的路径不会把它改得更短。",
    "greedy-finalization", "非负边权使未处理顶点经任何后续边扩展都不能产生更短的已确定距离。",
    "counterexample-negative-edge", "负边可能从较晚处理的顶点回连并缩短已确定距离，因此标准算法要求非负。",
    "说明贪心永久标号的关键假设。", "分析负权边为何会破坏该假设。", ["Dijkstra算法", "最短路径", "边权条件"])
add("hx29-408-prim-cut", "cs408.ds.topic.b66f6167354e",
    "Prim 算法构造最小生成树时，每一步选择的边通常是（）。",
    ["连接当前树与树外顶点的最小权边", "图中全局最大的边", "任意不在树中的边", "形成环的最小边"], "A",
    "Prim维护已纳入树的顶点集合，每步从跨越该集合与外部的边中选最小权边。",
    "cut-property", "由割性质，在跨割边中取最轻边可安全扩展某棵最小生成树。",
    "algorithm-invariant", "每次只加入一个新顶点且不形成环，直到包含所有连通分量顶点。",
    "划分已纳入树与未纳入顶点。", "应用割性质选出跨集合最轻边。", ["Prim算法", "最小生成树"])
add("hx29-408-kruskal", "cs408.ds.topic.285e8e87a0cf",
    "Kruskal 算法处理候选边时，若加入某边会与已选边构成环，应如何处理？",
    ["跳过该边", "必须加入并删除最重边", "重新开始排序", "将边权改为0后加入"], "A",
    "Kruskal按权从小到大考察边，只加入连接不同连通分量的边；会成环的边跳过。",
    "union-find-components", "若两个端点同属一个并查集代表元，加入会形成环，故不选。",
    "forest-invariant", "已选边始终构成森林，加入成环边违反该不变量。",
    "按权值升序考察边。", "用并查集判断端点是否已连通。", ["Kruskal算法", "并查集", "最小生成树"])
add("hx29-408-btree-leaf-depth", "cs408.ds.topic.ee1ca2a45d19",
    "一棵 B 树中所有叶结点通常满足什么深度性质？",
    ["都位于同一层", "根结点的孩子才是叶", "深度必须各不相同", "叶结点不保存关键字"], "A",
    "B树定义要求所有叶结点处于同一层，以维持平衡并保证查找路径长度一致。",
    "balanced-tree-invariant", "插入分裂与结点合并维持根到叶的路径等长。",
    "search-path-length", "叶层统一意味着成功查找路径具有相同层数。",
    "回忆 B 树的平衡定义。", "从根到叶的查找路径长度核验同层性质。", ["B树", "平衡多路查找树"])
add("hx29-408-insertion-sort-complexity", "cs408.ds.topic.60bf2405e5c6",
    "直接插入排序对长度 n 的逆序序列排序时，最坏时间复杂度为（）。",
    ["$O(n)$", r"$O(n\log n)$", "$O(n^2)$", "$O(2^n)$"], "C",
    r"第i次插入可能向前移动i个元素，逆序输入总比较/移动量为 $1+2+\cdots+(n-1)=n(n-1)/2$。",
    "insertion-count", "逐趟移动次数求和为三角数，数量级为n平方。",
    "worst-case-input", "逆序序列使每个新元素都移动到已排序前缀最前端。",
    "计算各趟最大移动量。", "利用求和公式确定渐进阶。", ["直接插入排序", "时间复杂度"])
add("hx29-408-merge-sort", "cs408.ds.topic.b5b80cd56cd5",
    "归并排序将序列递归对半划分并线性合并，其最坏时间复杂度是（）。",
    ["$O(n)$", r"$O(n\log n)$", "$O(n^2)$", r"$O(\log n)$"], "B",
    r"递归深度为 $\log_2n$，每层合并总成本为 $O(n)$，故总时间为 $O(n\log n)$。",
    "recurrence", r"递推式 $T(n)=2T(n/2)+cn$，主定理得 $T(n)=O(n\log n)$。",
    "level-cost", "每层所有子数组元素总量为n，共有对数层，因此总成本n log n。",
    "写出一层递归与合并成本。", "按递归树逐层累加。", ["归并排序", "时间复杂度"])
add("hx29-408-singly-linked-insert", "cs408.ds.topic.d5b72e4fbe7b",
    "已知单链表结点 p，若要在 p 之后插入新结点 s，且已分配 s，指针操作的时间复杂度是（）。",
    ["$O(1)$", "$O(n)$", r"$O(n\log n)$", "$O(n^2)$"], "A",
    "只需令 $s.next=p.next$，再令 $p.next=s$，不需要遍历链表。",
    "pointer-update-count", "固定两次指针赋值完成插入，操作数不随链表长度变化。",
    "locality-of-operation", "已知前驱位置p，不需要搜索目标位置，故为常数时间。",
    "确定插入位置已由 p 给出。", "列出常数次指针更新。", ["单链表", "插入操作", "时间复杂度"])
add("hx29-408-controller-role", "cs408.co.topic.a1e3b44f8513",
    "I/O 控制器的基本作用是（）。",
    ["在 CPU/总线与具体 I/O 设备间提供控制和数据交换接口", "执行所有用户态应用程序", "替代主存储器保存全部数据", "负责网络路由选择"], "A",
    "I/O控制器管理设备寄存器、状态与数据传送，使处理器和总线能以统一方式访问设备。",
    "register-interface", "控制器暴露数据、状态、控制寄存器并协调设备操作。",
    "device-abstraction", "控制器屏蔽部分设备细节，为处理器提供交互接口。",
    "区分处理器、控制器和外设。", "从寄存器与传送协调说明接口作用。", ["I/O控制器", "设备接口"])
add("hx29-408-io-interface-registers", "cs408.co.topic.e31ff79f7b2e",
    "I/O 接口中的状态寄存器通常用于表示什么？",
    ["设备就绪、忙、错误等当前状态", "程序的全部源代码", "磁盘文件目录树", "CPU 的虚拟地址空间大小"], "A",
    "状态寄存器向CPU报告接口和设备当前状态，供轮询或中断处理判断后续操作。",
    "status-register-semantics", "就绪、忙、完成和错误标志均属于设备状态。",
    "control-data-separation", "状态寄存器反映现状，控制寄存器下发命令，数据寄存器承载数据。",
    "区分状态、控制和数据寄存器。", "列举状态标志在 I/O 控制中的用途。", ["I/O接口", "状态寄存器"])
add("hx29-408-context-switch", "cs408.os.topic.e73a5b633dc7",
    "进程上下文切换时，操作系统通常需要保存和恢复什么？",
    ["进程的处理器状态等执行上下文", "所有磁盘扇区的内容", "整个可执行文件的源代码", "仅网络路由表"], "A",
    "上下文包括程序计数器、寄存器、栈指针等使进程能暂停后继续执行的处理器状态。",
    "save-restore-state", "切出时保存寄存器和PC等，切入时恢复目标进程对应状态。",
    "resume-equivalence", "恢复这些状态后，目标进程从其先前指令位置继续执行。",
    "列出可恢复执行所需的处理器状态。", "解释保存与恢复如何支持暂停续跑。", ["上下文切换", "进程状态"])
add("hx29-408-virtual-page-fault", "cs408.os.topic.fac871808395",
    "启用请求分页的进程访问某虚拟页，而该页当前不在物理内存中，通常会发生什么？",
    ["缺页异常，由操作系统调入页面", "直接把虚拟地址当磁盘地址", "必然发生死锁", "CPU 自动忽略本次访存"], "A",
    "页表项显示页面不在内存时触发缺页异常，内核选择页框并从后备存储调页后重启指令。",
    "present-bit-check", "页表存在位为0时MMU触发异常，由内核处理缺页。",
    "instruction-restart", "页面调入并更新页表后，故障指令通常重新执行。",
    "检查页表中的存在位。", "按缺页异常处理流程说明调页与重启。", ["虚拟内存", "请求分页", "缺页异常"])
add("hx29-408-ethernet-duplex", "cs408.cn.topic.bcfe8d79341e",
    "传统共享式半双工以太网检测到冲突后，发送站通常执行哪种处理？",
    ["停止发送并采用二进制指数退避后重传", "继续发送并忽略冲突", "立即永久关闭网卡", "把冲突帧标记为成功接收"], "A",
    "CSMA/CD检测冲突后发送拥塞信号并退避随机时间，再尝试重传。",
    "collision-response", "检测冲突后停止当前帧传输并进入退避过程。",
    "binary-exponential-backoff", "退避槽数随连续冲突次数按二进制指数规则随机选择。",
    "确定冲突检测后的立即动作。", "说明随机退避为何降低再次冲突概率。", ["以太网", "CSMA/CD", "退避"])
add("hx29-408-stop-and-wait", "cs408.cn.topic.d702790fde46",
    "停等可靠传输协议用 0/1 交替序号区分新帧与重传帧，主要是为了（）。",
    ["让接收方识别重复帧并避免重复交付", "提高链路物理带宽", "允许无限多个未确认帧", "取消差错检测"], "A",
    "若确认丢失导致发送方重传，交替序号让接收方辨认该帧已交付过，从而只重发确认。",
    "duplicate-detection", "接收序号与期望序号不符时将其视为重复帧而不再次交付。",
    "lost-ack-scenario", "确认丢失会触发重传，序号防止接收端重复传递同一数据。",
    "分析数据帧或确认丢失后的重传。", "说明交替序号如何辨认新帧与旧帧。", ["可靠传输", "停等协议", "序号"])
add("hx29-408-gbn-window", "cs408.cn.topic.ab43d1fb00a1",
    "后退 N 帧（GBN）协议收到窗口内的失序帧时，接收方通常如何处理？",
    ["丢弃失序帧并重复确认当前期望序号", "缓存所有失序帧并逐帧确认", "立即关闭连接", "把窗口整体前移到该帧之后"], "A",
    "GBN接收方通常只按序接收，失序帧丢弃并发送累计确认，提示发送方缺少的期望帧。",
    "receiver-state", "接收状态只跟踪下一个期望序号，失序帧不改变状态。",
    "cumulative-ack", "累计确认号表示按序前缀，收到失序帧仍重复确认当前前缀。",
    "确定接收方的下一个期望序号。", "按 GBN 累计确认规则处理失序帧。", ["GBN", "滑动窗口", "累计确认"])
add("hx29-408-email-protocol", "cs408.cn.topic.64b2c1c54cf3",
    "在典型电子邮件系统中，用户代理向邮件服务器提交外发邮件常用的应用层协议是（）。",
    ["SMTP", "ARP", "ICMP", "RIP"], "A",
    "SMTP用于邮件提交与邮件服务器之间的转发；POP3/IMAP通常用于收取或访问邮箱。",
    "protocol-function", "SMTP定义邮件传输与提交，其他选项分别属于地址解析、控制报文和路由协议。",
    "mail-flow", "沿发件用户代理到邮件服务器的方向属于发送流程，采用SMTP。",
    "区分发送邮件与读取邮箱。", "按邮件流向匹配应用层协议。", ["电子邮件", "SMTP"])
add("hx29-408-radix-sort", "cs408.ds.topic.b901c6e9e751",
    "对定长整数采用最低位优先的基数排序时，为保证整体稳定性，每一趟按当前位排序通常必须（）。",
    ["使用稳定排序", "使用不稳定排序", "先删除相同关键字", "随机打乱相同关键字"], "A",
    "LSD基数排序依赖低位已有次序在高位排序后保留，因此每趟必须稳定。",
    "stability-composition", "稳定的高位排序保留当前位相同元素的低位相对顺序。",
    "two-digit-counterexample", "若某趟不稳定，相同当前位元素可能交换低位顺序，最终字典序失效。",
    "从低位到高位描述每趟处理。", "说明稳定性如何维持已排序的低位信息。", ["基数排序", "稳定性", "LSD"])
add("hx29-408-sequential-search", "cs408.ds.topic.d6d83159a7e3",
    "在含 n 个元素的无序线性表中，若成功查找目标等概率位于任一位置，顺序查找平均比较次数为（）。",
    ["$n/2$", "$(n+1)/2$", r"$\log_2n$", "$n$"], "B",
    r"各位置比较次数为1至n，平均值为 $(1+2+\cdots+n)/n=(n+1)/2$。",
    "arithmetic-mean", "对等概率位置的代价1到n求算术平均，得到(n+1)/2。",
    "expected-value", "期望为每个位置的比较次数乘1/n求和，化简同为(n+1)/2。",
    "列出每个成功位置对应的比较次数。", "按等概率计算离散期望。", ["顺序查找", "平均查找长度"])
add("hx29-408-searching-comparison", "cs408.ds.topic.d4f941ee9608",
    "折半查找对顺序表的关键前提之一是（）。",
    ["关键字有序且可按下标随机访问", "关键字必须全部相同", "表中元素只能为整数", "表长必须是2的幂"], "A",
    "折半查找依赖有序性排除一半区间，并依赖顺序表随机访问快速定位中点。",
    "interval-elimination", "只有序列有序，比较中点后才能据大小排除一半元素。",
    "random-access", "每轮需直接访问区间中点；顺序表可按下标常数时间访问。",
    "解释比较中点后排除半区的依据。", "检查访问中点是否需要遍历前置元素。", ["查找算法比较", "折半查找条件"])
add("hx29-408-error-detection-parity", "cs408.co.topic.e2880988de52",
    "偶校验位方案中，若传输过程中恰有1个数据位翻转，接收端通常会（）。",
    ["检测到奇数个比特错误", "无法检测任何错误", "自动定位错误位", "自动纠正该错误位"], "A",
    "一个比特翻转改变1的奇偶性，接收端重算校验后会发现校验不一致，但单个奇偶位不能定位并纠正错误。",
    "parity-recomputation", "单个位翻转使总1的个数奇偶性改变，偶校验检查失败。",
    "code-distance", "单奇偶校验最小距离为2，可检测单比特错误但不能定位纠正。",
    "比较发送与接收的总奇偶性。", "区分检测能力与纠正能力。", ["校验码", "奇偶校验"])
add("hx29-408-disk-rotation-latency", "cs408.co.topic.4497bb39baed",
    "磁盘转速为 7200 r/min，假设匀速转动，平均旋转延迟约为多少？",
    ["1.04 ms", "4.17 ms", "8.33 ms", "16.67 ms"], "B",
    "每转时间为 $60/7200$ 秒约8.33 ms，平均等待半圈，约4.17 ms。",
    "rotation-period", "7200转每分钟对应每转8.333毫秒，平均旋转等待取半转。",
    "angular-uniformity", "目标扇区随机相位均匀分布，等待时间均值为完整周期的一半。",
    "由转速求单圈周期。", "随机相位下取半个周期作为平均延迟。", ["磁盘存储器", "旋转延迟"])

expected = {spec["node_code"] for spec in batch.CODEX_PUBLIC_ORIGINALS}
if len(batch.CODEX_PUBLIC_ORIGINALS) != 50 or len(expected) != 50:
    raise RuntimeError("batch29_must_target_50_unique_nodes")
if sum(code.startswith("math.exam.") for code in expected) != 19:
    raise RuntimeError("batch29_math_target_count_mismatch")
if sum(code.startswith("cs408.") for code in expected) != 31:
    raise RuntimeError("batch29_408_target_count_mismatch")
if not expected.issubset(empty):
    raise RuntimeError(f"batch29_targets_not_empty_in_checkpoint:{sorted(expected-set(empty))}")
if any(".family." in code for code in expected):
    raise RuntimeError("batch29_must_not_target_family_summary_nodes")

if __name__ == "__main__":
    raise SystemExit(batch.main())
