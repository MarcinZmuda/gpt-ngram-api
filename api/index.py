import os
import json
import re
import requests
from collections import Counter, defaultdict
from flask import Flask, request, jsonify
try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    spacy = None
    SPACY_AVAILABLE = False
# v56.0: Removed google-generativeai — semantic keyphrases now extracted via TF-IDF (scikit-learn)
from sklearn.feature_extraction.text import TfidfVectorizer
import firebase_admin
from firebase_admin import credentials, firestore

# 🆕 v28.0: trafilatura for clean content extraction (eliminates CSS garbage)
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
    print("[S1] ✅ trafilatura loaded — clean content extraction")
except ImportError:
    TRAFILATURA_AVAILABLE = False
    print("[S1] ⚠️ trafilatura not installed — using regex fallback (may include CSS garbage)")

# ======================================================
# ⭐ v22.3 LIMITS - zapobieganie OOM
# ======================================================
MAX_CONTENT_SIZE = 30000      # Max 30KB per page (było unlimited → 175KB crash)
MAX_TOTAL_CONTENT = 200000    # Max 200KB total content
SCRAPE_TIMEOUT = 8            # 8 sekund timeout per page (było 10)
SKIP_DOMAINS = ['bip.', '.pdf', 'gov.pl/dana/', '/uploads/files/']  # Skip duże dokumenty

# ======================================================
# 🔑 SERP Provider Configuration (v55.0: DataForSEO + SerpAPI)
# ======================================================
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
if SERPAPI_KEY:
    print("[S1] ✅ SerpAPI key configured")
else:
    print("[S1] ⚠️ SERPAPI_KEY not set")

# v55.0: DataForSEO as alternative/primary SERP provider
try:
    try:
        from .dataforseo_provider import is_available as dataforseo_available, fetch_serp_data as dataforseo_fetch, fetch_raw_debug as dataforseo_debug
    except ImportError:
        from dataforseo_provider import is_available as dataforseo_available, fetch_serp_data as dataforseo_fetch, fetch_raw_debug as dataforseo_debug
    DATAFORSEO_ENABLED = dataforseo_available()
except ImportError:
    DATAFORSEO_ENABLED = False
    dataforseo_fetch = None
    dataforseo_debug = None
    print("[S1] ⚠️ dataforseo_provider module not found")

if DATAFORSEO_ENABLED:
    print("[S1] ✅ DataForSEO provider available")

# v56.2: Runtime flag — set to True when DataForSEO returns auth error (40100)
# Prevents futile retry as secondary provider in the same session
_DATAFORSEO_AUTH_FAILED = False

# SERP_PROVIDER: "dataforseo", "serpapi", or "auto" (default)
# "auto" = use DataForSEO if configured, fallback to SerpAPI
SERP_PROVIDER = os.getenv("SERP_PROVIDER", "auto").lower()
print(f"[S1] 🔧 SERP_PROVIDER={SERP_PROVIDER} (DataForSEO={'✅' if DATAFORSEO_ENABLED else '❌'}, SerpAPI={'✅' if SERPAPI_KEY else '❌'})")

# ======================================================
# 🔥 Firebase Initialization (Safe for Render & Local)
# ======================================================
if not firebase_admin._apps:
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    try:
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            print(f"[S1] ✅ Firebase initialized from credentials file: {cred_path}")
        else:
            firebase_admin.initialize_app()
            print("[S1] ✅ Firebase initialized with default credentials")
    except Exception as e:
        print(f"[S1] ⚠️ Firebase init skipped: {e}")

# ======================================================
# ⚙️ v56.0: Semantic keyphrases via TF-IDF (no external AI)
# ======================================================
print("[S1] ✅ Semantic keyphrases: TF-IDF extractor (scikit-learn)")

# ======================================================
# 🧠 Import local modules (compatible with both local and Render)
# ======================================================
try:
    from .synthesize_topics import synthesize_topics
    from .generate_compliance_report import generate_compliance_report
    from .entity_extractor import perform_entity_seo_analysis
except ImportError:
    from synthesize_topics import synthesize_topics
    from generate_compliance_report import generate_compliance_report
    from entity_extractor import perform_entity_seo_analysis

# Flag do włączania/wyłączania Entity SEO
ENTITY_SEO_ENABLED = os.getenv("ENTITY_SEO_ENABLED", "true").lower() == "true"
print(f"[S1] {'✅' if ENTITY_SEO_ENABLED else '⚠️'} Entity SEO: {'ENABLED' if ENTITY_SEO_ENABLED else 'DISABLED'}")

# 🆕 v45.0: Causal Triplet Extractor
CAUSAL_EXTRACTOR_ENABLED = False
try:
    try:
        from .causal_extractor import extract_causal_triplets, format_causal_for_agent
    except ImportError:
        from causal_extractor import extract_causal_triplets, format_causal_for_agent
    CAUSAL_EXTRACTOR_ENABLED = True
    print("[S1] ✅ Causal Triplet Extractor v1.0 enabled")
except ImportError:
    print("[S1] ℹ️ Causal Triplet Extractor not available")

# 🆕 v45.0: Gap Analyzer
GAP_ANALYZER_ENABLED = False
try:
    try:
        from .gap_analyzer import analyze_content_gaps
    except ImportError:
        from gap_analyzer import analyze_content_gaps
    GAP_ANALYZER_ENABLED = True
    print("[S1] ✅ Gap Analyzer v1.0 enabled")
except ImportError:
    print("[S1] ℹ️ Gap Analyzer not available")

app = Flask(__name__)

# ======================================================
# 🧩 Load spaCy model (preinstalled lightweight version)
# ======================================================
try:
    nlp = spacy.load("pl_core_news_sm")
    print("[S1] ✅ spaCy pl_core_news_sm loaded")
except OSError:
    from spacy.cli import download
    download("pl_core_news_sm")
    nlp = spacy.load("pl_core_news_sm")
    print("[S1] ✅ spaCy model downloaded and loaded")

# ======================================================
# ⭐ v22.3 Helper: Check if URL should be skipped
# ======================================================
def should_skip_url(url):
    """Sprawdza czy URL powinien być pominięty (duże dokumenty, PDF, BIP)."""
    url_lower = url.lower()
    for skip_pattern in SKIP_DOMAINS:
        if skip_pattern in url_lower:
            return True
    # Skip jeśli URL kończy się na rozszerzenie pliku
    if any(url_lower.endswith(ext) for ext in ['.pdf', '.doc', '.docx', '.xls', '.xlsx']):
        return True
    return False

# ======================================================
# 🧠 Helper: Semantic extraction using TF-IDF (v56.0 — replaces Gemini)
# ======================================================
# Polish stop words for TF-IDF filtering
_TFIDF_STOP_PL = [
    "i", "w", "na", "z", "do", "że", "się", "nie", "to", "jest", "za", "po",
    "od", "o", "jak", "ale", "co", "ten", "tym", "być", "może", "już", "tak",
    "gdy", "lub", "czy", "tego", "tej", "są", "dla", "ich", "przez", "jako",
    "te", "ze", "tych", "było", "ma", "przy", "które", "który", "która",
    "których", "jego", "jej", "także", "więc", "tylko", "też", "sobie",
    "bardzo", "jeszcze", "wszystko", "przed", "między", "pod", "nad", "bez",
    "oraz", "gdzie", "kiedy", "ile", "jeśli", "strona", "kliknij", "czytaj",
]

