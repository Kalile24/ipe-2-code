"""Formulário de operação do painel: um data/operacao.yaml antigo não pode impedir de salvar."""
import yaml

from robot_reaction_ros import painel_node as painel_mod
from robot_reaction_ros.painel_node import PainelNode


def _yaml(caminho, parametros):
    caminho.write_text(yaml.safe_dump({"/**": {"ros__parameters": parametros}}))


def _painel(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    _yaml(tmp_path / "config" / "operacao.yaml", {"vx": 0.2, "vyaw_min": 0.3, "centro_chegada": 0.3})
    monkeypatch.setattr(painel_mod, "get_package_share_directory", lambda _pacote: str(tmp_path))
    painel = PainelNode.__new__(PainelNode)  # sem o __init__: não precisa de ROS rodando
    painel._operacao_file = str(tmp_path / "operacao.yaml")
    return painel


def test_saved_file_older_than_a_new_field_shows_the_package_value(tmp_path, monkeypatch):
    painel = _painel(tmp_path, monkeypatch)
    _yaml(tmp_path / "operacao.yaml", {"vx": 0.1})
    assert painel.operacao() == {"vx": 0.1, "vyaw_min": 0.3, "centro_chegada": 0.3}


def test_form_saves_over_a_file_older_than_a_new_field(tmp_path, monkeypatch):
    painel = _painel(tmp_path, monkeypatch)
    _yaml(tmp_path / "operacao.yaml", {"vx": 0.1})
    painel.salvar_operacao({"vyaw_min": "0.25"})
    salvo = yaml.safe_load((tmp_path / "operacao.yaml").read_text())["/**"]["ros__parameters"]
    assert salvo == {"vx": 0.1, "vyaw_min": 0.25, "centro_chegada": 0.3}
