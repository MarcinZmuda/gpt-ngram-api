# Plik: api/lemmatize_and_count.py

import json
import spacy
from http.server import BaseHTTPRequestHandler

# Ładujemy model spaCy tylko raz przy starcie serwera (optymalizacja)
try:
    NLP = spacy.load("pl_core_news_sm")
except OSError:
    # Ten blok jest na wypadek, gdyby model nie był zainstalowany lokalnie.
    # Na Vercel zostanie zainstalowany z requirements.txt.
    from spacy.cli import download
    download("pl_core_news_sm")
    NLP = spacy.load("pl_core_news_sm")

class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        return

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data)
            text_to_process = data.get("text")
            keywords_to_find = data.get("keywords")

            if not text_to_process or not isinstance(keywords_to_find, list):
                raise ValueError("Missing 'text' or 'keywords' parameter.")

            # Lematyzacja tekstu
            doc_text = NLP(text_to_process.lower())
            text_lemmas = {token.lemma_ for token in doc_text}

            # Lematyzacja słów kluczowych i zliczanie
            keyword_counts = {}
            for keyword in keywords_to_find:
                doc_kw = NLP(keyword.lower())
                # Bierzemy tylko pierwszy, najważniejszy lemat frazy
                kw_lemma = doc_kw[0].lemma_
                
                # Zliczamy wystąpienia lematu
                count = sum(1 for token in doc_text if token.lemma_ == kw_lemma)
                keyword_counts[keyword] = count

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            response_data = json.dumps({"keyword_counts": keyword_counts})
            self.wfile.write(response_data.encode('utf-8'))

        except Exception as e:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            error_response = json.dumps({"error": str(e)})
            self.wfile.write(error_response.encode('utf-8'))
        
        return