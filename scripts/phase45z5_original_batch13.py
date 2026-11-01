"""Batch 13: calculus conditions and networking state/calculation questions."""
from __future__ import annotations
import argparse, json, subprocess, sys
from fractions import Fraction
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from scripts import phase45z5_original_batch01 as runner
from scripts.phase45z5_original_batch02 import item
BACKUP=ROOT/'storage/quality-audits/phase45z5-20261013/originals/batch12/post-batch.dump'
BACKUP_SHA256='90238C4930A87D17A634707EA8B220F8323BAE8FDF6DFC375574639762607502'
OUT_DIR=ROOT/'storage/quality-audits/phase45z5-20261013/originals/batch13'
DB_NAME,PORT,SYSTEM_ID=runner.DB_NAME,runner.PORT,runner.SYSTEM_ID

def S(key,node,answer,stem,options,explanation,derive,check,depth,trap,tags):
    return item('z5b13-'+key,node,answer,stem,options,explanation,
        [('independent_derivation',derive),('separate_calculation_or_rule_check',check)],
        [('derive',derive),('crosscheck',check)],{k:k==answer for k in options},
        (depth,derive,trap,'将'+tags[0]+'与'+tags[1]+'联系起来，训练条件辨析、推理过程和结果核对。'),tags)

def candidates():
    return [
      S('symmetric-gravity-equilibrium','math.exam.0e5b36de4dd9','B',
        '两个相同质量M的质点固定于数轴−a、a（a>0），试探质点质量m位于−a<x<a，规定向右为正，且只沿该轴运动。依牛顿引力F(x)=GmM[(a−x)⁻²−(a+x)⁻²]。平衡点及小位移下稳定性为（ ）。',
        {'A':'x=0，稳定','B':'x=0，不稳定','C':'x=a/2，稳定','D':'不存在平衡点'},
        '区间内两个分母均正，F=0等价于a−x=a+x，故仅x=0。若x>0，右侧距离较小而F>0；若x<0则F<0，力将小偏移进一步放大。也有F′(0)=4GmM/a³>0，因此沿轴的该平衡不稳定。',
        '解两侧引力相等的方程得到唯一平衡点，再用左右符号检验扰动方向。',
        '化简F=4GmMax/(a²−x²)²，分母严格为正；另求导得F′(0)>0。',
        '需要依据对称性确定平衡，再结合力的局部符号判断扰动是否恢复。',
        '两侧引力相等只说明平衡，不能据此推断稳定；更近的质点吸引力更强。',
        ['引力模型与对称性','平衡稳定性','函数符号']),
      S('bernoulli-reciprocal-initial-value','math.exam.21e0818406c9','C',
        '初值问题y′+y=y²，y(0)=1/2，在包含0的解区间内，y(ln2)及x→+∞时的极限为（ ）。',
        {'A':'2/3，1','B':'1/3，1','C':'1/3，0','D':'2/3，0'},
        '令u=1/y，因y′=y²−y，得u′=u−1。u(0)=2，所以u=1+eˣ，y=1/(1+eˣ)。因此y(ln2)=1/3，且正向无奇点、y随x增大趋于0。直接代入原微分方程可核对符号。',
        '通过倒数代换将Bernoulli方程化为u′−u=−1，并依据初值求得u=1+eˣ。',
        '直接微分y=1/(1+eˣ)，核对y′+y=y²及y(0)=1/2，再计算指定点与极限。',
        '需要识别非线性方程的倒数代换，并同时检验初值、解值和长期行为。',
        '倒数求导带负号，遗漏会把衰减解变成增长解；长期极限不能沿用初值。',
        ['其他方程','Bernoulli方程','初值条件']),
      S('nonlinear-energy-reduction','math.exam.ec75fe95fe0f','A',
        '设y″=2y³，y(0)=1、y′(0)=−1。包含0的解区间内，y(1)及最大实定义区间为（ ）。',
        {'A':'1/2，(−1,+∞)','B':'1/2，(−∞,1)','C':'2，(−1,+∞)','D':'0，整个实轴'},
        '两边乘y′并积分得(y′)²=y⁴+C，初值给C=0。由于初始导数负且解保持正，取y′=−y²，分离变量得y=1/(1+x)。此解在x>−1满足方程和初值，x=−1处发散，故y(1)=1/2。',
        '先构造能量型一阶积分，再由初始导数选择正确分支并求解分离变量方程。',
        '直接求y=1/(1+x)的两阶导数，核对y″=2y³和初值，检查分母为零的位置。',
        '需要使用一阶积分降低非线性方程阶数，并按初值选择符号分支。',
        '平方关系不允许任意选正负分支；必须用初始导数和解连续性固定分支。',
        ['二阶非线性微分方程','降阶积分','解区间']),
      S('discontinuous-integrand-composite-limit','math.exam.3504d885999b','D',
        '令f(t)=−1（t<0）、f(t)=1（t>0），并取f(0)=0；F(x)=∫₀ˣf(t)dt，G(x)=∫₀^{x²}f(t)dt。关于零点的导数，正确的是（ ）。',
        {'A':'F′(0)=0，G′(0)=0','B':'F′(0)=1，G′(0)=0','C':'F′(0)不存在，G′(0)不存在','D':'F′(0)不存在，G′(0)=0'},
        'x>0时F=x，x<0时积分反向且被积函数为−1，故F=−x，合成F=|x|，左右导数为−1和1。x²始终非负，因此G=x²，G′(0)=0。f在0不连续，不能机械写F′(0)=f(0)。',
        '分别在正负积分区间直接计算F=|x|，再利用非负上限得到G=x²并比较左右差商。',
        '取h正负两侧检查F(h)/h得到±1；而G(h)/h=h，两侧均趋于0。',
        '需要分析不连续被积函数、积分方向和复合上限对可导性的不同影响。',
        '基本定理求导需要相应连续条件，单点定义f(0)=0不能消除F的尖点。',
        ['积分上限变化与导数连续性','左右导数','复合上限']),
      S('log-inequality-two-sided','math.exam.68217a446e4c','B',
        '对所有x>1，下列不等式链中始终严格成立的是（ ）。',
        {'A':'x−1<ln x<2(x−1)/(x+1)','B':'2(x−1)/(x+1)<ln x<x−1','C':'ln x<2(x−1)/(x+1)<x−1','D':'2(x−1)/(x+1)<x−1<ln x'},
        '令h=ln x−2(x−1)/(x+1)，h(1)=0且h′=(x−1)²/[x(x+1)²]>0，所以x>1时h>0。再令k=x−1−ln x，k(1)=0且k′=1−1/x>0，得ln x<x−1。两条严格不等式合并给出B。',
        '构造两个差函数，求导并由x=1的零值及x>1时导数严格为正推出上下界。',
        '以积分表示ln x=∫₁ˣdt/t核对上界；下界差函数导数精确化简为正的平方项。',
        '需要分别建立非线性上下界，处理严格性并统一参数的适用区间。',
        '不能将x<1时的下界方向直接移用到x>1，严格不等式也不包括x=1。',
        ['不等式的证明','单调性方法','对数函数']),
      S('composite-differential-mixed-partial','math.exam.6dcf2377bdd4','C',
        'z=u²v+eᵛ，u=x+y，v=xy。点(x,y)=(1,0)处的全微分dz与混合偏导z_xy分别为（ ）。',
        {'A':'2dx，4','B':'2dy，2','C':'2dy，4','D':'dx+dy，3'},
        '该点u=1,v=0，z_u=2uv=0，z_v=u²+eᵛ=2；du=dx+dy,dv=y dx+x dy=dy，因此dz=2dy。将z展开为x³y+2x²y²+xy³+e^{xy}，混合偏导在(1,0)为3+1=4。',
        '先用复合函数全微分得到一阶结果，再展开复合表达式计算混合偏导。',
        '符号微分直接对z=(x+y)²xy+exp(xy)计算梯度与混合偏导，代点得到(0,2)、4。',
        '需要在不同中间变量之间应用链式法则，并区分一阶与混合二阶信息。',
        '中间量v在点上为零不等于其微分为零；指数项仍对混合偏导贡献1。',
        ['全微分与复合函数求导','混合偏导','链式法则']),
      S('two-variable-implicit-second-partial','math.exam.84058ab2e9bb','A',
        '方程z+ln z=x²+y²在(1,0,1)附近确定z=z(x,y)，z>0。该点z_x与z_xx分别为（ ）。',
        {'A':'1，3/2','B':'1，1/2','C':'2，3/2','D':'1，−3/2'},
        'F_z=1+1/z在该点为2，满足隐函数条件。对x求导：(1+1/z)z_x=2x，得z_x=1。再求导：(1+1/z)z_xx−z_x²/z²=2，代入2z_xx−1=2，得z_xx=3/2。',
        '先核查F_z非零，再对隐式关系连续求两次x偏导，保留系数对z的链式求导。',
        '用F_xx+F_zz z_x²+F_z z_xx=0核对，其中F_xx=−2、F_zz=−1，得到3/2。',
        '需要处理二元隐函数的存在条件和含未知偏导的二阶链式关系。',
        '再次求导时1+1/z不是常数，遗漏负平方项会把二阶偏导误算为1。',
        ['隐函数确定的二元函数偏导数','二阶偏导','隐函数条件']),
      S('router-longest-prefix','cs408.cn.topic.0a2961dff8db','D',
        '路由表有10.1.0.0/16→接口1、10.1.2.0/24→接口2、10.1.2.128/25→接口3、默认→接口4。目的地址10.1.2.200与10.1.3.1分别由哪个接口转发？忽略其他策略。',
        {'A':'2、4','B':'1、1','C':'3、2','D':'3、1'},
        '10.1.2.200同时匹配/16、/24、/25，最长前缀/25的范围为10.1.2.128–255，因此选接口3。10.1.3.1只匹配给定的/16和默认路由，选更长的/16接口1。路由表顺序不能替代最长前缀选择。',
        '逐项以掩码检验目的地址，按最大前缀长度选择接口，得到3和1。',
        '将三个前缀转换为地址区间，检查200位于/25上半区而3网段仅属于/16。',
        '需要同时处理多个重叠路由和两个不同目的地址的最长前缀选择。',
        '一个地址可匹配多项路由；必须选择最具体项，不能只取最早匹配路由。',
        ['路由器组成与功能','最长前缀','路由转发']),
      S('wlan-hidden-terminal-rts-cts','cs408.cn.topic.1351211c91cf','B',
        '无线站点A、C均可与B通信，但A、C彼此听不到。两者都向B发送长数据帧。关于碰撞风险及RTS/CTS作用，正确的是（ ）。',
        {'A':'载波监听可保证A、C不会同时发送','B':'A、C形成隐藏终端；RTS/CTS可减少长帧碰撞，但短RTS仍可能碰撞','C':'B发CTS后仅A能听到，C无需等待','D':'RTS/CTS把无线链路改成全双工并彻底消除碰撞'},
        'A无法检测C的发送、C也无法检测A，因此各自可能判断信道空闲并在B处发生碰撞。RTS成功后B广播CTS，A、C都能听到B，被告知预留持续时间而等待。该机制缩短发生碰撞的开销，但RTS竞争本身仍可能冲突。',
        '按给定可听拓扑分析两个发送站的载波监听盲区，再追踪B的CTS覆盖范围。',
        '构造A、C同时发送RTS的反例，验证该机制无法完全消除碰撞但可保护后续长帧。',
        '需要根据无线覆盖关系分析冲突位置和控制帧的预留效果及限制。',
        '听不到对方发送不意味着接收端没有冲突；控制帧预留也不等于全双工。',
        ['无线局域网','隐藏终端','RTS/CTS']),
      S('modulation-coding-net-rate','cs408.cn.topic.1e611d5e4eb0','C',
        '链路采用16-QAM，符号速率2000 Baud；信道编码率为3/4，编码前信息流中每6 bit有1 bit帧同步开销。其有效用户数据速率为（ ）。',
        {'A':'8000 bit/s','B':'6000 bit/s','C':'5000 bit/s','D':'4000 bit/s'},
        '16种符号每符号携带log₂16=4个编码比特，编码后线上比特率2000×4=8000 bit/s。编码率3/4给编码前信息流6000 bit/s；其中用户比例5/6，得到6000×5/6=5000 bit/s。不能将编码率倒除。',
        '依次把符号速率换为编码比特率，再乘编码率和用户有效比例得到5000。',
        '取一秒2000符号共8000编码位，按分组比例精确计数信息位6000及用户位5000。',
        '需要区分符号速率、编码线上比特、编码前信息与有效载荷四个层次。',
        '编码冗余和帧同步均占用链路容量，用户速率不能直接等于波特率乘符号位数。',
        ['编码与调制','编码率','有效速率']),
      S('mail-delivery-versus-synchronization','cs408.cn.topic.64b2c1c54cf3','A',
        '用户通过邮件客户端向另一域发送邮件，并希望在两台设备同步收件箱状态。关于邮件传送和接收的协议分工，正确的是（ ）。',
        {'A':'服务器之间用SMTP传送；发送服务器可借MX记录定位接收域邮件服务；客户端可用IMAP同步服务器邮箱','B':'服务器之间用IMAP传送；SMTP负责客户端同步文件夹','C':'MX记录把收件邮箱所有邮件直接下载到发送方','D':'POP3和IMAP都负责为服务器之间建立SMTP路由'},
        'SMTP承担邮件提交和服务器间邮件传送，跨域发送时服务器可查询DNS MX记录定位目标邮件服务器。IMAP允许客户端访问服务器保留的邮箱并同步文件夹和已读等状态，适合多设备。MX负责定位服务器而非传送邮件正文。',
        '沿发送客户端、发送服务器、目标服务器与接收客户端的通信路径区分协议职责。',
        '分别检验SMTP的传送角色、DNS MX的定位角色和IMAP的服务器状态同步角色。',
        '需要在跨域投递和多设备同步两个场景中区分应用协议与DNS定位。',
        '邮件传送、服务器定位和邮箱同步是不同动作，不能让MX记录承担正文传输。',
        ['电子邮件','SMTP与IMAP','MX记录']),
      S('store-forward-two-packet-pipeline','cs408.cn.topic.658f7cffbc1f','D',
        '源端经两条串行链路向目的端连续发送两个1000 B分组；链路速率依次为1 Mb/s、2 Mb/s，传播时延依次为2 ms、3 ms。中间节点存储转发，无其他队列。首分组及第二分组完整到达目的端的时刻分别为（ ）。',
        {'A':'13 ms、21 ms','B':'17 ms、21 ms','C':'12 ms、20 ms','D':'17 ms、25 ms'},
        '两条链路发送时间分别为8 ms、4 ms。首包在中间节点完整到达为8+2=10 ms，第二链路发送10–14，再传播3 ms，17 ms到达。第二包第一链路发送8–16，18 ms到中间；第二链路已于14 ms空闲，故18–22发送，25 ms到达。',
        '逐分组排出两条链路的发送和传播区间，按完整接收后才能转发确定17和25。',
        '应用start₂=max(complete₁,previous_link₂_finish)的单服务台递推，核对两包结束时刻。',
        '需要区分发送与传播延迟，并分析存储转发和流水线对第二分组的影响。',
        '不能把两个分组的端到端时间完全串行相加，也不能忽略中间节点完整接收条件。',
        ['网络性能指标','存储转发','流水发送']),
      S('byte-stuffing-frame-length','cs408.cn.topic.7507d0c4e02a','B',
        '字节填充协议用0x7E作帧界定、0x7D作转义；数据中的这两种字节转为0x7D后接原字节异或0x20。有效载荷为7E 01 7D。填充后载荷及含首尾界定的帧长为（ ）。',
        {'A':'7D 7E 01 7D 7D，7 B','B':'7D 5E 01 7D 5D，7 B','C':'7D 5E 01 7D 5D，5 B','D':'7E 01 7D，5 B'},
        '0x7E异或0x20为0x5E，编码为7D 5E；01原样保留；0x7D异或0x20为0x5D，编码为7D 5D。载荷变为5 B，首尾各1 B界定，完整帧7 B。解码时去转义并再异或可恢复3 B原载荷。',
        '对每个特殊字节逐项执行转义与异或，再累加两个帧界定字节计算长度。',
        '程序执行编码与逆解码，得到7D5E017D5D并确认可逆恢复7E017D。',
        '需要同时处理透明传输编码、可逆解码和有效载荷与完整帧长度。',
        '转义字节之后必须是异或后的值；载荷长度不包含两端帧界定符。',
        ['数据链路层功能与组帧','字节填充','数据透明性']),
      S('distance-vector-route-change','cs408.cn.topic.8e7e1292d6b4','C',
        '距离向量路由器X到邻居A、B的链路代价分别为2、5；二者广告到目的D的距离分别为4、0。之后A将广告改为1，B仍为0，均可信有效且无其他路径。X初次和更新后的下一跳及距离分别为（ ）。',
        {'A':'A、4；A、1','B':'B、0；A、1','C':'B、5；A、3','D':'A、6；B、5'},
        '距离向量应加上本地到邻居代价。初次经A为2+4=6，经B为5+0=5，选B、5；更新后经A为2+1=3，经B仍5，改选A、3。广告值不是本路由器自身距离。',
        '对每个邻居计算本地链路代价加广告距离，取最小并在更新后重新计算。',
        '将两阶段路径展开为X→邻居→D的两段加和，复核选择从B改为A。',
        '需要在邻居广告更新前后应用距离向量递推，并正确叠加本地边代价。',
        '不能把邻居到目的距离直接当成本地距离，零广告也不代表本地免费到达。',
        ['路由协议（RIP/OSPF/BGP）','距离向量','路径代价']),
      S('synchronous-tdm-framing-rate','cs408.cn.topic.9a617d7c8ebe','A',
        '同步TDM有10路，每帧给每路32 bit，另有16 bit帧开销，帧频率4000帧/s。每路有效速率与总线上速率分别为（ ）。',
        {'A':'128 kb/s，1.344 Mb/s','B':'128 kb/s，1.280 Mb/s','C':'134.4 kb/s，1.344 Mb/s','D':'32 kb/s，1.344 Mb/s'},
        '每路每帧32 bit，速率32×4000=128000bit/s=128kb/s。每帧线上共10×32+16=336bit，总速率336×4000=1344000bit/s=1.344Mb/s。帧开销占用物理速率而不进入每路有效载荷。',
        '分别计算每路时隙数据率与包含同步开销的完整帧发送速率。',
        '汇总十路有效率1.28Mb/s再加开销64kb/s，得到同一线上1.344Mb/s。',
        '需要区分每路有效时隙、全帧容量和共享同步开销的归属。',
        '不能把帧开销均当成用户数据，也不能把32位时隙误作每秒数据量。',
        ['信道划分 MAC','同步TDM','帧开销']),
      S('dijkstra-route-relaxation','cs408.cn.topic.a2e54e0115b9','D',
        '有向图边为A→B:4、A→C:1、C→B:2、B→D:1、C→D:5、D→E:3、C→E:8，权重均正。从A到E的最短路径及总权重为（ ）。',
        {'A':'A→C→E，9','B':'A→B→D→E，8','C':'A→C→D→E，9','D':'A→C→B→D→E，7'},
        '先确定C距离1，用C松弛B得3、D得6、E得9；再确定B距离3并将D改为4；确定D后将E改为7。回溯前驱为A、C、B、D、E，总重1+2+1+3=7。不能一次发现E就停止。',
        '按Dijkstra确定最小暂定距离并逐边松弛，记录B、D、E的改进过程。',
        '枚举所有A到E的简单路径，得到9、9、7、8，取最小值7并核对前驱链。',
        '需要连续松弛并更新前驱，区分首次发现的路径和最终最短路径。',
        'E的首次暂定距离9并未确定，必须等待所有可能改进它的更短节点处理。',
        ['路由算法','Dijkstra','最短路径']),
      S('gbn-loss-discard-retransmission','cs408.cn.topic.ab43d1fb00a1','B',
        'GBN协议发送窗口5，按序发送编号0–4；接收端仅接收按序帧，ACK编号明确表示最后正确按序收到的帧。0成功，1丢失，2、3、4依次到达。随后1超时且没有新确认。接收端最后重复ACK及发送端重传帧数为（ ）。',
        {'A':'ACK1，1帧','B':'ACK0，4帧','C':'ACK4，1帧','D':'ACK0，5帧'},
        '接收0后期待1，1丢失后2–4失序均被丢弃，因此重复确认最后按序收到的0。发送端1超时后按GBN回退重传尚未确认的1–4，共4帧；已确认0无须重传。',
        '逐帧模拟仅接受期待编号的接收状态，最后保持期待1并发送ACK0。',
        '由最早未确认1到已发送最高编号4计算重传闭区间长度4−1+1=4。',
        '需要结合累计确认、失序丢弃和超时回退范围推演双方状态。',
        'ACK编号在题干定义为最后按序帧，不能套用下一期待编号的另一种约定。',
        ['后退 N 帧（GBN）','累计确认','超时重传']),
      S('token-bucket-sustained-peak','cs408.cn.topic.b8e94d7c568d','C',
        '令牌桶容量4 MB、补充速率2 MB/s，初始桶满，发送端有持续积压并以峰值5 MB/s发送，每字节消耗一个字节令牌。不考虑离散粒度。保持峰值至令牌首次耗尽的最长时间和此间输出量为（ ）。',
        {'A':'0.8 s，4 MB','B':'2 s，10 MB','C':'4/3 s，20/3 MB','D':'4/3 s，4 MB'},
        '峰值发送期间令牌以5−2=3 MB/s净消耗，初始4 MB只能支持4/3s。期间输出5×4/3=20/3MB，其中4MB来自初始桶，8/3MB来自持续补充。桶空后不能在无新积累下继续保持5MB/s。',
        '列令牌余额b(t)=4+(2−5)t，求首次零点并计算峰值输出积分。',
        '以输出量等于初始令牌加补充量的守恒方程5t=4+2t核对时间与总量。',
        '需要考虑峰值期间仍持续补充令牌，并区分初始突发额度和实际输出量。',
        '桶容量不等于突发期间全部输出量，因为补充速率会在发送期间继续贡献令牌。',
        ['拥塞控制（网络层视角）','令牌桶','突发整形']),
      S('ftp-passive-nat-direction','cs408.cn.topic.d8296e4021b3','A',
        '客户端位于只允许主动出站连接的NAT后，已从临时端口连接FTP服务器21端口。服务器在被动模式返回数据监听端口50000。客户端获取文件时应如何建立数据连接？',
        {'A':'客户端另用临时端口主动连接服务器50000端口；21端口控制连接继续保留','B':'服务器从20端口主动连接客户端21端口','C':'继续在原21端口控制连接中传送全部文件，无数据连接','D':'服务器50000端口主动连接客户端控制连接的源端口'},
        '被动FTP由服务器提供数据监听地址和端口，客户端主动建立独立数据连接到该端口。原21端口连接继续传控制命令。与主动模式相比，该方向符合只允许出站建立连接的客户端NAT约束。FTP控制和数据连接不同。',
        '根据被动模式的监听方和连接发起方，确定客户端到服务器50000的新连接方向。',
        '对照NAT只允许出站建立的条件，检查新数据连接与保留的控制连接职责。',
        '需要同时理解FTP双连接结构、被动模式端口协商和NAT方向限制。',
        '服务器返回监听端口并不意味着服务器主动连回客户端，文件也不走控制连接。',
        ['FTP 协议','被动模式','NAT连接方向']),
      S('nyquist-shannon-joint-bound','cs408.cn.topic.e09a336289ea','D',
        '理想低通信道带宽3000 Hz，采用16种码元状态，信噪比S/N=15（非dB）。同时考虑奈奎斯特码元限制和香农容量上限，最高理论比特速率不超过（ ）。',
        {'A':'24000 bit/s','B':'16000 bit/s','C':'45000 bit/s','D':'12000 bit/s'},
        '奈奎斯特上限2B log₂M=2×3000×4=24000bit/s。香农容量B log₂(1+S/N)=3000×log₂16=12000bit/s。二者必须同时满足，取较小的12000。增大码元状态数不能突破噪声约束。',
        '分别计算码元状态数量给出的奈奎斯特界与信噪比给出的香农界，再取较小值。',
        '用log₂16=4做精确计算，检验两界为24000和12000且结论满足全部约束。',
        '需要区分无噪声编码界和含噪声信息容量，并联合两个限制确定上限。',
        '题干信噪比是比值15而非15dB，不能再做dB变换或把两个容量相加。',
        ['奈奎斯特与香农定理','联合速率上限','信噪比']),
    ]

