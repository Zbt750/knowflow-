"""Authored linear-algebra lesson pages for the existing knowledge-tree slice.

The selection follows the repository's actual math.linear-algebra tree and its
reference-only descendants. It deliberately excludes generated family nodes.
Pages are original teaching drafts; they do not verify exam answers or mappings.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.generate_knowledge_lessons import _all_nodes

QUALITY_MARKER = "<!-- knowledge-lesson-quality:subject-textbook-draft-v3 -->"


GUIDES: dict[str, tuple[str, str]] = {
    "math.linear-algebra": (
        r"线性代数不是一组孤立公式，而是用矩阵表达线性关系、用行列式判断方阵可逆性、用向量组描述解空间，再用特征结构与二次型研究变换。阅读时要把“计算对象—可用定理—条件—结论”连起来：行列式为零说明方阵不可逆；矩阵秩决定线性方程组解的维数；特征向量描述变换保持方向的向量；二次型的变量替换属于合同变换。相似与合同、向量相关与方程无解都不能混为一谈。",
        r"""**例题。** 解方程组 $x+y=3,\;2x-y=0$，并说明它与矩阵可逆性的关系。

**分析与解答。** 系数矩阵为 $A=\begin{pmatrix}1&1\\2&-1\end{pmatrix}$，右端为 $b=\begin{pmatrix}3\\0\end{pmatrix}$。其行列式为 $-1-2=-3\ne0$，故 $A$ 可逆且方程组有唯一解。由第二式 $y=2x$，代入第一式得 $3x=3$，于是 $(x,y)=(1,2)$。这里行列式只负责判断唯一性；实际求解仍可用消元。""",
    ),
    "math.linear-algebra.determinant": (
        r"行列式是方阵对应的标量，不是把矩阵元素简单相加或相乘。它综合反映行（列）向量的线性独立性：行列式非零当且仅当方阵可逆。二阶行列式可直接算，三阶及以上常借助初等行变换、按行（列）展开或结构化简。使用行变换时必须同步记录行列式如何变化。",
        r"""**例题。** 计算 $D=\begin{vmatrix}1&2&0\\0&3&1\\0&0&-2\end{vmatrix}$，并判断对应矩阵是否可逆。

**分析与解答。** 这是上三角行列式，值等于主对角线元素的乘积：$D=1\cdot3\cdot(-2)=-6$。因 $D\ne0$，矩阵可逆。若为了计算把某行乘以 $k$，新行列式也乘以 $k$；不能忘记把这种变化换算回原行列式。""",
    ),
    "math.linear-algebra.exam.vector": (
        r"向量组主题围绕线性组合、线性表示、相关性和秩展开。向量 $b$ 能由 $a_1,\ldots,a_m$ 线性表示，等价于方程 $Ax=b$ 有解，其中 $A$ 的列为这些向量。线性相关是存在不全为零的系数使组合为零；秩是最大线性无关子组所含向量数。分析前应先确认向量所在空间及它们按行还是按列组成矩阵。",
        r"""**例题。** 判断 $b=(3,1)^T$ 是否能由 $a_1=(1,1)^T,a_2=(1,-1)^T$ 线性表示。

**分析与解答。** 令 $c_1a_1+c_2a_2=b$，得到 $c_1+c_2=3$、$c_1-c_2=1$。相加得 $2c_1=4$，故 $c_1=2,c_2=1$。因此 $b=2a_1+a_2$。由于两列组成矩阵的行列式为 $-2\ne0$，表示系数还唯一。""",
    ),
    "math.linear-algebra.exam.eigen": (
        r"特征值问题研究 $Ax=\lambda x$ 且 $x\ne0$ 的方向；相似变换 $B=P^{-1}AP$ 则表示同一线性变换在不同基下的矩阵。可对角化意味着存在由特征向量组成的基。实 $n$ 阶矩阵有 $n$ 个互不相同的特征值时可对角化；有重根时须检查每个特征空间维数，不能只看特征多项式。",
        r"""**例题。** 设 $A=\begin{pmatrix}2&1\\0&3\end{pmatrix}$，求特征值并构造对角化。

