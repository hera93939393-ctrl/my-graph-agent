"""
그래프 추출 + 정규화.

1) 사례문서(합성 심사결과서, 반구조화)  -> 절 헤더 기반 규칙 추출
2) 규정문서(서류심사 세부기준 등, 산문) -> 스키마 어휘(별칭 포함) co-occurrence 추출
3) 정규화: HACCP(품목) 세부 인증을 상위 HACCP 개념에 병합, 고립 노드 제거

출력: ./output/graph.graphml
"""

import json
import os
import re

import networkx as nx

from corpus_utils import load_cases, load_reference_docs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUT_DIR = os.path.join(BASE_DIR, "output")
GRAPH_PATH = os.path.join(OUT_DIR, "graph.graphml")

# 규정문서 산문 안에서 규정명이 실제로 등장하는 표기 (별칭)
REGULATION_ALIASES = {
    "학교급식법_시행규칙": "학교급식법 시행규칙",
    "식품위생법": "식품위생법",
    "축산물_위생관리법": "축산물 위생관리법",
    "화물자동차_운수사업법": "화물자동차 운수사업법",
    "감염병의_예방및관리에관한법률_시행규칙": "감염병의 예방 및 관리에 관한 법률 시행규칙",
    "eaT_이용약관": "eaT 이용약관",
}

# 위반유형 코드가 규정문서 산문에서 실제로 등장하는 표현(별칭 여러 개 가능)
VIOLATION_ALIASES = {
    "주민등록번호_미마스킹": ["주민등록번호"],
    "원본대조필_누락": ["원본대조필"],
    "서류_유효기간_만료": ["유효기간"],
    "소재지_불일치": ["소재지"],
    "열람용_등기부등본_제출": ["열람용"],
    "현장심사_수진자_자격미달": ["수진자"],
    "옥외_탈부착간판": ["탈부착"],
    "타업체와_사업장_미분리": ["분리된 사업장", "시건장치"],
    "창고_공동사용": ["공동사용"],
    "야외창고_사용": ["야외 창고"],
    "냉장냉동_미분리": ["냉장·냉동 보관 구역"],
    "냉장온도_기준초과": ["냉장", "10℃"],
    "냉동온도_기준초과": ["냉동", "-18℃"],
    "방충방서시설_미비": ["방충", "쥐막이"],
    "정기소독_미실시": ["소독"],
    "건강진단서_미구비": ["건강진단결과서", "건강진단"],
}

COLD_CHAIN_LINE_RE = re.compile(r"-\s*(\S+?)\s*:\s*냉장\s*(필요|불필요),\s*냉동\s*(필요|불필요)")
COLD_TEMP_RE = re.compile(r"냉장은\s*(-?\d+)℃\s*이하,\s*냉동은\s*(-?\d+)℃\s*이하")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def node_id(ntype, name):
    return f"{ntype}::{name}"


def add_node(g, ntype, name, **attrs):
    nid = node_id(ntype, name)
    if nid not in g:
        g.add_node(nid, type=ntype, name=name)
    for k, v in attrs.items():
        if v is not None:
            g.nodes[nid][k] = v
    return nid


def add_edge(g, src, relation, dst, source_doc):
    if g.has_edge(src, dst):
        data = g[src][dst]
        rels = set(filter(None, data.get("relation", "").split("|")))
        rels.add(relation)
        data["relation"] = "|".join(sorted(rels))
        docs = set(filter(None, data.get("source_docs", "").split("|")))
        docs.add(source_doc)
        data["source_docs"] = "|".join(sorted(docs))
    else:
        g.add_edge(src, dst, relation=relation, source_docs=source_doc)


# ---------------------------------------------------------------------------
# 1) 사례문서 추출 (절 헤더 기반 규칙 추출 — 이미 구조화된 문서이므로 결정적으로 파싱)
# ---------------------------------------------------------------------------
def extract_case_doc(g, case):
    file = case["file"]
    company = add_node(
        g, "SupplyCompany", case["company"],
        doc_result=case["doc_result"], site_result=case["site_result"],
        final_result=case["final_result"],
    )
    region = add_node(g, "RegionalOffice", case["region"])
    add_edge(g, company, "LOCATED_IN", region, file)

    for item in case["items"]:
        item_node = add_node(g, "HandlingItem", item)
        add_edge(g, company, "HANDLES", item_node, file)

    for cert in case["certs"]:
        cert_node = add_node(g, "Certification", cert)
        add_edge(g, company, "HOLDS", cert_node, file)

    for doc_type in case["submitted_docs"]:
        doc_node = add_node(g, "DocumentType", doc_type)
        add_edge(g, company, "SUBMITTED", doc_node, file)

    violation_nodes = []
    for v in case["violations"]:
        v_node = add_node(g, "ViolationType", v)
        add_edge(g, company, "VIOLATED", v_node, file)
        violation_nodes.append(v_node)

    for s in case["sanctions"]:
        s_node = add_node(g, "Sanction", s)
        # 업체 -> 제재 직접 엣지. ViolationType -> Sanction 만 있으면 같은 위반유형을
        # 공유하는 업체들의 제재가 한 엣지에 뭉뚱그려져(source_docs만 여러 개), 답변
        # 생성·검증 단계에서 "이 업체가 정확히 어떤 제재를 받았는지"를 간접 추론해야
        # 했다 — 실제로 이 간접성 때문에 검증기가 틀린 값을 못 고치고 통째로 들어내는
        # 사례가 나왔다(REPORT.md 3절/6절). 업체별 사실을 엣지 하나로 직접 조회 가능하게 한다.
        add_edge(g, company, "RESULTS_IN", s_node, file)
        for v_node in violation_nodes:
            add_edge(g, v_node, "RESULTS_IN", s_node, file)


