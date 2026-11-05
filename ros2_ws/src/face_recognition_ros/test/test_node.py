"""Testes do nó sem câmera nem modelo: FaceEngine é substituído por um dublê."""
import cv2
import numpy as np
import pytest
import rclpy
from cv_bridge import CvBridge
from rclpy.qos import ReliabilityPolicy

import face_recognition_ros.face_recognition_node as node_mod


class _Face:
    def __init__(self, bbox):
        self.bbox = bbox
        self.embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        self.det_score = 0.9


class _FakeEngine:
    faces = []
    kwargs = {}

    def __init__(self, *a, **k):
        _FakeEngine.kwargs = k

    def extract_faces(self, frame):
        return list(_FakeEngine.faces)

    def active_providers(self):
        return {"detection": ["CPUExecutionProvider"], "recognition": ["CPUExecutionProvider"]}


@pytest.fixture
def node(monkeypatch, tmp_path):
    monkeypatch.setattr(node_mod, "FaceEngine", _FakeEngine)
    rclpy.init(args=["--ros-args", "-p", "similarity_threshold:=1", "-p", f"db_path:={tmp_path}/identity_db"])
    n = node_mod.FaceRecognitionNode()
    yield n
    n.destroy_node()
    rclpy.shutdown()


def test_onnx_providers_param_is_split_and_forwarded(monkeypatch, tmp_path):
    monkeypatch.setattr(node_mod, "FaceEngine", _FakeEngine)
    rclpy.init(args=[
        "--ros-args", "-p", f"db_path:={tmp_path}/identity_db",
        "-p", "onnx_providers:=TensorrtExecutionProvider, CUDAExecutionProvider,CPUExecutionProvider",
    ])
    try:
        n = node_mod.FaceRecognitionNode()
        n.destroy_node()
    finally:
        rclpy.shutdown()
    assert _FakeEngine.kwargs["providers"] == [
        "TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"
    ]


def test_without_onnx_providers_param_the_insightface_default_is_kept(node):
    assert _FakeEngine.kwargs["providers"] is None


def _image(frame_id, h=480, w=640):
    img = CvBridge().cv2_to_imgmsg(np.zeros((h, w, 3), dtype=np.uint8), encoding="bgr8")
    img.header.frame_id = frame_id
    return img


def test_int_threshold_is_accepted_and_subscription_is_best_effort_depth_1(node):
    assert node._threshold == 1.0
    info = node.get_subscriptions_info_by_topic("/camera/color/image_raw")[0]
    assert info.qos_profile.reliability == ReliabilityPolicy.BEST_EFFORT
    # a descoberta DDS não transporta a profundidade da fila; ler do objeto local
    assert node._subscription.qos_profile.depth == 1


def test_published_array_carries_header_of_measured_frame(node, monkeypatch):
    published = []
    monkeypatch.setattr(node._publisher, "publish", published.append)
    _FakeEngine.faces = [_Face((-10, -5, 700, 500))]
    node._on_image(_image("f1"))
    node._on_image(_image("f2"))
    assert [m.header.frame_id for m in published] == ["f1", "f2"]
    det = published[1].detections[0]
    assert det.header.frame_id == "f2"
    assert (det.bbox.size_x, det.bbox.size_y) == (640.0, 480.0)  # recortada à imagem
    assert det.results[0].id == "desconhecido"


def test_heartbeat_reports_processed_frames_then_resets(node, monkeypatch):
    logs = []
    monkeypatch.setattr(node, "get_logger", lambda: type("L", (), {
        "info": lambda self, m: logs.append(("info", m)), "warn": lambda self, m: logs.append(("warn", m)),
    })())
    _FakeEngine.faces = [_Face((10, 10, 100, 100))]
    node._on_image(_image("f1"))
    node._on_image(_image("f2"))
    node._heartbeat()
    node._heartbeat()  # nada chegou desde o último: tem que avisar
    assert logs[0][0] == "info" and logs[0][1].startswith("2 imagens processadas") and "2 rostos" in logs[0][1]
    assert logs[1][0] == "warn" and logs[1][1].startswith("nenhuma imagem")


def test_boxes_fully_outside_are_dropped_and_engine_errors_do_not_kill_node(node, monkeypatch):
    published = []
    monkeypatch.setattr(node._publisher, "publish", published.append)
    _FakeEngine.faces = [_Face((700, 10, 800, 50))]
    node._on_image(_image("f1"))
    assert published and published[-1].detections == []

    def boom(frame):
        raise RuntimeError("modelo explodiu")

    monkeypatch.setattr(node._engine, "extract_faces", boom)
    node._on_image(_image("f2"))  # não deve lançar
    assert len(published) == 1  # frame com erro não publica nada


def _pedido_cadastro(nome, n, adicionar):
    from robot_reaction_interfaces.srv import Cadastrar
    from sensor_msgs.msg import CompressedImage

    ok, jpeg = cv2.imencode(".jpg", np.zeros((8, 8, 3), np.uint8))
    assert ok
    foto = CompressedImage(format="jpeg", data=jpeg.tobytes())
    return Cadastrar.Request(nome=nome, fotos=[foto] * n, adicionar=adicionar), Cadastrar.Response()


def test_enrollment_adds_to_or_replaces_the_person_and_keeps_the_others(node, monkeypatch):
    monkeypatch.setattr(_FakeEngine, "faces", [_Face((0, 0, 10, 10))])
    node._on_cadastrar(*_pedido_cadastro("aderson", 2, False))
    node._on_cadastrar(*_pedido_cadastro("gil", 1, False))
    resposta = node._on_cadastrar(*_pedido_cadastro("aderson", 3, True))
    assert resposta.ok and resposta.fotos_usadas == 3 and "5 no total" in resposta.mensagem
    assert len(node._store.embeddings["aderson"]) == 5
    node._on_cadastrar(*_pedido_cadastro("aderson", 1, False))
    assert len(node._store.embeddings["aderson"]) == 1
    assert len(node._store.embeddings["gil"]) == 1


def test_enrollment_without_a_face_changes_nothing_even_when_replacing(node, monkeypatch):
    monkeypatch.setattr(_FakeEngine, "faces", [_Face((0, 0, 10, 10))])
    node._on_cadastrar(*_pedido_cadastro("gil", 2, False))
    monkeypatch.setattr(_FakeEngine, "faces", [])
    resposta = node._on_cadastrar(*_pedido_cadastro("gil", 1, False))
    assert resposta.ok is False and len(node._store.embeddings["gil"]) == 2
