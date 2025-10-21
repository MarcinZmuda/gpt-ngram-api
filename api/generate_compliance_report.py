import re
import spacy

try:
    NLP = spacy.load("pl_core_news_sm")
except OSError:
    from spacy.cli import download
    download("pl_core_news_sm")
    NLP = spacy.load("pl_core_news_sm")

def generate_compliance_report(text_to_process, keyword_list_string):
    """
    Generuje raport zgodności użycia słów kluczowych względem zadanych zakresów (min–max).
    """

    if not text_to_process or not keyword_list_string:
        return {"error": "Payload must include 'text' and 'keyword_list_string'."}

    # === INTELIGENTNE PARSOWANIE LISTY UŻYTKOWNIKA ===
    keywords_with_ranges = {}
    for line in keyword_list_string.strip().split('\n'):
        line = line.strip()
        if not line:
            continue

        # Format "słowo: min-max"
        match = re.match(r'^(.*?):\s*(\d+)-(\d+)x?$', line)
        if match:
            kw, min_val, max_val = match.groups()
            keywords_with_ranges[kw.strip()] = {"min": int(min_val), "max": int(max_val)}
            continue

        # Format "słowo: max"
        match = re.match(r'^(.*?):\s*(\d+)x?$', line)
        if match:
            kw, max_val = match.groups()
            keywords_with_ranges[kw.strip()] = {"min": 1, "max": int(max_val)}

    # === ANALIZA NLP ===
    doc_text = NLP(text_to_process.lower())
    text_lemmas = [token.lemma_ for token in doc_text]

    compliance_report = []
    for keyword, ranges in keywords_with_ranges.items():
        min_val, max_val = ranges.get("min", 0), ranges.get("max", float('inf'))
        doc_kw = NLP(keyword.lower())
        kw_lemma = doc_kw[0].lemma_
        actual_count = text_lemmas.count(kw_lemma)

        status = "OK" if min_val <= actual_count <= max_val else "ERROR"

        compliance_report.append({
            "keyword": keyword,
            "range": f"{min_val}-{max_val}",
            "actual": actual_count,
            "status": status
        })

    return {"compliance_report": compliance_report}
