"""As poses que o g1_arm_controller.py lê estão no repositório (a rotina não depende do ~/hhhh).

Sem importar o módulo (ele precisa do SDK da Unitree): lê os nomes dos arquivos no código-fonte.
"""
import json
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "ros2_ws" / "src" / "robot_reaction_ros"
CONTROLLER = PKG / "robot_reaction_ros" / "g1_arm_controller.py"
POSES = PKG / "poses"


def _referenced() -> set:
    return set(re.findall(r'DEFAULT_POSE_DIRECTORY / "([^"]+\.json)"', CONTROLLER.read_text(encoding="utf-8")))


def test_every_pose_the_controller_reads_is_in_the_repo():
    referenced = _referenced()
    assert len(referenced) >= 10
    missing = sorted(n for n in referenced if not (POSES / n).is_file())
    assert not missing, f"poses faltando em {POSES}: {missing}"


def test_poses_are_valid_json():
    for path in sorted(POSES.glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))


def test_controller_has_no_gui_nor_hhhh_path():
    source = CONTROLLER.read_text(encoding="utf-8")
    assert "import tkinter" not in source and "from tkinter" not in source
    assert "/home/unitree/hhhh" not in source
