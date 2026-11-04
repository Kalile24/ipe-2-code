"""initialize_to_balance em pé, sem robô: o SDK da Unitree é um dublê, o controlador é o de verdade."""
import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

_SDK = [
    "unitree_sdk2py", "unitree_sdk2py.core", "unitree_sdk2py.core.channel", "unitree_sdk2py.g1",
    "unitree_sdk2py.g1.loco", "unitree_sdk2py.g1.loco.g1_loco_api", "unitree_sdk2py.g1.loco.g1_loco_client",
    "unitree_sdk2py.idl", "unitree_sdk2py.idl.default", "unitree_sdk2py.idl.unitree_go",
    "unitree_sdk2py.idl.unitree_go.msg", "unitree_sdk2py.idl.unitree_go.msg.dds_", "unitree_sdk2py.idl.unitree_hg",
    "unitree_sdk2py.idl.unitree_hg.msg", "unitree_sdk2py.idl.unitree_hg.msg.dds_", "unitree_sdk2py.utils",
    "unitree_sdk2py.utils.crc", "pymodbus", "pymodbus.client",
]


@pytest.fixture
def controlador():
    with mock.patch.dict(sys.modules, {nome: mock.MagicMock() for nome in _SDK}):
        arquivo = Path(__file__).parents[1] / "ros2_ws/src/robot_reaction_ros/robot_reaction_ros/g1_arm_controller.py"
        spec = importlib.util.spec_from_file_location("g1_arm_controller_teste", arquivo)
        modulo = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = modulo
        spec.loader.exec_module(modulo)
        yield modulo.G1ArmController.__new__(modulo.G1ArmController)
        del sys.modules[spec.name]


def _preparar(robo, modo, balance_pose=None):
    import threading

    robo.action_lock = threading.Lock()
    robo.initialized_801 = False
    robo.balance_pose = balance_pose
    robo.loco = mock.MagicMock()
    robo.log = lambda _texto: None
    robo.state = lambda _rotulo: (801, modo)
    robo.wait_low_state = lambda timeout=0: True
    robo.current_all_arm_position = lambda: {"capturada": True}


def _braco_pronto(robo, leituras):
    import threading

    robo.initialized_801 = True
    robo.pose_lock = threading.Lock()
    robo.command_pose = robo.target_pose = None
    robo.arm_enabled = False
    robo.log = lambda _texto: None
    robo.current_all_arm_position = lambda: {"atual": True}
    robo.lidas = 0

    def ler(_rotulo):
        robo.lidas += 1
        return leituras[min(robo.lidas - 1, len(leituras) - 1)]

    robo.state = ler


def test_arm_control_reads_once_when_the_robot_answers(controlador):
    _braco_pronto(controlador, [(801, 0)])
    assert controlador.enable_arm_control() is True
    assert controlador.lidas == 1


def test_a_failed_reading_right_after_walking_does_not_abort_the_gesture(controlador, monkeypatch):
    # No robô: andou até a pessoa e a rotina acabava sem nenhum gesto nem fala.
    _braco_pronto(controlador, [(None, None), (801, 1), (801, 0)])
    monkeypatch.setattr("time.sleep", lambda _s: None)
    assert controlador.enable_arm_control() is True
    assert controlador.lidas == 3


def test_arm_control_still_refuses_when_not_in_balance(controlador, monkeypatch):
    _braco_pronto(controlador, [(4, 0)])
    monkeypatch.setattr("time.sleep", lambda _s: None)
    relogio = iter(range(0, 1000))
    monkeypatch.setattr("time.time", lambda: float(next(relogio)))
    assert controlador.enable_arm_control() is False
    assert controlador.arm_enabled is False


def test_mode_0_captures_the_balance_pose(controlador):
    _preparar(controlador, 0)
    assert controlador.initialize_to_balance(permitir_damp=False) is True
    assert controlador.balance_pose == {"capturada": True}


def test_mode_3_standing_never_goes_through_damp(controlador):
    _preparar(controlador, 3)
    assert controlador.initialize_to_balance(permitir_damp=False) is True
    controlador.loco.SetFsmId.assert_not_called()