def extract_semantic_keyphrases_tfidf(text, top_n=10):
    """
    v56.0: Wyciąga frazy semantyczne z tekstu konkurencji za pomocą TF-IDF.
    Zastępuje Gemini Flash — zero zależności od zewnętrznego AI, zero hallucynacji.
    Zwraca format kompatybilny: [{"phrase": "...", "score": 0.xx}]
    """
    if not (text or "").strip():
        return []

    try:
        # Split text into pseudo-documents (paragraphs) for meaningful TF-IDF
        paragraphs = [p.strip() for p in re.split(r'\n{2,}|\.\s+', text[:15000]) if len(p.strip()) > 30]
        if len(paragraphs) < 2:
            # Fallback: split into chunks of ~200 words
            words = text[:15000].split()
            paragraphs = [" ".join(words[i:i+200]) for i in range(0, len(words), 150)]

        if not paragraphs:
            return []

        vectorizer = TfidfVectorizer(
            ngram_range=(2, 4),
            max_features=500,
            stop_words=_TFIDF_STOP_PL,
            min_df=1,
            max_df=0.95,
            token_pattern=r'(?u)\b[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{2,}\b',
        )
        tfidf_matrix = vectorizer.fit_transform(paragraphs)
        feature_names = vectorizer.get_feature_names_out()

        # Average TF-IDF across all paragraphs (important phrases appear broadly)
        avg_scores = tfidf_matrix.mean(axis=0).A1
        top_indices = avg_scores.argsort()[::-1]

        results = []
        seen_lemmas = set()
        for idx in top_indices:
            phrase = feature_names[idx]
            # Skip near-duplicates (one phrase is substring of another already added)
            lower = phrase.lower()
            if any(lower in s or s in lower for s in seen_lemmas):
                continue
            seen_lemmas.add(lower)
            score = round(min(0.95, float(avg_scores[idx]) * 3), 3)
            results.append({"phrase": phrase, "score": score})
            if len(results) >= top_n:
                break

        print(f"[S1] ✅ TF-IDF semantic keyphrases: {len(results)} extracted")
        return results
    except Exception as e:
        print(f"[S1] ❌ TF-IDF Semantic Error: {e}")
        return []

# ======================================================
# 💡 Helper: Generate Content Hints (inspiracje dla GPT)
# ======================================================
def generate_content_hints(serp_analysis, main_keyword):
    """
    Przekształca surowe dane SERP w subtelne wskazówki dla GPT.
    To są INSPIRACJE, nie twarde reguły - GPT ma je traktować jako tło.
    """
    hints = {}

    # 1️⃣ INTRO INSPIRATION - z Featured Snippet / AI Overview
    featured = serp_analysis.get("featured_snippet")
    if featured and isinstance(featured, dict) and featured.get("answer"):
        hints["intro_inspiration"] = {
            "google_promotes": featured.get("answer", "")[:500],
            "source_type": featured.get("type", "unknown"),
            "hint": "Google wyróżnia tę odpowiedź w wynikach. Rozważ napisanie lepszego/pełniejszego wstępu który naturalnie odpowiada na to samo pytanie. NIE kopiuj - napisz wartościowszą wersję."
        }

    # 2️⃣ QUESTIONS USERS ASK - z PAA
    paa = serp_analysis.get("paa_questions", [])
    if paa:
        questions = [q.get("question", "") for q in paa if isinstance(q, dict) and q.get("question")][:6]
        hints["questions_users_ask"] = {
            "questions": questions,
            "hint": "Użytkownicy często pytają o te rzeczy. Jeśli pasują do tematu, rozważ naturalne poruszenie w treści. Nie musisz odpowiadać na wszystkie - wybierz relevantne."
        }

        # Bonus: krótkie odpowiedzi jako kontekst
        qa_context = []
        for q in paa[:3]:
            if isinstance(q, dict) and q.get("question") and q.get("answer"):
                qa_context.append({
                    "q": q.get("question"),
                    "current_answer": (q.get("answer", "") or "")[:200]
                })
        if qa_context:
            hints["questions_users_ask"]["current_answers_preview"] = qa_context

    # 3️⃣ RELATED TOPICS - z Related Searches
    related = serp_analysis.get("related_searches", [])
    if related:
        hints["related_topics"] = {
            "topics": related[:8],
            "hint": "Powiązane frazy wyszukiwane przez użytkowników. Mogą naturalnie pojawić się w tekście jeśli są relevantne. Nie upychaj na siłę."
        }

    # 4️⃣ COMPETITOR INSIGHTS - z tytułów i snippetów
    titles = serp_analysis.get("competitor_titles", [])
    snippets = serp_analysis.get("competitor_snippets", [])
    if titles or snippets:
        hints["competitor_insights"] = {
            "hint": "Tak konkurencja prezentuje temat w SERP. Tylko dla orientacji - Twoje podejście może być inne i lepsze."
        }
        if titles:
            hints["competitor_insights"]["title_patterns"] = titles[:5]
        if snippets:
            hints["competitor_insights"]["description_samples"] = snippets[:3]

    # 5️⃣ STRUCTURE INSPIRATION - z H2 konkurencji
    h2_patterns = serp_analysis.get("competitor_h2_patterns", [])
    if h2_patterns:
        unique_h2 = list(dict.fromkeys(h2_patterns))[:10]
        hints["structure_inspiration"] = {
            "competitor_sections": unique_h2,
            "hint": "Przykładowe sekcje używane przez konkurencję. Twoja struktura może być inna - to tylko kontekst co inni poruszają."
        }

    # 6️⃣ META HINT - ogólna wskazówka
    hints["_meta"] = {
        "interpretation": "Te wskazówki to TŁO i INSPIRACJA, nie checklist. Artykuł ma być naturalny, wartościowy i unikalny. Używaj tych danych żeby lepiej zrozumieć intencję użytkownika, nie żeby mechanicznie odpowiadać na każdy punkt.",
        "priority": "Jakość treści > dopasowanie do SERP"
    }

    return hints

# ======================================================
# 🔍 Helper: Fetch sources from SerpAPI (FULL SERP DATA)
# ======================================================
def _generate_paa_claude_fallback(keyword: str, serp_data: dict) -> list:
    """
    v61: PAA fallback via Anthropic Haiku (primary) or OpenAI (fallback).
    Generates 5-8 PAA-style questions when both SerpAPI and DataForSEO
    return no PAA (common for Polish queries / niche topics).
    """
    # Build context from SERP data if available
    _snippets = ""
    if serp_data:
        _organic = serp_data.get("organic_results", [])[:5]
        if _organic:
            _snippets = "\n".join(
                f"- {r.get('title', '')}: {r.get('snippet', '')}"
                for r in _organic if isinstance(r, dict)
            )

    _prompt = (
        f"Dla zapytania Google \"{keyword}\" wygeneruj 6 pytań PAA (People Also Ask) "
        f"w języku polskim. Pytania powinny być naturalne, konkretne i odpowiadać "
        f"intencji wyszukiwania.\n\n"
    )
    if _snippets:
        _prompt += f"Kontekst z wyników SERP:\n{_snippets}\n\n"
    _prompt += (
        "Format: każde pytanie w osobnej linii, bez numerów, bez myślników.\n"
        "Tylko pytania, zero komentarzy."
    )

    # Try Anthropic first, then OpenAI
    raw = _paa_call_anthropic(_prompt, keyword) or _paa_call_openai(_prompt, keyword)
    if not raw:
        return []

    questions = []
    for line in raw.splitlines():
        q = line.strip().strip("-•·0123456789.)").strip()
        if q and len(q) > 10 and "?" in q:
            questions.append({
                "question": q,
                "answer": "",
                "source": "",
                "title": "",
                "generated": True,
            })
    if questions:
        print(f"[PAA_FALLBACK] ✅ Generated {len(questions)} PAA questions for '{keyword}'")
    return questions[:8]


def _paa_call_anthropic(prompt: str, keyword: str) -> str:
    """Call Anthropic Haiku for PAA generation."""
    _key = os.getenv("ANTHROPIC_API_KEY")
    if not _key:
        print(f"[PAA_FALLBACK] ℹ️ ANTHROPIC_API_KEY not set, trying OpenAI...")
        return ""
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[PAA_FALLBACK] ⚠️ Anthropic API error: {resp.status_code}")
            return ""
        content = resp.json().get("content", [])
        return content[0].get("text", "").strip() if content else ""
    except Exception as e:
        print(f"[PAA_FALLBACK] ⚠️ Anthropic PAA error: {e}")
        return ""


