# Plik: api/analyze_headings.py
import json
from collections import Counter
from http.server import BaseHTTPRequestHandler

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
            headings = data.get("headings")

            if not isinstance(headings, list):
                raise ValueError("Payload must include 'headings' (a list of strings).")

            # Zliczanie wystąpień każdego nagłówka
            heading_counts = Counter(headings)
            
            # Sortowanie od najczęstszych i pobranie TOP 5
            top_5_headings = [{"heading": h, "count": c} for h, c in heading_counts.most_common(5)]

            # Wysłanie odpowiedzi
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            response_data = json.dumps({"top_headings": top_5_headings})
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
