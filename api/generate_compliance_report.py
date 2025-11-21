import re
import spacy
import json
from rapidfuzz import fuzz  # nowa biblioteka do fuzzy matchy

# --- Stałe dla fuzzy-matching ---
FUZZY_SIMILARITY_THRESHOLD = 90  # próg podobieństwa 0–100
MAX_FUZZY_WINDOW_EXPANSION = 2   # max ile dodatkowych lematów może wejść „w środek” frazy


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


# --- NOWA FUNKCJA: parser stanu ---
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
            match = re.match(
                r'^(.*?):\s*(\d+)\s*(?:-|–|—)\s*(\d+)\s*x?$',
                line,
                re.IGNORECASE
            )
            if match:
                kw, min_val, max_val = match.groups()
                keywords_with_ranges[kw.strip()] = {
                    "min": int(min_val),
                    "max": int(max_val)
                }
                continue

            # Format "słowo: max"
            match = re.match(r'^(.*?):\s*(\d+)\
