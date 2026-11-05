"""Restore a bounded set of 2017 408 public questions from the 15b clone.

This batch reuses the existing question-pack importer and qualification service.
Codex independent reviews are explicit, item-bound evidence, not human review.
All writes stay in a fresh clone of the named isolated checkpoint.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch

batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261011/batch-15b"
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-16-final"
batch.PACK = ROOT / "storage/question-intake/phase45hx-20261011/phase45hx-408-2017-batch16-v1.json"
batch.PDF = Path("C:/Users/ZBT/Desktop/考研知识点/408/2017/2017年计算机408统考真题.pdf")
batch.PDF_SHA = "16f9c9afac663bc64e4057fe666d4563091349f71ba4113c26f58a66ea449883"
batch.EXPECTED_QUESTIONS = 8
batch.SOURCE_SUCCESS_STATUS = "BATCH_05_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-16"
batch.SUCCESS_STATUS = "BATCH_16_COMPLETE"
batch.TEST_FILES = [
    "tests/integration/test_auto_question_review.py",
    "tests/integration/test_question_pack_import.py",
    "tests/unit/test_phase45hx_recovery.py",
]
batch.TEST_ARGS = ["-k", "hash_bound_codex_review_can_replace_missing_solver"]

METHODS = {
    "408-2017-q24-system-call-order": (
        "C",
        [{"method": "kernel-entry-state-order", "result": "参数在用户态准备；trap之后CPU进入内核并分派服务程序；服务结束后才恢复用户态，故顺序只能是③②④①。"},
         {"method": "constraint-elimination", "result": "检查四个序列：A把返回用户态放在服务前，B把服务放在参数传递前，D把服务放在trap之前；仅C满足调用因果顺序。"}],
        ["用户态先按调用约定放置参数，随后执行trap进入内核。", "内核完成服务程序后才返回用户态，因此正确选项为C。"],
        {"A": False, "B": False, "C": True, "D": False}),
    "408-2017-q28-multiprogramming-advantages": (
        "D",
        [{"method": "resource-overlap-model", "result": "CPU与I/O等待可由不同作业交替覆盖，提升CPU与I/O利用率；多作业推进增加单位时间完成量。"},
         {"method": "statement-by-statement", "result": "I、III、IV符合多道程序的资源重叠收益；II错误，因为调度、切换、保护等管理成本通常增加而非变小。"}],
        ["作业交替执行可减少CPU空闲，并提高I/O设备利用率和吞吐量。", "多道管理引入额外调度与保护开销，II不成立，组合为D。"],
        {"A": False, "B": False, "C": False, "D": True}),
    "408-2017-q31-hard-link-open-file-offsets": (
        "B",
        [{"method": "filesystem-object-model", "result": "硬链接增加目录项但指向同一inode；两次独立open创建各自的打开文件对象/偏移，故I错、II对。"},
         {"method": "process-descriptor-table-model", "result": "每进程fd表中分别有fd1与fd2项，二者对应各自打开项；结合共享inode可得II与III成立，即B。"}],
        ["同一硬链接文件名对应同一inode，但独立open不会因此共享文件读写偏移。", "各自进程描述符表项分别指向打开文件项，故II、III正确，选B。"],
        {"A": False, "B": True, "C": False, "D": False}),
    "408-2017-q32-dma-sequence": (
        "B",
        [{"method": "device-state-transition", "result": "DMA寄存器初始化并启动设备是数据搬运前提；块搬运完成触发DMA中断，CPU随后进入结束服务程序。"},
         {"method": "event-causality", "result": "中断不可能先于本次块传输完成，初始化也不能晚于传输；四步因果关系唯一排列为②③①④。"}],
        ["先初始化DMA并启动磁盘，随后DMA把一块数据送入内存缓冲区。", "数据块完成后产生中断请求，最后执行结束中断服务程序，答案B。"],
        {"A": False, "B": True, "C": False, "D": False}),
    "408-2017-q35-80211-three-addresses": (
        "B",
        [{"method": "80211-to-ds-field-mapping", "result": "主机到AP的To-DS帧中Addr1是接收AP/BSSID，Addr2是发送站H，Addr3是分布系统目的端R。"},
         {"method": "address-role-substitution", "result": "将图中MAC代入角色：AP=…9b、H=…9a、R=…9c，地址序列为…9b、…9a、…9c，对应B。"}],
        ["To-DS方向的第一地址指向AP，第二地址标识发送主机H。", "第三地址承载分布系统中的目的路由器R地址，代入图中MAC得到B。"],
        {"A": False, "B": True, "C": False, "D": False}),
    "408-2017-q36-ipv4-source-only-address": (
        "A",
        [{"method": "special-address-semantics", "result": "0.0.0.0可在地址配置初期作为未配置主机的源地址，但不是可路由目的主机地址。"},
         {"method": "option-role-comparison", "result": "127.0.0.1用于回送且可作目的；200.10.10.3为普通单播；255.255.255.255是目的受限广播，只有A符合。"}],
        ["初始化配置场景允许主机以0.0.0.0表示未获得地址的源端。", "回送地址、普通单播与受限广播均可作为目的类地址使用，故源专用项为A。"],
        {"A": True, "B": False, "C": False, "D": False}),
    "408-2017-q38-subnet-host-count": (
        "C",
        [{"method": "prefix-bit-allocation", "result": "128=2^7，需借7位子网位，前缀/16变为/23，留下32-23=9个主机位。"},
         {"method": "address-count", "result": "9位主机字段有512个地址，普通子网排除网络号与广播地址，得到512-2=510，对应C。"}],
        ["划分128个等规模子网需要7位子网号，因此子网前缀为/23。", "9位主机空间共有512个地址，除去网络与广播地址后可分配510个。"],
        {"A": False, "B": False, "C": True, "D": False}),
    "408-2017-q39-tcp-slow-start-rounds": (
        "A",
        [{"method": "cwnd-recurrence", "result": "慢启动从1 MSS开始，每个RTT约翻倍：1、2、4、8、16、32KB，需5个增长轮次。"},
         {"method": "window-minimum-bound", "result": "接收缓存64KB大于目标32KB，不先限制窗口；5个RTT乘以5ms/RTT等于25ms。"}],
        ["初始拥塞窗口按1 MSS计，逐RTT翻倍到32 MSS需五轮。", "接收窗口上限64KB不构成更紧约束，至少耗时5×5ms=25ms，选A。"],
        {"A": True, "B": False, "C": False, "D": False}),
}

batch.CODEX_REVIEW_EVIDENCE = {
    source_id: {"derived_answer": answer, "method_evidence": methods,
        "explanation_key_steps": steps, "option_truth_table": truth}
    for source_id, (answer, methods, steps, truth) in METHODS.items()
}


if __name__ == "__main__":
    batch.main()
