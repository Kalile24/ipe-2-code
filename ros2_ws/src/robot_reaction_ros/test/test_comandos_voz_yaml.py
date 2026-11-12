from __future__ import annotations

import yaml
from ament_index_python.packages import get_package_share_directory

from core.comandos_voz import carregar_comandos, reconhecer


def test_yaml_do_pacote_carrega_e_tem_os_quatro():
    with open(get_package_share_directory("robot_reaction_ros") + "/config/comandos_voz.yaml") as f:
        tabela = carregar_comandos(yaml.safe_load(f))
    assert set(tabela.comandos) == {"sentido", "continencia", "apresentacao", "a_vontade"}
    assert "atencao" not in tabela.comandos  # desligado até resolver o desequilíbrio do descansar
    assert reconhecer(tabela, "atenção") is None
    assert tabela.nao_entendi == "Não entendi, repita o comando"
    assert reconhecer(tabela, "Tenente, apresente-se") == "apresentacao"
    assert reconhecer(tabela, "à vontade") == "a_vontade"
    assert tabela.comandos["apresentacao"][1] == [
        {"postura": "sentido"}, {"fala": "Sou o Tenente Nichinica"}, {"postura": "a_vontade"}]
