from flask import Flask, request, jsonify
from collections import Counter
import spacy
from .synthesize_topics import synthesize_topics
from .generate_compliance_report import generate_compliance_report

# ======================================================
# 🌍 Inicjalizacja aplikacji Flask
# ======================================================
app = Flask(__name__)

# Załaduj model języka polskiego (spaCy)
nlp = spacy.load("pl_core_news_sm")

# ======================================================
# 🧩 1️⃣ Endpoint: analiza n-gramów i encji
# ======================================================
@app.route("/api/ngram_entity_analysis", methods=["POST"])
def perform_ngram_analysis():
    """
    Analizuje tekst pod kątem encji (entities) i n-gramów (2-, 3-, 4-gramów).
    Dodatkowo nadaje priorytety n-gramom na podstawie:
    - częstotliwości wystąpień,
    - powiązań z PAA, powiązanymi wyszukiwaniami i snippetami (jeśli podano).
    """
    data = request.get_json()
    text = data.get("text", "")
    main_keyword = data.get("main_keyword", "")
    serp_context = data.get("serp_context", {})  # optional – np. PAA, related searches, snippets

    if not text.strip():
        return jsonify({"error": "Brak tekstu do analizy"}), 400

    doc = nlp(text)

    # --- Wykrywanie encji (entities) ---
    entities = list({ent.text for ent in doc.ents if len(ent.text) > 2})

    # --- Tokenizacja + lematyzacja ---
    tokens = [t.lemma_.lower() for t in doc if t.is_alpha and not t.is_stop]

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

    # --- Sortowanie po priorytecie ---
    for key in ngram_results:
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
# 🧩 2️⃣ Endpoint: synteza tematów
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
    text = data.get("text", "")

    result = synthesize_topics(ngrams, headings, text)
    return jsonify(result)


# ======================================================
# 🧩 3️⃣ Endpoint: raport jakości treści
# ======================================================
@app.route("/api/generate_compliance_report", methods=["POST"])
def perform_generate_compliance_report():
    """
    Analizuje zgodność treści z założonymi słowami kluczowymi.
    Sprawdza ich użycie i gęstość w stosunku do dopuszczalnych zakresów.
    """
    data = request.get_json()
    text = data.get("text", "")
    keywords = data.get("keywords", {})

    result = generate_compliance_report(text, keywords)
    return jsonify(result)


# ======================================================
# 🧩 4️⃣ Endpoint: testowy root (opcjonalny)
# ======================================================
@app.route("/", methods=["GET"])
def root():
    return jsonify({"message": "GPT N-Gram & Entity API działa poprawnie."})


# ======================================================
# 🩺 5️⃣ Health Check
# ======================================================
@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "✅ API działa poprawnie",
        "version": "v3.0.0",
        "message": "gpt-ngram-api-igyw online"
    }), 200


# ======================================================
# 🚀 Uruchomienie lokalne
# ======================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
