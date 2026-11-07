"""Laço puro da meia-volta: gira 180° para a esquerda medindo o yaw da IMU.

Puro: recebe o ângulo já acumulado e o tempo, devolve a velocidade de giro e o estado. Spec:
docs/superpowers/specs/2026-11-07-meia-volta-design.md
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

GIRANDO = "girando"
CHEGOU = "chegou"
FALHOU_TEMPO = "tempo esgotado"
FALHOU_SENTIDO = "girou para o lado errado"
FALHOU_SEM_ANGULO = "sem angulo"
SEM_GIRO_S = 2.0  # depois disto girando, menos de SEM_GIRO_GRAUS é IMU parada
SEM_GIRO_GRAUS = 5.0


@dataclass(frozen=True)
class MeiaVoltaConfig:
    vyaw_meia_volta: float = 0.5  # rad/s, positivo = esquerda; 0,22 não girou o G1
    tolerancia_meia_volta_graus: float = 10.0
    passo_m: float = 0.2  # 0 = sem passo depois do giro
    vx_passo: float = 0.2  # m/s
    tempo_max_meia_volta_s: float = 12.0


def acumular(girado: float, yaw_anterior: float, yaw: float) -> float:
    """Soma a variação de yaw ao ângulo já girado, com a diferença reduzida a (−π, π]."""
    d = yaw - yaw_anterior
    return girado + math.pi - (math.pi - d) % (2 * math.pi)


def passo_giro(cfg: MeiaVoltaConfig, girado: Optional[float], decorrido_s: float) -> Tuple[float, str]:
    """(vyaw, estado) de um passo: gira enquanto falta ângulo e há tempo; para em chegou ou falhou."""
    if girado is None or not math.isfinite(girado):
        return 0.0, FALHOU_SEM_ANGULO
    tol = math.radians(cfg.tolerancia_meia_volta_graus)
    if girado >= math.pi - tol:
        return 0.0, CHEGOU
    if girado <= -tol:
        return 0.0, FALHOU_SENTIDO
    if decorrido_s >= SEM_GIRO_S and abs(girado) < math.radians(SEM_GIRO_GRAUS):
        return 0.0, FALHOU_SEM_ANGULO  # comandou o giro e o yaw não saiu do lugar: IMU parada
    if decorrido_s >= cfg.tempo_max_meia_volta_s:
        return 0.0, FALHOU_TEMPO
    return cfg.vyaw_meia_volta, GIRANDO


def duracao_passo(cfg: MeiaVoltaConfig) -> float:
    """Segundos andando para a frente depois do giro. 0 se não há passo."""
    if cfg.passo_m == 0:
        return 0.0
    return cfg.passo_m / cfg.vx_passo
