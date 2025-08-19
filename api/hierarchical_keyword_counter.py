# Plik: api/hierarchical_keyword_counter.py

import json
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
            raw_counts = data.get("raw_counts")

            if not isinstance(raw_counts, dict):
                raise ValueError("'raw_counts' must be a dictionary.")

            hierarchical_counts = self.calculate_hierarchical_counts(raw_counts)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            response_data = json.dumps({"hierarchical_counts": hierarchical_counts})
            self.wfile.write(response_data.encode('utf-8'))

        except (json.JSONDecodeError, ValueError) as e:
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
                if short_kw in long_kw:
                    if re.search(r'\b' + re.escape(short_kw) + r'\b', long_kw):
                        hierarchical_counts[short_kw] += raw_counts.get(long_kw, 0)
        
        return hierarchical_counts