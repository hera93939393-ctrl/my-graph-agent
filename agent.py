"""
질문 -> 시작 개체 찾기 -> n홉 확장 -> 근거만으로 답변 + 경로 제시.

홉 정책 (config.json 과 동일):
  - 최대 2홉까지만 확장한다. 1홉에서 근거가 하나도 안 걸리면 2홉으로 넓히고,
    2홉에서도 없으면 "모른다"고 답한다.
  - RegionalOffice · Regulation 노드는 연결 차수가 지나치게 높은 허브라서,
    그대로 두면 사실상 전수조사가 되어버린다. 이 노드를 거쳐 이웃을 모을 때는
    최대 5건만 취하고, 잘렸다는 사실을 결과에 남긴다.

LLM은 OpenAI API를 쓴다 — 근거 문서가 전부 합성 데이터 + 공개 안내자료라
외부 API 사용에 개인정보 문제가 없다. API 키가 없으면 규칙 기반 요약으로
자동 대체되어, 키 없이도 파이프라인 검증은 가능하다.
"""

import json
import os
import sys

import networkx as nx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
GRAPH_PATH = os.path.join(BASE_DIR, "output", "graph.graphml")

MODEL = "gpt-4o"

ANSWER_SYSTEM_PROMPT = """당신은 eaT 공공급식통합플랫폼 공급업체 등록심사 지식그래프 에이전트입니다.
아래로 주어지는 '근거 삼중항'과 '노드 속성'만 사용해서 질문에 답하세요.
- 근거에 없는 내용은 절대 지어내지 말고 "모른다"고 답하세요.
- 질문이 여러 업체(또는 여러 개체)에 대해 묻고 있다면, 절대 하나의 값으로 뭉뚱그리지 말고
  업체별로 각각 어떤 삼중항이 있는지 짚어가며 개별적으로 답하세요. 예를 들어 A·B·C 업체가
  같은 위반유형을 공유하더라도 제재(Sanction)는 업체마다 다를 수 있습니다 — "모두 같은
  제재를 받았다"고 일반화하기 전에, 각 업체 이름 옆에 붙은 RESULTS_IN/그 외 관계를 하나씩
  따로 확인하세요. 한 업체의 사실을 다른 업체에게도 해당된다고 추정하지 마세요.
- 답변을 쓰기 전에 근거 삼중항 목록을 다시 훑어, 답변에 쓸 모든 문장이 실제로 존재하는
  삼중항 하나 이상과 정확히 대응하는지 스스로 확인하세요. 대응하는 삼중항이 없는 문장은 쓰지 마세요.
- 답변 마지막 줄에 반드시 "근거:" 로 시작하는 줄을 추가해 사용한 출처 문서 파일명을 나열하세요.
- 간결하고 사실 위주로 답하세요."""


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_graph():
    return nx.read_graphml(GRAPH_PATH)


def resolve_entities(g, question):
    """질문 문자열에 등장하는 그래프 노드 이름을 찾는다.
    긴 이름부터 매칭해 부분 매칭 오검출(예: '가온' 이 '가온식품' 안에 잡히는 것)을 줄인다."""
    candidates = [(nid, data["name"]) for nid, data in g.nodes(data=True)]
    candidates.sort(key=lambda x: len(x[1]), reverse=True)
    matched = []
    consumed = ""
    for nid, name in candidates:
        if name and name in question and name not in consumed:
            matched.append(nid)
            consumed += name
    return matched


def neighbors_both_directions(g, node):
    """방향 그래프지만 다홉 탐색에서는 양방향 연결성을 본다 (방향 정보는 트리플에 남긴다)."""
    seen = set()
    for succ in g.successors(node):
        seen.add(succ)
    for pred in g.predecessors(node):
        seen.add(pred)
    return seen


def edge_triples(g, a, b):
    """a-b 사이에 실제로 존재하는 엣지(들)를 (subject, relation, object, source_docs) 로 만든다."""
    triples = []
    if g.has_edge(a, b):
        data = g.edges[a, b]
        for rel in data.get("relation", "").split("|"):
            triples.append((g.nodes[a]["name"], rel, g.nodes[b]["name"], data.get("source_docs", "")))
    if g.has_edge(b, a):
        data = g.edges[b, a]
        for rel in data.get("relation", "").split("|"):
            triples.append((g.nodes[b]["name"], rel, g.nodes[a]["name"], data.get("source_docs", "")))
    return triples


# 질문 표현 -> 그 표현이 가리키는 관계. 2번째 홉을 어느 방향으로 넓힐지 고르는 데 쓴다.
RELATION_KEYWORDS = [
    (("지역본부", "지역"), "LOCATED_IN"),
    (("품목", "취급"), "HANDLES"),
    (("인증",), "HOLDS"),
    (("위반",), "VIOLATED"),
    (("제재",), "RESULTS_IN"),
    (("서류", "제출"), "SUBMITTED"),
    (("규정", "근거", "법령"), "GOVERNED_BY"),
    (("온도", "냉장", "냉동"), "REQUIRES_TEMP"),
]