**分析与解答。** 特征方程 $\det(A-\lambda I)=(2-\lambda)(3-\lambda)=0$，所以特征值为 $2,3$。对 $\lambda=2$，解 $(A-2I)x=0$ 得特征向量 $(1,0)^T$；对 $\lambda=3$，可取 $(1,1)^T$。令 $P=\begin{pmatrix}1&1\\0&1\end{pmatrix}$，则 $P$ 可逆，且 $AP=P\operatorname{diag}(2,3)$，所以 $P^{-1}AP=\operatorname{diag}(2,3)$。""",
    ),
    "math.linear-algebra.exam.matrix": (
        r"矩阵是线性映射和线性方程组的表示。加法、数乘要求同型；乘法要求前矩阵列数等于后矩阵行数，且通常 $AB\ne BA$。可逆性、秩、矩阵方程和矩阵幂是同一运算体系中的不同问题。计算前先标出维数，再看矩阵是否方阵、是否可逆、是否具有对角或分块结构。",
        r"""**例题。** 取 $A=\begin{pmatrix}1&1\\0&1\end{pmatrix}$、$B=\begin{pmatrix}1&0\\1&1\end{pmatrix}$，比较 $AB$ 与 $BA$。

**分析与解答。** 按“行乘列”计算，$AB=\begin{pmatrix}2&1\\1&1\end{pmatrix}$，而 $BA=\begin{pmatrix}1&1\\1&2\end{pmatrix}$。二者不相等，说明矩阵乘法不可交换；但结合律仍成立，且在维数允许时 $(AB)C=A(BC)$。把数的乘法交换律套到矩阵上会导致错误。""",
    ),
    "math.linear-algebra.exam.system": (
        r"线性方程组 $Ax=b$ 是否有解由 $r(A)$ 与 $r(A|b)$ 决定：两者相等时有解，不等时无解；有解时，若秩等于未知数个数则唯一，否则有自由变量并有无穷多解。齐次系统 $Ax=0$ 至少有零解，其解空间维数为未知数个数减 $r(A)$。这些结论来自高斯消元后的主元与自由变量。",
        r"""**例题。** 讨论 $\begin{cases}x+y+z=1\\2x+2y+2z=2\\x-y+z=0\end{cases}$ 的解的情况。

**分析与解答。** 第二行是第一行的两倍，不增加主元；第一、三行独立，所以系数矩阵秩为 $2$。增广列没有造成矛盾，故增广矩阵秩也为 $2$。未知数有 $3$ 个，秩小于未知数个数，因此有一个自由变量、无穷多解。第一式减第三式得 $2y=1$，所以 $y=1/2$；代入第一式得 $x+z=1/2$。令 $x=s$，则 $z=1/2-s$，通解为 $(s,1/2,1/2-s)$。""",
    ),
    "math.linear-algebra.exam.quadratic": (
        r"实二次型 $q(x)=x^TAx$ 只由对称部分 $\frac12(A+A^T)$ 决定，所以通常取 $A$ 为对称矩阵。可逆线性替换 $x=Cy$ 后矩阵变为 $C^TAC$，这是合同变换，不是相似变换。配方法适合逐步消去交叉项；实对称矩阵也可正交对角化。正定判别必须核对对称性及判据前提。",
        r"""**例题。** 化简 $q(x,y)=x^2+2xy+3y^2$，并判断正定性。

**分析与解答。** 配方得 $q=(x+y)^2+2y^2$。令 $u=x+y,v=y$，该变换可逆（$x=u-v,y=v$），于是 $q=u^2+2v^2$。对任意非零 $(x,y)$，变换后的 $(u,v)$ 仍非零，两个平方项系数均正，故 $q>0$，二次型正定。矩阵为 $\begin{pmatrix}1&1\\1&3\end{pmatrix}$，顺序主子式为 $1,2$，也符合正定判据。""",
    ),
}


DETAILS: dict[str, str] = {
    "math.linear-algebra.determinant.properties": r"""
行列式性质能把结构化计算化成少量合法操作。交换两行（列）变号；一行（列）乘 $k$，行列式乘 $k$；把一行的 $k$ 倍加到另一行，行列式不变。$n$ 阶方阵满足 $\det(kA)=k^n\det A$、$\det(AB)=\det A\det B$；若 $A$ 可逆，则 $\det(A^{-1})=1/\det A$。后两式要求方阵且维数匹配。

