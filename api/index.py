import os
import json
import re
from collections import Counter, defaultdict
from flask import Flask, request, jsonify
import spacy
import google.generativeai as genai

# --- Firestore Integration ---
from firebase_admin import firestore

# --- Konfiguracja Gemini (Zastępstwo dla KeyBERT) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("[S1] ⚠️ GEMINI_API_KEY not set — semantic extraction fallback active")

# --- Importy lokalne (dla trybu pakietowego i lokalnego) ---
try:
    from .synthesize_topics import synthesize_topics
    from .generate_compliance_report import generate_compliance_report
except ImportError:
    from synthesize_topics import synthesize_topics
    from generate_compliance_report import generate_compliance_report

app = Flask(__name__)

# --- Ładowanie spaCy (lekki model do S1) ---
try:
    nlp = spacy.load("pl_core_news_sm")
    print("[S1] ✅ spaCy pl_core_news_sm loaded")
except OSError:
    from spacy.cli import download
    download("pl_core_news_sm")
    nlp = spacy.load("pl_core_news_sm")
    print("[S1] ✅ spaCy model downloaded and loaded")


# ======================================================
# 🧠 Helper: Semantyka przez Gemini (Cloud)
# ======================================================
def extract_semantic_tags_gemini(text, top_n=10):
    """Używa Google Gemini Flash do wyciągnięcia fraz semantycznych."""
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
        return [{"phrase": kw, "score": 0.95 - (i * 0.02)} for i, kw in enumerate(keywords[:top_n])]
    except Exception as e:
        print(f"[S1] ❌ Gemini Semantic Error: {e}")
        return []


# ======================================================
# 🧩 Endpoint: Analiza N-gramów + Semantyka Cloud + Firestore Save
# ======================================================
@app.route("/api/ngram_entity_analysis", methods=["POST"])
def perform_ngram_analysis():
    data = request.get_json(force=True)
    main_keyword = data.get("main_keyword", "")
    sources = data.get("sources", [])
    top_n = int(data.get("top_n", 30))
    project_id = data.get("project_id")

    if not sources:
        return jsonify({"error": "Brak źródeł do analizy"}), 400

    print(f"[S1] 🔍 Analiza n-gramów dla: {main_keyword}")

    # 1️⃣ NLP Statystyczne (N-gramy)
    ngram_presence = defaultdict(set)
    ngram_freqs = Counter()
    all_text_content = []

    for src in sources:
        content = src.get("content", "").lower()
        if not content.strip():
            continue

        all_text_content.append(src.get("content", ""))
        doc = nlp(content[:100000])
        tokens = [t.text.lower() for t in doc if t.is_alpha]

        for n in range(2, 5):
            for i in range(len(tokens) - n + 1):
                ngram = " ".join(tokens[i:i + n])
                ngram_freqs[ngram] += 1
                ngram_presence[ngram].add(src.get("url", "unknown"))

    max_freq = max(ngram_freqs.values()) if ngram_freqs else 1
    results = []

    for ngram, freq in ngram_freqs.items():
        if freq < 2:
            continue
        freq_norm = freq / max_freq
        site_score = len(ngram_presence[ngram]) / len(sources)
        weight = round(freq_norm * 0.5 + site_score * 0.5, 4)
        if main_keyword.lower() in ngram:
            weight += 0.1
        results.append({
            "ngram": ngram,
            "freq": freq,
            "weight": min(1.0, weight),
            "site_distribution": f"{len(ngram_presence[ngram])}/{len(sources)}"
        })

    results = sorted(results, key=lambda x: x["weight"], reverse=True)[:top_n]

    # 2️⃣ Semantyka (Gemini Flash)
    full_text_sample = " ".join(all_text_content)[:15000]
    semantic_keyphrases = extract_semantic_tags_gemini(full_text_sample)

    response_payload = {
        "main_keyword": main_keyword,
        "ngrams": results,
        "semantic_keyphrases": semantic_keyphrases,
        "summary": {
            "total_sources": len(sources),
            "engine": "v18.5-semantic-firestore",
            "lsi_candidates": len(semantic_keyphrases),
        }
    }

    # 3️⃣ Firestore Save (jeśli podano project_id)
    if project_id:
        try:
            db = firestore.client()
            doc_ref = db.collection("seo_projects").document(project_id)
            if doc_ref.get().exists:
                avg_len = (
                    sum(len(t.split()) for t in all_text_content) // len(all_text_content)
                    if all_text_content else 0
                )
                doc_ref.update({
                    "s1_data": response_payload,
                    "lsi_enrichment": {"enabled": True, "count": len(semantic_keyphrases)},
                    "avg_competitor_length": avg_len,
                    "updated_at": firestore.SERVER_TIMESTAMP
                })
                response_payload["saved_to_firestore"] = True
                print(f"[S1] ✅ Wyniki n-gramów zapisane do Firestore → {project_id}")
            else:
                response_payload["saved_to_firestore"] = False
                print(f"[S1] ⚠️ Nie znaleziono projektu {project_id}")
        except Exception as e:
            print(f"[S1] ❌ Firestore error: {e}")
            response_payload["firestore_error"] = str(e)

    return jsonify(response_payload)


# ======================================================
# 🧩 Pozostałe Endpointy (Proxy)
# ======================================================
@app.route("/api/synthesize_topics", methods=["POST"])
def perform_synthesize_topics():
    data = request.get_json(force=True)
    return jsonify(synthesize_topics(data.get("ngrams", []), data.get("headings", [])))


@app.route("/api/generate_compliance_report", methods=["POST"])
def perform_generate_compliance_report():
    data = request.get_json(force=True)
    return jsonify(generate_compliance_report(data.get("text", ""), data.get("keyword_state", {})))


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "engine": "v18.5-semantic-firestore",
        "gemini_enabled": bool(GEMINI_API_KEY)
    })


# ======================================================
# 🧩 Uruchomienie lokalne
# ======================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
