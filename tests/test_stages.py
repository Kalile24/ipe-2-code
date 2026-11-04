import pytest

from core.stages import ESTAGIOS, filter_steps, parse_stages

GIL = [
    {"postura": "sentido"}, {"postura": "continencia"},
    {"fala": "Olá, aspirante a oficial da reserva Gil, sou o Tenente Nichinica"},
    {"postura": "desc_arma"}, {"postura": "descansar"}, {"pausa": 15}, {"postura": "a_vontade"},
]

def test_all_stages_by_default_text():
    assert parse_stages("virar,aproximar,fala,posturas") == frozenset(ESTAGIOS)

def test_approach_implies_turning():
    assert parse_stages(" aproximar , fala ") == {"aproximar", "virar", "fala"}

@pytest.mark.parametrize("texto", ["", " , ", "virar,pular"])
def test_invalid_stages_fail_naming_the_valid_ones(texto):
    with pytest.raises(ValueError, match="posturas"):
        parse_stages(texto)

def test_only_speech_drops_postures_and_pauses():
    assert filter_steps(GIL, frozenset({"fala"})) == [GIL[2]]

def test_only_postures_keeps_pause_and_drops_speech():
    assert filter_steps(GIL, frozenset({"posturas"})) == [s for s in GIL if "fala" not in s]

def test_filter_can_leave_nothing():
    assert filter_steps([{"fala": "oi"}], frozenset({"posturas"})) == []

def test_movement_stages_do_not_filter_steps():
    assert filter_steps(GIL, frozenset(ESTAGIOS)) == GIL
