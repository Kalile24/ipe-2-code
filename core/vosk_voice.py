"""Reconhecimento da fala do operador com o Vosk, restrito a uma gramática (as frases dos comandos).

Com a gramática o Vosk só devolve uma das frases ou "[unk]" (vira texto vazio): não há ditado livre a
errar. Roda na CPU, dentro do voz_node, sem servidor. O áudio só passa pela memória.
Modelo: vosk-model-small-pt-0.3 em ~/.cache/ipe-vosk (docs/guides/jetson-deployment.md).
"""
from __future__ import annotations

import json
import os

MODELO_PADRAO = os.path.expanduser("~/.cache/ipe-vosk/vosk-model-small-pt-0.3")


class Transcritor:
    """`transcritor(pcm)` → texto. PCM S16_LE 16 kHz mono (o que o Gravador entrega)."""

    def __init__(self, frases: list[str], modelo: str = MODELO_PADRAO) -> None:
        import vosk  # só no robô; aqui para o resto do core não depender dele

        if not os.path.isdir(modelo):
            raise RuntimeError(f"modelo Vosk não encontrado em {modelo} (docs/guides/jetson-deployment.md)")
        vosk.SetLogLevel(-1)
        self._rec = vosk.KaldiRecognizer(vosk.Model(modelo), 16000, json.dumps(frases, ensure_ascii=False))

    def __call__(self, pcm: bytes) -> str:
        if not pcm:
            return ""
        self._rec.AcceptWaveform(pcm)
        texto = json.loads(self._rec.FinalResult()).get("text", "")  # FinalResult zera para a próxima fala
        return " ".join(p for p in texto.split() if p != "[unk]")
