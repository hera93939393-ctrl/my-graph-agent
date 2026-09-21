# eaT 공급업체 등록심사 지식그래프 에이전트

eaT 공공급식통합플랫폼의 **공급업체 등록심사(서류심사·현장심사)** 를 도메인으로 한 GraphRAG 챗봇.
공개 심사기준 문서 3건 + 그 기준을 바탕으로 만든 가상 업체 심사결과서 50건에서 지식그래프를 뽑고,
질문 → 시작 개체 탐색 → n홉 확장 → 근거·경로 제시 순으로 답한다. 자세한 설계 배경은 [REPORT.md](REPORT.md) 참고.

## 준비

```bash
pip install -r requirements.txt
```

LLM 기반 답변 생성을 쓰려면(선택) 프로젝트 루트에 `.env` 를 만들고 키를 넣는다. 키가 없어도
파이프라인 전체(그래프 구축·평가·데모)는 규칙 기반 요약으로 그대로 동작한다.

```
OPENAI_API_KEY=sk-...
```

## 실행 순서

```bash
# 1. 합성 코퍼스 생성 (이미 data/docs 에 결과물이 있음 — 다시 만들고 싶을 때만)
python generate_cases.py

# 2. 골든셋(평가셋) 생성 — 코퍼스에서 정답을 계산해서 만든다
python build_goldenset.py

# 3. 그래프 추출 + 정규화 -> output/graph.graphml
python build_graph.py

# 4. 골든셋으로 평가 (GraphRAG vs basic RAG 대조, 홉별 재현율, 실패층 분류)
python evaluate.py

# 5. 데모 실행
streamlit run app.py
```

CLI로 단발 질문만 던져보고 싶으면:

```bash
python agent.py "가득축산과 같은 지역본부에 등록된 다른 업체는 어디인가?"
```

## 데모 화면

`streamlit run app.py` 로 실행한 뒤 브라우저(기본 http://localhost:8501)에서 질문을 입력하거나
예시 질문 드롭다운(골든셋 문항)을 고르면, 답변과 함께 사용한 홉 수·탄 경로(트리플)·근거 문서
목록을 확인할 수 있다.

> 이 세션에서 Streamlit 앱을 브라우저로 직접 띄워 질문→답변→경로/근거 표시까지 정상 동작을
> 확인했다. 제출용 캡처 이미지는 로컬에서 `streamlit run app.py` 실행 후 화면을 캡처해
> `assets/` 폴더에 추가할 것 (예: `assets/demo_screenshot.png`, 이 README에서 링크).

## 프로젝트 구조

```
my-graph-agent/
├── data/
│   ├── docs/            # 문서 53건 (심사기준 3 + 합성 심사결과서 50)
│   ├── manifest.json    # 코퍼스 생성 기록
│   └── goldenset.json   # 평가셋 12문항
├── config.json           # 노드·관계 스키마, 홉 상한, 허브 노드 정책
├── corpus_utils.py        # 사례문서 파싱 공통 유틸
├── generate_cases.py      # 합성 심사결과서 코퍼스 생성
├── build_goldenset.py     # 골든셋 생성 (코퍼스에서 정답 계산)
├── build_graph.py         # 그래프 추출 + 정규화 -> output/graph.graphml
├── agent.py               # 질문 -> 시작개체 -> n홉 확장 -> 근거 기반 답변
├── evaluate.py            # 골든셋 평가 (홉별 GraphRAG vs basic RAG, 실패층 분류)
├── app.py                 # Streamlit 데모
├── output/
│   ├── graph.graphml
│   ├── eval.json
│   └── runs.jsonl
└── REPORT.md
```

## 데이터에 관해

`data/docs` 의 문서는 두 종류다.

1. **실제 공개 자료** 3건 — eaT 공급업체 회원등록 심사 퀵 가이드(서류심사편/현장심사편), 공급업체
   서류심사 세부기준(개정). 심사 절차·기준을 안내하는 공개 문서라 개인정보·영업비밀이 없다.
2. **합성 데이터** 50건 — 위 기준을 바탕으로 만든 가상 업체의 심사결과서. 실제 심사 사례(기관
   내부자료, 실제 업체명·개인정보 포함)는 공개 GitHub 저장소에 올릴 수 없어서 대신 만들었다.
   업체명·수치는 전부 가상이다.
