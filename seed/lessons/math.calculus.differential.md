<!-- kp:math.calculus.differential -->
<!-- knowledge-node-lesson:v3; code=math.calculus.differential -->
<!-- knowledge-lesson-quality:subject-textbook-draft-v3 -->
# 一元函数微分学

## 章节导读与概念关系

本章从变化率的定义走向计算与应用。链式法则是复合函数、反函数和隐函数求导的共同基础；中值定理连接一个区间的总体变化与某点的导数；导数符号用于单调性和极值，二阶导及凹凸变化用于拐点和曲率。可导不是连续的同义词，驻点也不是极值的同义词。

## 阅读路线

- [隐函数求导](/knowledge/math.calculus.differential.implicit/lesson)
- [导数的应用](/knowledge/math.exam.9578b3defcb0/lesson)
- [曲线的凹凸性、拐点及渐近线](/knowledge/math.exam.f37948c82a05/lesson)
- [导数与微分的计算](/knowledge/math.exam.de439863790e/lesson)
- [函数的单调性、极值与最值](/knowledge/math.exam.de02b85cba3d/lesson)
- [微分中值定理](/knowledge/math.exam.4586eb88acb7/lesson)
- [导数与微分的概念](/knowledge/math.exam.547f1fa49cd2/lesson)
- [方程根的存在性与个数](/knowledge/math.exam.0318406f8b47/lesson)
- [不等式的证明](/knowledge/math.exam.68217a446e4c/lesson)
- [极值定义](/knowledge/math.exam.bc1427755983/lesson)
- [凹凸函数与割线斜率单调性](/knowledge/math.exam.423bee85b09f/lesson)
- [反函数及其导数](/knowledge/math.exam.3e373cbe2c92/lesson)
- [隐函数曲线曲率与曲率半径](/knowledge/math.exam.f67ee0d0080c/lesson)
- [曲线拐点](/knowledge/math.exam.79c96a83b3ff/lesson)

## 代表性概念与例题

导数是差商极限 $f'(a)=\lim_{h\to0}[f(a+h)-f(a)]/h$。可导时实际增量满足 $\Delta y=f'(a)h+o(h)$，线性主部 $dy=f'(a)dx$ 称微分。可导蕴含连续，连续不蕴含可导。

**例题。** 不用求导表，求 $f(x)=x^2$ 在 $a$ 处的导数，并用微分估计 $2.01^2$。

**分析与解答。** 差商为 $[(a+h)^2-a^2]/h=2a+h$，令 $h\to0$ 得 $f'(a)=2a$。在 $a=2$、$h=0.01$ 时，$dy=4\times0.01=0.04$，估计值为 $4.04$。真实值 $4.0401$，误差 $h^2=0.0001$ 与增量相比是高阶小量。

**易错。** $dy$ 不等于任意步长下的精确 $\Delta y$。对 $|x|$ 在零的左右差商分别是 $-1,1$，所以虽连续却无双侧导数。导数为零也不说明函数在附近恒定。