def independent_checks():
    import sympy as s
    import ipaddress
    x,z=s.symbols('x z',positive=True); y=s.symbols('y')
    force=1/(1-x)**2-1/(1+x)**2
    assert s.diff(force,x).subs(x,0)==4 and s.factor(force)==4*x/((x-1)**2*(x+1)**2)
    sol=1/(1+s.exp(x)); assert s.simplify(s.diff(sol,x)+sol-sol**2)==0
    assert sol.subs(x,s.log(2))==s.Rational(1,3)
    sol2=1/(1+x); assert s.simplify(s.diff(sol2,x,2)-2*sol2**3)==0
    assert sol2.subs(x,1)==s.Rational(1,2)
    h=s.log(x)-2*(x-1)/(x+1)
    assert s.simplify(s.diff(h,x)-(x-1)**2/(x*(x+1)**2))==0
    expr=(x+y)**2*x*y+s.exp(x*y)
    assert [s.diff(expr,v).subs({x:1,y:0}) for v in (x,y)]==[0,2]
    assert s.diff(expr,x,y).subs({x:1,y:0})==4
    assert (2+1)/2==1.5
    routes=[('10.1.0.0/16',1),('10.1.2.0/24',2),('10.1.2.128/25',3),('0.0.0.0/0',4)]
    best=lambda addr:max(((ipaddress.ip_network(n).prefixlen,p) for n,p in routes if ipaddress.ip_address(addr) in ipaddress.ip_network(n)))[1]
    assert (best('10.1.2.200'),best('10.1.3.1'))==(3,1)
    assert 2000*4*Fraction(3,4)*Fraction(5,6)==5000
    link2finish=0; arrivals=[]
    for firstfinish in (8,16):
        link2finish=max(firstfinish+2,link2finish)+4;arrivals.append(link2finish+3)
    assert arrivals==[17,25]
    raw=bytes((0x7e,1,0x7d));encoded=[]
    for b in raw: encoded.extend((0x7d,b^0x20) if b in (0x7e,0x7d) else (b,))
    assert bytes(encoded)==bytes.fromhex('7d5e017d5d') and len(encoded)+2==7
    assert (min((2+4,'A'),(5+0,'B')),min((2+1,'A'),(5+0,'B')))==((5,'B'),(3,'A'))
    assert (32*4000,(10*32+16)*4000)==(128000,1344000)
    arcs=[('A','B',4),('A','C',1),('C','B',2),('B','D',1),('C','D',5),('D','E',3),('C','E',8)]
    dist={'A':0};prev={};done=set()
    while len(done)<5:
        u=min((k for k in dist if k not in done),key=dist.get);done.add(u)
        for a,b,w in arcs:
            if a==u and dist[u]+w<dist.get(b,999):dist[b]=dist[u]+w;prev[b]=u
    assert dist['E']==7 and [prev[k] for k in ('E','D','B','C')]==['D','B','C','A']
    expect=0;last=-1
    for number in (0,2,3,4):
        if number==expect:last=number;expect+=1
    assert last==0 and len(list(range(expect,5)))==4
    assert Fraction(4,5-2)==Fraction(4,3) and 5*Fraction(4,3)==Fraction(20,3)
    assert (2*3000*4,3000*4)==(24000,12000)
    rows=candidates();assert len(rows)==20
    for r in rows:
        assert all(len(v)>=20 for v in r['reason'].values()),r['request']
        assert len(set(r['output'].options.values()))==4,r['request']
    return {'status':'PASS','candidate_structure_cases':20,'methods':['SymPy derivatives and substitutions','exact fractions','IPv4 prefix membership','packet service timeline','byte encoding','Dijkstra simulation','GBN simulation'], 'paid_model_calls':0}

