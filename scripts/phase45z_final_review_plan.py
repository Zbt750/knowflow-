"""Encode the completed content review, without changing the database."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
BASE=ROOT/'storage/quality-audits/phase45z5-20261013/final-candidate'
OUT=ROOT/'storage/quality-audits/phase45z-final-20261013'
KEEP={
6:'由偏序约束推导两种拓扑序，保留为拓扑计数的必要基础。',7:'两次积分和内外变量区分是该计算节点的必要基础，与区域变换综合题衔接。',
9:'先检查0/0条件，再执行商法则及求极限，保留为洛必达适用性基础。',16:'通过互异特征值对应向量无关证明可对角化，连接谱信息与基的构造。',
25:'分析用户权限与特权执行的因果边界，保留为运行模式保护的必要基础。',39:'将多个树分量各自的边数求和，训练森林分量约束而非记忆单树公式。',
49:'从特征方程分解出不同实根，再构造两个独立解，保留实根分支基础。',64:'分别识别线程私有上下文和进程共享存储，训练资源作用域。',
70:'需要识别指数共振、选择x倍试探并代回求系数，具有独立方法选择价值。',73:'需要区分独立open与dup的打开文件描述和偏移状态，保留文件寿命语义考点。',
79:'由左右子树约束递归推出严格有序，并使用互异关键字前提。',80:'同时使用无向性和无自环条件推出对称性与对角元素，保留图表示基础。',
84:'不将合同与相似混淆，明确可逆变换的惯性不变量，为二次型分类作必要基础。',87:'联合零硬链接和零打开引用两个条件分析数据回收，非单一删除动作。',
89:'比较四个必要条件及可剥夺与不可剥夺的相反关系，保留死锁条件基础。',
92:'从逆序输入逐趟移动量建立等差和，说明最坏复杂度的来源。',93:'联用递归深度和逐层总工作量，推导nlogn而非只引用标签。',
96:'同时分析有序排除与随机访问成本，是查找算法选择的必要条件辨析。',116:'分析链表中点定位成本，说明有序性不足以保证对数时间。',
122:'根据多对一映射推导阻塞传播，区分用户线程与内核调度实体。',123:'用带标签记录执行交换并构造不稳定反例，具有操作推理价值。',
127:'根据区域限制建立二维体积积分，包含内层和外层计算；保留几何建模基础。',129:'求驻点后比较端点和内部候选，训练闭区间全局最值方法。',
137:'有环的顺序约束无法线性化，保留拓扑排序存在性的必要基础。',139:'建立n−1与0的退化划分递推，解释最坏复杂度。',
146:'区分局部邻域、全域以及二阶导充分条件，是极值定义的必要逻辑基础。',152:'由共轭虚根构造实三角解，是常系数方程不同根型的独立覆盖。',
156:'二维配方需同时定位两个变量并证明全局下界，保留极值计算基础。',157:'通过平方分解和同时为零条件证明严格正定，不把半正定与正定混同。',
163:'从等待解除推到就绪，再与实际调度分离，训练事件与状态边界。',166:'需要排序服务次序、累计等待并求平均，包含明确的调度轨迹。',
172:'Hessian异号对应两条方向的一增一减，保留鞍点判别的必要反例。',174:'两次积分使用两项独立初值确定常数，保留降阶恢复过程基础。',
175:'先发现线性关系，再证明保留的两向量无关，分别给秩的上下界。',186:'从一次性资源申请推导请求并保持被破坏，训练预防机制与条件的对应。',
190:'分析环导致无限递归的风险和visited的不变量，保留搜索终止性基础。',
195:'对三角共振选择x倍试探并验证二阶方程，独立覆盖复根共振。',196:'负指数共振时导数带负号，必须计算而不能机械沿用正指数系数。',
200:'将三循环分解成两次对换，利用奇偶性求行列式，保留置换复合基础。',204:'用像空间包含于核空间及秩零度定理给出上界，构造秩1例子可达。',
205:'必须比较带对数的端点阶次，并另查临界p=−1，保留反常积分参数基础。',
206:'先求中间偏导，再结合两条复合路径的变化率，训练多元链式法则。',
208:'区分无权边数最短与权值最短，依据BFS分层不变量推理。',209:'明确阶的定义与非根限制，保留B树边界约定基础。',
210:'分析有序输入每趟一次比较的成本，与最坏逆序轨迹形成必要对照。',211:'区分合并暂存数组与递归栈，保留数组归并空间开销基础。',
215:'同进程切换仍保存寄存器，但地址空间通常不切换，训练两类开销的区别。',
216:'联合驻留位和写权限辨别保护异常而非普通缺页，具有条件辨析价值。',
219:'先对阶相加再规范化，保留浮点基础流程，不与舍入误差题混同。',220:'更新尾指针且保持头结点闭环，训练删除后结构不变量。',
222:'结合有序叶链和查询停止条件选择范围扫描，保留B+树机制基础。',
227:'将末元素补根，再选择较大孩子下调，训练堆结构恢复过程。',
230:'分析接口封装与层间开销的差异，保留操作系统结构的必要架构基础。',
232:'分别计算索引与块内两级查找成本，不能只估算其中一层。',
238:'根据局部置换范围分析两个进程的页框隔离，具有明确系统条件。',
239:'同时证明存在性和严格单调的唯一性，是根个数判断的完整方法。',
240:'使用递推归纳证明所有正整数幂的结果，保留矩阵结构不变量基础。',
242:'分离变量、确定初值常数并恢复解，作为非线性分离方程基础；与全局线性解区别。',
243:'通过左右积分差商说明积分函数可连续但不可导，保留连续性前提反例。',
244:'将两列右端分别限制到列空间，推导参数充要条件。',
245:'利用线性算子相减抵消同一右端，保留齐次与非齐次解结构基础。',
248:'分别检验函数极限和左右导数，保留连续不能推出可导的必要反例。',
250:'既需证明下界又需检查等号可达条件，保留最优不等式基础。',
252:'两侧有限极限不相等，区分跳跃与可去间断，保留间断分类基础。',
253:'以二阶导为零但两侧不变号构造反例，防止把必要条件当充分条件。',
255:'选择行列式检验三向量，非零结果给无关性，保留线性无关判定基础。',
258:'结合正定义域和导数变号证明全局最小，训练方法及范围条件。',
262:'区分ISA的软件可见兼容性和微体系结构性能，实现层次辨析。'}
FOUNDATION={6,7,9,16,25,39,49,64,79,80,84,89,137,146,152,172,190,209,211,219,222,230,240,242,245,248,250,252,255}
EXTRA_SAMPLE_RETIRE={13,16,19,27,45,50,52,69,72,73,96,99}
SAMPLE_FOUNDATION={1,26,32,34,35,64,68,93,98}

def main():
 from scripts.phase45z_final_upgrades import final_specs,verify
 verify()
 if (OUT/'review-262.json').exists():raise SystemExit('review_exists_refuse_overwrite')
 OUT.mkdir(parents=True,exist_ok=True)
 source=BASE/'remaining-depth-review.json';rows=json.loads(source.read_text(encoding='utf-8'))
 formal=json.loads((BASE/'formal-questions.json').read_text(encoding='utf-8'))
 sample=json.loads((BASE/'fresh-original-sample-100.json').read_text(encoding='utf-8'))['questions']
 upgrades={r['id']:r for r in final_specs()}
 raw_by_id={r['id']:r for r in formal}
 decisions=[]
 for index,row in enumerate(rows,1):
  qid=row['id']
  if qid in upgrades:choice='UPGRADE';reason=upgrades[qid]['reason']['knowledge_depth'];depth='SUBSTANTIVE_REPAIR'
  elif index in KEEP:choice='KEEP';reason=KEEP[index];depth='FOUNDATION_EXCEPTION' if index in FOUNDATION else 'INTERMEDIATE_REASONING'
  else:choice='RETIRE';reason='本题的独立考核步骤仅为：'+row['explanation']+' 当前节点已有覆盖该核心方法的正式题，本题不提供额外条件分析或过程验证，退出重复的低深度考核要求。';depth='LOW_DEPTH_REDUNDANT'
  decisions.append({'index':index,'question_id':qid,'node_code':row['node_code'],'knowledge_point':row['node_name'],
   'decision':choice,'depth':depth,'reasoning_process':row['explanation'],'training_value_rationale':reason,
   'foundation_exception':depth=='FOUNDATION_EXCEPTION','duplicate_claim':False,
   'reviewer_kind':'AI_ASSISTED_CONTENT_REVIEW','human_verified':False,
   'source_fields':{k:row[k] for k in ('stem','options','answer','explanation')}})
 by_id={r['question_id']:r for r in decisions};sample_decisions=[]
 for index,row in enumerate(sample,1):
  if row['id'] in upgrades:decision='UPGRADE';depth='SUBSTANTIVE_REPAIR';reason=upgrades[row['id']]['reason']['knowledge_depth']
  elif row['id'] in by_id:
   source_decision=by_id[row['id']];decision='PASS' if source_decision['decision']=='KEEP' else source_decision['decision'];depth=source_decision['depth'];reason=source_decision['training_value_rationale']
  elif index in EXTRA_SAMPLE_RETIRE:decision='RETIRE';depth='LOW_DEPTH_REDUNDANT';reason='逐题读取后，仅有直接公式代入、单一概念或与已保留考核同方法数值替换，未提供独立训练角度。该题退出规定集合，记录保留。'
  else:decision='PASS';depth='FOUNDATION_EXCEPTION' if index in SAMPLE_FOUNDATION else 'INTERMEDIATE_OR_ABOVE';reason='完整推理过程为：'+row['explanation']+' 条件辨析和上述推导是本题保留的训练内容；不依据difficulty标签。'
  sample_decisions.append({'index':index,'question_id':row['id'],'node_code':row['node_code'],'knowledge_point':row['node_name'],
    'decision':decision,'depth':depth,'reasoning_process':row['explanation'],'training_value_rationale':reason,
    'source_fields':{k:row[k] for k in ('stem','options','answer','explanation')},'reviewer_kind':'AI_ASSISTED_CONTENT_REVIEW','human_verified':False})
 retire={r['question_id'] for r in decisions if r['decision']=='RETIRE'}|{r['question_id'] for r in sample_decisions if r['decision']=='RETIRE'}
 for d in decisions+sample_decisions:
  if d['decision']!='RETIRE':continue
  peers=[r for r in formal if r['node_code']==d['node_code'] and r['id'] not in retire and r['id']!=d['question_id']]
  if not peers:raise RuntimeError('retire_would_leave_node_without_peer:'+d['node_code'])
  peer=max(peers,key=lambda r:len(r['stem'])+len(r['explanation']))
  d['retained_coverage_question_id']=peer['id'];d['retained_coverage_stem']=peer['stem']
  d['retirement_is_quality_decision_not_semantic_duplicate_assertion']=True
 payload={'source_artifact_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'reviewed_count':len(decisions),'results':decisions}
 (OUT/'review-262.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (OUT/'review-100.json').write_text(json.dumps({'source_seed':451015,'reviewed_count':100,'results':sample_decisions},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (OUT/'peer-coverage.json').write_text(json.dumps([{'retiring':d['question_id'],'node':d['knowledge_point'],'retained':d['retained_coverage_question_id'],'stem':d['retained_coverage_stem']} for d in decisions+sample_decisions if d['decision']=='RETIRE'],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 from collections import Counter
 print(json.dumps({'262':dict(Counter(d['decision'] for d in decisions)),'100':dict(Counter(d['decision'] for d in sample_decisions)),'unique_retire':len(retire),'unique_upgrades':len(upgrades)},ensure_ascii=True))
if __name__=='__main__':main()
