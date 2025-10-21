import re

def hierarchical_keyword_counter(raw_counts):
    """
    Oblicza hierarchiczne zliczanie fraz kluczowych.
    Jeśli krótsze słowo występuje w dłuższym (np. 'rozwód' w 'rozwód warszawa'),
    liczba jego wystąpień zostaje zwiększona o liczbę wystąpień dłuższej frazy.

    Parametry:
        raw_counts (dict): np. {"rozwód": 3, "rozwód warszawa": 2}

    Zwraca:
        dict: {"rozwód": 5, "rozwód warszawa": 2}
    """

    if not isinstance(raw_counts, dict):
        return {"error": "'raw_counts' must be a dictionary."}

    # Sortujemy frazy od najdłuższej do najkrótszej
    keywords = sorted(raw_counts.keys(), key=len, reverse=True)
    hierarchical_counts = raw_counts.copy()

    # Dla każdej frazy sprawdzamy, czy zawiera krótszą
    for i, long_kw in enumerate(keywords):
        for short_kw in keywords[i + 1:]:
            if short_kw in long_kw and re.search(r'\b' + re.escape(short_kw) + r'\b', long_kw):
                hierarchical_counts[short_kw] += raw_counts.get(long_kw, 0)

    return {"hierarchical_counts": hierarchical_counts}
