from flask import Flask, request, jsonify
from collections import Counter, defaultdict
import spacy
import re
import os

# --- KeyBERT + sentence-transformers ---
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer

# --- Importy lokalne ---
try:
    from .synthesize_topics import synthesize_topics
    from .generate_compliance_report import generate_compliance_report
except ImportError:
    from synthesize_topics import synthesize_topics
    from generate_compliance_report import generate_compliance_report


# ======================================================
# 🌍 Inicjalizacja aplikacji Flask
# ======================================================
app = Flask(__name__)

# -------- spaCy PL --------
try:
    nlp = spacy.load("pl_core_news_sm")
except OSError:
    from spacy.cli import download
    download("pl_core_news_sm")
    nlp = spacy.load("pl_core_news_sm")


# ======================================================
# 🤖 MODELE SEMANTYCZNE (KeyBERT / HerBERT)
# ======================================================
KEYBERT_MODEL_NAME = os.getenv(
    "KEYBERT_MODEL_NAME",
    "paraphrase-multilingual-MiniLM-L12-v2"
)

try:
    sentence_model = SentenceTransformer(KEYBERT_MODEL_NAME)
    keybert = KeyBERT(model=sentence_model)
except Exception as e:
    print("⚠️ KeyBERT init error:", e)
    keybert = None


# ======================================================
# 🧩 1️⃣ Endpoint: analiza n-gramów + encji + semantic keyphrases
# ======================================================
@app.route("/api/ngram_entity_analysis", methods=["POST"])
def perform_ngram_analysis():
    data = request.get_json()

    main_keyword = data.get("main_keyword", "")
    serp_context = data.get("serp_context", {})
    text = data.get("text", "")
    sources = data.get("sources", [])
    top_n = int(data.get("top_n", 30))

    if not text.strip() and not sources:
        return jsonify({"error": "Brak tekstu lub źródeł do analizy"}), 400

    # Jeśli dostajemy tylko tekst – zamieniamy na strukturę sources
    if not sources:
        sources = [{"url": "input_text", "content": text}]

    # ======================================================
    # 1. NLP → tokenizacja i ngramy 2–4
    # ======================================================
    ngram_presence = defaultdict(set)
    ngram_freqs = Counter()

    for src in sources:
        content = src.get("content", "").lower()
        doc = nlp(content)
        tokens = [t.text.lower() for t in doc if t.is_alpha]

        for n in range(2, 5):  # n-gramy 2,3,4
            for i in range(len(tokens) - n + 1):
                ngram = " ".join(tokens[i:i+n])
                ngram_freqs[ngram] += 1
                ngram_presence[ngram].add(src["url"])

    # Normalizacja częstotliwości
    max_freq = max(ngram_freqs.values()) if ngram_freqs else 1

    # ======================================================
    # 2. Scoring (freq_norm + position_score + site_distribution)
    # ======================================================
    results = []
    for ngram, freq in ngram_freqs.items():
        freq_norm = freq / max_freq
        site_score = len(ngram_presence[ngram]) / len(sources)

        # position_score — jeśli ngram pojawia się w pierwszych 20% treści
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

    # ======================================================
    # 3. Encje globalne
    # ======================================================
    all_text = " ".join(s["content"] for s in sources)
    doc_global = nlp(all_text)
    entities = list({ent.text for ent in doc_global.ents if len(ent.text) > 2})

    # ======================================================
    # 4. Semantic Keyphrases (KeyBERT / HerBERT)
    # ======================================================
    semantic_keyphrases = []
    if keybert and all_text.strip():
        try:
            phrases = keybert.extract_keywords(
                all_text,
                keyphrase_ngram_range=(1, 4),
                stop_words=None,
                use_mmr=True,
                diversity=0.6,
                top_n=top_n
            )
            semantic_keyphrases = [
                {"phrase": p[0], "score": float(p[1])}
                for p in phrases
            ]
        except Exception as e:
            print("⚠️ KeyBERT extraction error:", e)

    # ======================================================
    # 5. SERP context boost
    # ======================================================
    serp_blob = " ".join([
        " ".join(serp_context.get("people_also_ask", [])),
        " ".join(serp_context.get("related_searches", [])),
        " ".join(serp_context.get("featured_snippets", [])),
    ]).lower()

    for r in results:
        boost = 0.0
        if main_keyword.lower() in r["ngram"]:
            boost += 0.05
        if r["ngram"] in serp_blob:
            boost += 0.05
        r["weight"] = round(min(1.0, r["weight"] + boost), 4)

    results = sorted(results, key=lambda x: x["weight"], reverse=True)[:top_n]

    return jsonify({
        "main_keyword": main_keyword,
        "ngrams": results,
        "entities": entities[:20],
        "semantic_keyphrases": semantic_keyphrases,
        "summary": {
            "total_sources": len(sources),
            "unique_ngrams": len(ngram_freqs),
            "context_used": bool(serp_context),
            "sentence_model": KEYBERT_MODEL_NAME
        }
    })


# ======================================================
# 🧩 2️⃣ Endpoint: synteza tematów (bez zmian)
# ======================================================
@app.route("/api/synthesize_topics", methods=["POST"])
def perform_synthesize_topics():
    data = request.get_json()
    ngrams = data.get("ngrams", [])
    headings = data.get("headings", [])
    result = synthesize_topics(ngrams, headings)
    return jsonify(result)


# ======================================================
# 🧩 3️⃣ Endpoint: raport licznika (bez zmian)
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
# 🧩 Health
# ======================================================
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "message": "GPT N-Gram & Entity API (v7.0 semantic) działa poprawnie.",
    })


@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "version": "v7.0-semantic",
        "sentence_model": KEYBERT_MODEL_NAME
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
