"""Conversation-owned student statements, never objective mastery evidence.

Stored on the existing persisted user-message history; corrections append new
messages. Reading another conversation never inherits these statements.
"""
import re
from sqlalchemy import select
from backend.models.chat import ChatMessage


def evidence_attribution_request(message):
    if re.search(r'(?:重新|再).{0,4}(?:核对|核实|查证).{0,5}(?:记录|作答)|'
            r'你说我.{0,25}(?:答对|答错).{0,30}(?:但|明明)', message):
        return True
    if re.search(r'公式|定理|算法|法则', message) and not re.search(r'我|判断|薄弱|掌握|作答', message):
        return False
    return bool(re.search(r'你.{0,20}(?:为什么|为何).{0,8}(?:判断|认为|觉得)|'
        r'(?:根据什么|依据是什么|判断依据|说明依据)|'
        r'(?:自述|自评).{0,12}(?:还是|实际|记录)|'
        r'(?:薄弱点|掌握|不会).{0,8}(?:记错|判断错)|你把我的.{0,12}记错|'
        r'(?:根据|按照).{0,8}(?:作答)?记录.{0,8}(?:重新|再).{0,6}(?:判断|核对|评估)|'
        r'(?:根据|按照).{0,12}(?:这个|该)?(?:新信息|自述).{0,12}(?:重新判断|重新核对|重新评估|核实掌握)|'
        r'你(?:刚才|之前|上次).{0,24}(?:说|判断|认为).{0,50}(?:但|可是|不过).{0,40}(?:答对|答错|自述|真正容易错)', message))


