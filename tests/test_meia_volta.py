from __future__ import annotations

import math

import pytest

from core.meia_volta import (
    CHEGOU,
    FALHOU_SEM_ANGULO,
    FALHOU_SENTIDO,
    FALHOU_TEMPO,
    GIRANDO,
    MeiaVoltaConfig,
    acumular,
    duracao_passo,
    passo_giro,
)


def test_girado_atravessa_mais_menos_pi():
    g = acumular(0.0, math.radians(170), math.radians(-170))
    assert g == pytest.approx(math.radians(20))


def test_gira_para_a_esquerda_ate_chegar():
    cfg = MeiaVoltaConfig()
    assert passo_giro(cfg, math.radians(90), 2.0) == (0.5, GIRANDO)
    assert passo_giro(cfg, math.radians(171), 4.0) == (0.0, CHEGOU)


def test_lado_errado_falha():
    assert passo_giro(MeiaVoltaConfig(), math.radians(-11), 1.0)[1] == FALHOU_SENTIDO


def test_tempo_esgotado():
    assert passo_giro(MeiaVoltaConfig(), math.radians(90), 12.0)[1] == FALHOU_TEMPO


def test_sem_angulo_nao_gira():
    assert passo_giro(MeiaVoltaConfig(), float("nan"), 0.0) == (0.0, FALHOU_SEM_ANGULO)
    assert passo_giro(MeiaVoltaConfig(), None, 0.0) == (0.0, FALHOU_SEM_ANGULO)


def test_imu_parada_depois_de_2s_falha_sem_angulo():
    cfg = MeiaVoltaConfig()
    assert passo_giro(cfg, math.radians(4), 2.0) == (0.0, FALHOU_SEM_ANGULO)
    assert passo_giro(cfg, math.radians(4), 1.9) == (0.5, GIRANDO)
    assert passo_giro(cfg, math.radians(6), 2.0) == (0.5, GIRANDO)


def test_duracao_do_passo():
    assert duracao_passo(MeiaVoltaConfig()) == pytest.approx(1.0)
    assert duracao_passo(MeiaVoltaConfig(passo_m=0.0)) == 0.0
