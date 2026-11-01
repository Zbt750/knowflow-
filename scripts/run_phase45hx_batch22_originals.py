"""Add a second small mixed-subject batch of reviewed public originals."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch
from backend.services.question_generation import Output

batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261011/batch-18-originals"
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-22-originals"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_18_ORIGINALS_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-22-originals"
batch.SUCCESS_STATUS = "BATCH_22_ORIGINALS_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]


def choice(stem, options, answer, explanation, steps):
    return Output(stem=stem, question_type="single_choice", options=options,
        correct_answer=answer, final_value=answer, explanation=explanation, steps=steps)


def fill(stem, answer, explanation, steps):
    return Output(stem=stem, question_type="fill_blank", options=None,
        correct_answer=answer, final_value=answer, explanation=explanation, steps=steps)


batch.CODEX_PUBLIC_ORIGINALS = [
    {
        "request_id": "hx22-math-lhopital-exp-sin-v1",
        "node_code": "math.calculus.limit.lhopital",
        "output": choice("计算极限 $\\lim_{x\\to0}\\frac{e^{2x}-1}{\\sin 3x}$。",
            {"A": "2/3", "B": "3/2", "C": "2", "D": "0"}, "A",
            "当 x→0 时分子、分母均趋于 0，可用洛必达法则。求导后比值为 2e^{2x}/(3cos 3x)，代入 x=0 得 2/3。",
            [{"expression": "2*exp(2*x)/(3*cos(3*x)) at x=0", "value": "2/3"}]),
        "derived_answer": "2/3",
        "method_evidence": [
            {"method": "l-hopital-derivative-ratio", "result": "分子分母导数分别为2e^(2x)、3cos(3x)，极限为2/3。"},
            {"method": "first-order-equivalent-expansions", "result": "e^(2x)-1~2x，sin(3x)~3x，商的极限为2/3。"},
        ],
        "explanation_key_steps": ["先确认是 0/0 型，满足洛必达法则适用形式。", "求导后代入 0 得 2/3；一阶等价展开也得到同一结果。"],
        "option_truth_table": {"A": True, "B": False, "C": False, "D": False},
        "skill_tags": ["洛必达法则适用条件", "0/0 型极限"],
    },
    {
        "request_id": "hx22-math-infinitesimal-cos-v1",
        "node_code": "math.calculus.limit.infinitesimal",
        "output": choice("计算 $\\lim_{x\\to0}\\frac{1-\\cos 2x}{x^2}$。",
            {"A": "1/2", "B": "1", "C": "2", "D": "4"}, "C",
            "利用 1-cos u~u²/2，令 u=2x，则分子约为 (2x)²/2=2x²，极限为 2。",
            [{"expression": "(2*x)^2/(2*x^2)", "value": "2"}]),
        "derived_answer": "2",
        "method_evidence": [
            {"method": "cosine-equivalent-infinitesimal", "result": "1-cos(2x)~(2x)^2/2=2x^2，商趋于2。"},
            {"method": "second-order-taylor", "result": "cos(2x)=1-2x^2+o(x^2)，所以分子为2x^2+o(x^2)，极限为2。"},
        ],
        "explanation_key_steps": ["等价无穷小 1-cos u~u²/2 的变量必须取 u=2x。", "约去 x² 后常数为 2。"],
        "option_truth_table": {"A": False, "B": False, "C": True, "D": False},
        "skill_tags": ["等价无穷小替换", "三角函数极限"],
    },
    {
        "request_id": "hx22-math-double-integral-square-v1",
        "node_code": "math.exam.a0d6b80898e3",
        "output": fill("计算二重积分 $\\int_0^1\\int_0^2 (x+2y)\\,dy\\,dx$。",
            "5", "先对 y 积分：∫₀²(x+2y)dy=2x+4；再对 x 积分：∫₀¹(2x+4)dx=1+4=5。",
            [{"expression": "integral_y_0^2(x+2*y)dy", "value": "2*x+4"},
             {"expression": "integral_x_0^1(2*x+4)dx", "value": "5"}]),
        "derived_answer": "5",
        "method_evidence": [
            {"method": "iterated-integration-dy-dx", "result": "内层积分为2x+4，外层积分为[x²+4x]_0^1=5。"},
            {"method": "separate-linearity-check", "result": "∫₀¹∫₀²x dy dx=1；∫₀¹∫₀²2y dy dx=4；总和为5。"},
        ],
        "explanation_key_steps": ["按题目给定积分次序先对 y 积分，x 作为常量。", "再对 x 从0到1积分，结果为5。"],
        "skill_tags": ["二重积分累次积分", "矩形区域积分"],
    },
    {
        "request_id": "hx22-math-derivative-monotonic-v1",
        "node_code": "math.exam.9578b3defcb0",
        "output": choice("函数 $f(x)=x^3-3x$ 在哪个区间严格递减？",
            {"A": "(-∞,-1)", "B": "(-1,1)", "C": "(1,∞)", "D": "(-∞,∞)"}, "B",
            "求导得 f'(x)=3(x²-1)。当 -1<x<1 时 f'(x)<0，因此函数在该区间严格递减；区间外导数为正。",
            [{"expression": "3*(x^2-1)<0", "value": "-1<x<1"}]),
        "derived_answer": "B",
        "method_evidence": [
            {"method": "derivative-sign-chart", "result": "f'=3(x-1)(x+1)，符号在两个临界点间为负，故递减区间为(-1,1)。"},
            {"method": "monotonicity-definition-check", "result": "f'在(-1,1)恒负；其余给定选项区间上恒负的条件不成立。"},
        ],
        "explanation_key_steps": ["用导数符号判断单调性。", "解 3(x²−1)<0 得 −1<x<1。"],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
        "skill_tags": ["导数判单调性", "临界点分区"],
    },
    {
        "request_id": "hx22-408-graph-complete-edges-v1",
        "node_code": "cs408.ds.topic.48968798d156",
        "output": fill("无向简单完全图 $K_7$ 有多少条边？", "21",
            "每两个不同顶点恰好构成一条边，边数为 C(7,2)=7×6/2=21。",
            [{"expression": "7*6/2", "value": "21"}]),
        "derived_answer": "21",
        "method_evidence": [
            {"method": "unordered-vertex-pairs", "result": "边与无序顶点对一一对应，C(7,2)=21。"},
            {"method": "degree-sum", "result": "K7 每个顶点度为6，总度数42；无向图边数为42/2=21。"},
        ],
        "explanation_key_steps": ["完全简单无向图中任意两个不同顶点之间有一条边。", "用无序顶点对计数得 C(7,2)=21。"],
        "skill_tags": ["完全图边数", "无向图度数和"],
    },
    {
        "request_id": "hx22-408-topological-orders-v1",
        "node_code": "cs408.ds.topic.8ea0de0d75f4",
        "output": fill("有向无环图仅含顶点 A、B、C、D 和边 A→C、B→C、C→D。该图共有多少种拓扑序列？", "2",
            "A、B 必须都在 C 之前，C 必须在 D 之前；A 与 B 之间没有先后约束，因此只有 A,B,C,D 与 B,A,C,D 两种。",
            [{"expression": "permutations(A,B) with C before D after both", "value": "2"}]),
        "derived_answer": "2",
        "method_evidence": [
            {"method": "kahn-available-zero-indegree", "result": "初始零入度点为A、B，两种选择顺序；之后只能C、D，计2种。"},
            {"method": "partial-order-enumeration", "result": "约束A<C、B<C、C<D，A/B可互换且其余次序固定，共2种。"},
        ],
        "explanation_key_steps": ["拓扑序必须使 A、B 均先于 C，且 C 先于 D。", "A 与 B 可交换，其他次序被约束固定，故为2种。"],
        "skill_tags": ["拓扑排序", "DAG偏序计数"],
    },
    {
        "request_id": "hx22-408-semaphore-basic-v1",
        "node_code": "cs408.os.topic.86089b973451",
        "output": choice("初值为 1 的互斥信号量 S 上，进程 P1 已成功执行 P(S)，尚未执行 V(S)。此时进程 P2 执行 P(S) 的结果是什么？",
            {"A": "P2 成功进入临界区，S 变为 -1", "B": "P2 被阻塞等待，直到获得信号量", "C": "P2 立即终止", "D": "S 自动恢复为 1"}, "B",
            "P1 执行 P 后占有互斥信号量，S=0。P2 再执行 P 时无法获得资源，将阻塞等待；P1 执行 V 释放后，等待进程才可继续。",
            [{"expression": "S=1 -> P1.P(S): S=0, owns lock -> P2.P(S): unavailable", "value": "P2 blocks"}]),
        "derived_answer": "B",
        "method_evidence": [
            {"method": "semaphore-state-transition", "result": "P1成功P后S=0；互斥信号量不可再分配，P2阻塞。"},
            {"method": "mutual-exclusion-invariant", "result": "互斥要求同一时刻至多一个进程持有资源，P1未V前P2不能成功进入。"},
        ],
        "explanation_key_steps": ["信号量初值1，P1 执行 P 后占有互斥资源。", "P1 尚未执行 V，P2 不能同时获得资源，因而等待/阻塞。"],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
        "skill_tags": ["互斥信号量P/V", "阻塞与唤醒"],
    },
    {
        "request_id": "hx22-408-tcp-zero-window-v1",
        "node_code": "cs408.cn.topic.fdfe51b5d88a",
        "output": choice("TCP 接收方通告的接收窗口 rwnd=0，发送方通常应采取哪种处理？",
            {"A": "继续发送普通数据段直到拥塞窗口耗尽", "B": "停止发送普通数据并按零窗口探测机制周期性探测窗口", "C": "立即将连接改为半关闭状态", "D": "发送方自动认为连接已复位"}, "B",
            "接收窗口反映接收缓存可用空间。rwnd=0 时发送方暂停常规数据发送，并依据零窗口探测机制确认接收窗口何时重新开放；这与拥塞窗口及连接关闭状态不同。",
            [{"expression": "rwnd=0 -> no ordinary payload; persist/zero-window probe", "value": "B"}]),
        "derived_answer": "B",
        "method_evidence": [
            {"method": "tcp-receiver-flow-control", "result": "接收窗口为0表示接收端暂不能接收普通数据，发送端暂停常规发送并探测窗口更新。"},
            {"method": "protocol-state-elimination", "result": "rwnd为流量控制通告，不表示拥塞窗口耗尽、半关闭或连接复位。"},
        ],
        "explanation_key_steps": ["rwnd 是接收端通告的流量控制窗口。", "窗口为0时暂停普通数据发送，发送端可用零窗口探测机制获知窗口恢复。"],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
        "skill_tags": ["TCP接收窗口", "零窗口探测"],
    },
]


if __name__ == "__main__":
    batch.main()