**例题。** 已知 $A$ 为三阶方阵，$\det A=-2$，求 $\det(2A)$、$\det(A^{-1})$ 及 $\det(A^TA)$。

**分析与逐步解答。** 1. 整个三阶矩阵乘 $2$ 相当于三行各乘 $2$，所以 $\det(2A)=2^3\det A=-16$。2. $\det A\ne0$，故 $A$ 可逆，$\det(A^{-1})=1/(-2)=-1/2$。3. $\det(A^TA)=\det(A^T)\det A=(\det A)^2=4$。注意“某一行乘 $2$”只使行列式乘 $2$，而“整个三阶矩阵乘 $2$”使其乘 $8$。

**易错边界。** 行倍加不变、行交换变号、行倍乘变化三者不可混；$\det(A+B)$ 一般不能拆成 $\det A+\det B$。
""",
    "math.exam.f4e5ed0360ea": r"""
行列式的展开按一行或一列进行。$n$ 阶行列式沿第 $i$ 行展开为 $\sum_j a_{ij}C_{ij}$，其中代数余子式 $C_{ij}=(-1)^{i+j}M_{ij}$，$M_{ij}$ 是删去第 $i$ 行、第 $j$ 列后的余子式。遇到三角形结构先用对角线乘积；展开时优先选零多的一行（列），符号棋盘从左上角正号开始。

**例题。** 计算 $D=\begin{vmatrix}1&2&0\\3&0&1\\0&1&2\end{vmatrix}$。

**分析与逐步解答。** 第一行有一个零，沿第一行展开：$D=1\begin{vmatrix}0&1\\1&2\end{vmatrix}-2\begin{vmatrix}3&1\\0&2\end{vmatrix}+0$。第一个二阶行列式为 $-1$，第二个为 $6$，所以 $D=-1-12=-13$。用 Sarrus 法或消元可交叉检查。$D\ne0$，对应方阵可逆。

**易错边界。** 展开符号是 $(-1)^{i+j}$，不是把余子式本身直接相加；矩阵行列式只对方阵定义。
""",
    "math.exam.44eab8b0d00b": r"""
“$b$ 可由向量组线性表示”就是存在系数 $c_j$ 使 $b=\sum_j c_ja_j$。把向量按列组成 $A$ 后，这是求解 $Ac=b$；有解等价于 $r(A)=r(A|b)$。当列向量线性无关时，表示系数至多一组；若相关，可能不唯一。实际操作用增广矩阵消元。

**例题。** $a_1=(1,0,1)^T,a_2=(0,1,1)^T,a_3=(1,1,2)^T$，判断 $b=(2,1,3)^T$ 能否表示，系数是否唯一。

**分析与逐步解答。** 由 $a_3=a_1+a_2$ 可知三列相关。设 $c_1a_1+c_2a_2+c_3a_3=b$，比较分量得到 $c_1+c_3=2,c_2+c_3=1,c_1+c_2+2c_3=3$。第三式是前两式之和，系统相容。令 $c_3=t$，则 $c_1=2-t,c_2=1-t$，故有无穷多组表示；取 $t=0$ 即 $b=2a_1+a_2$。

**易错边界。** 相关只说明系数表示不唯一，不代表目标向量不能表示；相容条件仍应通过秩或消元确认。
""",
    "math.exam.08a5efb8a98d": r"""
矩阵 $A,B$ 相似是存在可逆矩阵 $P$ 使 $B=P^{-1}AP$。相似保留特征多项式、行列式、迹和秩，但一般不保留每个矩阵元素。对角化是相似到对角矩阵；$P$ 的列应按对角矩阵中特征值的顺序排列为对应特征向量。可对角化当且仅当能找到 $n$ 个线性无关特征向量。

**例题。** 对 $A=\begin{pmatrix}2&1\\0&3\end{pmatrix}$ 构造相似对角矩阵。

