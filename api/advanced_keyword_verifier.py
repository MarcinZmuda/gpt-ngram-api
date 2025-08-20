# Plik: api/advanced_keyword_verifier.py
import json
import re
import spacy
from http.server import BaseHTTPRequestHandler

# Model spaCy jest ładowany raz, co optymalizuje działanie
try:
    NLP = spacy.load("pl_core_news_sm")
except OSError:
    from spacy.cli import download
    download("pl_core_news_sm")
    NLP = spacy.load("pl_core_news_sm")

class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        # Obsługa zapytań preflight CORS
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
            keywords_to_track = data.get("keywords")

            if not text_to_process or not isinstance(keywords_to_track, list):
                raise ValueError("Payload must include 'text' (string) and 'keywords' (list).")

            # Krok 1: Lematyzacja tekstu wejściowego
            doc_text = NLP(text_to_process.lower())
            text_lemmas = [token.lemma_ for token in doc_text]

            # Krok 2: Lematyzacja słów kluczowych i surowe zliczenie
            raw_counts = {}
            for keyword in keywords_to_track:
                doc_kw = NLP(keyword.lower())
                kw_lemma = doc_kw[0].lemma_ # Używamy pierwszego lematu jako reprezentanta
                raw_counts[keyword] = text_lemmas.count(kw_lemma)

            # Krok 3: Obliczenia hierarchiczne na podstawie surowych zliczeń
            final_counts = self.calculate_hierarchical_counts(raw_counts)

            # Wysłanie poprawnej odpowiedzi
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            response_data = json.dumps({"hierarchical_counts": final_counts})
            self.wfile.write(response_data.encode('utf-8'))

        except Exception as e:
            # Obsługa błędów
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            error_response = json.dumps({"error": str(e)})
            self.wfile.write(error_response.encode('utf-8'))
        
        return

    def calculate_hierarchical_counts(self, raw_counts):
        keywords = sorted(raw_counts.keys(), key=len, reverse=True)
        hierarchical_counts = raw_counts.copy()
        
        for i, long_kw in enumerate(keywords):
            for short_kw in keywords[i+1:]:
                if short_kw in long_kw and re.search(r'\\b' + re.escape(short_kw) + r'\\b', long_kw):
                    hierarchical_counts[short_kw] += raw_counts.get(long_kw, 0)
        
        return hierarchical_counts
