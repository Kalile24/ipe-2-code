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
  gesto: high wave
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
    def __init__(self):
        self.callbacks = []

    def add_done_callback(self, callback):
        self.callbacks.append(callback)

    def finish(self, sucesso, mensagem=""):
        resposta = type("R", (), {"result": type("Res", (), {"sucesso": sucesso, "mensagem": mensagem})()})()
        for callback in self.callbacks:
            callback(_Done(resposta))


class _FakeRotina:
    """No lugar do ActionClient: o body_node está de pé (ready), aceita ou recusa as rotinas."""

    def __init__(self):
        self.ready = True
        self.accept = True
        self.goals = []
        self.results = []

    def server_is_ready(self):
        return self.ready

    def destroy(self):
        pass

    def send_goal_async(self, goal):
        self.goals.append(goal)
        result = _Pending()
        self.results.append(result)
        handle = type("H", (), {"accepted": self.accept, "get_result_async": lambda _self: result})()
        return _Done(handle)


@pytest.fixture
def node(tmp_path, monkeypatch):
    path = _yaml(tmp_path, ROTINA_YAML)
    # Sem cooldown global: os testes andam no relógio de verdade.
    rclpy.init(args=["--ros-args", "-p", f"reactions_file:={path}", "-p", "confirm_frames:=3", "-p", "global_cooldown_s:=0.0"])
    n = node_mod.ReactionNode()
    published = []
    monkeypatch.setattr(n._publisher, "publish", published.append)
    n.subscribers = 1  # gesture_node de pé
    monkeypatch.setattr(n._publisher, "get_subscription_count", lambda: n.subscribers)
    n._rotina.destroy()  # o ActionClient de verdade sai; entra o dublê
    n._rotina = _FakeRotina()
    yield n, published
    n.destroy_node()
    rclpy.shutdown()


def test_confirmed_person_publishes_one_gesture_command(node):
    n, published = node
    for _ in range(6):
        n._on_detections(_array("gil", "desconhecido"))
    assert [m.data for m in published] == ["high wave"]


def test_empty_arrays_reset_the_count(node):
    n, published = node
    for msg in [_array("gil"), _array("gil"), _array(), _array("gil"), _array("gil")]:
        n._on_detections(msg)
    assert published == []


def test_routine_goes_to_the_body_node_as_an_action_goal(node):
    n, published = node
    for _ in range(3):
        n._on_detections(_array("cmt"))
    assert published == []
    assert [(g.pessoa, json.loads(g.passos_json)) for g in n._rotina.goals] == [
        ("cmt", [{"postura": "sentido"}, {"fala": "Olá, comandante"}, {"postura": "a_vontade"}])
    ]


def test_nobody_else_is_greeted_while_a_routine_runs(node):
    n, published = node
    for _ in range(3):
        n._on_detections(_array("cmt"))
    for _ in range(5):
        n._on_detections(_array("gil"))
    assert published == []  # gil esperou a rotina do cmt
    n._rotina.results[0].finish(True)
    n._on_detections(_array("gil"))
    assert [m.data for m in published] == ["high wave"]


def test_rejected_routine_does_not_count_as_greeted(node):
    n, _ = node
    n._rotina.accept = False  # inicializando ou ocupado
    for _ in range(3):
        n._on_detections(_array("cmt"))
    n._rotina.accept = True
    n._on_detections(_array("cmt"))
    assert len(n._rotina.goals) == 2


def test_failed_routine_still_counts_as_greeted(node):
    n, _ = node
    for _ in range(3):
        n._on_detections(_array("cmt"))
    n._rotina.results[0].finish(False, "falhou")
    for _ in range(5):
        n._on_detections(_array("cmt"))
    assert len(n._rotina.goals) == 1


def test_routine_without_body_node_is_not_counted(node):
    n, _ = node
    n._rotina.ready = False  # robo.launch.py: sem body_node
    for _ in range(3):
        n._on_detections(_array("cmt"))
    assert n._rotina.goals == []
    n._rotina.ready = True
    n._on_detections(_array("cmt"))
    assert len(n._rotina.goals) == 1


def test_gesture_without_gesture_node_is_not_counted(node):
    n, published = node
    n.subscribers = 0  # rotina.launch.py: sem gesture_node
    for _ in range(3):
        n._on_detections(_array("gil"))
    assert published == []
    n.subscribers = 1
    n._on_detections(_array("gil"))
    assert [m.data for m in published] == ["high wave"]


def test_body_node_vanishing_mid_routine_frees_the_others(node):
    n, published = node
    for _ in range(3):
        n._on_detections(_array("cmt"))
    n._rotina.ready = False  # body_node morreu: o resultado nunca chega
    for _ in range(3):
        n._on_detections(_array("gil"))
    assert [m.data for m in published] == ["high wave"]


def test_same_person_in_front_is_not_greeted_again(node):
    n, published = node
    for _ in range(30):
        n._on_detections(_array("gil"))
    assert [m.data for m in published] == ["high wave"]


def test_liberar_parameter_allows_greeting_again(node):
    n, published = node
    for _ in range(3):
        n._on_detections(_array("gil"))
    result = n.set_parameters([Parameter("liberar", Parameter.Type.STRING, "gil")])
    assert result[0].successful
    n._on_detections(_array("gil"))
    assert [m.data for m in published] == ["high wave", "high wave"]


def test_liberar_unknown_name_is_refused(node):
    n, _ = node
    result = n.set_parameters([Parameter("liberar", Parameter.Type.STRING, "ze")])
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
    path = _yaml(tmp_path, "gil:\n  gesture: high wave\n")
    _start_must_fail(["-p", f"reactions_file:={path}"], ReactionConfigError, "gesture")


def test_missing_map_file_fails_with_its_path(tmp_path):
    _start_must_fail(["-p", f"reactions_file:={tmp_path}/nao_existe.yaml"], FileNotFoundError, "nao_existe")


def test_installed_default_map_loads():
    rclpy.init(args=[])
    try:
        n = node_mod.ReactionNode()  # reactions_file "" = config/reactions.yaml do pacote
        n.destroy_node()
    finally:
        rclpy.shutdown()