**分析与逐步解答。** 特征值为 $2,3$。对应特征向量可取 $v_1=(1,0)^T,v_2=(1,1)^T$。它们组成 $P=\begin{pmatrix}1&1\\0&1\end{pmatrix}$，$\det P=1$，故可逆。计算 $AP=P\begin{pmatrix}2&0\\0&3\end{pmatrix}$，因此 $P^{-1}AP=\operatorname{diag}(2,3)$。若把特征向量顺序交换，必须同时交换对角线上特征值顺序。

**易错边界。** 相似用 $P^{-1}AP$，二次型换元用 $P^TAP$；二者含义和保持量不同。
""",
    "math.exam.985c26775327": r"""
矩阵加法与数乘逐项进行，矩阵乘法按行乘列。乘积 $AB$ 的定义要求 $A$ 的列数等于 $B$ 的行数；一般不可交换，但可结合，且乘法对加法满足分配律。转置满足 $(AB)^T=B^TA^T$。矩阵运算常表示线性变换复合，先做右侧变换再做左侧变换。

**例题。** 令 $A=\begin{pmatrix}1&1\\0&1\end{pmatrix},B=\begin{pmatrix}1&0\\1&1\end{pmatrix}$，求 $AB$、$BA$ 并说明顺序。

**分析与逐步解答。** $AB=\begin{pmatrix}2&1\\1&1\end{pmatrix}$，$BA=\begin{pmatrix}1&1\\1&2\end{pmatrix}$。因此 $AB\ne BA$。若列向量 $x$ 先经 $B$ 再经 $A$，结果是 $A(Bx)=(AB)x$；矩阵乘积的书写顺序与作用顺序相反。

**易错边界。** 不要将数的交换律照搬到矩阵；维数不匹配时乘积甚至没有定义。$AB=0$ 也不能推出 $A=0$ 或 $B=0$。
""",
    "math.exam.c106a40cda48": r"""
线性方程组统一写为 $Ax=b$。高斯消元用可逆初等行变换化为阶梯形，不改变解集。无解的典型信号是出现 $0=c\;(c\ne0)$；主元变量由非零行决定，非主元变量可自由取值。非齐次系统相容时，通解等于一个特解加齐次系统 $Ax=0$ 的通解。

**例题。** 解 $x+y+z=1,\;x-y+z=0$。

**分析与逐步解答。** 两式相减得 $2y=1$，故 $y=1/2$。代回任一式得 $x+z=1/2$。令自由变量 $z=t$，则 $x=1/2-t$，所以通解为 $(x,y,z)=(1/2-t,1/2,t)$。两个方程独立、三个未知数，正好有一个自由参数。代回两式均成立。

**易错边界。** 方程数少于未知数不一定无解；秩不足且相容时是无穷多解。写通解时要明确自由参数并避免重复参数化。
""",
    "math.exam.9bda63607d7e": r"""
特征值 $\lambda$ 与非零特征向量 $x$ 满足 $(A-\lambda I)x=0$。特征值由 $\det(A-\lambda I)=0$ 求出；对应特征空间是齐次方程的解空间。不同特征值的特征向量线性无关。实对称矩阵的特征值为实数，并可由正交矩阵对角化。

**例题。** 求 $A=\begin{pmatrix}2&1\\0&3\end{pmatrix}$ 的特征值和各特征空间。

**分析与逐步解答。** $\det(A-\lambda I)=(2-\lambda)(3-\lambda)$，特征值为 $2,3$。当 $\lambda=2$ 时方程给 $y=0$，特征空间为 $\operatorname{span}\{(1,0)^T\}$；当 $\lambda=3$ 时 $-x+y=0$，特征空间为 $\operatorname{span}\{(1,1)^T\}$。两向量独立，因此矩阵可对角化。

**易错边界。** 特征向量不能取零向量；求特征空间要解齐次系统，而不是只报特征值。特征值的代数重数大于一时，需另算几何重数。
""",
    "math.exam.6df0d75f1b07": r"""
伴随矩阵 $A^*$ 的第 $(i,j)$ 元是代数余子式 $C_{ji}$，即余子式矩阵转置。它满足 $AA^*=A^*A=(\det A)I$。因此 $\det A\ne0$ 时 $A^{-1}=A^*/\det A$；若 $\det A=0$，这个逆矩阵公式不能使用。大矩阵求逆时高斯消元通常更方便。

