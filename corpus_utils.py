"""data/docs 의 사례문서(합성 심사결과서)를 파싱하는 공통 유틸.
build_goldenset.py 와 build_graph.py 가 함께 사용한다."""

import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "data", "docs")

FIELD_PATTERNS = {
    "region": r"- 지역본부:\s*(.+)",
    "items": r"- 주취급품목:\s*(.+)",
    "doc_result": r"## 서류심사 결과\n(.+)",
    "site_result": r"## 현장심사 결과\n(.+)",
    "final_result": r"## 최종 결과\n(.+)",
    "certs": r"## 보유 인증\n(.+)",
    "sanctions": r"## 제재조치\n(.+)",
    "submitted_docs": r"## 제출 서류\n(.+)",
}


def parse_case(path):
    """사례문서 1건을 파싱한다. 규정문서(참고문서)면 None을 반환한다."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    title_match = re.search(r"^# (.+?) 공급업체 등록심사 결과서", text)
    if not title_match:
        return None
    company = title_match.group(1)

    def find(field):
        m = re.search(FIELD_PATTERNS[field], text)
        return m.group(1).strip() if m else ""

    region = find("region")
    items = [x.strip() for x in find("items").split(",") if x.strip()]
    certs_raw = find("certs")
    certs = [] if certs_raw == "보유 인증 없음" else [x.strip() for x in certs_raw.split(",")]
    submitted_docs = [x.strip() for x in find("submitted_docs").split(",") if x.strip()]
    doc_result = find("doc_result")
    site_result = find("site_result")
    final_result = find("final_result")
    sanctions_raw = find("sanctions")
    sanctions = [] if sanctions_raw == "해당없음" else [x.strip() for x in sanctions_raw.split(",")]

    violation_section = re.search(r"## 위반사항\n(.+?)\n\n## 제재조치", text, re.S)
    violations = []
    if violation_section and "위반사항 없음" not in violation_section.group(1):
        for line in violation_section.group(1).strip().splitlines():
            m = re.match(r"- (\S+?):", line.strip())
            if m:
                violations.append(m.group(1))

    return {
        "company": company,
        "file": os.path.basename(path),
        "region": region,
        "items": items,
        "certs": certs,
        "submitted_docs": submitted_docs,
        "doc_result": doc_result,
        "site_result": site_result,
        "final_result": final_result,
        "violations": violations,
        "sanctions": sanctions,
    }


def load_cases(docs_dir=DOCS_DIR):
    cases = []
    for name in sorted(os.listdir(docs_dir)):
        if not name.endswith(".md"):
            continue
        c = parse_case(os.path.join(docs_dir, name))
        if c:
            cases.append(c)
    return cases


def load_reference_docs(docs_dir=DOCS_DIR):
    """규정문서(사례문서가 아닌 것)의 (파일명, 본문) 목록을 반환한다."""
    refs = []
    for name in sorted(os.listdir(docs_dir)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(docs_dir, name)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        if not re.search(r"^# (.+?) 공급업체 등록심사 결과서", text):
            refs.append((name, text))
    return refs


def josa(word, no_final, has_final):
    """마지막 글자의 받침 유무에 따라 조사를 고른다."""
    last = word[-1]
    if "가" <= last <= "힣":
        has_batchim = (ord(last) - ord("가")) % 28 != 0
        return has_final if has_batchim else no_final
    return no_final


def ga(word):
    return josa(word, "가", "이")


def eun(word):
    return josa(word, "는", "은")
