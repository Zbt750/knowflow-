"""Recover three 2017 408 questions whose source IDs were still unmatched."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch

batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261011/batch-23-originals-retry"
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-24-recover-q04-q05-q13"
batch.PACK = ROOT / "storage/question-intake/phase45hx-20261011/phase45hx-408-2017-q04-q05-q13-v1.json"
batch.PDF = Path("C:/Users/ZBT/Desktop/考研知识点/408/2017/2017年计算机408统考真题.pdf")
batch.PDF_SHA = "16f9c9afac663bc64e4057fe666d4563091349f71ba4113c26f58a66ea449883"
batch.EXPECTED_QUESTIONS = 3
batch.PROCESS_PACK = True
batch.CODEX_PUBLIC_ORIGINALS = []
batch.SOURCE_SUCCESS_STATUS = "BATCH_23_ORIGINALS_RETRY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-24-recover-q04-q05-q13"
batch.SUCCESS_STATUS = "BATCH_24_COMPLETE"
batch.TEST_FILES = [
    "tests/integration/test_auto_question_review.py",
    "tests/integration/test_question_pack_import.py",
    "tests/unit/test_phase45hx_recovery.py",
]
batch.TEST_ARGS = ["-k", "hash_bound_codex_review_can_replace_missing_solver"]

batch.CODEX_REVIEW_EVIDENCE = {
    "408-2017-q04-preorder-inorder-equality": {
        "derived_answer": "B",
        "method_evidence": [
            {"method": "preorder-inorder-root-position", "result": "先序首元素是根；中序根前的所有元素来自左子树。两序列相同要求左子树为空。"},
            {"method": "recursive-subtree-condition", "result": "对每个非叶子子树递归应用同一条件，每个非叶结点只能有右子树，故B。"},
        ],
        "explanation_key_steps": [
            "根在先序中首先出现，而中序中根之前恰是左子树遍历序列。",
            "两序列相同要求左子树为空；对子树递归后，每个非叶结点只能有右子树。",
        ],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
    },
    "408-2017-q05-postorder-same-level": {
        "derived_answer": "B",
        "method_evidence": [
            {"method": "explicit-tree-levels", "result": "按原卷左右孩子图转为明确结构：f为根，c/g在第1层，a/d在第2层，e/b在第3层；与a同层的是d。"},
            {"method": "postorder-cross-check", "result": "该结构后序为e,a,c,b,d,g,f，与题干给定后序一致；d与a深度相同，选B。"},
        ],
        "explanation_key_steps": [
            "先根据原卷图示确定左右孩子关系，并用题给后序序列交叉检查结构转录。",
            "从根f计层，a与d均在深度2；选项中只有d符合。",
        ],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
    },
    "408-2017-q13-unaligned-double-memory-cycles": {
        "derived_answer": "C",
        "method_evidence": [
            {"method": "byte-span-and-word-boundaries", "result": "每次传送4字节，起始偏移2，double占8字节，覆盖10字节跨度，需要ceil(10/4)=3次。"},
            {"method": "aligned-block-enumeration", "result": "地址0x...1A到0x...21跨越对齐块0x...18–1B、1C–1F、20–23，共3个32位块。"},
        ],
        "explanation_key_steps": [
            "总线每次最多传送4字节；起始地址0x...1A在该4字节边界内偏移2字节。",
            "8字节double覆盖3个连续4字节对齐块，因此需3个存储周期。",
        ],
        "option_truth_table": {"A": False, "B": False, "C": True, "D": False},
    },
}

if __name__ == "__main__":
    batch.main()
