import re
import logging

logger = logging.getLogger(__name__)


def _legacy_hierarchical_keyword_counter(raw_counts):
    """
    Legacy algorithm: Oblicza hierarchiczne zliczanie fraz kluczowych.
    Jeśli krótsze słowo występuje w dłuższym (np. 'rozwód' w 'rozwód warszawa'),
    liczba jego wystąpień zostaje zwiększona o liczbę wystąpień dłuższej frazy.

    Parametry:
        raw_counts (dict): np. {"rozwód": 3, "rozwód warszawa": 2}

    Zwraca:
        dict: {"rozwód": 5, "rozwód warszawa": 2}
    """

    if not isinstance(raw_counts, dict):
        return {"error": "'raw_counts' must be a dictionary."}

    # Sortujemy frazy od najdłuższej do najkrótszej
    keywords = sorted(raw_counts.keys(), key=len, reverse=True)
    hierarchical_counts = raw_counts.copy()

    # Dla każdej frazy sprawdzamy, czy zawiera krótszą
    for i, long_kw in enumerate(keywords):
        for short_kw in keywords[i + 1:]:
            if short_kw in long_kw and re.search(r'\b' + re.escape(short_kw) + r'\b', long_kw):
                hierarchical_counts[short_kw] += raw_counts.get(long_kw, 0)

    return {"hierarchical_counts": hierarchical_counts}


def hierarchical_keyword_counter(raw_counts):
    """
    FIX #14 + #22: Unified keyword counter with proxy fallback.

    Strategy:
    1. Try to call master-seo-api /api/count_keywords_inherited (proxy)
    2. Fallback to _legacy_hierarchical (original algorithm preserved)

    Parametry:
        raw_counts (dict): np. {"rozwód": 3, "rozwód warszawa": 2}

    Zwraca:
        dict: {"hierarchical_counts": {...}} or error dict
    """
    if not isinstance(raw_counts, dict):
        return {"error": "'raw_counts' must be a dictionary."}

    # Try proxy first
    try:
        import requests
        from urllib.parse import urljoin

        # Fix #14 v4.2: Use env var, not localhost
        import os
        master_url = os.environ.get('MASTER_SEO_API_URL', '')
        if not master_url:
            raise ValueError("MASTER_SEO_API_URL not set")
        proxy_url = f"{master_url}/api/count_keywords_inherited"
        timeout = 2  # Short timeout to fail fast if unavailable

        response = requests.post(
            proxy_url,
            json={"raw_counts": raw_counts},
            timeout=timeout,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            result = response.json()
            logger.info("Used proxy endpoint for keyword counting")
            return result
        else:
            logger.warning(f"Proxy returned status {response.status_code}, falling back to legacy")
    except Exception as e:
        logger.debug(f"Proxy call failed: {e}, falling back to legacy algorithm")

    # Fallback to legacy algorithm
    return _legacy_hierarchical_keyword_counter(raw_counts)
