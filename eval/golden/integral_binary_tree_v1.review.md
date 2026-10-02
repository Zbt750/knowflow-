# Golden Learning Slice · integral-binary-tree v1

这是人工核验清单，不是已核验题库。数学二与 408 各一个小范围原创合成专题；不是历年真题。
自动验算和判题测试不能把 GENERATED / UNVERIFIED 自动变成 VERIFIED。

资产哈希：`392414dee214ccd4ab61ced03ac35ea6de6aac5011c2b30e7a7a3fba908f5909`

逐题核对题干、选项唯一性、标准答案、解析、知识映射、判题方式和发布来源。
数值最终答案判对不代表过程正确；证明、符号表达式和算法题不得强行数值评分。

## 定积分的计算（math2）

节点：`math.exam.c431f98f817c`；讲解状态：UNVERIFIED。
讲解：`seed/lessons/math.exam.c431f98f817c.md`；SHA256：`8b6b88285be179ae818d500853672e2aed4b73cd761818aac5f85ff89aa0a57d`。

### M01 · fill_blank · basic

计算定积分 $\int_0^1 x^2\,dx$，只提交最终数值。

候选答案：1/3

候选解析：原函数为 x³/3，代入 1 和 0 得 1/3。

技能标签：幂函数积分；估计 3 分钟（未进行学习耗时校准）。
拟用判题：numeric_final；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`28325c98f22a6915fafb3455e40eb8335ee11b1597b38752bd89236739499c03`。
判题协议探针：4 个，通过（不等于内容通过）。

### M02 · single_choice · basic

定积分 $\int_{-1}^1 x^3\,dx$ 的值是？

- A. 0
- B. 1/2
- C. -1/2
- D. 1

候选答案：A

候选解析：x³ 在对称区间连续且为奇函数，因此积分为 0。

技能标签：对称性、适用条件；估计 2 分钟（未进行学习耗时校准）。
拟用判题：single_choice；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`0c269f7b8a3b90ab43ec2676e3381d5264176f2672af88f099fafb398689ecde`。
判题协议探针：4 个，通过（不等于内容通过）。

### M03 · calculation · typical

计算 $\int_0^2(3x^2+1)\,dx$，只提交最终数值。

候选答案：10

候选解析：原函数为 x³+x，代入上下限得 8+2=10。

技能标签：直接积分；估计 4 分钟（未进行学习耗时校准）。
拟用判题：numeric_final；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`811b244984421feaefa42b709797172d908c5df55ac8479ad55286a22abf44b6`。
判题协议探针：4 个，通过（不等于内容通过）。

### M04 · calculation · variant

计算 $\int_0^1 2x(x^2+1)\,dx$，只提交最终数值。

候选答案：3/2

候选解析：令 u=x²+1，du=2x dx，上下限为 1 和 2，积分等于 (4-1)/2=3/2。也可展开逐项积分。

技能标签：换元积分、上下限；估计 5 分钟（未进行学习耗时校准）。
拟用判题：numeric_final；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`12d33caf02dca49f27af61bdfdd3dbe2c1b936161352238353940cc4d8f49153`。
判题协议探针：4 个，通过（不等于内容通过）。

### M05 · calculation · typical

计算 $\int_0^1 x(1-x)\,dx$，只提交最终数值。

候选答案：1/6

候选解析：展开为 x-x²，积分得 1/2-1/3=1/6。

技能标签：直接积分、展开；估计 4 分钟（未进行学习耗时校准）。
拟用判题：numeric_final；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`72adcd1350ebf2065273c44bf18424b95bab1e9b05cb01fd53dbea67a795b714`。
判题协议探针：4 个，通过（不等于内容通过）。

### M06 · calculation · variant

计算 $\int_{-1}^1 |x|\,dx$，只提交最终数值。

候选答案：1

候选解析：分成 [-1,0] 和 [0,1]，分别积分 -x 和 x，结果为 1/2+1/2=1。

技能标签：分段积分、对称性；估计 5 分钟（未进行学习耗时校准）。
拟用判题：numeric_final；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`76bd8e34634ee332dfcbd510263f378583c7a5013172f43f64b439a2d78d1da5`。
判题协议探针：4 个，通过（不等于内容通过）。

### M07 · calculation · typical

计算 $\int_1^2 dx/x$，提交精确表达式（不要求近似小数）。

候选答案：ln(2)

候选解析：积分区间内 x>0，原函数为 ln x，所以结果为 ln 2。当前数值比较器不支持这种符号判等，须保留为未机器判定。

技能标签：对数积分、判题边界；估计 5 分钟（未进行学习耗时校准）。
拟用判题：不自动判分；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`7bdad1560d70414d52c39b561dfbacd8b9d013a058284ee163c805cc2e4e952a`。
判题协议探针：2 个，通过（不等于内容通过）。

### M08 · proof · comprehensive

设 a>0，f 在 [-a,a] 上连续且为奇函数，证明 $\int_{-a}^a f(x)\,dx=0$。

候选答案：将负半区间令 x=-t，得到该段积分为 -∫₀ᵃf(t)dt，与正半区间相消。

候选解析：连续性保证积分存在。由奇函数性质 f(-t)=-f(t)，负半段积分等于正半段积分的相反数；不能只输入 0 就当作证明完成。

技能标签：对称性、证明条件；估计 8 分钟（未进行学习耗时校准）。
拟用判题：不自动判分；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`e9205a426454052984ade541b8ccb2584f66ac5c6469b74b84358f84a78fb731`。
判题协议探针：2 个，通过（不等于内容通过）。

## 二叉树基础（性质+存储）（408）