def detect_relation_filter(question):
    for keywords, relation in RELATION_KEYWORDS:
        if any(k in question for k in keywords):
            return relation
    return None


def bfs_expand(g, start_nodes, hop_limit, hub_cap, relation_filter=None):
    """start_nodes 에서 hop_limit 까지 넓히며 지나간 트리플(홉 번호 포함)과 방문 노드를 모은다.

    1홉째는 앵커의 모든 직접 사실(제출서류·품목·인증·위반사항 등)을 그대로 다 모은다.
    2홉째부터는 relation_filter 가 있으면 그 관계로 도달한 노드만 계속 넓힌다 — 그렇게 하지
    않으면 '같은 지역본부의 다른 업체는?' 같은 질문에서 지역본부뿐 아니라 취급품목·서류종류
    등 무관한 허브까지 다 갈라져 나가 답이 노이즈에 묻히는 문제가 있었다. relation_filter 가
    없는(질문에서 관계를 못 읽은) 경우에는 기존처럼 모든 방향으로 넓힌다."""
    visited = set(start_nodes)
    frontier = set(start_nodes)
    triples_by_hop = {}
    truncated_hubs = []

    for hop in range(1, hop_limit + 1):
        next_frontier = set()
        continue_frontier = set()
        hop_triples = []
        for node in frontier:
            neighbors = neighbors_both_directions(g, node)
            node_type = g.nodes[node].get("type")
            # SupplyCompany 자신의 직접 사실은 그대로 다 보여준다. 그 외 노드(지역본부·서류종류·
            # 인증·품목·위반유형 등 "어휘형" 노드)는 최대 50개 업체까지 붙을 수 있는 허브이므로,
            # "다른 업체"로 되짚어 나갈 때만 상한을 둔다. 상한은 업체(SupplyCompany) 이웃에만
            # 적용한다 — 온도기준·상위 인증 같은 단일 노드까지 알파벳 정렬에 밀려 잘리면 안 된다.
            if node_type != "SupplyCompany":
                company_nbs = {n for n in neighbors if g.nodes[n].get("type") == "SupplyCompany"}
                other_nbs = neighbors - company_nbs
                if len(company_nbs) > hub_cap:
                    company_nbs = set(sorted(company_nbs, key=lambda n: g.nodes[n]["name"])[:hub_cap])
                    truncated_hubs.append(g.nodes[node]["name"])
                neighbors = company_nbs | other_nbs
            for nb in neighbors:
                edge_ts = edge_triples(g, node, nb)
                hop_triples.extend(edge_ts)
                if nb in visited:
                    continue
                next_frontier.add(nb)
                if hop == 1 and relation_filter:
                    if any(rel == relation_filter for _, rel, _, _ in edge_ts):
                        continue_frontier.add(nb)
                else:
                    continue_frontier.add(nb)
        triples_by_hop[hop] = sorted(set(hop_triples))
        visited |= next_frontier
        frontier = continue_frontier
        if not frontier:
            break

    all_triples = sorted({t for hop_list in triples_by_hop.values() for t in hop_list})
    max_hop_with_data = max((h for h, ts in triples_by_hop.items() if ts), default=0)
    return visited, all_triples, truncated_hubs, max_hop_with_data


def collect_node_attrs(g, visited):
    """VIOLATED/HOLDS 같은 엣지로는 못 담는 노드 속성(심사결과, 온도기준 등)을 모은다."""
    attrs = {}
    skip_keys = {"type", "name"}
    for node in visited:
        data = g.nodes[node]
        extra = {k: v for k, v in data.items() if k not in skip_keys}
        if extra:
            attrs[data["name"]] = extra
    return attrs


def format_evidence_context(triples, node_attrs):
    lines = ["[근거 삼중항]"]
    for subj, rel, obj, docs in triples:
        lines.append(f"- {subj} -[{rel}]-> {obj} (출처: {docs})")
    if node_attrs:
        lines.append("[노드 속성]")
        for name, extra in node_attrs.items():
            lines.append(f"- {name}: {extra}")
    return "\n".join(lines)


def fallback_answer(question, triples, node_attrs, source_docs):
    """API 키가 없을 때 쓰는 규칙 기반 요약(근거를 그대로 나열)."""
    if not triples and not node_attrs:
        return "모른다 (수집된 근거가 없습니다)."
    lines = ["[규칙 기반 요약 — LLM 미사용]"]
    for subj, rel, obj, _ in triples[:15]:
        lines.append(f"- {subj} {rel} {obj}")
    for name, extra in node_attrs.items():
        lines.append(f"- {name}: {extra}")
    lines.append(f"근거: {', '.join(sorted(source_docs))}")
    return "\n".join(lines)


