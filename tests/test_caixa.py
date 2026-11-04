import pytest

from core.caixa import CAIXA_PADRAO, caixa_atual, mac_valido, nome_do_sink, ler_dispositivos


def test_without_a_saved_speaker_the_default_is_used(tmp_path):
    assert caixa_atual(str(tmp_path / "nao_existe.txt")) == CAIXA_PADRAO == "A8:AA:CD:C6:5C:A3"


def test_saved_speaker_wins(tmp_path):
    arquivo = tmp_path / "caixa.txt"
    arquivo.write_text("11:22:33:44:55:66\n")
    assert caixa_atual(str(arquivo)) == "11:22:33:44:55:66"


def test_garbage_in_the_file_falls_back_to_the_default(tmp_path):
    arquivo = tmp_path / "caixa.txt"
    arquivo.write_text("; rm -rf /")
    assert caixa_atual(str(arquivo)) == CAIXA_PADRAO


@pytest.mark.parametrize("mac, ok", [("A8:AA:CD:C6:5C:A3", True), ("a8:aa:cd:c6:5c:a3", False), ("A8:AA", False), ("A8:AA:CD:C6:5C:A3;x", False)])
def test_mac_validation(mac, ok):
    assert mac_valido(mac) is ok


def test_sink_name_uses_underscores():
    assert nome_do_sink("A8:AA:CD:C6:5C:A3") == "A8_AA_CD_C6_5C_A3"


def test_device_list_is_parsed_and_noise_ignored():
    saida = "[NEW] x\nDevice A8:AA:CD:C6:5C:A3 KD-833\nDevice 11:22:33:44:55:66 Caixa Nova 2\nlixo\n"
    assert ler_dispositivos(saida) == [
        {"mac": "A8:AA:CD:C6:5C:A3", "nome": "KD-833"},
        {"mac": "11:22:33:44:55:66", "nome": "Caixa Nova 2"},
    ]
