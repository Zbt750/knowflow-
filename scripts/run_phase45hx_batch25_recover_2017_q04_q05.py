"""Recover 2017 408 Q4/Q5; Q13 is already present and remains untouched."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch

batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261011/batch-23-originals-retry"
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-25-recover-q04-q05"
batch.PACK = ROOT / "storage/question-intake/phase45hx-20261011/phase45hx-408-2017-q04-q05-v1.json"
batch.PDF = Path("C:/Users/ZBT/Desktop/考研知识点/408/2017/2017年计算机408统考真题.pdf")
batch.PDF_SHA = "16f9c9afac663bc64e4057fe666d4563091349f71ba4113c26f58a66ea449883"
batch.EXPECTED_QUESTIONS = 2
batch.PROCESS_PACK = True
batch.CODEX_PUBLIC_ORIGINALS = []
batch.SOURCE_SUCCESS_STATUS = "BATCH_23_ORIGINALS_RETRY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-25-recover-q04-q05"
batch.SUCCESS_STATUS = "BATCH_25_COMPLETE"
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
            {"method": "preorder-inorder-root-position", "result": "先序首元素是根；中序根前的元素属于左子树。两序列相同要求左子树为空。"},
            {"method": "recursive-subtree-condition", "result": "对子树递归同理，每个非叶结点只能有右子树，答案B。"},
        ],
        "explanation_key_steps": [
            "先序中根最先访问，中序中根之前访问左子树。",
            "要使两序列相同，根及每个子树根都不能有左子树。",
        ],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
    },
    "408-2017-q05-postorder-same-level": {
        "derived_answer": "B",
        "method_evidence": [
            {"method": "original-tree-structure-and-levels", "result": "原卷图的孩子关系编码为f:(c,g), c:(空,a), a:(e,空), g:(d,空), d:(空,b)；a和d深度均为2。"},
            {"method": "postorder-sequence-cross-check", "result": "对该树执行左右根后序得到e,a,c,b,d,g,f，与题干相同；同层选项为d，即B。"},
        ],
        "explanation_key_steps": [
            "按原卷图示恢复左右孩子关系，并用题干后序序列核对转录。",
            "从根开始计层，a与d同为第2层；答案B。",
        ],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
    },
}

if __name__ == "__main__":
    batch.main()
