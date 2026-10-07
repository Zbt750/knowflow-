<!-- kp:math.calculus.limit -->
<!-- knowledge-node-lesson:v3; code=math.calculus.limit -->
<!-- knowledge-lesson-quality:subject-textbook-draft-v3 -->
# 极限与连续

## 章节导读与概念关系

极限先回答函数值接近哪里，连续再要求该趋势接到实际点值。数列极限需要讨论序列，不要直接搬用函数求导。遇到函数极限先代入识别结构，再比较有理化、基本极限、等价无穷小、泰勒和洛必达的条件；抵消题应保留高阶项。

## 阅读路线

- [洛必达法则](/knowledge/math.calculus.limit.lhopital/lesson)
- [等价无穷小替换](/knowledge/math.calculus.limit.infinitesimal/lesson)
- [函数的连续性与间断点的类型](/knowledge/math.exam.71a29108dd89/lesson)
- [确定极限中的参数](/knowledge/math.exam.e90535214807/lesson)
- [函数极限的计算](/knowledge/math.exam.c5c672022b7f/lesson)
- [无穷小量](/knowledge/math.exam.cdaedae1e143/lesson)
- [泰勒公式](/knowledge/math.exam.167393e991a4/lesson)
- [反三角函数与泰勒展开](/knowledge/math.exam.a24681a8ee59/lesson)
- [极限计算](/knowledge/math.exam.547ca6df680c/lesson)
- [等价无穷小与泰勒展开](/knowledge/math.exam.c1948d9cc280/lesson)

## 代表性概念与例题

连续的意思不是图像看起来平滑，而是函数值与附近趋势接得上：在定义域内点 $a$，需要 $\lim_{x\to a}f(x)=f(a)$；端点用相应单侧极限。判断间断点时先分别求左右极限，再比较点值。左右极限有限但不等是跳跃间断；两侧相等却缺少或不等于点值是可去间断；无穷或振荡导致有限单侧极限不存在，属于第二类间断。

**例题。** 设 $f(x)=\sin x/x$（$x\ne0$），$f(0)=c$，求连续时的 $c$。

**分析与解答。** 第一步，点值是 $c$，但点值不参与去心极限。第二步，左右两侧都有 $\sin x/x\to1$，所以两侧极限相同。第三步，连续要求点值等于该极限，故 $c=1$。若 $c=2$，极限仍存在，但原函数在零处有可去间断。

**反例与检查。** $\operatorname{sgn}x$ 在零两侧极限为 $-1,1$，改一个点值不能修复跳跃；$\sin(1/x)$ 两侧振荡也不能补一个数变连续。连续不保证可导，$|x|$ 在零处连续却不可导。
