from __future__ import annotations

from core import bateria


def test_grava_e_le_a_carga_recente(tmp_path):
    arquivo = str(tmp_path / "bat.txt")
    bateria.gravar(57, agora=1000.0, arquivo=arquivo)
    assert bateria.ler(arquivo, agora=1010.0) == 57


def test_leitura_velha_ausente_ou_invalida_e_desconhecida(tmp_path):
    arquivo = str(tmp_path / "bat.txt")
    assert bateria.ler(arquivo) is None
    bateria.gravar(57, agora=1000.0, arquivo=arquivo)
    assert bateria.ler(arquivo, agora=1000.0 + bateria.VELHA_S + 1) is None
    (tmp_path / "bat.txt").write_text("lixo")
    assert bateria.ler(arquivo) is None


def test_niveis_e_quando_pode_armar():
    assert bateria.nivel(4) == "critica" and not bateria.pode_armar(4)  # o G1 agachou com 4%
    assert bateria.nivel(bateria.MINIMO) == "baixa" and bateria.pode_armar(bateria.MINIMO)
    assert bateria.nivel(bateria.AVISO) == "ok"
    assert bateria.nivel(None) == "desconhecida" and bateria.pode_armar(None)  # avisa, não impede


def test_comando_da_subida_recusa_bateria_critica(tmp_path, monkeypatch, capsys):
    arquivo = str(tmp_path / "bat.txt")
    monkeypatch.setattr(bateria, "ARQUIVO", arquivo)
    monkeypatch.setattr(bateria.ler, "__defaults__", (arquivo, None))
    bateria.gravar(4, arquivo=arquivo)
    assert bateria.main(["--pode-armar"]) == 1 and "4%" in capsys.readouterr().out
    bateria.gravar(15, arquivo=arquivo)
    assert bateria.main(["--pode-armar"]) == 0 and "15%" in capsys.readouterr().out
