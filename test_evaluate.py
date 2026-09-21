"""evaluate.py 의 채점 함수 자체를 검증하는 테스트.

실제로 겪은 사고를 회귀 테스트로 남긴다: classify_failure() 가 정답의 밑줄 코드
표기('이용제한_1개월')와 LLM의 자연어 표기('이용제한 1개월')를 다른 문자열로 보고
정상 답변을 '생성 실패'로 오분류한 적이 있다. 분류기를 고치고 나서 재발하면
이 테스트가 실패해서 바로 알 수 있어야 한다.

실행: pytest test_evaluate.py -v
"""

import networkx as nx
import pytest

from evaluate import (
    classify_failure,
    evidence_recall,
    fact_exists_anywhere_in_graph,
    normalize_for_compare,
    path_recall,
)


# ---------------------------------------------------------------------------
# normalize_for_compare
# ---------------------------------------------------------------------------
def test_normalize_strips_underscore_and_space():
    assert normalize_for_compare("이용제한_1개월") == normalize_for_compare("이용제한 1개월")


def test_normalize_distinguishes_different_values():
    assert normalize_for_compare("이용제한_1개월") != normalize_for_compare("이용제한_3개월")


# ---------------------------------------------------------------------------
# path_recall
# ---------------------------------------------------------------------------
def test_path_recall_none_when_no_expected_path():
    assert path_recall([], ["A -[REL]-> B"]) is None


def test_path_recall_full_match():
    expected = ["A -[LOCATED_IN]-> B"]
    actual = ["A -[LOCATED_IN]-> B", "A -[HANDLES]-> C"]
    assert path_recall(expected, actual) == 1.0


def test_path_recall_partial_match():
    expected = ["A -[LOCATED_IN]-> B", "A -[HANDLES]-> C"]
    actual = ["A -[LOCATED_IN]-> B"]
    assert path_recall(expected, actual) == 0.5


def test_path_recall_zero_when_relation_missing():
    expected = ["A -[VIOLATED]-> X"]
    actual = ["A -[HANDLES]-> C"]
    assert path_recall(expected, actual) == 0.0


# ---------------------------------------------------------------------------
# evidence_recall
# ---------------------------------------------------------------------------
def test_evidence_recall_none_when_no_expected_evidence():
    assert evidence_recall([], ["a.md"]) is None


def test_evidence_recall_partial():
    assert evidence_recall(["a.md", "b.md"], ["a.md"]) == 0.5


def test_evidence_recall_full():
    assert evidence_recall(["a.md", "b.md"], ["a.md", "b.md"]) == 1.0


# ---------------------------------------------------------------------------
# fact_exists_anywhere_in_graph / classify_failure
# ---------------------------------------------------------------------------
@pytest.fixture
def toy_graph():
    g = nx.DiGraph()
    g.add_node("SupplyCompany::A", type="SupplyCompany", name="A")
    g.add_node("ViolationType::V", type="ViolationType", name="V")
    g.add_edge("SupplyCompany::A", "ViolationType::V", relation="VIOLATED", source_docs="a.md")
    return g


def test_fact_exists_anywhere_true(toy_graph):
    assert fact_exists_anywhere_in_graph(toy_graph, {"a.md"}) is True


def test_fact_exists_anywhere_false(toy_graph):
    assert fact_exists_anywhere_in_graph(toy_graph, {"없는문서.md"}) is False


def test_classify_failure_normal_when_evidence_and_answer_match(toy_graph):
    item = {"evidence": ["a.md"], "expected_answer": "A: 이용제한_1개월"}
    result = {"evidence": ["a.md"], "answer": "A는 이용제한 1개월의 제재를 받았습니다.\n\n근거: a.md"}
    assert classify_failure(item, result, toy_graph) is None


def test_classify_failure_regression_underscore_vs_space(toy_graph):
    """실제로 겪은 버그의 회귀 테스트. 이 테스트가 실패하면 그 버그가 되살아난 것이다."""
    item = {"evidence": ["a.md"], "expected_answer": "이용제한_1개월"}
    result = {"evidence": ["a.md"], "answer": "제재는 이용제한 1개월입니다.\n\n근거: a.md"}
    assert classify_failure(item, result, toy_graph) is None


def test_classify_failure_generation_when_answer_truly_unrelated(toy_graph):
    item = {"evidence": ["a.md"], "expected_answer": "이용제한_1개월"}
    result = {"evidence": ["a.md"], "answer": "죄송하지만 답변을 생성할 수 없습니다.\n\n근거: a.md"}
    assert classify_failure(item, result, toy_graph) == "생성"


def test_classify_failure_index_when_fact_missing_from_whole_graph(toy_graph):
    item = {"evidence": ["a.md", "없는문서.md"], "expected_answer": "이용제한_1개월"}
    result = {"evidence": ["a.md"], "answer": "이용제한 1개월\n\n근거: a.md"}
    assert classify_failure(item, result, toy_graph) == "색인"


def test_classify_failure_search_when_fact_exists_but_not_retrieved():
    g = nx.DiGraph()
    g.add_node("SupplyCompany::A", type="SupplyCompany", name="A")
    g.add_node("SupplyCompany::B", type="SupplyCompany", name="B")
    g.add_node("RegionalOffice::R", type="RegionalOffice", name="R")
    g.add_edge("SupplyCompany::A", "RegionalOffice::R", relation="LOCATED_IN", source_docs="a.md")
    g.add_edge("SupplyCompany::B", "RegionalOffice::R", relation="LOCATED_IN", source_docs="b.md")

    item = {"evidence": ["a.md", "b.md"], "expected_answer": "B"}
    result = {"evidence": ["a.md"], "answer": "A만 찾았습니다.\n\n근거: a.md"}
    assert classify_failure(item, result, g) == "탐색"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
