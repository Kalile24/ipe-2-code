import re
from pathlib import Path

import pytest

from core.approach import (
    ANDANDO, DESISTIU_ROSTO, DESISTIU_TEMPO, LIMITES_OPERACAO, PRONTO, SEM_ROSTO, ApproachConfig, Comando,
    escolher_caixa, passo_aproximacao, validar_operacao,
)

CFG = ApproachConfig()

def _passo(caixa, aproximar=True, visto_em=0.0, agora=0.0, cfg=CFG):
    return passo_aproximacao(cfg, aproximar, caixa, visto_em, inicio=0.0, agora=agora)

def test_face_on_the_right_turns_right_with_negative_yaw():
    c = _passo((480.0, 50.0))  # desvio +0,5
    assert c.vyaw == pytest.approx(-0.3)  # -kp 0,6 × 0,5 = -0,3 (= -vyaw_max)
    assert c.vx == 0.0 and c.estado == ANDANDO  # desvio > centro_para_andar: só gira

def test_turn_is_clamped_and_can_be_inverted():
    assert _passo((640.0, 50.0)).vyaw == pytest.approx(-0.3)
    assert _passo((480.0, 50.0), cfg=ApproachConfig(inverter_giro=True)).vyaw == pytest.approx(0.3)

def test_walks_at_constant_speed_when_roughly_centred_and_far():
    c = _passo((352.0, 50.0))  # desvio +0,1
    assert c.vx == pytest.approx(0.2) and c.vyaw == 0.0  # dentro de centro_ok: não gira

def test_ready_when_centred_and_box_tall_enough():
    assert _passo((320.0, 90.0)).estado == PRONTO
    assert _passo((320.0, 90.0)).vx == 0.0

def test_turning_in_place_uses_at_least_vyaw_min():
    # No robô: desvio -0,37 → 0,22 rad/s parado por 20 s sem girar; 0,3 girou.
    c = _passo((320.0 - 0.37 * 320, 42.0), aproximar=False, cfg=ApproachConfig(vyaw_max=0.5))
    assert c.vx == 0.0 and c.vyaw == pytest.approx(0.3)
    c = _passo((320.0 + 0.37 * 320, 42.0), aproximar=False, cfg=ApproachConfig(vyaw_max=0.5, inverter_giro=True))
    assert c.vyaw == pytest.approx(0.3)  # o sinal invertido é mantido

def test_walking_keeps_the_fine_proportional_turn():
    c = _passo((320.0 - 0.2 * 320, 42.0))  # desvio -0,2: anda e corrige de leve
    assert c.vx == pytest.approx(0.2) and c.vyaw == pytest.approx(0.12)

def test_keeps_walking_while_correcting_up_to_centro_para_andar():
    c = _passo((320.0 - 0.35 * 320, 42.0))  # desvio -0,35: antes parava para girar; agora anda e gira
    assert c.vx == pytest.approx(0.2) and c.vyaw > 0
    assert _passo((320.0 - 0.5 * 320, 42.0)).vx == 0.0  # longe demais do centro: só gira

def test_close_enough_accepts_the_walking_tolerance():
    # No robô: caixa 94 px, desvio -0,17 → girava a 0,10 rad/s sem sair do lugar até o tempo_max.
    assert _passo((320.0 - 0.17 * 320, 94.0)).estado == PRONTO
    c = _passo((320.0 - 0.35 * 320, 94.0))  # perto, mas fora até da tolerância de andar: ainda gira
    assert c.estado == ANDANDO and c.vx == 0.0 and c.vyaw > 0

def test_turn_only_keeps_the_tight_tolerance():
    assert _passo((320.0 - 0.17 * 320, 94.0), aproximar=False).estado == ANDANDO

def test_turn_only_is_ready_once_centred():
    assert _passo((330.0, 10.0), aproximar=False).estado == PRONTO
    assert _passo((480.0, 10.0), aproximar=False).vx == 0.0

def test_stale_detection_stops_then_gives_up():
    assert _passo((480.0, 50.0), visto_em=0.0, agora=1.5) == Comando(0.0, 0.0, SEM_ROSTO)
    assert _passo((480.0, 50.0), visto_em=0.0, agora=5.5).estado == DESISTIU_ROSTO

def test_never_seen_gives_up_after_desistir_s():
    assert _passo(None, agora=4.0).estado == SEM_ROSTO
    assert _passo(None, agora=5.0).estado == DESISTIU_ROSTO

def test_gives_up_after_tempo_max():
    assert _passo((352.0, 50.0), visto_em=20.0, agora=20.0).estado == DESISTIU_TEMPO

def test_other_faces_are_ignored():
    caixas = [("marcos", 300.0, 120.0), ("gil", 100.0, 40.0), ("gil", 500.0, 60.0), ("desconhecido", 320.0, 200.0)]
    assert escolher_caixa(caixas, "gil") == (500.0, 60.0)
    assert escolher_caixa([("marcos", 300.0, 120.0)], "gil") is None

def test_never_walks_backwards_when_too_close():
    assert _passo((352.0, 300.0)).vx == 0.0


def test_stops_moving_one_second_after_the_last_sighting():
    # No robô: a câmera caía e ele seguia andando na última caixa e chegava perto demais.
    assert _passo((352.0, 50.0), visto_em=0.0, agora=1.0).vx == pytest.approx(0.2)
    c = _passo((352.0, 50.0), visto_em=0.0, agora=1.1)
    assert (c.vx, c.vyaw, c.estado) == (0.0, 0.0, SEM_ROSTO)

def test_package_config_stops_within_one_second():
    texto = (Path(__file__).parents[1] / "ros2_ws/src/robot_reaction_ros/config/operacao.yaml").read_text(encoding="utf-8")
    assert float(re.search(r"perda_rosto_s:\s*([\d.]+)", texto).group(1)) == 1.0

def test_vyaw_max_wins_over_vyaw_min():
    c = _passo((480.0, 50.0), aproximar=False, cfg=ApproachConfig(vyaw_max=0.2))
    assert c.vyaw == pytest.approx(-0.2)


def test_valid_operation_values_pass():
    from core.approach import validar_operacao

    validar_operacao({"vx": 0.2, "vyaw_max": 0.3, "centro_ok": 0.15, "centro_para_andar": 0.45, "centro_chegada": 0.3,
                      "perda_rosto_s": 1.0, "desistir_s": 10.0, "tempo_max_s": 30.0, "altura_caixa_alvo_px": 90.0})


@pytest.mark.parametrize("valores", [
    {"vx": 2.0},                                         # o "0.2" digitado errado
    {"vx": float("nan")},
    {"centro_ok": 0.5, "centro_para_andar": 0.45},       # parado entre os dois até o tempo_max
    {"centro_ok": 0.4, "centro_chegada": 0.3},
    {"perda_rosto_s": 5.0, "desistir_s": 2.0},
])
def test_unsafe_operation_values_are_refused(valores):
    from core.approach import validar_operacao

    with pytest.raises(ValueError):
        validar_operacao(valores)


def test_limites_da_meia_volta():
    assert LIMITES_OPERACAO["vyaw_meia_volta"] == (0.3, 0.8)
    assert LIMITES_OPERACAO["tolerancia_meia_volta_graus"] == (2.0, 30.0)
    assert LIMITES_OPERACAO["passo_m"] == (0.0, 0.5)
    assert LIMITES_OPERACAO["vx_passo"] == (0.05, 0.3)
    assert LIMITES_OPERACAO["tempo_max_meia_volta_s"] == (5.0, 30.0)
    with pytest.raises(ValueError):
        validar_operacao({"passo_m": 0.6})
