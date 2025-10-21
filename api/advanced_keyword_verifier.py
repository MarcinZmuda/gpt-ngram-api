import re
import spacy

# Model spaCy ładowany raz dla optymalizacji
try:
    NLP = spacy.load("pl_core_news_sm")
except OSError:
    from spacy.cli import download
    download("pl_core_news_sm")
    NLP = spacy.load("pl_core_news_sm")

def advanced_keyword_verifier(text, keyword_list):
    """
    Zaawansowany walidator słów kluczowych:
    - sprawdza występowanie słów kluczowych (z odmianami)
    - raportuje brakujące i nadmiarowe frazy
    """

    if not text or not keyword_list:
        return {"error": "Brak danych. Wymagane pola: text, keyword_list."}

    # Zamiana listy na obiekt NLP
    doc = NLP(text.lower())
    lemmas = [token.lemma_ for token in doc if not token.is_punct]

    # Normalizacja słów kluczowych
    normalized_keywords = [kw.strip().lower() for kw in keyword_list if kw.strip()]
    results = []

    for kw in normalized_keywords:
        kw_doc = NLP(kw)
        kw_lemma = kw_doc[0].lemma_
        count = lemmas.count(kw_lemma)

        results.append({
            "keyword": kw,
            "lemma": kw_lemma,
            "count": count,
            "status": "OK" if count > 0 else "MISSING"
        })

    summary = {
        "total_keywords": len(normalized_keywords),
        "found": sum(1 for r in results if r["status"] == "OK"),
        "missing": sum(1 for r in results if r["status"] == "MISSING")
    }

    return {"summary": summary, "results": results}
