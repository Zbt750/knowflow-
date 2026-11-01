"""Small shared contract for existing-bank selection; never invokes a model."""
import re

QUESTION_COUNT_PATTERN = r'([零〇一二两三四五六七八九十百千]+|[1-9]\d*)\s*道'


def question_count(token):
    """Parse a whole numeral; never interpret the suffix of 十一道 as 一道."""
    if token.isdigit():
        return int(token)
    digits={'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if token in digits:return digits[token]
    if token.count('十')==1:
        tens,ones=token.split('十')
        if (not tens or tens in digits) and (not ones or ones in digits):
            return digits.get(tens,1)*10+digits.get(ones,0)
    return None

def excluded_bank_filters(text):
    types={'选择题':'single_choice','单选题':'single_choice','填空题':'fill_blank','计算题':'calculation','证明题':'proof'}
    levels={'基础':'basic','简单':'basic','中等':'medium','适中':'medium','较难':'hard','困难':'hard','难题':'hard'}
    prefix=r'(?:不要|不用|不选|不练|排除)[^，,。；;！？!?]{0,4}'
    return ({kind for name,kind in types.items() if re.search(prefix+name,text)},
            {kind for name,kind in levels.items() if re.search(prefix+name,text)})


def bank_selection_request(text):
    parts=[p.strip() for p in re.split(r'[，,；;。！？?\n]',text) if p.strip()]
    positive=[p for p in parts if not re.search(r'(?:不要|不用|先别|先不|不必).{0,10}(?:加|找|选|检索)',p)]
    operation='；'.join(positive)
    negated_new=bool(re.search(r'(?:不要|不用|别|不必|无需).{0,4}新编',text))
    explicit_new=bool(re.search(r'新编|(?:直接|重新)?生成.{0,8}(?:新的|新题)|不用查.{0,8}题库.{0,8}(?:直接)?出题',text)) and not negated_new
    bank_source=bool(re.search(r'(?:从|查|找|在).{0,8}(?:我的|个人|已有|现有)?题库|已有题目|题库里',text)) and not explicit_new
    requested=bool(re.search(r'(?:添加|增加|再加|额外加|追加|补充|再补|加入|加进|加到|加上|加|再来|(?:给我|帮我|请)?来|选|找|检索).{0,24}(?:一道|两道|[1-9]\d*道|题|练习)',operation))
    if bank_source and re.search(r'(?:来|拿(?:来)?).{0,5}(?:一道|一题)|(?:找|选|出).{0,10}(?:一道|题)',operation):requested=True
    if not requested or re.match(r'^(?:为什么|为何|如何|怎么|能否|是否)',operation):return None
    count=re.search(QUESTION_COUNT_PATTERN,operation)
    amount=question_count(count[1]) if count else 1
    if amount is None or amount < 1:return None
    excluded_types,excluded_levels=excluded_bank_filters(text)
    preference_text=re.sub(r'(?:不要|不用|不选|不练|排除)[^，,。；;！？!?]{0,4}(?:基础|简单|中等|适中|较难|困难|难题|难的|填空题|选择题|单选题|计算题|证明题)','',text)
    difficulty='medium' if re.search(r'中等|适中',preference_text) else 'basic' if re.search(r'基础|简单',preference_text) else 'hard' if re.search(r'较难|困难|难一点|难一些|难题|难的',preference_text) else None
    type_names={'单选题':'single_choice','选择题':'single_choice','填空题':'fill_blank','计算题':'calculation','证明题':'proof'}
    requested_types={kind for name,kind in type_names.items() if name in preference_text}
    question_type=next(iter(requested_types)) if len(requested_types)==1 else None
    narrow=bool(re.search(r'只保留前[一二两三四五六七八九十\d]+个(?:推荐)?知识点',text))
    explicit_replace=bool(re.search(r'不要原来的推荐.{0,20}(?:只做|只练)|只(?:练|做)(?!\s*\d+\s*道)[^，,。；;]{0,24}(?:洛必达|知识点|范围|线性代数|矩阵|行列式|积分|极限)|系统推荐范围.{0,8}(?:改成|改为|替换为)|(?:知识点)?范围.{0,8}(?:改成|改为|替换为)|(?:原来的推荐|原推荐|系统推荐).{0,4}(?:全部)?替换(?:成|为)|不保留.{0,10}(?:原推荐|系统推荐)',text))
    add_operation=bool(re.search(r'(?:再)?(?:给我)?加\s*(?:[一二两三四五六七八九十]|[1-9]\d*)\s*道|(?:给我|帮我|请)?来\s*(?:[一二两三四五六七八九十]|[1-9]\d*)?\s*(?:一道|一题|题目)|(?:给我|帮我|请)来一道|添加|增加|再加|额外加|追加|补充|再补|加入|加进|加到|加上|再来|(?:基础上|推荐.*)加|今日卷|放(?:进|入|到|在).{0,10}(?:今日|今天)(?:学习)?卷',operation))
    scope_mode='narrow' if narrow else 'replace' if explicit_replace else 'append' if add_operation else 'replace'
    append=scope_mode=='append'
    return {'count':amount,'additional_count':amount if append else None,'difficulty':difficulty,'question_type':question_type,
        'excluded_question_types':sorted(excluded_types),'excluded_difficulties':sorted(excluded_levels),
        'append':append,'scope_mode':scope_mode,'bank_source':bank_source,
        'include_personal':bool(bank_source and re.search(r'我的题库|个人题库',text)),
        'similar':bool(re.search(r'类似|相似|差不多|同类|同类型|变式',operation))}


def ambiguous_question_source(text):
    """An unspecified “出/来一道题” does not authorize paid authoring."""
    # 明确要求“出一道新题/生成新题”是生成授权，不是来源歧义。
    if re.search(r'新编|出一道新题|出.{0,6}新题|生成.{0,8}(?:新的|新题)|我想生成|再出一道不同', text):
        return False
    if (re.search(r'(?:给我|帮我|请)?出(?:一|两|几)?道.{2,20}题', text)
            and not re.search(r'找|查|题库|练习|加入', text)):
        return False
    # 明确的“把刚才第 N 道换一道”是替换预览目标题，不是来源歧义。
    if (re.search(r'换一(?:道|个)|换道', text)
            and re.search(r'刚才|上面|上一|第\s*[一二两三四五六七八九十\d]+\s*道|这道|那一道', text)):
        return False
    # 明确要求“基于刚才这道题出变式”是生成，不是题库来源歧义。
    if (re.search(r'变式|新编', text)
            and re.search(r'刚才|上面|上一|第\s*[一二两三四五六七八九十\d]+\s*道', text)):
        return False
    bank=bank_selection_request(text)
    if bank and bank.get('bank_source'):
        return False
    clauses=[p for p in re.split(r'[，,；;。！？?\n]',text) if p.strip()]
    positive=[p for p in clauses if not re.search(r'(?:不要|不用|别|不必|无需|不自动).{0,6}(?:新编|生成|出题)',p)]
    if any(re.search(r'新编|编(?:写|造|一道)|生成|出新题|直接出题',p) for p in positive):
        return False
    return any(re.search(r'(?:出|来|再给我|换)\s*(?:一|两|二|三|[1-9]\d*)\s*(?:道|题)|(?:给我|帮我|请)\s*出题',p) for p in positive)
