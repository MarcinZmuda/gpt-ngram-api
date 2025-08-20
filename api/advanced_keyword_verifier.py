# Plik: api/advanced_keyword_verifier.py
import json
import re
import spacy
from http.server import BaseHTTPRequestHandler

# Model spaCy jest ładowany raz
NLP = spacy.load("pl_core_news_sm")

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        # ... (obsługa requestu i CORS, tak jak poprzednio) ...
        
        try:
            data = json.loads(post_data)
            text_to_process = data.get("text")
            keywords_to_track = data.get("keywords") # Oczekujemy listy stringów

            # 1. Lematyzacja tekstu
            doc_text = NLP(text_to_process.lower())
            text_lemmas = [token.lemma_ for token in doc_text]

            # 2. Lematyzacja słów kluczowych i surowe zliczenie
            raw_counts = {}
            lemmatized_keywords = {}
            for keyword in keywords_to_track:
                doc_kw = NLP(keyword.lower())
                # Bierzemy tylko pierwszy lemat jako reprezentatywny
                kw_lemma = doc_kw[0].lemma_
                lemmatized_keywords[keyword] = kw_lemma
                raw_counts[keyword] = text_lemmas.count(kw_lemma)

            # 3. Obliczenie hierarchiczne (serce operacji)
            final_counts = self.calculate_hierarchical_counts(raw_counts)

            # Zwracamy finalne, hierarchiczne zliczenia
            self.send_response(200)
            # ... (obsługa response, tak jak poprzednio) ...
            self.wfile.write(json.dumps({"hierarchical_counts": final_counts}).encode('utf-8'))

        except Exception as e:
            # ... (obsługa błędów) ...
        
        return

    def calculate_hierarchical_counts(self, raw_counts):
        # Ta funkcja pozostaje taka sama, jak w naszej poprzedniej dyskusji
        keywords = sorted(raw_counts.keys(), key=len, reverse=True)
        hierarchical_counts = raw_counts.copy()
        
        for i, long_kw in enumerate(keywords):
            for short_kw in keywords[i+1:]:
                if short_kw in long_kw and re.search(r'\b' + re.escape(short_kw) + r'\b', long_kw):
                    hierarchical_counts[short_kw] += raw_counts.get(long_kw, 0)
        
        return hierarchical_counts
