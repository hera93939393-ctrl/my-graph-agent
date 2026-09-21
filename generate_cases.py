"""
합성 심사결과서 코퍼스 생성 스크립트.

실제 eaT 서류심사·현장심사 기준(config.json 의 vocab)을 바탕으로
가상의 공급업체 등록심사 결과서 N건을 만들어 ./data/docs 에 저장한다.
실제 업체명·개인정보는 전혀 사용하지 않는다 (합성 데이터).
"""

import json
import os
import random

random.seed(42)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUT_DIR = os.path.join(BASE_DIR, "data", "docs")
NUM_CASES = 50

NAME_PREFIXES = [
    "한마루", "청록", "다솜", "온누리", "푸른들", "황금", "해오름", "은비", "정성", "우리",
    "새힘", "고운", "드림", "바른", "건강한", "풍년", "가온", "다온", "단비", "솔빛",
    "초록", "맑은", "든든", "참", "해맑은", "알찬", "여울", "보람", "하나로", "으뜸",
    "늘봄", "새아침", "미소", "정원", "튼튼", "풀잎", "구름", "샛별", "옹달샘", "청솔",
    "밝은", "다정", "행복", "든윤", "소담", "가득", "정갈", "빛나는", "터전", "새순",
]
NAME_SUFFIXES = ["식품", "푸드", "농산", "수산", "축산", "유통", "물류", "팜", "F&B", "키친"]


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def make_company_name(used_names):
    while True:
        name = random.choice(NAME_PREFIXES) + random.choice(NAME_SUFFIXES)
        if name not in used_names:
            used_names.add(name)
            return name


def choose_items(vocab_list, k_range):
    k = random.randint(*k_range)
    k = min(k, len(vocab_list))
    return random.sample(vocab_list, k)


def build_case(vocab, used_names):
    company = make_company_name(used_names)
    biz_type = random.choice(["법인사업자", "개인사업자"])
    region = random.choice(vocab["regional_offices"])
    items = choose_items(vocab["handling_items"], (1, 2))

    # 취급품목과 어느 정도 관련 있는 인증을 우선 배치
    related_certs = [c for c in vocab["certifications"] if any(item in c for item in items)]
    cert_pool = related_certs if related_certs and random.random() < 0.6 else vocab["certifications"]
    holds_none = random.random() < 0.15
    certifications = [] if holds_none else choose_items(cert_pool, (1, 2))

    submitted_docs = choose_items(vocab["document_types"], (9, len(vocab["document_types"])))

    has_violation = random.random() < 0.55
    violations = choose_items(vocab["violation_types"], (1, 2)) if has_violation else []
    sanctions = choose_items(vocab["sanctions"], (1, 1)) if has_violation else []

    doc_review_pass = not any(
        v in ("주민등록번호_미마스킹", "원본대조필_누락", "서류_유효기간_만료", "소재지_불일치", "열람용_등기부등본_제출")
        for v in violations
    )
    site_review_pass = not any(
        v in (
            "현장심사_수진자_자격미달", "옥외_탈부착간판", "타업체와_사업장_미분리", "창고_공동사용",
            "야외창고_사용", "냉장냉동_미분리", "냉장온도_기준초과", "냉동온도_기준초과",
            "방충방서시설_미비", "정기소독_미실시", "건강진단서_미구비",
        )
        for v in violations
    )

    year = random.choice([2024, 2025])
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    review_date = f"{year}-{month:02d}-{day:02d}"

    reg = random.choice(vocab["regulations"])

    return {
        "company": company,
        "biz_type": biz_type,
        "region": region,
        "items": items,
        "certifications": certifications,
        "submitted_docs": submitted_docs,
        "violations": violations,
        "sanctions": sanctions,
        "doc_review_pass": doc_review_pass,
        "site_review_pass": site_review_pass,
        "review_date": review_date,
        "related_regulation": reg,
    }


VIOLATION_NARRATIVE = {
    "주민등록번호_미마스킹": "제출 서류에 주민등록번호 뒷자리가 가려지지 않아 개인정보보호법에 따른 마스킹 기준을 충족하지 못했다.",
    "원본대조필_누락": "흑백으로 제출된 서류에 원본대조필과 업체 직인이 날인되지 않았다.",
    "서류_유효기간_만료": "제출된 서류의 유효기간이 심사일 기준으로 이미 만료되어 갱신이 필요하다.",
    "소재지_불일치": "사업자등록증 소재지와 등기부등본·창고확인서상 소재지가 일치하지 않았다.",
    "열람용_등기부등본_제출": "제출용이 아닌 열람용 등기부등본이 등록되어 승인 기준을 충족하지 못했다.",
    "현장심사_수진자_자격미달": "현장심사 수진자가 대표자도 아니고 플랫폼에 등록된 임직원도 아니어서 심사가 제한되었다.",
    "옥외_탈부착간판": "옥외 간판이 탈부착 가능한 형태여서 독립된 사업장 기준을 충족하지 못했다.",
    "타업체와_사업장_미분리": "타 업체를 거쳐서 출입하거나 시건장치를 공유하고 있어 분리된 사업장 기준에 부적합했다.",
    "창고_공동사용": "다른 업체와 창고를 공동으로 사용하고 있어 위생적 보관·관리 기준에 부적합했다.",
    "야외창고_사용": "가설건축물 허가와 천장가림막 없이 야외 창고를 사용하고 있어 부적합했다.",
    "냉장냉동_미분리": "냉장·냉동 보관 구역이 분리되어 있지 않아 취급품목별 보관기준에 부적합했다.",
    "냉장온도_기준초과": "냉장고 온도가 기준치인 10℃를 초과한 상태로 확인되었다.",
    "냉동온도_기준초과": "냉동고 온도가 기준치인 -18℃를 초과한 상태로 확인되었다.",
    "방충방서시설_미비": "쥐막이 및 방충시설이 구비되지 않아 해충 유입 우려가 확인되었다.",
    "정기소독_미실시": "동절기·하절기 정기소독 주기를 지키지 않은 것으로 확인되었다.",
    "건강진단서_미구비": "식품 취급 종사자의 건강진단결과서 원본이 구비되지 않았다.",
}


