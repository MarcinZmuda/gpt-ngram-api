import os
import json
import re
from collections import Counter, defaultdict
from flask import Flask, request, jsonify
import spacy
import google.generativeai as genai

# --- Konfiguracja Gemini (Zastępstwo dla KeyBERT) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- Importy lokalne (Poprawione z kropką dla struktury modułu) ---
try:
    from .synthesize_topics import synthesize_topics
    from .generate_compliance_report import generate_compliance_report
except ImportError:
    # Fallback dla uruchamiania lokalnego poza pakietem
    from synthesize_topics import synthesize_topics
    from generate_compliance_report import generate_compliance_report

app = Flask(__name__)

# --- Ładowanie spaCy (Lekki model) ---
try:
    nlp = spacy.load("pl_core_news_sm")
except OSError:
    from spacy.cli import download
    download("pl_core_news_sm")
    nlp = spacy.load("pl_core_news_sm")


# ======================================================
# 🧠 Helper: Semantyka przez Gemini (Cloud)
# ======================================================
def extract_semantic_tags_gemini(text, top_n=10):
    """
    Używa Google Gemini Flash do wyciągnięcia fraz semantycznych.
    Zastępuje ciężkiego KeyBERT-a. Nie zużywa RAM-u.
    """
    if not GEMINI_API_KEY or not text.strip():
        return []

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
        Jesteś ekspertem SEO. Przeanalizuj poniższy tekst i wypisz {top_n} najważniejszych fraz kluczowych (semantic keywords), które najlepiej oddają jego sens.
        Zwróć TYLKO listę po przecinku, bez numerowania.
        
        TEKST: {text[:8000]}...
        """
        response = model.generate_content(prompt)
        keywords = [k.strip() for k in response.text.split(",") if k.strip()]
        
        # Formatujemy tak jak stary KeyBERT: [{"phrase": x, "score": 0.9}]
        # Dajemy sztuczny score, bo Gemini go nie zwraca, a frontend go lubi.
        return [{"phrase": kw, "score": 0.95 - (i*0.02)} for i, kw in enumerate(keywords[:top_n])]
    except Exception as e:
        print(f"Gemini Semantic Error: {e}")
        return []


# ======================================================
# 🧩 Endpoint: Analiza N-gramów + Semantyka Cloud
# ======================================================
@app.route("/api/ngram_entity_analysis", methods=["POST"])
def perform_ngram_analysis():
    data = request.get_json()
    main_keyword = data.get("main_keyword", "")
    serp_context = data.get("serp_context", {})
    sources = data.get("sources", [])
    top_n = int(data.get("top_n", 30))

    if not sources:
        return jsonify({"error": "Brak źródeł do analizy"}), 400

    # 1. NLP Statystyczne (N-gramy) - Lekkie, na CPU
    ngram_presence = defaultdict(set)
    ngram_freqs = Counter()
    
    # Łączymy tekst do analizy semantycznej
    all_text_content = []

    for src in sources:
        content = src.get("content", "").lower()
        all_text_content.append(src.get("content", ""))
        
        doc = nlp(content[:100000]) # Limit dla bezpieczeństwa RAM
        tokens = [t.text.lower() for t in doc if t.is_alpha]

        for n in range(2, 5):
            for i in range(len(tokens) - n + 1):
                ngram = " ".join(tokens[i:i + n])
                ngram_freqs[ngram] += 1
                ngram_presence[ngram].add(src.get("url", "unknown"))

    # Scoring N-gramów
    max_freq = max(ngram_freqs.values()) if ngram_freqs else 1
    results = []
    
    for ngram, freq in ngram_freqs.items():
        if freq < 2: continue # Ignorujemy unikaty
        
        freq_norm = freq / max_freq
        site_score = len(ngram_presence[ngram]) / len(sources)
        
        # Prosta waga: częstotliwość + dystrybucja
        weight = round(freq_norm * 0.5 + site_score * 0.5, 4)
        
        # Boost za słowo kluczowe
        if main_keyword.lower() in ngram: weight += 0.1

        results.append({
            "ngram": ngram,
            "freq": freq,
            "weight": min(1.0, weight),
            "site_distribution": f"{len(ngram_presence[ngram])}/{len(sources)}"
        })

    # Sortowanie N-gramów
    results = sorted(results, key=lambda x: x["weight"], reverse=True)[:top_n]

    # 2. Semantyka w Chmurze (Gemini zamiast KeyBERT)
    full_text_sample = " ".join(all_text_content)[:15000] # Próbka dla Gemini
    semantic_keyphrases = extract_semantic_tags_gemini(full_text_sample)

    return jsonify({
        "main_keyword": main_keyword,
        "ngrams": results,
        "semantic_keyphrases": semantic_keyphrases, # Tu wchodzą wyniki z Gemini
        "summary": {
            "total_sources": len(sources),
            "engine": "v11-light-cloud"
        }
    })


# ======================================================
# 🧩 Pozostałe Endpointy (Proxy)
# ======================================================
@app.route("/api/synthesize_topics", methods=["POST"])
def perform_synthesize_topics():
    data = request.get_json()
    return jsonify(synthesize_topics(data.get("ngrams", []), data.get("headings", [])))

@app.route("/api/generate_compliance_report", methods=["POST"])
def perform_generate_compliance_report():
    data = request.get_json()
    return jsonify(generate_compliance_report(data.get("text", ""), data.get("keyword_state", {})))

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "mode": "lightweight-cloud-semantic"})

# Uruchomienie (dla lokalnych testów, Render używa Gunicorna)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
