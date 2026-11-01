"""Fifth constrained public-original batch for the owned isolated DB."""
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
BASE = ROOT / "scripts/phase45z5_original_batch04.py"
BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch04/post-batch04.dump"
BACKUP_SHA256 = "756CFED82EDECC32411E0EFB8C48579EA4DEEB392B6739A3C8CB4EE4A7AA7049"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch05"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"

spec = importlib.util.spec_from_file_location("phase45z5_batch04", BASE)
batch04 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(batch04)


def candidates():
    item = batch04.batch03.batch02.item
    return [
        item("z5b5-math-reduction-order", "math.exam.66f8f7b61188", "A",
            "函数y满足y″=(y′)²，y(0)=0、y′(0)=1。y(1/2)等于（ ）。",
            {"A":"ln2","B":"1/2","C":"1","D":"2ln2"},
            "令p=y′，则p′=p²。分离变量得−1/p=x+C，由p(0)=1得p=1/(1−x)。再积分并用y(0)=0，得到y=−ln(1−x)，故y(1/2)=ln2。该解在包含[0,1/2]的区间内存在。",
            [("order_reduction", "以p=y′降阶并解p′=p²，得到p(x)=1/(1−x)。"),
             ("integrate_and_initial_value", "再积分p并使用y(0)=0，得y(x)=−ln(1−x)，代入1/2为ln2。")],
            [("reduced_equation", "令p=y′后满足p′=p²，初值p(0)=1给出p=1/(1−x)。"),
             ("solution_check", "y=−ln(1−x)满足方程与两个初值，且y(1/2)=ln2。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需将二阶非线性方程按y′降阶，并对所得一阶方程分离变量后再积分。","先求导数函数p，再求原函数y，两个初值分别确定两次积分常数。","若把y″直接当成y′平方的代数方程或漏用第二个初值，解会不唯一或错误。","考查二阶方程降阶、解的区间限制以及初值逐层恢复。"),
            ["二阶方程降阶","非线性微分方程","初值问题"]),
        item("z5b5-math-nonlinear-autonomous-ode", "math.exam.ec75fe95fe0f", "C",
            "初值问题y″=y·y′，y(0)=0、y′(0)=1。在包含0的解区间内，y(π/(2√2))等于（ ）。",
            {"A":"1","B":"0","C":"√2","D":"2"},
            "令p=y′并把p视作y的函数，则y″=p·dp/dy。方程给p(dp/dy)=yp，初值附近p不为0，故dp/dy=y，积分并用p(0)=1得p=1+y²/2。于是dy/dx=1+y²/2，积分得arctan(y/√2)=x/√2。代入x=π/(2√2)，右端为π/4，故y=√2。",
            [("autonomous_order_reduction", "p dp/dy=yp约化为dp/dy=y，得到p=1+y²/2。"),
             ("separation_and_inverse", "解dy/dx=1+y²/2得arctan(y/√2)=x/√2，所给x对应y=√2。")],
            [("reduced_first_integral", "由y″=y′dy′/dy=yy′，在初值邻域约去非零y′后得y′=1+y²/2。"),
             ("direct_substitution", "y=√2tan(x/√2)满足原方程和初值，代入指定点得到√2。")],
            {"A":False,"B":False,"C":True,"D":False},
            ("必须识别自主方程可令p(y)=y′降阶，再解出一阶积分关系。","先利用p dp/dy=yp求p(y)，随后分离变量并反解正切函数。","降阶时不能误写成p′(y)=yp；还需由指定自变量算出反正切角。","将二阶非线性自主方程降阶与初值分支、反函数求值串联。"),
            ["二阶非线性方程","自主方程降阶","变量代换"], difficulty="advanced"),
        item("z5b5-math-endpoint-integral-parameter", "math.exam.a62c828f6537", "B",
            "对实参数p，反常积分J(p)=∫₀¹ xᵖ ln(1/x)/(1−x) dx收敛的充要条件为（ ）。",
            {"A":"p≥0","B":"p>−1","C":"p>−2","D":"任意实数p"},
            "x→1时ln(1/x)/(1−x)→1，故端点1附近被积函数与有限函数xᵖ同阶，不产生发散。x→0时1/(1−x)趋于1，故与xᵖln(1/x)同敛散；∫₀^ε xᵖ|ln x|dx当且仅当p>−1收敛。因此充要条件是p>−1。",
            [("endpoint_one_limit", "由ln(1/x)∼1−x可知x→1时比值趋于1。"),
             ("endpoint_zero_comparison", "x→0时因子1/(1−x)有界且趋于1，使用幂乘对数积分判别得p>−1。")],
            [("substitution_at_zero", "令x=e^(−t)，端点0附近积分等价于∫^∞ t e^(−(p+1)t)dt，收敛当且仅当p+1>0。"),
             ("local_asymptotic_at_one", "端点1附近被积函数趋于1，故该端点对任意有限p都可积。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("必须分别分析两个端点；分母在1处为零但与对数零点抵消。","在0端用指数代换得到指数衰减条件，在1端用等价无穷小判定有界性。","只看x^p会遗漏对数因子虽不改变临界幂指数但影响边界p=−1的发散性质。","训练端点分类与含对数因子的临界收敛判定。"),
            ["广义积分","端点比较","含对数积分"]),
        item("z5b5-math-vector-representation-family", "math.exam.9a1731a929ab", "D",
            "在R³中u₁=(1,0,1)、u₂=(0,1,1)、u₃=(1,1,2)。向量w=(2,−1,1)可表示为a u₁+b u₂+c u₃。满足该表示的三元组(a,b,c)构成的集合维数为（ ）。",
            {"A":"0","B":"1且只有一个三元组","C":"2","D":"1且有无穷多个三元组"},
            "坐标方程为a+c=2、b+c=−1、a+b+2c=1。第三式等于前两式相加，故只有两个独立约束。令c=t，则a=2−t、b=−1−t，t可任取实数，解集为一维仿射直线，包含无穷多个三元组。",
            [("coordinate_equation_rank", "三条坐标方程中第三式由前两式线性组合得到，系数矩阵秩为2。"),
             ("parametric_solution", "令c=t得到(a,b,c)=(2−t,−1−t,t)，t∈R，为一维解集。")],
            [("generator_dependency", "u₃=u₁+u₂，故三个生成向量线性相关且其张成空间维数为2。"),
             ("consistency_and_dimension", "w在该平面内；三未知量减秩2得一维解集，参数式验证等式。")],
            {"A":False,"B":False,"C":False,"D":True},
            ("需要把向量表示转成线性方程组，并区分张成空间维数与表示系数解集维数。","列出坐标方程、识别冗余方程，再用自由参数写出全部表示。","u₃依赖于u₁、u₂，因此表示不唯一；不能把可表示误当作系数唯一。","训练向量组线性表示、方程组秩与表示多样性之间的联系。"),
            ["向量组线性表示","线性相关","方程组秩"]),
        item("z5b5-math-permutation-sign-composition", "math.exam.f99711e0ea65", "A",
            "4阶置换矩阵P满足P e₁=e₃、P e₂=e₁、P e₃=e₄、P e₄=e₂。det(P)等于（ ）。",
            {"A":"−1","B":"1","C":"0","D":"−2"},
            "该置换的单行表示为(3,1,4,2)。逆序对为(3,1)、(3,2)、(4,2)，共3个，故置换奇偶性为奇，置换矩阵行列式为(−1)³=−1。等价地，该置换分解为一个长度为4的循环，其符号为(−1)³。",
            [("inversion_count", "单行置换(3,1,4,2)有3个逆序，故符号为−1。"),
             ("cycle_decomposition", "映射形成一个4-循环，循环符号为(−1)^(4−1)=−1。")],
            [("permutation_matrix_columns", "列映射顺序为3、1、4、2，逆序数3为奇数。"),
             ("determinant_sign", "置换矩阵行列式等于置换符号，故为−1。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需要从基向量像确定置换单行表示，再计算置换符号。","用逆序数奇偶性计算，并以循环分解的符号独立复核。","把P e_i的像误写成矩阵第i行会改变单行置换；行列式只能为±1。","将置换矩阵结构与行列式符号、循环分解联系起来。"),
            ["置换矩阵","行列式","置换奇偶性"]),
        item("z5b5-408-preorder-inorder-postorder", "cs408.ds.topic.56a82ba8b1ba", "C",
            "一棵无重复关键字的二叉树先序序列为A、B、D、E、C、F，中序序列为D、B、E、A、F、C。其后序序列为（ ）。",
            {"A":"D、E、B、A、F、C","B":"D、B、E、F、C、A","C":"D、E、B、F、C、A","D":"B、D、E、C、F、A"},
            "先序首项A为根；中序中A左侧D、B、E为左子树，右侧F、C为右子树。左子树先序为B、D、E，根B及左右孩子D、E，因此左子树后序D、E、B。右子树先序C、F且中序F、C，说明C根、左孩子F，后序F、C。合并为D、E、B、F、C、A，对应C。",
            [("recursive_traversal_reconstruction", "按先序根在前、中序划分左右子树，递归得到左后序D,E,B及右后序F,C。"),
             ("root_partition_check", "根A分割中序两侧；右子树根C先于其左孩子F，故后序F,C，再访问A。")],
            [("left_and_right_subtrees", "左子树根B含左D右E；右子树根C含左F，因此左右后序分别DEB与FC。"),
             ("sequence_validation", "后序先输出左、右子树再输出A，完整结果DEB FCA。")],
            {"A":False,"B":False,"C":True,"D":False},
            ("需用先序定位根并用中序递归分割左右子树，不能只做局部重排。","分别重建根A的左右子树，递归求后序后再拼接根。","右子树C有左孩子F，不能把F放到C之后；后序根必须最后输出。","检验遍历序列之间的结构约束及二叉树唯一重建。"),
            ["先序遍历","中序遍历","二叉树重建"]),
        item("z5b5-408-selection-sort-stability", "cs408.ds.topic.ddb8a6a53756", "B",
            "对记录[(2,a),(2,b),(1,c)]执行升序简单选择排序。每趟在未排序区选取第一个最小关键字，并与未排序区首记录交换。完成第一趟后，关键字2的两个相等记录相对次序为（ ）。",
            {"A":"仍为a在b前，且算法稳定","B":"变为b在a前，算法不稳定","C":"仍为a在b前，但算法不稳定","D":"变为b在a前，但该实现稳定"},
            "第一趟未排序区中最小记录(1,c)位于末尾，与首记录(2,a)交换，数组成为[(1,c),(2,b),(2,a)]。相等关键字2的原次序a、b被逆转，故这种基于交换的简单选择排序实现不稳定。",
            [("selection_swap_trace", "首趟最小值(1,c)与首项(2,a)交换后为[(1,c),(2,b),(2,a)]。"),
             ("stability_definition_check", "相等关键字a、b的相对次序从a在b前变为b在a前，违反稳定性。")],
            [("record_identity_trace", "第一次交换把末项c移至首位，原中间记录b越过a。"),
             ("stable_sort_criterion", "算法稳定要求相等键保持相对次序，此实例出现次序反转。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("需要跟踪记录身份而不只是关键字，才能观察相等元素的相对次序变化。","逐项执行首趟选择及交换，再按稳定排序定义检查原相对次序。","把‘选择第一个最小值’误认为整个算法稳定；跨越相等记录的交换可改变次序。","用可复现的反例理解简单选择排序稳定性取决于实现操作。"),
            ["简单选择排序","排序稳定性","记录交换"]),
        item("z5b5-408-reno-fast-recovery-window", "cs408.cn.topic.b8e94d7c568d", "D",
            "按TCP Reno规则，某次丢失发生前飞行窗口FlightSize=20 MSS，慢启动阈值为24 MSS。收到第三个重复ACK时，假设立即快速重传并进入快速恢复，且采用ssthresh=max(FlightSize/2,2 MSS)、cwnd=ssthresh+3 MSS。此时ssthresh和cwnd分别为（ ）。",
            {"A":"24 MSS，27 MSS","B":"10 MSS，10 MSS","C":"10 MSS，12 MSS","D":"10 MSS，13 MSS"},
            "按题目给定Reno参数，ssthresh=max(20/2,2)=10 MSS；第三个重复ACK触发快速重传后，cwnd暂设为ssthresh+3=13 MSS。旧阈值24 MSS不再作为新阈值。选项D符合。",
            [("reno_threshold_update", "FlightSize/2=10 MSS大于下限2 MSS，更新ssthresh为10 MSS。"),
             ("third_duplicate_ack_state", "第三个重复ACK时cwnd=ssthresh+3 MSS=13 MSS。")],
            [("rule_substitution", "将FlightSize=20代入题设明确的阈值与快速恢复公式，得到10和13 MSS。"),
             ("old_threshold_exclusion", "新ssthresh由丢失时FlightSize计算，不能沿用旧阈值24 MSS。")],
            {"A":False,"B":False,"C":False,"D":True},
            ("需要结合飞行窗口计算新阈值，并区分第三个重复ACK时快速恢复的临时拥塞窗口。","先应用阈值下限公式，再应用Reno在第三个重复ACK时的cwnd调整。","把cwnd直接降到ssthresh或误把旧阈值沿用都会漏掉快速恢复的三个MSS补偿。","训练TCP拥塞控制丢包事件中阈值更新和快速恢复状态转移。"),
            ["TCP拥塞控制","Reno","快速重传与恢复"]),
        item("z5b5-408-stop-and-wait-efficiency", "cs408.cn.topic.e567ffa4c80f", "A",
            "停等协议在双向同速率10 Mbit/s链路上传输。数据帧有效载荷1000字节，ACK长32字节，单向传播时延5 ms；忽略处理时延、帧外开销且无差错。一个完整周期含数据帧发送、ACK发送和往返传播。有效载荷吞吐率约为（ ）。",
            {"A":"0.739 Mbit/s","B":"0.800 Mbit/s","C":"1.000 Mbit/s","D":"7.39 Mbit/s"},
            "数据发送时间8000/10^7=0.8 ms，ACK发送时间256/10^7=0.0256 ms，往返传播为10 ms。周期总长10.8256 ms，每周期成功交付8000 bit有效载荷，吞吐率约8000/0.0108256=739,110 bit/s，即0.739 Mbit/s。",
            [("cycle_time_accounting", "周期为0.8+0.0256+10=10.8256 ms。"),
             ("goodput_calculation", "每周期交付8000有效bit，除以周期秒数约为0.739 Mbit/s。")],
            [("serialization_delay", "1000字节与32字节分别需要0.8 ms与0.0256 ms发送。"),
             ("round_trip_propagation_and_rate", "传播往返10 ms；8000 bit/10.8256 ms约0.739 Mbit/s。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需在停等周期中分别计入数据与确认帧串行化时延及往返传播时延。","用链路速率求两次发送时长，再以单周期有效载荷除以总周期。","把10 ms往返传播漏掉会显著高估吞吐率；ACK也占用反向链路时间。","综合链路时延、帧长度与协议停等机制计算有效吞吐。"),
            ["通信基础","停等协议","带宽时延分析"]),
        item("z5b5-408-load-address-relocation", "cs408.os.topic.8266516a5539", "C",
            "一个可重定位目标模块内某函数入口的相对地址为0x02A，模块实际装入内存的起始物理地址为0x4000，且该地址字段需要加装入基址重定位。重定位后的物理地址为（ ）。",
            {"A":"0x4020","B":"0x4002","C":"0x402A","D":"0x42A0"},
            "可重定位地址字段保存模块内偏移0x02A，装入时将基址0x4000与偏移相加：0x4000+0x002A=0x402A。因此函数入口物理地址是0x402A。",
            [("base_plus_relocation_offset", "基址重定位将模块装入基址0x4000与相对地址0x002A相加。"),
             ("hexadecimal_addition", "十六进制低位0x000+0x02A=0x02A，结果0x402A。")],
            [("relocation_semantics", "模块内相对地址并非最终物理地址，加载器需要应用装入基址。"),
             ("address_arithmetic", "0x4000+0x002A=0x402A，选项C唯一匹配。")],
            {"A":False,"B":False,"C":True,"D":False},
            ("需理解可重定位地址与装入基址的关系，并以十六进制正确相加。","将模块相对偏移转换为同宽十六进制数后加基址。","把相对地址误当绝对地址或按十进制拼接数字会选错。","连接目标模块重定位语义与装入后的实际地址计算。"),
            ["程序装入","重定位","物理地址"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    args = parser.parse_args()
    output = OUT_DIR / ("preview.json" if args.mode == "dry-run" else "checkpoint.json")
    if output.exists():
        raise SystemExit("refusing_to_overwrite_batch05_output")
    if not BACKUP.is_file() or hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper() != BACKUP_SHA256:
        raise SystemExit("post_batch04_backup_missing_or_hash_mismatch")
    pg_restore = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
    toc = subprocess.run([str(pg_restore), "--list", str(BACKUP)], capture_output=True, timeout=30)
    if toc.returncode or b"TABLE DATA public questions" not in toc.stdout:
        raise SystemExit("post_batch04_backup_archive_invalid")
    batch04.batch03.batch02.batch01.BACKUP = BACKUP
    batch04.batch03.batch02.batch01.BACKUP_SHA256 = BACKUP_SHA256
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres",
        host="127.0.0.1", port=PORT, database=DB_NAME), pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.begin()
            try:
                report = batch04.batch03.batch02.batch01.run(db, candidate_specs=candidates(), batch_id="05")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH05_APPLIED"
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
