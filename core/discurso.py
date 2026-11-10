"""Fala de apresentação do robô (F3+R1 ou o painel): sentido, o texto e à vontade.

O texto fica em data/discurso.txt (fora do git; o painel grava) e é escrito como deve soar. Sem o
arquivo, vale o padrão. Lido a cada vez: salvar no painel vale na próxima fala, sem reiniciar nada.
"""
from __future__ import annotations

import os

ARQUIVO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "discurso.txt")
PADRAO = ("Olá oficiais, alunos e banca avaliadora, sou o Tenente Nichinica, "
          "o robô humanoide do projeto Níksi.")
MAX_CARACTERES = 600  # ~40 s de fala


def validar(texto: str) -> str:
    """Texto limpo (espaços normais, sem quebra de linha); ValueError se vazio ou longo demais."""
    limpo = " ".join(str(texto).split())
    if not limpo:
        raise ValueError("o discurso não pode ficar vazio")
    if len(limpo) > MAX_CARACTERES:
        raise ValueError(f"o discurso passa de {MAX_CARACTERES} caracteres ({len(limpo)})")
    return limpo


def ler(arquivo: str = ARQUIVO) -> str:
    """O texto salvo, ou o padrão se não houver arquivo ou ele estiver inválido."""
    try:
        with open(arquivo, encoding="utf-8") as f:
            return validar(f.read())
    except (OSError, ValueError):
        return PADRAO


def salvar(texto: str, arquivo: str = ARQUIVO) -> str:
    limpo = validar(texto)
    os.makedirs(os.path.dirname(arquivo), exist_ok=True)
    temporario = arquivo + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        f.write(limpo + "\n")
    os.replace(temporario, arquivo)  # quem lê no meio da gravação vê o antigo ou o novo, nunca a metade
    return limpo


def passos(texto: str) -> list[dict]:
    return [{"postura": "sentido"}, {"fala": texto}, {"postura": "a_vontade"}]