def _paa_call_openai(prompt: str, keyword: str) -> str:
    """Call OpenAI for PAA generation (fallback)."""
    _key = os.getenv("OPENAI_API_KEY")
    if not _key:
        print(f"[PAA_FALLBACK] ⚠️ No API key available for PAA generation ('{keyword}')")
        return ""
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4.1-mini",
                "max_tokens": 300,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[PAA_FALLBACK] ⚠️ OpenAI API error: {resp.status_code}")
            return ""
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[PAA_FALLBACK] ⚠️ OpenAI PAA error: {e}")
        return ""


def _fetch_serpapi_data(keyword, num_results=10):
    """
    v55.0: SerpAPI provider — fetches SERP metadata (PAA, AI Overview, etc.)
    Returns standardized dict + organic_results for scraping.
    """
    empty_result = {
        "paa": [],
        "featured_snippet": None,
        "ai_overview": None,
        "related_searches": [],
        "serp_titles": [],
        "serp_snippets": [],
        "organic_results": [],
    }

    if not SERPAPI_KEY:
        print("[S1] ⚠️ SerpAPI key not configured")
        return empty_result

    print(f"[S1/SerpAPI] 🔍 Fetching SERP data for: {keyword}")
    serp_response = requests.get(
        "https://serpapi.com/search",
        params={
            "q": keyword,
            "api_key": SERPAPI_KEY,
            "num": num_results,
            "hl": "pl",
            "gl": "pl",
            "no_cache": "true",
        },
        timeout=30
    )

    if serp_response.status_code != 200:
        print(f"[S1/SerpAPI] ❌ HTTP {serp_response.status_code}")
        return empty_result

    serp_data = serp_response.json()

    # Debug logging
    serp_keys = list(serp_data.keys())
    print(f"[S1/SerpAPI] 🔑 Response keys: {serp_keys}")
    if "related_questions" in serp_data:
        print(f"[S1/SerpAPI] 📋 related_questions count: {len(serp_data['related_questions'])}")
    else:
        print(f"[S1/SerpAPI] ⚠️ NO related_questions in response")
    if "ai_overview" in serp_data:
        aio_keys = list(serp_data["ai_overview"].keys()) if isinstance(serp_data["ai_overview"], dict) else "non-dict"
        print(f"[S1/SerpAPI] 🤖 ai_overview keys: {aio_keys}")
    else:
        print(f"[S1/SerpAPI] ⚠️ NO ai_overview in response")
    if "answer_box" in serp_data:
        print(f"[S1/SerpAPI] 📦 answer_box type: {serp_data['answer_box'].get('type', 'unknown')}")

    # ── AI Overview (with page_token pagination) ──
    ai_overview = None
    ai_overview_data = serp_data.get("ai_overview", {})

    if ai_overview_data and ai_overview_data.get("page_token") and not ai_overview_data.get("text_blocks"):
        try:
            page_token = ai_overview_data["page_token"]
            print(f"[S1/SerpAPI] 🔄 AI Overview requires page_token fetch...")
            aio_resp = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_ai_overview",
                    "page_token": page_token,
                    "api_key": SERPAPI_KEY,
                },
                timeout=15,
            )
            if aio_resp.status_code == 200:
                ai_overview_data = aio_resp.json().get("ai_overview", ai_overview_data)
                print(f"[S1/SerpAPI] ✅ AI Overview fetched via page_token")
            else:
                print(f"[S1/SerpAPI] ⚠️ AI Overview page_token fetch failed: {aio_resp.status_code}")
        except Exception as e:
            print(f"[S1/SerpAPI] ⚠️ AI Overview page_token error: {e}")

    if ai_overview_data:
        text_blocks = ai_overview_data.get("text_blocks", [])
        ai_text_parts = []
        for block in text_blocks:
            block_type = block.get("type", "")
            if block_type in ("paragraph", "heading"):
                snippet = block.get("snippet", "")
                if snippet:
                    ai_text_parts.append(snippet)
            elif block_type == "list":
                for item in block.get("list", []):
                    snippet = item.get("snippet", "")
                    if snippet:
                        ai_text_parts.append(f"- {snippet}")
            elif block_type == "paragraph_list":
                for item in block.get("list", []):
                    title = item.get("title", "")
                    snippet = item.get("snippet", "")
                    if title or snippet:
                        ai_text_parts.append(f"{title}: {snippet}" if title and snippet else title or snippet)

        combined_text = ai_overview_data.get("text", "") or "\n".join(ai_text_parts)
        references = ai_overview_data.get("references", []) or ai_overview_data.get("sources", [])

        if combined_text or text_blocks:
            ai_overview = {
                "text": combined_text,
                "sources": [
                    {
                        "title": ref.get("title", ""),
                        "link": ref.get("link", ""),
                        "snippet": ref.get("snippet", ""),
                        "index": ref.get("index", None),
                    }
                    for ref in references[:5]
                ],
                "text_blocks": text_blocks,
            }
            print(f"[S1/SerpAPI] ✅ AI Overview ({len(combined_text)} chars, {len(text_blocks)} blocks)")

    # ── PAA ──
    paa_questions = []
    for q in serp_data.get("related_questions", []):
        paa_questions.append({
            "question": q.get("question", ""),
            "answer": q.get("snippet", ""),
            "source": q.get("link", ""),
            "title": q.get("title", "")
        })
    if paa_questions:
        print(f"[S1/SerpAPI] ✅ {len(paa_questions)} PAA questions")

    # ── Featured Snippet ──
    featured_snippet = None
    answer_box = serp_data.get("answer_box", {})
    if answer_box:
        featured_snippet = {
            "type": answer_box.get("type", "unknown"),
            "title": answer_box.get("title", ""),
            "answer": answer_box.get("answer", "") or answer_box.get("snippet", ""),
            "source": answer_box.get("link", ""),
            "displayed_link": answer_box.get("displayed_link", "")
        }
        print(f"[S1/SerpAPI] ✅ Featured Snippet: {featured_snippet.get('type')}")

    # ── Related Searches ──
    related_searches = []
    for rs in serp_data.get("related_searches", []):
        query = rs.get("query", "")
        if query:
            related_searches.append(query)
    if related_searches:
        print(f"[S1/SerpAPI] ✅ {len(related_searches)} related searches")

    # ── v60: Refinement Chips (search intent filters at top of SERP) ──
    refinement_chips = []
    for rc in serp_data.get("refine_this_search", []):
        if isinstance(rc, dict):
            query = rc.get("query", "").strip()
            if query and len(query) > 1:
                refinement_chips.append(query)
    # Also check inline_searches (alternative SerpAPI field)
    for rc in serp_data.get("inline_searches", []):
        if isinstance(rc, dict):
            title = rc.get("title", "").strip()
            if title and title not in refinement_chips:
                refinement_chips.append(title)
    if refinement_chips:
        print(f"[S1/SerpAPI] ✅ {len(refinement_chips)} refinement chips: {refinement_chips[:6]}")

    # ── Organic Results (titles + snippets + URLs for scraping) ──
    organic_results = serp_data.get("organic_results", [])
    serp_titles = []
    serp_snippets = []
    for result in organic_results:
        title = result.get("title", "")
        snippet = result.get("snippet", "")
        if title:
            serp_titles.append(title)
        if snippet:
            serp_snippets.append(snippet)

    print(f"[S1/SerpAPI] ✅ {len(organic_results)} organic results")

    return {
        "paa": paa_questions,
        "featured_snippet": featured_snippet,
        "ai_overview": ai_overview,
        "related_searches": related_searches,
        "refinement_chips": refinement_chips,
        "serp_titles": serp_titles,
        "serp_snippets": serp_snippets,
        "organic_results": organic_results,
        "_serp_data": serp_data,  # Keep raw data for PAA fallback
    }


