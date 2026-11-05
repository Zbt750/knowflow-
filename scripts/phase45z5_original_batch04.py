"""Fourth constrained public-original batch for the owned isolated DB."""
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
BASE = ROOT / "scripts/phase45z5_original_batch03.py"
BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch03/post-batch03-applied.dump"
BACKUP_SHA256 = "C4FA09F4A4D71F251C16C37801646D726CB54C49D220B0ECB88AB64446E8A25F"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch04"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"

spec = importlib.util.spec_from_file_location("phase45z5_batch03", BASE)
batch03 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(batch03)


def candidates():
    item = batch03.batch02.item
    return [
        item("z5b4-math-parameter-limit-order", "math.exam.e90535214807", "B",
            "实数a、b满足 lim(x→0)[ln(1+ax+bx²)−2x]/x²=1。则(a,b)为（ ）。",
            {"A":"(2,1)","B":"(2,3)","C":"(−2,3)","D":"(1,5)"},
            "展开ln(1+ax+bx²)=ax+(b−a²/2)x²+o(x²)。商有有限极限先要求a−2=0，故a=2；极限值再要求b−2=1，故b=3。将(2,3)代回，分子为x²+o(x²)，极限确为1。",
            [("coefficient_matching", "先消去一次项得到a=2，再匹配二次项b−a²/2=1得到b=3。"),
             ("substitution_expansion_check", "代回a=2,b=3，ln(1+2x+3x²)−2x=x²+o(x²)，满足给定极限。")],
            [("finite_limit_condition", "一次项系数必须满足a−2=0。"),("second_order_coefficient", "二次项系数为b−a²/2=1，故b=3。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("必须先利用有限极限约束消除低阶项，再匹配目标二阶系数。","按Taylor阶次依次确定a与b，并将结果代回验证。","忽略对数展开的−u²/2项会把b错算为1；只匹配二阶项不能忽略一次项。","训练含两个未知参数的极限存在条件与系数识别。"),
            ["参数极限","对数展开","极限存在条件"], difficulty="medium"),
        item("z5b4-math-mvt-unique-point", "math.exam.4a56bd52caf7", "D",
            "函数f(x)=x³−3x在[0,2]上满足拉格朗日中值定理。所有满足 f′(ξ)=[f(2)−f(0)]/2 的ξ∈(0,2)中，最大的一个为（ ）。",
            {"A":"1/√3","B":"1","C":"√3","D":"2/√3"},
            "割线斜率为(f(2)−f(0))/2=(2)/2=1。f′(x)=3x²−3，令3ξ²−3=1，得ξ²=4/3。区间(0,2)内唯一解ξ=2/√3。注意选项D为2/√3，故正确选项应为D。",
            [("secant_slope_and_derivative_equation", "割线斜率1，导数方程3ξ²−3=1给出ξ=±2/√3。"),
             ("interval_filter", "仅正根2/√3位于(0,2)，因此最大且唯一。")],
            [("mean_value_slope", "[f(2)−f(0)]/2=1。"),("critical_point_filter", "f′(ξ)=1给出ξ=2/√3，满足区间限制。")],
            {"A":False,"B":False,"C":False,"D":True},
            ("需先算区间割线斜率，再解导数方程并依据开区间过滤根。","由f(2)=2得到斜率1，解二次方程后仅保留正根。","方程有正负两个根，但负根不在(0,2)；易误把√3或2/√3混淆。","把中值定理的存在点条件与区间约束、代数求根结合。"),
            ["拉格朗日中值定理","导数","区间根筛选"]),
        item("z5b4-math-eigen-rank-parameter", "math.exam.90bbbeb58b4a", "A",
            "矩阵A(a)=diag([[a,1],[0,a]], [a−2])。使A(a)的特征值0的代数重数恰为2的实数a是（ ）。",
            {"A":"a=0","B":"a=2","C":"a=0或2","D":"不存在"},
            "A(a)为分块上三角矩阵，特征多项式为(λ−a)²(λ−(a−2))。当a=0时，0作为前一Jordan块的特征值重数2，第三特征值为−2；当a=2时，第三块特征值为0而前两者为2，重数仅1。故仅a=0。",
            [("block_triangular_characteristic_polynomial", "对角块特征多项式相乘得(λ−a)²(λ−a+2)。"),
             ("parameter_case_multiplicity", "分别代入a=0与a=2，0的代数重数依次为2与1。")],
            [("characteristic_roots", "特征值为a（代数重数2）和a−2（重数1）。"),("zero_multiplicity", "a=0时重数2；a=2时重数1。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需由分块结构构造特征多项式，并区分相同特征值的重数与矩阵是否可对角化。","计算特征多项式后按参数分类统计λ=0的因子次数。","a=2时第三块才为零，但前块不为零；代数重数不是几何重数。","训练含参数矩阵特征值对零点重数的分类，保留特征多项式中的重复因子。"),
            ["特征值","代数重数","参数矩阵"], difficulty="medium"),
        item("z5b4-math-variable-force-work", "math.exam.ceb4bcf4246a", "D",
            "质点沿直线从x=0移动到x=2，沿运动方向的变力为F(x)=x(3−x)牛顿。该力所做的功为（ ）。",
            {"A":"2 J","B":"3 J","C":"4 J","D":"10/3 J"},
            "变力沿位移方向做功W=∫₀²F(x)dx=∫₀²(3x−x²)dx=[3x²/2−x³/3]₀²=6−8/3=10/3焦耳。区间上F(x)≥0，与运动方向一致，结果为正。",
            [("work_integral_model", "一维变力沿运动方向做功为力对位移的积分。"),
             ("exact_endpoint_evaluation", "原函数在2处为6−8/3=10/3，在0处为0。")],
            [("force_sign", "F(x)=x(3−x)在[0,2]非负，功为正。"),("antiderivative", "∫(3x−x²)dx=3x²/2−x³/3，端点差为10/3。")],
            {"A":False,"B":False,"C":False,"D":True},
            ("需要把变力功建模为定积分，保留方向与区间信息并进行精确端点计算。","先判断力与位移同向，再将位置相关的力在完整运动区间积分并化简精确分数。","只取终点力乘位移会忽略力随位置变化；积分上限代入时易漏立方项。","将定积分用于力学量累积，体现模型建立而非单纯原函数计算。"),
            ["定积分应用","变力做功","物理建模"]),
        item("z5b4-math-ode-integrating-factor", "math.exam.3b91ad45ab4c", "A",
            "一阶线性微分方程 y′+2y=e^(−x)，并满足y(0)=0。y(ln2)等于（ ）。",
            {"A":"1/4","B":"1/3","C":"1/2","D":"2/3"},
            "积分因子为e^(2x)，所以(e^(2x)y)′=e^x。积分并用y(0)=0得e^(2x)y=e^x−1，故y=e^(−x)−e^(−2x)。代入x=ln2，y=1/2−1/4=1/4。正确选项应为A。",
            [("integrating_factor_solution", "积分因子e^(2x)给出e^(2x)y=e^x−1。"),
             ("initial_condition_and_substitution", "初值确定常数为0，y(ln2)=1/2−1/4=1/4。")],
            [("linear_ode", "使用积分因子解得y=e^(−x)−e^(−2x)。"),("endpoint_check", "在ln2处分别为1/2与1/4，差为1/4。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需选择积分因子、应用初值并在对数点进行指数化简。","解线性方程后代入初值，再独立核对微分方程。","易将积分因子误写成e^(−2x)，或在e^(−2ln2)处漏掉平方。","把线性方程求解、初值确定和函数值计算串联起来。"),
            ["一阶线性微分方程","积分因子","初值问题"]),
        item("z5b4-408-router-longest-prefix", "cs408.cn.topic.0a2961dff8db", "C",
            "路由表含有目的前缀192.168.0.0/16→R1、192.168.1.0/24→R2、192.168.1.128/25→R3及默认路由→R0。目的地址192.168.1.200应转发到（ ）。",
            {"A":"R0","B":"R1","C":"R3","D":"R2"},
            "目的地址同时匹配/16、/24和/25三条前缀。路由器采用最长前缀匹配，选取掩码最长的/25，因此下一跳为R3。地址192.168.1.200落在192.168.1.128至192.168.1.255范围内。",
            [("prefix_membership", "192.168.1.200属于192.168.1.128/25，也属于其上级/24和/16。"),
             ("longest_prefix_rule", "逐项比较所有匹配前缀的位数，/25最长，因此最终选择R3下一跳。")],
            [("binary_prefix", "前三个八位组相同且最后一组200的最高位为1，匹配192.168.1.128/25。"),("route_selection", "最长匹配/25覆盖/24和/16。")],
            {"A":False,"B":False,"C":True,"D":False},
            ("需同时判断多个重叠前缀是否匹配，再按前缀长度优先级选择。","比较地址所属网段，并从匹配项中选择最长掩码。","仅按表项顺序或较粗的/16匹配会选错；/25边界128需正确处理。","训练路由转发的最长前缀匹配与CIDR范围判断。"),
            ["IP路由","CIDR","最长前缀匹配"]),
        item("z5b4-408-switch-learning-trace", "cs408.cn.topic.201ce80c4dd6", "D",
            "一台自学习以太网交换机初始转发表为空。端口1收到源MAC为A、目的MAC为B的帧；端口2随后收到源MAC为B、目的MAC为A的帧；最后端口3收到源MAC为C、目的MAC为A的帧。无老化且均为单播帧。第三帧的转发动作是（ ）。",
            {"A":"仅转发到端口2","B":"广播到端口1和2","C":"不转发","D":"仅转发到端口1"},
            "第一帧学习A→端口1，B未知，泛洪到其他端口。第二帧学习B→端口2，目的A已知，转发至端口1。第三帧学习C→端口3，目的A仍在端口1，故只转发到端口1，对应D。",
            [("mac_learning_state_trace", "处理前两帧后转发表有A→1、B→2；第三帧到达再学习C→3。"),
             ("known_unicast_forwarding", "目的A已知位于端口1，单播转发到端口1。")],
            [("forwarding_database", "三次源地址学习后A、B、C分别映射1、2、3。"),("third_frame_action", "第三帧目的A对应端口1，因此定向转发至端口1。")],
            {"A":False,"B":False,"C":False,"D":True},
            ("需要逐帧更新自学习转发表，并区分未知目的泛洪与已知目的定向转发。","按源地址学习端口映射，再查询目的MAC确定出端口。","把未知目的泛洪套用于已知单播，或忘记先从源地址学习都会选错。","把透明桥学习行为表示为状态机而非只背交换机定义。"),
            ["以太网交换机","自学习转发表","单播转发"]),
        item("z5b4-408-programmed-io-poll-count", "cs408.co.topic.bfd3c1878167", "B",
            "CPU以程序查询方式每隔5μs读取一次设备状态，查询时刻为0、5、10、…μs。设备在t=23μs变为就绪，CPU持续轮询直至首次读到就绪状态。首次成功查询前的失败查询次数和检测到就绪的时刻分别为（ ）。",
            {"A":"4次，20μs","B":"5次，25μs","C":"5次，23μs","D":"6次，30μs"},
            "在t=0、5、10、15、20μs的查询均早于23μs，故有5次失败查询。下一次查询在25μs首次读到就绪，因此检测时刻为25μs。设备实际就绪时刻与CPU观测时刻不同。",
            [("poll_schedule", "查询时刻序列中小于23的为0、5、10、15、20，共5次。"),
             ("first_observation_after_ready", "下一查询时刻为25μs，CPU在此时首次观测到已经就绪的设备状态。")],
            [("failed_polls", "floor(23/5)+1=5个早于23的查询时刻。"),("detection_latency", "首个不早于设备就绪时刻的轮询时刻为ceil(23/5)×5=25μs。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("需区分设备状态变化的真实时刻与离散轮询第一次观察到该变化的时刻。","列出等间隔查询序列，分别计数失败次数并取首个不早于就绪的查询。","把t=23当作CPU观测时刻会忽略轮询粒度；边界采用严格早于23计失败。","分析程序查询的检测延迟与CPU轮询开销。"),
            ["程序查询方式","轮询","设备状态检测"]),
        item("z5b4-408-bubble-sort-early-stop", "cs408.ds.topic.dd68a6da9516", "A",
            "对数组[4,1,5,2,3]执行升序冒泡排序：每趟从左至右比较相邻元素，最大元素沉至未排序区末端；第i趟只比较未排序区内相邻元素，若一整趟没有交换则停止。总比较次数和总交换次数为（ ）。",
            {"A":"9次，5次","B":"10次，5次","C":"9次，6次","D":"12次，5次"},
            "第1趟4次比较、交换3次，数组变为[1,4,2,3,5]；第2趟3次比较、交换2次，变为[1,2,3,4,5]；第3趟对剩余3个元素作2次比较且无交换，触发停止。总比较4+3+2=9，总交换3+2=5。",
            [("pass_by_pass_trace", "三趟比较数为4、3、2；交换数为3、2、0。"),
             ("sorted_result_and_stop", "第三趟扫描未发生交换，数组保持升序，因此符合提前停止条件并结束。")],
            [("adjacent_swap_simulation", "逐趟数组状态：41523→14235→12345→12345。"),("count_sum", "比较9次，交换5次。")],
            {"A":True,"B":False,"C":False,"D":False},
            ("需按每趟未排序区长度追踪比较、交换并应用无交换提前终止条件。","逐趟模拟数组状态变化，按缩短后的未排序区计数比较，并分别累计比较和交换。","把每趟比较数固定为n−1或漏掉最后一趟检查都会导致比较数错误。","训练冒泡排序状态演化与优化停止条件的计数分析。"),
             ["冒泡排序","排序过程","比较与交换次数"]),
        item("z5b4-408-tcp-advertised-window", "cs408.cn.topic.fdfe51b5d88a", "B",
            "TCP接收端缓冲区容量8192字节，当前已占用5500字节，下一期待序号为10000。随后按序收到长度分别为1000和800字节的两个数据段，应用程序在两段均交付后从缓冲区读走600字节。此时接收端新通告窗口及右边界（下一期待序号+窗口）为（ ）。",
            {"A":"692字节，12692","B":"1492字节，13292","C":"2092字节，13892","D":"2692字节，12692"},
            "两段按序到达后，下一期待序号从10000前移1800至11800。缓冲占用量为5500+1800−600=6700，空闲容量及可通告接收窗口为8192−6700=1492字节。接收窗口右边界为11800+1492=13292。",
            [("receive_sequence_and_buffer_conservation", "按序数据使RCV.NXT增加1800；占用量按收到1800并被应用读走600更新为6700。"),
             ("advertised_window_right_edge", "空闲窗口1492，右边界11800+1492=13292。")],
            [("byte_sequence_update", "收到的连续字节区间长度1800，下一期待序号变为11800。"),
             ("buffer_capacity_check", "缓冲空闲8192−6700=1492，序号加窗口得到右边界13292。")],
            {"A":False,"B":True,"C":False,"D":False},
            ("需要联合维护按序字节序号、接收缓冲区占用与应用读取造成的空闲空间。","先更新连续接收边界，再用容量守恒求通告窗口并计算其右边界。","误把窗口保持为初始值会忽略接收数据和应用读取；右边界不是当前序号加已占用量。","把TCP流量控制状态从单一窗口值扩展到序号边界与缓冲资源同步变化。"),
            ["TCP流量控制","接收窗口","累计确认序号"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    args = parser.parse_args()
    output = OUT_DIR / ("preview-rerun02.json" if args.mode == "dry-run" else "checkpoint.json")
    if output.exists():
        raise SystemExit("refusing_to_overwrite_batch04_output")
    if not BACKUP.is_file() or hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper() != BACKUP_SHA256:
        raise SystemExit("post_batch03_backup_missing_or_hash_mismatch")
    pg_restore = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
    toc = subprocess.run([str(pg_restore), "--list", str(BACKUP)], capture_output=True, timeout=30)
    if toc.returncode or b"TABLE DATA public questions" not in toc.stdout:
        raise SystemExit("post_batch03_backup_archive_invalid")
    batch03.batch02.batch01.BACKUP, batch03.batch02.batch01.BACKUP_SHA256 = BACKUP, BACKUP_SHA256
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres",
        host="127.0.0.1", port=PORT, database=DB_NAME), pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.begin()
            try:
                report = batch03.batch02.batch01.run(db, candidate_specs=candidates(), batch_id="04")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH04_APPLIED"
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
