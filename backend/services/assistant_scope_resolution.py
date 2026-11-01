"""Resolve explicit learner topics without treating a subject label as a match.

Aliases identify curriculum concepts, never manufacture nodes. Missing concepts
remain visible and block a narrowed plan instead of widening it to a parent.
"""
import re


def correction_target(message):
    patterns = (r'我说的不是[^，,。；;]+[，,]\s*是([^，,。；;]+)',
        r'我说的是([^，,。；;]+)[，,]\s*不是')
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return match[1].strip()
    return None


def draft_revision(message):
    return bool(re.search(r'\d+\s*(?:分钟|分|小时)', message) and re.search(
        r'(?:原|旧)(?:计划|方案|安排).{0,8}(?:缩短|压缩|调整|修改)|'
        r'修改后的版本|(?:压缩|缩短|只剩).{0,12}(?:分钟|分|小时)|改成\s*\d+\s*(?:分钟|分|小时)|'
        r'(?:分钟|分|小时).{0,45}(?:保留最重要|压缩|缩短|减少练习|调整)', message))


def document_question(message):
    return bool(re.search(r'(?:这|该|那)(?:份|篇|本)?(?:讲义|资料|文档|笔记)|'
        r'(?:讲义|资料|文档|笔记)(?:里|中|有没有|是否|记载|记录)|上传的', message))


def resolve_topics(nodes, message):
    target = correction_target(message)
    text = target or message
    # Longer variants win so “定积分应用” is not reduced to all integral topics.
    groups = [(['定积分应用','定积分的应用'], ('math.calculus.exam.integral.application',)),
        (['等价无穷小替换','等价无穷小'], ('math.calculus.limit.infinitesimal',)),
        (['洛必达法则','洛必达'], ('math.calculus.limit.lhopital',)),
        (['定积分'], ()), (['积分'], ('math.calculus.exam.integral',)),
        (['极限'], ('math.calculus.limit',))]
    remaining=text
    resolutions=[]
    for aliases,codes in groups:
        found=next((a for a in aliases if a in remaining),None)
        if not found:
            continue
        matches=[n for n in nodes if n.code in codes or any(
            re.sub(r'\s*[（(]SYNTHETIC[）)]\s*$','',n.name,flags=re.I).replace('的','') == a.replace('的','')
            for a in aliases)]
        # “极限与连续” is a chapter synonym, not every leaf mentioning a limit.
        if found=='极限':
            matches += [n for n in nodes if n.name in {'极限与连续','函数极限'}]
        resolutions.append({'topic':found,'status':'matched' if matches else 'unmatched',
            'node_ids':list(dict.fromkeys(str(n.id) for n in matches))})
        for alias in aliases:
            remaining=remaining.replace(alias,'')
    if target and not resolutions:
        matches=[n for n in nodes if n.code==target or re.sub(
            r'\s*[（(]SYNTHETIC[）)]\s*$','',n.name,flags=re.I).replace('的','')==target.replace('的','')]
        resolutions=[{'topic':target,'status':'matched' if matches else 'unmatched',
            'node_ids':[str(n.id) for n in matches]}]
    return resolutions
