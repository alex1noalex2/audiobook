"""POST /api/tts {text, voice} -> audio/mpeg (Google Cloud TTS, голоса Chirp 3 HD).

Ключ API — в переменной окружения Vercel GOOGLE_TTS_KEY, в коде его нет.
"""
import base64
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

VOICES = {
    "ru-RU-Chirp3-HD-Aoede",
    "ru-RU-Chirp3-HD-Charon",
    "ro-RO-Chirp3-HD-Aoede",
    "ro-RO-Chirp3-HD-Charon",
}
MAX_CHARS = 3000  # у Google лимит 5000 байт на запрос, кириллица — 2 байта на букву
URL = "https://texttospeech.googleapis.com/v1/text:synthesize?key="


def synth(text, voice):
    body = json.dumps({
        "input": {"text": text},
        "voice": {"languageCode": voice[:5], "name": voice},
        "audioConfig": {"audioEncoding": "MP3"},
    }).encode()
    req = urllib.request.Request(URL + os.environ["GOOGLE_TTS_KEY"], body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=50) as r:
        return base64.b64decode(json.load(r)["audioContent"])


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            text = str(body.get("text", "")).strip()
            voice = body.get("voice")
        except (ValueError, AttributeError):
            return self._send(400, b"bad json", "text/plain")
        if voice not in VOICES or not text or len(text) > MAX_CHARS:
            return self._send(400, b"bad text or voice", "text/plain")
        try:
            audio = synth(text, voice)
        except urllib.error.HTTPError as e:  # ответ Google как есть — клиент покажет и повторит
            return self._send(502, e.read()[:500], "text/plain")
        except Exception as e:
            return self._send(502, str(e).encode()[:500], "text/plain")
        self._send(200, audio, "audio/mpeg")

    def _send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
