from types import SimpleNamespace as N

from scripts.report_question_counts import summarize, markdown


def node(identifier, code="cs408.ds.topic.sample", name="隔离样例", parent=None, assessable=True):
    return N(id=identifier, code=code, name=name, parent_id=parent, is_active=True,
             is_assessable=assessable, subject="408")


def reference(kp, year=2026, number=1):
    return N(knowledge_point_id=kp, subject="408", year=year, question_number=number)


def test_same_exam_across_summary_and_leaf_not_added_to_global_total():
    nodes = [node(1), node(2, "cs408.ds.family.trees")]
    report = summarize(nodes, [], [reference(1), reference(1), reference(2)])
    assert report["distinct_indexed_exam_questions"] == 1
    assert report["nodes"][0]["exam_reference_windows"]["2010_2026"] == 1
    assert report["subjects"]["408"]["individual_nodes"] == 1
    assert report["subjects"]["408"]["topic_summary_nodes"] == 1


def test_year_windows_and_missing_nodes_preserve_low_frequency_cases():
    report = summarize([node(1), node(2)], [], [reference(1, 2010), reference(1, 2020, 2)])
    r = report["subjects"]["408"]["windows"]
    assert r["2010_2026"]["distinct_indexed_questions"] == 2
    assert r["2017_2026"]["distinct_indexed_questions"] == 1
    assert r["2021_2026"]["individual_nodes_with_zero_refs"] == 2
    assert r["2010_2026"]["individual_nodes_below_minimum_refs"] == 2


def test_retired_questions_not_online_and_transcription_not_automatic():
    q = N(kp_id=1, is_active=True, question_type="single_choice", correct_answer="A", options={"A": "甲"},
          grading_config={"verified": False, "provenance": {"content_status": "source_transcribed"}})
    retired = N(kp_id=1, is_active=False)
    report = summarize([node(1)], [q, retired], [reference(1)])
    assert report["online_total"] == 1
    assert report["nodes"][0]["transcribed_unverified"] == 1
    assert report["nodes"][0]["automatic_grading"] == 0
    assert report["nodes"][0]["online_gap"] == 4


def test_category_not_counted_as_leaf_and_markdown_escapes_names():
    report = summarize([node(1, name="含|分隔符", assessable=False)], [], [])
    assert report["assessable_nodes"] == 0
    assert report["nodes"][0]["online_gap"] is None
    assert "含\\|分隔符" in markdown(report)
