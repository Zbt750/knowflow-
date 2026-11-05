"""Recovery adapters must prove new parameters and reject unsupported premises."""
from copy import deepcopy
from functools import lru_cache
from itertools import permutations
from types import SimpleNamespace

from backend.services.phase45hs_verifiers import problem, explanation
from backend.services.question_identity import verified_identity


def lane_question(sequence, answer, options=None):
    count = len(sequence)
    return SimpleNamespace(
        stem=(f"设有火车车轨，入口到出口之间有 n 条轨道，列车的行进方向均为从左至右，列车可驶入任意一条轨道。"
              f"现有编号为 1～{count} 的 {count} 列列车，驶入的次序依次是 {','.join(map(str, sequence))}。"
              f"若期望驶出的次序依次为 1～{count}，则 n 至少是（ ）。"),
        question_type="single_choice" if options else "fill_blank",
        correct_answer=answer, options=options,
    )


def exhaustive_minimum_lanes(sequence):
    """Independent small-instance oracle: enumerate FIFO lane assignments."""
    @lru_cache(None)
    def assign(index, tails):
        if index == len(sequence):
            return len(tails)
        car = sequence[index]
        values = [assign(index + 1, tuple(sorted((*tails, car))))]
        for lane, tail in enumerate(tails):
            if tail < car:
                updated = list(tails)
                updated[lane] = car
                values.append(assign(index + 1, tuple(sorted(updated))))
        return min(values)
    return assign(0, ())


def test_unseen_permutations_against_exhaustive_lane_assignment():
    for count in range(2, 7):
        for sequence in permutations(range(1, count + 1)):
            expected = exhaustive_minimum_lanes(sequence)
            result = problem(lane_question(sequence, str(expected)))
            assert result and result["status"] == "PASS", (sequence, result)
            proof = result["proof"]
            assert proof["lower_bound"] == proof["upper_bound"] == expected
            assert all(all(a < b for a, b in zip(lane, lane[1:]))
                       for lane in proof["increasing_fifo_lanes"])


def test_options_wrong_answer_ambiguity_and_cross_format_identity():
    sequence = (4, 2, 1, 3, 5)
    correct = lane_question(sequence, "C", {"A": "1", "B": "2", "C": "3", "D": "4"})
    result = problem(correct)
    assert result["status"] == "PASS"
    assert "最少轨道数为 3" in explanation(correct, result)[0]
    wrong = deepcopy(correct)
    wrong.correct_answer = "B"
    assert problem(wrong)["status"] == "FAIL"
    ambiguous = deepcopy(correct)
    ambiguous.options["D"] = "3.0"
    assert problem(ambiguous)["status"] == "FAIL"
    unsupported = deepcopy(correct)
    unsupported.options["D"] = "n+1"
    assert problem(unsupported)["status"] == "UNKNOWN"
    fill = lane_question(sequence, "3")
    assert verified_identity(fill) == verified_identity(correct)
    assert verified_identity(fill) != verified_identity(lane_question((1, 2, 3, 4, 5), "1"))


def test_invalid_or_changed_track_conditions_are_not_guessed():
    duplicate_car = lane_question((1, 1, 3), "2")
    assert problem(duplicate_car)["status"] == "UNKNOWN"
    missing_car = lane_question((1, 2, 4), "1")
    assert problem(missing_car)["status"] == "UNKNOWN"
    for replacement in ("列车可超越前车", "列车可以由右至左行驶"):
        changed = lane_question((3, 1, 2), "2")
        changed.stem = changed.stem.replace("列车的行进方向均为从左至右", replacement)
        assert problem(changed) is None
    changed = lane_question((3, 1, 2), "2")
    changed.stem += "列车还可以在轨道中间换轨。"
    assert problem(changed) is None
