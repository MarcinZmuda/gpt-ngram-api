from flask import Flask, request, jsonify
from collections import Counter, defaultdict
import spacy
import re

try:
    from .synthesize_topics import synthesize_topics
    from .generate_compliance_report import generate_compliance_report
except ImportError:
    print("Uwaga: uruchamianie w trybie fallback import (bez .)")
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
    from spacy.cli import download
    download("pl_core_news_sm")
    nlp = spacy.load("pl_core_news_sm")


# ======================================================
# 🧩 1️⃣ Endpoint: analiza n-gramów i encji (rozszerzony)
# ======================================================
@app.route("/api/ngram_entity_analysis", methods=["POST"])
def perform_ngram_analysis():
    """
    Analizuje tekst lub listę źródeł (sources) pod kątem n-gramów 2–4 i encji.
    Oblicza freq_norm, position_score, site_distribution_score i zwraca ranking.
    """
    data = request.get_json()
    main_keyword = data.get("main_keyword", "")
    serp_context = data.get("serp_context", {})
    text = data.get("text", "")
    sources = data.get("sources", [])

    if not text.strip() and not sources:
        return jsonify({"error": "Brak tekstu lub źródeł do analizy"}), 400

    # --- Przygotowanie listy źródeł ---
    if not sources:
        sources = [{"url": "input_text", "content": text}]
    avg_text_length = sum(len(s["content"]) for s in sources) / len(sources)

    ngram_presence = defaultdict(set)
    ngram_freqs = Counter()
    total_tokens = 0

    # --- Analiza każdego źródła ---
    for idx, src in enumerate(sources):
        content = src.get("content", "")
        if not content.strip():
            continue
        doc = nlp(content)
        tokens = [t.text.lower() for t in doc if t.is_alpha]
        total_tokens += len(tokens)

        # Pozycje n-gramów
        for n in range(2, 5):
            for i in range(len(tokens) - n + 1):
                ngram = " ".join(tokens[i:i+n])
                ngram_freqs[ngram] += 1
                ngram_presence[ngram].add(src["url"])

    # --- Normalizacja i scoring ---
    max_freq = max(ngram_freqs.values()) if ngram_freqs else 1
    results = []
    for ngram, freq in ngram_freqs.most_common():
        freq_norm = freq / max_freq

        # site_distribution_score
        site_score = len(ngram_presence[ngram]) / len(sources)

        # position_score (bazowo 1.0, jeśli występuje w 20% początkowych tokenów)
        position_score = 0
        for src in sources:
            content = src.get("content", "").lower()
            pos = content.find(ngram)
            if pos != -1 and pos < len(content) * 0.2:
                position_score += 1
        position_score = position_score / len(sources)

        weight = round(freq_norm * 0.6 + position_score * 0.2 + site_score * 0.2, 4)

        results.append({
            "ngram": ngram,
            "freq": freq,
            "freq_norm": round(freq_norm, 3),
            "position_score": round(position_score, 3),
            "site_distribution": f"{len(ngram_presence[ngram])}/{len(sources)}",
            "site_distribution_score": round(site_score, 3),
            "weight": weight
        })

    # --- Encje globalne ---
    all_text = " ".join(s["content"] for s in sources)
    doc_global = nlp(all_text)
    entities = list({ent.text for ent in doc_global.ents if len(ent.text) > 2})

    # --- Kontekst SERP (boost priorytetu) ---
    paa = " ".join(serp_context.get("people_also_ask", []))
    related = " ".join(serp_context.get("related_searches", []))
    snippets = " ".join(serp_context.get("featured_snippets", []))
    all_context = f"{paa} {related} {snippets}".lower()

    for r in results:
        boost = 0
        if main_keyword and main_keyword.lower() in r["ngram"]:
            boost += 0.05
        if r["ngram"] in all_context:
            boost += 0.05
        r["weight"] = round(min(1.0, r["weight"] + boost), 4)

    # --- Sortowanie końcowe ---
    results = sorted(results, key=lambda x: x["weight"], reverse=True)[:30]

    return jsonify({
        "main_keyword": main_keyword,
        "avg_text_length": round(avg_text_length, 1),
        "ngrams": results,
        "entities": entities[:20],
        "summary": {
            "total_sources": len(sources),
            "unique_ngrams": len(ngram_freqs),
            "context_used": bool(serp_context)
        }
    })


# ======================================================
# 🧩 2️⃣ Endpoint: synteza tematów (Bez zmian)
# ======================================================
@app.route("/api/synthesize_topics", methods=["POST"])
def perform_synthesize_topics():
    data = request.get_json()
    ngrams = data.get("ngrams", [])
    headings = data.get("headings", [])
    result = synthesize_topics(ngrams, headings)
    return jsonify(result)


# ======================================================
# 🧩 3️⃣ Endpoint: raport jakości treści (Bez zmian)
# ======================================================
@app.route("/api/generate_compliance_report", methods=["POST"])
def perform_generate_compliance_report():
    data = request.get_json()
    text = data.get("text", "")
    keyword_state_input = data.get("keyword_state") or data.get("keywords")
    if not keyword_state_input:
        return jsonify({"error": "Brak 'keyword_state' w payloadzie"}), 400
    result = generate_compliance_report(text, keyword_state_input)
    return jsonify(result)


# ======================================================
# 🧩 Root i Health Check
# ======================================================
@app.route("/", methods=["GET"])
def root():
    return jsonify({"message": "GPT N-Gram & Entity API (v5.0) działa poprawnie."})

@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "version": "v5.0",
        "message": "gpt-ngram-api z obsługą site_distribution i position_score działa."
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
