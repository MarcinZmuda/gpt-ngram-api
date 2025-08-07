# api/keyword_validator.py
from http.server import BaseHTTPRequestHandler
import json
import spacy

# Ładujemy polski model językowy RAZ, przy starcie funkcji, aby działała szybciej.
nlp = spacy.load("pl_core_news_sm")

def validate_keywords_with_lemmatization(data):
    text_to_analyze = data.get('text', '')
    keywords_to_track = data.get('keywords_to_track', [])

    if not text_to_analyze or not keywords_to_track:
        return {"error": "Missing text or keywords_to_track"}

    # Lematyzujemy cały tekst wejściowy
    doc = nlp(text_to_analyze.lower())
    lemmatized_text = " ".join([token.lemma_ for token in doc])

    results = {}
    for keyword in keywords_to_track:
        # Lematyzujemy każde słowo kluczowe
        keyword_doc = nlp(keyword.lower())
        lemmatized_keyword = " ".join([token.lemma_ for token in keyword_doc])
        
        # Zliczamy wystąpienia zlematyzowanej frazy w zlematyzowanym tekście
        count = lemmatized_text.count(lemmatized_keyword)
        results[keyword] = count

    return {"keyword_counts": results}

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
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            input_data = json.loads(post_data)
            response_data = validate_keywords_with_lemmatization(input_data)
            
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