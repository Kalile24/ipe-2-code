"""Testes do body_node sem robô: o corpo (G1ArmController) e a voz são dublês.

As rotinas chegam pela ação /reaction/rotina, de um cliente de verdade no mesmo processo.
"""
import json
import threading
import time

import pytest
import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter

import robot_reaction_ros.body_node as node_mod
from robot_reaction_interfaces.action import Rotina

PASSOS = [
    {"postura": "sentido"},
    {"fala": "Olá, aspirante"},
    {"postura": "descansar"},
    {"postura": "a_vontade"},
    {"fala": "Bom ver o senhor"},
]


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


def _wait(future, timeout=5.0):
    fim = time.monotonic() + timeout
    while not future.done():
        assert time.monotonic() < fim, "o body_node não respondeu"
        time.sleep(0.01)
    return future.result()


class _Env:
    def __init__(self, node, client):
        self.node = node
        self.client = client

    def send(self, passos=PASSOS, pessoa="gil", passos_json=None):
        """Manda a rotina; devolve (aceita, future do resultado ou None)."""
        goal = Rotina.Goal(pessoa=pessoa, passos_json=passos_json if passos_json is not None else json.dumps(passos))
        handle = _wait(self.client.send_goal_async(goal))
        return handle.accepted, (handle.get_result_async() if handle.accepted else None), handle

    def run(self, **kw):
        aceita, resultado, _ = self.send(**kw)
        assert aceita
        return _wait(resultado).result


@pytest.fixture
def make_node(monkeypatch):
    status, spoken, cleanup = [], [], []
    monkeypatch.setattr(node_mod.BodyNode, "_publish", lambda self, text: status.append(text))

    def speak(text, url, timeout_s):
        spoken.append(text)

    def make(body=None, armed=False, factory_error=None, wait_init=True):
        def factory(poses_dir, network_interface, rest_forward_pulse):
            if factory_error is not None:
                raise factory_error
            return body

        rclpy.init(args=["--ros-args", "-p", "pausa_s:=0.0", "-p", f"armed:={'true' if armed else 'false'}"])
        n = node_mod.BodyNode(body_factory=factory, speak=speak)
        if n._init_thread is not None and wait_init:
            n._init_thread.join(5)
        client_node = rclpy.create_node("cliente_teste")
        client = ActionClient(client_node, Rotina, "/reaction/rotina")
        executor = MultiThreadedExecutor()
        executor.add_node(n)
        executor.add_node(client_node)
        threading.Thread(target=executor.spin, daemon=True).start()
        assert client.wait_for_server(timeout_sec=5)
        cleanup.append((executor, n, client_node))
        return _Env(n, client)

    yield make, status, spoken
    for executor, n, client_node in cleanup:
        executor.shutdown()
        client_node.destroy_node()
        n.destroy_node()
    rclpy.shutdown()


def test_disarmed_speaks_but_only_logs_postures(make_node):
    make, status, spoken = make_node
    env = make()
    resultado = env.run()
    assert resultado.sucesso
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
    env = make(body=body, armed=True)
    assert "pronto: em equilíbrio, esperando reconhecimento" in status
    assert env.run().sucesso
    assert body.calls == ["initialize", "sentido", "descansar", "a_vontade"]
    assert spoken == ["Olá, aspirante", "Bom ver o senhor"]


def test_failed_initialization_falls_back_to_dry_run(make_node):
    make, status, _ = make_node
    body = _FakeBody(init_ok=False)
    env = make(body=body, armed=True)
    env.run()
    assert body.calls == ["initialize"]
    assert "dry_run postura sentido" in status


def test_factory_error_is_reported_and_node_stays_up(make_node):
    make, status, _ = make_node
    env = make(armed=True, factory_error=ImportError("sem poses"))
    assert any(s.startswith("falha na inicialização") and "sem poses" in s for s in status)
    assert env.run().sucesso


def test_second_routine_while_busy_is_rejected_and_the_client_knows(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    body.gate = threading.Event()
    aceita, primeira, _ = env.send()
    assert aceita
    segunda_aceita, _, _ = env.send()
    body.gate.set()
    assert _wait(primeira).result.sucesso
    assert not segunda_aceita
    assert "rotina de gil rejeitada: ocupado" in status
    assert body.calls.count("sentido") == 1


def test_routine_during_initialization_is_rejected(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    gate = threading.Event()
    initialize = body.initialize
    body.initialize = lambda: gate.wait(5) and initialize()
    env = make(body=body, armed=True, wait_init=False)
    aceita, _, _ = env.send()
    gate.set()
    env.node._init_thread.join(5)
    assert not aceita
    assert env.run().sucesso  # depois de pronto, aceita


@pytest.mark.parametrize(
    "kw",
    [
        {"passos_json": "não é json"},
        {"passos_json": "{}"},
        {"passos": [{"postura": "sentido"}]},  # sem a_vontade
        {"pessoa": " "},
    ],
)
def test_invalid_goals_are_rejected(make_node, kw):
    make, status, spoken = make_node
    env = make()
    aceita, _, _ = env.send(**kw)
    assert not aceita
    assert status[-1].startswith("rotina rejeitada")
    assert spoken == []


def test_armed_cannot_change_after_start(make_node):
    make, _, _ = make_node
    env = make()
    result = env.node.set_parameters([Parameter("armed", Parameter.Type.BOOL, True)])
    assert not result[0].successful


def test_cancel_stops_after_the_current_step_and_releases_the_arms(make_node):
    make, status, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    body.gate = threading.Event()
    aceita, resultado, handle = env.send()
    assert aceita
    _wait(handle.cancel_goal_async())
    body.gate.set()
    final = _wait(resultado)
    assert not final.result.sucesso
    assert body.calls == ["initialize", "sentido", "a_vontade"]
    assert "rotina de gil: interrompida" in status


def test_long_pause_ends_on_cancel(make_node):
    make, _, _ = make_node
    env = make(body=_FakeBody(), armed=True)
    passos = [{"postura": "descansar"}, {"pausa": 120}, {"postura": "a_vontade"}]
    aceita, resultado, handle = env.send(passos=passos)
    assert aceita
    time.sleep(0.2)
    inicio = time.monotonic()
    _wait(handle.cancel_goal_async())
    _wait(resultado, timeout=3)
    assert time.monotonic() - inicio < 3


def test_shutdown_waits_for_current_step_then_releases(make_node):
    make, _, _ = make_node
    body = _FakeBody()
    env = make(body=body, armed=True)
    body.gate = threading.Event()
    aceita, _, _ = env.send()
    assert aceita
    threading.Timer(0.2, body.gate.set).start()
    env.node.shutdown(timeout_s=5)
    # Parou depois do sentido em andamento (não começou o descansar), fez o a_vontade e só então
    # soltou o arm_sdk.
    assert body.calls == ["initialize", "sentido", "a_vontade", "shutdown"]
    assert not env.send()[0]  # encerrando: nenhuma rotina nova
