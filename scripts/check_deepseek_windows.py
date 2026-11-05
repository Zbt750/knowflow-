#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 宿主机 DeepSeek API 连通性检查（不打印 Key）。"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.long_question_api_worker import check_api  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(check_api())
