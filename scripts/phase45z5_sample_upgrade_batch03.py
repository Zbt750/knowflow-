"""Ten substantive sample refinements using the existing versioned runner."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from scripts import phase45z5_sample_upgrade_batch01 as runner
from scripts.phase45z5_sample_upgrade_batch02 import row
OUT=ROOT/'storage/quality-audits/phase45z5-20261013/sample-upgrades/batch03'
BACKUP=ROOT/'storage/quality-audits/phase45z5-20261013/new-question-refinement/batch01/post-refinement.dump'
SHA='FC802E1434F0450E5531F73DB29C2E50A35693E17C5B4BDFEA08DA92501ECFAB'

def task(qid,node,answer,stem,options,explanation,m1,m2,steps,depth,trap,tags):
    reason=(depth,'先建立题目中的完整条件与运算关系，再逐步计算并用另一种方法复核关键结果。',trap,'通过本题明确条件下的推导和交叉验证，训练'+tags[0]+'与'+tags[-1]+'的综合使用。')
    return row(qid,node,answer,stem,options,explanation,[('direct_derivation',m1),('independent_crosscheck',m2)],steps,reason,tags)

def specs():
    return [
        task('bbb2023a-eb0e-5230-add1-e9534e109500','math.exam.3e373cbe2c92','A',
            'f(x)=x³+x，g=f⁻¹。则(g′(2),g″(2))为（ ）。',
            {'A':'(1/4,−3/32)','B':'(1/4,3/32)','C':'(1/2,−3/32)','D':'(1/4,−3/8)'},
            'f′=3x²+1>0，故反函数存在；f(1)=2。由f(g(y))=y求导，g′(2)=1/f′(1)=1/4。再次求导得g″(2)=−f″(1)/(f′(1))³=−6/64=−3/32。',
            '在复合恒等式f(g(y))=y上逐次使用链式法则，求出一阶及二阶反函数导数。','在x=1处局部展开y−2=4(x−1)+3(x−1)²+高阶项，反演得到x−1=(y−2)/4−3(y−2)²/64，二阶导为−3/32。',
            [('point','先由f(1)=2找到反函数对应的原变量点。'),('derivatives','一阶导取倒数，二阶导为−f″/(f′)³，代入得到1/4与−3/32。')],
            '结合反函数存在性、对应点确定和二阶链式法则，而非仅背一阶倒数公式。','二阶公式分母为一阶导的三次方，不能只取f″倒数或漏掉负号。',['反函数求导','二阶导数','局部反演']),
        task('e78e86b5-cf81-56a7-8bf9-d634ca42fcc2','math.exam.9578b3defcb0','C',
            '可导函数f的导数为f′(x)=(x−1)²(x+2)。关于x=−2和x=1处的性质正确的是（ ）。',
            {'A':'两处均为极小点','B':'−2为极大点，1为极小点','C':'−2为极小点，1为驻点拐点而非极值点','D':'−2不是极值点，1为极大点'},
            'f′在−2左侧负、右侧正，因此−2为极小点。x=1左右f′均为正，只在1处为0，因此不为极值。f″=3(x−1)(x+1)在1处由负变正，故曲线在1处为驻点拐点。',
            '制作f′在−2与1两侧的符号表，分别判断单调性是否反转。','独立求二阶导3(x−1)(x+1)，确认1处凹凸反转，同时一阶导为0。',
            [('extremum','在−2处f′由负转正，构成极小。'),('stationary_inflection','1处f′不变号但f″变号，故为驻点拐点。')],
            '需区分一阶导零点、极值与拐点，联合两阶导数的符号变化。','偶重因子使一阶导在1不变号，不能把所有导数零点都当成极值。',['导数符号分析','极值','驻点拐点']),
        task('aebbadd7-9b89-5952-b709-7fb83e8f0be1','cs408.os.topic.ec4f03dc7ff5','B',
            '磁盘柱面0至99，磁头位于50且向柱面增大方向移动，等待请求为18、35、61、83、91。LOOK到最后一个同方向请求便折返，SCAN到物理端99后折返；全部请求完成后停止。两者总移动量分别为（ ）。',
            {'A':'114，114','B':'114，130','C':'130，114','D':'127，130'},
            'LOOK服务61、83、91后折返至35、18，总移动(91−50)+(91−18)=41+73=114。SCAN先到99再折返至18，途中服务全部请求，移动(99−50)+(99−18)=49+81=130。两者差异来自91至99的额外往返。',
            '分别列出LOOK端点91和SCAN物理端点99，累加两个方向的跨度。','逐段模拟LOOK的11+22+8+56+17=114，SCAN的11+22+8+8+64+17=130。',
            [('turnaround','LOOK在91折返，SCAN在99折返。'),('movement','由起点到折返点再到18，分别得到114和130柱面。')],
            '需根据两种调度算法的折返约定形成请求服务轨迹并累计寻道距离。','将LOOK误当SCAN会额外访问物理端点；不能按请求排列直接执行FCFS。',['磁盘调度','LOOK与SCAN','寻道轨迹']),
        task('95e36f64-eb20-5ab4-89df-9682d5066926','cs408.cn.topic.9d2dd646a2ab','D',
            '应用数据400B，TCP首部20B、IPv4首部20B。路由器出接口MTU=300B，允许分片，IPv4无选项。MAC首部14B、尾部4B，无填充。按最大合法载荷分片，两片IP总长及第二片片偏移分别为（ ）。',
            {'A':'300B、180B；35','B':'300B、160B；280','C':'280B、140B；35','D':'300B、160B；35'},
            '原IP载荷含TCP首部，为420B。每片IP载荷至多280B且非末片必须为8B倍数，首片载荷280B、IP总长300B；剩余140B，末片IP总长160B。第二片片偏移按原IP载荷字节位置除8，280/8=35。MAC开销不计入MTU与IP总长；其帧长分别318B、178B。',
            '先按协议封装得到420B IP载荷，再按300B MTU减20B首部分片。','检查280是8的整数倍，第二片偏移35；两片载荷280+140恰覆盖原420B。',
            [('payload','400B应用数据加20B TCP首部形成420B IP载荷。'),('fragments','首片280B载荷、次片140B，IP总长300/160B且偏移35。')],
            '综合分层封装、MTU范围、8字节片偏移单位及分片首部重复。','不能把MAC开销计入IP MTU，片偏移也不能直接使用字节数280。',['IP分片','分层封装','片偏移']),
        task('8ed3ba75-03ab-5a00-8791-d1892ba33591','cs408.ds.topic.b66f6167354e','A',
            '无向图边权SA=3、SB=4、SC=10、AB=2、BC=2、AC=6。从S出发的最短路径树总权与图的最小生成树总权之差为（ ）。',
            {'A':'2','B':'0','C':'1','D':'3'},
            '最短距离A=3、B=4、C=6，最短路径树使用SA、SB、BC，总权9。最小生成树使用AB、BC、SA，总权2+2+3=7；通过Kruskal先选两个权2边再以权3连接S，已连通且不含环。差为2。最短路径树优化根到各点距离，MST优化全部树边总权。',
            '按Dijkstra比较各根路径得到SA、SB、BC组成最短路径树，边权和9。','用Kruskal依权升序选AB、BC、SA得到最小生成树，边权和7。',
            [('shortest_tree','根距离3、4、6对应边SA、SB、BC，总和9。'),('spanning_tree','最小生成树边AB、BC、SA总和7，两个优化目标差2。')],
            '需区分最短路径树与最小生成树的目标，并执行两种算法验证差异。','不能因为最短路径树所有根路径最短就认为其总边权最小。',['Prim最小生成树','最短路径树','优化目标区别']),
        task('dfd60eb7-1904-5761-8564-37a686a181db','math.exam.423bee85b09f','B',
            'f在[0,2]上二阶连续可导，f(0)=0、f(2)=4且f″(x)≥2。f(1)的最佳统一上界为（ ）。',
            {'A':'0','B':'1','C':'2','D':'4'},
            '令g(x)=f(x)−x²，则g″≥0，g为凸函数且g(0)=g(2)=0。凸函数在区间内不超过端点连线，所以g(1)≤0，得到f(1)≤1。函数f(x)=x²满足全部条件且f(1)=1，故该上界可达且最佳。',
            '减去曲率基准x²得到凸函数g，利用端点连线界推出f(1)≤1。','用f=x²构造达到上界的函数，证明无法进一步统一降低上界。',
            [('convex_reduction','g″=f″−2≥0且端点g都为0，凸性给g(1)≤0。'),('sharpness','f=x²满足假设并取到f(1)=1，因此上界最佳。')],
            '把二阶导下界转化为强凸函数的弦线界，并要求构造可达性证明。','仅由f凸性得到2不是最佳界，必须利用曲率下界2。',['凸函数','二阶导数界','最佳界构造']),
        task('944cf9a4-89f5-5b95-ac61-2ded117c5c15','math.exam.3504d885999b','C',
            '设F(x)=∫₀^(x²)|t−1|dt。关于F的光滑性，正确的是（ ）。',
            {'A':'在x=±1不可导','B':'在0不可导','C':'在全实轴C¹，但在x=±1无二阶导数','D':'在全实轴C²'},
            '被积函数连续，链式法则给F′(x)=2x|x²−1|，全轴连续。|x|<1时F′=2x−2x³，F″=2−6x²；|x|>1时F′=2x³−2x，F″=6x²−2。在±1处二阶导的两侧极限分别涉及−4和4，不一致，故二阶导不存在；其余处均光滑。',
            '先用变上限积分与链式法则求F′，按x²是否小于1分段求F″。','直接积分得到x²≤1时F=x²−x⁴/2，x²≥1时F=x⁴/2−x²+1，独立核对拼接的一、二阶导。',
            [('first_derivative','F′=2x|x²−1|连续，因此F属于C¹。'),('second_derivative','分段二阶导在±1两侧分别为−4和4，无法拼接。')],
            '组合变上限积分求导、复合上限链式法则与绝对值分段光滑性。','上限x²达到被积函数尖点1的位置是±1，不是仅x=1。',['变上限积分','链式法则','分段光滑性']),
        task('c43d49ae-0d80-5373-a68a-668cf915f958','math.exam.36050d277510','D',
            '方程组x+a y=1，2x+4y=b。关于解的情况，正确的是（ ）。',
            {'A':'a=2时总无解','B':'a≠2时有无穷多解','C':'a=2且b=2时唯一解','D':'a≠2唯一解；a=2,b=2无穷多解；a=2,b≠2无解'},
            '系数行列式4−2a，a≠2时非零，任意b唯一解。a=2时第二式左侧是第一式的2倍，若b=2则约束重合而有一个自由变量；若b≠2则右侧不相容，无解。该分类需同时检查系数秩与增广秩。',
            '按行列式是否为零分两类；退化时比较第二方程与第一方程的倍数。','行变换第二行减2倍第一行得到(4−2a)y=b−2，直接识别唯一、自由及矛盾。',
            [('elimination','消元得到(4−2a)y=b−2，非零系数唯一确定y。'),('singular_cases','系数为零时b−2也零才相容，否则出现0等于非零数。')],
            '需对系数参数与右端参数联合分类，不能只由行列式零判断无解。','奇异系数矩阵可能无解或无穷多解，区别在增广秩与相容性。',['矩阵方程','参数分类','秩与相容性']),
        task('8ec8e926-8698-594a-b16c-9df15322b753','math.exam.c431f98f817c','A',
            '计算I=∫₀^π x sin x/(1+cos²x) dx。（ ）',
            {'A':'π²/4','B':'π/2','C':'π²/2','D':'π'},
            '令h(x)=sin x/(1+cos²x)，有h(π−x)=h(x)。将积分作x→π−x变换并与原式相加，得2I=π∫₀^πh(x)dx。再令u=cos x，积分为∫₋₁¹1/(1+u²)du=π/2，故I=π²/4。',
            '利用关于π/2的对称性消去线性因子x，将I化为π/2倍的无x权积分。','代换u=cos x算出剩余反正切端点差π/2，并核对正积分与最终π²/4。',
            [('symmetry','h关于π/2对称，I与变换后的π−x权积分相加得2I。'),('substitution','剩余积分经u=cos x变为反正切端点差π/2。')],
            '需要先选择对称性化简加权积分，再进行三角代换与端点求值。','直接分部积分会引入更复杂函数；变换后的上、下界方向需正确处理。',['定积分对称性','方法选择','三角代换']),
        task('4a8cb210-cd34-5ee0-9f77-035161de750e','math.exam.936d8c834760','B',
            'D为椭圆x²/4+y²≤1，求∬_D(x²+2xy+3y²)dA。（ ）',
            {'A':'7π/4','B':'7π/2','C':'5π/2','D':'7π'},
            '令x=2u、y=v，区域为单位圆，Jacobian绝对值2。被积项变为4u²+4uv+3v²，奇项uv积分为0。单位圆上∬u²=∬v²=π/4，因此结果2(4+3)π/4=7π/2。也可在原椭圆用轴对称消掉xy，再分别计算二阶面积矩。',
            '将椭圆缩放为单位圆，保留Jacobian并利用旋转对称性算两个平方项。','原区域关于两坐标轴对称，交叉项积分零；原椭圆x²面积矩2π、y²面积矩π/2，合成7π/2。',
            [('transform','x=2u、y=v给Jacobian2，转化到单位圆。'),('moments','单位圆两个坐标平方积分均π/4，交叉项零，合成7π/2。')],
            '组合非等尺度变量变换、Jacobian、交叉项对称消项和面积矩计算。','漏掉Jacobian或把x²缩放因子错写成2，会低估积分值。',['二重积分','椭圆变量变换','对称面积矩']),
    ]

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');args=p.parse_args()
    output=OUT/('checkpoint.json' if args.apply else 'preview.json')
    if output.exists():raise SystemExit('output_exists')
    if hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper()!=SHA:raise SystemExit('backup_hash_mismatch')
    runner.OUT=OUT;runner.specs=specs
    e=create_engine('postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test')
    try:
        with Session(e,expire_on_commit=False) as db:
            report=runner.run(db,args.apply);db.commit() if args.apply else db.rollback()
        OUT.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8');print(json.dumps({'status':report['status'],'upgraded':len(report['results'])}))
    finally:e.dispose()
