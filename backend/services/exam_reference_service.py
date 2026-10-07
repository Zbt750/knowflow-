"""Build and sync source-linked annual exam references into knowledge points.

The bundled annual Markdown files contain question numbers and brief topic tags,
not exam stems or answer keys. These rows never become fabricated practice
``Question`` records; users may add the original-paper task to a daily plan and
self-assess it as evidence for the linked knowledge-point graduation policy.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from backend.resources import bundled_path

from backend.models.learning import (
    ExamQuestionReference,
    KnowledgePoint,
    KpMasteryPolicy,
    KpState,
)

_REFERENCE_POLICY_NOTE = "历年真题索引策略："

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILTIN_DIR = PROJECT_ROOT / "seed" / "materials" / "builtin"
_QUESTION_ROW = re.compile(r"^\|\s*第\s*(\d+)\s*题\s*\|\s*([^|]+?)\s*\|(.*)$")
_LINK = re.compile(r"\[[^\]]+\]\(<(https?://[^>]+)>\)|\[[^\]]+\]\((https?://[^)]+)\)")
_LABEL_SEPARATOR = re.compile(r"[；;]")

_408_SECTIONS: dict[str, tuple[str, str]] = {
    "数据结构": ("ds", "数据结构"),
    "计算机组成原理": ("co", "计算机组成原理"),
    "操作系统": ("os", "操作系统"),
    "计算机网络": ("cn", "计算机网络"),
}

_CATEGORY_NODES: dict[str, tuple[str, str, str]] = {
    "math.calculus.exam.integral": ("math.calculus", "一元函数积分学", "考研数学"),
    "math.calculus.exam.multivariable": ("math.calculus", "多元函数微积分", "考研数学"),
    "math.calculus.exam.ode": ("math.calculus", "微分方程", "考研数学"),
    "math.calculus.exam.comprehensive": ("math.calculus", "综合题与应用", "考研数学"),
    "math.calculus.exam.other": ("math.calculus", "待核对与其他考点", "考研数学"),
    "math.linear-algebra.exam.matrix": ("math.linear-algebra", "矩阵", "考研数学"),
    "math.linear-algebra.exam.vector": ("math.linear-algebra", "向量组", "考研数学"),
    "math.linear-algebra.exam.system": ("math.linear-algebra", "线性方程组", "考研数学"),
    "math.linear-algebra.exam.eigen": ("math.linear-algebra", "特征值与相似", "考研数学"),
    "math.linear-algebra.exam.quadratic": ("math.linear-algebra", "二次型", "考研数学"),
    "math.linear-algebra.exam.other": ("math.linear-algebra", "综合与其他考点", "考研数学"),
}

# 真题来源往往把同一大考点拆成很细的标签。保留每个原始标签节点的同时，
# 再建立可加入今日学习的专题汇总节点；同一题在一个汇总专题中最多出现一次。
_MATH_FAMILY_SPECS: dict[str, tuple[str, str, str]] = {
    "math.calculus.limit": ("math.family.calculus-limit", "专题汇总：极限与连续", "math.calculus"),
    "math.calculus.differential": ("math.family.calculus-differential", "专题汇总：一元函数微分学", "math.calculus"),
    "math.calculus.exam.integral": ("math.family.calculus-integral", "专题汇总：一元函数积分学", "math.calculus"),
    "math.calculus.exam.multivariable": ("math.family.calculus-multivariable", "专题汇总：多元函数微积分", "math.calculus"),
    "math.calculus.exam.ode": ("math.family.calculus-ode", "专题汇总：常微分方程", "math.calculus"),
    "math.calculus.series": ("math.family.calculus-series", "专题汇总：无穷级数", "math.calculus"),
    "math.linear-algebra.determinant": ("math.family.linear-determinant", "专题汇总：行列式", "math.linear-algebra"),
    "math.linear-algebra.exam.matrix": ("math.family.linear-matrix", "专题汇总：矩阵", "math.linear-algebra"),
    "math.linear-algebra.exam.vector": ("math.family.linear-vectors", "专题汇总：向量组", "math.linear-algebra"),
    "math.linear-algebra.exam.system": ("math.family.linear-systems", "专题汇总：线性方程组", "math.linear-algebra"),
    "math.linear-algebra.exam.eigen": ("math.family.linear-eigen", "专题汇总：特征值与相似", "math.linear-algebra"),
    "math.linear-algebra.exam.quadratic": ("math.family.linear-quadratic", "专题汇总：二次型", "math.linear-algebra"),
}

_408_FAMILY_SPECS: dict[tuple[str, str], tuple[str, str]] = {
    ("ds", "linear"): ("线性表、栈与队列", "linear-structures"),
    ("ds", "tree"): ("树与二叉树", "trees"),
    ("ds", "graph"): ("图与图算法", "graphs"),
    ("ds", "sort"): ("排序专题", "sorting"),
    ("ds", "search"): ("查找与散列", "searching"),
    ("co", "number"): ("数值表示与运算", "number-representation"),
    ("co", "memory"): ("存储器与 Cache", "memory"),
    ("co", "cpu"): ("CPU、指令与数据通路", "cpu-instructions"),
    ("co", "io"): ("总线与 I/O", "io-bus"),
    ("os", "process"): ("进程、线程与同步", "process-sync"),
    ("os", "memory"): ("操作系统内存管理", "memory-management"),
    ("os", "files"): ("文件系统与设备管理", "files-devices"),
    ("os", "core"): ("操作系统基础与结构", "os-basics"),
    ("cn", "physical"): ("物理层与通信基础", "physical-layer"),
    ("cn", "link"): ("数据链路与局域网", "link-layer"),
    ("cn", "network"): ("网络层与 IP", "network-layer"),
    ("cn", "transport"): ("传输层与 TCP/UDP", "transport-layer"),
    ("cn", "application"): ("应用层协议", "application-layer"),
    ("cn", "general"): ("网络体系结构与基本概念", "network-basics"),
}

_EXISTING_TOPIC_CODES = {
    "洛必达法则": "math.calculus.limit.lhopital",
    "等价无穷小": "math.calculus.limit.infinitesimal",
    "等价无穷小替换": "math.calculus.limit.infinitesimal",
    "隐函数求导": "math.calculus.differential.implicit",
    "等比级数的敛散性与求和": "math.calculus.series.geometric",
    "等比级数的敛散性": "math.calculus.series.geometric",
    "行列式的性质": "math.linear-algebra.determinant.properties",
}


def _links(line: str) -> list[str]:
    return [left or right for left, right in _LINK.findall(line)]


def _topic_parts(label: str) -> list[str]:
    return [part.strip() for part in _LABEL_SEPARATOR.split(label) if part.strip()]


def _math_parent(topic: str) -> str:
    if "行列式" in topic:
        return "math.linear-algebra.determinant"
    if "二次型" in topic or "合同变换" in topic or "规范形" in topic:
        return "math.linear-algebra.exam.quadratic"
    if "特征值" in topic or "特征向量" in topic or "相似" in topic:
        return "math.linear-algebra.exam.eigen"
    if "线性方程组" in topic:
        return "math.linear-algebra.exam.system"
    if "向量组" in topic or "极大无关组" in topic or "线性相关" in topic:
        return "math.linear-algebra.exam.vector"
    if "矩阵" in topic or "伴随" in topic:
        return "math.linear-algebra.exam.matrix"
    if any(word in topic for word in ("微分方程", "齐次线性", "一阶线性", "方程的解")):
        return "math.calculus.exam.ode"
    if any(
        word in topic
        for word in ("偏导", "多元", "二元", "二重积分", "全微分", "Hessian", "极坐标", "积分区域", "黎曼和")
    ):
        return "math.calculus.exam.multivariable"
    if any(word in topic for word in ("积分", "积分学", "旋转体", "引力模型")):
        return "math.calculus.exam.integral"
    if any(word in topic for word in ("级数", "敛散性", "数列")):
        return "math.calculus.series"
    if any(word in topic for word in ("极限", "连续", "无穷小", "泰勒")):
        return "math.calculus.limit"
    if any(
        word in topic
        for word in (
            "导数", "微分", "中值", "极值", "最值", "凹凸", "拐点", "曲率",
            "单调", "根的存在", "不等式",
        )
    ):
        return "math.calculus.differential"
    return "math.calculus.exam.other"


def _family_spec(subject: str, section_code: str, topic: str) -> tuple[str, str, str] | None:
    """返回宽主题汇总节点；原始标签节点仍保留，不将细标签冒充为同义词。"""
    if topic.startswith("待核对："):
        return None
    if subject == "数学二":
        if any(
            word in topic
            for word in ("二重积分", "多元", "二元", "偏导", "全微分", "Hessian", "极坐标", "黎曼和", "方向导数", "梯度")
        ):
            return _MATH_FAMILY_SPECS["math.calculus.exam.multivariable"]
        return _MATH_FAMILY_SPECS.get(_math_parent(topic))

    name = topic.lower()
    family: str | None = None
    if section_code == "ds":
        if any(word in name for word in ("栈", "队列", "顺序表", "链表", "线性表", "双端队列")):
            family = "linear"
        elif any(word in name for word in ("图", "拓扑", "最短", "生成树", "连通")):
            family = "graph"
        elif any(word in name for word in ("树", "遍历", "哈夫曼", "二叉")):
            family = "tree"
        elif any(word in name for word in ("排序", "冒泡", "快速", "归并", "插入", "选择排序", "基数")):
            family = "sort"
        elif any(word in name for word in ("查找", "散列", "哈希", "折半", "二分")):
            family = "search"
    elif section_code == "co":
        if any(word in name for word in ("补码", "浮点", "定点", "编码", "校验码", "整数运算", "数值表示")):
            family = "number"
        elif any(word in name for word in ("存储", "cache", "主存", "虚拟存储", "层次结构")):
            family = "memory"
        elif any(word in name for word in ("总线", "i/o", "dma", "输入输出", "设备")):
            family = "io"
        else:
            family = "cpu"
    elif section_code == "os":
        if any(word in name for word in ("进程", "线程", "同步", "互斥", "信号量", "调度", "通信")):
            family = "process"
        elif any(word in name for word in ("内存", "页", "虚拟存储", "置换", "分配", "缺页")):
            family = "memory"
        elif any(word in name for word in ("文件", "目录", "磁盘", "i/o", "设备", "spooling", "挂载")):
            family = "files"
        else:
            family = "core"
    elif section_code == "cn":
        if any(word in name for word in ("物理层", "信道", "奈奎斯特", "香农", "传输介质", "通信基础")):
            family = "physical"
        elif any(word in name for word in ("数据链路", "组帧", "mac", "以太网", "vlan", "crc", "局域网", "帧")):
            family = "link"
        elif any(word in name for word in ("网络层视角", "网络层", "arp", "dhcp", "icmp", "ipv4", "ipv6", "ip地址", "子网", "cidr", "nat", "路由")):
            family = "network"
        elif any(word in name for word in ("tcp", "udp", "拥塞控制", "流量控制", "连接管理", "传输层")):
            family = "transport"
        elif any(word in name for word in ("网络概念", "网络体系", "网络组成", "网络模型", "协议层次")):
            family = "general"
        else:
            family = "application"

    if family is None:
        return None
    family_name, slug = _408_FAMILY_SPECS[(section_code, family)]
    return f"cs408.{section_code}.family.{slug}", f"专题汇总：{family_name}", f"cs408.{section_code}"


def _topic_code(subject: str, section_code: str, topic: str) -> str:
    digest = hashlib.sha1(topic.encode("utf-8")).hexdigest()[:12]
    return f"math.exam.{digest}" if subject == "数学二" else f"cs408.{section_code}.topic.{digest}"


def _node_depth(code: str, nodes: dict[str, dict[str, Any]]) -> int:
    depth = 0
    current = nodes.get(code)
    seen: set[str] = set()
    while current and current.get("parent_code"):
        parent = current["parent_code"]
        if parent in seen:
            raise ValueError(f"知识树父节点循环：{code}")
        seen.add(parent)
        depth += 1
        current = nodes.get(parent)
        if current is None:  # Existing math syllabus parents are intentionally reused.
            break
    return depth


def build_exam_reference_seed(
    builtin_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse annual indexes into topic nodes and per-question bindings."""
    builtin_dir = builtin_dir or bundled_path("seed/materials/builtin")
    node_defs: dict[str, dict[str, Any]] = {}
    reference_defs: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    family_rows: dict[str, dict[tuple[str, int, int], dict[str, Any]]] = {}
    family_specs: dict[str, tuple[str, str, str]] = {}

    def add_node(
        code: str,
        name: str,
        subject: str,
        parent_code: str | None,
        *,
        reference_only: bool,
    ) -> None:
        node_defs.setdefault(
            code,
            {
                "code": code,
                "name": name,
                "subject": subject,
                "parent_code": parent_code,
                "is_reference_only": reference_only,
            },
        )

    files = sorted(
        [*builtin_dir.glob("exam_math2_*_topics.md"), *builtin_dir.glob("exam_408_*_topics.md")],
        key=lambda path: path.name,
    )
    for path in files:
        math_match = re.fullmatch(r"exam_math2_(\d{4})_topics\.md", path.name)
        cs_match = re.fullmatch(r"exam_408_(\d{4})_topics\.md", path.name)
        if not math_match and not cs_match:
            continue
        subject = "数学二" if math_match else "408"
        year = int((math_match or cs_match).group(1))
        lines = path.read_text(encoding="utf-8").splitlines()
        topic_source_url: str | None = None
        question_archive_url: str | None = None
        for line in lines:
            links = _links(line)
            if topic_source_url is None and links and ("来源" in line or "整理自" in line):
                topic_source_url = links[0]
            if (
                subject == "数学二"
                and year <= 2019
                and question_archive_url is None
                and line.startswith("题目来源与版本：")
                and links
            ):
                question_archive_url = links[0]

        section_code = ""
        for line in lines:
            heading = re.match(r"^##\s+(.+?)\s*$", line)
            if heading:
                if subject == "408":
                    section_name = heading.group(1).strip()
                    section = _408_SECTIONS.get(section_name)
                    if section is None:
                        raise ValueError(f"未识别的 408 科目分支：{path.name}: {section_name}")
                    section_code, display_name = section
                    add_node("cs408", "408 计算机学科专业基础", "408", None, reference_only=False)
                    add_node(
                        f"cs408.{section_code}", display_name, "408", "cs408", reference_only=False
                    )
                continue

            match = _QUESTION_ROW.match(line)
            if not match:
                continue
            question_number = int(match.group(1))
            source_topic_label = match.group(2).strip()
            row_links = _links(match.group(3))
            question_source_url = row_links[0] if subject == "408" and row_links else question_archive_url

            for topic in _topic_parts(source_topic_label):
                unresolved = topic == "该题页面未提供考点标签"
                display_topic = "待核对：来源未提供考点标签" if unresolved else topic
                if subject == "408":
                    parent_code = f"cs408.{section_code}"
                    code = _topic_code(subject, section_code, display_topic)
                    node_subject = "408"
                else:
                    existing_code = _EXISTING_TOPIC_CODES.get(display_topic)
                    if existing_code is not None:
                        code, parent_code = existing_code, None
                    else:
                        parent_code = _math_parent(display_topic)
                        code = _topic_code(subject, "", display_topic)
                    node_subject = "考研数学"
                    category = _CATEGORY_NODES.get(parent_code or "")
                    if category is not None:
                        category_parent, category_name, category_subject = category
                        add_node(
                            parent_code or "",
                            category_name,
                            category_subject,
                            category_parent,
                            reference_only=False,
                        )

                if code not in _EXISTING_TOPIC_CODES.values():
                    add_node(code, display_topic, node_subject, parent_code, reference_only=True)

                source_note = (
                    "来源页面没有给出考点标签；此节点仅用于人工核对，不代表具体知识点。"
                    if unresolved
                    else (
                        "第三方题目/考点索引，分类不是官方命题标注。"
                        if subject == "408"
                        else (
                            "按本地 2026 数学二资料整理的标签，非官方命题标注。"
                            if year == 2026
                            else "第三方复习标签，非官方命题标注；请按原题核对。"
                        )
                    )
                )
                item = {
                    "subject": subject,
                    "year": year,
                    "question_number": question_number,
                    "knowledge_point_code": code,
                    "topic_label": display_topic,
                    "source_topic_label": source_topic_label,
                    "question_source_url": question_source_url,
                    "topic_source_url": topic_source_url,
                    "local_folder": f"{('数学' if subject == '数学二' else '408')}/{year}",
                    "source_note": source_note,
                }
                reference_defs.setdefault((subject, year, question_number, code), item)
                family_spec = _family_spec(subject, section_code, display_topic)
                if family_spec is not None:
                    family_code, family_name, family_parent = family_spec
                    family_specs[family_code] = family_spec
                    family_key = (subject, year, question_number)
                    family_item = family_rows.setdefault(family_code, {}).get(family_key)
                    if family_item is None:
                        family_item = {**item, "knowledge_point_code": family_code}
                        family_rows[family_code][family_key] = family_item
                    elif display_topic not in family_item["topic_label"].split("；"):
                        family_item["topic_label"] += f"；{display_topic}"

    # 仅发布至少覆盖两道不同原卷题的专题，避免新造单题分组节点。
    for family_code, rows in family_rows.items():
        if len(rows) < 2:
            continue
        _family_code, family_name, family_parent = family_specs[family_code]
        subject = "考研数学" if family_code.startswith("math.") else "408"
        add_node(
            family_code,
            family_name,
            subject,
            family_parent,
            reference_only=True,
        )
        for (row_subject, year, question_number), item in rows.items():
            aggregate_item = {
                **item,
                "source_note": (
                    "专题汇总映射：按原始考点标签归入本专题，原始标签仍保留；"
                    "该宽口径归并是项目整理，不是官方命题分类。 "
                    + item["source_note"]
                ),
            }
            reference_defs.setdefault(
                (row_subject, year, question_number, family_code), aggregate_item
            )

    nodes = sorted(node_defs.values(), key=lambda node: _node_depth(node["code"], node_defs))
    references = sorted(
        reference_defs.values(),
        key=lambda row: (row["subject"], row["year"], row["question_number"], row["knowledge_point_code"]),
    )
    return nodes, references


