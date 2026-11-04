"""Laço de aproximação em pixels: gira até centrar o rosto do alvo e anda até a caixa ficar alta o bastante.

Puro: recebe a caixa do rosto e o tempo, devolve a velocidade a comandar. Spec:
docs/superpowers/specs/2026-11-04-aproximacao-e-estagios-design.md
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

ANDANDO = "andando"
SEM_ROSTO = "sem_rosto"
PRONTO = "pronto"
DESISTIU_ROSTO = "desistiu: rosto perdido"
DESISTIU_TEMPO = "desistiu: tempo esgotado"


@dataclass(frozen=True)
class ApproachConfig:
    largura_imagem: int = 640
    altura_caixa_alvo_px: float = 90.0
    inverter_giro: bool = False
    centro_ok: float = 0.15
    centro_para_andar: float = 0.45  # 0,30 fazia o anda-e-para com a pessoa oscilando perto do limite
    centro_chegada: float = 0.30  # já perto: desvio aceito como "de frente" para cumprimentar
    vyaw_max: float = 0.3
    vyaw_min: float = 0.3  # giro no lugar abaixo disso o G1 não executa (0,22 não girou; 0,3 girou)
    vx: float = 0.2
    kp_giro: float = 0.6
    perda_rosto_s: float = 1.0
    desistir_s: float = 5.0
    tempo_max_s: float = 20.0


@dataclass(frozen=True)
class Comando:
    vx: float
    vyaw: float
    estado: str


def escolher_caixa(caixas: List[Tuple[str, float, float]], nome: str) -> Optional[Tuple[float, float]]:
    """Devolve (center_x, size_y) da maior caixa com o nome, ou None."""
    doalvo = [(cx, sy) for n, cx, sy in caixas if n == nome]
    return max(doalvo, key=lambda c: c[1]) if doalvo else None


def passo_aproximacao(
    cfg: ApproachConfig,
    aproximar: bool,
    caixa: Optional[Tuple[float, float]],
    visto_em: float,
    inicio: float,
    agora: float,
) -> Comando:
    """Um passo do laço. PRONTO e DESISTIU_* encerram o estágio."""
    if agora - inicio >= cfg.tempo_max_s:
        return Comando(0.0, 0.0, DESISTIU_TEMPO)
    if caixa is None or agora - visto_em > cfg.perda_rosto_s:
        return Comando(0.0, 0.0, DESISTIU_ROSTO if agora - visto_em >= cfg.desistir_s else SEM_ROSTO)
    centro_x, altura = caixa
    meia = cfg.largura_imagem / 2
    desvio = (centro_x - meia) / meia
    vyaw = 0.0
    if abs(desvio) > cfg.centro_ok:
        vyaw = max(-cfg.vyaw_max, min(cfg.vyaw_max, -cfg.kp_giro * desvio))
        if cfg.inverter_giro:
            vyaw = -vyaw
    longe = altura < cfg.altura_caixa_alvo_px
    vx = cfg.vx if aproximar and longe and abs(desvio) < cfg.centro_para_andar else 0.0
    if vx == 0.0 and vyaw != 0.0 and abs(vyaw) < cfg.vyaw_min:
        # Parado, o giro proporcional fino não sai do lugar: gira no mínimo que o G1 executa.
        # Andando, o giro fino funciona (o passo para frente já movimenta as pernas).
        vyaw = math.copysign(min(cfg.vyaw_min, cfg.vyaw_max), vyaw)
    # Já perto: aceita centro_chegada. Exigir centro_ok ali prendia o robô até o tempo_max (no
    # G1, o giro fino de ~0,1 rad/s perto do centro não chega a girar).
    tolerancia = cfg.centro_chegada if aproximar and not longe else cfg.centro_ok
    if abs(desvio) <= tolerancia and (not aproximar or not longe):
        return Comando(0.0, 0.0, PRONTO)
    return Comando(vx, vyaw, ANDANDO)