**例题。** 用伴随矩阵求 $A=\begin{pmatrix}1&2\\3&4\end{pmatrix}$ 的逆。

**分析与逐步解答。** $\det A=4-6=-2$。二阶情形 $A^*=\begin{pmatrix}4&-2\\-3&1\end{pmatrix}$。于是 $A^{-1}=A^*/(-2)=\begin{pmatrix}-2&1\\3/2&-1/2\end{pmatrix}$。直接相乘可得 $AA^{-1}=I$。

**易错边界。** 伴随矩阵的余子式下标要转置；非零行列式是使用逆矩阵公式的前提。$A^*$ 存在于奇异方阵情形，但此时不代表 $A$ 可逆。
""",
    "math.exam.f29397bf3b27": r"""
二次型是关于变量的齐次二次多项式，可唯一写成 $x^TAx$，其中 $A$ 通常取对称矩阵。交叉项 $2a_{ij}x_ix_j$ 对应矩阵中两个位置均为 $a_{ij}$。配方法通过可逆线性替换消交叉项；对称矩阵的正交对角化给出另一条路径。正定性看任意非零向量上的函数值，而不是只看某个方向。

**例题。** 把 $q(x,y)=2x^2+4xy+5y^2$ 写成矩阵形式并判断正定。

**分析与逐步解答。** $A=\begin{pmatrix}2&2\\2&5\end{pmatrix}$，因 $x^TAx=2x^2+4xy+5y^2$。配方为 $2(x+y)^2+3y^2$，对非零 $(x,y)$ 至少一项非零，故 $q>0$，正定。也可由顺序主子式 $2>0$、$\det A=6>0$ 判定。

**易错边界。** 交叉项系数要平均分到两个对称位置；正定判据和半正定判据不同。
""",
    "math.exam.7d6f5725a5ab": r"""
向量组线性相关是存在不全为零的系数使线性组合为零；否则线性无关。把向量组成矩阵的列，线性无关等价于齐次方程只有零解，等价于列秩等于向量个数。若向量个数超过空间维数，必相关。包含零向量的向量组必相关。

**例题。** 判断 $a_1=(1,0,1)^T,a_2=(0,1,1)^T,a_3=(1,1,2)^T$ 是否线性相关。

**分析与逐步解答。** 观察 $a_3=a_1+a_2$，于是 $a_1+a_2-a_3=0$，系数 $(1,1,-1)$ 不全为零，故相关。前两个向量不成比例，彼此独立，所以该组秩为 $2$，可选 $a_1,a_2$ 为极大无关组。

**易错边界。** “两个向量不成比例”只足以判断两个非零向量独立，不能直接处理三个及以上向量；应建立齐次方程或计算秩。
""",
    "math.exam.0aad93648d60": r"""
矩阵的秩是其列空间（也等于行空间）的维数，是最大非零子式的阶数，也是行阶梯形中主元数。行变换可以用于求秩，但行变换后的某些列不再是原矩阵对应的向量；若要挑选原矩阵的极大无关列，应按主元列位置回到原矩阵取列。

**例题。** 求 $A=\begin{pmatrix}1&2&3\\2&4&6\\1&1&1\end{pmatrix}$ 的秩，并给出一组原矩阵的极大无关列。

**分析与逐步解答。** 第二行是第一行的两倍，因此 $r(A)\le2$。第一、三行独立，故 $r(A)=2$。第一列 $(1,2,1)^T$ 与第三列 $(3,6,1)^T$ 不成比例，因此它们独立，可构成极大无关列组。第二列恰为第一列的两倍。

**易错边界。** 行变换可改列向量本身，不能把变换后矩阵的主元列直接当成原向量；应保留主元列序号。
""",
    "math.exam.f99711e0ea65": r"""
置换矩阵由单位矩阵交换行（或列）得到，每行每列恰有一个 $1$，其余为零。左乘置换矩阵重排矩阵的行，右乘重排列。置换矩阵正交，$P^{-1}=P^T$；其行列式为对应置换的奇偶性，偶置换为 $1$，奇置换为 $-1$。

