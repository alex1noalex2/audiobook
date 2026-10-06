"""POST /api/tts {text, voice} -> audio/mpeg (голоса Microsoft Edge через edge-tts)."""
import asyncio
import json
from http.server import BaseHTTPRequestHandler

import edge_tts

VOICES = {
    "ru-RU-SvetlanaNeural",
    "ru-RU-DmitryNeural",
    "ro-RO-AlinaNeural",
    "ro-RO-EmilNeural",
}
MAX_CHARS = 3000


async def synth(text, voice):
    audio = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    return bytes(audio)


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
            audio = asyncio.run(synth(text, voice))
        except Exception as e:  # сбой на стороне Microsoft — отдаём клиенту, он повторит
            return self._send(502, str(e).encode()[:500], "text/plain")
        self._send(200, audio, "audio/mpeg")

    def _send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
