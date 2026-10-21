#!/usr/bin/env python3
"""Озвучка книги без кода: страница в браузере на вашем компьютере. Бросаете PDF/EPUB/TXT, выбираете голос, нажимаете
«Озвучить». Всё лежит в ~/Audiobook: voices/ (голоса: имя.wav + имя.txt с текстом записи), books/<книга>/ (результат),
для_colab/ (то, что загрузить на Google Диск, если книга длинная). Запуск: двойной щелчок по «Озвучить книгу.command»
или python3 local/app.py"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path(os.environ.get("AUDIOBOOK_HOME", Path.home() / "Audiobook"))
SCRIPT = os.environ.get("BOOK2AUDIO_SCRIPT", str(Path(__file__).resolve().parent / "book2audio_f5.py"))
PAGE = Path(__file__).with_name("app.html")
FORMATS = {".pdf", ".epub", ".txt"}
ACTIONS = {"assemble": "--assemble", "redo": "--redo-weak"}      # озвучить / пересобрать книгу из готовых кусков / переозвучить слабые места
PROGRESS = re.compile(r"\[(\d+)/(\d+)\].*осталось ~([\d.]+) ч")

job = {"name": None, "proc": None, "log": [], "done": 0, "total": 0, "eta": None, "status": "idle"}
lock = threading.Lock()


def safe_name(name):
    """Имя книги -> имя папки без путей и спецсимволов."""
    stem = re.sub(r"[^\w .\-]+", "_", Path(name).stem, flags=re.UNICODE).strip(" .")
    return (stem or "book")[:80]


def voices():
    return sorted(p.stem for p in (HOME / "voices").glob("*.wav") if p.with_suffix(".txt").exists())


def books():
    out = []
    for d in sorted((HOME / "books").glob("*")):
        if d.is_dir():
            files = sorted(f.name for f in d.glob("*.mp3"))
            out.append({"name": d.name, "files": files, "done": (d / f"{d.name}.mp3").exists()})
    return out


def colab_cell(name, book_file, voice):
    """Ячейка для Google Colab: книга и голос лежат на Диске в Audiobook, результат — туда же."""
    return f'''from google.colab import drive
drive.mount('/content/drive')
FOLDER = "/content/drive/MyDrive/Audiobook"
!rm -rf /content/audiobook && git clone -q https://github.com/alex1noalex2/audiobook /content/audiobook
!pip install -q f5-tts silero-stress onnxruntime "onnx-asr[hub]" num2words praat-parselmouth pypdf
!python /content/audiobook/local/book2audio_f5.py "{{FOLDER}}/{book_file}" --ref "{{FOLDER}}/{voice}.wav" --out "{{FOLDER}}/{name}_audio"
print("ГОТОВО")
'''


def prepare_colab(name, voice):
    book = next((f for f in (HOME / "books" / name).iterdir() if f.suffix.lower() in FORMATS), None)
    if not book:
        raise ValueError("Сначала загрузите книгу")
    target = HOME / "для_colab"
    target.mkdir(exist_ok=True)
    shutil.copy(book, target / book.name)
    for ext in (".wav", ".txt"):
        shutil.copy(HOME / "voices" / f"{voice}{ext}", target / f"{voice}{ext}")
    return colab_cell(name, book.name, voice)


def start_job(name, voice, tries, boost, action="voice"):
    with lock:
        if job["proc"] and job["proc"].poll() is None:
            raise ValueError("Уже идёт озвучка другой книги")
    folder = HOME / "books" / name
    book = next((f for f in folder.iterdir() if f.suffix.lower() in FORMATS), None)
    if not book:
        raise ValueError("Сначала загрузите книгу")
    ref = HOME / "voices" / f"{voice}.wav"
    if not ref.exists() or not ref.with_suffix(".txt").exists():
        raise ValueError(f"Нет голоса «{voice}»: нужны {voice}.wav и {voice}.txt в {HOME / 'voices'}")
    cmd = [sys.executable, SCRIPT, str(book), "--ref", str(ref), "--out", str(folder / "audio"),
           "--tries", str(tries), "--q-boost", str(boost)]
    if action in ACTIONS:
        cmd.append(ACTIONS[action])
    env = dict(os.environ, PYTORCH_ENABLE_MPS_FALLBACK="1", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    with lock:
        job.update(name=name, proc=proc, log=[], done=0, total=0, eta=None, status="running")
    threading.Thread(target=pump, args=(proc,), daemon=True).start()


def pump(proc):
    for line in proc.stdout:
        line = line.rstrip()
        with lock:
            job["log"] = (job["log"] + [line])[-200:]
            m = PROGRESS.search(line)
            if m:
                job["done"], job["total"], job["eta"] = int(m[1]), int(m[2]), float(m[3])
    code = proc.wait()
    with lock:
        job["status"] = "finished" if code == 0 else ("stopped" if job["status"] == "stopping" else "error")


def state():
    with lock:
        return {"voices": voices(), "books": books(), "home": str(HOME),
                "job": {k: job[k] for k in ("name", "done", "total", "eta", "status")} | {"log": job["log"][-12:]}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="application/json", code=200):
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def url(self):
        """http.server читает адрес как latin-1; браузер шлёт UTF-8 в процентной записи, curl — голыми байтами."""
        return urlparse(self.path.encode("latin-1").decode("utf-8", "replace"))

    def do_GET(self):
        if self.url().path == "/api/state":
            return self.send(state())
        self.send(PAGE.read_text(encoding="utf-8"), "text/html")

    def do_POST(self):
        url = self.url()
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        try:
            if url.path == "/api/upload":                                  # файл целиком в теле запроса, имя в адресе
                name = query.get("name", "")
                if Path(name).suffix.lower() not in FORMATS:
                    raise ValueError("Подходят PDF, EPUB и TXT")
                folder = HOME / "books" / safe_name(name)
                folder.mkdir(parents=True, exist_ok=True)
                with open(folder / f"{safe_name(name)}{Path(name).suffix.lower()}", "wb") as f:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(remaining, 1 << 20))
                        f.write(chunk)
                        remaining -= len(chunk)
                return self.send({"name": folder.name})
            req = json.loads(self.rfile.read(length) or b"{}")
            if url.path == "/api/start":
                start_job(req["name"], req["voice"], int(req.get("tries", 1)), float(req.get("boost", 4)), req.get("action", "voice"))
                return self.send({"ok": True})
            if url.path == "/api/stop":
                with lock:
                    if job["proc"] and job["proc"].poll() is None:
                        job["status"] = "stopping"
                        job["proc"].terminate()
                return self.send({"ok": True})
            if url.path == "/api/colab":
                return self.send({"cell": prepare_colab(req["name"], req["voice"]), "folder": str(HOME / "для_colab")})
            if url.path == "/api/open":
                folder = HOME / "books" / req["name"] if req.get("name") else HOME
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
                return self.send({"ok": True})
            self.send({"error": "нет такого действия"}, code=404)
        except (ValueError, KeyError, OSError) as e:
            self.send({"error": str(e)}, code=400)


def main():
    (HOME / "voices").mkdir(parents=True, exist_ok=True)
    (HOME / "books").mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", 8765))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Откройте http://127.0.0.1:{port} (окно закрывать не нужно, остановка: Ctrl+C)")
    if not os.environ.get("NO_BROWSER"):
        webbrowser.open(f"http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        with lock:
            if job["proc"] and job["proc"].poll() is None:
                job["proc"].terminate()


if __name__ == "__main__":
    main()
