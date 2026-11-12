"""Carga da bateria do G1: o robo_controle.py lê rt/lf/bmsstate (SDK) e grava aqui; painel e subida leem.

Com 4% de carga o G1 agachou sozinho (proteção de bateria baixa, 2026-11-10). Abaixo de MINIMO a subida
armada é recusada; abaixo de AVISO o painel avisa. Sem leitura recente (controle fora do ar), a carga é
desconhecida: avisa, mas não impede. Puro, só biblioteca padrão (o script de subida usa: python3 -m core.bateria).
"""
from __future__ import annotations

import os
import sys
import time

ARQUIVO = "/tmp/ipe-bateria.txt"  # "<soc> <epoch>"
AVISO, MINIMO = 20, 10  # %
VELHA_S = 30.0


def gravar(soc: int, agora: float | None = None, arquivo: str = ARQUIVO) -> None:
    temporario = arquivo + ".tmp"
    with open(temporario, "w") as f:
        f.write(f"{int(soc)} {time.time() if agora is None else agora:.0f}\n")
    os.replace(temporario, arquivo)


def ler(arquivo: str = ARQUIVO, agora: float | None = None) -> int | None:
    """A carga em %, ou None sem arquivo, com leitura velha ou inválida."""
    try:
        with open(arquivo) as f:
            soc, quando = f.read().split()
        soc_i, quando_f = int(soc), float(quando)
    except (OSError, ValueError):
        return None
    if (time.time() if agora is None else agora) - quando_f > VELHA_S or not 0 <= soc_i <= 100:
        return None
    return soc_i


def nivel(soc: int | None) -> str:
    if soc is None:
        return "desconhecida"
    return "critica" if soc < MINIMO else "baixa" if soc < AVISO else "ok"


def pode_armar(soc: int | None) -> bool:
    return soc is None or soc >= MINIMO


def main(argv: list[str] | None = None) -> int:
    """`python3 -m core.bateria --pode-armar`: 0 se pode subir armado, 1 (com o motivo) se não."""
    args = sys.argv[1:] if argv is None else argv
    soc = ler()
    if args == ["--pode-armar"]:
        if not pode_armar(soc):
            print(f"ERRO: bateria em {soc}%: abaixo de {MINIMO}% o G1 agacha sozinho. Troque a bateria antes de armar.")
            return 1
        if soc is None:
            print("AVISO: carga da bateria desconhecida (o ipe-controle está de pé?); confira no controle da Unitree.")
        elif soc < AVISO:
            print(f"AVISO: bateria em {soc}%: troque logo.")
        return 0
    print("desconhecida" if soc is None else f"{soc}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
