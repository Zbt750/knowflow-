"""Small reviewed Codex-original batch for the owned Phase 4.5Z-5 database.

Every candidate is independently derived in this file, admitted by the current
public auto-review service, and included in a new v3 set version. No LLM/API is
called. The target is hard-bound to the previously verified isolated cluster.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"
BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/known-content/post-known-fixes-pre-batch01.dump"
BACKUP_SHA256 = "C4960CBAC5904D31A98C5BE86232A256969D00DEA4B3F8333C98F77F32ECD0F2"
OUT = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch01/checkpoint.json"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def table_fingerprint(db: Session, model) -> tuple[int, str]:
    rows = []
    columns = list(model.__table__.columns)
    primary = [column.key for column in model.__table__.primary_key.columns]
    for row in db.scalars(select(model)).all():
        rows.append({column.key: getattr(row, column.key) for column in columns})
    rows.sort(key=lambda item: json.dumps([item.get(key) for key in primary], default=str))
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode("utf-8")
    return len(rows), hashlib.sha256(payload).hexdigest()


def policy_rule_fingerprint(db: Session) -> str:
    from backend.models.learning import KpMasteryPolicy
    fields = ["min_confirmations", "min_real_questions", "required_question_types",
        "policy_version", "required_question_origins", "excluded_question_types",
        "required_skill_tags", "required_variant_count", "min_day_span",
        "manual_mastered_credit", "review_intervals_days"]
    rows = [{"kp_id": str(row.kp_id), **{key: getattr(row, key) for key in fields}}
        for row in db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id)).all()]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def specs():
    from backend.services.question_generation import Output
    # Each item carries two distinct derivation/check paths, an option truth
    # table, and specific difficulty rationale. None uses a fixed-template API.
    return [
        {
            "request": "z5b1-math-limit-parameter-log-series",
            "node": "math.exam.e90535214807", "answer": "A", "difficulty": "medium",
            "tags": ["参数确定", "对数展开", "极限存在条件"],
            "output": Output(stem="设实数 a、b 满足 lim(x→0){ln(1+ax+bx²)−2x}/x²=3。则(a,b)为（ ）。",
                question_type="single_choice", options={"A":"(2,5)","B":"(2,1)","C":"(-2,5)","D":"(1,5)"},
                correct_answer="A", final_value="(2,5)",
                explanation="对数展开为 ax+(b−a²/2)x²+o(x²)。商要有有限极限，先令一次项系数 a−2=0，故a=2；再令二次项系数 b−a²/2=3，得b=5。检查：ln(1+2x+5x²)=2x+3x²+o(x²)，极限确为3。",
                steps=[{"expression":"a-2=0","value":"a=2"},{"expression":"b-a^2/2=3","value":"b=5"}]),
            "methods": [
                {"method":"logarithm_taylor_coefficients", "result":"先消去x项要求a=2，再匹配x²项 b−a²/2=3，唯一得到(2,5)。"},
                {"method":"sympy_series_substitution", "result":"将a=2,b=5代回，ln(1+2x+5x²)−2x=3x²+O(x³)；逐个干扰项均不满足系数约束。"}],
            "steps": ["有限极限首先要求分子的一阶项消失，因此a=2。", "将二阶Taylor系数与给定极限3相等，解得b=5；代回展开复核。"],
            "truth":{"A":True,"B":False,"C":False,"D":False},
            "reason":{"knowledge_depth":"需要同时处理一次项抵消与二阶对数展开，不能直接套一个标准极限值。","reasoning_steps":"先由有限性确定a，再用二阶系数确定b，并将所得参数代回验证。","trap_design":"常见错误是漏掉ln(1+u)中的−u²/2项，或把b直接当作二阶系数。","application_value":"训练参数极限的阶次匹配，使学生识别存在性约束与目标极限方程的先后关系。"}},
        {
            "request": "z5b1-math-definite-log-integral",
            "node": "math.exam.c431f98f817c", "answer": "C", "difficulty": "medium",
            "tags": ["分部积分", "有理化被积函数", "定积分"],
            "output": Output(stem="计算 I=∫₀¹ ln(1+x²) dx。",
                question_type="single_choice", options={"A":"ln2−2−π/2","B":"2−ln2+π/2","C":"ln2−2+π/2","D":"ln2+2−π/2"},
                correct_answer="C", final_value="ln(2)-2+pi/2",
                explanation="分部积分取u=ln(1+x²)、dv=dx，得I=ln2−∫₀¹2x²/(1+x²)dx。用x²/(1+x²)=1−1/(1+x²)，积分为2−π/2，故I=ln2−2+π/2。等价地，原函数为xln(1+x²)−2x+2arctan x。",
                steps=[{"expression":"integrate_by_parts","value":"ln(2)-2+pi/2"},{"expression":"x^2/(1+x^2)=1-1/(1+x^2)","value":"integral=2-pi/2"}]),
            "methods": [
                {"method":"integration_by_parts_then_rational_decomposition", "result":"I=ln2−∫2x²/(1+x²)dx=ln2−2+π/2。"},
                {"method":"antiderivative_differentiation_and_endpoint_check", "result":"对F=xln(1+x²)−2x+2arctan x求导得ln(1+x²)，F(1)−F(0)=ln2−2+π/2。"}],
            "steps": ["分部积分把对数积分转为有理式积分。", "将x²/(1+x²)拆成1−1/(1+x²)，计算端点并核对原函数导数。"],
            "truth":{"A":False,"B":False,"C":True,"D":False},
            "reason":{"knowledge_depth":"组合分部积分与有理式拆分，并需正确处理反正切端点。","reasoning_steps":"先选取对数作u，再把x²/(1+x²)拆分，最后用端点值求精确结果。","trap_design":"选项分别覆盖反正切符号、常数项与对数项错误，避免只凭数值量级猜测。","application_value":"练习含对数被积函数的定积分化简与原函数反向求导检查。"}},
        {
            "request": "z5b1-math-span-intersection-r4",
            "node": "math.exam.44eab8b0d00b", "answer": "A", "difficulty": "advanced",
            "tags": ["线性张成", "子空间交与和", "维数公式"],
            "output": Output(stem="在R⁴中令 U=span{(1,0,1,0),(0,1,1,0)}，V=span{(1,1,2,0),(0,0,0,1)}。求(dim(U+V),dim(U∩V))。（ ）",
                question_type="single_choice", options={"A":"(3,1)","B":"(3,0)","C":"(4,1)","D":"(4,0)"},
                correct_answer="A", final_value="(3,1)",
                explanation="V的第一个生成向量等于U中两个生成向量之和，因此交集至少含span{(1,1,2,0)}。令U的一般向量为(s,t,s+t,0)，与V一般向量(c,c,2c,d)相等，得s=t=c且d=0，故交集恰为一维。U+V由前两个独立向量和(0,0,0,1)张成，维数3。",
                steps=[{"expression":"u=s(1,0,1,0)+t(0,1,1,0)","value":"(s,t,s+t,0)"},{"expression":"u=v","value":"s=t=c,d=0"},{"expression":"dim(U+V)=dimU+dimV-dimIntersection","value":"2+2-1=3"}]),
            "methods": [
                {"method":"coordinate_equation_for_intersection", "result":"解(s,t,s+t,0)=(c,c,2c,d)，得到s=t=c,d=0，交集为一维。"},
                {"method":"rank_and_dimension_formula", "result":"四个生成向量的矩阵秩为3；dimU=dimV=2，故交维数2+2−3=1。"}],
            "steps": ["分别写出两个子空间的一般向量并解相等条件，求出交集。", "计算四个生成向量的秩，并用维数公式交叉检查。"],
            "truth":{"A":True,"B":False,"C":False,"D":False},
            "reason":{"knowledge_depth":"同一题同时考线性表示、交空间求解与子空间维数公式。","reasoning_steps":"先列一般向量方程求交，再独立计算和空间秩，最后用维数公式核对。","trap_design":"生成向量间有线性关系，容易误把四个向量当作线性无关或忽略交空间。","application_value":"训练用坐标方程与秩两种视角处理子空间交和，而非只背维数公式。"}},
        {
            "request": "z5b1-math-inflection-coordinates",
            "node": "math.exam.79c96a83b3ff", "answer": "B", "difficulty": "medium",
            "tags": ["二阶导数", "凹凸性", "拐点"],
            "output": Output(stem="曲线 y=x⁴/4−x³ 的拐点坐标为（ ）。",
                question_type="single_choice", options={"A":"仅(0,0)","B":"(0,0)与(2,−4)","C":"(0,0)与(2,4)","D":"仅(2,−4)"},
                correct_answer="B", final_value="(0,0),(2,-4)",
                explanation="y′=x³−3x²，y″=3x(x−2)。y″在x=0及x=2处均变号，所以两处均为拐点。代回原函数：y(0)=0，y(2)=4−8=−4，故坐标为(0,0)和(2,−4)。",
                steps=[{"expression":"y''=3x(x-2)","value":"sign changes at 0 and 2"},{"expression":"y(2)=2^4/4-2^3","value":"-4"}]),
            "methods": [
                {"method":"second_derivative_sign_chart", "result":"y″=3x(x−2)，符号依次为正、负、正，两个零点均为凹凸改变点。"},
                {"method":"factor_roots_and_direct_coordinate_substitution", "result":"因式分解得根0、2；代回y得0、−4，排除只求横坐标或误算函数值的选项。"}],
            "steps": ["求二阶导并制作符号区间，确认两个零点处都发生凹凸改变。", "把横坐标代回曲线方程，求完整拐点坐标。"],
            "truth":{"A":False,"B":True,"C":False,"D":False},
            "reason":{"knowledge_depth":"考查拐点判定不能止于y″=0，还必须确认凹凸性实际改变。","reasoning_steps":"先求二阶导及符号区间，再回代函数求纵坐标。","trap_design":"干扰项针对漏查变号、漏报纵坐标与代值算术符号错误。","application_value":"把导数符号分析与曲线几何信息连接起来，形成完整拐点判断过程。"}},
        {
            "request": "z5b1-math-parameter-matrix-rank",
            "node": "math.exam.36050d277510", "answer": "A", "difficulty": "medium",
            "tags": ["参数矩阵", "行列式", "秩"],
            "output": Output(stem="令 A(a)=[[1,a,0],[a,1,0],[0,0,a+1]]，a∈R。A(a)奇异时的参数及对应秩为（ ）。",
                question_type="single_choice", options={"A":"a=−1时秩1，a=1时秩2","B":"a=−1时秩2，a=1时秩1","C":"a=−1、1时秩均为1","D":"仅a=1时奇异且秩2"},
                correct_answer="A", final_value="a=-1:rank1; a=1:rank2",
                explanation="行列式为(1−a²)(a+1)=(1−a)(1+a)²，因此奇异参数为−1与1。a=−1时前2×2块[[1,−1],[−1,1]]秩1且末对角元为0，总秩1；a=1时前块秩1、末对角元2非零，总秩2。",
                steps=[{"expression":"det(A)=(1-a^2)(a+1)","value":"(1-a)(1+a)^2"},{"expression":"rank at a=-1","value":"1"},{"expression":"rank at a=1","value":"2"}]),
            "methods": [
                {"method":"determinant_factorization", "result":"detA=(1−a²)(a+1)，实根仅−1和1。"},
                {"method":"block_rank_by_parameter_substitution", "result":"逐个代入−1、1，前2×2块秩均为1；末对角元分别0、2，故总秩依次1、2。"}],
            "steps": ["利用分块结构计算行列式并求出全部实奇异参数。", "分别代入参数计算前块与末对角块秩，不能只凭行列式判定奇异矩阵的秩。"],
            "truth":{"A":True,"B":False,"C":False,"D":False},
            "reason":{"knowledge_depth":"同时考查参数行列式零点与奇异矩阵的秩，行列式为零并不能确定秩。","reasoning_steps":"先因式分解求全部奇异参数，再分别分析两个参数下的块秩。","trap_design":"两个参数下秩不同，专门防止把‘奇异’统一误判为同一个秩。","application_value":"训练参数矩阵题从可逆性判断继续推进到解空间维数相关的秩分析。"}},
        {
            "request": "z5b1-408-cache-writeback-conflict",
            "node": "cs408.co.topic.ba9896acc602", "answer": "B", "difficulty": "advanced",
            "tags": ["Cache组相联", "LRU", "写回与写分配"],
            "output": Output(stem="Cache数据区4KiB，块16B，2路组相联，采用LRU、写回和写分配，初始为空。依次访问 W(0)、R(2048)、R(4096)、R(0)、R(2048)，括号内为字节地址。缺失次数和因脏块淘汰产生的写回次数分别为（ ）。",
                question_type="single_choice", options={"A":"4次，1次","B":"5次，1次","C":"5次，2次","D":"3次，1次"},
                correct_answer="B", final_value="5 misses,1 writeback",
                explanation="共有4096/(16×2)=128组。地址0、2048、4096对应块号0、128、256，均落在第0组。W(0)缺失并把块0置脏；R2048缺失后同组为0、128；R4096再缺失，LRU淘汰脏块0，写回1次。随后R0缺失淘汰较旧的干净块128；R2048再次缺失淘汰干净块256。总计5次缺失、1次脏块写回。",
                steps=[{"expression":"sets=4096/(16*2)","value":"128"},{"expression":"block_index=address/16; set=block_index mod 128","value":"0,128,256 all map to set 0"},{"expression":"LRU trace","value":"misses=5; dirty evictions=1"}]),
            "methods": [
                {"method":"set_index_and_lru_state_trace", "result":"三块映射同一组；逐步更新最近使用顺序得到5次未命中，其中第一次淘汰块0时脏，之后淘汰均干净。"},
                {"method":"independent_reference_simulation", "result":"按2路LRU状态逐次模拟访问序列，缺失标志为[1,1,1,1,1]，写回标志为[0,0,1,0,0]。"}],
            "steps": ["由容量、块大小和路数求组数，并计算每个地址的块号与组号。", "逐次维护同组LRU队列及脏位，分别统计缺失和脏淘汰。"],
            "truth":{"A":False,"B":True,"C":False,"D":False},
            "reason":{"knowledge_depth":"把组索引冲突、LRU状态、写分配和脏块回写放在同一访问轨迹中分析。","reasoning_steps":"先算组号，再逐次更新两路状态和脏位，分别统计缺失与写回。","trap_design":"地址间隔易使人误判为不同组；还需区分干净淘汰与写回。","application_value":"训练Cache题从位字段计算扩展到实际访存轨迹和写回策略分析。"}},
        {
            "request": "z5b1-408-srtf-waiting-time",
            "node": "cs408.os.topic.bc235cd7a2fb", "answer": "C", "difficulty": "medium",
            "tags": ["抢占式调度", "最短剩余时间优先", "等待时间"],
            "output": Output(stem="采用抢占式SRTF，进程J1=(到达0,运行8)、J2=(到达2,运行3)、J3=(到达4,运行2)，同一时刻若剩余时间相同则选编号较小者。平均等待时间为（ ）。",
                question_type="single_choice", options={"A":"1","B":"5/3","C":"2","D":"7/3"},
                correct_answer="C", final_value="2",
                explanation="t=0至2运行J1，剩6；t=2起J2剩余3小于J1的6，运行至t=4。此时J2剩1，小于新到达J3的2，故J2运行至5；J3运行5至7；J1运行7至13。等待时间分别为J1:13−0−8=5，J2:5−2−3=0，J3:7−4−2=1，平均(5+0+1)/3=2。",
                steps=[{"expression":"schedule","value":"J1[0,2), J2[2,5), J3[5,7), J1[7,13)"},{"expression":"waiting=(completion-arrival-burst)","value":"5,0,1"},{"expression":"(5+0+1)/3","value":"2"}]),
            "methods": [
                {"method":"event_driven_srtf_timeline", "result":"按到达事件与剩余时间比较得到J1、J2、J3、J1四段运行区间，完成时刻13、5、7。"},
                {"method":"turnaround_minus_burst_check", "result":"周转时间13、3、3减运行时间8、3、2，等待时间5、0、1，平均2。"}],
            "steps": ["按每个到达时刻比较当前剩余时间，形成抢占时间线。", "由完成−到达−运行求各等待时间后取平均。"],
            "truth":{"A":False,"B":False,"C":True,"D":False},
            "reason":{"knowledge_depth":"需要在新进程到达时比较剩余时间并决定是否抢占，不能按非抢占SJF排序。","reasoning_steps":"构造事件驱动时间线，随后独立用周转时间公式复核等待时间。","trap_design":"J3到达时J2只剩1个时间单位，继续运行J2；忽略这一比较会改变时间线。","application_value":"训练抢占调度中的动态决策及等待时间、周转时间之间的区别。"}},
        {
            "request": "z5b1-408-dijkstra-multistep-path",
            "node": "cs408.ds.topic.a52e1bedea58", "answer": "B", "difficulty": "medium",
            "tags": ["Dijkstra", "松弛", "最短路径恢复"],
            "output": Output(stem="有向非负权图的边为S→A:4、S→B:1、B→A:2、A→C:2、B→C:6、C→D:1、A→D:9、B→D:10。Dijkstra从S出发，D的最短距离及一条对应路径为（ ）。",
                question_type="single_choice", options={"A":"7，S→A→C→D","B":"6，S→B→A→C→D","C":"8，S→B→C→D","D":"11，S→B→D"},
                correct_answer="B", final_value="6; S-B-A-C-D",
                explanation="初始化d(A)=4、d(B)=1。先确定B，松弛A得3；确定A后松弛C得5；确定C后松弛D得6。经S→A→C→D为7，经S→B→C→D为8，直达D为11，故唯一最短距离为6，路径S→B→A→C→D。",
                steps=[{"expression":"relax B->A","value":"d(A)=min(4,1+2)=3"},{"expression":"relax A->C","value":"d(C)=3+2=5"},{"expression":"relax C->D","value":"d(D)=5+1=6"}]),
            "methods": [
                {"method":"dijkstra_settlement_and_relaxation", "result":"确定顺序B(1)、A(3)、C(5)、D(6)，前驱链还原为S-B-A-C-D。"},
                {"method":"simple_path_cost_crosscheck", "result":"比较候选路径长度6、7、8、11，最小为6且路径唯一。"}],
            "steps": ["从S初始化边距并按当前最小暂定距离确定顶点。", "依次松弛B→A、A→C、C→D，并用其他主要路径复核。"],
            "truth":{"A":False,"B":True,"C":False,"D":False},
            "reason":{"knowledge_depth":"需要连续执行三次边松弛并保留前驱，而非只做一次路径长度相加。","reasoning_steps":"从源点初始化、按最小暂定距离确定顶点、更新距离并恢复路径。","trap_design":"直达边和较短的局部路径会误导；必须经过中间点更新已有距离。","application_value":"同时检验Dijkstra的贪心确定过程、松弛更新和最终路径恢复。"}},
        {
            "request": "z5b1-408-tcp-fast-retransmit-cumulative-ack",
            "node": "cs408.cn.topic.8679c379d738", "answer": "B", "difficulty": "advanced",
            "tags": ["TCP累计确认", "重复ACK", "快速重传"],
            "output": Output(stem="TCP接收方当前累计确认号为1000。发送方依次发出5个各1000字节的段，序号分别为1000、2000、3000、4000、5000；只有序号2000的段丢失，其余按序到达。假定接收方对每个失序段立即发送累计ACK，使用无SACK的Reno规则，发送方收到第三个重复ACK即快速重传。触发快速重传前重复ACK数，以及重传2000段后接收方的新累计ACK号为（ ）。",
                question_type="single_choice", options={"A":"2个，3000","B":"3个，6000","C":"3个，5000","D":"4个，6000"},
                correct_answer="B", final_value="3 duplicate ACKs; ACK=6000",
                explanation="段1000到达后累计ACK变为2000。序号3000、4000、5000三个段到达时，缺口2000仍未填补，接收方分别再发ACK=2000，累计产生3个重复ACK并触发快速重传。重传段2000到达后，1000至5999字节连续齐全，累计确认号前移至6000。",
                steps=[{"expression":"out-of-order segments after hole","value":"3000,4000,5000 -> 3 duplicate ACKs"},{"expression":"contiguous byte range after retransmission","value":"[1000,6000)"}]),
            "methods": [
                {"method":"receiver_cumulative_ack_state_trace", "result":"缺口仍在2000时，对后续三个失序段都重复确认2000；填洞后确认号跨过全部已缓存字节至6000。"},
                {"method":"byte_interval_union_check", "result":"重传后区间[1000,1999]、[2000,2999]、[3000,5999]连续并集为[1000,5999]，下一期待字节6000。"}],
            "steps": ["先按累计确认规则跟踪缺口前的下一期待字节及失序段产生的重复ACK。", "按Reno阈值确定触发次数，再合并重传后连续字节区间求最终ACK。"],
            "truth":{"A":False,"B":True,"C":False,"D":False},
            "reason":{"knowledge_depth":"把累计确认的字节边界、失序段重复ACK和Reno快速重传阈值组合起来。","reasoning_steps":"逐段跟踪接收端期待序号，再在缺口补齐后合并缓存区间。","trap_design":"重复ACK次数不等于丢失段数；ACK字段表示下一期待字节而不是最后收到的序号。","application_value":"训练TCP可靠传输状态推演，避免把段序号、字节序号和确认号混淆。"}},
        {
            "request": "z5b1-408-producer-consumer-semaphore-trace",
            "node": "cs408.os.topic.a28022393ec2", "answer": "A", "difficulty": "medium",
            "tags": ["生产者消费者", "信号量", "缓冲区状态"],
            "output": Output(stem="有界缓冲区容量4，初始empty=4、full=0、mutex=1。生产者按P(empty),P(mutex),写入,V(mutex),V(full)完成3次；消费者随后按P(full),P(mutex),取出,V(mutex),V(empty)完成2次。假定无阻塞且操作均成功，结束时(empty,full)为（ ）。",
                question_type="single_choice", options={"A":"(3,1)","B":"(2,2)","C":"(1,3)","D":"(4,0)"},
                correct_answer="A", final_value="(3,1)",
                explanation="每次成功生产使empty减1、full加1；三次后为(1,3)。每次成功消费使full减1、empty加1；两次后为(3,1)。mutex只控制互斥，不改变空槽和已存项目计数。",
                steps=[{"expression":"(empty,full) after 3 producers","value":"(1,3)"},{"expression":"after 2 consumers","value":"(3,1)"}]),
            "methods": [
                {"method":"semaphore_operation_state_machine", "result":"将P(empty)/V(full)及P(full)/V(empty)分别应用三次和两次，得到(3,1)。"},
                {"method":"occupancy_conservation", "result":"缓冲区净占用=3−2=1，故full=1、empty=4−1=3，且empty+full=4。"}],
            "steps": ["分别列出生产与消费对empty、full的增减，不把mutex算入缓冲计数。", "用净占用和容量守恒关系复核最终计数。"],
            "truth":{"A":True,"B":False,"C":False,"D":False},
            "reason":{"knowledge_depth":"需要区分互斥信号量与资源计数信号量，并跟踪两类操作的状态变化。","reasoning_steps":"先执行三次生产，再执行两次消费，并用容量守恒关系复核。","trap_design":"干扰项对应把full/empty方向颠倒、忽略净操作次数或把mutex误作槽数。","application_value":"把生产者消费者同步原语映射到可观察缓冲状态，支持后续并发流程分析。"}},
    ]


def run(db: Session, candidate_specs=None, batch_id: str = "01") -> dict:
    from backend.models.learning import (KpGraduationQuestionSetVersion, KpMasteryPolicy,
        KpState, KnowledgePoint, LearningEvent, Question, QuestionAttempt, QuestionAutoReviewEvent)
    from backend.services.question_generation import prepare_codex_public_original
    from backend.services.auto_question_review import (assess_auto_qualification,
        qualify_public_question, current_auto_review, question_snapshot_sha256)
    from backend.services.question_eligibility import question_eligibility
    from backend.services.graduation_question_set import publish_all_public_question_set_version

    identity = db.execute(text("SELECT current_database(), inet_server_port(), system_identifier FROM (SELECT current_database() current_database, inet_server_port() inet_server_port, system_identifier FROM pg_control_system()) s")).one()
    if identity.current_database != DB_NAME or identity.inet_server_port != PORT or str(identity.system_identifier) != SYSTEM_ID:
        raise ValueError("isolated_database_identity_mismatch")
    questions_before = db.query(Question).count()
    events_before = db.query(QuestionAutoReviewEvent).count()
    sets_before = db.query(KpGraduationQuestionSetVersion).count()
    protected_before = {"attempts": table_fingerprint(db, QuestionAttempt),
        "learning_events": table_fingerprint(db, LearningEvent), "kp_states": table_fingerprint(db, KpState)}
    rules_before = policy_rule_fingerprint(db)
    existing = list(db.scalars(select(Question).where(Question.bank_scope == "public",
        Question.generation_batch_id.is_(None))).all())
    changed_nodes = set()
    accepted, rejected = [], []

    for spec in (candidate_specs if candidate_specs is not None else specs()):
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == spec["node"]))
        if node is None or not node.is_active or not node.is_assessable or node.children:
            rejected.append({"request": spec["request"], "status": "BLOCKED_NODE"})
            continue
        savepoint = db.begin_nested()
        try:
            q = prepare_codex_public_original(spec["output"], node,
                request_id=spec["request"], derived_answer=spec["answer"],
                method_evidence=spec["methods"], explanation_key_steps=spec["steps"],
                option_truth_table=spec["truth"], difficulty=spec["difficulty"],
                skill_tags=spec["tags"], difficulty_reason=spec["reason"])
            if db.get(Question, q.id) is not None:
                raise ValueError("stable_question_id_already_exists")
            db.add(q)
            db.flush()
            live_rows = list(db.scalars(select(Question).where(Question.bank_scope == "public",
                Question.generation_batch_id.is_(None))).all())
            assessment = assess_auto_qualification(db, q, node, all_questions=live_rows)
            if assessment.get("status") != "AUTO_VERIFIED":
                stages = assessment.get("stages", {})
                failed = [key for key, value in stages.items() if value.get("status") != "PASS"]
                raise ValueError("quality_gate:" + ",".join(failed))
            event, qualification = qualify_public_question(db, question_id=q.id,
                node_id=node.id, expected_snapshot_sha256=question_snapshot_sha256(q),
            idempotency_key=f"phase45z5-original-batch{batch_id}:{spec['request']}:{question_snapshot_sha256(q)}")
            if event is None or qualification.get("status") != "AUTO_VERIFIED" or current_auto_review(q, node) is None:
                raise ValueError("public_auto_qualification_not_current")
            eligibility = question_eligibility(q, node)
            if not (eligibility.practice_eligible and eligibility.evidence_capability == "verified_objective"
                    and eligibility.grading_capability == "deterministic"):
                raise ValueError("formal_practice_or_evidence_eligibility_failed")
            savepoint.commit()
            accepted.append({"question_id": str(q.id), "request": spec["request"],
                "node_code": node.code, "subject": node.subject, "type": q.question_type,
                "difficulty": spec["difficulty"], "source": "development_original",
                "question_snapshot_sha256": question_snapshot_sha256(q),
                "answer_sha256": event.answer_sha256, "auto_review_event_id": str(event.id),
                "auto_review_version": event.review_version,
                "independent_methods": [item["method"] for item in spec["methods"]],
                "difficulty_reason_fields": sorted(spec["reason"]),
                "grader": eligibility.grading_capability, "public_exam_eligible": True,
                "model_calls": 0})
            changed_nodes.add(node.id)
        except Exception as exc:
            savepoint.rollback()
            rejected.append({"request": spec["request"], "status": "REJECTED_OR_BLOCKED",
                "reason": str(exc)[:300]})

    publications = []
    for kp_id in sorted(changed_nodes, key=str):
        node = db.get(KnowledgePoint, kp_id)
        policy = db.scalar(select(KpMasteryPolicy).where(KpMasteryPolicy.kp_id == kp_id).with_for_update())
        if policy is None or policy.policy_version != 3 or not policy.graduation_set_version:
            raise ValueError(f"v3_policy_or_current_set_missing:{node.code}")
        previous = db.get(KpGraduationQuestionSetVersion, (kp_id, policy.graduation_set_version))
        if previous is None:
            raise ValueError(f"current_set_version_missing:{node.code}")
        rows = list(db.scalars(select(Question).where(Question.kp_id == kp_id,
            Question.bank_scope == "public", Question.generation_batch_id.is_(None))))
        ids = [q.id for q in rows if (lambda e: e.practice_eligible and
            e.evidence_capability == "verified_objective" and e.grading_capability == "deterministic")(
                question_eligibility(q, node))]
        publication_key = f"phase45z5-original-batch{batch_id}:{node.code}"
        _, result = publish_all_public_question_set_version(db, kp_id=kp_id,
            question_ids=ids, expected_set_version=policy.graduation_set_version,
            expected_set_sha256=previous.question_ids_sha256,
            publication_key=publication_key,
            reason="Append the newly auto-verified development originals to the full current public set; preserve learner-pinned prior versions.")
        publications.append({"node_code": node.code,
            "old_version": result.get("old_set_version", policy.graduation_set_version),
            "new_version": result.get("set_version", policy.graduation_set_version),
            "members": len(ids), "status": result["status"],
            "learner_history_modified": result.get("learner_history_modified", False)})

    protected_after = {"attempts": table_fingerprint(db, QuestionAttempt),
        "learning_events": table_fingerprint(db, LearningEvent), "kp_states": table_fingerprint(db, KpState)}
    rules_after = policy_rule_fingerprint(db)
    if protected_before != protected_after or rules_before != rules_after:
        raise ValueError("learner_history_or_graduation_algorithm_changed")
    return {"database": {"name": DB_NAME, "port": PORT, "system_identifier": SYSTEM_ID},
        "before": {"question_rows": questions_before, "auto_review_events": events_before,
            "set_versions": sets_before, "policy_rule_fingerprint": rules_before,
            "protected_history": protected_before},
        "after": {"question_rows": db.query(Question).count(),
            "auto_review_events": db.query(QuestionAutoReviewEvent).count(),
            "set_versions": db.query(KpGraduationQuestionSetVersion).count(),
            "policy_rule_fingerprint": rules_after, "protected_history": protected_after},
        "accepted": accepted, "rejected": rejected, "publications": publications,
        "backup": {"path": BACKUP.relative_to(ROOT).as_posix(), "sha256": BACKUP_SHA256,
            "sha256_valid": sha_file(BACKUP) == BACKUP_SHA256},
        "live_development_db_accessed": False, "paid_model_calls": 0,
        "student_graduation_algorithm_changed": False, "history_rewritten": False}


def main() -> int:
    import argparse
    import subprocess
    from sqlalchemy import create_engine
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    args = parser.parse_args()
    output = OUT.with_name("preview.json") if args.mode == "dry-run" else OUT
    if output.exists():
        raise SystemExit(f"refusing_to_overwrite_existing_output:{output.name}")
    if not BACKUP.is_file() or sha_file(BACKUP) != BACKUP_SHA256:
        raise SystemExit("prebatch_backup_missing_or_hash_mismatch")
    pg_restore = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
    toc = subprocess.run([str(pg_restore), "--list", str(BACKUP)],
        capture_output=True, timeout=30)
    if toc.returncode or b"TABLE DATA public questions" not in toc.stdout:
        raise SystemExit("prebatch_backup_archive_invalid")
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres",
        host="127.0.0.1", port=PORT, database=DB_NAME), pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.begin()
            try:
                report = run(db)
                report["status"] = ("DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else
                    ("BATCH01_APPLIED" if report["accepted"] else "BATCH01_NO_QUALIFIED_ITEMS"))
                if not report["backup"]["sha256_valid"]:
                    raise ValueError("backup_changed_during_batch")
                if args.mode == "dry-run":
                    db.rollback()
                else:
                    db.commit()
            except Exception:
                db.rollback()
                raise
        report["backup"]["toc_entries"] = len(toc.stdout.splitlines())
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        print(json.dumps({"status": report["status"], "accepted": len(report["accepted"]),
            "rejected": len(report["rejected"]), "publications": report["publications"],
            "checkpoint": output.relative_to(ROOT).as_posix()}, ensure_ascii=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
