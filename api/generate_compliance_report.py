import re
import spacy

# --- Ładowanie modelu ---
# Model spaCy ładowany raz dla optymalizacji
try:
    NLP = spacy.load("pl_core_news_sm")
except OSError:
    print("Pobieranie modelu pl_core_news_sm...")
    from spacy.cli import download
    download("pl_core_news_sm")
    NLP = spacy.load("pl_core_news_sm")


# --- Funkcja pomocnicza z lemmatize_and_count.py (Doskonała lematyzacja) ---
def _lemmatize_text_to_list(text):
    """
    Zwraca listę lematów z tekstu (tylko tokeny alfabetyczne, 
    bez interpunkcji).
    """
    doc = NLP(text.lower())
    # Używamy is_alpha, aby odfiltrować interpunkcję i liczby
    return [token.lemma_ for token in doc if token.is_alpha]


# --- Główna funkcja (połączenie obu logik) ---
def generate_compliance_report(text_to_process, keyword_list_string):
    """
    Generuje raport zgodności, używając:
    - Inteligentnego parsera zakresów (z generate_compliance_report.py)
    - Zaawansowanego liczenia sekwencji n-gram (z lemmatize_and_count.py)
    """

    if not text_to_process or not keyword_list_string:
        return {"error": "Payload must include 'text' and 'keyword_list_string'."}

    # === 1. PARSER (Idealny - z generate_compliance_report.py) ===
    # Paruje format briefu S2 (np. "rozwód warszawa: 2-4x")
    keywords_with_ranges = {}
    for line in keyword_list_string.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # Format "słowo: min-max" (obsługuje -, –, —)
        # Dodano re.IGNORECASE dla "x"
        match = re.match(r'^(.*?):\s*(\d+)[\s*(-|–|—)\s*](\d+)\s*x?$', line, re.IGNORECASE)
        if match:
            kw, min_val, max_val = match.groups()
            keywords_with_ranges[kw.strip()] = {"min": int(min_val), "max": int(max_val)}
            continue

        # Format "słowo: max" (np. "rozwód: 5x")
        match = re.match(r'^(.*?):\s*(\d+)\s*x?$', line, re.IGNORECASE)
        if match:
            kw, max_val = match.groups()
            keywords_with_ranges[kw.strip()] = {"min": 1, "max": int(max_val)}
            continue

        # Format "słowo" (bez zakresu) - przypisujemy domyślny zakres
        if ':' not in line and line:
            keywords_with_ranges[line] = {"min": 1, "max": 99} # Domyślny wysoki zakres


    # === 2. ANALIZA NLP (Doskonała - z lemmatize_and_count.py) ===
    # Lematyzujemy CAŁY tekst DOKŁADNIE RAZ
    text_lemmas = _lemmatize_text_to_list(text_to_process)
    text_lemmas_len = len(text_lemmas)

    # === 3. LOGIKA LICZENIA (Doskonała - z lemmatize_and_count.py) ===
    compliance_report = []
    
    for keyword, ranges in keywords_with_ranges.items():
        min_val, max_val = ranges["min"], ranges["max"]

        # Lematyzujemy frazę kluczową (nawet jeśli ma wiele słów)
        keyword_lemmas = _lemmatize_text_to_list(keyword)
        kw_len = len(keyword_lemmas)
        actual_count = 0

        if kw_len == 0: # Pusta fraza, pomijamy
            continue
            
        # Przesuwamy się po tekście i sprawdzamy pełne dopasowania SEKWENCJI
        for i in range(text_lemmas_len - kw_len + 1):
            if text_lemmas[i:i + kw_len] == keyword_lemmas:
                actual_count += 1

        # === 4. RAPORTOWANIE (z generate_compliance_report.py) ===
        status = "OK"
        if actual_count < min_val:
            status = "UNDER"
        elif actual_count > max_val:
            status = "OVER"

        compliance_report.append({
            "keyword": keyword,
            "range": f"{min_val}-{max_val}",
            "actual": actual_count,
            "status": status
        })

    return {"compliance_report": compliance_report}


# --- Przykładowe użycie do testów ---
if __name__ == "__main__":
    test_text = """
    Cześć, tu prawnik. Rozwód w Warszawie to skomplikowana sprawa. 
    Jeśli myślisz o rozwodzie, pamiętaj o kosztach. 
    Nasz prawnik od rozwodów pomoże. Rozwód w Warszawie może trwać.
    Co więcej, nasz prawnik od rozwodów to ekspert.
    """
    
    test_keywords_string = """
    rozwód w Warszawie: 2-3x
    prawnik od rozwodów: 1-1x
    rozwód: 4-10x
    koszty: 1x
    cześć: 1-2x
    """
    
    report = generate_compliance_report(test_text, test_keywords_string)
    
    import json
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # Oczekiwany wynik:
    # rozwód w Warszawie: actual 2, status OK
    # prawnik od rozwodów: actual 2, status OVER
    # rozwód: actual 2, status UNDER (bo liczy tylko "rozwód" jako pojedyncze słowo)
    # koszty: actual 1, status OK
    # cześć: actual 1, status OK
