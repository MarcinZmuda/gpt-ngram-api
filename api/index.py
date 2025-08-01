# api/index.py
from http.server import BaseHTTPRequestHandler
import json
import re
import math

# =================================================================
#  WERSJA FINALNA - z pełną logiką i poprawionym filtrem
# =================================================================

def process_data(data):
    # === PARAMETRY ===
    BONUS_TITLE = 0.6
    BONUS_H1 = 0.4
    BONUS_H2 = 0.2
    TOP_N = 30
    RANK_BONUSES = {1: 0.6, 2: 0.4, 3: 0.2}
    STOPWORDS = set([
        'i','oraz','ale','że','który','która','to','się','na','do','w','z','o','u','od','po',
        'jak','jest','czy','by','być','ten','ta','te','go','co','dla','bez','przez','jeśli',
        'the','and','but','or','of','on','in','to','for','is','at','with','by','as','from',
        'a','an','be'
    ])

    def clean(txt = ''):
        return re.sub(r'[^a-z0-9ąćęłńóśźż]+', ' ', str(txt).lower()).strip()

    # === POPRAWIONY, MNIEJ AGRESYWNY FILTR ===
    def is_low_quality_gram(gram):
        words = gram.split()
        stop_count = sum(1 for w in words if w in STOPWORDS)
        
        # Odrzuca tylko frazy składające się w całości ze stopwords (np. "co to jest w")
        if len(words) > 0 and (len(words) - stop_count) < 1:
            return True
        return False

    def get_ngram_counts(raw, n):
        tokens = clean(raw).split()
        counts = {}
        for i in range(len(tokens) - n + 1):
            gram = " ".join(tokens[i:i+n])
            if is_low_quality_gram(gram):
                continue
            counts[gram] = counts.get(gram, 0) + 1
        return counts

    def score_and_rank(counts, title_txt, h1_txt, h2_txt):
        scores = {}
        for gram, cnt in counts.items():
            s = float(cnt)
            if gram in title_txt: s += BONUS_TITLE
            if gram in h1_txt: s += BONUS_H1
            if gram in h2_txt: s += BONUS_H2
            scores[gram] = s
        return scores

    # === Główna logika przetwarzająca ===
    competitor_pages = data.get('competitor_pages', [])
    num_documents = len(competitor_pages)
    if num_documents == 0:
        return {}

    processed_items = []
    for item_data in competitor_pages:
        rank = item_data.get('rank', 0)
        page_rank_bonus = RANK_BONUSES.get(rank, 0)
        title_txt = clean(item_data.get('title', ''))
        h1_txt = clean(" ".join(item_data.get('h1s', [])))
        h2_txt = clean(" ".join(item_data.get('h2s', [])))
        content = item_data.get('content', '')
        item_output = {}
        for n in range(2, 5):
            raw_counts = get_ngram_counts(content, n)
            scored_grams = score_and_rank(raw_counts, title_txt, h1_txt, h2_txt)
            for gram in scored_grams:
                scored_grams[gram] += page_rank_bonus
            item_output[f'top{n}grams'] = [{'gram': gram, 'totalScore': score} for gram, score in scored_grams.items()]
        processed_items.append(item_output)
    
    idf_scores = {2: {}, 3: {}, 4: {}}
    for n in range(2, 5):
        key = f'top{n}grams'
        doc_frequency = {}
        for item in processed_items:
            unique_grams_in_doc = set(d['gram'] for d in item.get(key, []))
            for gram in unique_grams_in_doc:
                doc_frequency[gram] = doc_frequency.get(gram, 0) + 1
        for gram, freq in doc_frequency.items():
            if freq > 0:
                idf_scores[n][gram] = math.log(num_documents / freq)

    final_output = {}
    for n in range(2, 5):
        key = f'top{n}grams'
        aggregated_map = {}
        for item in processed_items:
            for gram_data in item.get(key, []):
                gram = gram_data['gram']
                score = gram_data['totalScore']
                aggregated_map[gram] = aggregated_map.get(gram, 0) + score
        
        final_scores = {}
        for gram, total_score in aggregated_map.items():
            idf_multiplier = idf_scores[n].get(gram, 1)
            final_scores[gram] = total_score * (1 + idf_multiplier)

        top_n_list = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
        top_grams_formatted = [{'gram': gram, 'totalScore': round(score, 2)} for gram, score in top_n_list]
        final_output[f'top{n}grams'] = top_grams_formatted
        final_output[f'joined{n}grams'] = ", ".join([item['gram'] for item in top_grams_formatted])

    return final_output


class handler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        try:
            input_data = json.loads(post_data)
            results = process_data(input_data)
            self.wfile.write(json.dumps(results).encode('utf-8'))
        except Exception as e:
            error_response = {'error': str(e), 'type': type(e).__name__}
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
        return
