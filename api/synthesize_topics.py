# Plik: api/synthesize_topics.py
import json
from collections import Counter
import re
from http.server import BaseHTTPRequestHandler

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
            ngrams = data.get("ngrams", []) # Oczekujemy listy n-gramów jako stringi
            headings = data.get("headings", []) # Oczekujemy listy H2 jako stringi

            # Prosta tokenizacja - dzielenie na słowa i usuwanie krótkich słów
            def get_themes(text_list):
                words = re.findall(r'\b\w{3,}\b', ' '.join(text_list).lower())
                return Counter(words).most_common(10) # Bierzemy 10 najczęstszych słów jako "tematy"

            ngram_themes = [theme for theme, count in get_themes(ngrams)]
            heading_themes = [theme for theme, count in get_themes(headings)]
            
            # Łączymy i znajdujemy unikalne tematy
            all_themes = sorted(list(set(ngram_themes + heading_themes)))

            # Tworzymy tabelę ważności
            topic_importance = []
            for theme in all_themes:
                h_freq = sum(1 for h in headings if theme in h.lower())
                n_freq = sum(1 for n in ngrams if theme in n.lower())
                if h_freq > 0 or n_freq > 0:
                    topic_importance.append({
                        "theme": theme,
                        "h2_frequency": h_freq,
                        "ngram_frequency": n_freq
                    })

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            response_data = json.dumps({"topic_importance": topic_importance})
            self.wfile.write(response_data.encode('utf-8'))

        except Exception as e:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            error_response = json.dumps({"error": str(e)})
            self.wfile.write(error_response.encode('utf-8'))
        
        return
