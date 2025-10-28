from flask import Flask, request, jsonify
from collections import Counter
import spacy

# --- Importowanie lokalnych modułów ---
# Upewnij się, że pliki .py są w tym samym katalogu (lub pakiecie)
# i że plik generate_compliance_report.py został zaktualizowany
# do wersji stanowej (v4.1), którą podałem wcześniej.
try:
    from .synthesize_topics import synthesize_topics
    from .generate_compliance_report import generate_compliance_report
except ImportError:
    # Fallback dla uruchomienia bezpośrednio (np. python index.py)
    print("Uwaga: Uruchamianie w trybie fallback import (bez .)")
    from synthesize_topics import synthesize_topics
    from generate_compliance_report import generate_compliance_report


# ======================================================
# 🌍 Inicjalizacja aplikacji Flask
# ======================================================
app = Flask(__name__)

# Załaduj model języka polskiego (spaCy)
try:
    nlp = spacy.load("pl_core_news_sm")
except OSError:
    print("Model pl_core_news_sm nie znaleziony. Próba pobrania...")
    from spacy.cli import download
    download("pl_core_news_sm")
    nlp = spacy.load("pl_core_news_sm")

# ======================================================
# 🧩 1️⃣ Endpoint: analiza n-gramów i encji (Bez zmian)
# ======================================================
@app.route("/api/ngram_entity_analysis", methods=["POST"])
def perform_ngram_analysis():
    """
    Analizuje tekst pod kątem encji (entities) i n-gramów (2-, 3-, 4-gramów)
    oraz nadaje im priorytety na podstawie kontekstu SERP.
    """
    data = request.get_json()
    text = data.get("text", "")
    main_keyword = data.get("main_keyword", "")
    serp_context = data.get("serp_context", {})  # optional

    if not text.strip():
        return jsonify({"error": "Brak tekstu do analizy"}), 400

    doc = nlp(text)

    # --- Wykrywanie encji (entities) ---
    entities = list({ent.text for ent in doc.ents if len(ent.text) > 2})

    # --- Tokenizacja (oryginalne słowa + stop-words) ---
    tokens = [t.text.lower() for t in doc if t.is_alpha or t.is_stop]

    # --- Tworzenie n-gramów (2–4) ---
    ngram_results = {}
    for n in range(2, 5):
        grams = Counter([" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)])
        ngram_results[f"{n}gram"] = [{"ngram": g, "count": c} for g, c in grams.most_common(25)]

    # --- Priorytetyzacja (jeśli kontekst SERP jest dostępny) ---
    paa = " ".join(serp_context.get("people_also_ask", []))
    related = " ".join(serp_context.get("related_searches", []))
    snippets = " ".join(serp_context.get("featured_snippets", []))
    all_context = f"{paa} {related} {snippets}".lower()

    for key in ngram_results:
        for item in ngram_results[key]:
            phrase = item["ngram"]
            priority = 1
            if phrase in all_context:
                priority += 2
            if main_keyword and main_keyword.lower() in phrase:
                priority += 1
            item["priority"] = priority
        # Sortowanie po priorytecie
        ngram_results[key] = sorted(
            ngram_results[key],
            key=lambda x: (x["priority"], x["count"]),
            reverse=True
        )

    # --- Finalna odpowiedź ---
    return jsonify({
        "entities": entities[:15],
        "ngrams": ngram_results,
        "main_keyword": main_keyword,
        "summary": {
            "total_entities": len(entities),
            "text_length": len(text),
            "context_used": bool(serp_context)
        }
    })


# ======================================================
# 🧩 2️⃣ Endpoint: synteza tematów (Bez zmian)
# ======================================================
@app.route("/api/synthesize_topics", methods=["POST"])
def perform_synthesize_topics():
    """
    Tworzy syntetyczne tematy i powiązania semantyczne na podstawie
    n-gramów i nagłówków (H2) zanalizowanych wcześniej.
    """
    data = request.get_json()
    ngrams = data.get("ngrams", [])
    headings = data.get("headings", [])

    # Zakładając, że synthesize_topics przyjmuje ngrams i headings
    result = synthesize_topics(ngrams, headings)
    return jsonify(result)


# ======================================================
# 🧩 3️⃣ Endpoint: raport jakości treści (WERSJA STANOWA v4.1)
# ======================================================
@app.route("/api/generate_compliance_report", methods=["POST"])
def perform_generate_compliance_report():
    """
    Analizuje zgodność treści z założonymi słowami kluczowymi (STANOWO).
    Sprawdza użycie w batchu i zwraca nowy stan.
    """
    data = request.get_json()
    text = data.get("text", "") # Tekst TYLKO z bieżącego batcha
    
    # Oczekujemy klucza 'keyword_state' z master_api.py (zgodnego z v4.1)
    keyword_state_input = data.get("keyword_state") 

    # Fallback dla kompatybilności (gdyby master_api wysłał stary klucz 'keywords')
    if not keyword_state_input:
        keyword_state_input = data.get("keywords")
        
    if not keyword_state_input:
         return jsonify({"error": "Brak 'keyword_state' (lub 'keywords') w payloadzie"}), 400

    # Wywołanie nowej, stanowej funkcji
    result = generate_compliance_report(text, keyword_state_input) 
    return jsonify(result)


# ======================================================
# 🧩 4️⃣ Endpoint: testowy root (Bez zmian)
# ======================================================
@app.route("/", methods=["GET"])
def root():
    return jsonify({"message": "GPT N-Gram & Entity API (Stateful v4.1) działa poprawnie."})


# ======================================================
# 🩺 5️⃣ Health Check (Bez zmian)
# ======================================================
@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "✅ API działa poprawnie",
        "version": "v4.1.0-stateful", # Zmieniona wersja dla jasności
        "message": "gpt-ngram-api online"
    }), 200


# ======================================================
# 🚀 Uruchomienie lokalne
# ======================================================
if __name__ == "__main__":
    # Używamy portu 5000, zgodnie z Twoim render.yaml
    app.run(host="0.0.0.0", port=5000, debug=True)
