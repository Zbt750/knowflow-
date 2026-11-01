"""Small mixed-subject Codex-authored public-original pilot on batch 17 clone."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import run_phase45hx_batch02 as batch
from backend.services.question_generation import Output

batch.SOURCE_RUN=ROOT/"storage/quality-audits/phase45hx-20261011/batch-17"
batch.OUT=ROOT/"storage/quality-audits/phase45hx-20261011/batch-18-originals"
batch.PACK=None
batch.PDF=None
batch.EXPECTED_QUESTIONS=0
batch.PROCESS_PACK=False
batch.SOURCE_SUCCESS_STATUS="BATCH_17_COMPLETE"
batch.PHASE_LABEL="4.5H-X-batch-18-originals"
batch.SUCCESS_STATUS="BATCH_18_ORIGINALS_COMPLETE"
batch.TEST_FILES=["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS=["-k","codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]

batch.CODEX_PUBLIC_ORIGINALS=[
    {
        "request_id":"hx18-math-determinant-transpose-v1",
        "node_code":"math.linear-algebra.determinant.properties",
        "output":Output(stem="设矩阵 A=[[1,2],[3,4]]，求 det(Aᵀ)。",question_type="fill_blank",
            correct_answer="-2",final_value="-2",
            explanation="利用转置不改变行列式的性质，det(Aᵀ)=det(A)。按二阶行列式定义计算 1×4−2×3=−2。先用 det(Aᵀ)=det(A) 化为原矩阵行列式，再代入 ad−bc 得到4−6=−2。",
            steps=[{"expression":"1*4-2*3","value":"-2"}]),
        "derived_answer":"-2",
        "method_evidence":[
            {"method":"transpose-invariance-and-definition","result":"det(Aᵀ)=det(A)=1×4−2×3=−2，转置不改变行列式。"},
            {"method":"direct-transposed-matrix-expansion","result":"Aᵀ=[[1,3],[2,4]]，直接按 ad−bc 展开为1×4−3×2=−2。"},
        ],
        "explanation_key_steps":[
            "先用 det(Aᵀ)=det(A) 将转置行列式化为原矩阵行列式。",
            "代入二阶行列式定义 ad−bc，得到4−6=−2。",
        ],
        "skill_tags":["行列式转置性质","二阶行列式展开"],
    },
    {
        "request_id":"hx18-math-implicit-derivative-v1",
        "node_code":"math.calculus.differential.implicit",
        "output":Output(stem="曲线 x²+y²=25 在点 (3,4) 处的切线斜率是多少？",question_type="fill_blank",
            correct_answer="-3/4",final_value="-3/4",
            explanation="对 x²+y²=25 两边关于 x 求导，得 2x+2y·y′=0，所以 y′=−x/y。在 (3,4) 处斜率为−3/4。几何上该圆的切线垂直于半径向量(3,4)，其斜率也为−3/4。",
            steps=[{"expression":"-3/4","value":"-3/4"}]),
        "derived_answer":"-3/4",
        "method_evidence":[
            {"method":"implicit-differentiation","result":"对方程逐项求导得到2x+2yy′=0，代入(3,4)得y′=−3/4。"},
            {"method":"circle-tangent-normality","result":"半径向量(3,4)与切线方向向量垂直，切线斜率满足3+4m=0，故m=−3/4。"},
        ],
        "explanation_key_steps":[
            "对等式两端求导时，y²需要使用链式法则，得到2y·y′。",
            "解出y′=−x/y，并在给定点代入，得到−3/4。",
        ],
        "skill_tags":["隐函数求导","链式法则","切线斜率"],
    },
    {
        "request_id":"hx18-math-geometric-series-v1",
        "node_code":"math.calculus.series.geometric",
        "output":Output(stem="求无穷等比级数 1+2/3+(2/3)²+(2/3)³+… 的和。",question_type="fill_blank",
            correct_answer="3",final_value="3",
            explanation="该级数首项 a=1、公比 r=2/3，且 |r|<1，故收敛和为 a/(1−r)=1/(1−2/3)=3。也可由部分和 S_n=3(1−(2/3)^(n+1)) 取 n→∞ 得3。",
            steps=[{"expression":"1/(1-2/3)","value":"3"}]),
        "derived_answer":"3",
        "method_evidence":[
            {"method":"geometric-series-sum-formula","result":"a=1,r=2/3 且 |r|<1，S=a/(1−r)=1/(1/3)=3。"},
            {"method":"partial-sum-limit","result":"S_n=1·(1−(2/3)^(n+1))/(1−2/3)，幂项趋于0，极限为3。"},
        ],
        "explanation_key_steps":[
            "先确认公比绝对值小于1，这是无穷等比级数收敛并使用求和公式的条件。",
            "代入首项和公比，得到1/(1−2/3)=3。",
        ],
        "skill_tags":["等比级数求和","级数收敛条件"],
    },
    {
        "request_id":"hx18-408-deque-ends-v1",
        "node_code":"cs408.ds.topic.48e8e73d9928",
        "output":Output(stem="哪一种线性数据结构允许在其两端分别进行插入和删除？",question_type="single_choice",
            options={"A":"普通循环队列","B":"栈","C":"双端队列","D":"按优先级取出的优先队列"},
            correct_answer="C",final_value="C",
            explanation="双端队列（deque）允许在队头、队尾插入和删除。普通队列通常一端入队、另一端出队；栈只在栈顶操作；优先队列按优先级选择元素，不等同于两端操作。",
            steps=[]),
        "derived_answer":"C",
        "method_evidence":[
            {"method":"operation-definition","result":"双端队列的定义允许两端插入和两端删除，题干描述与其直接对应。"},
            {"method":"alternative-structure-elimination","result":"普通队列、栈、优先队列分别受端点约束、单端约束或优先级约束，均不满足两端均可插删。"},
        ],
        "explanation_key_steps":[
            "双端队列的操作端点包括队头和队尾。",
            "逐一比较其余结构的操作规则，只有双端队列符合题目条件。",
        ],
        "option_truth_table":{"A":False,"B":False,"C":True,"D":False},
        "skill_tags":["双端队列定义","线性结构操作"],
    },
    {
        "request_id":"hx18-408-process-blocked-state-v1",
        "node_code":"cs408.os.topic.ad106d393729",
        "output":Output(stem="一个正在运行的进程请求磁盘读操作，必须等待该I/O完成后才能继续执行。操作系统通常将该进程转入什么状态？",question_type="single_choice",
            options={"A":"就绪态","B":"运行态","C":"阻塞态（等待态）","D":"终止态"},
            correct_answer="C",final_value="C",
            explanation="进程发出需要等待的阻塞式I/O请求后，当前不能继续占用CPU，进入阻塞态等待事件完成。I/O完成后通常转为就绪态，再由调度程序选择运行；请求本身不会使进程终止。",
            steps=[]),
        "derived_answer":"C",
        "method_evidence":[
            {"method":"process-state-transition","result":"运行进程发起阻塞I/O后，等待事件尚未完成，应从运行态转为阻塞态；完成后再到就绪态。"},
            {"method":"cpu-eligibility-check","result":"I/O等待期间进程不可运行但仍存活，故不是运行态或终止态；它也尚未具备CPU调度条件，故不是就绪态。"},
        ],
        "explanation_key_steps":[
            "等待磁盘I/O期间进程不能继续运行，因而离开运行态。",
            "事件完成前它尚不能参与CPU调度，处于阻塞/等待状态；完成后才回到就绪态。",
        ],
        "option_truth_table":{"A":False,"B":False,"C":True,"D":False},
        "skill_tags":["进程状态与转换","阻塞式I/O"],
    },
]


if __name__=="__main__":
    batch.main()
