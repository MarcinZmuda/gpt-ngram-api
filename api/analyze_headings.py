# Plik: api/analyze_headings.py
import json
from collections import Counter
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
            headings = data.get("headings")
            if not isinstance(headings, list): raise ValueError("Payload must include 'headings' (a list of strings).")
            heading_counts = Counter(headings)
            top_5_headings = [{"heading": h, "count": c} for h, c in heading_counts.most_common(5)]
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            self.wfile.write(json.dumps({"top_headings": top_5_headings}).encode('utf-8'))
        except Exception as e:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