**例题。** 令 $P=\begin{pmatrix}0&1&0\\1&0&0\\0&0&1\end{pmatrix}$，求 $P^2$、$P^{-1}$ 和 $\det P$。

**分析与逐步解答。** $P$ 交换前两行两次后复原，所以 $P^2=I$，因此 $P^{-1}=P$。它对应一次换位，是奇置换，故 $\det P=-1$。对任意矩阵 $A$，$PA$ 交换 $A$ 的前两行；$AP$ 则交换前两列。

**易错边界。** 左乘与右乘作用对象不同；一般置换矩阵仍可逆，但不一定等于自身转置以外的任意矩阵。
""",
    "math.exam.8b6ba0b9a789": r"""
伴随矩阵和逆矩阵通过恒等式 $AA^*=(\det A)I$ 联系。行列式非零时可除以行列式得到逆矩阵；行列式为零时仅能说明该方阵奇异，不能继续除。伴随矩阵中的代数余子式需要转置排列，这也是二阶公式 $\begin{pmatrix}a&b\\c&d\end{pmatrix}^*=\begin{pmatrix}d&-b\\-c&a\end{pmatrix}$ 的来源。

**例题。** 对 $A=\begin{pmatrix}2&1\\1&1\end{pmatrix}$ 求 $A^*$ 并验证逆矩阵。

**分析与逐步解答。** $\det A=1$，伴随矩阵为 $A^*=\begin{pmatrix}1&-1\\-1&2\end{pmatrix}$，故 $A^{-1}=A^*$。相乘第一行为 $(2-1,-2+2)=(1,0)$，第二行为 $(1-1,-1+2)=(0,1)$，得到单位矩阵。

**易错边界。** 不能把余子式矩阵和伴随矩阵混同；一般阶数必须转置代数余子式表。
""",
    "math.exam.36050d277510": r"""
矩阵方程常化为若干个线性方程组。$AX=B$ 有解当且仅当 $B$ 的每一列都属于 $A$ 的列空间，即 $r(A)=r(A|B)$；未知矩阵 $X$ 的每一列分别解 $Ax=b_j$。若 $A$ 可逆则唯一解为 $X=A^{-1}B$；若奇异，则需逐列检查相容性及自由变量。

**例题。** $A=\begin{pmatrix}1&1\\2&2\end{pmatrix}$、$B=\begin{pmatrix}1&2\\2&4\end{pmatrix}$，判断 $AX=B$ 是否有解，并求出一组解。

**分析与逐步解答。** $A$ 的第二行是第一行两倍，$r(A)=1$。$B$ 的两列分别是 $(1,2)^T$ 与 $(2,4)^T$，都在 $A$ 的列空间中，故相容。对第一列可取 $x_1=(1,0)^T$，对第二列取 $x_2=(2,0)^T$，于是 $X=\begin{pmatrix}1&2\\0&0\end{pmatrix}$ 满足 $AX=B$。解不唯一，因为 $A$ 奇异。

**易错边界。** $A$ 奇异并不必然无解；$AX=B$ 要逐列看相容，不是只看一个右端列。
""",
    "math.exam.9a1731a929ab": r"""
线性表示的计算可转成增广矩阵 $[a_1\;\cdots\;a_m\mid b]$ 的消元问题。若相容，求出的系数给出一个表示；若系数解唯一，当且仅当表示向量组线性无关。出现自由变量意味着存在多个系数组合表示同一个目标向量。

**例题。** $a_1=(1,1)^T,a_2=(1,-1)^T,a_3=(2,0)^T$，求 $b=(3,1)^T$ 的一组线性表示，并判断是否唯一。

**分析与逐步解答。** 因 $a_3=a_1+a_2$，向量组相关。令 $c_1a_1+c_2a_2+c_3a_3=b$，得 $c_1+c_2+2c_3=3$、$c_1-c_2=1$。取 $c_3=0$ 解得 $c_1=2,c_2=1$，所以 $b=2a_1+a_2$。又因 $c_3=t$ 可得到一族解，具体为 $c_1=2-t,c_2=1-t$，故表示不唯一。

**易错边界。** 找到一组系数只证明“能表示”，并不证明唯一；唯一性需检查齐次系统的自由度。
""",
    "math.exam.712e07e16572": r"""
