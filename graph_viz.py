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


def render_subgraph_html(g, visited_nodes, start_nodes, height="480px"):
    """visited_nodes 로 유도된 부분그래프를 인터랙티브 HTML(문자열)로 렌더링한다."""
    sub = g.subgraph(visited_nodes)

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
