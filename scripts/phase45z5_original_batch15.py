"""Batch 15: operating-system boundaries and computer arithmetic/state."""
from __future__ import annotations
import argparse,json,subprocess,sys,struct
from fractions import Fraction
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import phase45z5_original_batch01 as runner
from scripts.phase45z5_original_batch13 import S as prior_s
BACKUP=ROOT/'storage/quality-audits/phase45z5-20261013/originals/batch14/post-batch.dump'
BACKUP_SHA256='37E6B65E6A6D17CDDABE2F787F9BAE13CEF01DBF5A7D2CFF26F2643850FFC4A7'
OUT_DIR=ROOT/'storage/quality-audits/phase45z5-20261013/originals/batch15-retry1'
DB_NAME,PORT,SYSTEM_ID=runner.DB_NAME,runner.PORT,runner.SYSTEM_ID
def S(*args):
 r=prior_s(*args);r['request']=r['request'].replace('z5b13-','z5b15-',1);return r
def candidates():
 return [
  S('producer-lock-before-space-deadlock','cs408.os.topic.86089b973451','C',
    '容量1的有界缓冲区已满，empty=0、full=1、mutex=1。生产者错误执行P(mutex)后再P(empty)；消费者按P(full)、P(mutex)、取数据、V(mutex)、V(empty)。生产者先获得mutex并等待empty后，系统可能出现的情况及修正为（ ）。',
    {'A':'无风险，empty会自行变为1','B':'只会忙等，互斥量不影响消费者','C':'生产者持锁等空槽，消费者等锁无法取数据，可能死锁；生产者先P(empty)再P(mutex)','D':'消费者应删除P(full)，其余不变'},
    '生产者已把mutex减到0，并在empty=0处阻塞；消费者虽可取得full，但在mutex=0处阻塞，无法取出数据来V(empty)。形成彼此等待。应先取得空槽再进入临界区，等待资源时不持有缓冲互斥锁。',
    '按信号量值执行两条路径，指出释放empty所需的消费者操作被mutex阻挡。',
    '绘制生产者等待空槽、消费者等待生产者所持锁的依赖环，再核验修正顺序打破环。',
    '需要同时分析计数资源与互斥资源的取得顺序及阻塞形成的因果依赖。',
    '计数信号量不自行增加，等待空槽时持有消费者必需的锁会阻断资源释放。',
    ['信号量','生产者消费者','资源取得顺序']),
  S('shared-file-mapping-visibility-sync','cs408.os.topic.ad1f1d04dbc6','B',
    'POSIX本地文件上两个进程使用MAP_SHARED映射同一区域。P先修改一个字节，并通过明确的进程同步通知Q，Q随后读取该位置。关于可见性、并发同步和持久化的判断，正确的是（ ）。',
    {'A':'Q必须重新映射才能看到，MAP_SHARED完全禁止共享写','B':'共享映射允许Q读取更新；程序仍需协调并发访问，看到更新不代表磁盘持久化已完成','C':'Q读到更新证明数据已同步写入磁盘，可省掉全部写回操作','D':'MAP_SHARED自动提供任意复合读改写的互斥'},
    '同一文件区域的共享映射用于共享页内容，题干同步建立读取时序，Q可观察更新。但共享内存没有自动提供复合操作互斥，程序仍需锁或其他同步。内存可见性与文件写回持久化不同，更新可先处于脏页状态。',
    '分别分析共享映射的同页可见性、同步通知保证的时序和内存脏页状态。',
    '以两个进程并发复合更新的反例排除自动互斥，并用延迟写回情形排除已持久化推断。',
    '需要区分共享内存可见、访问次序和持久存储三个不同保证。',
    '看见修改不等于磁盘已写回，共享映射也不能替代应用级竞争控制。',
    ['内存映射文件','共享可见性','并发与持久化']),
  S('segmentation-limit-permission','cs408.os.topic.83dc2a1b2ae2','D',
    '段表项给出基址10000、段长1200 B、只读权限；段内偏移从0起，要求偏移严格小于段长。请求①读偏移1000，②读偏移1200，③写偏移1000。各自结果为（ ）。',
    {'A':'①地址11000；②地址11200；③地址11000','B':'①地址1000；②越界；③合法','C':'①地址11000；②合法；③权限错','D':'①地址11000；②越界；③权限错'},
    '①1000<1200且读权限满足，物理地址10000+1000=11000。②偏移等于段长，已超出0–1199的合法范围。③偏移合法但违反只读权限，应报保护异常而非完成写入。',
    '对每次请求分别先做段内范围和访问权限检查，再对合法项加基址。',
    '枚举合法字节区间[10000,11200)，验证上界不包含并独立核对只读权限矩阵。',
    '需要联合段长度边界、地址重定位和读写保护，不能只做基址相加。',
    '段长表示字节数而非最大合法偏移，地址在范围内也不意味着允许写访问。',
    ['段式管理','地址保护','边界条件']),
  S('hardlinks-unlink-open-descriptor','cs408.os.topic.a0be294e1416','A',
    '在支持硬链接的POSIX文件系统中，两个目录项a、b指向同一普通文件inode，进程已打开文件并持有有效描述符。依次unlink(a)、unlink(b)，描述符一直未关闭。此后读取及存储释放的典型行为为（ ）。',
    {'A':'仍可通过描述符读取；最后打开引用关闭后才可释放无链接文件的数据','B':'第一次unlink就删除另一目录项及打开描述符','C':'第二次unlink立即令已打开描述符读操作非法','D':'硬链接数为零后数据永远不能释放'},
    'unlink移除目录项并减少链接数，两个名字删除后已没有路径链接，但已打开的文件引用仍保留对象。进程可继续通过描述符读取。链接和打开引用均不再存在后，文件系统才可释放对象和数据块。',
    '分别跟踪inode的目录链接计数2→1→0与持续存在的打开文件引用。',
    '以路径查找失败但已打开引用仍有效的模型核对读取；再移除最后引用检查释放条件。',
    '需要区分名字、inode对象和打开文件引用，并分析删除名字后的对象寿命。',
    '删除目录项不等于强制关闭已有描述符，硬链接也不是复制一份文件内容。',
    ['目录管理','硬链接','打开文件寿命']),
  S('cached-read-system-call-mode','cs408.os.topic.05dcc6b2951b','C',
    '用户进程调用read读取普通文件，所需数据全部命中页缓存；内核检查和复制顺利完成，期间无阻塞或抢占。关于处理器模式与调度，正确的是（ ）。',
    {'A':'缓存命中意味着read完全不进入内核','B':'每次系统调用必然切换到另一用户进程','C':'仍发生用户态→内核态→用户态，题设无需切换到其他进程','D':'read返回后进程永久保留内核权限'},
    'read是受控系统调用，即使不做磁盘I/O也需进入内核完成描述符、权限及地址检查和复制。内核返回时恢复用户态。模式切换不等于进程调度切换；本题无阻塞或抢占，因此可一直执行同一进程。',
    '沿系统调用入口、缓存读取、内核复制及返回路径分析执行模式。',
    '利用无阻塞和无抢占条件排除进程切换，同时检验访问受保护文件操作仍需内核入口。',
    '需要区分硬件权限模式变化、设备I/O和进程上下文切换三个过程。',
    '页缓存命中只减少设备访问，不会取消系统调用安全边界或自动引起调度。',
    ['系统调用','模式切换','页缓存']),
  S('pipe-inherited-write-end-eof','cs408.os.topic.8fc713e5b56b','B',
    '进程创建匿名管道后fork，父进程关闭自己的写端并在空管道上做阻塞read；子进程仍保留继承的写端但不写数据。此时父read及要让它返回EOF的必要动作是（ ）。',
    {'A':'立即EOF，无需关闭子写端','B':'read可继续阻塞；所有进程持有的写端都关闭后才在空管道上返回EOF','C':'返回字节0；只需子进程关闭读端','D':'返回一个虚构空字节；父关闭读端即可继续读'},
    'EOF要求管道空且不存在任何打开的写端引用。fork后子仍持有写端，因此系统不能认定再无数据生产者，父read等待数据。子关闭写端且没有其他写者后，空管道上的read才返回0长度EOF。',
    '跟踪fork后读写端引用计数，父关闭只减少自己的写引用，子写引用仍阻止EOF。',
    '分别验证空且有写者的阻塞状态与空且无写者的EOF条件，排除把空管道直接当文件结束。',
    '需要分析描述符继承、管道端点引用与阻塞读取的终止条件。',
    '不写数据不等于关闭写端，子进程只关闭读端也不能让父读取获得EOF。',
    ['进程间通信','匿名管道','描述符继承']),
  S('two-dimensional-pagewalk-cost','cs408.os.topic.5aeca0416861','D',
    '简化虚拟机地址转换中，客户采用两级页表，宿主亦采用两级页表；无TLB与页表缓存。客户页表每次读取及最终客户数据读取，都必须先完整读取2个宿主页表项，再读取对应内存位置。忽略其他开销，一次客户虚拟地址数据读取需多少次主存访问？',
    {'A':'3','B':'5','C':'6','D':'9'},
    '客户需读取两个客户页表项及最终数据，共3次客户物理地址访问；每一次都先需2次宿主页表读取，再实际读取目标，成本3。因此总3×3=9次。不能仅把两套页表层数相加，因为客户页表访问本身也要做宿主转换。',
    '展开两个客户页表读取和一个最终数据读取，每个展开为宿主两级加目标一次访问。',
    '建立访存事件树，三条客户访问分支各有三次宿主实际主存访问，合计9。',
    '需要理解嵌套地址转换的乘性代价，并将客户页表读取视为普通客户内存访问。',
    '客户页表项不因用于地址转换就免费访问，简单相加两种层数会遗漏嵌套转换。',
    ['虚拟机','嵌套分页','访存成本']),
  S('inode-direct-indirect-boundaries','cs408.os.topic.75525cc498b3','A',
    '文件inode含12个直接块指针、1个一级间接指针、1个二级间接指针；块大小4 KiB，指针4 B。逻辑数据块从0编号。首次经一级和二级间接访问的块号，以及最多可寻址数据块数为（ ）。',
    {'A':'12、1036；12+1024+1024²','B':'11、1035；12+1024+1024²','C':'12、1036；12+1024+2048','D':'12、1024；12+1024²'},
    '每个间接块容纳4096/4=1024个指针。直接数据块号0–11；一级间接覆盖12–1035，二级第一块1036。二级有1024个下级指针块各指1024个数据块，容量1024²；总数据块容量12+1024+1024²。指针块不计为文件数据块。',
    '按各寻址层级的容量建立连续逻辑区间，再累加直接、一级和二级数据容量。',
    '以每块1024个指针独立计算树的叶子数据块数，核对两个边界和平方项。',
    '需要同时分析指针宽度、索引层次和零基逻辑块区间的衔接。',
    '二级间接数据容量是指针数平方而非两倍，间接索引块不能算成文件数据块。',
    ['文件物理结构','多级索引','逻辑块边界']),
  S('bitmap-word-index-offset','cs408.os.topic.b5a459680f3e','C',
    '空闲空间位图每32 bit存为一字，块号和字号从0开始，字内位0为最低位，1表示占用。分配块1000应修改哪个字、哪个位；保持其他位不变的置位掩码为（ ）。',
    {'A':'字32、位8；1<<8','B':'字31、位9；1<<9','C':'字31、位8；1<<8','D':'字31、位8；清空整字'},
    '1000=31×32+8，故字号31、位号8。为保留其他分配状态，使用该字与(1<<8)按位或来置位。块号0对应字0位0，不能加一；清空整字会破坏其余31个块的分配信息。',
    '对块号执行整除和取余计算字号、位号，再按位或构造只改变一位的更新。',
    '把该字的所有32个位逐项列为块992–1023，确认1000对应第8位且掩码仅一个1。',
    '需要将全局块编号映射到机器字与字内位，并保证局部更新不破坏其他状态。',
    '编号起点和最低位约定已明确，不能套用一基公式；整字覆盖会损坏无关块信息。',
    ['外存空闲空间管理','位图字索引','局部位更新']),
  S('round-robin-real-context-switches','cs408.os.topic.e73a5b633dc7','B',
    '两CPU密集进程A、B同时就绪，所需CPU时间5 ms、7 ms；先A，时间片3 ms。实际从一个进程切到另一个开销0.2 ms，首次调入和最终退出不计；只有B剩余时续用时间片不算进程切换。完成全部工作的实际切换次数及总历时为（ ）。',
    {'A':'4次，12.8 ms','B':'3次，12.6 ms','C':'2次，12.4 ms','D':'3次，12 ms'},
    '执行片段为A3、B3、A2（完成）、B3、B1（完成）。不同进程间切换A→B、B→A、A→B共3次，最后B续用没有换进程。有效工作12 ms加3×0.2=0.6 ms，历时12.6 ms。',
    '按时间片递减剩余CPU量并记录实际进程身份变化，区分时间片结束与上下文切换。',
    '以CPU工作量5+7加真正切换开销计算历时，并用片段序列相邻身份计数复核。',
    '需要跟踪就绪队列、剩余执行量和调度开销，而非将所有时间片边界算作切换。',
    '只有一个可运行进程时继续执行不需切往另一进程，不能多算最后一次时间片开销。',
    ['上下文切换','时间片轮转','调度开销']),
  S('secded-syndrome-even-parity','cs408.co.topic.e2880988de52','D',
    '8位数据采用标准Hamming SEC加一位总奇偶校验构成SECDED，且最多发生两位错误。Hamming校验位数取最小r使2ʳ≥8+r+1。接收结果Hamming综合征为5，总校验表现为偶数错误。总码长及应对为（ ）。',
    {'A':'12位；纠正第5位','B':'13位；纠正第5位','C':'13位；仅总奇偶位错误','D':'13位；检测双错，不按综合征直接纠正'},
    'r=3时8<12不够，r=4时16≥13，因此基础码8+4=12位，加总校验为13位。非零综合征说明基础码校验不符，而总错误奇偶为偶，在至多两错假设下应判双位错。单错才对应奇数总校验，故不能误纠第5位。',
    '先求冗余位数，再用SECDED的综合征与总奇偶联合判定错误类型。',
    '用错误数最多2的分类表核对：非零综合征加偶数错误为双错，应报告不可单错纠正。',
    '需要区分基础Hamming定位信息和总奇偶位提供的错误数奇偶信息。',
    '非零综合征不能单独触发纠正，双错时按综合征翻转会引入第三位错误。',
    ['校验码','SECDED','双错检测']),
  S('relative-address-signed-displacement','cs408.co.topic.0eeff5219603','A',
    '某CPU分支指令规定目标=下一条指令地址+符号扩展后的16位位移，位移以字节计。下一条地址0x1004，位移字段0xFFFC。分支目标及位移解释为（ ）。',
    {'A':'0x1000，−4 B','B':'0x11000，65532 B','C':'0x0FF4，−16 B','D':'0x1008，+4 B'},
    '16位字段0xFFFC按补码为65532−65536=−4，扩展后加下一条地址0x1004得到0x1000。题干位移为字节，不能再乘4；也不能按无符号加65532。',
    '先将16位补码字段解释为有符号整数，再按明确的PC相对地址基准求和。',
    '以0xFFFC的符号位和二进制补码值核对−4，计算目标和下一条之差为−4字节。',
    '需要区分指令地址基准、位移符号扩展和位移单位，才能得到正确目标。',
    '当前指令地址与下一条地址不是同一基准，字节位移不能套用字位移缩放。',
    ['寻址方式','PC相对寻址','符号扩展']),
  S('direct-cache-tag-index-conflict','cs408.co.topic.ba9896acc602','C',
    '32位字节地址，直接映射Cache数据容量4 KiB、块32 B。地址分解中的标记/行索引/块内偏移位数，以及地址0x0010和0x1010是否映射同一行，为（ ）。',
    {'A':'20/7/5；不同一行','B':'19/8/5；同一行','C':'20/7/5；同一行且标记不同','D':'20/5/7；同一行且标记相同'},
    '块偏移log₂32=5位；行数4096/32=128，索引7位；标记32−7−5=20位。两地址相差4096 B，即128块，块号模128相同；各自标记不同，因此访问会形成直接映射冲突。',
    '从容量和块宽计算行数及地址位段，再以块号取模比较两地址映射。',
    '按地址右移5位取低7位计算两个行索引均为0，右移12位标记分别为0和1。',
    '需要将Cache容量转换成行数，并验证地址冲突与标记区别。',
    '容量以字节给出，索引位数不能直接取log₂容量；映射同一行不等于同一数据块。',
    ['Cache 映射方式','地址位段','冲突替换']),
  S('binary32-rounding-cancellation','cs408.co.topic.c08c6a818873','B',
    '每一步均以IEEE754 binary32的最近值舍入、偶数规则计算并存储，禁止更高精度中间量。a=2²⁴，先计算b=a+1，再计算c=b−a。c及原因正确的是（ ）。',
    {'A':'1；浮点总能精确保留整数差','B':'0；a+1恰在相邻可表示数中点，舍入到偶数有效尾数对应的a','C':'2；所有中点都向上舍入','D':'−1；浮点减法改变加法误差的符号'},
    'binary32有24位有效精度，在2²⁴附近相邻较大可表示数间隔2。2²⁴+1位于2²⁴与2²⁴+2正中，偶数舍入选择2²⁴。因此b=a，后续精确相减得c=0，虽真实数学表达式结果为1。',
    '按该指数区间的有效位宽求可表示间隔，再应用最近偶数舍入和逐步存储条件。',
    '把a+1先编码解码为binary32，再独立执行binary32减法，参考结果为0。',
    '需要结合有效位精度、半ULP中点舍入和两步运算的存储语义。',
    '不能代数化简整式为1再当成机器结果；题干要求每步舍入且排除扩展精度。',
    ['浮点数运算','最近偶数舍入','消去误差']),
  S('page-number-frame-offset-compose','cs408.co.topic.279ec6c06fe1','D',
    '虚拟地址32位、物理地址24位、页大小4 KiB。虚拟地址0x12345DEF的页表项有效且物理页框号0xABC，访问权限满足。其虚拟页号、页内偏移和物理地址分别为（ ）。',
    {'A':'0x1234、0x5DEF、0xABC5DEF','B':'0x12345、0xDEF、0x12345ABC','C':'0x12345、0xDEF、0xABDDEF','D':'0x12345、0xDEF、0xABCDEF'},
    '页大小2¹²，低12位为偏移0xDEF，上20位为虚拟页号0x12345。24位物理地址除偏移12位外还有12位页框号，0xABC恰能容纳。物理地址=(0xABC<<12)|0xDEF=0xABCDEF，偏移保持不变。',
    '按页大小拆解虚拟地址，再将已给有效页框号与原偏移拼接。',
    '用整数除4096和取余核对页号偏移，再按框号乘4096加偏移计算物理地址。',
    '需要分析虚实地址各自位宽、页号转换和保持不变的页内偏移。',
    '页框号不是完整物理地址，拼接前必须左移12位；不能保留原虚拟页号。',
    ['虚拟存储器（计组视角）','页框转换','页内偏移']),
  S('byte-interrupt-versus-dma-block','cs408.co.topic.e31ff79f7b2e','A',
    '设备1 MB/s，CPU100 MHz。逐字节中断每字节一次；DMA每1000 B块完成中断一次。两方式每次中断服务均100周期，忽略DMA设定及其他开销。中断服务占CPU的理论比例依次为（ ）。',
    {'A':'100%，0.1%','B':'10%，0.1%','C':'100%，1%','D':'1%，0.1%'},
    '逐字节每秒10⁶次中断，需10⁸周期，占100MHz CPU理论全部周期。DMA每秒10⁶/1000=1000次完成中断，需10⁵周期，占10⁸的0.001，即0.1%。该估计不宣称逐字节方式还能承担其他工作。',
    '将吞吐转换为两种中断频率，再计算服务周期预算与CPU总周期的比值。',
    '按每字节与每块的服务时间换算，确认DMA减少1000倍中断次数及相同比例开销。',
    '需要区分字节传输事件和DMA块完成事件，并量化中断频率对CPU的负担。',
    'DMA并非每字节仍打一次中断；比例转成百分数时不能漏乘100。',
    ['I/O 接口','DMA完成中断','CPU服务预算']),
  S('forest-left-child-right-sibling-count','cs408.ds.topic.1d253ee449a8','C',
    '森林根按顺序为A、F、H；A的孩子为B、C，B的孩子为D、E，F的孩子为G，H的孩子为I、J，未列结点为叶子。按左孩子右兄弟转换成二叉树，左链接和右链接数分别为（ ）。',
    {'A':'7、2','B':'3、6','C':'4、5','D':'5、4'},
    '每个有孩子的结点贡献一条左孩子链接：A→B、B→D、F→G、H→I，共4。兄弟链贡献B→C、D→E、I→J，以及根兄弟A→F、F→H，共5。二叉树10结点总9条边，与4+5一致。',
    '分别列出每个父结点的首孩子链接及每组相邻兄弟链接，包括森林根兄弟。',
    '程序构造左孩子和右兄弟映射并计数，再用10结点树有9条边的守恒检查。',
    '需要区分原树父子边与转换后两类链接，并处理森林多个根的兄弟链。',
    '根之间也需右兄弟链接；原树的每条父子边并不都变成二叉树左链接。',
    ['森林与二叉树的转换','左孩子右兄弟','链接计数']),
  S('disk-random-then-contiguous-transfer','cs408.co.topic.4497bb39baed','B',
    '磁盘7200转/分，平均寻道5 ms，平均旋转等待取半周；连续传输速率128 MB/s（十进制）。一次随机定位读取256 kB，紧接着读取物理连续且已位于磁头下的下一段256 kB，第二段不再寻道或等待旋转。两段各自耗时为（ ）。',
    {'A':'5 ms，2 ms','B':'67/6 ms，2 ms','C':'67/6 ms，67/6 ms','D':'43/3 ms，2 ms'},
    '一周时间60000/7200=25/3 ms，平均旋转等待25/6 ms。256000 B以128000000 B/s传输需2 ms。第一段5+25/6+2=67/6 ms；题设下一段已连续就位，第二段只有2 ms传输时间。平均半周不能算成完整一周。',
    '分别计算寻道、平均半周和传输三项，再依据连续读取条件删除第二段的定位开销。',
    '以精确有理数计算旋转周期和字节速率换算，核对两阶段成本为67/6和2毫秒。',
    '需要综合磁盘机械定位、旋转周期及连续数据传输，并识别后续读取条件变化。',
    'kB与MB在题中明确为十进制，第二段连续读取不能重复叠加平均随机定位开销。',
    ['磁盘存储器','旋转时延','连续传输']),
 ]

