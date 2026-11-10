"""Testes do voz_node: gravador, transcrição, fala e ação dublês; os datagramas entram direto no tratador."""
from __future__ import annotations

import json
import threading
import time

import pytest
import rclpy
from std_msgs.msg import String

import robot_reaction_ros.voz_node as voz_mod
from test_reaction_node import _FakeRotina


class _Gravador:
    def __init__(self, dispositivo, falha=None, pcm=b"\x01\x02"):
        self.falha, self.pcm, self.parado = falha, pcm, False

    def presente(self):
        return self.falha is None

    def iniciar(self):
        if self.falha:
            raise self.falha

    def parar(self):
        self.parado = True
        return self.pcm


class _Pub:
    def __init__(self):
        self.msgs = []

    def publish(self, msg):
        self.msgs.append(json.loads(msg.data))


def _node(args=(), transcricao="sentido", falha=None):
    rclpy.init(args=["--ros-args", "-p", "porta:=0", *args])
    fala, ouvido = [], []

    def transcrever(pcm):
        ouvido.append(pcm)
        if isinstance(transcricao, Exception):
            raise transcricao
        return transcricao

    n = voz_mod.VozNode(gravador_factory=lambda d: _Gravador(d, falha), transcrever=transcrever, speak=fala.append)
    n._rotina.destroy()
    n._rotina = _FakeRotina()
    n._estado_pub = _Pub()
    n.fala, n.ouvido = fala, ouvido
    return n


@pytest.fixture
def node():
    n = _node()
    yield n
    n.destroy_node()
    rclpy.shutdown()


def _espera(n):
    for _ in range(100):
        t = n._ciclo
        rclpy.spin_once(n, timeout_sec=0.02)  # o timer do nó manda os goals pendentes
        if t is None or not t.is_alive():
            return
        t.join(0.02)
    raise AssertionError("ciclo nao terminou")


def _resultados(n):
    return [m["resultado"] for m in n._estado_pub.msgs]


def test_texto_vira_rotina_de_voz(node):
    node._on_datagrama("texto:Sentido!")
    _espera(node)
    g = node._rotina.goals[0]
    assert g.voz is True and g.pessoa == "voz"
    assert json.loads(g.passos_json) == [{"postura": "sentido"}]
    assert _resultados(node)[-1] == "ok" and node._estado_pub.msgs[-1]["comando"] == "sentido"


def test_frase_desconhecida_fala_nao_entendi(node):
    node._on_datagrama("texto:abacaxi")
    _espera(node)
    assert node.fala == ["Não entendi, repita o comando"] and not node._rotina.goals
    assert _resultados(node)[-1] == "nao_entendi"


@pytest.mark.parametrize("transcricao", ["", RuntimeError("x")])
def test_transcricao_vazia_ou_com_erro_fala_nao_entendi(transcricao):
    n = _node(transcricao=transcricao)
    try:
        n._on_datagrama("falar_inicio")
        n._on_datagrama("falar_fim")
        _espera(n)
        assert n.fala == ["Não entendi, repita o comando"] and not n._rotina.goals
        assert n.ouvido == [b"\x01\x02"]
    finally:
        n.destroy_node()
        rclpy.shutdown()


def test_fala_que_falha_so_e_logada(node):
    node._speak = lambda t: 1 / 0
    node._on_datagrama("texto:abacaxi")
    _espera(node)
    assert _resultados(node)[-1] == "nao_entendi"


def test_falar_inicio_e_fim_enviam_a_rotina(node):
    node._on_datagrama("falar_inicio")
    assert _resultados(node) == ["gravando"]
    node._on_datagrama("falar_fim")
    _espera(node)
    assert len(node._rotina.goals) == 1 and _resultados(node)[-2:] == ["transcrevendo", "ok"]
    assert node._estado_pub.msgs[-1]["microfone"] is True


def test_comando_e_texto_nao_derrubam_o_microfone(node):
    assert node._estado["microfone"] is True
    node._on_datagrama("comando:a_vontade")
    node._on_datagrama("texto:sentido")
    _espera(node)
    assert node._estado_pub.msgs and all(m["microfone"] is True for m in node._estado_pub.msgs)


def test_microfone_ausente_na_subida_aparece_no_estado():
    n = _node(falha=FileNotFoundError("arecord"))
    try:
        assert n._microfone is False and n._estado["microfone"] is False
    finally:
        n.destroy_node()
        rclpy.shutdown()


def test_gravacao_termina_sozinha_e_falar_fim_tardio_e_ignorado():
    n = _node(["-p", "gravacao_max_s:=0.2"])
    try:
        n._on_datagrama("falar_inicio")
        time.sleep(0.5)
        _espera(n)
        n._on_datagrama("falar_fim")
        _espera(n)
        assert len(n.ouvido) == 1 and len(n._rotina.goals) == 1
    finally:
        n.destroy_node()
        rclpy.shutdown()