# ---------------------------------------------------------------------------
# 2) 규정문서 추출 (산문 -> 절 단위 co-occurrence)
# ---------------------------------------------------------------------------
def split_blocks(text):
    """## / ### 헤더 단위로 쪼갠다. 절 하나 = co-occurrence 판단 단위."""
    parts = re.split(r"\n(?=#{2,3} )", text)
    return [p for p in parts if p.strip()]


def extract_reference_doc(g, filename, text, vocab):
    for block in split_blocks(text):
        present_regs = [code for code, phrase in REGULATION_ALIASES.items() if phrase in block]
        present_viols = [code for code, aliases in VIOLATION_ALIASES.items() if any(a in block for a in aliases)]
        present_doctypes = [d for d in vocab["document_types"] if d in block]

        for reg_code in present_regs:
            reg_node = add_node(g, "Regulation", reg_code)
            for v_code in present_viols:
                v_node = add_node(g, "ViolationType", v_code)
                add_edge(g, v_node, "GOVERNED_BY", reg_node, filename)
            for d in present_doctypes:
                d_node = add_node(g, "DocumentType", d)
                add_edge(g, d_node, "GOVERNED_BY", reg_node, filename)

        for m in COLD_CHAIN_LINE_RE.finditer(block):
            item, cold, frozen = m.group(1), m.group(2), m.group(3)
            if item in vocab["handling_items"]:
                item_node = add_node(
                    g, "HandlingItem", item,
                    requires_cold=(cold == "필요"), requires_frozen=(frozen == "필요"),
                )
                if cold == "필요" or frozen == "필요":
                    std_node = add_node(g, "Standard", "냉장냉동온도기준")
                    add_edge(g, item_node, "REQUIRES_TEMP", std_node, filename)

        temp_match = COLD_TEMP_RE.search(block)
        if temp_match:
            add_node(
                g, "Standard", "냉장냉동온도기준",
                냉장상한=f"{temp_match.group(1)}섭씨", 냉동상한=f"{temp_match.group(2)}섭씨",
            )

        if "HACCP" in block:
            for item in vocab["handling_items"]:
                if item in block:
                    item_node = add_node(g, "HandlingItem", item)
                    cert_node = add_node(g, "Certification", "HACCP")
                    add_edge(g, item_node, "REQUIRES", cert_node, filename)


# ---------------------------------------------------------------------------
# 3) 정규화: 표기 통일 · 별칭 병합 · 고립 노드(일반명사성 잔여) 제외
# ---------------------------------------------------------------------------
def normalize(g):
    # HACCP(품목) 세부 인증 -> 상위 HACCP 개념 (별칭 병합)
    generic_haccp = node_id("Certification", "HACCP")
    if generic_haccp in g:
        for n, data in list(g.nodes(data=True)):
            if data.get("type") == "Certification" and n != generic_haccp and data["name"].startswith("HACCP("):
                add_edge(g, n, "IS_A", generic_haccp, "normalization")

    # 다른 어떤 문서와도 연결되지 못한 고립 노드는 잡음으로 보고 제거
    isolated = [n for n in g.nodes if g.degree(n) == 0]
    g.remove_nodes_from(isolated)
    return g


def main():
    config = load_config()
    vocab = config["vocab"]

    g = nx.DiGraph()

    cases = load_cases()
    for case in cases:
        extract_case_doc(g, case)
    print(f"사례문서 {len(cases)}건 추출 완료")

    refs = load_reference_docs()
    for filename, text in refs:
        extract_reference_doc(g, filename, text, vocab)
    print(f"규정문서 {len(refs)}건 추출 완료")

    print(f"정규화 전: 노드 {g.number_of_nodes()}개, 엣지 {g.number_of_edges()}개")
    normalize(g)
    print(f"정규화 후: 노드 {g.number_of_nodes()}개, 엣지 {g.number_of_edges()}개")

    type_counts = {}
    for _, data in g.nodes(data=True):
        type_counts[data["type"]] = type_counts.get(data["type"], 0) + 1
    print("노드 타입별 개수:", type_counts)

    os.makedirs(OUT_DIR, exist_ok=True)
    nx.write_graphml(g, GRAPH_PATH)
    print(f"저장 완료: {GRAPH_PATH}")


if __name__ == "__main__":
    main()