def fetch_serp_sources(keyword, num_results=10):
    """
    Pobiera PEŁNE dane z Google przez wybranego SERP providera:
    - Organic results (top 10 stron) + scrapuje ich pełną treść
    - PAA (People Also Ask)
    - Featured Snippet
    - Related Searches
    - Tytuły i snippety z SERP

    v55.0: Obsługuje DataForSEO (primary) i SerpAPI (fallback)
    Provider wybierany przez SERP_PROVIDER env var:
      "dataforseo" — tylko DataForSEO
      "serpapi"     — tylko SerpAPI
      "auto"        — DataForSEO jeśli skonfigurowany, fallback do SerpAPI
    """
    empty_result = {
        "sources": [],
        "paa": [],
        "featured_snippet": None,
        "ai_overview": None,
        "related_searches": [],
        "refinement_chips": [],
        "serp_titles": [],
        "serp_snippets": []
    }

    # ── v55.0: Choose SERP provider ──
    provider_used = None
    serp_metadata = None

    try:
        global _DATAFORSEO_AUTH_FAILED

        if SERP_PROVIDER == "dataforseo":
            if not DATAFORSEO_ENABLED or _DATAFORSEO_AUTH_FAILED:
                print("[S1] ❌ SERP_PROVIDER=dataforseo but DataForSEO not configured or auth failed")
                return empty_result
            serp_metadata = dataforseo_fetch(keyword, num_results=num_results)
            provider_used = "dataforseo"
            # v56.2: Detect auth failure
            if not serp_metadata.get("organic_results_raw") and not serp_metadata.get("organic_results"):
                _DATAFORSEO_AUTH_FAILED = True

        elif SERP_PROVIDER == "serpapi":
            if not SERPAPI_KEY:
                print("[S1] ❌ SERP_PROVIDER=serpapi but SERPAPI_KEY not set")
                return empty_result
            serp_metadata = _fetch_serpapi_data(keyword, num_results=num_results)
            provider_used = "serpapi"

        else:  # "auto" — try DataForSEO first, fallback to SerpAPI
            if DATAFORSEO_ENABLED and not _DATAFORSEO_AUTH_FAILED:
                print(f"[S1] 🔄 Auto-mode: trying DataForSEO first...")
                serp_metadata = dataforseo_fetch(keyword, num_results=num_results)
                provider_used = "dataforseo"
                # Check if DataForSEO returned useful data
                has_organic = bool(serp_metadata.get("organic_results_raw"))
                if not has_organic:
                    print(f"[S1] ⚠️ DataForSEO returned no organic results, falling back to SerpAPI...")
                    _DATAFORSEO_AUTH_FAILED = True
                    serp_metadata = None
                    provider_used = None

            if serp_metadata is None and SERPAPI_KEY:
                print(f"[S1] 🔄 {'Fallback' if DATAFORSEO_ENABLED else 'Using'}: SerpAPI")
                serp_metadata = _fetch_serpapi_data(keyword, num_results=num_results)
                provider_used = "serpapi"

        if serp_metadata is None:
            print("[S1] ❌ No SERP provider available (set SERPAPI_KEY or DATAFORSEO_LOGIN/PASSWORD)")
            return empty_result

        print(f"[S1] ✅ SERP data from: {provider_used}")

        # ── Extract common fields ──
        paa_questions = serp_metadata.get("paa", [])
        featured_snippet = serp_metadata.get("featured_snippet")
        ai_overview = serp_metadata.get("ai_overview")
        related_searches = serp_metadata.get("related_searches", [])
        refinement_chips = serp_metadata.get("refinement_chips", [])
        serp_titles = serp_metadata.get("serp_titles", [])
        serp_snippets = serp_metadata.get("serp_snippets", [])

        # ── v55.2: PAA/AI Overview/Snippet cascade ──
        # Jeśli primary provider nie zwrócił PAA, AI Overview lub Snippet,
        # spróbuj drugiego providera zanim fallback do Claude.
        _missing = []
        if not paa_questions:
            _missing.append("PAA")
        if not ai_overview:
            _missing.append("AIO")
        if not featured_snippet:
            _missing.append("FS")

        if _missing:
            # Determine which secondary provider to try
            _secondary = None
            _secondary_name = None
            if provider_used == "dataforseo" and SERPAPI_KEY:
                _secondary_name = "serpapi"
            elif provider_used == "serpapi" and DATAFORSEO_ENABLED:
                _secondary_name = "dataforseo"

            # v57.1: Don't skip DataForSEO for PAA cascade — empty organic
            # results ≠ auth failure. DataForSEO may still return PAA even
            # when organic results are sparse for niche queries.
            if _secondary_name == "dataforseo" and _DATAFORSEO_AUTH_FAILED:
                if "PAA" in _missing:
                    print(f"[S1] 🔄 DataForSEO auth failed for organic, but trying for PAA anyway...")
                else:
                    _secondary_name = None
                    print(f"[S1] ⚠️ Skipping DataForSEO cascade — auth already failed this session")

            if _secondary_name:
                print(f"[S1] 🔄 Missing {', '.join(_missing)} from {provider_used} — trying {_secondary_name}...")
                try:
                    if _secondary_name == "serpapi":
                        _secondary = _fetch_serpapi_data(keyword, num_results=num_results)
                    else:
                        _secondary = dataforseo_fetch(keyword, num_results=num_results)

                    if _secondary:
                        if not paa_questions:
                            _sec_paa = _secondary.get("paa", [])
                            if _sec_paa:
                                paa_questions = _sec_paa
                                print(f"[S1] ✅ PAA from {_secondary_name}: {len(_sec_paa)} questions")
                        if not ai_overview:
                            _sec_aio = _secondary.get("ai_overview")
                            if _sec_aio:
                                ai_overview = _sec_aio
                                print(f"[S1] ✅ AI Overview from {_secondary_name}")
                        if not featured_snippet:
                            _sec_fs = _secondary.get("featured_snippet")
                            if _sec_fs:
                                featured_snippet = _sec_fs
                                print(f"[S1] ✅ Featured Snippet from {_secondary_name}")
                        if not related_searches:
                            _sec_rs = _secondary.get("related_searches", [])
                            if _sec_rs:
                                related_searches = _sec_rs
                except Exception as _sec_err:
                    print(f"[S1] ⚠️ Secondary provider {_secondary_name} error: {_sec_err}")

        # ── PAA Claude fallback (if still no PAA after both providers) ──
        if not paa_questions:
            print(f"[S1] ⚠️ No PAA from any provider — generating with Claude fallback...")
            serp_data_for_fallback = serp_metadata.get("_serp_data", {})
            if not serp_data_for_fallback:
                serp_data_for_fallback = {
                    "organic_results": serp_metadata.get("organic_results_raw") or serp_metadata.get("organic_results", []),
                    "ai_overview": ai_overview,
                }
            paa_questions = _generate_paa_claude_fallback(keyword, serp_data_for_fallback)
            if paa_questions:
                print(f"[S1] ✅ Claude PAA fallback: {len(paa_questions)} questions generated")

        # ── Get organic results for scraping ──
        # DataForSEO returns organic_results_raw, SerpAPI returns organic_results
        organic_results = serp_metadata.get("organic_results") or serp_metadata.get("organic_results_raw", [])

        if not organic_results:
            print(f"[S1] ⚠️ No organic results from {provider_used}")
            return {
                "sources": [],
                "paa": paa_questions,
                "featured_snippet": featured_snippet,
                "ai_overview": ai_overview,
                "related_searches": related_searches,
                "serp_titles": serp_titles,
                "serp_snippets": serp_snippets
            }

        print(f"[S1] ✅ {len(organic_results)} organic results from {provider_used}")

        # ⭐ 6. Scrapuj PEŁNĄ treść każdej strony + strukturę H2
        # ⭐ v47.1: Parallel scraping with ThreadPoolExecutor
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time as _time

        def _scrape_one(item):
            """Scrape a single URL — runs in thread pool."""
            url = item.get("link", "")
            title = item.get("title", "")
            if not url:
                return None
            if should_skip_url(url):
                print(f"[S1] ⏭️ Skipping large doc pattern: {url[:50]}...")
                return None

            t0 = _time.time()
            try:
                page_response = requests.get(
                    url,
                    timeout=SCRAPE_TIMEOUT,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5",
                    }
                )

                if page_response.status_code != 200:
                    print(f"[S1] ⚠️ HTTP {page_response.status_code} from {url[:40]}")
                    return None

                # v52.4: Smart encoding — requests domyślnie używa ISO-8859-1 dla text/html
                # bez deklaracji charset w nagłówkach, co powoduje pojÄciem zamiast pojęciem.
                content_type = page_response.headers.get('Content-Type', '')
                if 'charset=' in content_type.lower():
                    raw_html = page_response.text  # Zaufaj zadeklarowanemu charset
                else:
                    try:
                        raw_html = page_response.content.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            raw_html = page_response.content.decode('windows-1250')
                        except UnicodeDecodeError:
                            raw_html = page_response.content.decode('utf-8', errors='replace')

                # v56.2: Wyciągnij H2 z PEŁNEGO HTML (przed truncacją)
                h2_tags = re.findall(r'<h2[^>]*>(.*?)</h2>', raw_html, re.IGNORECASE | re.DOTALL)
                h2_clean = [re.sub(r'<[^>]+>', '', h).strip() for h in h2_tags]
                h2_clean = [h for h in h2_clean if h and len(h) < 200 and not re.search(r'[{};]|webkit|moz-|flex-|align-items', h, re.IGNORECASE)]

                # v56.2: Strip boilerplate BEFORE truncation — ensures trafilatura
                # gets meaningful HTML, not 60K of <script>/<style> from <head>
                stripped_html = raw_html
                if len(stripped_html) > MAX_CONTENT_SIZE * 2:
                    print(f"[S1] ⚠️ Content too large ({len(raw_html)} chars), truncating: {url[:40]}")
                    # Strip heavy non-content tags first
                    stripped_html = re.sub(r'<script[^>]*>.*?</script>', '', stripped_html, flags=re.DOTALL | re.IGNORECASE)
                    stripped_html = re.sub(r'<style[^>]*>.*?</style>', '', stripped_html, flags=re.DOTALL | re.IGNORECASE)
                    stripped_html = re.sub(r'<svg[^>]*>.*?</svg>', '', stripped_html, flags=re.DOTALL | re.IGNORECASE)
                    stripped_html = re.sub(r'<noscript[^>]*>.*?</noscript>', '', stripped_html, flags=re.DOTALL | re.IGNORECASE)
                    stripped_html = re.sub(r'<!--.*?-->', '', stripped_html, flags=re.DOTALL)
                    # Now truncate the cleaned HTML
                    stripped_html = stripped_html[:MAX_CONTENT_SIZE * 3]

                # Ekstrakcja treści — trafilatura lub regex fallback
                content = None
                if TRAFILATURA_AVAILABLE:
                    try:
                        content = trafilatura.extract(
                            stripped_html,
                            include_comments=False,
                            include_tables=True,
                            no_fallback=False,
                            favor_precision=True
                        )
                    except Exception as e:
                        print(f"[S1] ⚠️ trafilatura failed for {url[:40]}: {e}")
                        content = None

                # Fallback: regex — strip remaining boilerplate
                if not content:
                    content = stripped_html
                    content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'<nav[^>]*>.*?</nav>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'<footer[^>]*>.*?</footer>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'<header[^>]*>.*?</header>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'<aside[^>]*>.*?</aside>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    # v56.2: Remove inline CSS/JS artifacts
                    content = re.sub(r'\{[^}]{0,500}\}', ' ', content)
                    content = re.sub(r'<[^>]+>', ' ', content)
                    content = re.sub(r'\s+', ' ', content).strip()

                content = content[:MAX_CONTENT_SIZE]
                elapsed = _time.time() - t0

                if len(content) > 500:
                    word_count = len(content.split())
                    print(f"[S1] ✅ Scraped {len(content)} chars ({word_count} words), {len(h2_clean)} H2 from {url[:40]} [{elapsed:.1f}s]")
                    return {
                        "url": url,
                        "title": title,
                        "content": content,
                        "h2_structure": h2_clean[:15],
                        "word_count": word_count
                    }
                else:
                    print(f"[S1] ⚠️ Too short content from {url[:40]}")
                    return None

            except requests.exceptions.Timeout:
                print(f"[S1] ⏱️ Timeout for {url[:40]} (>{SCRAPE_TIMEOUT}s)")
                return None
            except Exception as e:
                print(f"[S1] ⚠️ Scrape error for {url[:40]}: {e}")
                return None

        # Launch all scrapes in parallel (max 6 threads)
        scrape_targets = [r for r in organic_results[:num_results] if r.get("link")]
        t_start = _time.time()
        print(f"[S1] 🚀 Parallel scraping {len(scrape_targets)} pages...")

        sources = []
        total_content_size = 0
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_scrape_one, item): item for item in scrape_targets}
            for future in as_completed(futures):
                result = future.result()
                if result and total_content_size < MAX_TOTAL_CONTENT:
                    sources.append(result)
                    total_content_size += len(result["content"])

        t_elapsed = _time.time() - t_start
        print(f"[S1] ✅ Parallel scrape done: {len(sources)} sources ({total_content_size} chars) in {t_elapsed:.1f}s")


        return {
            "sources": sources,
            "paa": paa_questions,
            "featured_snippet": featured_snippet,
            "ai_overview": ai_overview,  # v27.0
            "related_searches": related_searches,
            "refinement_chips": refinement_chips,  # v60: Google search refinement chips
            "serp_titles": serp_titles,
            "serp_snippets": serp_snippets
        }

    except Exception as e:
        print(f"[S1] ❌ SERP fetch error ({provider_used or 'unknown'}): {e}")
        return empty_result

