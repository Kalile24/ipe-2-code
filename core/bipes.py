"""Bipes curtos pela caixa Bluetooth (saída padrão do PulseAudio): um retorno sonoro para cada combo
do controle, sem depender do servidor de voz (que pode ainda não estar de pé).

Cada padrão é uma lista de (frequência em Hz, duração em s); 0 Hz é silêncio. `tocar` não bloqueia.
"""
from __future__ import annotations

import io
import math
import shutil
import struct
import subprocess
import tempfile
import wave

TAXA = 22050
VOLUME = 0.5

# Subindo: dois tons subindo. Agora: um tom. Automático: dois tons iguais. Parar: um tom grave.
# Encerrada: dois tons descendo. Recusado: dois tons graves (o combo não fez nada).
PADROES: dict[str, list[tuple[float, float]]] = {
    "iniciar": [(660, 0.12), (0, 0.05), (880, 0.18)],
    "agora": [(880, 0.2)],
    "automatico": [(660, 0.1), (0, 0.08), (660, 0.1)],
    "parar": [(440, 0.35)],
    "encerrada": [(660, 0.12), (0, 0.05), (440, 0.2)],
    "recusado": [(220, 0.15), (0, 0.08), (220, 0.15)],
    # Combo que precisa ser segurado: três bipes curtos ao começar; damp: três tons descendo.
    "segurar": [(1000, 0.06), (0, 0.06), (1000, 0.06), (0, 0.06), (1000, 0.06)],
    "damp": [(440, 0.15), (0, 0.04), (330, 0.15), (0, 0.04), (220, 0.25)],
}


def wav(padrao: list[tuple[float, float]]) -> bytes:
    """WAV mono 16 bits do padrão, com 5 ms de rampa em cada tom (sem estalo)."""
    amostras: list[int] = []
    rampa = int(0.005 * TAXA)
    for freq, dur in padrao:
        n = int(dur * TAXA)
        for i in range(n):
            if freq <= 0:
                amostras.append(0)
                continue
            envelope = min(1.0, i / rampa, (n - 1 - i) / rampa) if rampa else 1.0
            amostras.append(int(32767 * VOLUME * envelope * math.sin(2 * math.pi * freq * i / TAXA)))
    saida = io.BytesIO()
    with wave.open(saida, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(struct.pack(f"<{len(amostras)}h", *amostras))
    return saida.getvalue()


def tocar(nome: str) -> None:
    """Toca o padrão `nome` em segundo plano. Sem paplay (ou sem som), não faz nada."""
    if shutil.which("paplay") is None:
        return
    arquivo = tempfile.NamedTemporaryFile(prefix="ipe-bipe-", suffix=".wav", delete=False)
    arquivo.write(wav(PADROES[nome]))
    arquivo.close()
    # O shell apaga o arquivo depois de tocar; o controle não espera.
    subprocess.Popen(["sh", "-c", 'paplay "$1"; rm -f "$1"', "bipe", arquivo.name],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
