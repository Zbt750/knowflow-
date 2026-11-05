"""Current product inventory contract: no original historical exam papers.

This policy is supplied by the owner, not inferred from a model or a DB count.
It never relabels stored question records or grants qualification.
"""
import re

ORIGINAL_EXAM_NOTICE = '当前正式题库没有原版历年考研真题，现有相关题目为真题改编题。你是否接受查找真题改编题？本次没有用改编题替代原版，也没有修改今日卷。'


def requests_original_exam(text):
    selecting=bool(re.search(r'找|查|检索|给|拿|有没有|安排|加入|生成|只要|要一|要两',text))
    clauses=[c for c in re.split(r'[，,。；;！!？?\n]',text) if c.strip()]
    for clause in clauses:
        if re.search(r'(?:不要|不用|不找|不需要|排除|不接受).{0,6}(?:原版|历年真题|历史真题)',clause):
            continue
        original=bool(re.search(r'原版.{0,8}(?:真题|试题)|(?:历年|历史)(?:考研)?真题|考研原题',clause))
        adapted=bool(re.search(r'(?:真题|试题)(?:的)?(?:改编|变式)',clause))
        if original and not adapted and selecting:
            return True
    return False
