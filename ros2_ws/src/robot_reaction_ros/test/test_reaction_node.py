"""Testes do reaction_node sem câmera: detecções montadas à mão."""
import pytest
import rclpy
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


@pytest.fixture
def node(tmp_path, monkeypatch):
    path = _yaml(tmp_path, "gil:\n  gesto: high wave\n")
    rclpy.init(args=["--ros-args", "-p", f"reactions_file:={path}", "-p", "confirm_frames:=3"])
    n = node_mod.ReactionNode()
    published = []
    monkeypatch.setattr(n._publisher, "publish", published.append)
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
