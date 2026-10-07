<!-- kp:math.linear-algebra.determinant.properties -->
<!-- knowledge-node-lesson:v3; code=math.linear-algebra.determinant.properties -->
<!-- knowledge-lesson-quality:subject-textbook-draft-v3 -->
# 行列式的性质

## 概念、定义与适用条件

行列式性质能把结构化计算化成少量合法操作。交换两行（列）变号；一行（列）乘 $k$，行列式乘 $k$；把一行的 $k$ 倍加到另一行，行列式不变。$n$ 阶方阵满足 $\det(kA)=k^n\det A$、$\det(AB)=\det A\det B$；若 $A$ 可逆，则 $\det(A^{-1})=1/\det A$。后两式要求方阵且维数匹配。

**例题。** 已知 $A$ 为三阶方阵，$\det A=-2$，求 $\det(2A)$、$\det(A^{-1})$ 及 $\det(A^TA)$。

**分析与逐步解答。** 1. 整个三阶矩阵乘 $2$ 相当于三行各乘 $2$，所以 $\det(2A)=2^3\det A=-16$。2. $\det A\ne0$，故 $A$ 可逆，$\det(A^{-1})=1/(-2)=-1/2$。3. $\det(A^TA)=\det(A^T)\det A=(\det A)^2=4$。注意“某一行乘 $2$”只使行列式乘 $2$，而“整个三阶矩阵乘 $2$”使其乘 $8$。

**易错边界。** 行倍加不变、行交换变号、行倍乘变化三者不可混；$\det(A+B)$ 一般不能拆成 $\det A+\det B$。

## 阅读总结

请在练习中先写出适用条件和关键推导，再核对结果；关联真题由题库提供，本讲解不重复收录练习题。
