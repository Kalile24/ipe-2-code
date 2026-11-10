from __future__ import annotations

from core.comandos_voz import ComandosVoz, normalizar, posicao_final, reconhecer, transicao


def _tabela():
    return ComandosVoz(
        nao_entendi="Não entendi, repita o comando",
        comandos={
            "sentido": (["sentido"], [{"postura": "sentido"}]),
            "continencia": (["continencia"], [{"postura": "continencia"}]),
        },
    )


def test_normaliza_acento_e_pontuacao():
    assert normalizar("Tenente, À VONTADE!") == "tenente a vontade"


def test_reconhece_palavra_inteira():
    t = _tabela()
    assert reconhecer(t, "Tenente, sentido!") == "sentido"
    assert reconhecer(t, "ressentido") is None


def test_dois_comandos_nao_valem():
    assert reconhecer(_tabela(), "sentido e continência") is None


def test_frase_vazia():
    assert reconhecer(_tabela(), "  ") is None


def test_frase_de_varias_palavras():
    t = ComandosVoz("x", {"a_vontade": (["a vontade"], [{"postura": "a_vontade"}])})
    assert reconhecer(t, "Tenente, à vontade!") == "a_vontade"
    assert reconhecer(t, "gravidade vontade") is None


def test_de_continencia_para_sentido_passa_por_desc_arma():
    assert transicao("continencia", [{"postura": "sentido"}]) == [{"postura": "desc_arma"}, {"postura": "sentido"}]
    assert transicao("continencia", [{"postura": "descansar"}])[0] == {"postura": "desc_arma"}


def test_de_continencia_para_a_vontade_vai_direto():
    assert transicao("continencia", [{"postura": "a_vontade"}]) == [{"postura": "a_vontade"}]


def test_mesma_posicao_nao_faz_nada():
    assert transicao("sentido", [{"postura": "sentido"}]) == []


def test_a_vontade_sem_posicao_nao_faz_nada():
    assert transicao(None, [{"postura": "a_vontade"}]) == []


def test_apresentacao_com_fala_roda_mesmo_sem_posicao():
    passos = [{"postura": "sentido"}, {"fala": "oi"}, {"postura": "a_vontade"}]
    assert transicao(None, passos) == passos


def test_posicao_final():
    assert posicao_final(None, [{"postura": "sentido"}]) == "sentido"
    assert posicao_final("sentido", [{"postura": "a_vontade"}]) is None
    assert posicao_final("sentido", [{"fala": "oi"}]) == "sentido"


def test_carregar_rejeita_tabela_incompleta():
    import pytest

    from core.comandos_voz import carregar_comandos
    from core.reaction_policy import ReactionConfigError

    ok = {"palavras": ["x"], "passos": [{"postura": "sentido"}]}
    for raw in (None, {"comandos": {"a": ok}}, {"nao_entendi": "n"}, {"nao_entendi": "n", "comandos": {"a": {**ok, "palavras": []}}}):
        with pytest.raises(ReactionConfigError):
            carregar_comandos(raw)
    assert carregar_comandos({"nao_entendi": "n", "comandos": {"a": ok}}).comandos["a"][0] == ["x"]


def test_enviar_voz_chega_por_udp():
    import socket

    from core.comandos_voz import enviar_voz

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        s.settimeout(1)
        enviar_voz("comando:sentido", s.getsockname()[1])
        assert s.recv(100) == b"comando:sentido"


def test_gramatica_aceita_o_comando_sozinho_ou_com_o_vocativo():
    from core.comandos_voz import carregar_comandos, gramatica

    raw = {"nao_entendi": "n", "comandos": {
        "a_vontade": {"palavras": ["À  Vontade"], "passos": [{"postura": "a_vontade"}]},
        "sentido": {"palavras": ["sentido"], "passos": [{"postura": "sentido"}]},
    }}
    tabela = carregar_comandos(raw)
    assert tabela.frases == ["à vontade", "sentido"]
    assert gramatica(tabela) == [
        "à vontade", "sentido",
        "tenente à vontade", "tenente sentido",
        "tenente [unk] à vontade", "tenente [unk] sentido",
        "[unk]",
    ]
    assert tabela.comandos["a_vontade"][0] == ["a vontade"]  # a comparação continua sem acento
