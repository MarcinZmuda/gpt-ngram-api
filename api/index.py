# api/index.py --- KROK 1: PRZYWRÓCENIE STRUKTURY DANYCH ---
from http.server import BaseHTTPRequestHandler
import json
import re

def process_structured_data(data):
    # Oczekujemy {"competitor_pages": [...]}
    pages = data.get('competitor_pages', [])
    if not pages:
        return {"error": "Input 'competitor_pages' list is empty or missing"}

    # Na razie tylko łączymy treść ze wszystkich stron
    combined_text = " ".join([page.get('content', '') for page in pages])

    TOP_N = 50
    STOPWORDS = set(['i','oraz','ale','że','który','która','to','się','na','do','w','z','o','u','od','po','jak','jest','czy','by','być','ten','ta','te','go','co','dla','bez','przez','jeśli'])

    def clean(txt = ''):
        return re.sub(r'[^a-z0-9ąćęłńóśźż]+', ' ', str(txt).lower()).strip()

    tokens = clean(combined_text).split()
    final_output = {}

    for n in range(2, 5):
        counts = {}
        for i in range(len(tokens) - n + 1):
            gram_words = tokens[i:i+n]
            non_stop_count = sum(1 for w in gram_words if w not in STOPWORDS)
            if non_stop_count == 0: continue
            
            gram = " ".join(gram_words)
            counts[gram] = counts.get(gram, 0) + 1
        
        top_n_list = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
        final_output[f'top{n}grams'] = [{'gram': gram, 'count': count} for gram, count in top_n_list]

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
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            input_data = json.loads(post_data)
            results = process_structured_data(input_data)
            self.wfile.write(json.dumps(results).encode('utf-8'))
        except Exception as e:
            error_response = {'error': str(e), 'type': type(e).__name__}
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
        return
