"""Testes do reaction_node sem câmera: detecções montadas à mão."""
import json

import pytest
import rclpy
from rclpy.parameter import Parameter
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

import robot_reaction_ros.reaction_node as node_mod
from core.reaction_policy import ReactionConfigError


def _array(*nomes):
    msg = Detection2DArray()
    for nome in nomes:
        hypothesis = ObjectHypothesisWithPose()
        hypothesis.id = nome
        hypothesis.score = 0.8
        detection = Detection2D()
        detection.results.append(hypothesis)
        msg.detections.append(detection)
    return msg


def _yaml(tmp_path, text):
    path = tmp_path / "reactions.yaml"
    path.write_text(text)
    return path


ROTINA_YAML = """
gil:
  passos:
    - fala: "Olá, Gil"
cmt:
  passos:
    - postura: sentido
    - fala: "Olá, comandante"
    - postura: a_vontade
"""


class _Done:
    """Future já resolvido: chama o callback na hora, como o rclpy faz sem executor."""

    def __init__(self, value):
        self.value = value

    def result(self):
        return self.value

    def add_done_callback(self, callback):
        callback(self)


class _Pending:
    """Resultado da rotina: chega na hora (`auto`) ou quando o teste chama finish()."""

    def __init__(self, auto):
        self.auto = auto
        self.callbacks = []

    def add_done_callback(self, callback):
        self.callbacks.append(callback)
        if self.auto:
            self.finish(True)

    def finish(self, sucesso, mensagem=""):
        resposta = type("R", (), {"result": type("Res", (), {"sucesso": sucesso, "mensagem": mensagem})()})()
        for callback in self.callbacks:
            callback(_Done(resposta))


class _FakeRotina:
    """No lugar do ActionClient: o body_node está de pé (ready), aceita ou recusa as rotinas."""

    def __init__(self):
        self.ready = True
        self.accept = True
        self.hold = False  # True: a rotina fica em andamento até o teste chamar finish()
        self.goals = []
        self.results = []

    def server_is_ready(self):
        return self.ready

    def destroy(self):
        pass

    def send_goal_async(self, goal):
        self.goals.append(goal)
        result = _Pending(auto=not self.hold)
        self.results.append(result)
        handle = type("H", (), {"accepted": self.accept, "get_result_async": lambda _self: result})()
        return _Done(handle)


@pytest.fixture
def node(tmp_path):
    path = _yaml(tmp_path, ROTINA_YAML)
    # Sem cooldown global: os testes andam no relógio de verdade.
    rclpy.init(args=["--ros-args", "-p", f"reactions_file:={path}", "-p", "confirm_frames:=3", "-p", "global_cooldown_s:=0.0"])
    n = node_mod.ReactionNode()
    n._rotina.destroy()  # o ActionClient de verdade sai; entra o dublê
    n._rotina = _FakeRotina()
    yield n
    n.destroy_node()
    rclpy.shutdown()


def _greeted(n):
    return [g.pessoa for g in n._rotina.goals]


def test_confirmed_person_gets_one_routine(node):
    for _ in range(6):
        node._on_detections(_array("gil", "desconhecido"))
    assert _greeted(node) == ["gil"]


def test_a_short_empty_gap_keeps_the_count(node):
    # Os frames chegam em microssegundos: o vazio no meio é uma falha curta (< 0,5 s) e não zera
    # (de longe o reconhecimento falha um frame ou outro). Vazio longo zera: test_reaction_policy.
    for msg in [_array("gil"), _array("gil"), _array(), _array("gil")]:
        node._on_detections(msg)
    assert _greeted(node) == ["gil"]


def test_routine_goes_to_the_body_node_as_an_action_goal(node):
    for _ in range(3):
        node._on_detections(_array("cmt"))
    assert [(g.pessoa, json.loads(g.passos_json)) for g in node._rotina.goals] == [
        ("cmt", [{"postura": "sentido"}, {"fala": "Olá, comandante"}, {"postura": "a_vontade"}])
    ]


def test_nobody_else_is_greeted_while_a_routine_runs(node):
    node._rotina.hold = True
    for _ in range(3):
        node._on_detections(_array("cmt"))
    for _ in range(5):
        node._on_detections(_array("gil"))
    assert _greeted(node) == ["cmt"]  # gil esperou a rotina do cmt
    node._rotina.results[0].finish(True)
    node._on_detections(_array("gil"))
    assert _greeted(node) == ["cmt", "gil"]


def test_rejected_routine_does_not_count_as_greeted(node):
    node._rotina.accept = False  # inicializando ou ocupado
    for _ in range(3):
        node._on_detections(_array("cmt"))
    node._rotina.accept = True
    node._on_detections(_array("cmt"))
    assert _greeted(node) == ["cmt", "cmt"]


def test_failed_routine_still_counts_as_greeted(node):
    node._rotina.hold = True
    for _ in range(3):
        node._on_detections(_array("cmt"))
    node._rotina.results[0].finish(False, "falhou")
    for _ in range(5):
        node._on_detections(_array("cmt"))
    assert _greeted(node) == ["cmt"]


def test_routine_without_body_node_is_not_counted(node):
    node._rotina.ready = False
    for _ in range(3):
        node._on_detections(_array("cmt"))
    assert _greeted(node) == []
    node._rotina.ready = True
    node._on_detections(_array("cmt"))
    assert _greeted(node) == ["cmt"]


def test_body_node_vanishing_mid_routine_frees_the_others(node):
    node._rotina.hold = True
    for _ in range(3):
        node._on_detections(_array("cmt"))
    node._rotina.ready = False  # body_node morreu: o resultado nunca chega
    node._on_detections(_array("gil"))
    node._rotina.ready = True  # voltou
    for _ in range(2):
        node._on_detections(_array("gil"))
    assert _greeted(node) == ["cmt", "gil"]


def test_same_person_in_front_is_not_greeted_again(node):
    for _ in range(30):
        node._on_detections(_array("gil"))
    assert _greeted(node) == ["gil"]


def test_liberar_parameter_allows_greeting_again(node):
    for _ in range(3):
        node._on_detections(_array("gil"))
    result = node.set_parameters([Parameter("liberar", Parameter.Type.STRING, "gil")])
    assert result[0].successful
    node._on_detections(_array("gil"))
    assert _greeted(node) == ["gil", "gil"]


def test_liberar_unknown_name_is_refused(node):
    result = node.set_parameters([Parameter("liberar", Parameter.Type.STRING, "ze")])
    assert not result[0].successful
    assert "ze" in result[0].reason


def _start_must_fail(args, exc, trecho):
    rclpy.init(args=["--ros-args", *args])
    try:
        with pytest.raises(exc, match=trecho):
            node_mod.ReactionNode()
    finally:
        rclpy.shutdown()


def test_invalid_map_stops_the_node_at_startup(tmp_path):
    path = _yaml(tmp_path, "gil:\n  gesto: high wave\n")  # gestos do firmware saíram
    _start_must_fail(["-p", f"reactions_file:={path}"], ReactionConfigError, "gesto")


def test_missing_map_file_fails_with_its_path(tmp_path):
    _start_must_fail(["-p", f"reactions_file:={tmp_path}/nao_existe.yaml"], FileNotFoundError, "nao_existe")


def test_installed_default_map_loads():
    rclpy.init(args=[])
    try:
        n = node_mod.ReactionNode()  # reactions_file "" = config/reactions.yaml do pacote
        n.destroy_node()
    finally:
        rclpy.shutdown()
