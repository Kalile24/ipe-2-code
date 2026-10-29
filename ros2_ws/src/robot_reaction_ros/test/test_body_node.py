"""Testes do body_node sem robô: o corpo (G1ArmController do ~/hhhh) e a voz são dublês."""
import json
import threading

import pytest
import rclpy
from rclpy.parameter import Parameter
from std_msgs.msg import String

import robot_reaction_ros.body_node as node_mod

ROTINA = {
    "pessoa": "gil",
    "passos": [
        {"postura": "sentido"},
        {"fala": "Olá, aspirante"},
        {"postura": "descansar"},
        {"postura": "a_vontade"},
        {"fala": "Bom ver o senhor"},
    ],
}


class _FakeBody:
    def __init__(self, init_ok=True):
        self.calls = []
        self.init_ok = init_ok
        self.gate = None  # threading.Event: segura uma postura em andamento

    def initialize(self):
        self.calls.append("initialize")
        return self.init_ok

    def posture(self, nome):
        self.calls.append(nome)
        if self.gate is not None:
            self.gate.wait(5)
        return True

    def shutdown(self):
        self.calls.append("shutdown")


@pytest.fixture
def make_node(monkeypatch):
    status, spoken, nodes = [], [], []
    monkeypatch.setattr(node_mod.BodyNode, "_publish", lambda self, text: status.append(text))

    def speak(text, url, timeout_s):
        spoken.append(text)

    def make(body=None, armed=False, factory_error=None):
        def factory(hhhh_dir, network_interface):
            if factory_error is not None:
                raise factory_error
            return body

        rclpy.init(args=["--ros-args", "-p", "pausa_s:=0.0", "-p", f"armed:={'true' if armed else 'false'}"])
        n = node_mod.BodyNode(body_factory=factory, speak=speak)
        nodes.append(n)
        if n._worker is not None:
            n._worker.join(5)  # inicialização
        return n

    yield make, status, spoken
    for n in nodes:
        n.destroy_node()
    rclpy.shutdown()


def _send(n, dados, wait=True):
    n._on_routine(String(data=json.dumps(dados) if not isinstance(dados, str) else dados))
    if wait and n._worker is not None:
        n._worker.join(5)


def test_disarmed_speaks_but_only_logs_postures(make_node):
    make, status, spoken = make_node
    n = make()
    _send(n, ROTINA)
    assert spoken == ["Olá, aspirante", "Bom ver o senhor"]
    assert [s for s in status if s.startswith("dry_run")] == [
        "dry_run postura sentido",
        "dry_run postura descansar",
        "dry_run postura a_vontade",
    ]
    assert status[-1] == "rotina de gil: fim"


def test_armed_initializes_then_runs_postures_in_order(make_node):
    make, status, spoken = make_node
    body = _FakeBody()
    n = make(body=body, armed=True)
    assert "pronto: em equilíbrio, esperando reconhecimento" in status
    _send(n, ROTINA)
    assert body.calls == ["initialize", "sentido", "descansar", "a_vontade"]
    assert spoken == ["Olá, aspirante", "Bom ver o senhor"]


def test_failed_initialization_falls_back_to_dry_run(make_node):
    make, status, _ = make_node
    body = _FakeBody(init_ok=False)
    n = make(body=body, armed=True)
    _send(n, ROTINA)
    assert body.calls == ["initialize"]
    assert "dry_run postura sentido" in status


def test_factory_error_is_reported_and_node_stays_up(make_node):
    make, status, _ = make_node
    n = make(armed=True, factory_error=ImportError("sem ~/hhhh"))
    assert any(s.startswith("falha na inicialização") and "sem ~/hhhh" in s for s in status)
    _send(n, ROTINA)
    assert status[-1] == "rotina de gil: fim"


def test_second_routine_while_busy_is_rejected(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    n = make(body=body, armed=True)
    body.gate = threading.Event()
    _send(n, ROTINA, wait=False)
    _send(n, ROTINA, wait=False)
    body.gate.set()
    n._worker.join(5)
    assert "rotina de gil rejeitada: ocupado" in status
    assert body.calls.count("sentido") == 1


@pytest.mark.parametrize(
    "dados",
    ["não é json", {"pessoa": "gil"}, {"pessoa": "gil", "passos": [{"postura": "sentido"}]}],  # sem a_vontade
)
def test_invalid_messages_are_rejected(make_node, dados):
    make, status, spoken = make_node
    n = make()
    _send(n, dados)
    assert status[-1].startswith("rotina rejeitada")
    assert spoken == []


def test_armed_cannot_change_after_start(make_node):
    make, _, _ = make_node
    n = make()
    result = n.set_parameters([Parameter("armed", Parameter.Type.BOOL, True)])
    assert not result[0].successful


def test_shutdown_waits_for_current_step_then_releases(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    n = make(body=body, armed=True)
    body.gate = threading.Event()
    _send(n, ROTINA, wait=False)
    threading.Timer(0.2, body.gate.set).start()
    n.shutdown(timeout_s=5)
    # Parou depois do sentido em andamento (não começou o descansar) e só então soltou os braços.
    assert body.calls == ["initialize", "sentido", "shutdown"]
