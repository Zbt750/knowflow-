from __future__ import annotations

import importlib
import pkgutil

# 登记所有模型模块（autogenerate 通过 import_models 遍历包内模块）。
MODEL_MODULES = ("learning", "rag", "jobs")


def import_models() -> None:
    """显式 import 所有模型模块，再读取 Base.metadata。"""
    # 用 importlib 遍历包内模块，避免“新模型文件忘了登记”导致迁移缺表。
    package = importlib.import_module(__name__)
    for info in pkgutil.iter_modules(package.__path__):
        if info.name in {"base", "types", "enums"}:
            continue
        importlib.import_module(f"{__name__}.{info.name}")


# 导入本包即完成注册：任何模块（含新写的脚本、后台任务）只要用到 ORM 模型，
# 都会经过这里的导入链。否则「只导入 chat 模型、没导入 learning」会让
# SQLAlchemy 在解析外键时报 NoReferencedTableError ——
# 那是个只在特定导入顺序下才出现的偶发故障，极难排查。
import_models()

__all__ = ["MODEL_MODULES", "import_models"]