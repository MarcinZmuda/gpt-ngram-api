# api/index.py --- KOD DIAGNOSTYCZNY (LUSTRO) ---
from http.server import BaseHTTPRequestHandler
import json

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
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

        content_length = int(self.headers.get('Content-Length', 0))
        post_data_bytes = self.rfile.read(content_length)

        response = {
            "message": "This is the exact data I received from the GPT:",
            "received_data_as_string": post_data_bytes.decode('utf-8')
        }

        self.wfile.write(json.dumps(response, indent=2).encode('utf-8'))
        return
