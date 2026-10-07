from collections import Counter

from scripts.expand_phase3b_inventory import select_coverage, stop_reasons


def candidate(qid, node, *, selectable=True, qtype="single_choice", caps=("basic",)):
    return {}, {"question_id": qid, "kp_id": node, "expansion_selectable": selectable,
        "question_type": qtype, "capabilities": list(caps), "subject": "408",
        "year": 2020, "candidate_id": qid}


def pick(pairs, counts=None, types=None, caps=None, limit=50, excluded=None):
    return select_coverage([r for r,s in pairs], [s for r,s in pairs],
        Counter(counts or {}), types or {}, caps or {}, limit, excluded or set())


def test_no_candidate_can_bypass_confidence_or_previous_selection():
    selected=pick([candidate("blocked","zero",selectable=False),candidate("done","zero"),candidate("new","one")],excluded={"done"})
    assert [s["question_id"] for _,s in selected]==["new"]


def test_zero_nodes_precede_single_and_populated_nodes_and_virtual_count_spreads_picks():
    selected=pick([candidate("a1","a"),candidate("a2","a"),candidate("b1","b"),candidate("c1","c")],counts={"c":1},limit=3)
    assert {s["kp_id"] for _,s in selected[:2]}=={"a","b"}
    assert [s["selection_priority"] for _,s in selected]==[0,0,1]


def test_new_capability_precedes_higher_volume_with_same_count():
    selected=pick([candidate("a","one",caps=("basic",)),candidate("b","two",qtype="fill_blank",caps=("transfer",))],
        counts={"one":2,"two":2},types={"one":{"single_choice"},"two":{"single_choice"}},
        caps={"one":{"basic"},"two":{"basic"}},limit=1)
    assert selected[0][1]["question_id"]=="b"


def metrics(**changes):
    return {"provider_errors":0,"persisted_run_attempts":30,"observed_tokens":{"total_tokens":20000},**changes}


def test_individual_incomplete_is_isolated_but_systemic_rate_stops():
    assert not stop_reasons([{"status":"INCOMPLETE"}]+[{"status":"AI_CONSISTENT"}]*9,metrics())
    assert "excessive_incomplete" in stop_reasons([{"status":"INCOMPLETE"}]*4+[{"status":"AI_CONSISTENT"}]*6,metrics())
    assert "excessive_disagreement" in stop_reasons([{"status":"AI_DISAGREEMENT"}]*3+[{"status":"AI_CONSISTENT"}]*7,metrics())


def test_internal_pipeline_failure_stops_without_waiting_for_rate_sample():
    assert "pipeline_internal_error" in stop_reasons([{"status":"INTERNAL_ERROR"}],metrics())
