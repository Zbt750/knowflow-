"""Correct mapping/depth issues found in the new batches, preserving identities."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from scripts import phase45z5_sample_upgrade_batch01 as runner
from scripts.phase45z5_sample_upgrade_batch02 import row
OUT=ROOT/'storage/quality-audits/phase45z5-20261013/new-question-refinement/batch01'
BACKUP=ROOT/'storage/quality-audits/phase45z5-20261013/sample-upgrades/batch02/post-upgrade.dump'
SHA='C72BF5A5135CB8CE159BF8D522FFDAD9EEA8E3025F7104B3F84B0B8AAC469865'

def specs():
    return [
        row('e256d49d-b6d4-56b2-bcce-248d195bf284','math.exam.e90535214807','C',
            '实数a、b使lim(x→0)[ln(1+x)+ax+bx²]/(sin x−x)=−2，则(a,b)为（ ）。',
            {'A':'(1,1/2)','B':'(−1,−1/2)','C':'(−1,1/2)','D':'(−1,1)'},
            '分母为−x³/6+o(x³)，分子为(1+a)x+(b−1/2)x²+x³/3+o(x³)。有限性首先要求a=−1、b=1/2，消去一阶及二阶项；此时三阶系数比为(1/3)/(−1/6)=−2，满足目标。该题需要匹配三阶分母，不能只处理到二阶。',
            [('third_order_matching','分母首项阶数为3，分子一、二阶系数须同时消失，得到a=−1、b=1/2。'),('symbolic_limit_check','代入参数后分子首项x³/3与分母−x³/6相比得−2，满足完整目标条件。')],
            [('lower_orders','先使分子两个低于分母阶次的项为零，唯一确定参数。'),('third_order_ratio','保留对数与正弦三阶项，验证系数比恰为−2。')],
            ('需比较三阶分母与含两个自由参数的分子，逐阶处理有限性及目标值。','依次消去一阶和二阶项，最后比较三阶系数检查所求极限。','对数二阶符号与正弦三阶负号会分别造成参数和极限符号错误。','补充三阶匹配与参数条件的综合考查角度，避免同一二阶模板换数字。'),['参数极限','三阶匹配','有限性条件']),
        row('0b7e5edc-1a26-5f07-aeb7-31cc6b266f8e','math.exam.4a56bd52caf7','A',
            '由加权积分中值定理，存在ξ∈(0,1)使∫₀¹x²e^x dx=ξ²∫₀¹e^x dx。该ξ等于（ ）。',
            {'A':'√[(e−2)/(e−1)]','B':'(e−2)/(e−1)','C':'√[(e−1)/(e−2)]','D':'1/2'},
            '权函数e^x连续且严格正，x²在[0,1]连续递增，因此加权平均对应唯一ξ∈(0,1)。两次分部积分给∫₀¹x²e^x dx=[e^x(x²−2x+2)]₀¹=e−2，权积分为e−1。所以ξ²=(e−2)/(e−1)，取区间内正平方根。',
            [('weighted_mean_integral','用两次分部积分分别计算分子e−2与权积分e−1，得到ξ²的精确比值。'),('antiderivative_and_uniqueness','对e^x(x²−2x+2)求导得x²e^x；比值介于0和1，x²严格递增确定唯一正根。')],
            [('integral_ratio','积分平均值等于(e−2)/(e−1)，权函数严格正。'),('point','ξ必须在(0,1)，因此对ξ²的比值取唯一正平方根。')],
            ('结合带正权积分中值公式、两次分部积分和中值点的唯一性。','计算两个定积分之比，再借助区间及单调性选择平方根分支。','把ξ²当作ξ或取比值倒数会错；中值点不必是区间中点。','在真实积分平均值知识点内连接定理条件、积分计算与点值确定。'),['加权积分中值','分部积分','中值点唯一性']),
        row('68beab8a-5d99-5851-839e-df469f22fc78','math.exam.ceb4bcf4246a','B',
            '容器在高度y处的水平截面积为A(y)=1+y²平方米，液体充满0≤y≤1米，单位体积重力为12000N/m³。将全部液体泵到高度2米的出口，忽略损耗，所做功为（ ）。',
            {'A':'18000J','B':'23000J','C':'24000J','D':'30000J'},
            '厚dy的液层体积为(1+y²)dy，重力为12000(1+y²)dy，提升距离2−y。功为12000∫₀¹(1+y²)(2−y)dy。展开后积分为2−1/2+2/3−1/4=23/12，因此W=23000J。面积随高度变化，不能先把所有液体都按单一平均高度提升。',
            [('horizontal_layer_work','逐层体积、重量与提升距离相乘建立功积分，准确保留高度相关的截面积。'),('exact_polynomial_integration','多项式积分2−1/2+2/3−1/4=23/12，乘12000得23000J。')],
            [('model','每层重力12000(1+y²)dy，提升距离2−y，二者相乘后积分。'),('evaluation','被积多项式逐项积分为23/12，功为23000J。')],
            ('需将变截面积液体分层建模，结合体积、重力与提升距离计算累积功。','先建立每层重量和位移，再展开多项式进行精确积分。','截面积不是常数，液体质心也不在几何中点，直接套平均高度会错。','通过泵水物理场景训练定积分模型建立及变量相关因素的联合处理。'),['定积分物理应用','分层做功','变截面积']),
        row('252d1038-cf82-505d-948b-e296287e48e9','cs408.os.topic.8266516a5539','D',
            '目标模块装入基址为4000H，函数相对入口02AH；一条PC相对分支指令位于模块偏移010H，长度4字节，位移按目标地址减下一指令地址计算。入口绝对地址和该分支位移分别为（ ）。',
            {'A':'402AH，2AH','B':'402AH，1AH','C':'4014H，16H','D':'402AH，16H'},
            '函数入口绝对地址为4000H+002AH=402AH。分支指令位于4010H，下一指令地址为4014H，故相对位移402AH−4014H=0016H。PC相对位移中的装入基址相减抵消，不应将物理地址本身当作位移。',
            [('absolute_and_pc_relative_relocation','分别计算入口402AH与下一指令4014H，两者相减得16H。'),('base_cancellation_crosscheck','直接在模块偏移上算02AH−(010H+4)=016H，与装入后的绝对地址差相同。')],
            [('absolute_address','模块基址与函数偏移相加确定入口402AH。'),('pc_relative','指令结束地址需加4字节，目标减该地址得到位移16H。')],
            ('需区分绝对重定位与PC相对重定位，并正确采用下一指令地址作为基准。','先确定绝对入口及指令结束位置，再计算相对位移并验证基址抵消。','从当前指令地址而非下一指令地址减目标会多出4字节。','结合装入地址转换、不同重定位语义和指令长度解释位移计算。'),['程序装入','绝对重定位','PC相对重定位']),
    ]

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    output=OUT/('checkpoint.json' if args.apply else 'preview.json')
    if output.exists():raise SystemExit('output_exists')
    if hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper()!=SHA:raise SystemExit('backup_hash_mismatch')
    runner.OUT=OUT;runner.specs=specs
    engine=create_engine('postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test')
    try:
        with Session(engine,expire_on_commit=False) as db:
            report=runner.run(db,args.apply);db.commit() if args.apply else db.rollback()
        OUT.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'status':report['status'],'upgraded':len(report['results'])}))
    finally:engine.dispose()
