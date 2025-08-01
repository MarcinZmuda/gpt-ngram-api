# api/index.py --- WERSJA UPROSZCZONA "BRUTE FORCE" ---
from http.server import BaseHTTPRequestHandler
import json
import re

def process_simple_text(data):
    # Oczekujemy prostego JSON: {"text": "długi tekst..."}
    text = data.get('text', '')
    if not text:
        return {"error": "Input text is empty"}

    TOP_N = 50 # Zwiększamy, aby złapać więcej fraz
    STOPWORDS = set([
        'i','oraz','ale','że','który','która','to','się','na','do','w','z','o','u','od','po',
        'jak','jest','czy','by','być','ten','ta','te','go','co','dla','bez','przez','jeśli'
    ])

    def clean(txt = ''):
        return re.sub(r'[^a-z0-9ąćęłńóśźż]+', ' ', str(txt).lower()).strip()

    tokens = clean(text).split()
    final_output = {}

    for n in range(2, 5): # 2, 3, 4-gramy
        counts = {}
        for i in range(len(tokens) - n + 1):
            gram_words = tokens[i:i+n]
            # Prosty filtr: odrzucamy tylko n-gramy składające się w całości ze stopwords
            non_stop_count = sum(1 for w in gram_words if w not in STOPWORDS)
            if non_stop_count == 0:
                continue
            
            gram = " ".join(gram_words)
            counts[gram] = counts.get(gram, 0) + 1
        
        # Sortowanie i wybór TOP_N
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
            results = process_simple_text(input_data)
            self.wfile.write(json.dumps(results).encode('utf-8'))
        except Exception as e:
            error_response = {'error': str(e), 'type': type(e).__name__}
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
        return
