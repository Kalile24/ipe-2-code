"""Laço puro do retorno: depois da meia-volta, anda até o ponto de partida e vira para a pessoa.

Puro: recebe a posição e o rumo da odometria (rt/odommodestate, referencial do mundo) e o tempo,
devolve as velocidades e o estado. Spec: docs/superpowers/specs/2026-11-10-retorno-escuta-painel-design.md

- O ponto de partida P0 é marcado quando a rotina começa (antes de virar/aproximar).
- A pessoa fica na direção P0 → B, onde B é a posição no começo do retorno (o robô girou no lugar).
- Andar: rumo corrigido para P0; erro de rumo grande gira no lugar antes de andar.
- Virar: até o rumo absoluto P0 → B (não "mais 180°"), para os erros não se acumularem.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

ANDANDO = "andando"
VIRANDO = "virando"
CHEGOU = "chegou"
FALHOU_TEMPO = "tempo esgotado"
FALHOU_AFASTANDO = "afastando do ponto de partida"
FALHOU_SEM_ODOMETRIA = "sem odometria"
ALINHAR_RAD = math.radians(45)  # erro de rumo acima disto: gira no lugar antes de andar
VYAW_MIN = 0.3  # rad/s: abaixo de ~0,22 o G1 não gira (meia-volta, 2026-11-07)
MARGEM_AFASTAR_M = 0.5


@dataclass(frozen=True)
class RetornoConfig:
    vx_retorno: float = 0.3  # m/s
    tolerancia_retorno_m: float = 0.15
    retorno_min_m: float = 0.3  # andou menos que isto até a pessoa: não volta (nem vira de novo)
    tempo_max_retorno_s: float = 30.0
    vyaw_retorno: float = 0.5  # rad/s, teto da correção de rumo e do giro final
    kp_rumo: float = 1.0  # vyaw = kp × erro de rumo (rad)
    tolerancia_rumo_graus: float = 8.0  # giro final


def diferenca(alvo: float, atual: float) -> float:
    """alvo − atual reduzido a (−π, π]: positivo = virar à esquerda."""
    return math.pi - (math.pi - (alvo - atual)) % (2 * math.pi)


def distancia(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def rumo(de: Tuple[float, float], para: Tuple[float, float]) -> float:
    return math.atan2(para[1] - de[1], para[0] - de[0])


def _giro(cfg: RetornoConfig, erro: float) -> float:
    """vyaw proporcional, com piso (senão não gira) e teto."""
    modulo = min(cfg.vyaw_retorno, max(VYAW_MIN, cfg.kp_rumo * abs(erro)))
    return math.copysign(modulo, erro)


def _valida(*valores: Optional[float]) -> bool:
    return all(v is not None and math.isfinite(v) for v in valores)


def passo_andar(
    cfg: RetornoConfig,
    pos: Optional[Tuple[float, float]],
    yaw: Optional[float],
    alvo: Tuple[float, float],
    distancia_inicial: float,
    decorrido_s: float,
) -> Tuple[float, float, str]:
    """(vx, vyaw, estado) de um passo da caminhada até `alvo` (P0)."""
    if pos is None or not _valida(pos[0], pos[1], yaw):
        return 0.0, 0.0, FALHOU_SEM_ODOMETRIA
    falta = distancia(pos, alvo)
    if falta <= cfg.tolerancia_retorno_m:
        return 0.0, 0.0, CHEGOU
    if falta > distancia_inicial + MARGEM_AFASTAR_M:
        return 0.0, 0.0, FALHOU_AFASTANDO
    if decorrido_s >= cfg.tempo_max_retorno_s:
        return 0.0, 0.0, FALHOU_TEMPO
    erro = diferenca(rumo(pos, alvo), yaw)
    if abs(erro) > ALINHAR_RAD:
        return 0.0, _giro(cfg, erro), ANDANDO  # alinha no lugar (ex.: a meia-volta parou torta)
    vx = min(cfg.vx_retorno, max(0.1, falta))  # desacelera no último metro, sem ficar parado
    vyaw = max(-cfg.vyaw_retorno, min(cfg.vyaw_retorno, cfg.kp_rumo * erro))
    return vx, vyaw, ANDANDO


def passo_virar(cfg: RetornoConfig, yaw: Optional[float], rumo_alvo: float, decorrido_s: float) -> Tuple[float, str]:
    """(vyaw, estado) de um passo do giro final até `rumo_alvo` (de frente para a pessoa)."""
    if not _valida(yaw):
        return 0.0, FALHOU_SEM_ODOMETRIA
    erro = diferenca(rumo_alvo, yaw)
    if abs(erro) <= math.radians(cfg.tolerancia_rumo_graus):
        return 0.0, CHEGOU
    if decorrido_s >= cfg.tempo_max_retorno_s:
        return 0.0, FALHOU_TEMPO
    return _giro(cfg, erro), VIRANDO