节点：`cs408.ds.topic.1efaf3d00b50`；讲解状态：UNVERIFIED。
讲解：`seed/lessons/cs408.ds.topic.1efaf3d00b50.md`；SHA256：`92cd183cf82f9ffd0632c30671898c15e11fe0ee8b6a462ae59c1258e6036b18`。

### T01 · fill_blank · basic

一棵非空二叉树恰有 7 个度为 2 的节点，它有多少个叶子节点？

候选答案：8

候选解析：非空二叉树满足 n₀=n₂+1，所以叶子数为 8。

技能标签：节点计数、非空条件；估计 2 分钟（未进行学习耗时校准）。
拟用判题：numeric_final；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`29b9ebfdc8bfb477c6428826026656411caf0ad811b99c592fbbdcf484aa88f1`。
判题协议探针：4 个，通过（不等于内容通过）。

### T02 · calculation · typical

非空二叉树有 5 个叶子、3 个度为 1 的节点，求总节点数。

候选答案：12

候选解析：n₂=n₀-1=4，总节点数为 5+3+4=12。

技能标签：节点计数；估计 3 分钟（未进行学习耗时校准）。
拟用判题：numeric_final；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`2b88d022825f7eb35717502e14bec52f40e07726b606d1be7bedc4b3480ec112`。
判题协议探针：4 个，通过（不等于内容通过）。

### T03 · single_choice · basic

根节点算第 1 层，高度为 4 层的二叉树最多有多少个节点？

- A. 7
- B. 15
- C. 16
- D. 31

候选答案：B

候选解析：最多节点数为 2⁴-1=15；高度按层数而非边数定义。

技能标签：高度约定、层数；估计 2 分钟（未进行学习耗时校准）。
拟用判题：single_choice；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`319b93341f65c226bb895be400a73f654a4e9bc82b33723bb8e05ad0afc45bbf`。
判题协议探针：4 个，通过（不等于内容通过）。

### T04 · fill_blank · variant

一棵完全二叉树共有 13 个节点，问叶子节点数是多少？

候选答案：7

候选解析：编号 1 到 6 可有孩子，7 到 13 为叶子，故叶子数为 ceil(13/2)=7。

技能标签：完全二叉树、节点计数；估计 3 分钟（未进行学习耗时校准）。
拟用判题：numeric_final；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`2c75eeb156936fbc46f6ecdef62c865d8c5fe41cb9a381c2650a09aa8565b978`。
判题协议探针：4 个，通过（不等于内容通过）。

### T05 · fill_blank · typical

非空二叉树共有 5 个节点，使用每节点两个孩子指针的二叉链表且无额外头节点，空孩子指针共有多少个？

候选答案：6

候选解析：10 个孩子指针槽中有 4 个对应实际边，因此空指针为 10-4=6。

技能标签：链式存储、空指针；估计 3 分钟（未进行学习耗时校准）。
拟用判题：numeric_final；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`189de88edbf81208371f4ff348e4914ab735a9b31ec6010c7320a67d589dec22`。
判题协议探针：4 个，通过（不等于内容通过）。

### T06 · single_choice · typical

二叉树根为 A，A 的左孩子为 B、右孩子为 C；B 的左孩子为 D、右孩子为 E，C、D、E 无孩子。先序遍历是哪一个？

- A. D B E A C
- B. D E B C A
- C. A B D E C
- D. A B C D E

候选答案：C

候选解析：先序按根、左、右递归：先 A，再遍历 B 的子树得到 B D E，最后 C，合为 A B D E C。

技能标签：遍历基础；估计 3 分钟（未进行学习耗时校准）。
拟用判题：single_choice；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`e92e96feefaf5d36d158595fe8b359fab1512a7654703c14e2c920158492b500`。
判题协议探针：4 个，通过（不等于内容通过）。

### T07 · single_choice · variant

根算第 1 层，普通二叉树高度为 4 层，每个内部节点只需有一个孩子。最少节点数是多少？

- A. 4
- B. 7
- C. 8
- D. 15

候选答案：A

候选解析：单链形状即可达到 4 层且只有 4 个节点；不能将普通二叉树默认成满二叉树。

技能标签：高度约定、最少节点；估计 2 分钟（未进行学习耗时校准）。
拟用判题：single_choice；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`65da96406840099ea6341368eda61b835482c00cd2a358a51dbe2d9526f93287`。
判题协议探针：4 个，通过（不等于内容通过）。

### T08 · subjective · comprehensive

用伪代码写出二叉树叶子计数算法，说明空树与单节点情况，以及时间和递归栈空间复杂度。

候选答案：count(null)=0；若左右孩子皆空则返回1；否则返回count(left)+count(right)。时间 O(n)，栈空间 O(h)。

候选解析：必须先处理空指针再访问孩子。每个真实节点访问一次，空树返回 0，单节点返回 1。仅最终数字无法检验算法；本题只能保存过程或辅助审阅，不宣称沙箱执行通过。

技能标签：边界处理、递归算法、复杂度；估计 8 分钟（未进行学习耗时校准）。
拟用判题：不自动判分；内容来源：AI_GENERATED。
审核状态：answer=GENERATED；explanation=GENERATED；grading=GENERATED；mapping=GENERATED；source=GENERATED；stem=GENERATED。
审核绑定哈希：`9da9e53743dad1ae547a2f5ed6fc07442043690e60007850d4067ddf37f87550`。
判题协议探针：2 个，通过（不等于内容通过）。

## 发布与学习闭环边界

全部六项题目审核需记录真实人工审核人、日期、说明和上述绑定哈希；修改内容后旧审核失效。
讲解需独立确认并绑定文件哈希。审核完成后才导出 reviewed pack，再用现有导入器先 dry-run。
原引用节点上线在线题还需单独核对毕业策略，不由导入器自动修改。
当前集成测试中的人工审核是明确标注的隔离模拟，不是本文件已获真人确认。
