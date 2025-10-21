def keyword_validator(data):
    """
    Prosty walidator słów kluczowych.
    Oczekuje już zlematyzowanego tekstu i listy słów kluczowych.

    Parametry:
        data (dict): {
            "lemmatized_text": "tekst zlematyzowany ...",
            "lemmatized_keywords": ["słowo1", "słowo2"]
        }

    Zwraca:
        dict: {"keyword_counts": {"słowo1": 3, "słowo2": 1}}
    """

    lemmatized_text = data.get('lemmatized_text', '')
    lemmatized_keywords = data.get('lemmatized_keywords', [])

    if not lemmatized_text or not lemmatized_keywords:
        return {"error": "Missing lemmatized text or keywords"}

    results = {}
    for keyword in lemmatized_keywords:
        # Proste zliczanie wystąpień
        count = lemmatized_text.count(keyword)
        results[keyword] = count

    return {"keyword_counts": results}
