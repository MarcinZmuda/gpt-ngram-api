# api/keyword_validator.py --- WERSJA UPROSZCZONA BEZ SPACY ---
from http.server import BaseHTTPRequestHandler
import json

def simple_counter(data):
    # Oczekuje już zlematyzowanego tekstu i słów kluczowych
    lemmatized_text = data.get('lemmatized_text', '')
    lemmatized_keywords = data.get('lemmatized_keywords', [])

    if not lemmatized_text or not lemmatized_keywords:
        return {"error": "Missing lemmatized text or keywords"}

    results = {}
    for keyword in lemmatized_keywords:
        # Proste zliczanie, bo cała magia stała się już wcześniej
        count = lemmatized_text.count(keyword)
        results[keyword] = count

    return {"keyword_counts": results}

class handler(BaseHTTPRequestHandler):
    # Tutaj wklej resztę kodu handlera (z CORS), jest taki sam jak poprzednio
    def _set_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            input_data = json.loads(post_data)
            response_data = simple_counter(input_data)
            self.send_response(200)
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return
