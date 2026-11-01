"""CRC detection is exact GF(2) division, not proof of error-free transmission."""
import re

SOLVERS = frozenset({"hx_crc_received_zero_remainder_v1"})


def gf2_remainder(word: int, generator: int) -> int:
    if word < 0 or generator < 2:
        raise ValueError("nonnegative_word_and_nonconstant_generator_required")
    while word.bit_length() >= generator.bit_length():
        word ^= generator << (word.bit_length() - generator.bit_length())
    return word


def problem(q, text):
    match = re.fullmatch(r'采用生成多项式G=([01]{3,17})的CRC校验。以下收到的完整码字中,除以G后余数为零（即通过CRC检测）的是（）。', text)
    if not match:
        return None
    adapter = "hx_crc_received_zero_remainder_v1"
    bits = match[1]
    if q.question_type != "single_choice" or not bits.startswith("1") or not bits.endswith("1"):
        return {"status": "UNKNOWN", "adapter": adapter, "reason": "unsupported_crc_generator_or_question_type"}
    from backend.services.phase45hs_verifiers import value
    words = {key: value(raw) for key, raw in (q.options or {}).items()}
    if not 2 <= len(words) <= 8 or any(not re.fullmatch(r'[01]{1,256}', word) or len(word) < len(bits) for word in words.values()):
        return {"status": "UNKNOWN", "adapter": adapter, "reason": "received_word_outside_bounded_binary_scope"}
    generator = int(bits, 2)
    remainders = {key: gf2_remainder(int(word, 2), generator) for key, word in words.items()}
    matching = [key for key, remainder in remainders.items() if remainder == 0]
    status = "FAIL" if len(matching) != 1 else "PASS" if str(q.correct_answer).strip().upper() == matching[0] else "FAIL"
    proof = {"parameters": {"generator": bits, "received_words": sorted(words.values())},
        "goal": "crc_zero_remainder_detection", "remainders": {key: f"{remainder:0{len(bits)-1}b}" for key, remainder in remainders.items()},
        "division": "GF(2) polynomial long division; subtract by XOR without carries",
        "scope": "remainder zero means detection passes; actual absence of transmission errors is not established"}
    return {"status": status, "adapter": adapter, "reason": "non_unique_zero_remainder" if len(matching) != 1 else
        "derived_key_matches" if status == "PASS" else "derived_key_conflict",
        "derived_answer": matching[0] if len(matching) == 1 else None, "matching_options": matching,
        "proof": proof, "problem_identity": {"adapter": adapter, "parameters": proof["parameters"], "goal": proof["goal"]}}


def explanation(q, independent):
    if independent.get("status") != "PASS" or independent.get("adapter") not in SOLVERS:
        return None
    proof = independent["proof"]
    details = "；".join(f"{key} 项余数为 {value}" for key, value in proof["remainders"].items())
    text = ("按 GF(2) 多项式长除法逐项校验，减法采用异或，不进位也不借位。"
        + details + f"。只有 {independent['derived_answer']} 项余数为全0，故通过 CRC 检测。"
        "检测通过不等于数学上保证传输绝无错误，某些错误模式仍可能漏检。")
    return text, {"adapter": independent["adapter"], "proof": proof}
