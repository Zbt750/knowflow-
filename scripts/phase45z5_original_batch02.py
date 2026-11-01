"""Second constrained public-original batch for the owned isolated DB.

No external model calls. Dry-run is the default and rolls back its transaction.
"""
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

BASE = ROOT / "scripts/phase45z5_original_batch01.py"
BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch01/post-batch01.dump"
BACKUP_SHA256 = "96F7D282C1551DBEE4052C723B0F06627FE86038904AE1A2CDDC3CFC453517A4"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch02"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"

spec = importlib.util.spec_from_file_location("phase45z5_batch01", BASE)
batch01 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(batch01)


def item(request, node, answer, stem, options, explanation, methods, steps,
         truth, reason, tags, difficulty="medium"):
    from backend.services.question_generation import Output
    return {
        "request": request, "node": node, "answer": answer,
        "difficulty": difficulty, "tags": tags,
        "output": Output(stem=stem, question_type="single_choice", options=options,
            correct_answer=answer, final_value=answer, explanation=explanation,
            steps=[{"expression": a, "value": b} for a, b in steps]),
        "methods": [{"method": a, "result": b} for a, b in methods],
        "steps": [b for _, b in steps],
        "truth": truth,
        "reason": {"knowledge_depth": reason[0], "reasoning_steps": reason[1],
            "trap_design": reason[2], "application_value": reason[3]},
    }


