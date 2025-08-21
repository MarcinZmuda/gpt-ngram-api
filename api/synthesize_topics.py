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
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data)
            ngrams = data.get("ngrams", [])
            headings = data.get("headings", [])
            def get_themes(text_list):
                words = re.findall(r'\b\w{3,}\b', ' '.join(text_list).lower())
                return [theme for theme, count in Counter(words).most_common(10)]
            ngram_themes = get_themes(ngrams)
            heading_themes = get_themes(headings)
            all_themes = sorted(list(set(ngram_themes + heading_themes)))
            topic_importance = []
            for theme in all_themes:
                h_freq = sum(1 for h in headings if theme in h.lower())
                n_freq = sum(1 for n in ngrams if theme in n.lower())
                if h_freq > 0 or n_freq > 0:
                    topic_importance.append({"theme": theme, "h2_frequency": h_freq, "ngram_frequency": n_freq})
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            self.wfile.write(json.dumps({"topic_importance": topic_importance}).encode('utf-8'))
        except Exception as e:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