矩阵恒等式的证明要尊重乘法顺序和逆矩阵存在条件。常用工具包括结合律、分配律、转置规则、$A^{-1}A=I$、行列式判据及把矩阵多项式作用于特征向量。矩阵不交换时不能随意移动因子；$AB=AC$ 只有在可左消去（如 $A$ 可逆）时才能推出 $B=C$。

**例题。** 设 $A$ 可逆，证明 $(A^{-1}+B)A=I+BA$，并说明为何不能写成 $I+AB$。

**分析与逐步解答。** 用分配律展开：$(A^{-1}+B)A=A^{-1}A+BA=I+BA$。若要换成 $I+AB$，需要 $BA=AB$，而一般矩阵不满足交换律。取上一页中的非交换矩阵即可构造反例。因此每一步都应注明使用的是结合律还是可交换性；后者不能默认。

**易错边界。** 矩阵消去和标量消去不同；若从 $XA=YA$ 推 $X=Y$，需要 $A$ 可逆并在右侧乘 $A^{-1}$。
""",
    "math.exam.90bbbeb58b4a": r"""
矩阵幂零是存在正整数 $k$ 使 $N^k=0$。幂零矩阵的全部特征值只能是 $0$：若 $Nv=\lambda v$ 且 $v\ne0$，则 $0=N^kv=\lambda^kv$，所以 $\lambda=0$。反过来，所有特征值为零只说明特征多项式为 $\lambda^n$，在复数域上由 Cayley–Hamilton 可推出 $A^n=0$，因而幂零；若课程暂不使用该定理，可直接从结构或幂次验证。

**例题。** 对 $N=\begin{pmatrix}0&1&0\\0&0&1\\0&0&0\end{pmatrix}$ 验证幂零性并求特征值。

**分析与逐步解答。** 直接乘得 $N^2=\begin{pmatrix}0&0&1\\0&0&0\\0&0&0\end{pmatrix}$，再乘一次得到 $N^3=0$，所以 $N$ 幂零。$N$ 为上三角矩阵，对角线全为零，特征多项式为 $\lambda^3$，特征值只有 $0$（代数重数为三）。但它不等于零矩阵，且 $N^2\ne0$。

**易错边界。** “特征值全零”不代表矩阵本身为零，也不代表可对角化；该例只有一个线性无关特征向量。
""",
    "math.exam.7af99f485eff": r"""
二次型经可逆变量替换 $x=Cy$ 后变成 $y^T(C^TAC)y$，称合同变换。对称实矩阵可合同化为只含平方项的对角形；惯性定理指出正、负、零平方项个数不随可逆合同变换改变。合同通常不保留特征值数值；相似变换 $P^{-1}AP$ 才保留特征多项式。配方法应确保每次替换可逆。

**例题。** 化简 $q=x^2+2xy+2y^2$ 并说明惯性指数。

**分析与逐步解答。** $q=(x+y)^2+y^2$。令 $u=x+y,v=y$，矩阵变换可逆，故 $q=u^2+v^2$。规范形有两个正平方项、没有负或零平方项，惯性指数为 $(2,0,0)$，原二次型正定。若某一步变量替换不可逆，就不能保证变量空间一一对应，也不能据此判断原型的正定性。

**易错边界。** 不能把合同等同相似：合同分类看惯性指数，不要求特征值保持不变。
""",
    "math.exam.8d8ad14b2a44": r"""
向量组的秩等于极大线性无关组所含向量数。极大无关组不是唯一的，但任一组都含有恰好 $r$ 个向量，并能表示原向量组中其余向量。行化简找主元列时，主元列位置可以确定原矩阵哪些列独立；所选向量须从原矩阵取出。

**例题。** 对 $a_1=(1,0,1)^T,a_2=(0,1,1)^T,a_3=(1,1,2)^T$ 找一组极大无关组。

**分析与逐步解答。** 有 $a_3=a_1+a_2$，所以三向量秩至多为二。$a_1,a_2$ 不成比例且线性无关，因此秩至少为二。故秩为二，$\{a_1,a_2\}$ 是一组极大无关组，并且 $a_3$ 可由它们表示。另选 $\{a_1,a_3\}$ 也可以，但不能选三者全体作为无关组。

