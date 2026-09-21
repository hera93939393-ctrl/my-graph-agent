"""
data/docs 의 실제 생성 결과를 파싱해 골든셋(평가셋)을 만든다.
정답은 텍스트를 손으로 지어내지 않고, 실제 코퍼스에서 계산해서 채운다.
"""

import json
import os
from collections import defaultdict

from corpus_utils import BASE_DIR, ga, josa, load_cases

OUT_PATH = os.path.join(BASE_DIR, "data", "goldenset.json")


def build_index(cases, key_fn):
    idx = defaultdict(list)
    for c in cases:
        for key in key_fn(c):
            idx[key].append(c["company"])
    return idx


def pick_group(idx, min_size=3, max_size=6):
    """다른 업체 답이 너무 적거나(자명) 너무 많지(전수조사) 않은 그룹을 고른다."""
    for key, members in idx.items():
        if min_size <= len(members) <= max_size:
            return key, members
    return None, []


def main():
    cases = load_cases()
    by_company = {c["company"]: c for c in cases}
    region_idx = build_index(cases, lambda c: [c["region"]])
    item_idx = build_index(cases, lambda c: c["items"])
    violation_idx = build_index(cases, lambda c: c["violations"])
    cert_idx = build_index(cases, lambda c: c["certs"])

    goldenset = []

    # --- 1홉: 문서 내부 사실 확인 ---
    with_violation = [c for c in cases if c["violations"]]
    without_violation = [c for c in cases if not c["violations"]]

    c1 = with_violation[0]
    goldenset.append({
        "id": "Q1",
        "hop": 1,
        "question": f"{c1['company']}의 최종 심사 결과는 무엇인가?",
        "expected_answer": c1["final_result"],
        "expected_path": [f"{c1['company']} -[HAS_RESULT]-> {c1['final_result']}"],
        "evidence": [c1["file"]],
    })

    c2 = with_violation[1]
    goldenset.append({
        "id": "Q2",
        "hop": 1,
        "question": f"{c2['company']}{ga(c2['company'])} 보유한 인증은 무엇인가?",
        "expected_answer": ", ".join(c2["certs"]) if c2["certs"] else "보유 인증 없음",
        "expected_path": [f"{c2['company']} -[HOLDS]-> Certification"],
        "evidence": [c2["file"]],
    })

    c3 = without_violation[0]
    goldenset.append({
        "id": "Q3",
        "hop": 1,
        "question": f"{c3['company']}{ga(c3['company'])} 받은 제재조치는 무엇인가?",
        "expected_answer": "해당없음 (위반사항이 없어 제재조치 없음)",
        "expected_path": [f"{c3['company']} -[VIOLATED]-> (없음)"],
        "evidence": [c3["file"]],
        "note": "위반사항이 없는데도 제재를 지어내는지 확인하는 문항",
    })

    # --- 2홉: 같은 유형 개체 공유 (지역본부) ---
    region_key, region_members = pick_group(region_idx)
    anchor = region_members[0]
    others = region_members[1:]
    goldenset.append({
        "id": "Q4",
        "hop": 2,
        "question": f"{anchor}{josa(anchor, '와', '과')} 같은 지역본부({region_key})에 등록된 다른 업체는 어디인가?",
        "expected_answer": ", ".join(others),
        "expected_path": [
            f"{anchor} -[LOCATED_IN]-> {region_key}",
            f"{region_key} <-[LOCATED_IN]- {{{', '.join(others)}}}",
        ],
        "evidence": [by_company[anchor]["file"]] + [by_company[o]["file"] for o in others],
        "note": "RegionalOffice는 허브 노드라 상한(5건)을 둔다",
    })

    # --- 2홉: 같은 취급품목 공유 ---
    item_key, item_members = pick_group(item_idx)
    anchor2 = item_members[0]
    others2 = item_members[1:]
    goldenset.append({
        "id": "Q5",
        "hop": 2,
        "question": f"{anchor2}{josa(anchor2, '와', '과')} 같은 품목({item_key})을 취급하는 다른 업체 중 위반사항이 있는 곳은?",
        "expected_answer": ", ".join(o for o in others2 if by_company[o]["violations"]) or "없음",
        "expected_path": [
            f"{anchor2} -[HANDLES]-> {item_key}",
            f"{item_key} <-[HANDLES]- OtherCompany",
            "OtherCompany -[VIOLATED]-> ViolationType",
        ],
        "evidence": [by_company[anchor2]["file"]] + [by_company[o]["file"] for o in others2],
    })

    # --- 2홉: 같은 위반유형 공유 ---
    viol_key, viol_members = pick_group(violation_idx, min_size=2, max_size=6)
    if viol_members:
        anchor3 = viol_members[0]
        others3 = viol_members[1:]
        sanctions_of_others = {o: by_company[o]["sanctions"] for o in others3}
        goldenset.append({
            "id": "Q6",
            "hop": 2,
            "question": f"{anchor3}{josa(anchor3, '와', '과')} 같은 위반사항({viol_key})을 받은 다른 업체는 어떤 제재를 받았는가?",
            "expected_answer": "; ".join(f"{o}: {', '.join(s)}" for o, s in sanctions_of_others.items()),
            "expected_path": [
                f"{anchor3} -[VIOLATED]-> {viol_key}",
                f"{viol_key} <-[VIOLATED]- OtherCompany",
                "OtherCompany -[RESULTS_IN]-> Sanction",
            ],
            "evidence": [by_company[anchor3]["file"]] + [by_company[o]["file"] for o in others3],
        })

    # --- 2홉: 같은 인증 보유 공유 ---
    cert_key, cert_members = pick_group(cert_idx, min_size=2, max_size=6)
    if cert_members:
        anchor4 = cert_members[0]
        others4 = cert_members[1:]
        goldenset.append({
            "id": "Q7",
            "hop": 2,
            "question": f"{anchor4}{josa(anchor4, '와', '과')} 같은 인증({cert_key})을 보유한 다른 업체는 어디인가?",
            "expected_answer": ", ".join(others4),
            "expected_path": [
                f"{anchor4} -[HOLDS]-> {cert_key}",
                f"{cert_key} <-[HOLDS]- {{{', '.join(others4)}}}",
            ],
            "evidence": [by_company[anchor4]["file"]] + [by_company[o]["file"] for o in others4],
        })

    # --- 2홉 (문서 간 교차): 사례문서 + 규정문서 ---
    cold_chain_company = next(c for c in cases if "수산물" in c["items"])
    goldenset.append({
        "id": "Q8",
        "hop": 2,
        "question": f"{cold_chain_company['company']}{ga(cold_chain_company['company'])} 취급하는 수산물을 보관하려면 냉장·냉동 기준을 각각 몇 도 이하로 유지해야 하는가?",
        "expected_answer": "냉장 10℃ 이하, 냉동 -18℃ 이하 (수산물은 냉장·냉동 모두 필요)",
        "expected_path": [
            f"{cold_chain_company['company']} -[HANDLES]-> 수산물",
            "수산물 -[REQUIRES_TEMP]-> 현장심사_퀵가이드.md의 온도기준표",
        ],
        "evidence": [cold_chain_company["file"], "현장심사_퀵가이드.md"],
    })

    health_violation_company = next(
        (c for c in cases if "건강진단서_미구비" in c["violations"]), None
    )
    if health_violation_company:
        goldenset.append({
            "id": "Q9",
            "hop": 2,
            "question": f"{health_violation_company['company']}{ga(health_violation_company['company'])} '건강진단서_미구비' 위반을 받았다. 관련 규정상 건강진단은 얼마나 자주 받아야 하는가?",
            "expected_answer": "6개월에 1회 (폐결핵 검사는 연 1회), 근거: 학교급식법 시행규칙 제6조 제1항 별표4",
            "expected_path": [
                f"{health_violation_company['company']} -[VIOLATED]-> 건강진단서_미구비",
                "건강진단서_미구비 -[GOVERNED_BY]-> 공급업체_서류심사_세부기준.md",
            ],
            "evidence": [health_violation_company["file"], "공급업체_서류심사_세부기준.md"],
        })

    haccp_company = next(c for c in cases if any("HACCP" in x for x in c["certs"]))
    goldenset.append({
        "id": "Q10",
        "hop": 2,
        "question": f"{haccp_company['company']}{ga(haccp_company['company'])} HACCP 취급업체라면 인증서 외에 추가로 등록해야 하는 서류는 무엇인가?",
        "expected_answer": "대리점 계약서 (중간 유통업체가 있으면 유통업체-인증업체 간 계약서도 추가 등록)",
        "expected_path": [
            f"{haccp_company['company']} -[HOLDS]-> HACCP",
            "HACCP -[GOVERNED_BY]-> 공급업체_서류심사_세부기준.md",
        ],
        "evidence": [haccp_company["file"], "공급업체_서류심사_세부기준.md"],
    })

    # --- 근거 없음 -> 모른다 테스트 ---
    goldenset.append({
        "id": "Q11",
        "hop": 0,
        "question": f"{cases[0]['company']} 대표자의 실명과 주민등록번호는 무엇인가?",
        "expected_answer": "모른다 (코퍼스에 개인정보를 포함하지 않으므로 근거 없음)",
        "expected_path": [],
        "evidence": [],
        "note": "코퍼스에 없는 개인정보를 캐묻는 질문 — 모른다고 답해야 하는 네거티브 테스트",
    })

    # --- 절차 교차 (사례문서 + 서류심사 퀵가이드) ---
    rejected_company = next((c for c in cases if c["doc_result"] == "반려"), None)
    if rejected_company:
        goldenset.append({
            "id": "Q12",
            "hop": 2,
            "question": f"{rejected_company['company']}{ga(rejected_company['company'])} 서류심사에서 반려되었다면, 서류를 다시 제출한 뒤 재심사는 최대 며칠이 걸리는가?",
            "expected_answer": "영업일 기준 최대 3일 (서류 변경·갱신에 따른 재심사 기준)",
            "expected_path": [
                f"{rejected_company['company']} -[HAS_RESULT]-> 반려",
                "반려 -[GOVERNED_BY]-> 공급업체_서류심사_세부기준.md",
            ],
            "evidence": [rejected_company["file"], "공급업체_서류심사_세부기준.md"],
        })

    print(f"골든셋 문항 수: {len(goldenset)}")
    hop_counts = defaultdict(int)
    for item in goldenset:
        hop_counts[item["hop"]] += 1
    print("홉 수별 문항 수:", dict(hop_counts))

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(goldenset, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {OUT_PATH}")


if __name__ == "__main__":
    main()
