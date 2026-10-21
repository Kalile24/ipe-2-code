"""Testes do gesture_node sem robô: o cliente do SDK é substituído por um dublê."""
import threading

import pytest
import rclpy
from rclpy.parameter import Parameter
from std_msgs.msg import String
from std_srvs.srv import SetBool

import robot_reaction_ros.gesture_node as node_mod

HIGH_WAVE, RELEASE = 26, 99


class _FakeClient:
    def __init__(self, codes=None, raises=None):
        self.calls = []
        self.codes = codes or {}
        self.raises = raises
        self.gate = None  # threading.Event: segura o gesto em andamento

    def ExecuteAction(self, action_id):
        self.calls.append(action_id)
        if action_id != RELEASE:
            if self.gate is not None:
                self.gate.wait(5)
            if self.raises is not None:
                raise self.raises
        return self.codes.get(action_id, 0)


@pytest.fixture
def make_node(monkeypatch):
    status, inits, nodes = [], [], []
    monkeypatch.setattr(node_mod.GestureNode, "_publish", lambda self, text: status.append(text))

    def make(client=None, factory_error=None, armed=False):
        def factory(network_interface, timeout):
            inits.append((network_interface, timeout))
            if factory_error is not None:
                raise factory_error
            return client

        rclpy.init(args=["--ros-args", "-p", "hold_s:=0.0", "-p", f"armed:={'true' if armed else 'false'}"])
        n = node_mod.GestureNode(client_factory=factory)
        nodes.append(n)
        return n

    yield make, status, inits
    for n in nodes:
        n.destroy_node()
    rclpy.shutdown()


def _arm(n, on=True):
    return n._on_set_armed(SetBool.Request(data=on), SetBool.Response())


def _send(n, gesto, wait=True):
    n._on_gesture(String(data=gesto))
    if wait and n._worker is not None:
        n._worker.join(5)


def test_disarmed_publishes_dry_run_and_never_builds_the_client(make_node):
    make, status, inits = make_node
    _send(make(), "high wave")
    assert status == ["dry_run high wave"]
    assert inits == []


def test_unknown_empty_and_padded_commands_are_rejected(make_node):
    make, status, _ = make_node
    n = make(client=_FakeClient())
    _arm(n)
    for gesto in ["continencia", "", " high wave"]:
        _send(n, gesto)
    assert status == ["armed", "rejected unknown 'continencia'", "rejected unknown ''", "rejected unknown ' high wave'"]


def test_armed_gesture_runs_then_releases(make_node):
    make, status, inits = make_node
    client = _FakeClient()
    n = make(client=client)
    assert _arm(n).success
    _send(n, "high wave")
    assert client.calls == [HIGH_WAVE, RELEASE]
    assert status == ["armed", "started high wave", "done high wave"]
    assert inits == [("eth0", 10.0)]


def test_armed_param_arms_at_startup(make_node):
    make, status, inits = make_node
    make(client=_FakeClient(), armed=True)
    assert status == ["armed"]
    assert len(inits) == 1


def test_arming_twice_builds_the_client_once(make_node):
    make, _, inits = make_node
    n = make(client=_FakeClient())
    _arm(n)
    _arm(n)
    assert len(inits) == 1


def test_init_failure_keeps_node_disarmed_and_can_retry(make_node):
    make, status, inits = make_node
    n = make(factory_error=RuntimeError("sem DDS"))
    response = _arm(n)
    assert not response.success
    assert status[0].startswith("failed init") and "sem DDS" in status[0]
    _send(n, "high wave")
    assert status[-1] == "dry_run high wave"
    _arm(n)
    assert len(inits) == 2  # tentou de novo


def test_disarm_turns_commands_back_into_dry_run(make_node):
    make, status, _ = make_node
    client = _FakeClient()
    n = make(client=client)
    _arm(n)
    _arm(n, on=False)
    _send(n, "high wave")
    assert status == ["armed", "disarmed", "dry_run high wave"]
    assert client.calls == []


def test_failed_code_still_releases_arm(make_node):
    make, status, _ = make_node
    client = _FakeClient(codes={HIGH_WAVE: 3104})
    n = make(client=client)
    _arm(n)
    _send(n, "high wave")
    assert client.calls == [HIGH_WAVE, RELEASE]
    assert status[1:] == ["started high wave", "failed high wave code=3104"]


def test_sdk_exception_releases_and_does_not_leave_node_busy(make_node):
    make, status, _ = make_node
    client = _FakeClient(raises=RuntimeError("rpc caiu"))
    n = make(client=client)
    _arm(n)
    _send(n, "high wave")
    assert status[2].startswith("failed high wave") and "rpc caiu" in status[2]
    client.raises = None
    _send(n, "clap")
    assert status[-1] == "done clap"
    assert client.calls == [HIGH_WAVE, RELEASE, 17, RELEASE]


def test_second_command_while_busy_is_rejected_and_ctrl_c_releases(make_node):
    make, status, _ = make_node
    client = _FakeClient()
    client.gate = threading.Event()
    n = make(client=client)
    _arm(n)
    _send(n, "high wave", wait=False)
    _send(n, "clap", wait=False)
    n.release_if_busy()  # o que o main faz no Ctrl+C
    client.gate.set()
    n._worker.join(5)
    assert "rejected busy" in status
    assert client.calls.count(RELEASE) == 2  # o do Ctrl+C e o do fim do gesto


def test_param_set_armed_is_refused_so_only_the_service_changes_it(make_node):
    make, status, _ = make_node
    client = _FakeClient()
    n = make(client=client, armed=True)
    [result] = n.set_parameters([Parameter("armed", Parameter.Type.BOOL, False)])
    assert not result.successful and "set_armed" in result.reason
    _send(n, "high wave")
    assert status[-1] == "done high wave"  # continua armado: o param set não mentiu