def josa(word, no_final, has_final):
    """마지막 글자의 받침 유무에 따라 조사(은/는, 이/가 등)를 고른다."""
    last = word[-1]
    if "가" <= last <= "힣":
        has_batchim = (ord(last) - ord("가")) % 28 != 0
        return has_final if has_batchim else no_final
    return no_final


def render_case(case):
    company = case["company"]
    items_str = ", ".join(case["items"])
    certs_str = ", ".join(case["certifications"]) if case["certifications"] else "보유 인증 없음"
    docs_str = ", ".join(case["submitted_docs"])
    violations = case["violations"]
    sanctions = case["sanctions"]

    doc_result = "승인" if case["doc_review_pass"] else "반려"
    site_result = "합격" if case["site_review_pass"] else "불합격"
    final_result = "등록완료" if (case["doc_review_pass"] and case["site_review_pass"]) else "보류"

    if violations:
        violation_lines = "\n".join(f"- {v}: {VIOLATION_NARRATIVE[v]}" for v in violations)
    else:
        violation_lines = "위반사항 없음"

    sanction_lines = ", ".join(sanctions) if sanctions else "해당없음"

    company_topic = josa(company, "는", "은")
    narrative = (
        f"{company}{company_topic} {case['region']} 관내 소재 {case['biz_type']}로, "
        f"주취급품목은 {items_str}이다. 이번 등록심사에서 {docs_str} 등 서류를 제출하였고, "
        f"보유 인증은 {certs_str}이다."
    )
    if violations:
        narrative += (
            f" 심사 결과 {len(violations)}건의 위반사항이 확인되었으며, "
            f"이는 관련 규정인 {case['related_regulation']} 기준과 연계하여 검토되었다."
        )
    else:
        narrative += " 심사 과정에서 특별한 위반사항은 발견되지 않았다."

    items_requirement_lines = []
    for item in case["items"]:
        matched = [c for c in case["certifications"] if item in c]
        if matched:
            items_requirement_lines.append(
                f"- {item} 취급을 위해 {', '.join(matched)} 인증을 보유하고 있다."
            )
        else:
            items_requirement_lines.append(
                f"- {item} 취급 관련 인증은 현재 등록되어 있지 않아 추가 확인이 필요하다."
            )
    requirement_note = "\n".join(items_requirement_lines)

    review_opinion = (
        f"이번 심사는 {case['review_date']}에 {case['region']} 담당자가 진행했다. "
        f"서류심사에서는 {docs_str} 등 제출 서류와 사업자등록증·등기부등본상의 정보 일치 여부를 "
        f"{case['related_regulation']} 및 관련 위생 기준에 따라 대조하여 {doc_result} 처리했다. "
        f"현장심사에서는 사업장의 독립성, 냉장·냉동 시설의 온도 유지, 위생 관리 상태를 중심으로 "
        f"점검한 결과 {site_result} 판정을 내렸다."
    )

    categories = ["공급업체", case["region"]] + case["items"]

    content = f"""# {company} 공급업체 등록심사 결과서

분류: {", ".join(categories)}

## 업체 개요
- 업체명: {company}
- 사업자유형: {case['biz_type']}
- 지역본부: {case['region']}
- 주취급품목: {items_str}
- 심사일자: {case['review_date']}

## 개요 서술
{narrative}

## 보유 인증
{certs_str}

## 취급품목별 인증 현황
{requirement_note}

## 제출 서류
{docs_str}

## 심사 의견
{review_opinion}

## 서류심사 결과
{doc_result}

## 현장심사 결과
{site_result}

## 위반사항
{violation_lines}

## 제재조치
{sanction_lines}

## 최종 결과
{final_result}
"""
    return content


def main():
    vocab = load_config()["vocab"]
    os.makedirs(OUT_DIR, exist_ok=True)

    used_names = set()
    saved = []
    for i in range(NUM_CASES):
        case = build_case(vocab, used_names)
        content = render_case(case)
        filename = case["company"].replace(" ", "_") + ".md"
        path = os.path.join(OUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        saved.append(case["company"])
        print(f"  저장: {case['company']} ({len(content)}자, 위반 {len(case['violations'])}건)")

    print(f"총 생성 건수: {len(saved)}")

    manifest_path = os.path.join(BASE_DIR, "data", "manifest.json")
    manifest = {
        "source": "synthetic (eaT 서류심사·현장심사 기준 기반 가상 업체 사례)",
        "reference_docs": [
            "공급업체_서류심사_세부기준.md",
            "현장심사_퀵가이드.md",
            "서류심사_퀵가이드.md",
        ],
        "synthetic_case_count": len(saved),
        "synthetic_case_titles": saved,
        "total_docs": len(saved) + 3,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"manifest.json 기록 완료 (총 문서 {manifest['total_docs']}건)")


if __name__ == "__main__":
    main()
