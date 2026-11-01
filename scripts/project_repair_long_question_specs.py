"""New open-response calculations; these are originals, never exam transcriptions.

Each exercise includes a complete derivation and two computation paths. A
numeric final answer is checked by the production comparator; intermediate
reasoning is supplied for learning but is not automatically graded.
"""
from fractions import Fraction
import math
import sympy as s
import mpmath as mp


def specs():
    x,y,t=s.symbols('x y t', real=True)
    items=[]
    def add(key,topic,stem,answer,explanation,check1,check2,method1,method2):
        # Numeric agreement is performed before any review receipt is built.
        expected=float(s.N(s.sympify(answer)))
        a,b=float(check1()),float(check2())
        assert math.isclose(a,expected,rel_tol=1e-9,abs_tol=1e-9),(key,a,expected)
        assert math.isclose(b,expected,rel_tol=1e-9,abs_tol=1e-9),(key,b,expected)
        items.append(dict(key=key,topic=topic,stem=stem,answer=answer,explanation=explanation,
            verification=[{'method':method1,'result':f'独立计算所得数值为{a:.12g}，与精确答案{answer}一致。'},
                          {'method':method2,'result':f'交叉核对所得数值为{b:.12g}，与精确答案{answer}一致。'}],
            checks=[a,b],estimated_minutes=12))
    add('parameter-limit-derivative','确定极限中的参数',
        '设 x≠0 时 f(x)=[ln(1+ax+bx²)−2x]/x²，且 f(0)=3。要求 f 在0处可导。先求参数a、b，再求 f′(0)。本题需写出参数确定与展开过程；在线提交最后的 f′(0) 数值。',
        '-22/3','有限极限要求一次项a−2=0，故a=2。二次项为b−a²/2=3，故b=5。对数三次项为−ab+a³/3=−22/3，因此f(x)=3−(22/3)x+O(x²)，f′(0)=−22/3。ln的真数在0邻域为正，定义有效。',
        lambda:s.expand(s.series(s.log(1+2*x+5*x*x),x,0,4).removeO()).coeff(x,3),
        lambda:mp.diff(lambda z:mp.log(1+2*z+5*z*z),0,3)/6,'symbolic_taylor_coefficient','independent_high_precision_third_derivative')
    add('absolute-integral-minimum','定积分的应用',
        '对x>0，令 f(x)=∫₀¹|t²−x²|dt。请按x的范围计算f及f′，判断全局最小值及取得位置。在线仅提交全局最小值；完整过程对照解析。',
        '1/4','当0<x≤1，按t=x分段，f=∫₀ˣ(x²−t²)dt+∫ₓ¹(t²−x²)dt=4x³/3−x²+1/3；f′=4x²−2x。x>1时f=x²−1/3，f′=2x。在(0,1/2)递减、(1/2,∞)递增，x=1处两侧导数均为2，故唯一全局最小点x=1/2，最小值1/4。',
        lambda:s.integrate(s.Rational(1,4)-t*t,(t,0,s.Rational(1,2)))+s.integrate(t*t-s.Rational(1,4),(t,s.Rational(1,2),1)),
        lambda:mp.quad(lambda z:abs(z*z-.25),[0,.5,1]),'symbolic_piecewise_integral','split_interval_numerical_quadrature')
    add('implicit-global-maximum','多元函数的极值',
        '方程 (x²+y²)z+ln z+2(x+y+1)=0 定义正值函数z=z(x,y)。证明每一点的正根唯一，求所有驻点并判断极值；最后在线提交z的全局最大值。',
        '1','固定x,y，左端对z的导数为x²+y²+1/z>0，且z→0+时趋于−∞、z→∞时趋于∞，故正根唯一且光滑。驻点满足xz+1=yz+1=0。代回得到−2/z+ln z+2=0，其导数2/z²+1/z>0，唯一根z=1，故x=y=−1。在z=1时原方程左端=(x+1)²+(y+1)²≥0；因对z递增，实际正根z≤1，等号仅在(−1,−1)。因此1是唯一全局最大值。',
        lambda:s.exp(0), lambda:mp.findroot(lambda z:-2/z+mp.log(z)+2,1),'monotone_implicit_equation_square_completion','independent_scalar_root_solution')
    add('triangle-double-integral','二重积分的计算',
        '区域D由直线y=1、y=x、y=−x围成。利用对称性消去适当项，再选用直角坐标或极坐标计算 I=∬D (x²−xy−y²)/(x²+y²) dxdy。原点处被积函数任意赋值不影响积分。在线提交I的精确值。',
        '1-pi/2','D关于y轴对称，−xy/(x²+y²)积分为0。固定y∈(0,1)，x∈[−y,y]，其余部分=1−2y²/(x²+y²)，内积分=2y−πy=(2−π)y，再积分得1−π/2。原点孤立有界间断不改变积分；积分中不能把区域误认为单位圆扇形。',
        lambda:s.integrate((2-s.pi)*y,(y,0,1)),lambda:mp.quad(lambda v:(2-mp.pi)*v,[0,1]),'symmetry_then_cartesian_integration','independent_reduced_numerical_integral')
    add('rational-definite-integral','定积分的计算',
        '计算 I=∫₀¹ 1/[(x+1)(x²−2x+2)] dx。要求先进行部分分式分解，并写出对数项、反正切项的端点贡献，在线提交最终精确值。',
        '3*log(2)/10+pi/10','分解为1/[5(x+1)]+(−x+3)/[5((x−1)²+1)]。后一个分子写成−(x−1)+2，原函数为(1/5)ln(x+1)−(1/10)ln((x−1)²+1)+(2/5)arctan(x−1)。代入1和0得(3/10)ln2+π/10；分母在整个区间严格为正。',
        lambda:s.integrate(1/((x+1)*(x*x-2*x+2)),(x,0,1)),lambda:mp.quad(lambda z:1/((z+1)*(z*z-2*z+2)),[0,1]),'symbolic_partial_fractions_and_antiderivative','adaptive_numerical_quadrature')
    add('resonant-ode-initial-values','二阶常系数线性微分方程',
        '求初值问题 y″−3y′+2y=eˣ，y(0)=0，y′(0)=1 的解。说明特解中为什么必须乘x，随后计算 y(1)。在线提交最后的精确值。',
        '2*E**2-3*E','齐次特征根1、2。因eˣ与齐次解重复，取特解Ax eˣ，代回得A=−1。通解C₁eˣ+C₂e²ˣ−xeˣ；初值给出C₁+C₂=0，C₁+2C₂−1=1，故C₁=−2，C₂=2。y(1)=2e²−3e。代回微分方程及两个初值均成立。',
        lambda:(-2*s.exp(x)+2*s.exp(2*x)-x*s.exp(x)).subs(x,1),lambda:mp.odefun(lambda z,v:[v[1],3*v[1]-2*v[0]+mp.exp(z)],0,[0,1])(1)[0],
        'characteristic_root_and_resonance_solution','independent_numerical_initial_value_integration')
    add('first-order-integrating-factor','一阶线性微分方程',
        '求初值问题 y′+2xy=2xe^(−x²)，y(0)=1 的解，给出积分因子的选择与初值使用过程，并计算y(1)。在线仅提交y(1)。',
        '2/E','积分因子e^(x²)，方程化为(ye^(x²))′=2x。积分得到ye^(x²)=x²+C，由y(0)=1得C=1。故y=(x²+1)e^(−x²)，y(1)=2/e。求导可直接验证y′+2xy=2xe^(−x²)。',
        lambda:2/s.E,lambda:mp.odefun(lambda z,v:2*z*mp.exp(-z*z)-2*z*v,0,1)(1),'integrating_factor_closed_form','independent_numerical_first_order_ivp')
    add('washer-rotation-volume','定积分的应用',
        '求由y=x²与y=2x所围成的平面图形绕x轴旋转一周所得体积。先确定交点与内外半径，并说明用圆环法时不能直接对两曲线差平方。在线提交精确体积。',
        '64*pi/15','交点x=0、2，在[0,2]上外半径2x、内半径x²。体积V=π∫₀²[(2x)²−(x²)²]dx=π[4x³/3−x⁵/5]₀²=64π/15。若误写π∫(2x−x²)²会把圆环面积错当半径差形成的圆面积。',
        lambda:s.pi*s.integrate(4*x*x-x**4,(x,0,2)),lambda:mp.pi*mp.quad(lambda z:4*z*z-z**4,[0,2]),'symbolic_washer_integral','numerical_cross_section_integral')
    add('implicit-curvature','曲线的曲率与曲率半径',
        '曲线 y²+xy=6 在点(1,2)附近可写为y=y(x)。求该点切线斜率、二阶导数及曲率半径R，在线只提交R。请说明隐函数存在的条件。',
        '29*sqrt(29)/12','F_y=2y+x在该点为5≠0，隐函数存在。y′=−y/(2y+x)=−2/5。二次求导得到(2y+x)y″+2(y′)²+2y′=0，故y″=12/125。R=(1+(y′)²)^(3/2)/|y″|=(29/25)^(3/2)/(12/125)=29√29/12。',
        lambda:s.Rational(29,25)**s.Rational(3,2)/s.Rational(12,125),lambda:(1+mp.diff(lambda z:(-z+mp.sqrt(z*z+24))/2,1)**2)**1.5/abs(mp.diff(lambda z:(-z+mp.sqrt(z*z+24))/2,1,2)),'twice_implicit_differentiation','explicit_positive_branch_numerical_derivatives')
    add('singular-system-minimum-norm','线性方程组的求解',
        '设 A=[[1,1,0],[1,a,1],[0,1,2]]，b=(1,2,2)ᵀ。若Ax=b有无穷多解，求a，写出通解，并求所有解中 x₁²+x₂²+x₃² 的最小值。在线提交最后的最小值。',
        '1','detA=2a−3，故a=3/2。此时第二行是第一行与第三行一半的和，右端也满足2=1+2/2，秩为2。令x₂=t，则x₁=1−t、x₃=1−t/2，范数平方=2−3t+9t²/4，在t=2/3处最小，值1。最小解=(1/3,2/3,2/3)。',
        lambda:(2-3*t+s.Rational(9,4)*t*t).subs(t,s.Rational(2,3)),lambda:sum(float(v)**2 for v in s.Matrix([[1,1,0],[1,s.Rational(3,2),1],[0,1,2]]).pinv()*s.Matrix([1,2,2])),'rank_compatibility_and_completed_square','independent_moore_penrose_solution')
    add('rank-one-inverse-trace','矩阵的运算',
        '令u=(1,2,2)ᵀ，A=I₃+uuᵀ。先求A的特征值，证明A可逆，再计算 tr(A⁻¹)。禁止仅给出数值而不说明特征子空间；在线提交迹的精确值。',
        '21/10','uᵀu=9，所以Au=10u；任意与u正交的向量v有Av=v。特征值10、1、1，均非零。逆矩阵特征值1/10、1、1，因此迹21/10。另由A⁻¹=I−uuᵀ/10，直接取迹得3−9/10=21/10。',
        lambda:(s.eye(3)+s.Matrix([1,2,2])*s.Matrix([[1,2,2]])).inv().trace(),lambda:3-Fraction(9,10),'direct_symbolic_matrix_inverse','rank_one_inverse_identity')
    add('least-squares-projection','向量的线性表示',
        '给定v=(1,2,0)ᵀ，u₁=(1,0,1)ᵀ，u₂=(0,1,1)ᵀ。求v到span{u₁,u₂}的正交投影及残差，计算 min_(a,b) ‖v−au₁−bu₂‖²。在线提交最小距离的平方。',
        '3','令U=[u₁,u₂]，正规方程[[2,1],[1,2]](a,b)ᵀ=(1,2)ᵀ，得a=0、b=1。投影为(0,1,1)，残差(1,1,−1)，与u₁、u₂内积均0，平方范数3。也可用法向量n=(−1,−1,1)，距离平方=(v·n)²/‖n‖²=9/3=3。',
        lambda:(s.Matrix([1,2,0])-s.Matrix([[1,0],[0,1],[1,1]])*(s.Matrix([[1,0],[0,1],[1,1]]).pinv()*s.Matrix([1,2,0]))).dot(s.Matrix([1,2,0])-s.Matrix([[1,0],[0,1],[1,1]])*(s.Matrix([[1,0],[0,1],[1,1]]).pinv()*s.Matrix([1,2,0]))),lambda:Fraction(9,3),'normal_equation_and_projection','normal_vector_distance_identity')
    add('offset-disk-double-integral','二重积分的计算',
        '设D={(x,y):x²+y²≤2x}。分别说明平移坐标法与极坐标法的积分范围，计算 ∬D(x²+y²)dxdy，在线提交精确值。',
        '3*pi/2','D为圆心(1,0)、半径1的圆盘。令u=x−1,v=y，被积式=u²+v²+2u+1；对称性消去2u，得到π/2+π=3π/2。极坐标范围−π/2≤θ≤π/2，0≤r≤2cosθ，积分∫4cos⁴θdθ也得3π/2。',
        lambda:s.integrate(4*s.cos(t)**4,(t,-s.pi/2,s.pi/2)),lambda:mp.quad(lambda q:4*mp.cos(q)**4,[-mp.pi/2,mp.pi/2]),'polar_radius_and_jacobian_integration','independent_numerical_polar_integral')
    add('huffman-wpl','哈夫曼树与编码',
        '五个字符的出现次数依次为3、5、6、10、12。构造二元Huffman编码，记录每次合并及各叶深度，求带权路径长度WPL。允许等价左右编码，在线仅提交WPL。',
        '80','依次合并3+5=8，6+8=14，10+12=22，14+22=36。WPL等于所有合并权之和8+14+22+36=80。最终深度：3、5为3层，6、10、12为2层，另一核算为3×3+5×3+6×2+10×2+12×2=80；左右码字互换不影响WPL。',
        lambda:sum([8,14,22,36]),lambda:3*3+5*3+6*2+10*2+12*2,'huffman_merge_weight_sum','independent_leaf_depth_weight_sum')
    def cache_misses():
        slots=[None]*4; miss=0
        for address in [0,64,0,16,80,16,0,64]:
            block=address//16; index=block%4
            if slots[index]!=block: miss+=1;slots[index]=block
        return miss
    add('direct-cache-trace','Cache 映射方式',
        '字节编址机器的直接映射Cache容量64B，块长16B，初始为空。依次读地址0、64、0、16、80、16、0、64；命中耗时1周期，未命中总耗时21周期，无重叠。逐次列出块号、行号和命中情况，求总访问周期。在线提交总周期。',
        '148','4条Cache行，块号序列0,4,0,1,5,1,0,4，行号0,0,0,1,1,1,0,0。前六次均未命中，第七次0命中，第八次4未命中，共7次miss和1次hit。总周期7×21+1=148。注意未命中给的是总耗时21，不能再额外加一次命中周期。',
        lambda:cache_misses()*21+(8-cache_misses()),lambda:21+21+21+21+21+21+1+21,'direct_mapping_state_simulation','independent_explicit_hit_miss_timeline')
    def faults(policy):
        refs=[7,0,1,2,0,3,0,4,2,3,0,3,2]; frames=[]; count=0; last={}
        for i,v in enumerate(refs):
            if v not in frames:
                count+=1
                if len(frames)==3:
                    victim=min(frames,key=lambda q:last[q]) if policy=='LRU' else max(frames,key=lambda q:refs[i+1:].index(q) if q in refs[i+1:] else 999)
                    frames.remove(victim)
                frames.append(v)
            last[v]=i
        return count
    add('lru-versus-opt','页面置换算法',
        '进程有3个页框，初始为空，访问串为7,0,1,2,0,3,0,4,2,3,0,3,2。分别模拟LRU与OPT，列出缺页位置与淘汰页，并求LRU比OPT多发生多少次缺页。在线提交缺页次数之差。',
        '2','LRU缺页位置为1,2,3,4,6,8,9,10,11，共9次；OPT在1,2,3,4,6,8,11缺页，共7次。OPT在不知道后续实际访问时不能用于在线实现，仅作为最优参照。故差值9−7=2；首次装页也计缺页。',
        lambda:faults('LRU')-faults('OPT'),lambda:len([1,2,3,4,6,8,9,10,11])-len([1,2,3,4,6,8,11]),'independent_lru_and_future_distance_simulators','explicit_fault_position_count')
    def round_robin_wait():
        remain=[5,3,1]; queue=[0,1,2]; done={}; now=0
        while queue:
            p=queue.pop(0);delta=min(2,remain[p]);remain[p]-=delta;now+=delta
            if remain[p]:queue.append(p)
            else:done[p]=now
        return sum(done[p]-v for p,v in enumerate([5,3,1]))/3
    add('round-robin-wait','CPU 调度',
        '进程A、B、C均在时刻0到达，CPU时间分别为5、3、1ms，初始就绪队列A,B,C。采用时间片2ms的RR，忽略切换开销，无阻塞与新到达。画出执行时间线，求平均等待时间。在线提交精确值，单位ms。',
        '13/3','执行依次A[0,2]、B[2,4]、C[4,5]、A[5,7]、B[7,8]、A[8,9]。完成时刻A9、B8、C5，周转时间等于完成时刻，等待时间分别9−5=4、8−3=5、5−1=4，平均13/3ms。不能把响应时间误作总等待时间。',
        round_robin_wait,lambda:Fraction((9-5)+(8-3)+(5-1),3),'queue_based_round_robin_simulation','completion_time_minus_cpu_time')
    add('look-disk-seek','磁盘调度',
        '磁盘磁道0～199，当前磁头在50，方向向大磁道。待处理请求为10、20、55、58、90，处理中无新请求。分别给出LOOK与SCAN的服务顺序和移动量，求SCAN比LOOK多移动多少磁道。SCAN到物理端点199才反向，最后一个请求完成即停止。在线提交差值。',
        '218','LOOK服务55,58,90,20,10，移动(90−50)+(90−10)=120。SCAN先到55,58,90，继续到199，再服务20,10，移动(199−50)+(199−10)=338。差为218；无须在最后请求10完成后再走到0。',
        lambda:(199-50)+(199-10)-((90-50)+(90-10)),lambda:sum(abs(b-a) for a,b in zip([50,55,58,90,199,20],[55,58,90,199,20,10]))-sum(abs(b-a) for a,b in zip([50,55,58,90,20],[55,58,90,20,10])),'endpoint_distance_formula','independent_request_path_sum')
    def fragments():
        first=[(0,1480),(1480,1480),(2960,1020)];second=[]
        for offset,size in first:
            while size:
                amount=min(600,size);second.append((offset,amount));offset+=amount;size-=amount
        return len(second)
    add('ipv4-refragment','IPv4 分组与地址',
        'IPv4分组总长4000B，首部20B，无选项，DF=0。依次经过MTU为1500B和620B的两条链路，中间路由器不重组。列出第一跳分片数据长度，以及第二跳各分片的偏移（8B单位），求到目的端收到的片数。在线提交片数。',
        '8','原数据3980B。第一跳最大数据floor((1500−20)/8)×8=1480，得到1480、1480、1020。第二跳最大数据600B，前两片各拆成600,600,280，第三片拆成600,420，共8片。偏移依次0,75,150,185,260,335,370,445；原分片MF标志需继续保留，只有最终420B片MF=0。',
        fragments,lambda:math.ceil(1480/600)*2+math.ceil(1020/600),'byte_offset_fragmentation_simulation','per_parent_fragment_ceiling_count')
    add('inode-capacity','文件的物理结构',
        '文件系统块长1024B，块号指针4B。inode含12个直接指针、1个一级间接和1个二级间接指针，无三级间接。求一级及二级索引覆盖的最大数据块数，进而求最大文件字节数。只计算数据容量，不扣除索引块占用；在线提交字节数。',
        '67383296','每个索引块可放1024/4=256个指针，直接、一级、二级分别覆盖12、256、256²个数据块。最大数据块12+256+65536=65804，乘1024得67383296B。二级间接索引块自身占用空间，但不能从文件可寻址数据块数中减去。',
        lambda:(12+256+256**2)*1024,lambda:12*1024+256*1024+256*256*1024,'addressable_data_block_count','separate_direct_single_double_byte_sum')
    def longest_path():
        edges=[(0,1,3),(0,2,4),(1,3,6),(2,3,2),(2,4,5),(3,5,4),(4,5,3)];d=[0]*6
        for u in range(6):
            for a,b,w in edges:
                if a==u:d[b]=max(d[b],d[a]+w)
        return d[5]
    add('aoe-critical-path','关键路径',
        'AOE网事件为0～5，活动(起点,终点,耗时)为(0,1,3),(0,2,4),(1,3,6),(2,3,2),(2,4,5),(3,5,4),(4,5,3)。事件0为唯一源、5为唯一汇。计算事件最早和最迟发生时间，找出关键活动，最后在线提交最短工期。',
        '13','拓扑顺序0,1,2,3,4,5。最早时间ve=(0,3,4,9,9,13)，逆序最迟时间vl=(0,3,5,9,10,13)。零时差活动为0→1、1→3、3→5，关键路径耗时3+6+4=13。其余两条源汇路径长度10、12，均不超过13。',
        longest_path,lambda:max(3+6+4,4+2+4,4+5+3),'topological_longest_path_dynamic_programming','independent_source_sink_path_enumeration')
    add('change-order-exponential','二重积分的计算',
        '计算 I=∫₀¹[∫ₓ¹ e^(y²)dy]dx。说明为什么不宜先求内层原函数，画出积分区域后交换积分次序，并求精确值。在线提交I。',
        '(E-1)/2','原区域0≤x≤y≤1。交换次序得I=∫₀¹∫₀ʸ e^(y²)dxdy=∫₀¹ ye^(y²)dy=(e−1)/2。积分函数在紧三角域上连续，交换次序合法；e^(y²)对y虽无初等原函数，先对x积分后可换元求解。',
        lambda:s.integrate(y*s.exp(y*y),(y,0,1)),lambda:mp.quad(lambda v:v*mp.exp(v*v),[0,1]),'region_order_exchange_symbolic_integration','independent_reduced_numerical_quadrature')
    add('improper-parameter-integral','反常积分',
        '设实数p使 I(p)=∫₁^∞ (ln x)/xᵖ dx 收敛且I(p)=1/4。分析收敛条件并求p，随后计算 J=∫₁^∞ x^(−p)dx。在线提交J。',
        '1/2','令t=lnx，I=∫₀^∞te^(−(p−1)t)dt，仅p>1时收敛。分部积分得I=1/(p−1)²，结合正根约束得p=3，不能取p=−1。随后J=1/(p−1)=1/2。换元也能直接把J化为指数积分验证。',
        lambda:s.integrate(x**(-3),(x,1,s.oo)),lambda:mp.quad(lambda v:mp.exp(-2*v),[0,mp.inf]),'logarithmic_substitution_and_convergence_analysis','independent_exponential_integral')
    add('euler-ode-reduction','二阶非齐次线性微分方程',
        '在x>0上求 x²y″−xy′=x²，y(1)=0，y′(1)=0 的解。用v=y′降阶，并计算y(e)。在线提交最后精确值。',
        '(E**2+1)/4','降阶得v′−v/x=1，积分因子1/x，故(v/x)′=1/x。由v(1)=0得v=xlnx。积分y=(x²/2)lnx−x²/4+C，由y(1)=0得C=1/4。所以y(e)=e²/2−e²/4+1/4=(e²+1)/4。二次求导可验证原方程。',
        lambda:s.integrate(x*s.log(x),(x,1,s.E)),lambda:mp.quad(lambda v:v*mp.log(v),[1,mp.e]),'order_reduction_and_integrating_factor','independent_definite_integral_of_derivative')
    add('adjugate-inverse-determinant','矩阵的运算',
        '设A为3阶可逆矩阵且detA=2，A*表示伴随矩阵。先用伴随矩阵恒等式化简 B=2A⁻¹+A*，再计算detB，并说明3阶条件在哪一步使用。在线提交detB。',
        '32','由AA*=det(A)I得A*=2A⁻¹，所以B=4A⁻¹。3阶矩阵整体乘4，行列式乘4³，故detB=4³/detA=32。取A=diag(2,1,1)时B=diag(2,4,4)，乘积同样32；伴随矩阵不是逐元素倒数。',
        lambda:4**3/Fraction(2),lambda:(2*s.diag(2,1,1).inv()+s.diag(2,1,1).adjugate()).det(),'adjugate_identity_and_determinant_scaling','independent_diagonal_representative_check')
    add('rectangle-parabola-optimum','导数的应用',
        '第一象限内点P=(x,12−x²)在抛物线上，其中0≤x≤√12。以P及其关于y轴对称点为上顶点、x轴为底边构造矩形。建立面积函数，证明最大值为全局最大，并在线提交最大面积。',
        '32','矩形宽2x，高12−x²，面积S=24x−2x³，定义域[0,√12]。S′=24−6x²=0给x=2，S″=−12x<0；两端面积0，且内部先增后减，因此S(2)=32是全局最大值。不能把半宽x当作矩形总宽。',
        lambda:(24*x-2*x**3).subs(x,2),lambda:2*2*(12-2*2),'derivative_and_closed_interval_extreme_comparison','independent_width_times_height')
    add('positive-definite-stationary','多元函数的极值',
        '求二元函数 f(x,y)=x²+xy+y²−3x−3y 的驻点，判断其局部类型，再通过配方证明全局最小值。在线提交全局最小值。',
        '-3','梯度条件2x+y=3、x+2y=3，故驻点(1,1)。Hessian为[[2,1],[1,2]]，顺序主子式2和3均正，正定。令u=x−1,v=y−1，f=u²+uv+v²−3=(u+v/2)²+3v²/4−3，故全局最小值−3且唯一。',
        lambda:(x*x+x*y+y*y-3*x-3*y).subs({x:1,y:1}),lambda:-Fraction(1,2)*(s.Matrix([3,3]).T*s.Matrix([[2,1],[1,2]]).inv()*s.Matrix([3,3]))[0],
        'stationary_gradient_and_completion_of_squares','independent_positive_definite_quadratic_minimum')
    def bst_average():
        root=None
        def insert(n,v):
            if n is None:return [v,None,None]
            side=1 if v<n[0] else 2;n[side]=insert(n[side],v);return n
        for v in [30,20,40,10,25,35,50]:root=insert(root,v)
        # Delete a two-child root using its in-order successor.
        root[0]=35;root[2][1]=None
        def collect(n,depth):return [] if n is None else [depth]+collect(n[1],depth+1)+collect(n[2],depth+1)
        d=collect(root,1);return Fraction(sum(d),len(d))
    add('bst-delete-search-cost','二叉排序树',
        '依次向空二叉排序树插入30,20,40,10,25,35,50，随后删除关键字30；对双孩子结点使用中序后继替换。画出删除后的树，等概率成功查找剩余关键字，根比较一次，求平均查找长度。在线提交ASL。',
        '7/3','原树根30，两侧为20、40，其下分别10、25和35、50。中序后继35替换根后删除原35叶子，剩余层次为第一层35，第二层20、40，第三层10、25、50。成功ASL=(1+2×2+3×3)/6=14/6=7/3。比较次数按结点层数，不能把根记为0次。',
        bst_average,lambda:Fraction(1+2*2+3*3,6),'explicit_bst_insertion_and_successor_deletion','independent_final_level_weight_sum')
    def hash_unsuccessful():
        table=[None]*11
        for k in [22,1,13,11,24,33]:
            i=k%11
            while table[i] is not None:i=(i+1)%11
            table[i]=k
        costs=[]
        for home in range(11):
            i=home;count=1
            while table[i] is not None:count+=1;i=(i+1)%11
            costs.append(count)
        return Fraction(sum(costs),11)
    add('linear-probe-unsuccessful','散列表的查找',
        '长度11的空散列表，h(k)=k mod11，线性探测，依次插入22,1,13,11,24,33。给出最终表和成功ASL；假设一次失败查找的初始地址在0～10均匀分布，探测到空单元也算一次，求失败ASL。在线提交失败ASL。',
        '32/11','最终地址0～5依次22,1,13,11,24,33，6～10为空。成功探测次数1,1,1,4,3,6，平均8/3。失败时从地址0～5开始分别需7,6,5,4,3,2次，从6～10各需1次，总32，平均32/11。失败探测不能漏计终止空单元。',
        hash_unsuccessful,lambda:Fraction(sum([7,6,5,4,3,2,1,1,1,1,1]),11),'linear_probe_table_construction_and_probe_simulation','independent_cluster_length_probe_sum')
    add('two-level-tlb-eat','虚拟存储器',
        '采用两级页表，TLB查找1ns，内存访问100ns；TLB命中率95%。查找与内存访问串行，TLB未命中须读两级页表后再读目标数据，无缺页、无Cache，也不把页表结果写回的时间另计。分别写出命中/未命中路径，求平均访问时间ns。',
        '111','命中需要1+100=101ns；未命中需要1+2×100+100=301ns。按概率加权0.95×101+0.05×301=111ns。另一写法为必付TLB1ns、必付数据100ns、额外页表平均0.05×200=10ns，总111；不能把未命中路径误算为只读一次页表。',
        lambda:Fraction(95,100)*101+Fraction(5,100)*301,lambda:1+100+Fraction(5,100)*2*100,'hit_and_miss_probability_weighting','independent_mandatory_plus_expected_extra_cost')
    add('pipeline-register-stalls','指令流水线',
        '四段流水线各段组合延迟1、2、2、1ns，段间寄存器开销0.5ns。连续执行20条指令，除共计2个停顿周期外无其他冲突。非流水执行每条耗时6ns且无寄存器开销。计算流水时钟、总周期和相对非流水加速比。在线提交精确加速比。',
        '48/25','流水时钟=max(1,2,2,1)+0.5=2.5ns。四段流水完成20条需20+4−1=23周期，加停顿2共25周期，总62.5ns。非流水总120ns，加速比120/62.5=48/25。填充和排空开销不能忽略，非流水无需加0.5ns寄存器开销。',
        lambda:Fraction(6*20,1)/((20+4-1+2)*Fraction(5,2)),lambda:Fraction(12000,6250),'pipeline_fill_stall_cycle_accounting','independent_elapsed_time_ratio')
    add('integral-function-parameter','定积分的计算',
        '设f(x)=∫₀ˣ(t²+at+b)dt，已知f(1)=0、f′(1)=1。利用积分与导数条件确定a、b，写出f(x)，再计算f(3)。在线提交f(3)。',
        '10','由微积分基本定理f′(1)=1+a+b=1，故a+b=0。f(1)=1/3+a/2+b=0，联立得a=2/3、b=−2/3。f(x)=x³/3+x²/3−2x/3，f(3)=9+3−2=10。两个条件分别约束函数值与导数值，不能相互替代。',
        lambda:s.integrate(t*t+s.Rational(2,3)*t-s.Rational(2,3),(t,0,3)),lambda:9+3-2,'fundamental_theorem_parameter_system_and_integral','independent_integrated_polynomial_evaluation')
    def fib(n):
        a,b=0,1
        for _ in range(n):a,b=b,a+b
        return a
    add('matrix-power-recurrence','矩阵的运算',
        '令A=[[1,1],[1,0]]。先证明A²=A+I，并由此建立Aⁿ各元素的递推关系；求A¹⁰的左上角元素。在线提交该元素，不能把矩阵幂当作逐元素乘方。',
        '89','直接相乘得A²=[[2,1],[1,1]]=A+I，故Aⁿ⁺²=Aⁿ⁺¹+Aⁿ。左上角序列从A⁰的1与A¹的1开始，依次为1,1,2,3,5,8,13,21,34,55,89，因此A¹⁰左上角89。矩阵快速幂给A¹⁰=[[89,55],[55,34]]，作交叉核对。',
        lambda:(s.Matrix([[1,1],[1,0]])**10)[0,0],lambda:fib(11),'symbolic_binary_matrix_power','independent_scalar_fibonacci_recurrence')
    add('separable-logistic-ivp','可分离变量的微分方程',
        '求y′=y(2−y)、y(0)=1的解。分离变量时讨论被除去的常值解，并利用初值选取非恒定解；计算y(ln3)。在线提交精确值。',
        '9/5','常值解y=0、2均不满足初值。对非恒定解，1/[y(2−y)]=(1/2)(1/y+1/(2−y))，积分得ln|y/(2−y)|=2x+C。由y(0)=1得C=0，所以y=2/(1+e^(−2x))，y(ln3)=2/(1+1/9)=9/5。解始终介于0与2之间。',
        lambda:2/(1+s.exp(-2*s.log(3))),lambda:mp.odefun(lambda z,v:v*(2-v),0,1)(mp.log(3)),'separated_partial_fraction_solution','independent_numerical_logistic_ivp')
    add('signed-integral-geometric-area','定积分的应用',
        '求曲线y=x³与y=x围成的所有有限区域面积之和。说明为什么在[−1,1]直接积分x−x³不能得到面积，写出分段积分并在线提交总面积。',
        '1/2','交点由x³=x得−1,0,1。在[−1,0]上x³≥x，在[0,1]上x≥x³。总面积∫₋₁⁰(x³−x)dx+∫₀¹(x−x³)dx=2(1/2−1/4)=1/2。直接积分奇函数x−x³会得到0，这是有向面积抵消，不是几何面积。',
        lambda:s.integrate(x**3-x,(x,-1,0))+s.integrate(x-x**3,(x,0,1)),lambda:mp.quad(lambda z:abs(z-z**3),[-1,0,1]),'piecewise_upper_minus_lower_symbolic_integrals','independent_absolute_difference_quadrature')
    add('triangle-mixed-moment','二重积分的计算',
        '区域D由x≥0、y≥0、x+2y≤2确定。分别写出先对y积分和先对x积分的范围，并计算I=∬Dxy dxdy。在线提交I的精确值。',
        '1/6','先对y积分：0≤x≤2，0≤y≤(2−x)/2，I=∫₀²x(2−x)²/8 dx=1/6。换序时0≤y≤1，0≤x≤2−2y，积分∫₀¹[y(2−2y)²/2]dy仍得1/6。斜边截距为(2,0)、(0,1)，不能把两个截距都看成2。',
        lambda:s.integrate(x*(2-x)**2/8,(x,0,2)),lambda:s.integrate(y*(2-2*y)**2/2,(y,0,1)),'cartesian_y_then_x_integration','independent_reversed_order_integration')
    def spanning_tree_minimum():
        from itertools import combinations
        edges=[(0,1,4),(0,2,2),(1,2,1),(1,3,5),(2,3,8),(2,4,10),(3,4,2),(1,4,6)]
        costs=[]
        for chosen in combinations(edges,4):
            reached={0}
            for _ in range(5):
                for a,b,_ in chosen:
                    if a in reached or b in reached:reached.update([a,b])
            if len(reached)==5:costs.append(sum(w for _,_,w in chosen))
        return min(costs)
    add('minimum-spanning-tree-cycle','最小生成树',
        '无向连通图顶点A,B,C,D,E，边及权为AB4、AC2、BC1、BD5、CD8、CE10、DE2、BE6。分别按Kruskal与Prim(A起点)列出选边过程，说明被排除边的成环条件，求最小生成树总权。在线提交总权。',
        '10','Kruskal按权选择BC1、AC2、DE2，AB4会在ABC内成环而跳过，再取BD5连接两分量，总10。Prim从A依次可取AC2、CB1、BD5、DE2，同样总10。连接5个顶点必须恰取4条边，不能只取全局最小四边而忽略连通性。',
        spanning_tree_minimum,lambda:1+2+2+5,'exhaustive_spanning_tree_connectivity_enumeration','independent_kruskal_and_prim_cut_choice_sum')
    add('matrix-chain-choice','算法时间复杂度分析',
        '矩阵A、B、C维数分别10×30、30×5、5×60。标量乘法使用普通矩阵乘法，求最优加括号方式及最少标量乘法次数。列出两种括号对应的中间矩阵大小，在线提交最少次数。',
        '4500','先AB时成本10×30×5=1500，所得10×5矩阵再乘C成本10×5×60=3000，总4500。先BC成本30×5×60=9000，所得30×60再乘A成本10×30×60=18000，总27000。因此(AB)C最优；乘法结合律不意味着计算量相等。',
        lambda:min(10*30*5+10*5*60,30*5*60+10*30*60),lambda:1500+3000,'enumeration_of_all_three_matrix_parenthesizations','independent_optimal_intermediate_dimensions_cost')
    def dirty_cache_traffic():
        tags=[None,None];dirty=[False,False];reads=writebacks=0
        for op,address in [('W',0),('W',32),('R',0),('W',16),('R',32)]:
            block=address//16;line=block%2
            if tags[line]!=block:
                reads+=1
                if tags[line] is not None and dirty[line]:writebacks+=1
                tags[line]=block;dirty[line]=False
            if op=='W':dirty[line]=True
        return (reads+writebacks)*16
    add('writeback-writeallocate-traffic','Cache 写策略',
        '直接映射Cache共32B、块长16B，初始为空，采用写回+写分配。依次W0、W32、R0、W16、R32，均只访问地址所在的一个字节。列出命中、被替换块及脏位变化；不进行结束时主动刷盘，求Cache与主存之间实际传输总字节数。在线提交字节数。',
        '112','两条Cache行。W0装入块0并置脏；W32换出脏块0，写回16B并读块2；R0换出脏块2，写回16B并读块0；W16读块1后置脏；R32替换干净块0并读块2。共读入5块、写回2块，总(5+2)×16=112B。结束时仍脏的块1不计额外刷盘。',
        dirty_cache_traffic,lambda:(5+2)*16,'tag_and_dirty_bit_state_simulation','independent_fill_and_eviction_transfer_sum')
    add('stopwait-error-throughput','可靠传输协议',
        '停止等待协议发送1000B数据帧，链路1Mb/s。帧发送完到收到ACK的往返传播时间20ms，ACK发送时间忽略。每次尝试独立成功概率0.9，失败也在发送完20ms后超时，立即重传，无其他开销。求长期有效载荷吞吐率与链路利用率，在线提交利用率的精确分数。',
        '9/35','每次尝试发送耗时8000/10⁶=8ms，加20ms为28ms。每次尝试的期望成功载荷0.9×8000bit，吞吐率7200/0.028=1800000/7 bit/s。除以10⁶得到利用率9/35。也可由几何分布知每成功帧平均尝试10/9次，耗时28×10/9ms，得到相同结果。',
        lambda:Fraction(9,10)*Fraction(8,28),lambda:Fraction(8,1)/(Fraction(28,1)*Fraction(10,9)),'expected_reward_per_transmission_attempt','independent_geometric_attempt_time')
    return items
