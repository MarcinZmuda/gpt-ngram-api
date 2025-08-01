# api/index.py --- WERSJA Z WAŻENIEM POZYCYJNYM I BONUSEM ZA KONTEKST ---
from http.server import BaseHTTPRequestHandler
import json
import re

def process_advanced_simple_text(data):
    text = data.get('text', '')
    main_keyword = data.get('main_keyword', '')
    if not text:
        return {"error": "Input text is empty"}

    # --- Parametry ---
    TOP_N = 50
    POSITIONAL_BONUS_FACTOR = 1.5  # N-gramy w pierwszej 1/4 tekstu dostają 50% bonus
    KEYWORD_BONUS_FACTOR = 2.0     # N-gramy zawierające główne słowo kluczowe dostają 100% bonus
    STOPWORDS = set(['i','oraz','ale','że','który','która','to','się','na','do','w','z','o','u','od','po','jak','jest','czy','by','być','ten','ta','te','go','co','dla','bez','przez','jeśli'])

    def clean(txt = ''):
        return re.sub(r'[^a-z0-9ąćęłńóśźż]+', ' ', str(txt).lower()).strip()

    tokens = clean(text).split()
    positional_threshold = len(tokens) // 4  # Definiujemy próg dla 25% tekstu
    cleaned_main_keyword = clean(main_keyword)
    
    final_output = {}

    for n in range(2, 5):
        counts = {}
        for i in range(len(tokens) - n + 1):
            gram_words = tokens[i:i+n]
            non_stop_count = sum(1 for w in gram_words if w not in STOPWORDS)
            if non_stop_count == 0: continue
            
            gram = " ".join(gram_words)
            score = counts.get(gram, 0) + 1.0 # Bazowy wynik to 1.0
            
            # 1. Aplikacja Wagi Pozycyjnej
            if i < positional_threshold:
                score *= POSITIONAL_BONUS_FACTOR
            
            # 2. Aplikacja Bonusu za Kontekst
            if cleaned_main_keyword and cleaned_main_keyword in gram:
                score *= KEYWORD_BONUS_FACTOR

            counts[gram] = score
        
        top_n_list = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
        final_output[f'top{n}grams'] = [{'gram': gram, 'score': round(score, 2)} for gram, score in top_n_list]

    return final_output

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
        post_data = self.rfile.read(content_length)
        try:
            input_data = json.loads(post_data)
            results = process_advanced_simple_text(input_data)
            self.wfile.write(json.dumps(results).encode('utf-8'))
        except Exception as e:
            error_response = {'error': str(e), 'type': type(e).__name__}
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
        return