def test_sem_microfone_nao_derruba():
    n = _node(falha=FileNotFoundError("arecord"))
    try:
        n._on_datagrama("falar_inicio")
        assert n._estado_pub.msgs[-1]["resultado"] == "recusado" and n._estado_pub.msgs[-1]["microfone"] is False
        n._on_datagrama("falar_inicio")  # a flag foi liberada
        assert _resultados(n) == ["recusado", "recusado"]
    finally:
        n.destroy_node()
        rclpy.shutdown()


def test_corpo_em_rotina_recusa_em_silencio(node):
    node._on_corpo(String(data="rotina"))
    node._on_datagrama("falar_inicio")
    node._on_datagrama("falar_fim")
    _espera(node)
    assert _resultados(node) == ["recusado"] and not node.fala and not node.ouvido and not node._rotina.goals


def test_goal_rejeitado_e_silencioso(node):
    node._rotina.accept = False
    node._on_datagrama("texto:sentido")
    _espera(node)
    assert _resultados(node)[-1] == "recusado" and not node.fala


def test_body_node_fora_do_ar_e_silencioso(node):
    node._rotina.ready = False
    node._on_datagrama("comando:sentido")
    _espera(node)
    assert _resultados(node)[-1] == "recusado" and not node.fala and not node._rotina.goals


def test_comando_direto_nao_precisa_de_microfone():
    n = _node(falha=OSError("sem mic"))
    try:
        n._on_datagrama("comando:a_vontade")
        _espera(n)
        assert json.loads(n._rotina.goals[0].passos_json) == [{"postura": "a_vontade"}] and not n.ouvido
    finally:
        n.destroy_node()
        rclpy.shutdown()


def test_discurso_le_o_texto_salvo_e_vai_de_sentido_a_a_vontade(node, monkeypatch):
    from core import discurso

    monkeypatch.setattr(discurso, "ler", lambda: "Olá, banca.")
    node._on_datagrama("comando:discurso")
    _espera(node)
    assert json.loads(node._rotina.goals[0].passos_json) == [
        {"postura": "sentido"}, {"fala": "Olá, banca."}, {"postura": "a_vontade"}]
    assert _resultados(node)[-1] == "ok"


def test_comando_desconhecido_e_ignorado(node):
    node._on_datagrama("comando:inexistente")
    _espera(node)
    assert not node._rotina.goals and not node._estado_pub.msgs and not node.fala


def test_novo_aperto_durante_o_ciclo_e_ignorado(node):
    node._rotina.hold = True
    node._on_datagrama("texto:sentido")
    for _ in range(100):
        if node._rotina.goals:
            break
        rclpy.spin_once(node, timeout_sec=0.02)
    node._on_datagrama("falar_inicio")
    assert _resultados(node)[-1] == "recusado" and not node.ouvido
    node._rotina.results[0].finish(True)
    _espera(node)
    assert _resultados(node)[-1] == "ok"
    node._on_datagrama("falar_inicio")  # livre de novo
    assert _resultados(node)[-1] == "gravando"


def test_audio_nao_vai_para_o_disco(node, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    node._on_datagrama("falar_inicio")
    node._on_datagrama("falar_fim")
    _espera(node)
    assert isinstance(node.ouvido[0], bytes) and list(tmp_path.iterdir()) == []


def test_destroy_para_a_gravacao():
    n = _node()
    n._on_datagrama("falar_inicio")
    g = n._gravador
    n.destroy_node()
    rclpy.shutdown()
    assert g.parado


def _gira(n, ate):
    for _ in range(100):
        rclpy.spin_once(n, timeout_sec=0.02)
        if ate():
            return
    raise AssertionError("nao chegou")


def test_a_vontade_passa_durante_a_gravacao(node):
    node._on_datagrama("falar_inicio")
    node._on_datagrama("comando:a_vontade")
    _gira(node, lambda: node._rotina.goals)
    assert json.loads(node._rotina.goals[0].passos_json) == [{"postura": "a_vontade"}]
    assert node._gravador is not None  # a gravação segue


def test_a_vontade_passa_com_goal_em_andamento(node):
    node._rotina.hold = True
    node._on_datagrama("texto:sentido")
    _gira(node, lambda: node._rotina.goals)
    node._on_datagrama("comando:a_vontade")
    _gira(node, lambda: len(node._rotina.goals) == 2)
    node._rotina.results[0].finish(True)
    node._rotina.results[1].finish(True)
    _espera(node)


def test_a_vontade_com_corpo_em_rotina_e_recusado(node):
    node._on_corpo(String(data="rotina"))
    node._on_datagrama("comando:a_vontade")
    _espera(node)
    assert not node._rotina.goals and _resultados(node) == ["recusado"]


def test_nao_entendi_nao_fala_com_corpo_em_rotina(node):
    node._on_corpo(String(data="rotina"))
    node._on_datagrama("texto:abacaxi")
    _espera(node)
    assert not node.fala and _resultados(node) == ["recusado"]


def test_excecao_qualquer_no_iniciar_nao_deixa_surdo():
    n = _node(falha=ValueError("x"))
    try:
        n._on_datagrama("falar_inicio")
        n._on_datagrama("falar_inicio")
        assert _resultados(n) == ["recusado", "recusado"] and not n.fala
    finally:
        n.destroy_node()
        rclpy.shutdown()
