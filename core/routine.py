"""Executa a rotina de uma pessoa: posturas militares e falas, na ordem do reactions.yaml.

Puro: o corpo (posturas) e a voz chegam como funções. No robô são o G1ArmController do ~/hhhh e o
servidor Piper (body_node); nos testes, dublês. Quem chama garante que só uma rotina roda por vez.
"""
from __future__ import annotations

import time
from typing import Callable

from core.reaction_policy import A_VONTADE


def run_routine(
    passos: list[dict[str, str]],
    postura: Callable[[str], bool],
    falar: Callable[[str], None],
    pausa_s: float = 2.0,
    log: Callable[[str], None] = print,
    deve_parar: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Roda os passos em ordem; True se todos deram certo.

    - Depois de cada postura (menos a do último passo), espera `pausa_s`: o gesto fica legível.
    - Fala que falha só é registrada: o movimento não depende do som.
    - Postura que falha encerra a rotina e tenta `a_vontade`, para não deixar o braço preso
      numa pose intermediária (o mesmo que o operador faria com F1+RIGHT).
    - `deve_parar()` é conferido antes de cada passo (Ctrl+C no meio da rotina).
    """
    for i, passo in enumerate(passos):
        if deve_parar():
            log("rotina interrompida")
            return False
        if "fala" in passo:
            texto = passo["fala"]
            log(f"fala: {texto}")
            try:
                falar(texto)
            except Exception as exc:  # sem caixa ou sem Piper: segue sem som
                log(f"fala falhou: {exc!r}")
            continue
        nome = passo["postura"]
        log(f"postura: {nome}")
        if not _tentar(postura, nome, log):
            log(f"postura {nome} falhou; rotina encerrada")
            if nome != A_VONTADE:
                log(f"tentando {A_VONTADE} para soltar os braços")
                _tentar(postura, A_VONTADE, log)
            return False
        if i < len(passos) - 1:
            sleep(pausa_s)
    return True


def _tentar(postura: Callable[[str], bool], nome: str, log: Callable[[str], None]) -> bool:
    try:
        return bool(postura(nome))
    except Exception as exc:  # erro do SDK não pode derrubar a rotina sem soltar os braços
        log(f"erro na postura {nome}: {exc!r}")
        return False
