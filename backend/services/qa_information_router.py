"""Information source selection, separate from Planner write responsibility."""
import re
from backend.services.assistant_router import evidence_explanation
def information_route(message,ctx,*,private=False):
    if private:return "private_material"
    if re.search(r"(?:我上传|已上传|上传的|我的|私人).{0,16}(?:PDF|pdf|资料|文件|笔记)",message):return "private_scope_required"
    if re.search(r"https?://|联网|上网|网上查|最新|今年|明年|20\d{2}.*(?:大纲|政策|报名|考试时间)|(?:政策|大纲).*变化",message):return "web"
    if evidence_explanation(message):return "evidence"
    if ctx.material_id or re.search(r"内置|系统资料|讲解文件|节点讲解|知识树|根据.*(?:资料|讲义)|资料里",message):return "builtin_rag"
    if getattr(ctx,'task_id',None) and re.search(r'(?:这个|当前|刚才).*(?:方案|安排|计划|题量)|为什么.*(?:方案|安排|计划)|几道',message):return 'evidence'
    if re.search(r"毕业|掌握|证据|学习记录|为什么.*安排",message):return "evidence"
    if ctx.question_id and re.search(r"这(?:道)?题|当前题|提示|答案|思路|过程|看看这个|这一步",message):return "current_question"
    if ctx.knowledge_node_ids and re.search(r"这个知识点|相关知识|这部分",message):return "builtin_rag"
    return "general"
