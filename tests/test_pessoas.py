import pytest

from core.pessoas import nome_falado, rotina_padrao


def test_default_routine_keeps_the_gesture_and_changes_the_rank():
    assert rotina_padrao("coronel veterano", "Aderson") == {"passos": [
        {"postura": "sentido"},
        {"postura": "continencia"},
        {"fala": "Olá, coronel veterano Aderson, sou o Tenente Nichinica"},
        {"postura": "desc_arma"},
        {"postura": "a_vontade"},
    ]}


@pytest.mark.parametrize("tratamento, nome", [("", "Ana"), ("coronel", ""), ("  ", "Ana"), ("a\nb", "Ana"), ("x" * 81, "Ana")])
def test_invalid_rank_or_name_is_refused(tratamento, nome):
    with pytest.raises(ValueError):
        rotina_padrao(tratamento, nome)


@pytest.mark.parametrize("chave, falado", [("gil", "Gil"), ("ze_batista", "Ze Batista")])
def test_spoken_name_comes_from_the_key(chave, falado):
    assert nome_falado(chave) == falado
