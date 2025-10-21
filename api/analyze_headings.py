from collections import Counter

def analyze_headings(headings):
    """
    Analizuje listę nagłówków (np. H2, H3 itp.) i zwraca
    5 najczęściej powtarzających się wraz z liczbą ich wystąpień.

    Parametry:
        headings (list): Lista nagłówków w formie tekstowej.

    Zwraca:
        dict: {
            "top_headings": [
                {"heading": "przykładowy nagłówek", "count": 3},
                ...
            ]
        }
        lub {"error": "..."} w przypadku nieprawidłowych danych.
    """

    # Walidacja wejścia
    if not isinstance(headings, list):
        return {"error": "Payload must include 'headings' as a list of strings."}

    # Usunięcie pustych elementów i białych znaków
    clean_headings = [h.strip() for h in headings if isinstance(h, str) and h.strip()]

    # Zliczenie częstości wystąpień
    heading_counts = Counter(clean_headings)

    # Wybranie 5 najczęstszych
    top_5_headings = [
        {"heading": h, "count": c} for h, c in heading_counts.most_common(5)
    ]

    return {"top_headings": top_5_headings}
