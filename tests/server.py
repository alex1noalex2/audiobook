import sys, os, functools, importlib.util
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
spec = importlib.util.spec_from_file_location('tts', ROOT + '/api/tts.py')
tts = importlib.util.module_from_spec(spec); spec.loader.exec_module(tts)
MOCK = open(sys.argv[1], 'rb').read()
calls = []
def fake(text, voice):
    calls.append(voice); print('TTS', voice, len(text), flush=True); return MOCK
tts.synth = fake
class H(tts.handler, SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
ThreadingHTTPServer(('127.0.0.1', 8765), functools.partial(H, directory=ROOT)).serve_forever()
