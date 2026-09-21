"""
골든셋으로 GraphRAG 에이전트를 평가한다.

- 홉 수별로 GraphRAG vs basic RAG(단순 키워드 검색, 그래프 미사용)를 대조한다.
- 기대 경로(expected_path)가 실제로 탄 경로에 얼마나 들어왔는지(경로 재현율) 측정한다.
- 근거를 못 찾은 문항은 색인(그래프에 사실 자체가 없음) · 탐색(그래프엔 있지만 에이전트가
  못 찾음) · 생성(근거는 찾았지만 답변 문장에 못 담음) 중 어디서 깨졌는지 가른다.

출력: ./output/eval.json (요약), ./output/runs.jsonl (문항별 상세 기록)
"""

import json
import os
import re

from agent import answer as graphrag_answer
from agent import load_config, load_graph
from corpus_utils import BASE_DIR, DOCS_DIR

GOLDENSET_PATH = os.path.join(BASE_DIR, "data", "goldenset.json")
OUT_DIR = os.path.join(BASE_DIR, "output")
EVAL_PATH = os.path.join(OUT_DIR, "eval.json")
RUNS_PATH = os.path.join(OUT_DIR, "runs.jsonl")

TOP_K = 3


def load_all_docs():
    docs = {}
    for name in sorted(os.listdir(DOCS_DIR)):
        if name.endswith(".md"):
            with open(os.path.join(DOCS_DIR, name), "r", encoding="utf-8") as f:
                docs[name] = f.read()
    return docs


def tokenize_entities(g, text):
    """그래프 노드 이름 중 text 안에 등장하는 것들을 뽑는다 (질문/문서 공통 어휘 사전)."""
    found = set()
    for _, data in g.nodes(data=True):
        name = data["name"]
        if name and name in text:
            found.add(name)
    return found


def basic_rag_answer(question, docs, question_entities):
    """단순 키워드 겹침 기반 검색 — 그래프도 없고 다홉 확장도 없다.
    질문과 문서에 공통으로 등장하는 개체명 개수로 문서 점수를 매겨 상위 TOP_K만 근거로 쓴다."""
    scores = []
    for name, text in docs.items():
        overlap = sum(1 for e in question_entities if e in text)
        if overlap > 0:
            scores.append((overlap, name))
    scores.sort(reverse=True)
    top_docs = [name for _, name in scores[:TOP_K]]
    combined_text = "\n".join(docs[d] for d in top_docs)
    return {"evidence": top_docs, "context_text": combined_text}


def path_recall(expected_path, actual_path):
    if not expected_path:
        return None  # 경로가 필요 없는 문항(예: 근거없음 테스트)은 recall 계산 제외
    actual_joined = " || ".join(actual_path)
    hit = 0
    for step in expected_path:
        # "회사 <-[REL]- {a, b}" 같은 집합 표기는 관계명만으로 느슨하게 매칭한다
        rel_match = re.search(r"\[(\w+)\]", step)
        rel = rel_match.group(1) if rel_match else None
        subj_match = re.match(r"(\S+)", step)
        subj = subj_match.group(1) if subj_match else ""
        if rel and (f"-[{rel}]->" in actual_joined) and (subj in actual_joined or subj == ""):
            hit += 1
    return hit / len(expected_path)


def evidence_recall(expected_evidence, actual_evidence):
    if not expected_evidence:
        return None
    hit = sum(1 for e in expected_evidence if e in actual_evidence)
    return hit / len(expected_evidence)


def fact_exists_anywhere_in_graph(g, expected_evidence):
    """기대 근거 문서가 그래프의 어느 엣지 출처로든 한 번이라도 등장하는지 확인한다.
    (전혀 없다면 탐색 문제가 아니라 추출/색인 단계에서 이미 빠진 것)"""
    for _, _, data in g.edges(data=True):
        docs = set(filter(None, data.get("source_docs", "").split("|")))
        if docs & set(expected_evidence):
            return True
    return False


def normalize_for_compare(s):
    """'이용제한_1개월'(코드) 과 '이용제한 1개월'(LLM 자연어)처럼 밑줄/공백 표기만
    다른 걸 같은 문자열로 보기 위한 정규화. 실제로 이 차이 때문에 정상 답변이
    '생성 실패'로 오분류되는 걸 겪고 나서 추가했다."""
    return s.replace("_", "").replace(" ", "")


