"""Batch 14: multi-step calculus, algorithms and computer performance."""
from __future__ import annotations
import argparse,json,subprocess,sys,math
from fractions import Fraction
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import phase45z5_original_batch01 as runner
from scripts.phase45z5_original_batch13 import S as prior_s
BACKUP=ROOT/'storage/quality-audits/phase45z5-20261013/originals/batch13/post-batch.dump'
BACKUP_SHA256='B98E03B15E3955A7D0DA18620E5A3D44143C83F3D6CF9D9F3994E0F22ABE5BF5'
OUT_DIR=ROOT/'storage/quality-audits/phase45z5-20261013/originals/batch14'
DB_NAME,PORT,SYSTEM_ID=runner.DB_NAME,runner.PORT,runner.SYSTEM_ID
def S(*args):
    spec=prior_s(*args);spec['request']=spec['request'].replace('z5b13-','z5b14-',1);return spec
def candidates():
 return [
  S('arctan-fifth-order-cancellation','math.exam.a24681a8ee59','C',
    '极限lim(x→0)[arctan x−x+x³/3]/x⁵为（ ）。',
    {'A':'−1/5','B':'0','C':'1/5','D':'1/3'},
    'arctan x=x−x³/3+x⁵/5+o(x⁵)，前两项在分子中被精确消去，首个剩余项为x⁵/5，极限1/5。也可将分子记N，N′=x⁴/(1+x²)，一次洛必达即得N′/(5x⁴)=1/[5(1+x²)]→1/5。',
    '用五阶Taylor展开识别两轮消去后的首个非零项，并检查分母同阶。',
    '独立求分子导数化简为x⁴/(1+x²)，用一次洛必达得到同一极限。',
    '需要处理多个低阶项消去，并选择足够展开阶数或有效求导方法。',
    '只使用arctan x等价于x会把所有剩余高阶信息丢失，不能据此判极限为零。',
    ['反三角函数与泰勒展开','高阶消去','洛必达法则']),
  S('logistic-initial-value','math.exam.b05d65f2b0c1','A',
    '初值问题y′=y(1−y)，y(0)=1/3的解满足y(ln2)及x→+∞时的极限分别为（ ）。',
    {'A':'1/2，1','B':'2/3，0','C':'1/2，0','D':'2/3，1'},
    '初值在(0,1)，分离变量得ln[y/(1−y)]=x+C；由初值C=−ln2，故y=1/(1+2e^(−x))。代入ln2得1/2，向正无穷时趋于1。解保持在(0,1)，未在分离过程中遗漏该初值对应的非平衡解。',
    '对1/[y(1−y)]部分分式积分，利用初值确定常数并求出显式解。',
    '直接微分显式解核对微分方程，再代入指定点并计算长期极限。',
    '需要识别可分离方程、处理部分分式并结合初值分析非平衡解。',
    '分离变量时需区分平衡解与初值解；正向极限不能误认为初始值或零。',
    ['可分离变量的微分方程','初值条件','长期行为']),
  S('disk-odd-even-integral','math.exam.b481011b3a32','B',
    'D={(x,y):x²+y²≤1}，二重积分∬D(x³+y³+x²+y²)dA为（ ）。',
    {'A':'0','B':'π/2','C':'π','D':'π/4'},
    '单位圆盘关于两轴对称，x³和y³分别为奇函数，其积分为0。剩下x²+y²=r²，用极坐标并计Jacobian r，积分为∫₀^{2π}∫₀¹r³drdθ=2π/4=π/2。也可将圆盘分成同心薄环，环面积2πrdr得到同一结果。',
    '先以对称性消去奇项，再用极坐标及Jacobian计算径向平方项。',
    '用同心薄环的面积2πrdr乘半径平方r²，独立建立一维径向积分。',
    '需要辨别积分区域对称性和奇偶项，并正确转换面积微元。',
    '不能因含有奇函数就把整个积分归零；极坐标积分也不能漏掉Jacobian中的r。',
    ['二重积分的对称性与黎曼和','极坐标','奇偶分解']),
  S('ellipse-curvature-at-vertex','math.exam.f67ee0d0080c','D',
    '椭圆x²/4+y²=1在上顶点(0,1)附近写为y=y(x)。该点的曲率半径为（ ）。',
    {'A':'1/4','B':'1','C':'2','D':'4'},
    '隐式一阶关系x/2+2yy′=0给y′(0)=0。二阶关系1/2+2(y′)²+2yy″=0给y″(0)=−1/4。曲率κ=|y″|/[1+(y′)²]^(3/2)=1/4，半径ρ=1/κ=4。用显式上半支√(1−x²/4)的导数可交叉核对。',
    '以隐函数关系求两阶导数，再使用曲率公式并取其倒数得到半径。',
    '直接微分上半支y=√(1−x²/4)，代入顶点再次得到y′=0、y″=−1/4。',
    '需要结合曲线局部导数、曲率的绝对值和曲率半径的倒数关系。',
    'y″为负表示弯曲方向，不表示负曲率半径；曲率和曲率半径不可互换。',
    ['隐函数曲线曲率与曲率半径','二阶导数','几何量']),
  S('moving-both-integral-limits','math.exam.eac5b4d10863','C',
    'F(x)=∫_{sin x}^{x²}e^{t²}dt。F′(0)、F″(0)分别为（ ）。',
    {'A':'1，2','B':'−1，0','C':'−1，2','D':'0，2'},
    'Leibniz法则给F′=2x e^{x⁴}−cos x·e^{sin²x}，所以F′(0)=−1。再求导，首项在0的导数为2，第二项在0的导数为0，故F″(0)=2。也可局部展开原函数积分，得F(x)=−x+x²+O(x³)。',
    '同时处理上下限的链式因子，计算一阶导数后继续求导并代入零点。',
    '以e^{t²}=1+t²+O(t⁴)积分并代入两个小上限，局部展开复核前两阶系数。',
    '需要将两个可变积分端点的符号和链式导数纳入一阶、二阶计算。',
    '下限贡献带负号；上限x²在零点一阶贡献为零，但二阶贡献仍存在。',
    ['变限积分','Leibniz法则','二阶局部展开']),
  S('resonant-second-order-initial','math.exam.d59b003eda7d','B',
    'y″−2y′+y=eˣ，y(0)=0、y′(0)=0。y(1)为（ ）。',
    {'A':'e','B':'e/2','C':'1/2','D':'0'},
    '令y=eˣv，则左端为eˣv″，方程化成v″=1。两项初值分别给v(0)=0、v′(0)=0，所以v=x²/2，y=x²eˣ/2，y(1)=e/2。由于齐次特征根1为二重根，不能仅设特解Ceˣ。',
    '以指数代换消除重复特征根，把非齐次问题化为二次积分并使用两项初值。',
    '直接微分x²eˣ/2，代回原方程和初值检验，并核对共振特解的x²因子。',
    '需要处理二重特征根共振，并分清特解形式与初值确定的完整解。',
    '右端eˣ已属于齐次解空间，未乘足够的x幂会令试探特解被算子消去。',
    ['特解与对应齐次方程通解','共振','初值问题']),
  S('external-merge-pass-io','cs408.ds.topic.9de322fe9c8d','A',
    '文件1000个磁盘块，缓冲区11块；初始归并段用内存11块逐批排序，之后每次10路归并（10块输入、1块输出）。各阶段都完整读写文件，忽略开销。初始段数、归并趟数及累计块I/O为（ ）。',
    {'A':'91，2，6000','B':'100，2，4000','C':'91，1，4000','D':'91，3，8000'},
    '初始段数ceil(1000/11)=91。10路归并一趟后ceil(91/10)=10段，第二趟剩1段，所以归并2趟。含初始生成共3次完整读写，每次2×1000块，累计6000块I/O。',
    '逐阶段按缓冲区容量和归并路数向上取整，得到91→10→1的段数变化。',
    '分别累加初始生成和两趟归并的完整读写成本，各2000块得到6000。',
    '需要综合初始段长度、输入输出缓冲分配和逐趟磁盘读写成本。',
    '11块缓冲不表示11路归并，输出必须占1块；初始生成成本不能遗漏。',
    ['外部排序','多路归并','块I/O']),
  S('matrix-storage-two-orders','cs408.ds.topic.9554f672c611','D',
    '数组A[−1..2][2..6]每元素8 B，A[−1][2]地址为1000。分别采用行优先和列优先存储时，A[1][5]的地址为（ ）。',
    {'A':'1080，1112','B':'1104，1104','C':'1112，1104','D':'1104，1112'},
    '数组4行5列。行优先偏移为[(1−(−1))×5+(5−2)]×8=104，地址1104。列优先偏移为[(5−2)×4+(1−(−1))]×8=112，地址1112。必须先扣除非零下标界。',
    '按行列尺寸和各自下标下界建立两个线性化索引，再乘元素宽度。',
    '实际枚举行优先与列优先元素次序，目标分别是零基第13和第14项。',
    '需要处理非零甚至负下标边界，区分两种二维数组线性化规则。',
    '列优先乘行数而非列数；直接使用原下标会把偏移和地址均算错。',
    ['多维数组存储','行列优先','下标归一化']),
  S('symmetric-packed-address','cs408.ds.topic.1b4089986d5e','B',
    '5阶对称矩阵仅存下三角（含主对角），按行优先紧凑存储，每元素4 B，a₁₁地址2000。a₂₄的地址及总存储字节数为（ ）。',
    {'A':'2024，100 B','B':'2028，60 B','C':'2028，100 B','D':'2032，60 B'},
    '对称性给a₂₄=a₄₂。第4行前有1+2+3=6项，行内a₄₂是零基偏移1，所以总体索引7，地址2000+7×4=2028。下三角含5×6/2=15项，共60 B。',
    '先利用对称性转为下三角坐标，再累加前面各行长度计算地址。',
    '枚举紧凑坐标序列确认a₄₂位于第8项，并以三角数核对总体空间。',
    '需要联用对称坐标替换、变长行存储和字节地址计算三个步骤。',
    '上三角元素没有单独副本，必须访问对称位置；索引零基与矩阵一基需区分。',
    ['特殊矩阵压缩存储','对称矩阵','地址计算']),
  S('deque-two-end-operation-trace','cs408.ds.topic.48e8e73d9928','C',
    '空双端队列依次执行尾入1、尾入2、头入3、尾出、尾入4、头出、头入5。两个出队值及最终从头到尾序列为（ ）。',
    {'A':'2、1；[5,3,4]','B':'1、3；[5,2,4]','C':'2、3；[5,1,4]','D':'3、2；[5,1,4]'},
    '前三步队列[3,1,2]，尾出得到2，余[3,1]；尾入4变[3,1,4]，头出得到3，余[1,4]；头入5变[5,1,4]。双端操作不能按单一栈或普通FIFO队列替代。',
    '逐操作跟踪头端和尾端的增删，记录每次实际移除的元素及剩余顺序。',
    '用独立双端队列参考实现重放七个操作，得到出队2、3和末态[5,1,4]。',
    '需要同时维护双端入出位置并跟踪操作间的状态，而非套用单一顺序规则。',
    '头入会改变下一头出元素，尾出也不等于删除最近一次头入的元素。',
    ['双端队列','操作推演','队列状态']),
  S('circular-doubly-linked-delete','cs408.ds.topic.6eeda8ef4b0f','A',
    '带哨兵h的循环双链表当前只有一个数据结点p，h.next=h.prev=p，p.next=p.prev=h。按通用删除执行p.prev.next=p.next与p.next.prev=p.prev（释放p前）。删除后的状态及两行能否用于一般非哨兵结点为（ ）。',
    {'A':'h.next=h.prev=h；两行也适用于一般非哨兵结点','B':'h.next=NULL、h.prev=h；只能删除尾结点','C':'h.next=h.prev=p；还须遍历全表','D':'h.next=h.prev=NULL；只能删除首结点'},
    '第一行把h.next设为h，第二行把h.prev设为h，恢复空循环表。一般结点p两侧若为L、R，两行分别让L.next=R和R.prev=L，完成双向绕过p；哨兵保证首尾邻接也可统一处理。',
    '把仅一个数据结点时的前驱后继都代为哨兵，逐条求值两次链接更新。',
    '以一般前驱L、后继R的双向一致性核对通用删除规则及空表不变量。',
    '需要分析哨兵循环结构的边界情况，同时保持前向和后向链接一致。',
    '循环哨兵空表指向自己而非NULL，删除数据结点时不能释放哨兵或遗漏反向链接。',
    ['双链表','循环哨兵','边界删除']),
  S('shell-gap-pass-state','cs408.ds.topic.1408569fd510','D',
    '序列[9,8,7,6,5,4,3,2,1]执行一次增量3的希尔排序（各同余子序列直接插入排序）。本趟结束状态及能否据此认为全表已排序为（ ）。',
    {'A':'[1,2,3,4,5,6,7,8,9]；已全局有序','B':'[3,6,9,2,5,8,1,4,7]；已全局有序','C':'[3,2,1,6,5,4,9,8,7]；已全局有序','D':'[3,2,1,6,5,4,9,8,7]；仅各增量子序列有序'},
    '下标模3分组为[9,6,3]、[8,5,2]、[7,4,1]，各组升序后按原间隔放回，得[3,2,1,6,5,4,9,8,7]。相邻元素仍存在逆序，故本趟只保证3-有序，仍须后续更小增量。',
    '按下标模3拆分、分别排序并回填，检验相邻元素是否已满足全局顺序。',
    '直接执行增量3插入排序循环，得到同一末态；再测试所有相邻比较发现逆序。',
    '需要区分间隔子序列的有序性和全局排序目标，并重构回填后的表。',
    '不能把各子序列连续拼接，也不能因每组有序就断言整个序列已全局有序。',
    ['希尔排序','增量子序列','局部与全局有序']),
  S('stable-lsd-second-pass','cs408.ds.topic.b901c6e9e751','B',
    '对[329,457,657,839,436,720,355]进行十进制稳定LSD基数排序，先个位再十位。在十位趟结束后，序列为（ ）。',
    {'A':'[329,355,436,457,657,720,839]','B':'[720,329,436,839,355,457,657]','C':'[720,329,839,436,355,657,457]','D':'[329,720,436,839,457,657,355]'},
    '个位稳定分配收集后为[720,355,436,457,657,329,839]。按十位稳定分桶依次为2:[720,329]、3:[436,839]、5:[355,457,657]，故第二趟得到B。稳定性使同十位的元素保留已完成的个位顺序。',
    '先重放个位分桶，再从当前顺序执行稳定十位分桶，逐桶收集得到结果。',
    '对原序列按低两位数值稳定排序，等价结果为720,329,436,839,355,457,657。',
    '需要保留每一趟的已有次序，并解释稳定性如何累积低位排序结果。',
    '第二趟不能重新从原序列开始，也不能把完整数值最终排序当作中间状态。',
    ['基数排序','稳定分配','中间状态']),
  S('insertion-comparison-shift-cost','cs408.ds.topic.60bf2405e5c6','C',
    '直接插入排序处理[5,2,4,6,1,3]。内循环仅将a[j]>key计为关键字比较（j≥0检查不计），每次a[j+1]=a[j]计一次元素右移，key最终写回不计右移。关键字比较和右移总次数为（ ）。',
    {'A':'9，9','B':'12，12','C':'12，9','D':'15，9'},
    '五趟右移分别1、1、0、4、3，合计9，等于原序列逆序对数。关键字比较分别1、2、1、4、4，合计12；非首位结束的插入还会进行一次不成立的关键字比较。j退到−1时不再比较关键字。',
    '逐趟执行内循环，区分成功导致右移的比较与使循环停止的失败比较。',
    '程序计数核对12次比较和9次右移；独立枚举原数组逆序对再次得到9。',
    '需要依据精确定义统计比较和数据移动，处理循环停止时的边界差异。',
    '逆序对数等于右移次数但不必等于比较次数，不能将两种成本直接合并。',
    ['直接插入排序','逆序对','操作计数']),
  S('bfs-parent-shortest-path','cs408.ds.topic.525fc6e99b95','A',
    '无向图边为12、13、24、34、35、46、56。从1开始BFS，按邻点编号升序扫描，发现时立即标记并记录首个前驱。到6的前驱链路径及最短边数为（ ）。',
    {'A':'1→2→4→6，3','B':'1→3→5→6，2','C':'1→3→4→6，4','D':'1→2→4→3→5→6，5'},
    '先发现2、3，处理2时发现4；处理3时4已标记，另发现5；随后处理4先发现6，故前驱为6←4←2←1。距离按层递增，6位于第3层。1→3→5→6同为三边短路，但题干的首次前驱约定选择A。',
    '按FIFO队列和升序邻点顺序重放发现事件，得到前驱链和距离层数。',
    '独立枚举1到6的简单路径，最短边数3；用发现顺序确认所记录的是经2、4的路径。',
    '需要区分最短路径不唯一与算法记录的唯一前驱链，并追踪队列层序。',
    '即使另一条路径也最短，不能忽略题干指定的邻点次序和首次发现规则。',
    ['广度优先搜索','最短边数','前驱树']),
  S('adjacency-list-directed-indegrees','cs408.ds.topic.0eb5ea0549e9','D',
    '有向图邻接表A:[B,C]，B:[C]，C:[A,D]，D:[B]。删除弧C→D后，顶点D入度、C出度及全图边结点总数分别为（ ）。',
    {'A':'1、1、6','B':'0、2、5','C':'1、2、5','D':'0、1、5'},
    '有向邻接表每条弧在弧尾链中保存一次，原总数2+1+2+1=6。删除C→D后D不再有入弧，所以入度0；C仍有C→A，出度1；全图边结点数5。D→B为出弧，不能计入D入度。',
    '根据邻接表逐弧枚举，删除指定弧后分别统计弧头、弧尾和全图记录数。',
    '用独立边集合表示删除操作，核对D的入边空集、C的出边{A}和剩余5条弧。',
    '需要将邻接链方向、度数定义和结构更新后的全局记录数结合分析。',
    '有向邻接表不是每条弧存两次；顶点自己的链表长度是出度而不是入度。',
    ['邻接表','有向度数','删弧更新']),
  S('amdahl-fixed-parallel-overhead','cs408.co.topic.b084a43130bd','B',
    '程序在单处理器执行时间归一为1，20%不可并行、80%可理想分到p个处理器；当p>1时额外并行管理开销固定为原单机时间的5%。8处理器加速比及p→∞的极限加速比为（ ）。',
    {'A':'10/3，5','B':'20/7，4','C':'8，4','D':'20/7，5'},
    'p>1时T(p)=0.2+0.8/p+0.05。p=8得T=0.35，加速比1/0.35=20/7。p→∞仍保留串行0.2与固定开销0.05，因此极限为1/0.25=4。不可把管理开销分摊为0.05/p。',
    '分别建串行、并行和固定开销项的时间模型，代入8并求极限。',
    '用精确有理数算T8=7/20与T∞=1/4，再取倒数核对两种加速比。',
    '需要将Amdahl模型和固定管理开销同时纳入，分析有限与无限处理器情形。',
    '固定开销不会随处理器数增加自动消失；仅用串行比例估算极限会偏高。',
    ['多处理器基本概念','Amdahl定律','管理开销']),
  S('bus-burst-versus-separate-cycles','cs408.co.topic.497f9a53d9d0','C',
    '同步总线100 MHz、32 bit数据宽度。一次传输建立阶段3周期，之后每周期传一个32 bit字。连续8字可作为一个突发，或作8次独立传输。两种总时间分别为（ ）。',
    {'A':'80 ns，320 ns','B':'110 ns，110 ns','C':'110 ns，320 ns','D':'320 ns，110 ns'},
    '总线周期10 ns。突发只建立一次，3+8=11周期，共110 ns；8次独立传输每次3+1=4周期，总32周期320 ns。两种都传32 B，节省来自建立开销的复用而非数据宽度改变。',
    '分别计算一次建立加八个数据周期与八次建立加八个数据周期的总周期。',
    '把8次独立事务逐项列成4周期并相加，再用100MHz换算周期时长10ns。',
    '需要区分突发数据周期和事务建立开销，比较同等数据量下的总线效率。',
    '突发不能把建立开销完全省去，独立传输也不能只算一次建立过程。',
    ['总线定时','突发传输','建立开销']),
  S('polling-ready-transfer-cpu-budget','cs408.co.topic.bfd3c1878167','A',
    '设备持续以1 MB/s提供数据，每次就绪传输4 B。CPU为100 MHz；采用一次就绪对应一次查询及搬运的安排，每次共80周期，无空查询且无其他开销。查询搬运消耗的CPU时间比例为（ ）。',
    {'A':'20%','B':'80%','C':'8%','D':'2%'},
    '每秒传输次数10⁶/4=250000，CPU周期开销250000×80=2×10⁷周期/s，占CPU总10⁸周期/s的20%。题设排除空查询；实际忙等若存在额外失败查询，负担可能更高。',
    '按设备数据量除单次字节数求频率，再乘每次处理周期并除CPU频率。',
    '等价地每4μs到来4B，服务占80/100MHz=0.8μs，时间比0.8/4=20%。',
    '需要把字节吞吐、每次搬运单位和CPU执行周期转换成同一时间预算。',
    '不能把1MB/s直接当作每秒查询次数；题设无空查询也不代表CPU开销为零。',
    ['程序查询方式','CPU开销','设备速率']),
  S('array-machine-address-access-count','cs408.co.topic.53f5a8046fd9','D',
    'C程序执行a[i]=a[i]+b[j]，int为4 B；a、b首地址分别1000、2000，i=3、j=5均在寄存器，其他值未缓存于寄存器。仅计算数组数据访问（忽略取指和地址运算），访问地址与读写次数为（ ）。',
    {'A':'a=1003、b=2005；2读1写','B':'a=1012、b=2020；1读1写','C':'a=1012、b=2020；2读2写','D':'a=1012、b=2020；2读1写'},
    '下标按元素尺寸缩放，a[3]地址1000+3×4=1012，b[5]地址2000+5×4=2020。表达式需读取a[i]旧值和b[j]，相加后写回a[i]，合计2次数据读、1次数据写。寄存器中的下标不增加内存读。',
    '从C表达式的数据依赖列出两次load和一次store，并按元素宽度计算有效地址。',
    '构造LOAD a[3]、LOAD b[5]、ADD、STORE a[3]的参考指令序列，核对地址和访问次数。',
    '需要同时分析数组地址缩放和赋值表达式的数据依赖，区分寄存器与内存操作。',
    '数组下标不是字节偏移，赋值左侧仍需先读取其旧值参与右侧运算。',
    ['高级语言到机器级代码','数组寻址','数据访存']),
 ]

