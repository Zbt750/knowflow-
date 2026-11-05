"""Shared safe count-only text for live pre-generation queries and history."""

def inventory_answer(evidence):
    rows=evidence.get('scope_node_counts') or []
    details='；'.join(f"{row['name']} · {int(row.get('practice_eligible_count') or 0)}道可用题"
        for row in rows if isinstance(row,dict) and row.get('name'))
    count=evidence.get('question_count')
    summary=details or (f'当前范围 · {count}道可用题' if isinstance(count,int) else '知识点题量待重新读取')
    return (f'符合正式准入条件的真实题量：{summary}。今日正式学习卷尚未生成；'
        '预览阶段只展示知识点和题量，生成后才能查看具体题目。本次只读，没有创建今日卷。')
