"""탐색된 부분그래프를 pyvis로 시각화한다 (app.py 전용, agent.py 는 Streamlit/pyvis를 모른다)."""

from pyvis.network import Network

NODE_COLORS = {
    "SupplyCompany": "#4C8BF5",
    "RegionalOffice": "#34A853",
    "HandlingItem": "#F4B400",
    "Certification": "#9B59B6",
    "DocumentType": "#95A5A6",
    "ViolationType": "#E74C3C",
    "Sanction": "#C0392B",
    "Regulation": "#8D6E63",
    "Standard": "#1ABC9C",
}


def filter_nodes_by_answer(g, visited_nodes, start_nodes, answer_text):
    """탐색 중 방문한 노드는 많지만(제출서류 13종 등 답변과 무관한 것도 다 포함),
    실제로 답변 문장에 등장한 개체만 추리면 훨씬 읽기 쉬운 그래프가 된다.
    시작 개체는 항상 남기고, 그 외에는 이름이 답변 텍스트 안에 문자 그대로
    등장하는 노드만 남긴다."""
    keep = set(start_nodes)
    for node_id in visited_nodes:
        name = g.nodes[node_id].get("name", "")
        if name and name in answer_text:
            keep.add(node_id)

    # 답변이 개체명을 거의 안 썼다면(예: 요약형 문장) 시작 개체의 1홉 이웃까지는 보여준다 —
    # 텅 빈 그래프보다는 최소한의 맥락이 낫다.
    if len(keep) <= len(start_nodes):
        for s in start_nodes:
            if s in g:
                keep.update(g.successors(s))
                keep.update(g.predecessors(s))
    return keep


def render_subgraph_html(g, visited_nodes, start_nodes, answer_text=None, height="480px"):
    """visited_nodes 로 유도된 부분그래프를 인터랙티브 HTML(문자열)로 렌더링한다.
    answer_text 를 주면 답변에 실제로 언급된 개체만 추려서(filter_nodes_by_answer) 그린다."""
    if answer_text:
        nodes_to_draw = filter_nodes_by_answer(g, visited_nodes, start_nodes, answer_text)
    else:
        nodes_to_draw = visited_nodes
    sub = g.subgraph(nodes_to_draw)

    net = Network(
        height=height, width="100%", bgcolor="#111318", font_color="#EAEAEA",
        directed=True, cdn_resources="in_line",
    )
    net.barnes_hut(gravity=-4000, spring_length=120, spring_strength=0.02, damping=0.5)

    start_set = set(start_nodes)
    for node_id, data in sub.nodes(data=True):
        ntype = data.get("type", "")
        name = data.get("name", node_id)
        is_start = node_id in start_set
        net.add_node(
            node_id,
            label=name,
            title=f"{ntype}: {name}",
            color=NODE_COLORS.get(ntype, "#CCCCCC"),
            size=30 if is_start else 16,
            borderWidth=4 if is_start else 1,
            borderWidthSelected=6,
            font={"size": 22 if is_start else 14, "color": "#EAEAEA"},
        )

    for u, v, data in sub.edges(data=True):
        rel = data.get("relation", "")
        net.add_edge(u, v, label=rel, color="#6C7A89", font={"size": 10, "color": "#9AA5B1"}, arrows="to")

    net.set_options("""
    {
      "physics": {"stabilization": {"iterations": 120}},
      "interaction": {"hover": true, "tooltipDelay": 100}
    }
    """)

    return net.generate_html(notebook=False)
