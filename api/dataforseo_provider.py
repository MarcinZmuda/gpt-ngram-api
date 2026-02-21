# ================================================================
# v55.0: DataForSEO SERP Provider
# Alternative to SerpAPI — deeper PAA (4 levels), async AI Overview,
# cheaper at scale ($0.002/req live vs ~$2.75/1K on SerpAPI)
# ================================================================
import os
import json
import base64
import requests

DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.getenv("DATAFORSEO_PASSWORD")

# Pre-compute auth header once at import time
_DATAFORSEO_AUTH = None
if DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD:
    _creds = base64.b64encode(f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()).decode()
    _DATAFORSEO_AUTH = f"Basic {_creds}"
    print("[DataForSEO] ✅ Credentials configured")
else:
    print("[DataForSEO] ⚠️ DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD not set")


def is_available():
    """Check if DataForSEO credentials are configured."""
    return _DATAFORSEO_AUTH is not None


def fetch_serp_data(keyword, num_results=10, location_code=2616, language_code="pl"):
    """
    Fetch SERP data from DataForSEO Live Advanced endpoint.

    Returns dict with the SAME structure as SerpAPI-based fetch_serp_sources():
    {
        "sources": [],        # Empty — scraping is done by caller
        "paa": [...],
        "featured_snippet": {...} or None,
        "ai_overview": {...} or None,
        "related_searches": [...],
        "serp_titles": [...],
        "serp_snippets": [...],
        "organic_results_raw": [...],  # Raw organic results for caller to scrape
        "_provider": "dataforseo",
        "_raw_items_count": int,
    }

    Args:
        keyword: Search query
        num_results: Number of organic results to fetch (default 10)
        location_code: DataForSEO location code (2616 = Poland)
        language_code: Language code (default "pl")
    """
    empty_result = {
        "sources": [],
        "paa": [],
        "featured_snippet": None,
        "ai_overview": None,
        "related_searches": [],
        "serp_titles": [],
        "serp_snippets": [],
        "organic_results_raw": [],
        "_provider": "dataforseo",
    }

    if not _DATAFORSEO_AUTH:
        print("[DataForSEO] ❌ Not configured — cannot fetch")
        return empty_result

    try:
        print(f"[DataForSEO] 🔍 Fetching SERP for: {keyword}")

        payload = [
            {
                "keyword": keyword,
                "location_code": location_code,
                "language_code": language_code,
                "depth": num_results,
                "se_domain": "google.pl",
                "people_also_ask_click_depth": 4,
                "expand_ai_overview": True,
            }
        ]

        resp = requests.post(
            "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
            headers={
                "Authorization": _DATAFORSEO_AUTH,
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=30,
        )

        if resp.status_code != 200:
            print(f"[DataForSEO] ❌ HTTP {resp.status_code}: {resp.text[:300]}")
            return empty_result

        data = resp.json()

        # DataForSEO wraps everything in tasks[0].result[0]
        status_code = data.get("status_code")
        if status_code != 20000:
            msg = data.get("status_message", "unknown")
            print(f"[DataForSEO] ❌ API error {status_code}: {msg}")
            return empty_result

        tasks = data.get("tasks", [])
        if not tasks:
            print("[DataForSEO] ❌ No tasks in response")
            return empty_result

        task = tasks[0]
        task_status = task.get("status_code")
        if task_status != 20000:
            print(f"[DataForSEO] ❌ Task error {task_status}: {task.get('status_message')}")
            return empty_result

        results = task.get("result", [])
        if not results:
            print("[DataForSEO] ❌ No results in task")
            return empty_result

        result = results[0]
        items = result.get("items", [])
        item_types = result.get("item_types", [])

        print(f"[DataForSEO] 📦 Got {len(items)} items, types: {item_types}")

        # Parse items by type
        paa_questions = []
        featured_snippet = None
        ai_overview = None
        related_searches = []
        serp_titles = []
        serp_snippets = []
        organic_results_raw = []

        for item in items:
            item_type = item.get("type", "")

            # ── Organic Results ──
            if item_type == "organic":
                title = item.get("title", "")
                snippet = item.get("description", "")
                url = item.get("url", "")
                if title:
                    serp_titles.append(title)
                if snippet:
                    serp_snippets.append(snippet)
                organic_results_raw.append({
                    "link": url,
                    "title": title,
                    "snippet": snippet,
                    "position": item.get("rank_absolute", 0),
                })

            # ── People Also Ask ──
            elif item_type == "people_also_ask":
                paa_items = item.get("items", [])
                for paa_item in paa_items:
                    question = paa_item.get("title", "")
                    # DataForSEO nests answer in expanded_element
                    expanded = paa_item.get("expanded_element", [])
                    answer = ""
                    source_url = paa_item.get("url", "")
                    source_title = ""

                    for elem in expanded:
                        elem_type = elem.get("type", "")
                        if elem_type == "people_also_ask_expanded_element":
                            answer = elem.get("description", "") or elem.get("featured_title", "")
                            if not source_url:
                                source_url = elem.get("url", "")
                            source_title = elem.get("title", "")
                        elif elem_type == "people_also_ask_ai_overview_expanded_element":
                            # AI Overview embedded in PAA — extract text
                            aio_desc = elem.get("description", "")
                            if aio_desc and not answer:
                                answer = aio_desc

                    # Fallback: use description directly if no expanded_element
                    if not answer:
                        answer = paa_item.get("description", "")

                    if question:
                        paa_questions.append({
                            "question": question,
                            "answer": answer,
                            "source": source_url,
                            "title": source_title,
                        })

                    # Recurse into nested PAA (click_depth > 1)
                    nested_paa = paa_item.get("items", [])
                    for nested in nested_paa:
                        nq = nested.get("title", "")
                        n_expanded = nested.get("expanded_element", [])
                        n_answer = ""
                        n_url = nested.get("url", "")
                        n_title = ""
                        for ne in n_expanded:
                            if ne.get("type") == "people_also_ask_expanded_element":
                                n_answer = ne.get("description", "") or ne.get("featured_title", "")
                                if not n_url:
                                    n_url = ne.get("url", "")
                                n_title = ne.get("title", "")
                        if not n_answer:
                            n_answer = nested.get("description", "")
                        if nq:
                            paa_questions.append({
                                "question": nq,
                                "answer": n_answer,
                                "source": n_url,
                                "title": n_title,
                            })

            # ── Featured Snippet ──
            elif item_type == "featured_snippet":
                fs_desc = item.get("description", "")
                fs_title = item.get("title", "")
                fs_url = item.get("url", "")
                featured_snippet = {
                    "type": item.get("featured_snippet", {}).get("type", "paragraph") if isinstance(item.get("featured_snippet"), dict) else "paragraph",
                    "title": fs_title,
                    "answer": fs_desc,
                    "source": fs_url,
                    "displayed_link": item.get("breadcrumb", ""),
                }

            # ── AI Overview ──
            elif item_type == "ai_overview":
                ai_items = item.get("items", [])
                text_blocks = []
                ai_text_parts = []
                references = []

                for ai_item in ai_items:
                    ai_item_type = ai_item.get("type", "")

                    if ai_item_type == "paragraph":
                        text = ai_item.get("text", "")
                        if text:
                            ai_text_parts.append(text)
                            text_blocks.append({
                                "type": "paragraph",
                                "snippet": text,
                            })
                    elif ai_item_type == "table":
                        # Serialize table to text
                        table_content = ai_item.get("text", "")
                        if table_content:
                            ai_text_parts.append(table_content)
                            text_blocks.append({
                                "type": "paragraph",
                                "snippet": table_content,
                            })
                    elif ai_item_type == "list":
                        list_items = ai_item.get("items", [])
                        list_texts = []
                        for li in list_items:
                            li_text = li.get("text", "") or li.get("title", "")
                            if li_text:
                                list_texts.append(li_text)
                                ai_text_parts.append(f"- {li_text}")
                        if list_texts:
                            text_blocks.append({
                                "type": "list",
                                "list": [{"snippet": t} for t in list_texts],
                            })

                # Extract references from ai_overview
                refs_raw = item.get("references", [])
                for ref in refs_raw:
                    references.append({
                        "title": ref.get("title", ""),
                        "link": ref.get("url", ""),
                        "snippet": ref.get("description", ""),
                        "index": ref.get("position", None),
                    })

                combined_text = "\n".join(ai_text_parts)

                if combined_text or text_blocks:
                    ai_overview = {
                        "text": combined_text,
                        "sources": references[:5],
                        "text_blocks": text_blocks,
                    }
                    print(f"[DataForSEO] ✅ AI Overview: {len(combined_text)} chars, "
                          f"{len(text_blocks)} blocks, {len(references)} refs")

            # ── Related Searches ──
            elif item_type == "related_searches":
                rs_items = item.get("items", [])
                for rs in rs_items:
                    query = rs.get("title", "")
                    if query:
                        related_searches.append(query)

        # Log summary
        print(f"[DataForSEO] ✅ Parsed: {len(organic_results_raw)} organic, "
              f"{len(paa_questions)} PAA, "
              f"FS={'yes' if featured_snippet else 'no'}, "
              f"AIO={'yes' if ai_overview else 'no'}, "
              f"{len(related_searches)} related")

        return {
            "sources": [],  # Scraping done by caller
            "paa": paa_questions,
            "featured_snippet": featured_snippet,
            "ai_overview": ai_overview,
            "related_searches": related_searches,
            "serp_titles": serp_titles,
            "serp_snippets": serp_snippets,
            "organic_results_raw": organic_results_raw,
            "_provider": "dataforseo",
            "_raw_items_count": len(items),
        }

    except requests.exceptions.Timeout:
        print("[DataForSEO] ⏱️ Request timeout (>30s)")
        return empty_result
    except Exception as e:
        print(f"[DataForSEO] ❌ Fetch error: {e}")
        return empty_result


def fetch_raw_debug(keyword, location_code=2616, language_code="pl"):
    """
    Diagnostic: return raw DataForSEO response for debugging.
    Used by /api/debug/dataforseo endpoint.
    """
    if not _DATAFORSEO_AUTH:
        return {"error": "DataForSEO not configured"}

    payload = [
        {
            "keyword": keyword,
            "location_code": location_code,
            "language_code": language_code,
            "depth": 10,
            "se_domain": "google.pl",
            "people_also_ask_click_depth": 4,
            "expand_ai_overview": True,
        }
    ]

    resp = requests.post(
        "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
        headers={
            "Authorization": _DATAFORSEO_AUTH,
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=30,
    )

    raw = resp.json()

    # Extract diagnostic info
    tasks = raw.get("tasks", [])
    task = tasks[0] if tasks else {}
    results = task.get("result", [])
    result = results[0] if results else {}
    items = result.get("items", [])

    item_types_count = {}
    for it in items:
        t = it.get("type", "unknown")
        item_types_count[t] = item_types_count.get(t, 0) + 1

    # Find PAA items
    paa_items = []
    for it in items:
        if it.get("type") == "people_also_ask":
            paa_items = it.get("items", [])
            break

    # Find AI Overview
    aio_item = None
    for it in items:
        if it.get("type") == "ai_overview":
            aio_item = it
            break

    return {
        "keyword": keyword,
        "status_code": raw.get("status_code"),
        "status_message": raw.get("status_message"),
        "cost": raw.get("cost"),
        "task_status": task.get("status_code"),
        "total_items": len(items),
        "item_types": item_types_count,
        "has_people_also_ask": "people_also_ask" in [i.get("type") for i in items],
        "paa_count": len(paa_items),
        "paa_questions": [p.get("title", "") for p in paa_items[:10]],
        "has_ai_overview": aio_item is not None,
        "ai_overview_items_count": len(aio_item.get("items", [])) if aio_item else 0,
        "ai_overview_refs_count": len(aio_item.get("references", [])) if aio_item else 0,
        "has_featured_snippet": "featured_snippet" in [i.get("type") for i in items],
        "has_related_searches": "related_searches" in [i.get("type") for i in items],
        "organic_count": sum(1 for i in items if i.get("type") == "organic"),
        "organic_titles": [i.get("title", "") for i in items if i.get("type") == "organic"][:5],
    }
