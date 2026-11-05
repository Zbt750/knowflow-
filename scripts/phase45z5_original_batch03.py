"""Third constrained public-original batch for the owned isolated DB."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BASE = ROOT / "scripts/phase45z5_original_batch02.py"
BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch02/post-batch02.dump"
BACKUP_SHA256 = "7626BF4ED04782433AF5F1D25F46E782A246272BA9D8DFADB4C2E1C682C63566"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch03"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"

spec = importlib.util.spec_from_file_location("phase45z5_batch02", BASE)
batch02 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(batch02)


def candidates():
    item = batch02.item
    return [
        item("z5b3-math-parameter-integral", "math.exam.8eaf1a6aeb50", "C",
            "设 I(a)=∫₀¹ ln(1+a x²)dx（a>−1）。I′(1) 等于（ ）。",
            {"A":"π/4", "B":"π/4−1", "C":"1−π/4", "D":"1/2"},
            "在a=1附近，被积函数对参数可微且导数连续，可在紧区间上交换求导与积分：I′(1)=∫₀¹ x²/(1+x²)dx。将被积函数写成1−1/(1+x²)，积分得1−arctan(1)=1−π/4。",
            [("differentiate_under_integral", "I′(1)=∫₀¹ x²/(1+x²)dx，因为参数导数连续且区间紧。"),
             ("exact_antiderivative", "x²/(1+x²)=1−1/(1+x²)，端点积分结果为1−π/4。")],
            [("parameter_derivative", "参数求导后，被积函数为x²除以(1+x²)。"),
             ("integral", "精确积分为1−arctan(1)=1−π/4。")],
            {"A":False,"B":False,"C":True,"D":False},
            ("将参数求导移入积分后，还需对有理函数拆分并准确处理反正切端点。",
             "先验证可交换求导与积分，再积分x²/(1+x²)并代入端点。",
             "漏掉分母平方项或把arctan(1)符号处理错误会得到相反结果。",
             "训练含参积分的微分与精确求值，而不是套用单一积分公式。"),
            ["含参积分", "参数求导", "反正切积分"]),
        item("z5b3-math-log-rational-inequality", "math.exam.68217a446e4c", "B",
            "令 g(x)=ln(1+x)−2x/(2+x)，x>0。下列关于g的结论正确的是（ ）。",
            {"A":"g′(x)<0，因此g(x)<0", "B":"g′(x)=x²/[(1+x)(2+x)²]>0，且g(0)=0，故g(x)>0", "C":"g′(x)=1/(1+x)+4/(2+x)²，因此g递减", "D":"g(x)恒等于0"},
            "通分计算g′(x)=1/(1+x)−4/(2+x)²=[(x+2)²−4(x+1)]/[(1+x)(x+2)²]=x²/[(1+x)(x+2)²]>0。且g(0)=0，故对x>0严格有g(x)>0。",
            [("differentiate_and_common_denominator", "g′通分后的分子为(x+2)²−4(x+1)=x²，分母恒正。"),
             ("monotonicity_and_boundary", "g′在正半轴严格为正且g(0)=0，所以g(x)>0。")],
            [("derivative", "g′(x)=x²除以(1+x)(2+x)²。"),
             ("sign_and_value", "分母为正、x²为正且g(0)=0，故g(x)>0。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("需对两个初等函数求导并通分，随后结合边界值由单调性证明全区间不等式。",
             "先化简导数符号，再使用g(0)=0和严格递增推出结论。",
             "通分时容易把减号误作加号；仅做局部展开不能代替对全部x>0的证明。",
             "训练用单调性证明有理式与对数不等式的全局成立性。"),
            ["函数单调性", "不等式证明", "导数符号"]),
        item("z5b3-math-resonant-ode-double-root", "math.exam.f0de5da26b80", "D",
            "初值问题 y″−4y′+4y=e^(2x)，y(0)=y′(0)=0。y(ln2) 等于（ ）。",
            {"A":"(ln2)²/2", "B":"(ln2)²", "C":"4(ln2)²", "D":"2(ln2)²"},
            "特征方程为(r−2)²=0，右端e^(2x)与二重特征根共振。令y=e^(2x)v，则左端化为e^(2x)v″，故v″=1。由y(0)=0、y′(0)=0得v(0)=v′(0)=0，因此v=x²/2。代入x=ln2，y=4(ln2)²/2=2(ln2)²。",
            [("exponential_conjugation", "令y=e^(2x)v后，微分算子(D−2)²作用结果为e^(2x)v″，故v″=1。"),
             ("initial_value_and_resonance", "初值给v(0)=v′(0)=0，解v=x²/2，故y(ln2)=2(ln2)²。")],
            [("characteristic_root", "特征方程为(r−2)²=0，右端指数与二重根共振。"),
             ("transformed_solution", "变换后v″=1且v(0)=v′(0)=0，故y(ln2)=2(ln2)²。")],
            {"A":False,"B":False,"C":False,"D":True},
            ("需要识别二重根共振并用指数代换消去齐次算子，再由初值确定积分常数。",
             "化为v″=1后使用两个初值积分两次，最后准确代入ln2。",
             "按非共振形式取常数倍e^(2x)会失败；漏掉e^(2ln2)=4会少一个因子。",
             "把特征根重数、共振修正、初值和函数值计算结合起来。"),
            ["二阶常系数微分方程", "共振", "初值问题"], difficulty="advanced"),
        item("z5b3-math-composite-second-derivative", "math.exam.6dcf2377bdd4", "A",
            "令 z(x,y)=x²y+e^(xy)，x=t²+1，y=ln(1+t)（t在0附近）。复合函数 h(t)=z(x(t),y(t)) 满足 h″(0)=（ ）。",
            {"A":"−1", "B":"0", "C":"1", "D":"2"},
            "写成h(t)=(1+t²)²ln(1+t)+exp((1+t²)ln(1+t))。第一项在0处二阶导为−1；令u=(1+t²)ln(1+t)，有u(0)=0、u′(0)=1、u″(0)=−1，因此(e^u)″(0)=e^0[(u′)²+u″]=0。总和为−1。",
            [("second_order_chain_rule", "对x²y项求导并在0代入x=1,x′=0,x″=2,y=0,y′=1,y″=−1，得−1。"),
             ("log_series_expansion", "展开h(t)=−t²/2+t+e^(t−t²/2+O(t³))，指数项二次系数为0，故h″(0)=−1。")],
            [("polynomial_log_term", "对(1+t²)²ln(1+t)求二阶导并在0代入，结果为−1。"),
             ("exponential_composition", "指数内u满足u′(0)=1、u″(0)=−1，故(e^u)″(0)=0。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需对两类复合项分别使用乘积、链式及二阶求导规则，并将结果相加。",
             "分别计算对数乘积项和指数复合项的二阶导，再用Taylor展开交叉核验指数项抵消。",
             "只对z的显式x求二阶导会漏掉x(t)、y(t)的二阶变化；指数项有一阶变化但二阶贡献恰抵消。",
             "检验多元函数与参数曲线复合后的二阶变化及不同链式项之间的抵消。"),
            ["全微分", "复合函数求导", "二阶链式法则"]),
        item("z5b3-408-deque-circular-wrap", "cs408.ds.topic.48e8e73d9928", "C",
            "容量为6的循环双端队列用head指向队首、tail指向下一插入位置，并另存size；初态head=tail=0、size=0。依次执行右插10、右插20、右插30、右插40、左出、左出、右插50、右插60、左插5。终态的逻辑序列、head和tail为（ ）。",
            {"A":"[30,40,50,60,5]，head=2，tail=1", "B":"[5,30,40,50,60]，head=0，tail=5", "C":"[5,30,40,50,60]，head=1，tail=0", "D":"[30,40,50,60]，head=2，tail=0"},
            "四次右插后存储位置0至3为10、20、30、40，head=0、tail=4。两次左出移除10、20，head=2、size=2。右插50、60分别写入位置4、5，tail回绕到0、size=4。左插5先令head=(2−1) mod 6=1并写入位置1，最终逻辑序列为[5,30,40,50,60]，head=1、tail=0。",
            [("circular_deque_operation_trace", "逐操作回绕后head=1、tail=0，逻辑顺序5、30、40、50、60。"),
             ("size_and_index_invariants", "终态size=5，索引按模6更新，tail恒指向下一右插位置。")],
            [("front_updates", "两次左出后head=2，随后左插令head变为1。"),
             ("rear_wrap", "右插50、60占位4、5后tail由6模6回到0。"),
             ("logical_contents", "从head=1按环形顺序读取五项为5、30、40、50、60。")],
            {"A":False,"B":False,"C":True,"D":False},
            ("需要同步维护逻辑队列内容、size及首尾两个模数组下标。",
             "逐条执行出入队并在下标越界时模6回绕，最后从head顺序读取。",
             "把tail当成最后一个元素位置，或左插时忘记先回退head，会产生不同下标。",
             "通过前后两端操作和索引回绕检验循环双端队列实现约定。"),
            ["双端队列", "循环存储", "模数组下标"]),
        item("z5b3-408-external-merge-passes", "cs408.ds.topic.9de322fe9c8d", "B",
            "外部归并排序已有9个初始有序段；内存有3个块缓冲区，其中1个用于输出，其余用于输入。每趟只合并可容纳的最大段数，末趟结果也写回磁盘。完成归并至少需要几趟，若文件共N页，归并I/O总量为多少页？",
            {"A":"3趟，6N页", "B":"4趟，8N页", "C":"5趟，10N页", "D":"4趟，6N页"},
            "3个缓冲块中1个输出，故每趟最多2路归并。段数依次为9→5→3→2→1，共4趟。每趟完整读入并写出N页，末趟结果也写盘，因此总I/O为4×2N=8N页。",
            [("merge_fan_in_and_pass_recurrence", "输入缓冲为2，段数每趟取ceil(r/2)：9、5、3、2、1，共4趟。"),
             ("external_io_accounting", "每一趟读N页、写N页且末趟也落盘，总代价8N页。")],
            [("fan_in", "总块缓冲3减去输出块1，每趟输入扇入为2。"),
             ("run_counts", "9段经四趟依次归并为5、3、2、1段。"),
             ("io_total", "四趟各读写N页，归并总I/O为8N页。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("需把输出缓冲从可归并路数中扣除，逐趟计算段数并累计读写全文件的I/O。",
             "用扇入M−1递推段数至1，并对每一完整归并趟计一次读和一次写。",
             "忽略输出缓冲会把扇入误算为3；若末趟写盘则不能少计一轮写I/O。",
             "训练外部排序的多路归并能力与磁盘I/O成本模型。"),
            ["外部排序", "多路归并", "磁盘I/O"]),
        item("z5b3-408-adjacency-list-directed-degrees", "cs408.ds.topic.0eb5ea0549e9", "D",
            "有向图G的顶点为A、B、C、D、E，弧为A→B、A→D、B→C、C→A、D→C、D→E。采用邻接表且每条有向弧只在弧尾顶点的表中存一次。关于邻接表表结点总数及顶点D的出度，正确的是（ ）。",
            {"A":"12，2", "B":"6，1", "C":"12，3", "D":"6，2"},
            "每条有向弧在一个弧尾表中产生一个边结点，6条弧共6个表结点。D的邻接表列出C、E两项，故出度为2。对照入度，C有来自B、D的两条入弧，A有来自C的一条入弧。",
            [("edge_node_count", "在有向图邻接表中，每条弧尾对应一项表结点，总数为6个。"),
             ("outgoing_list_and_degree", "D的出边为D→C和D→E，邻接表长度及出度均为2。")],
            [("stored_references", "六条有向弧各存一次，表结点总数为6。"),
             ("degree_trace", "顶点D的邻接表含C和E两项，出度为2。")],
            {"A":False,"B":False,"C":False,"D":True},
            ("需要区分弧的存储方向、邻接表结点计数与入度和出度的含义。",
             "逐条核对弧尾表结点总数，再枚举指定顶点的出邻接点。",
             "将无向图每条边存两份的规则误用于有向弧，会把总表结点数翻倍。",
             "把图的抽象边集映射到邻接表存储量和局部度数。"),
            ["邻接表", "有向图", "度数计算"]),
        item("z5b3-408-syscall-mode-vs-context", "cs408.os.topic.05dcc6b2951b", "A",
            "某进程连续执行3次read系统调用；假设数据均已在页缓存中、调用立即返回，期间没有时钟中断、抢占或其他进程运行。每次系统调用都执行用户态到内核态再返回用户态。总共发生的特权级切换次数及进程上下文切换次数分别为（ ）。",
            {"A":"6次，0次", "B":"3次，0次", "C":"6次，3次", "D":"0次，3次"},
            "每次read从用户态陷入内核态一次，返回用户态一次，共2次特权级切换；3次共6次。题干明确无阻塞、抢占或其他进程运行，因此不发生进程上下文切换。系统调用进入内核态本身不等同于进程切换。",
            [("privilege_transition_count", "三次系统调用各包含一次trap入内核和一次返回，总计6次特权级切换。"),
             ("scheduler_condition_check", "无阻塞、抢占或其他进程运行，不触发进程上下文切换。")],
            [("system_call_transitions", "每次read有进入和返回两个特权级转换，三次共6次。"),
             ("process_switch_condition", "无调度事件且同一进程继续执行，进程上下文切换为0次。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需要区分处理器特权级转换与调度器切换进程这两个不同事件。",
             "按每次调用统计trap和返回，再依据是否发生阻塞或调度判定进程切换。",
             "把每次系统调用都误计为进程切换，忽略题设明确排除阻塞和抢占。",
             "澄清系统调用成本、内核态执行和上下文切换之间的概念边界。"),
            ["系统调用", "特权级转换", "上下文切换"]),
        item("z5b3-408-user-level-thread-blocking", "cs408.os.topic.e8dd56864fdc", "C",
            "某进程使用纯用户级线程库管理4个线程，操作系统内核只看见这一个进程；线程库不支持异步I/O或运行时拆分阻塞调用。该进程中的一个线程执行会阻塞的同步read系统调用时，哪项最符合此模型？",
            {"A":"内核只阻塞该用户线程，其余线程必在同一进程继续运行", "B":"内核可把4个用户线程自动分配到4个处理器并行执行", "C":"内核阻塞整个进程，进程内其他用户级线程不能由该库继续调度", "D":"系统调用不会进入内核态，因此read立即返回"},
            "纯用户级线程对内核不可见；阻塞read进入内核后，内核只能阻塞承载这些线程的整个进程。由于题设排除异步I/O及运行时拆分，用户态线程库无法在该进程阻塞期间切换到其他用户线程；内核也不能把这些线程独立分配到多个处理器。",
            [("kernel_visibility_model", "内核调度实体只有该进程，read阻塞会阻塞进程这一内核实体。"),
             ("user_library_scheduling_constraint", "题设没有异步拆分机制，进程阻塞期间用户态线程库无法运行。")],
            [("thread_mapping", "4个用户线程映射到内核可见的同一个进程调度实体。"),
             ("blocking_syscall_effect", "阻塞read使该进程睡眠，用户级线程库不能在睡眠期间调度其他线程。")],
            {"A":False,"B":False,"C":True,"D":False},
            ("需要将用户级线程的可见性、阻塞系统调用和处理器并行调度限制联系起来分析。",
             "先识别内核调度实体，再依据同步阻塞及无异步替代条件推导影响范围。",
             "把用户级线程与一对一内核线程的阻塞行为混淆，或把用户线程数等同于CPU并行度。",
             "帮助理解线程映射模型对阻塞行为和并行能力的实际影响。"),
            ["用户级线程", "线程阻塞", "线程映射"]),
        item("z5b3-408-inorder-threading-null-links", "cs408.ds.topic.36d6505de0b4", "A",
            "二叉树结构为：根4；4的左、右孩子为2、6；2的左、右孩子为1、3；6只有右孩子7。建立中序线索二叉树，并规定原本为空的左链域改作前驱线索、原本为空的右链域改作后继线索（首尾空线索仍指向空）。左线索与右线索各有多少条？",
            {"A":"4，3", "B":"4，4", "C":"3，4", "D":"5，2"},
            "中序序列为1、2、3、4、6、7。左孩子为空的结点为1、3、6、7，各产生一条左线索，共4条；右孩子为空的结点为1、3、7，共3条。结点6有右孩子7，结点2有右孩子3，均不产生右线索。",
            [("inorder_sequence_and_null_children", "中序序列1、2、3、4、6、7；左空链结点1、3、6、7，共4。"),
             ("right_null_child_count", "右空链结点为1、3、7，共3；结点2和6均有右孩子。")],
            [("left_thread_count", "左孩子为空的结点1、3、6、7共4个。"),
             ("right_thread_count", "右孩子为空的结点1、3、7共3个。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("必须根据明确树形逐结点统计左右空孩子，而不是把两类线索数互相推断。",
             "先写中序次序并列出每个结点的左右孩子，再分别计数空链域。",
             "左右空链域集合不同；将结点6误当成没有右孩子会把右线索数多算一条。",
             "训练线索二叉树中空指针转为前驱/后继线索的结构性计数。"),
            ["线索二叉树", "中序遍历", "空链域"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    args = parser.parse_args()
    output = OUT_DIR / ("preview-rerun02.json" if args.mode == "dry-run" else "checkpoint.json")
    if output.exists():
        raise SystemExit("refusing_to_overwrite_batch03_output")
    if not BACKUP.is_file() or hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper() != BACKUP_SHA256:
        raise SystemExit("post_batch02_backup_missing_or_hash_mismatch")
    pg_restore = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
    toc = subprocess.run([str(pg_restore), "--list", str(BACKUP)], capture_output=True, timeout=30)
    if toc.returncode or b"TABLE DATA public questions" not in toc.stdout:
        raise SystemExit("post_batch02_backup_archive_invalid")
    batch02.batch01.BACKUP, batch02.batch01.BACKUP_SHA256 = BACKUP, BACKUP_SHA256
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres",
        host="127.0.0.1", port=PORT, database=DB_NAME), pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.begin()
            try:
                report = batch02.batch01.run(db, candidate_specs=candidates(), batch_id="03")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH03_APPLIED"
                report["backup"]["toc_entries"] = len(toc.stdout.splitlines())
                if hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper() != BACKUP_SHA256:
                    raise ValueError("backup_changed_during_batch")
                db.rollback() if args.mode == "dry-run" else db.commit()
            except Exception:
                db.rollback()
                raise
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
        print(json.dumps({"status":report["status"],"accepted":len(report["accepted"]),
            "rejected":len(report["rejected"]),"checkpoint":output.relative_to(ROOT).as_posix()}, ensure_ascii=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
