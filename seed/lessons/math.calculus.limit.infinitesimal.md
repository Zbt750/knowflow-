<!-- kp:math.calculus.limit.infinitesimal -->
<!-- knowledge-node-lesson:v3; code=math.calculus.limit.infinitesimal -->
<!-- knowledge-lesson-quality:subject-textbook-draft-v3 -->
# 等价无穷小替换

## 直观概念、定义与适用条件

等价写作 $\alpha\sim\beta$，意思是同一趋近过程下 $\alpha/\beta\to1$。若商的其余部分极限适当存在，可将乘除结构中的因子替换；加减结构需要保留抵消后的误差，不能按每个加数随意替换。

## 例题分析与逐步解答

**例题一。** 求 $\lim_{x\to0}\sin(3x)/\tan(2x)$。

**解答。** 分子 $\sin(3x)\sim3x$，分母 $\tan(2x)\sim2x$，因此比值极限为 $3/2$。变量内的系数来自链式尺度，不能漏掉。

**例题二。** 求 $\lim_{x\to0}(1-\cos x)/x^2$。利用 $1-\cos x\sim x^2/2$，结果为 $1/2$。但 $\sin x-x$ 不能通过 $\sin x\sim x$ 化为零：其真实首项是 $-x^3/6$。

**总结。** 常用 $\ln(1+u)\sim u$、$e^u-1\sim u$、$(1+u)^a-1\sim au$（固定 $a\ne0$），都必须先检查 $u\to0$ 和实数定义域。

## 易错点与阅读总结

请先明确本页定义与适用条件，再沿例题的推导步骤理解方法；本页检查与反例用于区分结论成立的范围。练习题请从节点关联题库选择，本文件不重复收录练习卷。
