# Plik: api/generate_compliance_report.py
import json
import re
import spacy
from http.server import BaseHTTPRequestHandler

try:
    NLP = spacy.load("pl_core_news_sm")
except OSError:
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
            keyword_list_string = data.get("keyword_list_string")

            if not text_to_process or not keyword_list_string:
                raise ValueError("Payload must include 'text' and 'keyword_list_string'.")

            # === INTELIGENTNE PARSOWANIE SUROWEJ LISTY OD UŻYTKOWNIKA ===
            keywords_with_ranges = {}
            for line in keyword_list_string.strip().split('\n'):
                line = line.strip()
                if not line: continue
                
                # Próba dopasowania formatu "słowo: min-max"
                match = re.match(r'^(.*?):\s*(\d+)-(\d+)x?$', line)
                if match:
                    kw, min_val, max_val = match.groups()
                    keywords_with_ranges[kw.strip()] = {"min": int(min_val), "max": int(max_val)}
                    continue
                
                # Próba dopasowania formatu "słowo: max"
                match = re.match(r'^(.*?):\s*(\d+)x?$', line)
                if match:
                    kw, max_val = match.groups()
                    keywords_with_ranges[kw.strip()] = {"min": 1, "max": int(max_val)}
            # === KONIEC PARSOWANIA ===

            doc_text = NLP(text_to_process.lower())
            text_lemmas = [token.lemma_ for token in doc_text]

            compliance_report = []
            for keyword, ranges in keywords_with_ranges.items():
                min_val, max_val = ranges.get("min", 0), ranges.get("max", float('inf'))
                doc_kw = NLP(keyword.lower())
                kw_lemma = doc_kw[0].lemma_
                actual_count = text_lemmas.count(kw_lemma)
                
                status = "OK"
                if actual_count < min_val or actual_count > max_val:
                    status = "ERROR"
                
                compliance_report.append({
                    "keyword": keyword,
                    "range": f"{min_val}-{max_val}",
                    "actual": actual_count,
                    "status": status
                })

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            self.wfile.write(json.dumps({"compliance_report": compliance_report}).encode('utf-8'))

        except Exception as e:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', 'https://chat.openai.com')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        
        return
