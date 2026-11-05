"""把指定函数的函数体挖空，只留签名 + docstring + 一句 NotImplementedError。

默认只预览（dry-run），不改任何文件。确认无误后加 --apply 才真正写入。

    # 1) 预览
    python .learn/tools/blank.py backend/retrieval/fusion.py \
        --funcs reciprocal_rank_fusion,fuse_ranked_ids,rank_map

    # 2) 确认要改这几处后，写入
    python .learn/tools/blank.py backend/retrieval/fusion.py \
        --funcs reciprocal_rank_fusion,fuse_ranked_ids,rank_map --apply

    # 3) 后悔了：git checkout main -- backend/retrieval/fusion.py

保留：装饰器、函数签名（含多行签名）、docstring。
清空：docstring 之后到函数结束的全部语句。
不处理：类方法、嵌套函数（本项目练习目标是模块级函数）。
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

PLACEHOLDER = 'raise NotImplementedError("这里是空的 —— 按任务卡规格自己写")'


def _has_docstring(node: ast.AST) -> bool:
    body = getattr(node, "body", None)
    if not body:
        return False
    first = body[0]
    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )


def plan_edits(source: str, wanted: set[str]) -> tuple[list[str], list[dict], list[str]]:
    """返回 (源文件行, 待执行编辑, 警告列表)。"""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    edits: list[dict] = []
    warnings: list[str] = []
    found: set[str] = set()

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in wanted:
            continue
        found.add(node.name)

        body = node.body
        if _has_docstring(node):
            remove_from = body[0].end_lineno  # 1-based：docstring 结束行，从下一行开始清
        else:
            remove_from = node.lineno  # 连签名一起重写标题行？不——签名要保留
            # 没有 docstring 时，签名可能跨多行：保留到最后一行签名（即 body[0].lineno 之前）
            remove_from = body[0].lineno - 1

        remove_to = node.end_lineno
        if remove_from >= remove_to:
            warnings.append(f"{node.name}: 函数体只有一行，挖空意义不大，已跳过")
            continue

        indent = " " * body[0].col_offset
        edits.append(
            {
                "name": node.name,
                "from": remove_from + 1,  # 转成切片用的 1-based 起点
                "to": remove_to,          # 含
                "line_count": remove_to - remove_from,
                "replacement": f"{indent}{PLACEHOLDER}\n",
                "first_line": (body[0].lineno if True else 0),
            }
        )

    for name in wanted - found:
        warnings.append(f"未找到模块级函数: {name}")

    return lines, edits, warnings


def apply_edits(lines: list[str], edits: list[dict]) -> str:
    for edit in sorted(edits, key=lambda e: e["from"], reverse=True):
        lines[edit["from"] - 1 : edit["to"]] = [edit["replacement"]]
    return "".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="挖空指定函数的实现")
    parser.add_argument("path", help="要挖空的 .py 文件")
    parser.add_argument("--funcs", required=True, help="函数名，逗号分隔")
    parser.add_argument("--apply", action="store_true", help="真正写入文件（默认只预览）")
    parser.add_argument("--out", help="写到另一个路径而不是原地修改")
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"[FAIL] 文件不存在: {path}")
        return 1

    wanted = {n.strip() for n in args.funcs.split(",") if n.strip()}
    source = path.read_text(encoding="utf-8")

    try:
        lines, edits, warnings = plan_edits(source, wanted)
    except SyntaxError as exc:
        print(f"[FAIL] 语法错误，无法解析: {exc}")
        return 1

    for w in warnings:
        print(f"[WARN] {w}")

    if not edits:
        print("[FAIL] 没有可挖空的函数")
        return 1

    print(f"\n即将挖空 {len(edits)} 个函数（{path}）：")
    for e in edits:
        print(f"  - {e['name']}: 清空第 {e['from']}–{e['to']} 行（{e['line_count']} 行）")

    blanked = apply_edits(list(lines), edits)

    try:
        ast.parse(blanked)
    except SyntaxError as exc:
        print(f"[FAIL] 挖空后语法不合法，已中止（文件未改动）: {exc}")
        return 1

    if not args.apply and not args.out:
        print("\n[DRY-RUN] 未写入。确认无误后加 --apply。")
        preview = blanked.splitlines()
        print("\n--- 挖空后预览（前 40 行）---")
        print("\n".join(preview[:40]))
        return 0

    target = Path(args.out) if args.out else path
    target.write_text(blanked, encoding="utf-8")
    print(f"\n[OK] 已写入 {target}")
    print(f"     还原命令: git checkout main -- {path.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
