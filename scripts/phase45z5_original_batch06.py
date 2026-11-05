"""Sixth offline-authored public-original batch for the isolated Z5 database."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.phase45z5_original_batch01 import run as run_batch, sha_file  # noqa: E402
from scripts.phase45z5_original_batch02 import item  # noqa: E402

BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/sample-upgrades/batch05/post-sample-upgrade.dump"
BACKUP_SHA256 = "F1D1D6EA6D4594808CBC35F43F3AE51AF7F0C27C9229B246AAF483E1391047FA"
OUT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/originals/batch06-revised"
DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"


def candidates():
    return [
        item("z5b6-math-moving-integral-endpoints", "math.exam.3504d885999b", "C",
            "令 $F(x)=\\int_x^{x^2}\\ln(1+t^2)\\,dt$。$F''(1)$ 等于（ ）。",
            {"A": "2\\ln2+1", "B": "2\\ln2+4", "C": "2\\ln2+3", "D": "\\ln2+3"},
            "被积函数连续可微，先用Leibniz公式得 $F'(x)=2x\\ln(1+x^4)-\\ln(1+x^2)$。再求导：$F''(x)=2\\ln(1+x^4)+8x^4/(1+x^4)-2x/(1+x^2)$。代入1得 $2\\ln2+4-1=2\\ln2+3$。上下限在x=1相交不改变该求导公式。",
            [("leibniz_variable_limits", "分别对上限x²和下限x求导，得到2x ln(1+x⁴)−ln(1+x²)。"),
             ("differentiate_and_evaluate", "再对两项求导并在x=1代入，得到2ln2+4−1。")],
            [("first_derivative", "Leibniz公式对上限贡献2x ln(1+x⁴)，对下限贡献−ln(1+x²)。"),
             ("second_derivative", "在x=1，三项分别为2ln2、4、−1，合为2ln2+3。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要同时处理平方上限与线性下限的链式因子，并对结果再次求导。",
             "先逐端使用Leibniz公式，再分别对复合对数项求导并代入相交端点。",
             "下限求导带负号；上限x²产生2x，忽略任一项都会改变常数部分。",
             "综合变上限积分求导与高阶导数，检验多个移动边界的符号和链式法则。"),
            ["Leibniz公式", "变上限积分", "导数连续性"], difficulty="advanced"),

        item("z5b6-math-cusp-extrema-parameter", "math.exam.bc1427755983", "A",
            "设 $f_a(x)=x^2+a|x|$，a为实数。关于x=0处局部极值的结论正确的是（ ）。",
            {"A": "a<0时为严格局部极大；a≥0时为严格局部极小", "B": "a>0时为严格局部极大；a≤0时为严格局部极小",
             "C": "仅a=0时有局部极值", "D": "任意a时函数在0可导且取得极小值"},
            "若a>0，则对充分小的x≠0有x²+a|x|>0=f_a(0)，故0为严格局部极小；a=0时x²也给严格局部极小。若a<0，取0<|x|<−a，则x²+a|x|=|x|(|x|+a)<0=f_a(0)，故0为严格局部极大。a≠0时尖点处不可导，但极值定义仍适用。",
            [("sign_factorization", "写成|x|(|x|+a)，分别按a符号和邻域大小确定函数值相对f(0)的方向。"),
             ("definition_based_classification", "直接用局部极值定义分类，不依赖内点可导的必要条件。")],
            [("a_nonnegative", "a≥0时x²+a|x|对x≠0严格为正，故0是严格局部极小。"),
             ("a_negative", "a<0时在0<|x|<−a内乘积为负，故0是严格局部极大。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("参数符号与邻域大小共同决定尖点附近函数值，需直接应用极值定义。",
             "将差值因式分解为|x|(|x|+a)，再对a<0和a≥0分类。",
             "不可导不意味着没有极值；a=0也应计入严格局部极小。",
             "区分极值定义和可导驻点定理的适用条件，并处理带参数的非光滑点。"),
            ["局部极值定义", "参数分类", "不可导点"], difficulty="medium"),

        item("z5b6-math-resonant-ode-particular", "math.exam.d59b003eda7d", "D",
            "方程 $y''-2y'+y=xe^x$ 的标准试探特解写为 $y_p=e^xP(x)$，并约定P的常数项、一次项均取0。此时 $y_p$ 为（ ）。",
            {"A": "xe^x", "B": "x^2e^x/2", "C": "x^4e^x/24", "D": "x^3e^x/6"},
            "齐次特征根为1的二重根，齐次解为$(C_1+C_2x)e^x$。令$y=e^xP$，则$(D-1)^2y=e^xP''$，方程化为$P''=x$。积分得$P=x^3/6+C_1x+C_0$；按题设把常数项和一次项取0，得到$P=x^3/6$。直接代回左端也得$xe^x$。",
            [("shifted_operator", "利用(D−1)^2(e^xP)=e^xP''，将共振方程转为P''=x。"),
             ("particular_and_resonance", "两次积分得三次多项式；题设归一化消去可吸收进齐次解的常数与一次项。")],
            [("homogeneous_overlap", "特征根1二重，强迫项xe^x与齐次解共振，须在变换后解P''=x。"),
             ("substitution_check", "对P=x³/6有P''=x，故原算子作用结果正好xe^x。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需识别二重特征根共振，并把常系数算子平移成对多项式P的二阶导数。",
             "先求齐次根，再作y=e^xP变换，积分强迫项并按题设固定齐次自由项。",
             "未经共振修正直接取xe^x乘多项式会与齐次解重合；一次多项式不足以使二阶导数等于x。",
             "检验待定系数法在重根共振时的多项式次数与齐次解吸收自由度。"),
            ["常系数线性方程", "共振特解", "齐次解结构"], difficulty="advanced"),

        item("z5b6-math-composite-second-derivative", "math.exam.6dcf2377bdd4", "B",
            "设 $z(u,v)=u^2+uv+2v^2$，$u(t)=1+t$，$v(t)=2-t^2$，令 $h(t)=z(u(t),v(t))$。$h''(0)$ 为（ ）。",
            {"A": "−18", "B": "−16", "C": "−14", "D": "2"},
            "在t=0，(u,v)=(1,2)，$q'=(1,0)$、$q''=(0,-2)$。$\\nabla z=(2u+v,u+4v)=(4,9)$，Hessian为$[[2,1],[1,4]]$。二阶复合链式公式给$h''=q'^THq'+\\nabla z\\cdot q''=2-18=-16$。直接展开$h(t)=11+4t-8t²-t³+2t⁴$亦得二阶导为−16。",
            [("hessian_chain_rule", "用q′ᵀHq′+∇z·q″计算二阶复合导数，得到2−18。"),
             ("polynomial_expansion", "代入u(t)、v(t)展开并读取t²系数−8，二阶导为−16。")],
            [("gradient_hessian_values", "在(1,2)处梯度为(4,9)，Hessian作用于(1,0)给出2。"),
             ("curve_acceleration_term", "v″(0)=−2产生梯度加速度项9×(−2)=−18，合计−16。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要同时使用二阶链式法则中的Hessian项与路径加速度项。",
             "先在指定点计算梯度和Hessian，再分别计算切向曲率贡献与二阶路径贡献。",
             "只计算Hessian二次型会漏掉v″项；把梯度与曲率项混为一项也会错。",
             "把多元全微分、复合函数二阶导和沿曲线的加速度联系起来。"),
            ["全微分", "复合函数二阶导", "Hessian"], difficulty="advanced"),

        item("z5b6-math-moving-parameter-integral-third", "math.exam.8eaf1a6aeb50", "C",
            "设 $F(a)=\\int_a^{2a}e^{at}\\,dt$，按定向积分理解上下限。$F'''(0)$ 等于（ ）。",
            {"A": "3", "B": "6", "C": "9", "D": "12"},
            "作代换$t=au$可得$F(a)=a\\int_1^2e^{a^2u}du$，该式对a在0附近解析。展开至三次项：$e^{a^2u}=1+a^2u+O(a^4)$，所以$F(a)=a+a^3\\int_1^2u,du+O(a^5)=a+3a^3/2+O(a^5)$。因此$F'''(0)=3!×3/2=9$。定向积分代换保留a的符号，公式在a=0连续成立。",
            [("moving_bounds_substitution", "令t=au把移动区间化为固定[1,2]，并保留定向积分的因子a。"),
             ("series_coefficient", "提取F的三次项系数3/2，乘3!得到F'''(0)=9。")],
            [("fixed_interval_integral", "代换后F(a)=a∫₁²e^(a²u)du，展开三阶项为a³∫₁²u du。"),
             ("derivative_factorial", "三次Taylor系数为F'''(0)/3!=3/2，故三阶导数为9。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("上下限与被积函数均含参数，三阶导数需要合并边界变化和参数变化。",
             "先把移动区间变为固定区间，再用参数展开精确提取三次系数。",
             "只对e^(at)作三次求导会漏掉上下限移动；把定向因子a替成|a|也错误。",
             "训练Leibniz参数积分的移动边界处理和高阶导数局部展开。"),
            ["含参积分求导", "移动积分限", "Taylor系数"], difficulty="advanced"),

        item("z5b6-math-both-endpoint-convergence", "math.exam.a62c828f6537", "D",
            "对实参数p，反常积分 $J(p)=\\int_0^{\\infty}\\frac{x^p\\ln(1+x)}{1+x^2}\\,dx$ 收敛的充要条件为（ ）。",
            {"A": "p>−1", "B": "p<1", "C": "−1<p<2", "D": "−2<p<1"},
            "在0附近，ln(1+x)∼x且1+x²∼1，故被积函数与x^(p+1)同阶，积分收敛要求p+1>−1，即p>−2。在无穷远处，ln(1+x)∼ln x且1+x²∼x²，故与x^(p−2)ln x同阶，收敛要求p−2<−1，即p<1；临界p=1时∫ln x/x发散。两个端点条件交集为−2<p<1。",
            [("zero_endpoint_comparison", "零点处比较x^(p+1)，得到严格条件p>−2。"),
             ("infinity_endpoint_comparison", "无穷远比较x^(p−2)ln x，得到严格条件p<1，临界值发散。")],
            [("local_orders", "0端由对数的一阶零点把幂次提高1；∞端分母贡献x²并保留ln x。"),
             ("intersection_of_conditions", "独立检查0与∞后取条件交集，得到(−2,1)。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("必须分别处理零点和无穷远两个端点，且临界幂指数需要检查对数因子。",
             "先用等价阶确定两个比较积分，再分别解参数不等式并取交集。",
             "忽略ln(1+x)在0端的一阶零点会把下界错移1；只分析其中一个端点也不充分。",
             "综合含对数因子的双端反常积分比较与临界情形判别。"),
            ["广义积分", "端点比较", "参数收敛区间"], difficulty="advanced"),

        item("z5b6-math-symmetric-double-riemann-sum", "math.exam.b481011b3a32", "A",
            "求极限 $\\lim_{n\\to\\infty}\\frac1{n^2}\\sum_{i=1}^{n}\\sum_{j=1}^{n}\\left[(i/n)^2-(j/n)^2\\right]^2$。（ ）",
            {"A": "8/45", "B": "2/15", "C": "1/5", "D": "4/45"},
            "该双重和是单位正方形上连续函数$(x^2-y^2)^2$的黎曼和。积分为$\\int_0^1\\int_0^1(x^4+y^4-2x^2y^2)dxdy=1/5+1/5-2(1/3)^2=2/5-2/9=8/45$。对调x、y后被积函数不变，两个纯四次项贡献相同，可作为对称性检查。",
            [("riemann_sum_identification", "步长面积为1/n²，网格点(i/n,j/n)覆盖单位正方形。"),
             ("separable_integral", "展开后分离积分，得到1/5+1/5−2/9=8/45。")],
            [("continuity_and_limit", "被积函数在闭单位正方形连续，黎曼和收敛到其二重积分。"),
             ("symmetry_cross_check", "交换坐标不改变函数；交叉项积分为2(1/3)²。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要先识别二维黎曼和，再分解对称多项式的纯项与交叉项。",
             "把求和极限转换为单位正方形积分，并利用可分离积分精确计算。",
             "平方展开的交叉项带负号且系数2；漏掉它会得到错误的四次矩。",
             "将离散双重求和、黎曼积分和交换变量对称性联合使用。"),
            ["二重积分黎曼和", "对称性", "多项式积分"], difficulty="medium"),

        item("z5b6-math-quadratic-form-congruence", "math.exam.7af99f485eff", "B",
            "实二次型 $q(x,y)=x^2+4xy+3y^2$ 经可逆线性替换化为规范对角形。其惯性指数(正、负)为（ ）。",
            {"A": "(2,0)", "B": "(1,1)", "C": "(0,2)", "D": "(1,0)"},
            "配方得$q=(x+2y)^2-y^2$。令$u=x+2y,v=y$，变换矩阵行列式为1，故可逆，二次型合同于$u^2-v^2$。因此有一个正平方项、一个负平方项，惯性指数为(1,1)，秩为2。矩阵行列式$1·3-2²=-1$也确认其符号不定。",
            [("completion_of_square", "将交叉项配方为(x+2y)²−y²，并写出可逆替换。"),
             ("inertia_invariance", "可逆合同变换保持惯性指数，规范形有一正一负平方项。")],
            [("invertible_transform", "替换u=x+2y、v=y的行列式为1，满足合同变换可逆条件。"),
             ("determinant_cross_check", "原对称矩阵行列式−1，故两个特征值异号，与(1,1)一致。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要识别交叉项配方，并判断合同替换是否可逆后才可读取惯性指数。",
             "先构造可逆线性替换化为一正一负平方，再用行列式符号复核。",
             "对角化与合同变换的惯性不应混淆；交叉项系数4对应配方中的2y。",
             "联系二次型配方、矩阵合同和惯性指数不变量。"),
            ["二次型", "合同变换", "惯性指数"], difficulty="medium"),

        item("z5b6-math-nilpotent-rank-square", "math.exam.90bbbeb58b4a", "C",
            "四阶矩阵N满足 $N^3=0$ 且 $\\operatorname{rank}N=2$。仅凭这些条件，$\\operatorname{rank}(N^2)$ 能否唯一确定？（ ）",
            {"A": "必为0", "B": "必为1", "C": "不能唯一确定，0和1均可能", "D": "必为2"},
            "令$N_1=diag(J_2,J_2)$，其中$J_2=[[0,1],[0,0]]$，则$N_1^3=0$、rank$N_1=2$而rank$N_1^2=0$。另令$N_2=diag(J_3,0)$，其中$J_3$为三阶上移位幂零块，则$N_2^3=0$、rank$N_2=2$但rank$N_2^2=1$。两例满足同一已知条件而平方秩不同，所以不能唯一确定。",
            [("construct_first_counterexample", "两个二阶幂零块的直和满足N³=0、rankN=2、N²=0。"),
             ("construct_second_counterexample", "三阶幂零块与零块直和满足相同前提，但平方后秩为1。")],
            [("exact_block_multiplication", "逐块相乘验证J₂²=0及J₃²非零、J₃³=0。"),
             ("rank_comparison", "两构造的N秩均为2，而N²秩分别0与1，构成不唯一性的反例。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要区分幂零指数上界和幂零结构，单凭N³=0及rankN不能推出平方秩。",
             "构造两个满足同一约束的具体分块矩阵，直接计算N与N²的秩。",
             "幂零矩阵的秩不会唯一决定所有高次幂的秩；需提供结构或额外约束。",
             "通过可复算反例训练线性代数条件充分性和幂零矩阵幂秩判断。"),
            ["幂零矩阵", "矩阵秩", "反例构造"], difficulty="advanced"),

        item("z5b6-math-inverse-third-derivative", "math.exam.3e373cbe2c92", "D",
            "函数 $f(x)=x+\\sin x$ 在0附近严格递增，设其反函数为g。$g'''(0)$ 等于（ ）。",
            {"A": "−1/8", "B": "−1/16", "C": "1/8", "D": "1/16"},
            "由$f(g(y))=y$连续求导，$g'=1/f'(g)$，$g''=-f''(g)/(f'(g))^3$，并有$g'''=(3(f'')^2-f'f''')/(f')^5$，各导数在x=g(y)处取值。因g(0)=0、f'(0)=2、f''(0)=0、f'''(0)=−1，故$g'''(0)=2/32=1/16$。f'(0)>0保证局部反函数存在。",
            [("inverse_derivative_formula", "对f(g(y))=y连续求导三次，得到三阶反函数导数公式。"),
             ("local_data_substitution", "在x=0代入f′=2、f″=0、f‴=−1，得到1/16。")],
            [("inverse_function_existence", "f′(0)=1+cos0=2非零，逆函数在0邻域可微。"),
             ("third_order_chain_check", "三阶公式分子为−f′f‴=2，分母为2⁵=32。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需从反函数恒等式连续求导到三阶，并先确认局部逆函数条件。",
             "用一、二、三阶复合求导关系消去g的低阶导数，再代入原函数导数。",
             "三阶公式的分母为(f′)⁵；忽略f‴的负号会反转答案符号。",
             "综合反函数存在条件和三阶导数链式关系，考查高阶局部变化。"),
            ["反函数导数", "三阶导数", "链式法则"], difficulty="advanced"),

        item("z5b6-408-sequential-search-weighted-order", "cs408.ds.topic.d6d83159a7e3", "A",
            "线性表有4条记录，成功查找概率(按记录身份)分别为0.08、0.32、0.24、0.16，失败概率0.20；每次关键字比较计1。可任意重排记录，失败时需比较4次。最小平均比较次数为（ ）。",
            {"A": "2.40", "B": "2.60", "C": "2.80", "D": "3.40"},
            "成功查找应按概率降序排列以最小化加权位置和，顺序为0.32、0.24、0.16、0.08。成功部分期望为0.32×1+0.24×2+0.16×3+0.08×4=1.60；失败部分为0.20×4=0.80。最小平均比较次数为1.60+0.80=2.40。",
            [("exchange_argument", "相邻位置若概率较小者在前，交换会减少加权比较代价，故按概率降序排列。"),
             ("weighted_cost", "降序成功代价为1.60，失败代价0.80，总期望2.40。")],
            [("optimal_order", "将成功概率排序为0.32、0.24、0.16、0.08。"),
             ("expected_comparisons", "成功期望1.60加失败概率0.20乘4得0.80，总计2.40。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要依据成功概率优化线性表顺序，并同时计入失败查找的比较代价。",
             "用相邻交换论证概率降序最优，再计算成功与失败两部分的加权期望。",
             "概率总和必须为1；失败项不能漏计，且每条成功概率对应其新位置。",
             "把顺序查找平均长度从等概率公式推广到非均匀成功概率并选择最优顺序。"),
            ["顺序查找", "加权平均查找长度", "交换优化"], difficulty="advanced"),

        item("z5b6-408-post-inorder-level-order", "cs408.ds.topic.de07cf385c9a", "A",
            "一棵结点互异的二叉树中序序列为D、H、B、E、A、F、C、G，后序序列为H、D、E、B、F、G、C、A。其层序序列为（ ）。",
            {"A": "A、B、C、D、E、F、G、H", "B": "A、B、C、D、E、F、H、G", "C": "A、B、C、H、D、E、F、G", "D": "A、C、B、F、G、D、E、H"},
            "后序末项A为根，中序据此分成左侧D,H,B,E与右侧F,C,G。左子树后序H,D,E,B的根是B；其左侧中序D,H由后序H,D重建为D的右孩子H，右孩子为E。右子树根C，左孩子F、右孩子G。按层逐层访问得到A、B、C、D、E、F、G、H。",
            [("postorder_root_partition", "后序末项确定根A，中序切分左右子树并递归恢复根B与C。"),
             ("level_order_queue", "恢复结构后按队列逐层访问，D的右孩子H最后进入下一层。")],
            [("left_subtree_reconstruction", "左子树为B，左边D带右孩子H，右边为E。"),
             ("right_subtree_reconstruction", "右子树C有左右孩子F、G，合并后层序为AB CDEFGH。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需由后序末项和中序区间递归重建树，再进行与给定遍历不同的层序扫描。",
             "按根位置切分左右区间，递归建立结构后用队列生成层序。",
             "后序给根但不直接给层序；左子树D的右孩子H需放在下一层末尾。",
             "综合遍历序列重建、递归子树划分和队列层序访问。"),
            ["后序遍历", "中序遍历", "层序遍历"], difficulty="advanced"),

        item("z5b6-408-adjacency-matrix-two-step-walks", "cs408.ds.topic.f26de897ea89", "B",
            "有向图顶点为1、2、3、4，弧为1→2、1→3、2→4、3→4、4→1。其0-1邻接矩阵A中，从顶点1到顶点4恰走2条边的游走数，即$(A^2)_{1,4}$，为（ ）。",
            {"A": "1", "B": "2", "C": "3", "D": "4"},
            "矩阵乘法给$(A^2)_{1,4}=\\sum_k A_{1k}A_{k4}$。只有k=2和k=3两项非零，分别对应路径1→2→4与1→3→4，因此共有2条。长度为2的游走数由$A^2$对应元素计数，不是邻接矩阵中的边数。",
            [("matrix_product_entry", "按定义求和，候选中间顶点k必须同时满足1→k与k→4。"),
             ("explicit_path_enumeration", "逐一列出经2、经3的两条路径，结果为2。")],
            [("nonzero_terms", "A₁₂A₂₄=1、A₁₃A₃₄=1，其余中间顶点项为0。"),
             ("walk_count_identity", "邻接矩阵平方的(i,j)元素计数所有恰含两条边的i到j游走。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要把邻接矩阵乘法与固定长度游走计数联系起来，并枚举合法中间顶点。",
             "按矩阵平方元素求和，再用图路径逐项核对。",
             "不能把入边或出边总数当作二步路径数；只有同时连通的中间点贡献。",
             "运用邻接矩阵幂分析有向图中的定长游走数量。"),
            ["邻接矩阵", "矩阵乘法", "定长游走"], difficulty="medium"),

        item("z5b6-408-orthogonal-list-incidence-count", "cs408.ds.topic.ea735e877597", "D",
            "有向图弧集为u→v、u→w、v→w、w→u、w→x、x→w。用十字链表存储，每条弧只分配一个弧结点，同时挂入尾顶点出边链和头顶点入边链。顶点w的firstin与firstout两链合计可访问的不同弧结点数，以及全图弧结点总数分别为（ ）。",
            {"A": "4，10", "B": "5，5", "C": "6，6", "D": "5，6"},
            "进入w的弧为u→w、v→w、x→w，共3条；从w发出的弧为w→u、w→x，共2条。没有自环，两组弧不重叠，因此两条链合计涉及5个不同弧结点。全图只有6条弧，十字链表每条弧只存一个结点，故总数为6而不是入链、出链引用数之和。",
            [("incidence_enumeration", "按弧头统计入度3，按弧尾统计出度2，顶点w不含自环。"),
             ("single_arc_node_invariant", "每条有向弧结点同时链接两类链表但只分配一次，全图为6个。")],
            [("firstin_firstout", "w的firstin访问3条、firstout访问2条且两组不重合，合计5。"),
             ("global_storage_count", "弧集包含6条不同弧，因此分配6个弧结点。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需要分别遍历顶点的入弧链和出弧链，并区分链表引用数与实际弧结点数。",
             "先按弧头、弧尾枚举w关联弧，再利用每条弧只建一个结点统计全图存储。",
             "同一弧结点可同时被两类链引用，不能把全图节点数翻倍；本图也无自环重叠。",
             "把十字链表的双向关联结构用于图的入度、出度与实际结点存储计数。"),
            ["十字链表", "入边与出边", "弧结点共享"], difficulty="medium"),

        item("z5b6-408-os-concurrency-parallelism", "cs408.os.topic.6eeb2632531c", "C",
            "单核处理器采用抢占式时间片调度运行两个CPU密集进程。判断：Ⅰ二者可以在一段时间内交替推进；Ⅱ二者在同一瞬间并行执行指令；Ⅲ并发不意味着固定的交替顺序。正确的是（ ）。",
            {"A": "仅Ⅰ", "B": "Ⅰ、Ⅱ", "C": "Ⅰ、Ⅲ", "D": "Ⅱ、Ⅲ"},
            "单核在任一时刻只能执行一个进程的指令，因此Ⅱ不成立；抢占与切换可使两个进程在一段时间内交替推进，Ⅰ成立。调度时序由运行状态、中断和调度决策共同决定，并发本身不保证固定交替次序，Ⅲ成立。并发描述时间段内的交替推进，并行要求同一时刻有多个执行单元。",
            [("single_core_execution_constraint", "单核每一瞬间只执行一个指令流，排除同时并行。"),
             ("preemptive_interleaving", "时间片调度允许多个进程在时间段内交替推进，顺序不固定。")],
            [("concurrency_vs_parallelism", "单核可并发但不能同一瞬间并行执行两进程。"),
             ("schedule_nondeterminism", "抢占点受运行事件影响，系统不承诺固定交替次序。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要区分并发与并行的时间含义，并判断抢占调度是否保证确定顺序。",
             "逐条用单执行单元约束和时间片调度定义判定，再组合正确命题。",
             "在单核上多个进程可并发推进但不能同时运行；并发也不保证严格轮转。",
             "用具体硬件执行资源分析操作系统并发、并行和调度顺序。"),
            ["并发与并行", "单核调度", "抢占式多道程序"], difficulty="medium"),

        item("z5b6-408-spooling-process-lifetime", "cs408.os.topic.e54fc352f4b6", "A",
            "进程A的完整打印作业已在t=3时写入外存SPOOL队列；打印机当前任务到t=10才结束，且无取消策略。A在t=4退出。哪项必然成立？",
            {"A": "A退出后打印作业仍可由后台SPOOL服务在队列轮到时输出", "B": "A必须保持运行到t=10以后，否则作业自动丢失", "C": "作业写入SPOOL即表示打印机已完成输出", "D": "SPOOL只能在CPU空闲时直接控制打印机"},
            "题设说明作业在t=3已完整写入外存队列，后续输出由独立SPOOL服务按队列调度。应用进程退出不会撤销已持久化的队列作业；打印机当前任务结束后可继续处理A的作业。若进程在作业尚未完整写入前退出，则不能由本题结论保证完整作业保留。",
            [("spool_queue_decoupling", "完整作业已进入外存队列，提交者生命周期与设备服务时间解耦。"),
             ("device_service_order", "打印机空闲后由后台服务读取已排队作业并输出。")],
            [("persistence_premise", "关键条件是作业已在t=3完整写入外存而非仍由A生成。"),
             ("asynchronous_completion", "A在t=4退出不影响独立队列服务于t≥10继续打印。")],
            {"A": True, "B": False, "C": False, "D": False},
            ("需要识别SPOOLing通过外存队列把应用提交与物理设备服务分离。",
             "先确定作业已完整写入队列，再追踪后台服务与应用退出的先后关系。",
             "排队只表示等待设备处理，不表示打印完成；应用无需为已持久化作业一直存活。",
             "理解假脱机服务的异步解耦、外存缓冲和设备独立运行。"),
            ["SPOOLing", "外存缓冲", "异步设备服务"], difficulty="medium"),

        item("z5b6-408-http-connection-model-timing", "cs408.cn.topic.a44bb362c00a", "B",
            "网页含1个基础HTML和2个嵌入对象，总传输量30KB；链路速率10Mbit/s，RTT=20ms。忽略DNS、处理、并行、慢启动和协议头；每个对象的请求按顺序响应。HTTP非持久连接每个对象单独建连，持久连接只建1次TCP连接。非持久与持久完成时间分别约为（ ）。",
            {"A": "84ms，64ms", "B": "144ms，104ms", "C": "120ms，80ms", "D": "204ms，124ms"},
            "30KB=240kbit，链路传输时间为24ms。非持久方式3个对象各需1RTT建连和1RTT请求响应，共6RTT=120ms，总计144ms。持久方式需1RTT建立连接及3个顺序请求响应RTT，共4RTT=80ms，总计104ms。持久连接节省两个建连RTT，即40ms。",
            [("serialization_time", "240kbit除以10Mbit/s为24ms。"),
             ("connection_round_trip_count", "非持久每对象2RTT共6RTT；持久为1次建连加3次请求共4RTT。")],
            [("nonpersistent_total", "6×20+24=144ms。"),
             ("persistent_total", "4×20+24=104ms，较非持久少40ms。")],
            {"A": False, "B": True, "C": False, "D": False},
            ("需要分别计算对象传输时间和连接模型引入的往返时延。",
             "按对象逐个计建连与请求RTT，再加一次总数据串行化时间。",
             "基础对象也要建连和请求；持久连接仍需每个顺序请求的响应RTT。",
             "比较HTTP连接复用在多对象页面上的时延收益并统一处理传输量单位。"),
            ["客户机服务器模型", "HTTP持久连接", "RTT计数"], difficulty="advanced"),

        item("z5b6-408-router-ttl-expiry", "cs408.cn.topic.0a2961dff8db", "D",
            "IPv4分组初始TTL=2，沿途需经过路由器R1、R2到达目的主机；两处均有匹配路由，无其他丢弃原因。每台路由器转发前将TTL减1，校验和更新。分组到达R2后应如何处理？",
            {"A": "R2将TTL置为1并转发，目的主机收到TTL=0", "B": "R1因TTL=2而丢弃并发送ICMP超时", "C": "R2保持TTL=1转发，不必修改首部校验和", "D": "R1转发时TTL变1；R2减至0后丢弃并向源发送ICMP超时报文"},
            "R1转发时将TTL由2减至1并更新IPv4首部校验和。R2处理时TTL为1，再减1得到0，分组不得继续转发，应丢弃并通常向源地址发送ICMP Time Exceeded。TTL避免分组在转发环路中无限循环。",
            [("hop_by_hop_ttl_trace", "逐路由器记录TTL：R1后为1，R2减后为0。"),
             ("expiry_action", "TTL耗尽时路由器丢弃分组并生成ICMP超时报文，不转发到目的主机。")],
            [("header_update", "每次转发减TTL，并须更新IPv4首部校验和。"),
             ("second_router_expiry", "R2把1减到0，故触发超时丢弃而非向主机交付。")],
            {"A": False, "B": False, "C": False, "D": True},
            ("需逐跳跟踪TTL变化，并将到期后的控制面错误反馈与普通转发区分。",
             "先计算R1转发后的剩余值，再按R2处理规则判断是否可继续转发。",
             "不能让TTL为0的分组到达目的主机；每次TTL变化也改变首部校验和。",
             "将路由器转发、环路抑制和ICMP错误报告联系起来。"),
            ["路由器转发", "IPv4 TTL", "ICMP差错报告"], difficulty="medium"),

        item("z5b6-408-switch-store-forward-delay", "cs408.cn.topic.201ce80c4dd6", "C",
            "二层交换机对该端口采用存储转发，接收完整1500B以太网帧并完成FCS检查后才开始从输出端发送。输入端速率100Mbit/s，输出端速率1Gbit/s；忽略前导码、处理时延和排队。第一个比特在t=0进入交换机时，输出最早何时可开始？",
            {"A": "12μs", "B": "15μs", "C": "120μs", "D": "132μs"},
            "存储转发必须先完整接收帧。1500B=12000bit，输入串行化时间为12000/(100×10⁶)=120μs；完成帧与FCS检查后才可开始输出。输出端更快只影响后续发送时间，不缩短完整帧到达输入端所需时间。",
            [("bit_serialization_formula", "直接按比特串行化公式计算：12000bit÷100000000bit/s=0.00012s=120μs。"),
             ("byte_rate_cross_check", "换算输入速率为12500000B/s，再算1500B÷12500000B/s=0.00012s=120μs；存储转发须在整帧收完后才开始输出。")],
            [("frame_size_conversion", "1500B乘8为12000bit。"),
             ("rate_comparison", "输入端瓶颈时延120μs，输出速率不改变开始条件。")],
            {"A": False, "B": False, "C": True, "D": False},
            ("需要把交换方式的转发条件与输入端串行化时延关联起来。",
             "先把帧长换算为比特并用输入速率求完整接收时间。",
             "不能使用更快的输出速率计算接收时延，也不能在完整帧到达前开始存储转发。",
             "分析二层交换设备的存储转发机制与不同端口速率下的首位时延。"),
            ["以太网交换机", "存储转发", "串行化时延"], difficulty="medium"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    args = parser.parse_args()
    if not BACKUP.is_file() or hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper() != BACKUP_SHA256:
        raise SystemExit("prebatch_backup_missing_or_hash_mismatch")
    pg_restore = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
    toc = subprocess.run([str(pg_restore), "--list", str(BACKUP)], capture_output=True, timeout=30)
    if toc.returncode or b"TABLE DATA public questions" not in toc.stdout:
        raise SystemExit("prebatch_backup_archive_invalid")
    output = OUT_DIR / ("preview.json" if args.mode == "dry-run" else "checkpoint.json")
    if output.exists():
        raise SystemExit(f"refusing_to_overwrite_existing_output:{output.name}")

    from scripts import phase45z5_original_batch01 as runner
    runner.BACKUP, runner.BACKUP_SHA256 = BACKUP, BACKUP_SHA256
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres",
        host="127.0.0.1", port=PORT, database=DB_NAME), pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.begin()
            try:
                report = run_batch(db, candidate_specs=candidates(), batch_id="06")
                report["status"] = "DRY_RUN_ROLLED_BACK" if args.mode == "dry-run" else "BATCH06_APPLIED"
                report["backup"]["toc_entries"] = len(toc.stdout.splitlines())
                if sha_file(BACKUP) != BACKUP_SHA256:
                    raise ValueError("backup_changed_during_batch")
                db.rollback() if args.mode == "dry-run" else db.commit()
            except Exception:
                db.rollback()
                raise
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({
            "status": report["status"],
            "candidates": len(candidates()),
            "accepted": len(report["accepted"]),
            "rejected": report["rejected"],
            "checkpoint": output.relative_to(ROOT).as_posix(),
            "paid_model_calls": 0,
        }, ensure_ascii=False, default=str))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