**易错边界。** 极大表示“不能再添加而保持无关”，不是元素个数最大到向量组总数；选择主元列后回到原矩阵取列。
""",
    "math.exam.0949f5ff08f9": r"""
矩阵分解把一个线性变换拆成若干个结构简单的矩阵乘积；矩阵幂表示变换重复作用。若 $A=PDP^{-1}$，则 $A^n=PD^nP^{-1}$，这要求 $P$ 可逆且确实有相似对角化。不能对每个元素分别取 $n$ 次方来代替矩阵乘法。

**例题。** 设 $A=\begin{pmatrix}2&1\\0&3\end{pmatrix}$，利用对角化求 $A^n$（$n\ge1$）。

**分析与逐步解答。** 可取特征向量矩阵 $P=\begin{pmatrix}1&1\\0&1\end{pmatrix}$，并有 $D=\operatorname{diag}(2,3)$、$A=PDP^{-1}$。所以 $A^n=PD^nP^{-1}$。先算 $D^n=\operatorname{diag}(2^n,3^n)$，再按序相乘得 $A^n=\begin{pmatrix}2^n&3^n-2^n\\0&3^n\end{pmatrix}$。取 $n=2$ 得 $\begin{pmatrix}4&5\\0&9\end{pmatrix}$，直接计算 $A^2$ 相符。

**易错边界。** 只把特征值取幂而忘记乘回 $P$ 与 $P^{-1}$，会丢失原基下的矩阵；若矩阵不可对角化，不能使用此分解。
""",
}


def linear_algebra_nodes() -> list[dict]:
    nodes = _all_nodes()[0]
    selected = [
        node
        for node in nodes
        if (
            node["code"] == "math.linear-algebra"
            or node["code"].startswith("math.linear-algebra.")
            or (
                node["code"].startswith("math.exam.")
                and (node.get("parent_code") or "").startswith("math.linear-algebra")
            )
        )
        and ".family." not in node["code"]
    ]
    return selected


def render_pages() -> dict[str, str]:
    nodes = linear_algebra_nodes()
    codes = {node["code"] for node in nodes}
    parents = {node.get("parent_code") for node in nodes}
    pages: dict[str, str] = {}
    for node in nodes:
        code, name = node["code"], node["name"]
        header = (
            f"<!-- kp:{code} -->\n<!-- knowledge-node-lesson:v3; code={code} -->\n"
            f"{QUALITY_MARKER}\n# {name}\n\n"
        )
        if code in parents:
            guide, example = GUIDES[code]
            children = [item for item in nodes if item.get("parent_code") == code]
            links = "\n".join(f"- [{child['name']}](/knowledge/{child['code']}/lesson)" for child in children)
            body = (
                f"## 章节导读与概念关系\n\n{guide}\n\n## 阅读路线\n\n{links}\n\n"
                f"## 代表性例题与逐步解答\n\n{example}\n\n"
                "## 阅读边界\n\n父子节点表示课程组织关系，不是掌握度自动继承关系。请进入具体知识点页面阅读适用条件和完整推导；练习题从关联题库获取，本讲解不重复收录练习题。"
            )
        else:
            raw = DETAILS[code].strip()
            if "**例题。**" not in raw or "**分析与逐步解答。**" not in raw:
                raise ValueError(f"missing_topic_specific_worked_example:{code}")
            body = (
                "## 概念、定义与适用条件\n\n"
                + raw
                + "\n\n## 阅读总结\n\n"
                "请在练习中先写出适用条件和关键推导，再核对结果；关联真题由题库提供，本讲解不重复收录练习题。"
            )
        pages[f"{code}.md"] = header + body.strip() + "\n"
    if codes != {name[:-3] for name in pages}:
        raise AssertionError("lesson_page_coverage_mismatch")
    return pages


def main() -> None:
    # Output payload for applying reviewed pages with a normal patch-based edit.
    pages = render_pages()
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else len(pages)
    result = []
    for name, new in list(pages.items())[start : start + count]:
        path = PROJECT_ROOT / "seed" / "lessons" / name
        result.append({"name": name, "old": path.read_text(encoding="utf-8"), "new": new})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
