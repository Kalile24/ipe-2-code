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


@pytest.fixture
def node(tmp_path, monkeypatch):
    path = _yaml(tmp_path, ROTINA_YAML)
    rclpy.init(args=["--ros-args", "-p", f"reactions_file:={path}", "-p", "confirm_frames:=3"])
    n = node_mod.ReactionNode()
    published, routines = [], []
    monkeypatch.setattr(n._publisher, "publish", published.append)
    monkeypatch.setattr(n._routine_publisher, "publish", routines.append)
    n.routines = routines
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


def test_routine_goes_to_the_routine_topic_as_json(node):
    n, published = node
    for _ in range(3):
        n._on_detections(_array("cmt"))
    assert published == []
    assert [json.loads(m.data) for m in n.routines] == [
        {
            "pessoa": "cmt",
            "passos": [{"postura": "sentido"}, {"fala": "Olá, comandante"}, {"postura": "a_vontade"}],
        }
    ]


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
