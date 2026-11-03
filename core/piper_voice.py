"""Fala pela caixa Bluetooth do robô usando um servidor Piper local.

O servidor (contêiner `ipe-piper`, subido por scripts/robo_voz.sh) recebe
`POST /synthesize {"text": ...}`, gera o áudio com a voz pt_BR-faber-medium e toca com `paplay`
na saída padrão do PulseAudio (a caixa). Ele só responde depois de tocar: `say()` bloqueia até o
fim da frase. O alto-falante da cabeça do G1 não responde (RPC 3104), por isso a caixa.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:5005/synthesize"


def say(text: str, url: str = DEFAULT_URL, timeout_s: float = 60.0) -> None:
    """Fala `text` e volta quando o áudio terminou. Levanta RuntimeError se o servidor falhar."""
    request = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            response.read()  # o WAV que ele tocou; não precisamos dele
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"servidor Piper não respondeu em {url} ({exc}); ele está de pé? scripts/robo_voz.sh"
        ) from exc