def sync_exam_reference_index(db: Session) -> dict[str, int]:
    """Idempotently upsert reference-only topic nodes and year/question bindings."""
    nodes, references = build_exam_reference_seed()
    created_nodes = updated_nodes = created_refs = updated_refs = 0

    for node in nodes:
        current = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == node["code"]))
        parent_code = node.get("parent_code")
        parent = None
        if parent_code:
            parent = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == parent_code))
            if parent is None:
                raise ValueError(f"真题索引节点的父节点不存在：{parent_code} → {node['code']}")
        if current is None:
            current = KnowledgePoint(code=node["code"])
            db.add(current)
            created_nodes += 1
        else:
            updated_nodes += 1
        current.name = node["name"]
        current.subject = node["subject"]
        current.parent_id = parent.id if parent else None
        current.ordinal = 1
        current.is_assessable = node["is_reference_only"]
        current.is_reference_only = node["is_reference_only"]
        is_family = ".family." in node["code"]
        current.summary = (
            (
                "本项目按来源标签整理的跨年份专题汇总。下方保留每道题的原始索引标签；"
                "专题归并用于复习导航，不是官方考点分类。"
            )
            if is_family
            else (
                "历年真题知识点。下方提供年份、题号与原卷来源；原题题干和答案不在系统内。"
                if node["is_reference_only"]
                else "汇总按学科或考点分类的历年真题索引；不计入学习进度。"
            )
        )
        current.learning_goal = (
            (
                "按专题浏览不同年份的原卷题目；打开来源完成后，可将题目加入今日学习并按真实表现自评。"
            )
            if is_family
            else (
                "打开原卷完成对应题目后，在今日学习按真实掌握情况自评；已掌握的不同真题会计入本知识点毕业进度。"
                if node["is_reference_only"]
                else "按学科或考点浏览历年真题索引。"
            )
        )
        current.is_active = True
        db.flush()

    codes = {item["knowledge_point_code"] for item in references}
    points_by_code = {
        row.code: row.id
        for row in db.scalars(select(KnowledgePoint).where(KnowledgePoint.code.in_(codes))).all()
    }
    existing = {
        (row.subject, row.year, row.question_number, row.knowledge_point_id): row
        for row in db.scalars(select(ExamQuestionReference)).all()
    }
    for item in references:
        kp_id = points_by_code.get(item["knowledge_point_code"])
        if kp_id is None:
            raise ValueError(f"真题关联引用了不存在的知识点：{item['knowledge_point_code']}")
        key = (item["subject"], item["year"], item["question_number"], kp_id)
        row = existing.get(key)
        if row is None:
            row = ExamQuestionReference(
                subject=item["subject"],
                year=item["year"],
                question_number=item["question_number"],
                knowledge_point_id=kp_id,
            )
            db.add(row)
            existing[key] = row
            created_refs += 1
        else:
            updated_refs += 1
        row.topic_label = item["topic_label"]
        row.source_topic_label = item["source_topic_label"]
        row.question_source_url = item["question_source_url"]
        row.topic_source_url = item["topic_source_url"]
        row.local_folder = item["local_folder"]
        row.source_note = item["source_note"]

    # 测试/生产 session 使用 autoflush=False；显式落下新关联，下面的计数才看到刚导入真题。
    db.flush()

    # 这些节点没有系统内题干，因此毕业门槛按该节点实际绑定的不同真题数配置：
    # 最多要求 3 道，少于 3 道时按可用题量下调；同时取消变式配额（来源未标注变式），
    # 仍要求真实题目、自评确认、题型覆盖与考法标签覆盖，避免“点节点自评”直接毕业。
    reference_kps = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.is_reference_only.is_(True))
    ).all()
    for kp in reference_kps:
        reference_count = db.scalar(
            select(func.count(ExamQuestionReference.id)).where(
                ExamQuestionReference.knowledge_point_id == kp.id
            )
        ) or 0
        if reference_count < 1:
            continue
        required = min(3, reference_count)
        policy = db.get(KpMasteryPolicy, kp.id)
        created_policy = policy is None
        policy_note = (
            f"{_REFERENCE_POLICY_NOTE}共 {reference_count} 道已索引真题，"
            f"需要完成其中 {required} 道不同题；原卷题型/变式信息不完整，不伪造该类配额。"
        )
        if created_policy:
            policy = KpMasteryPolicy(kp_id=kp.id)
            db.add(policy)
        if created_policy or (
            policy is not None and policy.note and policy.note.startswith(_REFERENCE_POLICY_NOTE)
        ):
            policy.min_confirmations = required
            policy.min_real_questions = required
            policy.required_question_types = {"external_exam": required}
            policy.excluded_question_types = []
            policy.required_skill_tags = [kp.name]
            policy.required_variant_count = 0
            policy.min_day_span = min(2, required - 1)
            policy.note = policy_note
        if db.get(KpState, kp.id) is None:
            db.add(KpState(kp_id=kp.id))

    return {
        "nodes_created": created_nodes,
        "nodes_updated": updated_nodes,
        "references_created": created_refs,
        "references_updated": updated_refs,
    }