def independent_checks():
 import sympy as s
 from collections import deque
 x=s.symbols('x');t=s.symbols('t')
 assert s.limit((s.atan(x)-x+x**3/3)/x**5,x,0)==s.Rational(1,5)
 sol=1/(1+2*s.exp(-x));assert s.simplify(s.diff(sol,x)-sol*(1-sol))==0 and sol.subs(x,s.log(2))==s.Rational(1,2)
 assert s.integrate(2*s.pi*x**3,(x,0,1))==s.pi/2
 yy=s.sqrt(1-x*x/4);assert s.diff(yy,x).subs(x,0)==0 and s.diff(yy,x,2).subs(x,0)==-s.Rational(1,4)
 fp=2*x*s.exp(x**4)-s.cos(x)*s.exp(s.sin(x)**2);assert fp.subs(x,0)==-1 and s.diff(fp,x).subs(x,0)==2
 ode=x*x*s.exp(x)/2;assert s.simplify(s.diff(ode,x,2)-2*s.diff(ode,x)+ode)==s.exp(x)
 assert (math.ceil(1000/11),math.ceil(math.ceil(1000/11)/10))==(91,10)
 assert (1000+(2*5+3)*8,1000+(3*4+2)*8)==(1104,1112)
 assert (2000+(sum(range(1,4))+1)*4,5*6//2*4)==(2028,60)
 d=deque();d.append(1);d.append(2);d.appendleft(3);first=d.pop();d.append(4);second=d.popleft();d.appendleft(5);assert (first,second,list(d))==(2,3,[5,1,4])
 a=[9,8,7,6,5,4,3,2,1]
 for i in range(3,len(a)):
  key=a[i];j=i-3
  while j>=0 and a[j]>key:a[j+3]=a[j];j-=3
  a[j+3]=key
 assert a==[3,2,1,6,5,4,9,8,7]
 radix=[329,457,657,839,436,720,355]
 for divisor in (1,10):radix=sorted(radix,key=lambda n:n//divisor%10)
 assert radix==[720,329,436,839,355,457,657]
 a=[5,2,4,6,1,3];comparisons=shifts=0
 for i in range(1,len(a)):
  key=a[i];j=i-1
  while j>=0:
   comparisons+=1
   if a[j]<=key:break
   a[j+1]=a[j];shifts+=1;j-=1
  a[j+1]=key
 assert (comparisons,shifts)==(12,9)
 adj={i:[] for i in range(1,7)}
 for u,v in [(1,2),(1,3),(2,4),(3,4),(3,5),(4,6),(5,6)]:adj[u].append(v);adj[v].append(u)
 queue=deque([1]);parents={1:None};dist={1:0}
 while queue:
  u=queue.popleft()
  for v in sorted(adj[u]):
   if v not in parents:parents[v]=u;dist[v]=dist[u]+1;queue.append(v)
 assert dist[6]==3 and parents[6]==4 and parents[4]==2
 edges={('A','B'),('A','C'),('B','C'),('C','A'),('C','D'),('D','B')};edges.remove(('C','D'))
 assert (sum(v=='D' for u,v in edges),sum(u=='C' for u,v in edges),len(edges))==(0,1,5)
 assert 1/(Fraction(1,5)+Fraction(4,5)/8+Fraction(1,20))==Fraction(20,7)
 assert 1/(Fraction(1,5)+Fraction(1,20))==4
 assert ((3+8)*10,8*(3+1)*10)==(110,320)
 assert Fraction(1_000_000//4*80,100_000_000)==Fraction(1,5)
 assert (1000+3*4,2000+5*4)==(1012,2020)
 rows=candidates();assert len(rows)==20
 for r in rows:assert all(len(v)>=20 for v in r['reason'].values()),r['request']
 return {'status':'PASS','candidate_structure_cases':20,'methods':['symbolic limits, derivatives and ODE substitutions','exact rational performance calculations','gap insertion and stable radix simulations','BFS reference implementation','adjacency-set updates','deque trace'],'paid_model_calls':0}

def main():
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=('dry-run','apply'),default='dry-run');args=p.parse_args();checks=independent_checks()
 if runner.sha_file(BACKUP)!=BACKUP_SHA256:raise SystemExit('backup_hash_mismatch')
 toc=subprocess.run([r'C:\Program Files\PostgreSQL\18\bin\pg_restore.exe','--list',str(BACKUP)],capture_output=True,timeout=30)
 if toc.returncode or b'TABLE DATA public questions' not in toc.stdout:raise SystemExit('backup_archive_invalid')
 out=OUT_DIR/('preview.json' if args.mode=='dry-run' else 'checkpoint.json')
 if out.exists():raise SystemExit('output_exists_refuse_overwrite')
 runner.BACKUP,runner.BACKUP_SHA256=BACKUP,BACKUP_SHA256
 engine=create_engine(URL.create('postgresql+psycopg',username='postgres',host='127.0.0.1',port=PORT,database=DB_NAME))
 try:
  with Session(engine,expire_on_commit=False) as db:
   try:
    report=runner.run(db,candidate_specs=candidates(),batch_id='14');report['status']='DRY_RUN_ROLLED_BACK' if args.mode=='dry-run' else 'BATCH14_APPLIED';report['independent_checks']=checks
    if runner.sha_file(BACKUP)!=BACKUP_SHA256:raise ValueError('backup_changed')
    db.rollback() if args.mode=='dry-run' else db.commit()
   except BaseException:db.rollback();raise
  out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  print(json.dumps({'status':report['status'],'accepted':len(report['accepted']),'rejected':report['rejected']},ensure_ascii=True),flush=True)
 finally:engine.dispose()
if __name__=='__main__':main()
