"""app.py — eaT 공급업체 등록심사 지식그래프 에이전트 데모 화면 (Streamlit)."""
import json
import os

import streamlit as st

from agent import BASE_DIR, answer, load_config, load_graph

st.set_page_config(page_title="eaT 심사 그래프 에이전트", page_icon="🕸️", layout="centered")

st.markdown(
    """
    <style>
    .stApp { background: #FAFAF7; }
    .gr-hero {
        background: linear-gradient(135deg, #DFEAF6 0%, #EDE4FB 100%);
        border-radius: 20px; padding: 26px 26px 20px 26px; margin-bottom: 22px;
        border: 1px solid #00000010;
    }
    .gr-hero h1 { font-size: 1.6rem; font-weight: 800; margin: 0 0 8px 0; color: #1A1A1A; }
    .gr-hero p { margin: 0; color: #444; font-size: 0.92rem; }
    .gr-card {
        background: #FFFFFF; border-radius: 18px; padding: 20px 22px;
        margin-bottom: 16px; box-shadow: 0 2px 10px #00000010; border: 1px solid #00000008;
    }
    .gr-q { font-weight: 800; font-size: 1.0rem; margin-bottom: 6px; color: #1A1A1A; }
    .gr-a { font-size: 0.93rem; line-height: 1.6; color: #262626; margin-bottom: 12px; white-space: pre-wrap; }
    .gr-pill {
        display: inline-block; padding: 4px 11px; border-radius: 999px;
        font-size: 0.76rem; font-weight: 700; border: 1.5px solid;
        background: #EDF3FE; color: #2354C4; border-color: #AFC8F5; margin-right: 6px;
    }
    .gr-path-line { font-family: "Consolas", monospace; font-size: 0.82rem; color: #333; }
    div[data-testid="stSelectbox"] label {
        color: #999 !important; font-size: 0.8rem !important;
    }
    div[data-testid="stSelectbox"] div[role="group"] {
        background-color: #F4F4F2 !important;
        border-color: #E4E3DE !important;
    }
    div[data-testid="stSelectbox"] input {
        color: #999 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="gr-hero">
      <h1>🕸️ eaT 공급업체 등록심사 지식그래프 에이전트</h1>
      <p>서류심사·현장심사 기준 문서 + 가상 업체 심사결과서(합성 데이터) 기반 — 질문 → 시작 개체 → n홉 확장 → 근거·경로 함께 답변</p>
    </div>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_resources():
    return load_graph(), load_config()


g, config = get_resources()

try:
    with open(os.path.join(BASE_DIR, "data", "goldenset.json"), encoding="utf-8") as f:
        goldenset = json.load(f)
except FileNotFoundError:
    goldenset = []

example_questions = [item["question"] for item in goldenset]

if "history" not in st.session_state:
    st.session_state.history = []

question = st.text_input("질문을 입력하세요", placeholder="예: 가득축산과 같은 지역본부에 등록된 다른 업체는 어디인가?")
picked = st.selectbox("예시 질문 (참고용)", ["(직접 입력)"] + example_questions, label_visibility="visible")

if picked != "(직접 입력)":
    question = picked

if st.button("질문하기", type="primary") and question:
    with st.spinner("시작 개체를 찾고 그래프를 확장하는 중..."):
        result = answer(question, g=g, config=config)
    st.session_state.history.insert(0, result)

for result in st.session_state.history:
    st.markdown(
        f"""
        <div class="gr-card">
          <div class="gr-q">Q. {result['question']}</div>
          <div class="gr-a">{result['answer']}</div>
          <span class="gr-pill">사용 홉 수: {result['hop_used']}</span>
          <span class="gr-pill">근거 문서 {len(result['evidence'])}건</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander(f"탄 경로 보기 ({len(result['path'])}개 트리플)"):
        if result["path"]:
            for p in result["path"]:
                st.markdown(f'<div class="gr-path-line">{p}</div>', unsafe_allow_html=True)
        else:
            st.write("경로 없음 (개체를 못 찾았거나 근거가 없습니다)")
    with st.expander("근거 문서 목록 보기"):
        if result["evidence"]:
            for doc in result["evidence"]:
                st.write(f"- {doc}")
        else:
            st.write("근거 문서 없음")
    if result.get("truncated_hubs"):
        st.caption(f"⚠️ 허브 노드 상한(5건) 적용됨: {', '.join(set(result['truncated_hubs']))}")
