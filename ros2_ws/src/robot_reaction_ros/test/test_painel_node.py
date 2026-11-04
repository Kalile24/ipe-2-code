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


def _pessoas(painel_mod, tmp_path, monkeypatch, nos=()):
    painel = _painel(tmp_path, monkeypatch)
    (tmp_path / "config" / "reactions.yaml").write_text(
        'gil:\n  passos:\n    - fala: "oi"\naderson:\n  passos:\n    - fala: "oi"\n'
    )
    monkeypatch.setattr(painel_mod, "ARQ_REACOES", str(tmp_path / "reactions.yaml"))
    monkeypatch.setattr(painel_mod, "DB_BASE", str(tmp_path / "identity_db"))
    painel.get_node_names = lambda: list(nos)
    return painel


def _banco(tmp_path, *nomes):
    import numpy as np

    from core.identity_store import IdentityStore

    store = IdentityStore(str(tmp_path / "identity_db"), model_name=painel_mod.MODEL_NAME)
    for nome in nomes:
        store.enroll(nome, [np.array([1.0, 0.0])])
    store.save()


def test_people_list_shows_photos_and_routines(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    _banco(tmp_path, "gil", "ze_batista")
    assert painel.pessoas() == [
        {"nome": "aderson", "fotos": 0, "rotina": True, "padrao": True},
        {"nome": "gil", "fotos": 1, "rotina": True, "padrao": True},
        {"nome": "ze_batista", "fotos": 1, "rotina": False, "padrao": False},
    ]


def test_new_person_gets_the_default_routine(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    assert painel.salvar_pessoa("ana", "capitã", "")["ok"] is True
    salvo = yaml.safe_load((tmp_path / "reactions.yaml").read_text())
    assert salvo["ana"]["passos"][2] == {"fala": "Olá, capitã Ana, sou o Tenente Nichinica"}
    assert "ana" in painel.pessoas_com_rotina()


def test_panel_cannot_change_a_package_routine(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    assert painel.salvar_pessoa("gil", "general", "")["ok"] is False
    assert not (tmp_path / "reactions.yaml").exists()


def test_invalid_key_is_refused(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    assert painel.salvar_pessoa("Ana Maria", "capitã", "")["ok"] is False


def test_removing_needs_the_routine_stopped(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch, nos=["face_recognition_node"])
    _banco(tmp_path, "ze_batista")
    assert painel.remover_pessoa("ze_batista")["ok"] is False
    assert painel.pessoas()[-1]["fotos"] == 1


def test_removing_clears_photos_and_added_routine(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    _banco(tmp_path, "gil", "ana")
    painel.salvar_pessoa("ana", "capitã", "")
    assert painel.remover_pessoa("ana")["ok"] is True
    assert [p["nome"] for p in painel.pessoas()] == ["aderson", "gil"]


def test_removing_a_package_person_keeps_the_routine_and_drops_the_photos(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    _banco(tmp_path, "gil")
    assert painel.remover_pessoa("gil")["ok"] is True
    assert {"nome": "gil", "fotos": 0, "rotina": True, "padrao": True} in painel.pessoas()


def test_speaker_that_does_not_connect_is_not_saved(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    arquivo = tmp_path / "caixa.txt"
    monkeypatch.setattr(painel_mod, "ARQ_CAIXA", str(arquivo))
    monkeypatch.setattr(painel_mod, "_comando", lambda *a, **k: "Connected: no")
    assert painel.usar_caixa("11:22:33:44:55:66")["ok"] is False
    assert not arquivo.exists()


def test_speaker_that_connects_is_saved_and_can_go_back(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    arquivo = tmp_path / "caixa.txt"
    monkeypatch.setattr(painel_mod, "ARQ_CAIXA", str(arquivo))
    monkeypatch.setattr(painel_mod, "tocar", lambda _nome: None)
    monkeypatch.setattr(painel_mod, "_comando", lambda *a, **k: "Connected: yes\n1 bluez_sink.11_22_33_44_55_66.a2dp_sink x\n2 bluez_sink.A8_AA_CD_C6_5C_A3.a2dp_sink y")
    assert painel.usar_caixa("11:22:33:44:55:66")["ok"] is True
    assert arquivo.read_text().strip() == "11:22:33:44:55:66"
    assert painel.usar_caixa("isto nao e um mac")["ok"] is False
    painel.usar_caixa(painel_mod.CAIXA_PADRAO)
    assert not arquivo.exists()