def independent_checks():
 from collections import deque
 assert (10000+1000,1000<1200,1200<1200)==(11000,True,False)
 assert (2+1)*(2+1)==9
 assert (12,12+4096//4,12+1024+1024**2)==(12,1036,1049612)
 assert divmod(1000,32)==(31,8) and (1<<8).bit_count()==1
 rem={'A':5,'B':7};queue=deque(['A','B']);trace=[]
 while queue:
  who=queue.popleft();duration=min(3,rem[who]);trace.append((who,duration));rem[who]-=duration
  if rem[who]:queue.append(who)
 switches=sum(trace[i-1][0]!=trace[i][0] for i in range(1,len(trace)))
 assert switches==3 and sum(v for _,v in trace)+Fraction(1,5)*switches==Fraction(63,5)
 r=0
 while 2**r<8+r+1:r+=1
 assert r==4 and 8+r+1==13
 signed=0xfffc-2**16;assert signed==-4 and 0x1004+signed==0x1000
 assert (32-7-5,4096//32, (0x10>>5)&127,(0x1010>>5)&127,0x10>>12,0x1010>>12)==(20,128,0,0,0,1)
 f32=lambda value:struct.unpack('!f',struct.pack('!f',value))[0]
 a=f32(2**24);b=f32(a+1);assert f32(b-a)==0
 assert (0x12345def>>12,0x12345def&4095,(0xabc<<12)|0xdef)==(0x12345,0xdef,0xabcdef)
 assert (Fraction(1_000_000*100,100_000_000),Fraction(1000*100,100_000_000))==(1,Fraction(1,1000))
 children={'A':['B','C'],'B':['D','E'],'F':['G'],'H':['I','J']};roots=['A','F','H']
 left=sum(bool(v) for v in children.values());right=sum(len(v)-1 for v in children.values())+len(roots)-1
 assert (left,right)==(4,5)
 assert Fraction(60_000,7200)/2+5+Fraction(256_000,128_000_000)*1000==Fraction(67,6)
 rows=candidates();assert len(rows)==18
 for row in rows:
  assert all(len(v)>=20 for v in row['reason'].values()),row['request']
  assert len(set(row['output'].options.values()))==4,row['request']
 return {'status':'PASS','candidate_structure_cases':18,'methods':['exact address and bit-field calculations','round-robin queue simulation','binary32 reference encode/decode','forest conversion counts','resource and descriptor state analysis'],'paid_model_calls':0}

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
    report=runner.run(db,candidate_specs=candidates(),batch_id='15');report['status']='DRY_RUN_ROLLED_BACK' if args.mode=='dry-run' else 'BATCH15_APPLIED';report['independent_checks']=checks
    if runner.sha_file(BACKUP)!=BACKUP_SHA256:raise ValueError('backup_changed')
    db.rollback() if args.mode=='dry-run' else db.commit()
   except BaseException:db.rollback();raise
  out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  print(json.dumps({'status':report['status'],'accepted':len(report['accepted']),'rejected':report['rejected']},ensure_ascii=True),flush=True)
 finally:engine.dispose()
if __name__=='__main__':main()
