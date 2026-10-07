<!-- kp:math.linear-algebra -->
<!-- knowledge-node-lesson:v3; code=math.linear-algebra -->
<!-- knowledge-lesson-quality:subject-textbook-draft-v3 -->
# 线性代数

## 章节导读与概念关系

线性代数不是一组孤立公式，而是用矩阵表达线性关系、用行列式判断方阵可逆性、用向量组描述解空间，再用特征结构与二次型研究变换。阅读时要把“计算对象—可用定理—条件—结论”连起来：行列式为零说明方阵不可逆；矩阵秩决定线性方程组解的维数；特征向量描述变换保持方向的向量；二次型的变量替换属于合同变换。相似与合同、向量相关与方程无解都不能混为一谈。

## 阅读路线

- [行列式](/knowledge/math.linear-algebra.determinant/lesson)
- [向量组](/knowledge/math.linear-algebra.exam.vector/lesson)
- [特征值与相似](/knowledge/math.linear-algebra.exam.eigen/lesson)
- [矩阵](/knowledge/math.linear-algebra.exam.matrix/lesson)
- [线性方程组](/knowledge/math.linear-algebra.exam.system/lesson)
- [二次型](/knowledge/math.linear-algebra.exam.quadratic/lesson)

## 代表性例题与逐步解答

**例题。** 解方程组 $x+y=3,\;2x-y=0$，并说明它与矩阵可逆性的关系。

**分析与解答。** 系数矩阵为 $A=\begin{pmatrix}1&1\\2&-1\end{pmatrix}$，右端为 $b=\begin{pmatrix}3\\0\end{pmatrix}$。其行列式为 $-1-2=-3\ne0$，故 $A$ 可逆且方程组有唯一解。由第二式 $y=2x$，代入第一式得 $3x=3$，于是 $(x,y)=(1,2)$。这里行列式只负责判断唯一性；实际求解仍可用消元。

## 阅读边界

父子节点表示课程组织关系，不是掌握度自动继承关系。请进入具体知识点页面阅读适用条件和完整推导；练习题从关联题库获取，本讲解不重复收录练习题。