def candidates():
    return [
        item("z5b2-math-implicit-second-derivative", "math.calculus.differential.implicit", "B",
            "曲线 x²+xy+y²=3 在点(1,1)附近确定 y=y(x)。该点的 y'' 为（ ）。",
            {"A":"−1/3", "B":"−2/3", "C":"2/3", "D":"1/3"},
            "令F=x²+xy+y²−3=0。一次求导得2x+y+(x+2y)y'=0，在(1,1)有y'=−1。再求导：2+2y'+(x+2y)y''+2(y')²=0，代入得2−2+3y''+2=0，故y''=−2/3。",
            [("implicit_first_and_second_derivative", "由F_x+F_y y'=0求y'，再对等式求导得到y''=−2/3。"),
             ("implicit_hessian_formula", "−(F_xx+2F_xy y'+F_yy(y')²)/F_y=−(2−2+2)/3=−2/3。")],
            [("first_derivative", "在(1,1)代入一阶隐函数关系得到y′=−1。"), ("second_derivative", "代入二阶导数等式得到y″=−2/3。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("先由隐函数关系求一阶导数，再对含y'的表达式再次求导并处理交叉项。",
             "先算y'，后代入二阶隐函数导数公式；以直接二次求导复核。",
             "易漏掉两项xy'的求导贡献，导致交叉项系数或符号错误。",
             "训练隐函数曲线在指定点的二阶局部变化，而非仅求切线斜率。"),
            ["隐函数求导", "二阶导数", "链式法则"]),
        item("z5b2-math-improper-rotation-thresholds", "math.exam.9f10ce353fbd", "A",
            "设 p=3/4，区域 y=x^(−p) (x≥1) 与x轴围成无界区域。该区域绕x轴旋转所得体积V与侧面积S（不含底面）分别满足（ ）。",
            {"A":"V有限，S发散", "B":"V发散，S有限", "C":"V、S均有限", "D":"V、S均发散"},
            "圆盘法V=π∫₁∞x^(−2p)dx，p=3/4使指数−3/2，故V收敛。旋转侧面积S=2π∫₁∞x^(−p)√(1+p²x^(−2p−2))dx；根号因子趋于1且有正上下界，故与∫x^(−p)同敛散。p=3/4≤1，S发散。",
            [("volume_integral_p_test", "V与∫₁∞x^(−3/2)dx同敛，有限。"),
             ("surface_area_comparison", "根号因子趋于1并有界，S与∫₁∞x^(−3/4)dx同敛散，发散。")],
            [("volume_integrand", "体积被积幂函数为πx^(−3/2)，积分收敛。"), ("surface_integrand_order", "侧面积被积项与x^(−3/4)同阶，积分发散。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需要区分旋转体积的平方半径与侧面积的一次半径，并分别应用无穷积分比较判别。",
             "先写正确几何积分，再分别比较幂函数指数，避免把体积和面积使用同一收敛阈值。",
             "体积阈值p>1/2而侧面积阈值p>1，混用两个阈值会选错。",
             "连接旋转体几何建模与广义积分敛散性，体现参数对量纲和收敛性的影响。"),
            ["旋转体体积", "反常积分", "比较判别法"]),
        item("z5b2-math-hessian-all-stationary", "math.exam.58a5d04a7be9", "C",
            "函数 f(x,y)=x⁴+y⁴−4xy 的全部实驻点及类型为（ ）。",
            {"A":"仅(0,0)，极小点", "B":"(0,0)为鞍点，(1,1)、(−1,−1)为极大点", "C":"(0,0)为鞍点，(1,1)、(−1,−1)为极小点", "D":"原点为极大点，另有两个鞍点"},
            "驻点方程为x³=y、y³=x，因此x=x⁹，实解x∈{−1,0,1}，分别得(−1,−1)、(0,0)、(1,1)。Hessian为[[12x²,−4],[−4,12y²]]。原点行列式−16<0，为鞍点；在±1处主元12>0且行列式128>0，Hessian正定，均为严格极小点。",
            [("stationary_system_reduction", "y=x³且x=y³，解得对角线上x=−1,0,1。"),
             ("hessian_determinant_test", "D(0,0)=−16；D(±1,±1)=128且f_xx=12>0。")],
            [("critical_points", "(−1,−1),(0,0),(1,1)"), ("classification", "原点鞍点；两个非零驻点为极小点")],
            {"A":False,"B":False,"C":True,"D":False},
            ("需要完整解非线性驻点方程，再在不同驻点分别使用Hessian判别。",
             "先消元求出全部驻点，随后分别计算Hessian行列式并检查正定性条件。",
             "只解出原点会漏掉对称的两个驻点；Hessian在原点退化与非退化点判据不同。",
             "综合检验多元极值的驻点枚举、对称性和二阶判别，而非只代入一个点。"),
            ["驻点求解", "Hessian判别", "多元函数极值"]),
        item("z5b2-math-double-integral-centroid", "math.exam.5af66b782c26", "B",
            "三角形区域 D={(x,y):x≥0,y≥0,x+y≤1} 的面密度为ρ(x,y)=x+y。其质心的横坐标 x̄ 为（ ）。",
            {"A":"1/4", "B":"3/8", "C":"1/3", "D":"1/2"},
            "质量M=∬_D(x+y)dA=1/3。对y轴的力矩M_y=∬_D x(x+y)dA=∫₀¹∫₀^(1−x)(x²+xy)dy dx=1/8。因此x̄=M_y/M=(1/8)/(1/3)=3/8。",
            [("iterated_moment_integral", "M=1/3，M_y=1/8，故x̄=3/8。"),
             ("symmetry_and_polynomial_integral", "区域及密度关于x、y交换对称，质心两坐标相同；直接积分所得x坐标为3/8。")],
            [("mass", "区域面密度积分得到总质量M为1/3。"), ("first_moment_about_y_axis", "关于y轴的一阶矩My计算结果为1/8。"), ("centroid_x", "由质心定义My除以M得到横坐标3/8。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("需在三角形区域上建立二重积分，并区分总质量和对坐标轴的一阶矩。",
             "先积分密度得质量，再积分xρ得力矩，最后用质心定义求比值。",
             "将均匀密度质心直接套用会忽略ρ=x+y的非均匀分布。",
             "练习二重积分在质量分布中的建模与对称性复核。"),
            ["二重积分应用", "质量与质心", "积分区域"]),
        item("z5b2-math-mvt-two-points-product", "math.exam.4586eb88acb7", "D",
            "对 f(x)=x³−3x 在区间[−2,2]应用拉格朗日中值定理，所有满足 f′(c)=[f(2)−f(−2)]/4 的 c 值之积为（ ）。",
            {"A":"−2", "B":"−2/√3", "C":"2/3", "D":"−4/3"},
            "端点割线斜率为(2−(−2))/4=1。令f′(c)=3c²−3=1，得c²=4/3，故两个解为±2/√3，均在(−2,2)内，乘积为−4/3。",
            [("mean_value_equation", "端点斜率1，方程3c²−3=1得到c=±2/√3。"),
             ("root_product", "两个中值点是关于0对称的相反数，积为−(2/√3)²=−4/3。")],
            [("secant_slope", "端点差4除以区间长度4，平均变化率为1。"), ("mvt_points", "区间内两个中值点为正负2除以根号3。"), ("product", "两个中值点相乘得到负的4/3。")],
            {"A":False,"B":False,"C":False,"D":True},
            ("需同时计算割线斜率、解导数方程并确认中值点在开区间内。",
            "从定理方程求出区间内的全部根，再计算这些根的乘积。",
             "只取正根会漏解；将平均变化率误当成端点函数值也会改变方程。",
             "训练定理结论中的存在点可能不唯一，并要求汇总全部满足条件的点。"),
            ["拉格朗日中值定理", "导数方程", "多解分析"]),
        item("z5b2-408-crc-long-division", "cs408.cn.topic.7507d0c4e02a", "C",
            "数据位串为1101011011，CRC生成多项式为二进制10011。按模2除法生成的4位CRC余数为（ ）。",
            {"A":"1010", "B":"0111", "C":"1110", "D":"1101"},
            "生成多项式次数为4，数据后补4个0，模2长除所得余数为1110。发送码字为11010110111110；再以10011进行模2除法，余数为0000。",
            [("polynomial_long_division", "11010110110000 除以10011的模2余数为1110。"),
             ("codeword_syndrome_check", "将1110附加后复除，综合余数为0000。")],
            [("append_zero_bits", "数据末尾追加四个0后得到11010110110000。"), ("crc_remainder", "模二长除法得到四位余数1110。"), ("receiver_syndrome", "附加余数后的码字综合余数为0000。")],
            {"A":False,"B":False,"C":True,"D":False},
            ("需依据生成多项式次数补零并逐位执行异或长除，不能把CRC当普通整数除法。",
            "先求模二除法余数，再对生成码字执行接收端综合校验。",
             "常见错误是补错零位数或把减法按借位运算处理。",
             "从手算CRC生成延伸到接收端零综合验证。"),
            ["CRC", "模2运算", "差错检测"]),
        item("z5b2-408-wlan-backoff-freeze-timeline", "cs408.cn.topic.1351211c91cf", "A",
            "两站A、B均在DIFS结束时开始竞争，时隙9μs，A随机退避计数为1、B为4。A先发送120μs数据，随后经过SIFS 10μs和ACK 20μs；发送期间B冻结计数。ACK结束后信道空闲，仍需等待DIFS 34μs，之后B继续倒计时。忽略其他开销，B开始发送的时刻为（以首次DIFS开始为t=0）（ ）。",
            {"A":"254μs", "B":"263μs", "C":"236μs", "D":"245μs"},
            "初始DIFS结束于34μs，A用一个时隙后于43μs开始发送，持续120μs至163μs；SIFS和ACK后于193μs结束。随后DIFS至227μs，B剩余3个时隙，倒计时27μs后于254μs发送。",
            [("dcf_slot_freeze_timeline", "A起发43，ACK完成193；再次DIFS至227，B剩余3槽，因此B于254μs起发。"),
             ("counter_state_trace", "A计数1耗1槽；B计数4同期减1为3，繁忙期冻结，空闲DIFS后再耗3槽。")],
            [("A_start", "A退避一个9微秒时隙后于43微秒开始发送。"), ("B_remaining_counter", "A发帧期间B冻结，剩余退避计数为3个时隙。"), ("B_start", "ACK结束后等待DIFS和三个时隙，B于254微秒起发。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需要按DCF规则区分退避递减、发送期间冻结以及ACK后的DIFS恢复。",
            "建立绝对时间线，并在信道忙闲转换时单独追踪B的剩余计数。",
             "把SIFS、ACK、DIFS的先后顺序混淆，或在信道忙时继续递减退避值。",
             "把无线介质竞争状态转换落实为可检验的微秒时间线。"),
            ["802.11 DCF", "退避计数", "时序分析"]),
        item("z5b2-408-store-forward-pipeline", "cs408.cn.topic.658f7cffbc1f", "D",
            "3个长度均为1000B的分组依次经过两条串行存储转发链路，速率分别为8Mb/s和4Mb/s；每条链路传播时延均为1ms。允许不同链路上的分组流水传输，无排队以外的处理开销。第3个分组完整到达终点的时刻为（ ）。",
            {"A":"7ms", "B":"8ms", "C":"10ms", "D":"9ms"},
            "每包在第一链路发送1ms、传播1ms，故到达第二链路的时刻依次为2、3、4ms。第二链路每包发送2ms，服务区间依次为[2,4]、[4,6]、[6,8]ms；第三包再传播1ms，于9ms到达。",
            [("store_forward_pipeline_schedule", "链路1到达时刻2、3、4ms；链路2发送区间2–4、4–6、6–8ms；末端到达9ms。"),
             ("bottleneck_pipeline_formula", "总时延首包为1+1+2+1=5ms，后续每包受4Mb/s瓶颈间隔2ms，第三包5+2×2=9ms。")],
            [("link1_serialization", "1000B在8Mb/s链路上的发送时延为1ms。"), ("link2_serialization", "1000B在4Mb/s链路上的发送时延为2ms。"), ("third_arrival", "第三个分组经第二链路传播后于9ms到达。")],
            {"A":False,"B":False,"C":False,"D":True},
            ("需要结合逐链路存储转发、传播时延与瓶颈链路流水节拍。",
             "先算每链路串行化时延，再列首包和后续分组在第二链路的服务时间。",
             "简单把三包所有链路时延串行相加会忽略跨链路流水；只算瓶颈间隔则会漏首包传播。",
            "训练端到端分组时延与流水传输吞吐节拍之间的区别。"),
            ["分组时延", "存储转发", "流水传输"]),
        item("z5b2-408-alignment-endian-struct", "cs408.co.topic.236ea41712f9", "B",
            "某ABI规定char大小/对齐为1/1、uint16为2/2、uint32为4/4；结构体成员按声明顺序放置，各成员起始偏移须是自身对齐值的倍数，结构体总长补齐到最大成员对齐值的倍数。采用小端序，结构体{char c=0x11; uint32 x=0x12345678; uint16 y=0x9ABC;}中，x的起始偏移、x的4个存储字节和结构体总长分别为（ ）。",
            {"A":"1；12 34 56 78；8B", "B":"4；78 56 34 12；12B", "C":"4；12 34 56 78；10B", "D":"2；78 56 34 12；10B"},
            "c占偏移0。为满足uint32的4字节对齐，偏移1至3填充，x从偏移4开始并占4字节；小端序使最低有效字节78存于低地址，故偏移4至7依次为78 56 34 12。y从偏移8开始并占2字节。结构体最大对齐为4，总长10向上补齐为12字节。",
            [("member_alignment_layout", "偏移依次为c=0、x=4、y=8，末字段占用后原始末端为10。"),
             ("little_endian_byte_order", "0x12345678按最低有效字节放低地址，x字段内存顺序为78 56 34 12。"),
             ("aggregate_alignment_roundup", "结构体对齐为4，ceil(10/4)×4=12字节。")],
            [("field_offsets", "char、uint32、uint16的起始偏移依次为0、4、8。"), ("little_endian_bytes", "uint32值0x12345678在偏移4至7依次存为78 56 34 12。"), ("aligned_size", "最后字段到偏移10，按最大对齐4补齐后大小为12字节。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("需要逐字段处理内部填充，再按结构体最大对齐要求处理尾部填充。",
             "依声明顺序取满足对齐倍数的最小偏移，最后向上取整结构体总长。",
             "字段大小直接相加会漏掉中间和末尾填充；大小端概念也不能替代对齐计算。",
             "联合检验数据表示中的布局规则，并辨明端序与对齐的不同作用。"),
            ["结构体对齐", "数据表示", "存储布局"]),
        item("z5b2-408-round-robin-arrival-order", "cs408.os.topic.bc235cd7a2fb", "C",
            "采用时间片轮转，时间片2，进程在时间片结束时若未完成则进入就绪队尾；到达进程在同一时刻先入队，再将被抢占进程入队。A、B、C分别在0、1、2时刻到达，运行时间分别为5、3、1，切换开销为0。平均等待时间为（ ）。",
            {"A":"3", "B":"4", "C":"10/3", "D":"11/3"},
            "时间线为A[0,2)、B[2,4)、C[4,5)、A[5,7)、B[7,8)、A[8,9)。等待时间按完成−到达−运行计算：A=9−0−5=4，B=8−1−3=4，C=5−2−1=2；平均等待时间为(4+4+2)/3=10/3。",
            [("round_robin_queue_trace", "按题设同刻入队顺序逐个时间片推进，完成时刻A=9、B=8、C=5。"),
             ("waiting_time_identity", "用完成时刻减到达时刻与运行时间，等待时间为4、4、2，平均10/3。")],
            [("timeline", "时间片执行顺序为A、B、C、A、B、A，结束时刻依次为2、4、5、7、8、9。"), ("waiting", "A、B、C等待时间依次为4、4、2。"), ("mean", "三者等待时间的算术平均值为10/3。")],
            {"A":False,"B":False,"C":True,"D":False},
            ("需要维护轮转就绪队列、处理同刻到达顺序，并从完成时刻计算周转时间。",
            "逐时间片更新队列与剩余运行时间，最后按完成−到达−运行求平均等待时间。",
             "混淆等待时间与周转时间会得到不同结果；同刻队列规则会影响后续顺序。",
             "训练时间片调度中的事件排序及等待时间指标计算。"),
            ["时间片轮转", "进程调度", "周转时间"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    args = parser.parse_args()
    output = OUT_DIR / ("preview-rerun04.json" if args.mode == "dry-run" else "checkpoint.json")
    if output.exists():
        raise SystemExit("refusing_to_overwrite_batch02_output")
    if not BACKUP.is_file() or hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper() != BACKUP_SHA256:
        raise SystemExit("post_batch01_backup_missing_or_hash_mismatch")
    pg_restore = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
    toc = subprocess.run([str(pg_restore), "--list", str(BACKUP)], capture_output=True, timeout=30)
    if toc.returncode or b"TABLE DATA public questions" not in toc.stdout:
        raise SystemExit("post_batch01_backup_archive_invalid")
    batch01.BACKUP, batch01.BACKUP_SHA256 = BACKUP, BACKUP_SHA256
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres",
        host="127.0.0.1", port=PORT, database=DB_NAME), pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.begin()
            try:
                report = batch01.run(db, candidate_specs=candidates(), batch_id="02")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH02_APPLIED"
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
