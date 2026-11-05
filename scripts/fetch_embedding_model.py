"""临时脚本：通过国内镜像下载真正的 bge-small-zh-v1.5（用完即删）。

背景：本机缓存的 `models--BAAI--bge-small-zh-v1.5` 其实是 hidden_size=512、
只有 4 层的替身模型，而向量库集合是 384 维，导致资料索引必然失败
（`Collection expecting embedding with dimension of 384, got 512`）。
这里从 hf-mirror.com 取回官方权重（应为 12 层 / hidden_size 384）。
"""

import json
import os
from pathlib import Path

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

from huggingface_hub import snapshot_download  # noqa: E402

target = Path(r"D:\考研跑通项目\storage\models-real")
target.mkdir(parents=True, exist_ok=True)

print("开始下载 BAAI/bge-small-zh-v1.5（镜像 hf-mirror.com）…")
path = snapshot_download(
    repo_id="BAAI/bge-small-zh-v1.5",
    cache_dir=str(target),
    allow_patterns=[
        "*.json",
        "*.txt",
        "*.safetensors",
        "*.md",
        "*.model",
        "1_Pooling/*",
    ],
)
print("下载完成：", path)

configs = list(Path(path).glob("config.json"))
if configs:
    cfg = json.loads(configs[0].read_text(encoding="utf-8"))
    print("hidden_size =", cfg.get("hidden_size"))
    print("num_hidden_layers =", cfg.get("num_hidden_layers"))
    print("architectures =", cfg.get("architectures"))
    if cfg.get("hidden_size") == 384:
        print("结论：拿到的是**正确的官方模型**（384 维）")
    else:
        print("结论：维度仍不是 384，需要人工确认")
for f in sorted(Path(path).iterdir()):
    size = f.stat().st_size if f.is_file() else 0
    print(f"  {f.name:38s} {size/1024/1024:8.2f} MB" if size else f"  {f.name}/")