def classify_failure(item, result, g):
    """평가recall이 1.0 미만인 문항의 실패 층을 가른다."""
    expected_evidence = set(item["evidence"])
    actual_evidence = set(result["evidence"])
    missing = expected_evidence - actual_evidence
    if not missing:
        # 근거는 다 모았는데 최종 답변 문장에 핵심 키워드가 안 보이면 생성 단계 문제
        key_terms = [t for t in re.split(r"[,;() ]+", item["expected_answer"]) if len(t) >= 2]
        answer_norm = normalize_for_compare(result["answer"])
        if key_terms and not any(normalize_for_compare(t) in answer_norm for t in key_terms):
            return "생성"
        return None  # 정상
    if not fact_exists_anywhere_in_graph(g, missing):
        return "색인"  # 그래프 자체에 그 문서발 사실이 없다 = 추출 단계에서 누락
    return "탐색"  # 그래프엔 있지만 에이전트가 이번 확장 범위 안에서 못 찾았다


def main():
    g = load_graph()
    config = load_config()
    goldenset = json.load(open(GOLDENSET_PATH, encoding="utf-8"))
    docs = load_all_docs()

    os.makedirs(OUT_DIR, exist_ok=True)
    runs = []
    per_hop = {}

    with open(RUNS_PATH, "w", encoding="utf-8") as runs_f:
        for item in goldenset:
            question = item["question"]
            hop = item["hop"]

            gr_result = graphrag_answer(question, g=g, config=config)
            question_entities = tokenize_entities(g, question)
            br_result = basic_rag_answer(question, docs, question_entities)

            gr_path_recall = path_recall(item["expected_path"], gr_result["path"])
            gr_evi_recall = evidence_recall(item["evidence"], gr_result["evidence"])
            br_evi_recall = evidence_recall(item["evidence"], br_result["evidence"])

            failure_layer = None
            if gr_evi_recall is not None and gr_evi_recall < 1.0:
                failure_layer = classify_failure(item, gr_result, g)
            elif gr_evi_recall == 1.0:
                failure_layer = classify_failure(item, gr_result, g)  # 생성 단계만 점검

            record = {
                "id": item["id"],
                "hop": hop,
                "question": question,
                "graphrag_hop_used": gr_result["hop_used"],
                "graphrag_path_recall": gr_path_recall,
                "graphrag_evidence_recall": gr_evi_recall,
                "basic_rag_evidence_recall": br_evi_recall,
                "failure_layer": failure_layer,
            }
            runs.append(record)
            runs_f.write(json.dumps(record, ensure_ascii=False) + "\n")

            per_hop.setdefault(hop, {"graphrag_evi": [], "basic_evi": [], "path": []})
            if gr_evi_recall is not None:
                per_hop[hop]["graphrag_evi"].append(gr_evi_recall)
                per_hop[hop]["basic_evi"].append(br_evi_recall)
            if gr_path_recall is not None:
                per_hop[hop]["path"].append(gr_path_recall)

            print(f"{item['id']} (hop={hop}): GraphRAG 근거재현율={gr_evi_recall} "
                  f"basicRAG 근거재현율={br_evi_recall} 경로재현율={gr_path_recall} "
                  f"실패층={failure_layer}")

    def avg(xs):
        return sum(xs) / len(xs) if xs else None

    summary = {
        "per_hop": {
            str(hop): {
                "n": len(v["graphrag_evi"]),
                "graphrag_evidence_recall_avg": avg(v["graphrag_evi"]),
                "basic_rag_evidence_recall_avg": avg(v["basic_evi"]),
                "graphrag_path_recall_avg": avg(v["path"]),
            }
            for hop, v in sorted(per_hop.items())
        },
        "failure_layer_counts": {
            layer: sum(1 for r in runs if r["failure_layer"] == layer)
            for layer in ["색인", "탐색", "생성"]
        },
        "total_questions": len(goldenset),
    }

    print("\n=== 홉 수별 GraphRAG vs basic RAG (근거 재현율 평균) ===")
    for hop, stats in summary["per_hop"].items():
        print(f"  hop={hop} (n={stats['n']}): GraphRAG={stats['graphrag_evidence_recall_avg']}, "
              f"basicRAG={stats['basic_rag_evidence_recall_avg']}, "
              f"경로재현율={stats['graphrag_path_recall_avg']}")
    print("실패 층 분류:", summary["failure_layer_counts"])

    with open(EVAL_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {EVAL_PATH}, {RUNS_PATH}")


if __name__ == "__main__":
    main()