def extract_self_reports(message):
    # 明确纠正旧判断：保存为 correction，覆盖同主题旧自述；绝不反向写成相反正向断言。
    corrections = []
    previous_judgement = re.search(
        r'之前你(?:认为|说|判断|觉得)我(.{2,30}?)(?:薄弱|很差|不好|不熟|不行)', message)
    if previous_judgement and re.search(r'不是|不准确|不对|其实', message):
        topic = re.sub(r'^(?:的|在)', '', previous_judgement[1]).strip(' 的')
        if topic:
            corrections.append({'topic': topic[:80], 'assessment': 'corrected', 'correction': True,
                'statement': message[:240], 'source': 'self_report', 'independently_verified': False})
    changed_to_mastery = re.search(
        r'我之前说(.{2,30}?)(?:很差|不好|不会|不熟).{0,10}(?:现在|已经)(?:掌握|会了|熟悉|可以)', message)
    if changed_to_mastery:
        topic = changed_to_mastery[1].strip(' 的')
        if topic:
            corrections.append({'topic': topic[:80], 'assessment': 'can_use', 'correction': True,
                'statement': message[:240], 'source': 'self_report', 'independently_verified': False})
    progress = re.search(r'我最近(.{2,30}?)(?:进步很大|进步了|提升很大)', message)
    if progress:
        topic = progress[1].strip(' 的')
        if topic:
            corrections.append({'topic': topic[:80], 'assessment': 'can_use', 'correction': True,
                'statement': message[:240], 'source': 'self_report', 'independently_verified': False})
    now_weaker = re.search(r'我(?:现在|目前|其实)(?:其实)?(?:觉得|感觉)?(?:不太熟悉|不熟了|生疏了|不太会了)(.{2,30}?)(?:了)?$', message)
    if now_weaker and not re.search(r'你说|你认为|为什么', message):
        topic = re.sub(r'^(?:其实|现在|目前)', '', now_weaker[1]).strip(' 的')
        topic = re.sub(r'了[。.！!]?$', '', topic).strip(' 的')
        if topic:
            corrections.append({'topic': topic[:80], 'assessment': 'needs_help', 'correction': True,
                'statement': message[:240], 'source': 'self_report', 'independently_verified': False})
    if corrections:
        return corrections[:8]
    # Capture an explicit first-person assertion, not a quotation/attribution
    # question such as “你说我级数很差，为什么这样判断”. Keep the original
    # statement because a free-text topic is not proof of a knowledge-tree ID.
    claims = []
    first_person = bool(re.search(r'我', message))
    for clause in re.split(r'[，,；;。！？?：:\n]', message):
        clause = clause.strip()
        if re.search(r'你说|你认为|你判断|为什么|是不是|是否|你把', clause):
            continue
        # Positive self-assessments are still reports, never mastery evidence.
        # Capture common spoken forms such as "我觉得自己已经掌握了特征值"
        # separately from objective-result queries that ask whether we can verify it.
        positive_simple = re.search(
            r'^我(?:其实|真的|现在|目前)?(.{2,35}?)(?:很熟悉|很擅长|比较好|还行|没问题|学得不错)$', clause)
        if positive_simple and first_person:
            topic = re.sub(r'^(?:其实|真的|现在|目前)', '', positive_simple[1]).strip(' ：:，,。')
            if topic:
                claims.append({'topic': topic[:80], 'assessment': 'can_use',
                    'statement': clause[:240], 'source': 'self_report', 'independently_verified': False})
                continue
        positive_natural = re.search(
            r'^我(?:觉得|感觉|估计)(?:自己)?(?:现在|目前|已经)?(?:掌握了?|会用|会做|理解了)(.+)$', clause)
        if positive_natural and first_person:
            topic = positive_natural[1].strip(' ：:，,。')
            topic = re.sub(r'^(?:这个|这部分|该知识点)', '', topic).strip()
            if topic:
                claims.append({'topic': topic[:80], 'assessment': 'can_use',
                    'statement': clause[:240], 'source': 'self_report', 'independently_verified': False})
                continue
        # Also accept the common reverse wording “我估计积分换元会做”;
        # it remains a self-report and never upgrades objective mastery.
        positive_reverse = re.search(
            r'^我(?:觉得|感觉|估计)(?:自己)?(.{2,35}?)(?:会做|会用|掌握了?|理解了)$', clause)
        if positive_reverse and first_person:
            topic = re.sub(r'^(?:这个|这部分|该知识点)', '', positive_reverse[1]).strip()
            if topic:
                claims.append({'topic': topic[:80], 'assessment': 'can_use',
                    'statement': clause[:240], 'source': 'self_report', 'independently_verified': False})
                continue
        natural = re.search(r'^(?:(?:我(?:其实|自己|现在)?(?:感觉|觉得|估计)?|主要是))(.{2,35}?)(还可以|比较差|不太行|不会|经常做错|不太熟)$', clause)
        if natural and first_person:
            topic = re.sub(r'^(?:其实|自己|感觉|觉得|估计)', '', natural[1]).strip()
            claims.append({'topic': topic, 'assessment': 'can_use' if natural[2]=='还可以' else 'needs_help',
                'statement': clause[:240], 'source': 'self_report', 'independently_verified': False})
            continue
        correction = re.search(r'^(?:但|其实|现在|目前)?(?:我)?(?:真正|主要)?(?:容易|经常|总是)(?:做)?(?:错|出错|做错)(?:的)?(?:是|在|于)?(.+)$', clause)
        if correction and first_person:
            topic = correction[1].strip(' ：:，,。')
            if topic:
                claims.append({'topic': topic[:80], 'assessment': 'needs_help',
                    'statement': clause[:240], 'source': 'self_report', 'independently_verified': False})
                continue
        match = re.search(r'^(?:但|其实|现在|目前)?我(?:真正|确实|目前|现在)?(?:不会|不懂|不熟悉|不理解|不擅长)(?:的是|的|是)?(.+)$', clause)
        if match:
            topic, assessment = match[1], 'needs_help'
        else:
            positive = re.search(r'^我(?:现在|已经|目前)?(?:会用|掌握了|理解了)(.+)$', clause)
            if positive:
                topic, assessment = positive[1], 'can_use'
                claims.append({'topic': topic.strip()[:80], 'assessment': assessment, 'statement': clause[:240],
                    'source': 'self_report', 'independently_verified': False})
                continue
            match = re.search(r'^(?:我)?(.{2,35}?)(?:我)?(?:也)?(?:不太好|很差|不熟|会用|已经会了|已经掌握了)$', clause)
            if not match:
                continue
            topic = match[1]
            assessment = 'can_use' if re.search(r'会用|已经会了|已经掌握了', clause) else 'needs_help'
        topic = re.sub(r'^(?:真正|主要|其实)', '', topic).strip(' ：:')[:80]
        if topic and not re.search(r'你说|你认为|根据', topic):
            claims.append({'topic': topic, 'assessment': assessment, 'statement': clause[:240],
                'source': 'self_report', 'independently_verified': False})
    return claims[:8]


def read_self_reports(db, session_id):
    rows = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id,
        ChatMessage.role == 'user').order_by(ChatMessage.seq.desc()).limit(100)))
    latest = {}
    for row in rows:
        for claim in (row.metadata_ or {}).get('learner_self_reports', []):
            if isinstance(claim, dict) and claim.get('source') == 'self_report' and claim.get('topic'):
                latest.setdefault(claim['topic'], {**claim, 'message_id': str(row.id),
                    'recorded_at': row.created_at.isoformat()})
    return list(latest.values())[:16]
