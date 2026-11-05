from copy import deepcopy
from types import SimpleNamespace
from sympy import Poly, Symbol

from backend.services.phase45hx_crc_verifier import gf2_remainder
from backend.services.phase45hs_verifiers import problem, explanation


def question(generator="10011", answer="D"):
    return SimpleNamespace(question_type="single_choice", correct_answer=answer,
        stem=f"采用生成多项式 G={generator} 的 CRC 校验。以下收到的完整码字中，除以 G 后余数为零（即通过 CRC 检测）的是（）。",
        options={"A": "101110000", "B": "101110100", "C": "101111000", "D": "101111100"})


def reference_remainder(word, generator):
    x = Symbol("x")
    def polynomial(bits):
        return Poly(sum(((bits >> power) & 1) * x ** power for power in range(bits.bit_length())), x, modulus=2)
    result = polynomial(word).rem(polynomial(generator))
    return sum(int(result.nth(power)) % 2 << power for power in range(generator.bit_length()-1))


def test_xor_division_against_independent_symbolic_gf2_oracle():
    for generator in (0b1011, 0b1101, 0b10011, 0b11001):
        for word in range(256):
            assert gf2_remainder(word, generator) == reference_remainder(word, generator)


def test_crc_unique_option_wrong_answer_ambiguity_and_scope():
    q = question()
    result = problem(q)
    assert result["status"] == "PASS" and result["matching_options"] == ["D"]
    assert result["proof"]["remainders"]["D"] == "0000"
    assert "不等于" in explanation(q, result)[0]
    q.correct_answer = "A"
    assert problem(q)["status"] == "FAIL"
    q = question()
    q.options["A"] = q.options["D"]
    assert problem(q)["status"] == "FAIL"
    q = question()
    q.options["A"] = "10012"
    assert problem(q)["status"] == "UNKNOWN"
    assert problem(question(generator="01011"))["status"] == "UNKNOWN"
    q = question()
    q.stem += "检测通过即证明物理传输绝无错误。"
    assert problem(q) is None


def test_original_ambiguous_guarantee_is_not_automatically_certified():
    q = question()
    q.stem = "CRC 可以断定收到的比特串在传输过程中未发生错误。"
    assert problem(q)["status"] == "UNKNOWN"


def test_huffman_original_correction_and_old_truncation_remain_distinct():
    q = SimpleNamespace(question_type="single_choice", correct_answer="D",
        stem="字符 a…h 的码字依次为 0100、10、0000、0101、001、011、11、0001。译码串 0100011001001011110101，选结果：",
        options={"A": "acgabfh", "B": "adbagbb", "C": "afbeagd", "D": "afeefgd"})
    assert problem(q)["status"] == "PASS"
    old = deepcopy(q)
    old.stem = old.stem.replace("0100011001001011110101", "010001100100101011110101")
    assert problem(old)["status"] == "UNKNOWN"
