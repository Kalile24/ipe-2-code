import pytest

from core.approach import (
    ANDANDO, DESISTIU_ROSTO, DESISTIU_TEMPO, PRONTO, SEM_ROSTO, ApproachConfig, Comando, escolher_caixa,
    passo_aproximacao,
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
