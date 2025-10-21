import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from collections import Counter
import spacy

# ==============================================================
# 🔧 KONFIGURACJA I INICJALIZACJA
# ==============================================================

load_dotenv()
app = Flask(__name__)
CORS(app)

# 🔑 Klucze i adresy
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
SERPAPI_URL = os.getenv("SERPAPI_URL", "https://serpapi.com/search.json")
LANGEXTRACT_API_URL = os.getenv("LANGEXTRACT_API_URL", "https://langextract-api.onrender.com/extract")

# Model językowy Spacy (PL)
try:
    nlp = spacy.load("pl_core_news_sm")
    print("✅ Załadowano model językowy Spacy (pl_core_news_sm)")
except Exception as e:
    print(f"❌ Błąd ładowania modelu Spacy: {e}")
    nlp = None


# ==============================================================
# 🧠 HELPERY
# ==============================================================

def call_serpapi(topic):
    """Wywołanie SerpAPI – pobiera top 5 wyników, PAA, powiązane wyszukiwania, sugestie, snippet i AI Overview."""
    try:
        params = {
            "engine": "google",
            "q": topic,
            "gl": "pl",
            "hl": "pl",
            "api_key": SERPAPI_KEY
        }
        r = requests.get(SERPAPI_URL, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ Błąd SerpAPI: {e}")
        return None


def call_langextract(url):
    """Pobiera tekst strony z LangExtract API."""
    try:
        r = requests.post(LANGEXTRACT_API_URL, json={"url": url}, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ Błąd LangExtract dla {url}: {e}")
        return None


def extract_ngrams(text, n_values=[2, 3, 4]):
    """Generuje n-gramy (2–4) z tekstu i zwraca najczęstsze frazy."""
    if not nlp:
        return {"error": "Model językowy Spacy nie został załadowany."}

    doc = nlp(text.lower())
    tokens = [t.lemma_ for t in doc if t.is_alpha and not t.is_stop]
    ngram_map = {}

    for n in n_values:
        grams = Counter([" ".join(tokens[i:i+n]) for i in range(len(tokens)-n+1)])
        ngram_map[f"{n}gram"] = dict(grams.most_common(50))

    return ngram_map


def prioritize_ngrams(ngrams, paa_list, related_list, suggestions, snippets_text, ai_overview_text):
    """Nadaje priorytety n-gramom na podstawie dopasowań do PAA, related searches, suggestions, snippetów i AI Overview."""
    def match_score(ngram):
        score = 0
        lower_ngram = ngram.lower()
        if any(lower_ngram in q.lower() for q in paa_list): score += 3
        if any(lower_ngram in q.lower() for q in related_list): score += 2
        if any(lower_ngram in q.lower() for q in suggestions): score += 1
        if snippets_text and lower_ngram in snippets_text.lower(): score += 2
        if ai_overview_text and lower_ngram in ai_overview_text.lower(): score += 2
        return score

    all_ngrams = []
    for n_key, n_values in ngrams.items():
        for phrase, freq in n_values.items():
            priority = freq + match_score(phrase)
            all_ngrams.append({"phrase": phrase, "priority": priority, "length": n_key})

    all_ngrams = sorted(all_ngrams, key=lambda x: x["priority"], reverse=True)
    return all_ngrams[:10]


# ==============================================================
# 🧭 ENDPOINTY
# ==============================================================

@app.route("/api/s1_analysis", methods=["POST"])
def perform_s1_analysis():
    """Etap S1 – analiza SERP i n-gramów z priorytetami."""
    data = request.get_json()
    topic = data.get("topic", "")
    return_all_ngrams = data.get("return_all_ngrams", False)

    if not topic:
        return jsonify({"error": "Brak tematu (topic)"}), 400
    if not SERPAPI_KEY:
        return jsonify({"error": "Brak klucza SERPAPI_KEY"}), 500

    serp_data = call_serpapi(topic)
    if not serp_data:
        return jsonify({"error": "Błąd pobierania danych z SerpAPI"}), 502

    # 🔹 Zbieramy dane SERP
    organic_results = serp_data.get("organic_results", [])
    top_urls = [r.get("link") for r in organic_results[:5] if r.get("link")]

    # SERP features
    paa_list = [p.get("question") for p in serp_data.get("related_questions", []) if p.get("question")]
    related_searches = [r.get("query") for r in serp_data.get("related_searches", []) if r.get("query")]
    suggestions = [s for s in serp_data.get("suggested_searches", []) if isinstance(s, str)]
    ai_overview_text = serp_data.get("ai_overview", {}).get("content", "")
    snippet_data = serp_data.get("answer_box") or serp_data.get("featured_snippet")
    snippets_text = snippet_data.get("snippet", "") if isinstance(snippet_data, dict) else ""

    # 🔹 Pobranie treści stron
    combined_text = ""
    extraction_log = []
    for url in top_urls:
        content = call_langextract(url)
        if content and content.get("content"):
            combined_text += content["content"] + "\n"
            extraction_log.append({"url": url, "status": "success"})
        else:
            extraction_log.append({"url": url, "status": "failed"})

    if not combined_text.strip():
        return jsonify({"error": "Nie udało się pobrać treści z żadnego źródła"}), 502

    # 🔹 Generujemy n-gramy
    ngram_map = extract_ngrams(combined_text)

    # 🔹 Nadajemy priorytety (z uwzględnieniem Snippetów i AI Overview)
    prioritized = prioritize_ngrams(
        ngram_map, paa_list, related_searches, suggestions, snippets_text, ai_overview_text
    )

    # 🔹 Encje z tekstu
    doc = nlp(combined_text)
    entities = list({ent.text for ent in doc.ents if len(ent.text) > 2})

    # 🔹 Finalna odpowiedź
    response = {
        "topic": topic,
        "urls": top_urls,
        "paa_questions": paa_list,
        "related_searches": related_searches,
        "suggestions": suggestions,
        "entities": entities,
        "ngrams_prioritized": prioritized,
        "extraction_report": extraction_log,
        "serp_features": {
            "ai_overview": ai_overview_text,
            "featured_snippet": snippets_text,
        }
    }

    if return_all_ngrams:
        response["ngrams_all"] = ngram_map

    return jsonify(response)


@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"status": "✅ Unified SEO API działa poprawnie", "version": "v3.2.0"}), 200


# ==============================================================
# 🚀 URUCHOMIENIE
# ==============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🌍 Uruchamianie Unified SEO API v3.2.0 na porcie {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
