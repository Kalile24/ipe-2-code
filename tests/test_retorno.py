from __future__ import annotations

import math

from core.retorno import (
    ANDANDO, CHEGOU, FALHOU_AFASTANDO, FALHOU_SEM_ODOMETRIA, FALHOU_TEMPO, VIRANDO, VYAW_MIN, RetornoConfig,
    diferenca, passo_andar, passo_virar, rumo,
)

CFG = RetornoConfig()
P0 = (0.0, 0.0)


def test_diferenca_passa_pela_virada_de_mais_menos_180():
    assert math.isclose(diferenca(math.radians(170), math.radians(-170)), math.radians(-20))
    assert math.isclose(diferenca(math.radians(-170), math.radians(170)), math.radians(20))


def test_de_frente_para_o_ponto_anda_reto():
    # robô em (2, 0) olhando para trás (yaw = π), o ponto de partida está em (0, 0)
    vx, vyaw, estado = passo_andar(CFG, (2.0, 0.0), math.pi, P0, 2.0, 1.0)
    assert estado == ANDANDO and vx == CFG.vx_retorno and abs(vyaw) < 1e-9


def test_um_pouco_torto_corrige_o_rumo_andando():
    # olhando 171° (um pouco para +y) e o ponto está a 180°: corrige para a esquerda
    vx, vyaw, _ = passo_andar(CFG, (2.0, 0.0), math.pi - 0.2, P0, 2.0, 1.0)
    assert vx > 0 and vyaw > 0
    vx, vyaw, _ = passo_andar(CFG, (2.0, 0.0), -math.pi + 0.2, P0, 2.0, 1.0)
    assert vx > 0 and vyaw < 0  # o espelho: −171°, corrige para a direita


def test_muito_torto_gira_no_lugar_antes_de_andar():
    vx, vyaw, estado = passo_andar(CFG, (2.0, 0.0), math.pi / 2, P0, 2.0, 1.0)
    assert estado == ANDANDO and vx == 0.0 and abs(vyaw) >= VYAW_MIN


def test_perto_do_ponto_chega_e_desacelera_antes():
    assert passo_andar(CFG, (0.1, 0.0), math.pi, P0, 2.0, 5.0)[2] == CHEGOU
    vx, _, _ = passo_andar(CFG, (0.2, 0.0), math.pi, P0, 2.0, 5.0)
    assert 0.1 <= vx < CFG.vx_retorno


def test_falhas_param_o_robo():
    assert passo_andar(CFG, (3.0, 0.0), math.pi, P0, 2.0, 1.0)[:2] == (0.0, 0.0)  # afastando
    assert passo_andar(CFG, (3.0, 0.0), math.pi, P0, 2.0, 1.0)[2] == FALHOU_AFASTANDO
    assert passo_andar(CFG, (1.0, 0.0), math.pi, P0, 2.0, CFG.tempo_max_retorno_s)[2] == FALHOU_TEMPO
    assert passo_andar(CFG, None, math.pi, P0, 2.0, 1.0)[2] == FALHOU_SEM_ODOMETRIA
    assert passo_andar(CFG, (1.0, float("nan")), math.pi, P0, 2.0, 1.0)[2] == FALHOU_SEM_ODOMETRIA


def test_giro_final_vira_para_a_pessoa_pelo_lado_mais_curto():
    para_pessoa = rumo(P0, (2.0, 0.0))  # a pessoa estava em +x: rumo 0
    vyaw, estado = passo_virar(CFG, math.pi - 0.3, para_pessoa, 1.0)  # chegou olhando quase para trás
    assert estado == VIRANDO and vyaw < 0  # de 171° até 0°: o lado mais curto é pela direita
    assert passo_virar(CFG, math.radians(5), para_pessoa, 1.0) == (0.0, CHEGOU)
    assert passo_virar(CFG, None, para_pessoa, 1.0)[1] == FALHOU_SEM_ODOMETRIA
    assert passo_virar(CFG, 2.0, para_pessoa, CFG.tempo_max_retorno_s)[1] == FALHOU_TEMPO


def test_padroes_dentro_das_faixas_do_painel_e_toda_faixa_existe():
    from dataclasses import asdict, fields

    from core.approach import LIMITES_OPERACAO, validar_operacao

    validar_operacao(asdict(RetornoConfig()))
    assert all(f.name in LIMITES_OPERACAO for f in fields(RetornoConfig))