# ======================================================
# 🔍 Endpoint: N-gram + Semantic + SERP Analysis + Firestore Save
# ======================================================
@app.route("/api/ngram_entity_analysis", methods=["POST"])
def perform_ngram_analysis():
    data = request.get_json(force=True)
    
    # v27.0: Akceptuj zarówno "keyword" jak i "main_keyword"
    main_keyword = data.get("main_keyword") or data.get("keyword", "")
    
    sources = data.get("sources", [])
    top_n = int(data.get("top_n", 30))
    project_id = data.get("project_id")

    # ⭐ Zmienne na dodatkowe dane SERP
    paa_questions = []
    featured_snippet = None
    ai_overview = None  # v27.0: Google SGE
    related_searches = []
    refinement_chips = []  # v60: Google search refinement chips
    serp_titles = []
    serp_snippets = []
    h2_patterns = []

    # ⭐ AUTO-FETCH: Jeśli brak sources, pobierz PEŁNE dane z SerpAPI
    if not sources:
        if not main_keyword:
            return jsonify({"error": "Brak main_keyword do analizy"}), 400

        print(f"[S1] 🔄 No sources provided - auto-fetching FULL SERP data...")
        serp_result = fetch_serp_sources(main_keyword, num_results=8)  # ⭐ v22.3: Reduced from 10 to 8

        # Wyciągnij wszystkie dane z rezultatu
        sources = serp_result.get("sources", [])
        paa_questions = serp_result.get("paa", [])
        featured_snippet = serp_result.get("featured_snippet")
        ai_overview = serp_result.get("ai_overview")  # v27.0
        related_searches = serp_result.get("related_searches", [])
        refinement_chips = serp_result.get("refinement_chips", [])  # v60: Google chips
        serp_titles = serp_result.get("serp_titles", [])
        serp_snippets = serp_result.get("serp_snippets", [])

        if not sources:
            return jsonify({
                "error": f"Nie udało się pobrać źródeł z SERP ({SERP_PROVIDER})",
                "hint": "Sprawdź konfigurację SERP providera (DATAFORSEO_LOGIN/PASSWORD lub SERPAPI_KEY)",
                "main_keyword": main_keyword,
                "paa": paa_questions,
                "related_searches": related_searches
            }), 400

    print(f"[S1] 🔍 Analiza n-gramów dla: {main_keyword}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 1️⃣ NLP Statystyczne (N-gramy)
    # v52.0: LEMMA-BASED N-GRAMS + HIGH-SIGNAL SOURCES
    #
    # Problem który rozwiązujemy:
    # A) FLEKSJA: "wpływem alkoholu", "wpływu alkoholu", "wpływ alkoholu" to ta
    #    sama fraza - Surfer liczy je razem, Brajn liczył jako 3 osobne n-gramy.
    #    FIX: indeksujemy po LEMATACH (canonical form), zachowujemy najczęstszą
    #    formę powierzchniową do wyświetlania.
    #
    # B) BRAKUJĄCE FRAZY: "warunkowe umorzenie" pojawia się w related_searches /
    #    PAA / snippetach ale rzadko w treści stron (bo to krótkie strony).
    #    FIX: PAA + related_searches + snippety = "high-signal source" - niższy
    #    próg freq dla tych fraz (wystarczy 1x, nie 2x).
    # ═══════════════════════════════════════════════════════════════════════════
    ngram_presence = defaultdict(set)
    ngram_freqs = Counter()
    ngram_per_source = defaultdict(lambda: Counter())
    lemma_surface_freq = defaultdict(Counter)  # lemma_key → {surface_form: count}
    all_text_content = []

    def _lemmatize_tokens(text_content, limit=50000):
        """Zwraca dwie listy: tokeny raw i tokeny-lematy (wyrównane, tylko alfa)."""
        doc = nlp(text_content[:limit])
        raw_toks, lem_toks = [], []
        for t in doc:
            if t.is_alpha:
                raw_toks.append(t.text.lower())
                lem_toks.append(t.lemma_.lower())
        return raw_toks, lem_toks

    def _build_ngrams_for_source(raw_toks, lem_toks, src_label, src_idx):
        """Buduje n-gramy używając LEMATÓW jako klucza, surface form do wyświetlania."""
        for n in range(2, 5):
            for i in range(len(lem_toks) - n + 1):
                lemma_key = " ".join(lem_toks[i:i + n])
                surface_form = " ".join(raw_toks[i:i + n])
                ngram_freqs[lemma_key] += 1
                ngram_presence[lemma_key].add(src_label)
                ngram_per_source[lemma_key][src_idx] += 1
                lemma_surface_freq[lemma_key][surface_form] += 1

    # ── Główne źródła: scraped pages ──────────────────────────────────────────
    for src_idx, src in enumerate(sources):
        content = (src.get("content", "") or "").lower()
        if not content.strip():
            continue
        all_text_content.append(src.get("content", ""))
        src_h2 = src.get("h2_structure", [])
        if src_h2:
            # Track which source each H2 comes from for frequency counting
            for h2_item in src_h2:
                if isinstance(h2_item, str):
                    h2_patterns.append({"text": h2_item, "source_idx": src_idx})
                elif isinstance(h2_item, dict):
                    h2_item["source_idx"] = src_idx
                    h2_patterns.append(h2_item)
        raw_toks, lem_toks = _lemmatize_tokens(content)
        _build_ngrams_for_source(raw_toks, lem_toks, src.get("url", f"src_{src_idx}"), src_idx)

    # ── v52.0: High-signal sources: PAA + related searches + SERP snippets ────
    # Google sam selekcjonuje te frazy - zawierają ważne słowa kluczowe których
    # brak w krótkich stronach SERP (np. "warunkowe umorzenie", "dożywotni zakaz").
    HIGH_SIGNAL_SRC_IDX = len(sources)
    HIGH_SIGNAL_LABEL = "__google_signals__"
    high_signal_texts = []

    for paa_item in paa_questions:
        q = paa_item.get("question", "") if isinstance(paa_item, dict) else str(paa_item)
        if q:
            high_signal_texts.append(q)
    for rs in related_searches:
        q = rs if isinstance(rs, str) else (rs.get("query", "") or rs.get("text", ""))
        if q:
            high_signal_texts.append(q)
    for title in serp_titles:
        if title:
            high_signal_texts.append(title)
    for snippet in serp_snippets:
        if snippet:
            high_signal_texts.append(snippet)

    if high_signal_texts:
        combined_signal = " . ".join(high_signal_texts)
        raw_hs, lem_hs = _lemmatize_tokens(combined_signal, limit=20000)
        _build_ngrams_for_source(raw_hs, lem_hs, HIGH_SIGNAL_LABEL, HIGH_SIGNAL_SRC_IDX)
        print(f"[S1] 🎯 High-signal: {len(high_signal_texts)} tekstów (PAA+related+snippets) → dodane do n-gramów")

    # ── Resolve best surface form per lemma-key ────────────────────────────────
    lemma_to_surface = {}
    for lemma_key, surface_counts in lemma_surface_freq.items():
        lemma_to_surface[lemma_key] = surface_counts.most_common(1)[0][0]

    max_freq = max(ngram_freqs.values()) if ngram_freqs else 1
    num_sources = len(sources)
    results = []

    for ngram, freq in ngram_freqs.items():
        # v52.0: Oddzielny próg dla high-signal vs stron
        page_presence = {s for s in ngram_presence[ngram] if s != HIGH_SIGNAL_LABEL}
        page_freq = sum(
            cnt for idx, cnt in ngram_per_source[ngram].items()
            if idx != HIGH_SIGNAL_SRC_IDX
        )
        is_high_signal_only = (HIGH_SIGNAL_LABEL in ngram_presence[ngram]
                               and not page_presence)
        # Stary filtr: min 2x w stronach; nowy: high-signal przechodzi przy freq>=1
        if page_freq < 2 and not is_high_signal_only:
            continue
        # v52.0: Wyświetlamy najczęstszą formę powierzchniową, nie lemat
        display_ngram = lemma_to_surface.get(ngram, ngram)

        page_presence_set = {s for s in ngram_presence[ngram] if s != HIGH_SIGNAL_LABEL}
        freq_norm = page_freq / max_freq if max_freq else 0
        site_score = len(page_presence_set) / num_sources if num_sources else 0
        weight = round(freq_norm * 0.5 + site_score * 0.5, 4)

        # Boost: fraza zawiera główne słowo kluczowe
        if main_keyword and main_keyword.lower() in display_ngram:
            weight += 0.1
        # Boost: fraza pochodzi z high-signal source (PAA/related/snippet)
        if HIGH_SIGNAL_LABEL in ngram_presence[ngram]:
            weight += 0.08

        # v51/v52: Per-source frequency stats (Surfer-style ranges) — tylko prawdziwe strony
        per_src = ngram_per_source.get(ngram, {})
        all_counts = [per_src.get(i, 0) for i in range(num_sources)]
        non_zero = sorted([c for c in all_counts if c > 0])

        if non_zero:
            freq_min = non_zero[0]
            freq_max = non_zero[-1]
            mid = len(non_zero) // 2
            freq_median = non_zero[mid] if len(non_zero) % 2 == 1 else (non_zero[mid-1] + non_zero[mid]) // 2
        else:
            freq_min = freq_median = freq_max = 0

        results.append({
            "ngram": display_ngram,          # najczęstsza forma powierzchniowa
            "ngram_lemma": ngram,            # lemat (do dedup w keyword_counter)
            "freq": page_freq,               # tylko z prawdziwych stron
            "freq_total": freq,              # łącznie z high-signal
            "is_high_signal": is_high_signal_only,
            "weight": min(1.0, weight),
            "site_distribution": f"{len(page_presence_set)}/{num_sources}",
            "freq_per_source": all_counts,
            "freq_min": freq_min,
            "freq_median": freq_median,
            "freq_max": freq_max
        })

    results = sorted(results, key=lambda x: x["weight"], reverse=True)[:top_n]

    # 2️⃣ Semantyka (TF-IDF — v56.0, replaces Gemini Flash)
    full_text_sample = " ".join(all_text_content)[:15000]
    semantic_keyphrases = extract_semantic_keyphrases_tfidf(full_text_sample)

    # ⭐ H2 konkurencji z CZĘSTOŚCIĄ (ile stron używa danego wzorca)
    # Liczymy per source żeby H2 z 1 strony nie zdominowało przez repetycje
    h2_source_counts = {}   # h2_text → set of source indices
    for item in h2_patterns:
        if isinstance(item, dict):
            h2_text = item.get("text", item.get("h2", "")).strip()
            src_idx = item.get("source_idx", 0)
        else:
            h2_text = str(item).strip()
            src_idx = 0
        if not h2_text or len(h2_text) < 4:
            continue
        if h2_text not in h2_source_counts:
            h2_source_counts[h2_text] = set()
        h2_source_counts[h2_text].add(src_idx)

    # Sort by number of sources (descending) — most common across competitors first
    sorted_h2 = sorted(h2_source_counts.items(), key=lambda x: len(x[1]), reverse=True)
    unique_h2_patterns = [
        {"text": h2, "count": len(srcs), "sources": len(srcs)}
        for h2, srcs in sorted_h2[:30]
    ]
    print(f"[S1] 📊 H2 patterns: {len(unique_h2_patterns)} unique "
          f"(top: {unique_h2_patterns[0]['text'][:40] if unique_h2_patterns else 'none'} "
          f"x{unique_h2_patterns[0]['count'] if unique_h2_patterns else 0})")

    # ⭐ Przygotuj serp_analysis
    # v53.0: Standaryzacja — competitors zawiera title, snippet, url
    # Mapowanie snippet do competitor na podstawie pozycji w SERP
    serp_analysis_data = {
        "paa_questions": paa_questions,
        "featured_snippet": featured_snippet,
        "ai_overview": ai_overview,  # v27.0: Google SGE
        "related_searches": related_searches,
        "refinement_chips": refinement_chips,  # v60: Google search refinement chips
        "competitor_titles": serp_titles[:10],
        "competitor_snippets": serp_snippets[:10],
        "competitor_h2_patterns": unique_h2_patterns,
        # v53.0: competitors z title, snippet, url, word_count, h2_count
        "competitors": [
            {
                "url": src.get("url", ""),
                "title": src.get("title", ""),
                "snippet": serp_snippets[i] if i < len(serp_snippets) else "",
                "word_count": src.get("word_count", 0),
                "h2_count": len(src.get("h2_structure", []))
            }
            for i, src in enumerate(sources)
        ]
    }

    # v53.0: Analiza długości — recommended_length na podstawie competitors
    word_counts = [src.get("word_count", 0) for src in sources if src.get("word_count", 0) > 0]
    if word_counts:
        avg_word_count = int(sum(word_counts) / len(word_counts))
        median_idx = len(word_counts) // 2
        sorted_wc = sorted(word_counts)
        median_word_count = sorted_wc[median_idx] if len(sorted_wc) % 2 == 1 else (sorted_wc[median_idx - 1] + sorted_wc[median_idx]) // 2
        recommended_length = int(avg_word_count * 1.1)  # 10% więcej niż średnia
    else:
        avg_word_count = 0
        median_word_count = 0
        recommended_length = 0

    length_analysis = {
        "recommended": recommended_length,
        "avg_competitor": avg_word_count,
        "median_competitor": median_word_count,
        "min_competitor": min(word_counts) if word_counts else 0,
        "max_competitor": max(word_counts) if word_counts else 0,
        "competitors_count": len(word_counts),
    }

    # 3️⃣ Content Hints - WYŁĄCZONE v28.0 (duplikuje dane z serp_analysis)
    # content_hints = generate_content_hints(serp_analysis_data, main_keyword)

    # 4️⃣ 🆕 Entity SEO Analysis (v28.0)
    entity_seo_data = None
    if ENTITY_SEO_ENABLED and sources:
        try:
            print(f"[S1] 🧠 Running Entity SEO analysis...")
            entity_seo_data = perform_entity_seo_analysis(
                nlp=nlp,
                sources=sources,
                main_keyword=main_keyword,
                h2_patterns=unique_h2_patterns
            )
            print(f"[S1] ✅ Entity SEO: {entity_seo_data.get('entity_seo_summary', {}).get('total_entities', 0)} entities found")
        except Exception as e:
            print(f"[S1] ⚠️ Entity SEO error (non-critical): {e}")
            entity_seo_data = {"error": str(e), "status": "FAILED"}

    # 5️⃣ 🆕 Causal Triplet Extraction (v45.0)
    causal_data = None
    if CAUSAL_EXTRACTOR_ENABLED and sources:
        try:
            print(f"[S1] 🔗 Running Causal Triplet Extraction...")
            causal_triplets = extract_causal_triplets(
                texts=[s.get("content", "") for s in sources],
                main_keyword=main_keyword
            )
            # v53.0: Standaryzacja — chains zawierają cause/mechanism/effect,
            # singles zawierają cause/effect (bez mechanism)
            causal_chains = []
            for t in causal_triplets:
                if t.is_chain:
                    causal_chains.append({
                        "cause": t.cause,
                        "mechanism": t.relation_type,
                        "effect": t.effect,
                        "confidence": t.confidence,
                        "source_sentence": t.source_sentence,
                    })
            causal_singles = []
            for t in causal_triplets:
                if not t.is_chain:
                    causal_singles.append({
                        "cause": t.cause,
                        "effect": t.effect,
                        "confidence": t.confidence,
                        "source_sentence": t.source_sentence,
                    })
            causal_data = {
                "count": len(causal_triplets),
                "chains": causal_chains,
                "singles": causal_singles,
                "agent_instruction": format_causal_for_agent(causal_triplets, main_keyword)
            }
            print(f"[S1] ✅ Causal Triplets: {len(causal_triplets)} found "
                  f"({sum(1 for t in causal_triplets if t.is_chain)} chains)")
        except Exception as e:
            print(f"[S1] ⚠️ Causal extraction error (non-critical): {e}")
            causal_data = {"error": str(e), "status": "FAILED"}

    # 6️⃣ 🆕 Content Gap Analysis (v45.0)
    content_gaps_data = None
    if GAP_ANALYZER_ENABLED and sources:
        try:
            print(f"[S1] 📊 Running Gap Analysis...")
            # v53.0: Przekaż H2 jako listę stringów (gap_analyzer oczekuje list of str)
            h2_texts = [
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in unique_h2_patterns
            ]
            raw_gaps = analyze_content_gaps(
                competitor_texts=[s.get("content", "") for s in sources],
                competitor_h2s=h2_texts,
                paa_questions=paa_questions,
                related_searches=related_searches,
                main_keyword=main_keyword
            )
            # v53.0: Standaryzacja — dodaj flat string lists obok pełnych obiektów
            content_gaps_data = {
                "total_gaps": raw_gaps.get("total_gaps", 0),
                "suggested_new_h2s": raw_gaps.get("suggested_new_h2s", []),
                "paa_unanswered": [
                    g.get("topic", "") for g in raw_gaps.get("paa_unanswered", [])
                ],
                "subtopic_missing": [
                    g.get("topic", "") for g in raw_gaps.get("subtopic_missing", [])
                ],
                "depth_missing": [
                    g.get("topic", "") for g in raw_gaps.get("depth_missing", [])
                ],
                "instruction": raw_gaps.get("agent_instruction", ""),
                # Zachowaj pełne obiekty dla kompatybilności
                "all_gaps": raw_gaps.get("all_gaps", []),
                "status": raw_gaps.get("status", "OK"),
            }
            print(f"[S1] ✅ Content Gaps: {content_gaps_data.get('total_gaps', 0)} gaps found")
        except Exception as e:
            print(f"[S1] ⚠️ Gap Analysis error (non-critical): {e}")
            content_gaps_data = {"error": str(e), "status": "FAILED"}

    # ⭐ PEŁNA ODPOWIEDŹ z wszystkimi danymi SERP
    # v53.0: Standaryzacja — ujednolicone pola, aliasy dla kompatybilności
    response_payload = {
        "main_keyword": main_keyword,
        "ngrams": results,
        "semantic_keyphrases": semantic_keyphrases,

        # ✅ NOWE (MINIMALNA ZMIANA): zwracamy próbkę pełnych treści konkurencji,
        # aby Master API mogło liczyć semantic coverage na realnym korpusie.
        # Zachowujemy kompatybilność wsteczną przez alias "serp_content".
        "full_text_sample": full_text_sample,
        "serp_content": full_text_sample,

        # ⭐ Pełna analiza SERP (surowe dane)
        "serp_analysis": serp_analysis_data,

        # v53.0: Top-level PAA alias (ZAWSZE obecny, wskazuje na serp_analysis.paa_questions)
        "paa": paa_questions,

        # v53.0: Analiza długości (recommended_length + dane kompetytorów)
        "length_analysis": length_analysis,
        "recommended_length": recommended_length,

        # v53.0: Top-level H2 patterns alias
        "competitor_h2_patterns": unique_h2_patterns,

        # 🆕 Entity SEO (v28.0)
        "entity_seo": entity_seo_data,

        # 🆕 Causal Triplets (v45.0, v53.0: standaryzacja chains/singles)
        "causal_triplets": causal_data,

        # 🆕 Content Gaps (v45.0, v53.0: flat string lists + instruction)
        "content_gaps": content_gaps_data,

        "summary": {
            "total_sources": len(sources),
            "sources_auto_fetched": not bool(data.get("sources", [])),
            "paa_count": len(paa_questions),
            "has_featured_snippet": featured_snippet is not None,
            "has_ai_overview": ai_overview is not None,
            "related_searches_count": len(related_searches),
            "h2_patterns_found": len(unique_h2_patterns),
            "entity_seo_enabled": ENTITY_SEO_ENABLED,
            "entities_found": entity_seo_data.get("entity_seo_summary", {}).get("total_entities", 0) if entity_seo_data else 0,
            "causal_triplets_found": causal_data.get("count", 0) if causal_data else 0,
            "content_gaps_found": content_gaps_data.get("total_gaps", 0) if content_gaps_data else 0,
            "recommended_length": recommended_length,
            "engine": "v56.2",
            "lsi_candidates": len(semantic_keyphrases),
        }
    }

    # 3️⃣ Firestore Save (optional)
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
# v53.0: /api/s1_analysis — Alias for /api/ngram_entity_analysis
# Frontend oczekuje tego endpointu pod tą nazwą
# ======================================================
@app.route("/api/s1_analysis", methods=["POST"])
def perform_s1_analysis():
    """Alias — deleguje do perform_ngram_analysis."""
    return perform_ngram_analysis()

# ======================================================
# v54.0: GET /api/debug/serpapi?keyword=...
# Diagnostyczny endpoint — zwraca surowy JSON z SerpAPI
# żeby zobaczyć co dokładnie przychodzi (PAA, AI Overview, etc.)
# ======================================================
@app.route("/api/debug/serpapi", methods=["GET"])
def debug_serpapi():
    keyword = request.args.get("keyword", "")
    if not keyword:
        return jsonify({"error": "Podaj ?keyword=..."}), 400
    if not SERPAPI_KEY:
        return jsonify({"error": "SERPAPI_KEY not configured"}), 500

    try:
        resp = requests.get(
            "https://serpapi.com/search",
            params={
                "q": keyword,
                "api_key": SERPAPI_KEY,
                "num": 8,
                "hl": "pl",
                "gl": "pl",
                "no_cache": "true",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return jsonify({"error": f"SerpAPI HTTP {resp.status_code}", "body": resp.text[:500]}), 502

        raw = resp.json()

        # Zwróć diagnostykę — surowe klucze + interesujące sekcje
        diag = {
            "keyword": keyword,
            "all_keys": list(raw.keys()),
            "has_related_questions": "related_questions" in raw,
            "related_questions_count": len(raw.get("related_questions", [])),
            "related_questions": raw.get("related_questions", []),
            "has_ai_overview": "ai_overview" in raw,
            "ai_overview_keys": list(raw["ai_overview"].keys()) if isinstance(raw.get("ai_overview"), dict) else None,
            "ai_overview_has_page_token": bool(raw.get("ai_overview", {}).get("page_token")) if isinstance(raw.get("ai_overview"), dict) else False,
            "ai_overview": raw.get("ai_overview"),
            "has_answer_box": "answer_box" in raw,
            "answer_box": raw.get("answer_box"),
            "has_related_searches": "related_searches" in raw,
            "related_searches": raw.get("related_searches", []),
            "organic_results_count": len(raw.get("organic_results", [])),
            "organic_titles": [r.get("title", "") for r in raw.get("organic_results", [])[:5]],
        }
        return jsonify(diag)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ======================================================
# v55.0: GET /api/debug/dataforseo?keyword=...
# Diagnostyczny endpoint — zwraca surowy JSON z DataForSEO
# ======================================================
@app.route("/api/debug/dataforseo", methods=["GET"])
def debug_dataforseo():
    keyword = request.args.get("keyword", "")
    if not keyword:
        return jsonify({"error": "Podaj ?keyword=..."}), 400
    if not DATAFORSEO_ENABLED:
        return jsonify({"error": "DataForSEO not configured (set DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD)"}), 500

    try:
        diag = dataforseo_debug(keyword)
        return jsonify(diag)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ======================================================
# 🧩 Pozostałe Endpointy (Proxy)
# ======================================================
@app.route("/api/synthesize_topics", methods=["POST"])
def perform_synthesize_topics():
    data = request.get_json(force=True)
    ngrams = data.get("ngrams", [])

    # ✅ NOWE (MINIMALNA ZMIANA): obsługa listy dictów {ngram: "..."} dla kompatybilności.
    if isinstance(ngrams, list) and ngrams and isinstance(ngrams[0], dict):
        ngrams = [x.get("ngram", "") for x in ngrams if isinstance(x, dict) and x.get("ngram")]

    return jsonify(synthesize_topics(ngrams, data.get("headings", [])))

@app.route("/api/generate_compliance_report", methods=["POST"])
def perform_generate_compliance_report():
    data = request.get_json(force=True)
    return jsonify(generate_compliance_report(data.get("text", ""), data.get("keyword_state", {})))

# ======================================================
# v53.0: Global JSON Error Handlers
# NIGDY nie zwracaj HTML error pages — ZAWSZE Content-Type: application/json
# ======================================================
@app.errorhandler(400)
def handle_400(e):
    return jsonify({"error": "Bad Request", "details": str(e)}), 400

@app.errorhandler(404)
def handle_404(e):
    return jsonify({"error": "Not Found", "details": str(e)}), 404

@app.errorhandler(405)
def handle_405(e):
    return jsonify({"error": "Method Not Allowed", "details": str(e)}), 405

@app.errorhandler(500)
def handle_500(e):
    return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    print(f"[ERROR] Unhandled exception: {e}")
    return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "engine": "v56.2",
        "limits": {
            "max_content_per_page": MAX_CONTENT_SIZE,
            "max_total_content": MAX_TOTAL_CONTENT,
            "scrape_timeout": SCRAPE_TIMEOUT,
            "skip_domains": SKIP_DOMAINS
        },
        "features": {
            "tfidf_semantic_enabled": True,
            "serpapi_enabled": bool(SERPAPI_KEY),
            "dataforseo_enabled": DATAFORSEO_ENABLED,
            "serp_provider": SERP_PROVIDER,
            "paa_extraction": True,
            "featured_snippet_extraction": True,
            "ai_overview_extraction": True,
            "related_searches_extraction": True,
            "competitor_h2_analysis": True,
            "competitor_word_count": True,
            "full_content_scraping": True,
            "oom_protection": True,
            "keyword_alias_support": True,
            # v28.0: Entity SEO
            "entity_seo_enabled": ENTITY_SEO_ENABLED,
            "entity_extraction": ENTITY_SEO_ENABLED,
            "topical_coverage": ENTITY_SEO_ENABLED,
            "entity_relationships": ENTITY_SEO_ENABLED,
            # v28.0: content_hints WYŁĄCZONE (BRAJEN używa serp_analysis)
            "content_hints_generation": False,
            # v45.0: Causal Triplets + Gap Analysis
            "causal_triplets_enabled": CAUSAL_EXTRACTOR_ENABLED,
            "gap_analysis_enabled": GAP_ANALYZER_ENABLED,
            # v53.0
            "s1_analysis_alias": True,
            "json_error_handlers": True,
        }
    })

# ======================================================
# 🧩 Uruchomienie lokalne
# ======================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
