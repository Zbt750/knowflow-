<!-- kp:math.linear-algebra.determinant -->
<!-- knowledge-node-lesson:v3; code=math.linear-algebra.determinant -->
<!-- knowledge-lesson-quality:subject-textbook-draft-v3 -->
# 行列式

## 章节导读与概念关系

行列式是方阵对应的标量，不是把矩阵元素简单相加或相乘。它综合反映行（列）向量的线性独立性：行列式非零当且仅当方阵可逆。二阶行列式可直接算，三阶及以上常借助初等行变换、按行（列）展开或结构化简。使用行变换时必须同步记录行列式如何变化。

## 阅读路线

- [行列式的性质](/knowledge/math.linear-algebra.determinant.properties/lesson)
- [行列式](/knowledge/math.exam.f4e5ed0360ea/lesson)

## 代表性例题与逐步解答

**例题。** 计算 $D=\begin{vmatrix}1&2&0\\0&3&1\\0&0&-2\end{vmatrix}$，并判断对应矩阵是否可逆。

**分析与解答。** 这是上三角行列式，值等于主对角线元素的乘积：$D=1\cdot3\cdot(-2)=-6$。因 $D\ne0$，矩阵可逆。若为了计算把某行乘以 $k$，新行列式也乘以 $k$；不能忘记把这种变化换算回原行列式。

## 阅读边界

父子节点表示课程组织关系，不是掌握度自动继承关系。请进入具体知识点页面阅读适用条件和完整推导；练习题从关联题库获取，本讲解不重复收录练习题。