VERIFY_SYSTEM_PROMPT = """당신은 답변 검증기입니다. 아래 근거(삼중항·노드속성)만 보고 draft_answer의 각 문장이
근거로 뒷받침되는지 하나씩 대조하세요.
- 여러 개체(업체 등)에 대한 답변이면, 각 개체의 사실이 실제로 그 개체의 삼중항과 정확히 일치하는지
  확인하세요 — 한 개체의 사실을 다른 개체에게도 해당된다고 일반화한 부분이 있으면 반드시 잡아내세요.
- 근거로 뒷받침되지 않는 주장은 제거하거나 "모른다"로 바꿔 다시 쓰세요.
- JSON으로만 답하세요: {"grounded": true|false, "issues": ["짧은 문제 설명", ...], "revised_answer": "근거만으로 다시 쓴 최종 답변 (마지막 줄에 근거: 줄 유지)"}
- draft_answer가 처음부터 전부 근거로 뒷받침됐다면 grounded=true, issues=[], revised_answer는 draft_answer와 동일하게 반환하세요."""


def call_llm(question, context):
    try:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": f"질문: {question}\n\n{context}"},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"  (LLM 호출 실패, 규칙 기반 요약으로 대체: {e})")
        return None


def call_verify(question, context, draft_answer):
    """생성 후처리 검증. draft_answer의 각 문장이 근거 삼중항과 실제로 대응하는지
    별도 LLM 호출로 다시 대조한다 — 근거는 100% 맞게 모았는데 답변 문장이 여러 업체의
    서로 다른 사실을 하나로 뭉뚱그리는 식의 생성 단계 환각을 잡기 위한 단계다
    (REPORT.md 3절 참고: 근거 재현율 1.0인데도 이런 환각이 실제로 발생한 적이 있다).
    검증 호출 자체가 실패하면 원래 답변을 그대로 쓴다 — 후처리가 안 된다고 답변 자체를
    막을 이유는 없다."""
    try:
        import json as _json

        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        if not os.environ.get("OPENAI_API_KEY"):
            return draft_answer, None
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"질문: {question}\n\n{context}\n\ndraft_answer:\n{draft_answer}",
                },
            ],
        )
        result = _json.loads(response.choices[0].message.content)
        revised = result.get("revised_answer") or draft_answer
        issues = result.get("issues") or []
        return revised, issues
    except Exception as e:
        print(f"  (검증 호출 실패, 원래 답변 유지: {e})")
        return draft_answer, None


def answer(question, g=None, config=None):
    g = g or load_graph()
    config = config or load_config()
    hop_limit = config["hop_limit"]
    hub_cap = 5

    start_nodes = resolve_entities(g, question)
    if not start_nodes:
        return {
            "question": question,
            "answer": "모른다 (질문에서 코퍼스 내 개체를 찾지 못했습니다).",
            "hop_used": 0,
            "path": [],
            "evidence": [],
            "start_nodes": [],
            "visited_nodes": [],
        }

    relation_filter = detect_relation_filter(question)
    visited, triples, truncated, hop_used = bfs_expand(
        g, start_nodes, hop_limit, hub_cap, relation_filter=relation_filter
    )

    node_attrs = collect_node_attrs(g, visited)
    source_docs = set()
    for _, _, _, docs in triples:
        source_docs |= set(filter(None, docs.split("|")))

    if not triples and not node_attrs:
        return {
            "question": question,
            "answer": f"모른다 ({hop_limit}홉까지 확장했지만 관련 근거를 찾지 못했습니다).",
            "hop_used": hop_limit,
            "path": [],
            "evidence": [],
            "start_nodes": start_nodes,
            "visited_nodes": list(visited),
        }

    context = format_evidence_context(triples, node_attrs)
    llm_answer = call_llm(question, context)

    verify_issues = None
    if llm_answer:
        final_answer, verify_issues = call_verify(question, context, llm_answer)
    else:
        final_answer = fallback_answer(question, triples, node_attrs, source_docs)

    return {
        "question": question,
        "answer": final_answer,
        "hop_used": hop_used,
        "path": [f"{s} -[{r}]-> {o}" for s, r, o, _ in triples],
        "evidence": sorted(source_docs),
        "verify_issues": verify_issues,
        "truncated_hubs": truncated,
        "start_nodes": start_nodes,
        "visited_nodes": list(visited),
    }


def main():
    import sys

    g = load_graph()
    config = load_config()

    if len(sys.argv) > 1:
        questions = [" ".join(sys.argv[1:])]
    else:
        questions = [
            "가득축산의 최종 심사 결과는 무엇인가?",
            "가득축산과 같은 지역본부에 등록된 다른 업체는 어디인가?",
        ]

    for q in questions:
        result = answer(q, g=g, config=config)
        print("=" * 60)
        print("질문:", result["question"])
        print("답변:", result["answer"])
        print("사용 홉 수:", result["hop_used"])
        print("경로:")
        for p in result["path"][:10]:
            print("  ", p)
        print("근거 문서:", result["evidence"])


if __name__ == "__main__":
    main()
