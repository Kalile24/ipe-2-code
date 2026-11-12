import pytest

from core.stages import ESTAGIOS, filter_steps, migrar_estagios, override_estagios, parse_stages

GIL = [
    {"postura": "sentido"}, {"postura": "continencia"},
    {"fala": "Olá, aspirante a oficial da reserva Gil, sou o Tenente Nichinica"},
    {"postura": "desc_arma"}, {"postura": "descansar"}, {"pausa": 15}, {"postura": "a_vontade"},
]

def test_all_stages_by_default_text():
    assert parse_stages("virar,aproximar,fala,posturas,meia_volta,retorno") == frozenset(ESTAGIOS)

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


def test_meia_volta_e_um_estagio_valido():
    assert parse_stages("posturas,meia_volta") == frozenset({"posturas", "meia_volta"})

def test_migra_estagios_de_arquivo_antigo():
    assert migrar_estagios({"estagios": "virar,fala"})["estagios"] == "virar,fala,meia_volta"

def test_migra_estagios_nao_mexe_em_arquivo_novo():
    v = {"estagios": "virar,fala", "vyaw_meia_volta": 0.5}
    assert migrar_estagios(v) == v

def test_migra_estagios_nao_duplica():
    assert migrar_estagios({"estagios": "fala,meia_volta"})["estagios"] == "fala,meia_volta"


def test_override_estagios():
    assert override_estagios({"estagios": "virar,fala"}) == "virar,fala,meia_volta"
    assert override_estagios({"estagios": "fala", "vyaw_meia_volta": 0.5}) is None
    assert override_estagios({}) is None
