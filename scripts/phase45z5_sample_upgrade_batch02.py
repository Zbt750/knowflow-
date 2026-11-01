"""Second content-upgrade batch, using the existing protected revision runner."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from scripts import phase45z5_sample_upgrade_batch01 as runner
from scripts.phase45z5_original_batch02 import item
OUT=ROOT/'storage/quality-audits/phase45z5-20261013/sample-upgrades/batch02'
BACKUP=ROOT/'storage/quality-audits/phase45z5-20261013/sample-upgrades/batch01/post-upgrade.dump'
SHA='F515C8173B2888F6FBD7675BEA9F8E3DFF014E80013D4CD16BBA143BEB44D011'

def row(qid,node,answer,stem,options,explanation,methods,steps,reason,tags):
    truth={x:x==answer for x in options}
    data=item('z5-sample02-'+qid,node,answer,stem,options,explanation,methods,steps,truth,reason,tags)
    return {'id':qid,**data}

def specs():
    return [
        row('641ab11f-c3ab-55f0-8e1d-577ccd3ff7d8','math.exam.e90535214807','D',
            '是否存在实数a使lim(x→0)(e^(ax)−1−x)/x²=2？（ ）',
            {'A':'a=1','B':'a=2','C':'a=−2','D':'不存在这样的实数a'},
            '展开分子为(a−1)x+a²x²/2+o(x²)。要有有限两侧极限，必须a=1，此时极限为1/2而非2。因此有限性条件与目标值条件不相容，不存在所求a。只由a²/2=2解a=±2会留下发散的一阶项。',
            [('finite_limit_and_coefficient','有限极限先强制a=1，再由二阶项算得1/2，目标2不相容。'),('one_sided_divergence_check','a≠1时商含(a−1)/x，正负侧发散方向不同，不可能得到有限两侧极限。')],
            [('first_order','低阶项除以x²产生(a−1)/x，有限性迫使a=1。'),('target_conflict','代入a=1后独立展开得到极限1/2，与目标2矛盾。')],
            ('需要同时审查极限存在条件与目标值方程是否相容，不能仅解最终系数。','先消除会发散的一阶项，再计算剩余二阶项并检验目标条件。','由二次系数求出±2忽略分子一阶项，导致把发散候选误认为解。','训练参数极限中条件先后关系与不存在性论证。'),['参数极限','条件相容性','Taylor展开']),
        row('4b40c3b3-f74f-5bf5-a612-e98dd57d76ff','cs408.co.topic.ba9896acc602','B',
            '比较两个Cache：数据区均64B、块16B，一个直接映射，另一个2路组相联LRU；均初始为空，只读访问字节地址0、64、0、64、128、0、64。两者未命中次数分别为（ ）。',
            {'A':'7，7','B':'7，5','C':'5，3','D':'4，3'},
            '块号为0、4、0、4、8、0、4。直接映射有4行，三块都映射第0行，每次访问均替换前块，7次全未命中。2路组相联有2组，三块同在第0组；前两次未命中后，下一次0和4命中；访问8淘汰LRU的0，再访问0淘汰4，再访问4淘汰8，共5次未命中。',
            [('mapping_and_lru_trace','块号0、4、8在直接映射同一行，在2路结构同一组；跟踪两路LRU得M M H H M M M。'),('independent_cache_simulation','分别用一槽替换和容量2的LRU队列模拟相同块序列，缺失总数为7和5。')],
            [('mapping','容量64B除以16B得4行；2路有2组，三个块均冲突在索引0。'),('trace','2路第3、4次访问命中，之后三个访问均缺失，合计5；直接映射合计7。')],
            ('把容量、块号映射和LRU状态联合用于两种结构的性能比较。','先计算映射位置，再分别跟踪每次命中、缺失及最近使用次序。','组相联并未消除所有冲突，第三个同组块加入后仍可能连续抖动。','训练区分直接映射冲突和有限路数下的LRU替换效应。'),['Cache映射','LRU','冲突缺失']),
        row('37a7a050-0951-50c4-882e-0e40eb754ac6','math.calculus.limit.infinitesimal','C',
            'lim(x→0)(tan x−sin x)/[x(1−cos x)]为（ ）。',
            {'A':'0','B':'1/2','C':'1','D':'2'},
            '先用恒等式tan x−sin x=sin x(1−cos x)/cos x。在足够小且非零的x上可约去1−cos x，商变成sin x/(x cos x)，极限为1。独立展开也可见分子为x³/2+o(x³)，分母为x³/2+o(x³)。直接在差式中把tan x和sin x都替换为x会丢失主项。',
            [('identity_before_equivalence','先因式分解差式并约去相同因子，得到sin x/(x cos x)趋于1。'),('third_order_taylor','tan与sin的三阶系数差为1/3+1/6=1/2，分母三阶系数也为1/2。')],
            [('cancellation','差式恒等变形使公共因子1−cos x可在穿孔邻域约去。'),('crosscheck','三阶展开确认分子分母同为x³/2主项，极限为1。')],
            ('需要识别等价替换在减法抵消中的限制，并选用恒等变形保留有效阶次。','先化差为乘积，约去公共因子后应用标准极限，再用三阶展开校核。','分别将tan和sin换成x会错误地产生零分子并丢失三阶项。','训练极限计算的方法选择和减法中等价无穷小的适用条件。'),['等价无穷小','三角恒等式','阶次抵消']),
        row('26bc66b6-50b7-5275-a894-585f73004e54','cs408.co.topic.497f9a53d9d0','A',
            '同步总线时钟100MHz、数据线64位，一次突发读16个字。该次事务地址阶段2周期，首个数据字等待及传送4周期，余下15个字各1周期，事务末端转向1周期；阶段不重叠。总周期数和有效数据带宽约为（ ）。',
            {'A':'22周期，581.8MB/s','B':'21周期，609.5MB/s','C':'18周期，711.1MB/s','D':'22周期，800MB/s'},
            '事务周期为2+4+15+1=22。100MHz的周期是10ns，耗时220ns；16个64位字共128B，因此有效带宽128/(220×10^(−9))约581.8MB/s。800MB/s为每周期一个64位字且没有事务开销的峰值，不能用于该事务。',
            [('bus_phase_accounting','按题设不重叠阶段累加2+4+15+1=22周期，每周期10ns得220ns。'),('payload_per_transaction','有效载荷16×8=128B，除以220ns得约581.8MB/s，低于800MB/s峰值。')],
            [('cycles','地址、首字、后续数据、转向四段全部计入，合计22周期。'),('throughput','有效载荷128B除以事务时长220ns，得到581.8MB/s。')],
            ('同时计算同步总线阶段时序与突发传输的有效带宽，区分峰值和实际事务值。','先按时钟周期建立完整事务时间，再将有效载荷字节数除以该时间。','漏掉地址或转向周期会高估带宽；余下字数为15而非16。','训练总线定时约定、突发首字开销及性能计算的联合分析。'),['同步总线','突发传输','有效带宽']),
        row('9f4738e4-ec50-5a91-b295-2fbce43982e7','math.exam.f99711e0ea65','D',
            'P为4阶循环置换矩阵，P e₁=e₂、P e₂=e₃、P e₃=e₄、P e₄=e₁。令S=I+P+P²+P³，则(rank S, rank(I−P))为（ ）。',
            {'A':'(4,3)','B':'(1,4)','C':'(3,1)','D':'(1,3)'},
            '任一基向量经I、P、P²、P³遍历全部四个基向量，因此S的每列都是全1向量，rank S=1。方程(I−P)x=0要求四个坐标相等，核是一维常向量空间，由秩零化度公式rank(I−P)=4−1=3。等式(I−P)S=I−P⁴=0可核对像空间包含在核中。',
            [('orbit_sum_matrix','每个基向量完整循环一次，S每列均为全1，因此S非零且秩1。'),('fixed_vector_nullspace','Px=x要求四坐标相同，核维数1，因此I−P秩3。')],
            [('sum_rank','逐列计算轨道和均为(1,1,1,1)，矩阵秩为1。'),('kernel_rank','固定向量空间一维，并用(I−P)S=0交叉验证，秩为3。')],
            ('把循环置换的轨道、矩阵多项式和固定向量空间联系起来求两个秩。','先求S对基向量的像，再解Px=x并应用秩零化度公式。','P可逆不意味着I−P或轨道和可逆；不能把四个置换矩阵秩直接相加。','训练置换矩阵的结构推理及矩阵多项式的像核关系。'),['循环置换','矩阵秩','固定向量空间']),
        row('6a5b92a7-5b44-5821-9655-4ae151fdd709','cs408.co.topic.a1e3b44f8513','B',
            '设备状态字为8位，bit7为BUSY、bit6为ERROR、bit0为READY，其他位忽略。CPU只有在BUSY=0、ERROR=0、READY=1时才能读数据。状态依次为81H、41H、01H。正确的允许读取测试与首次可读状态序号为（ ）。',
            {'A':'(s & 01H)!=0；第1个','B':'(s & C1H)==01H；第3个','C':'(s & C1H)==C1H；第3个','D':'(s & 80H)==0；第2个'},
            '三个位的掩码为80H+40H+01H=C1H，允许状态的目标模式只有READY置1，即01H。81H带BUSY，41H带ERROR，均不能读；01H满足三个条件，因此第三个状态首次可读。仅测READY会忽略忙与错误，仅测BUSY会忽略错误和未就绪。',
            [('bitmask_boolean_conditions','三个条件对应掩码C1H与目标位图01H，必须同时匹配所有关心位。'),('status_sequence_evaluation','81H掩码结果81H，41H结果41H，01H结果01H，仅第三项满足比较。')],
            [('mask','位7、6、0组合掩码C1H，目标只有bit0为1。'),('sequence','逐次代入掩码等式，前两次分别因BUSY与ERROR被拒绝，第三次允许。')],
            ('需要将控制器多个状态条件转化为位掩码测试，并跟踪轮询中首次合法读时机。','先构造关心位掩码及目标模式，再逐状态检验所有条件。','只检查READY会在BUSY或ERROR同时置位时错误读设备数据。','训练设备控制器状态寄存器的位级解释与安全操作顺序。'),['设备控制器','状态寄存器','位掩码']),
        row('ebc59251-d756-515e-9aee-0f91e598f8e3','math.exam.90bbbeb58b4a','C',
            '4阶矩阵N满足N³=0、N²≠0且rank N=2。则(I+N)的逆及dim ker N分别为（ ）。',
            {'A':'I−N；2','B':'I−N+N²；1','C':'I−N+N²；2','D':'I+N+N²；2'},
            '有限几何乘积(I+N)(I−N+N²)=I+N³=I，反向乘积相同，因此逆为I−N+N²。因N²≠0，不能省掉N²项。4维空间中rank N=2，秩零化度公式给dim ker N=4−2=2。',
            [('nilpotent_polynomial_inverse','直接乘开得到I+N³=I，利用N³=0验证左右逆。'),('rank_nullity_dimension','矩阵作用在R⁴，rank N为2，核维数4−2=2；N²不为0排除截短逆式。')],
            [('inverse','乘积验证I−N+N²是左右逆，二次项因N²≠0必须保留。'),('nullity','由4阶及rank2得到核维数2，与逆矩阵存在性独立。')],
            ('结合幂零阶次控制矩阵多项式求逆与秩零化度公式，而非仅套N²=0的特例。','用多项式相乘检查逆，再由矩阵阶数和秩计算核维数。','把N²=0特例的I−N照搬过来会漏掉非零二次项。','训练幂零条件、可逆矩阵构造和向量空间维数的联合判断。'),['幂零矩阵','有限几何多项式','秩零化度']),
        row('6dca1f10-4a92-511a-bcb5-1929c3998728','math.exam.b481011b3a32','A',
            '求lim(n→∞)(1/n²)Σᵢ₌₁ⁿΣⱼ₌₁ⁿ[(i/n−j/n)²+(i/n)³−(j/n)³]。（ ）',
            {'A':'1/6','B':'1/3','C':'1/2','D':'0'},
            '双重求和区域对i、j对称，三次差项逐对抵消为0。剩余部分为单位正方形上(x−y)²的二维黎曼和。积分展开x²−2xy+y²，分别积分得到1/3−2×1/4+1/3=1/6。独立用整数求和公式得到ΣΣ(i−j)²=n²(n²−1)/6，除n⁴也趋于1/6。',
            [('symmetry_and_double_riemann_sum','反对称三次差在正方形求和域抵消，剩余黎曼和趋于∬(x−y)²=1/6。'),('finite_sum_identity','利用Σi与Σi²公式，双和(i−j)²等于n²(n²−1)/6，规范化后极限1/6。')],
            [('odd_swap_cancel','交换i,j后三次差变号，整个双和该部分恰为0。'),('remaining_integral','平方差积分为1/3−1/2+1/3=1/6，并以有限和恒等式复核。')],
            ('需识别双重求和的交换对称性，并将剩余项正确缩放为二维黎曼和。','先消去反对称项，再展开积分并用整数求和恒等式作第二种验证。','尺度是n⁴对应(i−j)²的双和，漏掉双重权重会使极限错误。','训练对称性消项、二维黎曼和及有限求和公式的结合。'),['双重黎曼和','交换对称性','二重积分']),
    ]

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    output=OUT/('checkpoint.json' if args.apply else 'preview.json')
    if output.exists():raise SystemExit('refusing_existing_output')
    if hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper()!=SHA:raise SystemExit('backup_hash_mismatch')
    runner.OUT=OUT;runner.specs=specs
    engine=create_engine('postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test')
    try:
        with Session(engine,expire_on_commit=False) as db:
            report=runner.run(db,args.apply)
            db.commit() if args.apply else db.rollback()
        OUT.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'status':report['status'],'upgraded':len(report['results'])}))
    finally:engine.dispose()