def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('dry-run','apply'),default='dry-run');args=p.parse_args()
    checks=independent_checks()
    if not BACKUP.is_file() or runner.sha_file(BACKUP)!=BACKUP_SHA256:raise SystemExit('backup_hash_mismatch')
    toc=subprocess.run([r'C:\Program Files\PostgreSQL\18\bin\pg_restore.exe','--list',str(BACKUP)],capture_output=True,timeout=30)
    if toc.returncode or b'TABLE DATA public questions' not in toc.stdout:raise SystemExit('backup_archive_invalid')
    out=OUT_DIR/('preview.json' if args.mode=='dry-run' else 'checkpoint.json')
    if out.exists():raise SystemExit('existing_output_refuse_overwrite')
    runner.BACKUP,runner.BACKUP_SHA256=BACKUP,BACKUP_SHA256
    engine=create_engine(URL.create('postgresql+psycopg',username='postgres',host='127.0.0.1',port=PORT,database=DB_NAME))
    try:
        with Session(engine,expire_on_commit=False) as db:
            try:
                report=runner.run(db,candidate_specs=candidates(),batch_id='13')
                report['status']='DRY_RUN_ROLLED_BACK' if args.mode=='dry-run' else 'BATCH13_APPLIED';report['independent_checks']=checks
                if runner.sha_file(BACKUP)!=BACKUP_SHA256:raise ValueError('backup_changed')
                db.rollback() if args.mode=='dry-run' else db.commit()
            except BaseException:db.rollback();raise
        out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':report['status'],'accepted':len(report['accepted']),'rejected':report['rejected']},ensure_ascii=True),flush=True)
    finally:engine.dispose()

if __name__=='__main__':main()
