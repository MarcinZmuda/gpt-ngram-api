# Plik: api/lemmatize_and_count.py

import json
import spacy
from http.server import BaseHTTPRequestHandler

# Ładujemy model spaCy tylko raz przy starcie serwera
try:
    NLP = spacy.load("pl_core_news_sm")
except OSError:
    from spacy.cli import download
    download("pl_core_news_sm")
    NLP = spacy.load("pl_core_news_sm")

def lemmatize_text(text):
    """Zwraca listę lematów z tekstu (bez znaków interpunkcyjnych)."""
    doc = NLP(text.lower())
    return [token.lemma_ for token in doc if token.is_alpha]

class handler(BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self._set_headers()
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        try:
            data = json.loads(post_data)
            text_to_process = data.get("text")
            keywords_to_find = data.get("keywords")

            if not text_to_process or not isinstance(keywords_to_find, list):
                raise ValueError("Missing 'text' or 'keywords' parameter.")

            # Lematyzujemy cały tekst (lista lematów)
            text_lemmas = lemmatize_text(text_to_process)

            keyword_counts = {}

            for keyword in keywords_to_find:
                # Lematyzacja frazy kluczowej
                keyword_lemmas = lemmatize_text(keyword)
                kw_len = len(keyword_lemmas)
                count = 0

                # Przesuwamy się po tekście i sprawdzamy pełne dopasowania sekwencji
                for i in range(len(text_lemmas) - kw_len + 1):
                    if text_lemmas[i:i + kw_len] == keyword_lemmas:
                        count += 1

                keyword_counts[keyword] = count

            # Wysyłamy odpowiedź
            self.send_response(200)
            self._set_headers()
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response_data = json.dumps({"keyword_counts": keyword_counts})
            self.wfile.write(response_data.encode('utf-8'))

        except Exception as e:
            self.send_response(400)
            self._set_headers()
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            error_response = json.dumps({"error": str(e)})
            self.wfile.write(error_response.encode('utf-8'))
