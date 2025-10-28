import re
import spacy
import json

# --- Ładowanie modelu ---
try:
    NLP = spacy.load("pl_core_news_sm")
except OSError:
    print("Pobieranie modelu pl_core_news_sm...")
    from spacy.cli import download
    download("pl_core_news_sm")
    NLP = spacy.load("pl_core_news_sm")

# --- Funkcja pomocnicza (Lematyzacja) ---
def _lemmatize_text_to_list(text):
    """Zwraca listę lematów z tekstu (tylko tokeny alfabetyczne)."""
    doc = NLP(text.lower())
    return [token.lemma_ for token in doc if token.is_alpha]

# --- NOWA FUNKCJA: Parser stanu ---
def _parse_keyword_state(keyword_state_input):
    """
    Parsuje stan słów kluczowych.
    Wejście może być stringiem (brief S2) lub obiektem (poprzedni stan).
    Zawsze zwraca obiekt (słownik) formatu: {'fraza': {'min': X, 'max': Y}}
    """
    keywords_with_ranges = {}
    
    # Przypadek 1: Wejście to string (pierwsze wywołanie z S2)
    if isinstance(keyword_state_input, str):
        for line in keyword_state_input.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Format "słowo: min-max"
            match = re.match(r'^(.*?):\s*(\d+)[\s*(-|–|—)\s*](\d+)\s*x?$', line, re.IGNORECASE)
            if match:
                kw, min_val, max_val = match.groups()
                keywords_with_ranges[kw.strip()] = {"min": int(min_val), "max": int(max_val)}
                continue

            # Format "słowo: max"
            match = re.match(r'^(.*?):\s*(\d+)\s*x?$', line, re.IGNORECASE)
            if match:
                kw, max_val = match.groups()
                keywords_with_ranges[kw.strip()] = {"min": 1, "max": int(max_val)}
                continue

            # Format "słowo" (bez zakresu)
            if ':' not in line and line:
                keywords_with_ranges[line] = {"min": 1, "max": 99}
        return keywords_with_ranges
    
    # Przypadek 2: Wejście to już obiekt (kolejne wywołania)
    elif isinstance(keyword_state_input, dict):
        # Walidacja, czy format jest poprawny
        if all(isinstance(v, dict) and 'min' in v and 'max' in v for v in keyword_state_input.values()):
            return keyword_state_input
        else:
            raise ValueError("Niepoprawny format obiektu 'keyword_state'. Oczekiwano {'kw': {'min': x, 'max': y}}.")
    
    else:
        raise ValueError("Niepoprawny typ 'keyword_state'. Oczekiwano stringa lub obiektu.")

# --- Główna funkcja (wersja STANOWA) ---
def generate_compliance_report(text_to_process, keyword_state_input):
    """
    Generuje raport zgodności i ZWRACA NOWY STAN.
    Liczy słowa tylko w podanym 'text_to_process' (batchu).
    Odejmuje policzone słowa od stanu 'keyword_state_input'.
    """

    # === 1. PARSOWANIE STANU ===
    try:
        # Wczytujemy pulę, jaka nam pozostała
        current_state = _parse_keyword_state(keyword_state_input)
    except Exception as e:
        return {"error": str(e), "new_keyword_state": keyword_state_input}

    # Jeśli tekst jest pusty, nie rób nic, zwróć ten sam stan
    if not text_to_process:
        empty_report = [{
            "keyword": kw,
            "range_remaining": f"{v['min']}-{v['max']}",
            "actual_in_batch": 0,
            "status": "OK" # Nic się nie stało
        } for kw, v in current_state.items()]
        return {"compliance_report": empty_report, "new_keyword_state": current_state}

    # === 2. ANALIZA NLP (tylko bieżący batch) ===
    text_lemmas = _lemmatize_text_to_list(text_to_process)
    text_lemmas_len = len(text_lemmas)

    # === 3. LOGIKA LICZENIA (batch) i AKTUALIZACJA STANU ===
    compliance_report_batch = []
    new_keyword_state = {}

    for keyword, ranges in current_state.items():
        min_val, max_val = ranges["min"], ranges["max"]

        # Lematyzacja frazy kluczowej
        keyword_lemmas = _lemmatize_text_to_list(keyword)
        kw_len = len(keyword_lemmas)
        actual_count_in_batch = 0 # Licznik tylko dla tego batcha

        if kw_len > 0:
            for i in range(text_lemmas_len - kw_len + 1):
                if text_lemmas[i:i + kw_len] == keyword_lemmas:
                    actual_count_in_batch += 1
        
        # Obliczanie statusu dla BIEŻĄCEGO batcha (czy nie przekroczył puli)
        status = "OK"
        if actual_count_in_batch > max_val:
            status = "OVER" # Użyto w batchu więcej niż pozostało w puli
        
        # Tworzenie raportu dla batcha
        compliance_report_batch.append({
            "keyword": keyword,
            "range_remaining": f"{min_val}-{max_val}", # Jaki był cel na początku batcha
            "actual_in_batch": actual_count_in_batch,
            "status": status 
        })
        
        # Tworzenie NOWEGO STANU na następny batch
        # Odejmujemy to, co zużyliśmy w tym batchu
        new_min = max(0, min_val - actual_count_in_batch) # min nie może spaść poniżej 0
        new_max = max(0, max_val - actual_count_in_batch) # max nie może spaść poniżej 0
        
        if new_min > new_max:
            new_max = new_min # Wyrównujemy, jeśli min > max
            
        new_keyword_state[keyword] = {
            "min": new_min,
            "max": new_max
        }

    return {
        "compliance_report": compliance_report_batch, 
        "new_keyword_state": new_keyword_state # Zwracamy zaktualizowaną pulę
    }
