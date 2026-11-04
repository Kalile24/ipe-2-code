from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.piper_voice import say


@pytest.fixture
def servidor():
    """Um falso servidor Piper: guarda os textos recebidos e devolve um 'WAV'."""
    recebidos = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            recebidos.append((self.path, corpo["text"]))
            self.send_response(200 if self.path == "/synthesize" else 404)
            self.send_header("Content-Length", "4")
            self.end_headers()
            self.wfile.write(b"RIFF")

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", recebidos
    httpd.shutdown()


def test_posts_the_text_as_utf8_json(servidor):
    base, recebidos = servidor
    say("Olá, aspirante Gil", url=f"{base}/synthesize")
    assert recebidos == [("/synthesize", "Olá, aspirante Gil")]


def test_http_error_raises_runtime_error(servidor):
    base, _ = servidor
    with pytest.raises(RuntimeError, match="Piper"):
        say("oi", url=f"{base}/errado")


def test_server_down_raises_runtime_error_with_hint():
    with pytest.raises(RuntimeError, match="robo_voz"):
        say("oi", url="http://127.0.0.1:9/synthesize", timeout_s=2.0)
