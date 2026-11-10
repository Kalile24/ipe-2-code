from __future__ import annotations

import pytest

from core import discurso
from core.reaction_policy import validate_steps


def test_sem_arquivo_vale_o_padrao(tmp_path):
    assert discurso.ler(str(tmp_path / "nao_existe.txt")) == discurso.PADRAO


def test_salvar_limpa_espacos_e_ler_devolve_o_salvo(tmp_path):
    arquivo = str(tmp_path / "data" / "discurso.txt")
    assert discurso.salvar("  Olá,\n  banca.  ", arquivo) == "Olá, banca."
    assert discurso.ler(arquivo) == "Olá, banca."


def test_vazio_ou_longo_demais_e_recusado_e_o_arquivo_fica(tmp_path):
    arquivo = str(tmp_path / "discurso.txt")
    discurso.salvar("Olá.", arquivo)
    for ruim in ("   ", "a" * (discurso.MAX_CARACTERES + 1)):
        with pytest.raises(ValueError):
            discurso.salvar(ruim, arquivo)
    assert discurso.ler(arquivo) == "Olá."


def test_passos_sao_uma_rotina_valida_que_termina_a_vontade():
    passos = discurso.passos(discurso.PADRAO)
    assert validate_steps("discurso", passos) == passos
    assert passos[1] == {"fala": discurso.PADRAO}
