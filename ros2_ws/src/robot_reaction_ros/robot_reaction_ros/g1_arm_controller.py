"""Controle dos braços e mãos do Unitree G1 para as posturas militares (sem interface gráfica).

Cópia do `G1ArmController` de `~/hhhh/g1_arm_calibration_gui_v29.py` (projeto de voz e movimentos
militares que divide o robô com o nosso), trazida em 2026-11-03 para a rotina de cumprimento não
depender da pasta ~/hhhh. O movimento é o mesmo; as únicas mudanças, marcadas com [ipe-2-code]:

- sem a GUI (classe G1ArmCalibrationGUI, tkinter e main);
- poses lidas de `robot_reaction_ros/poses/` (cópia de ~/hhhh/poses/; G1_POSE_DIR muda o lugar);
- `wait_fsm4_transition_complete` na versão tolerante do ~/hhhh/movimentos_militares.py;
- `rest_forward_pulse`: desliga o passo para frente do Descansar (padrão ligado, como no ~/hhhh);
- `shutdown` devolve os braços ANTES de parar a thread de controle (no ~/hhhh, parar a thread
  primeiro deixava o retorno ao equilíbrio sem ninguém movendo os braços).

Precisa do unitree_sdk2py, numpy e pymodbus (mãos Inspire por Modbus TCP): o venv do projeto no
robô. Só o body_worker (processo sem ROS) importa isto. Spec:
docs/superpowers/specs/2026-10-29-rotina-cumprimento-design.md
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Dict, Optional

import numpy as np

from unitree_sdk2py.core.channel import (
    ChannelFactoryInitialize,
    ChannelPublisher,
    ChannelSubscriber,
)
from unitree_sdk2py.g1.loco.g1_loco_api import (
    ROBOT_API_ID_LOCO_GET_FSM_ID,
    ROBOT_API_ID_LOCO_GET_FSM_MODE,
)
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
from unitree_sdk2py.idl.default import (
    unitree_go_msg_dds__WirelessController_,
    unitree_hg_msg_dds__LowCmd_,
)
from unitree_sdk2py.idl.unitree_go.msg.dds_ import WirelessController_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_
from unitree_sdk2py.utils.crc import CRC

try:
    from pymodbus.client import ModbusTcpClient
except ImportError as exc:
    raise ImportError(
        "A biblioteca pymodbus não está instalada. "
        "Use o mesmo ambiente Python no qual o Inspire Hand SDK foi instalado."
    ) from exc


class G1JointIndex:
    # Cintura / tronco
    WaistYaw = 12
    WaistRoll = 13
    WaistPitch = 14

    # Braço esquerdo
    LeftShoulderPitch = 15
    LeftShoulderRoll = 16
    LeftShoulderYaw = 17
    LeftElbow = 18
    LeftWristRoll = 19
    LeftWristPitch = 20
    LeftWristYaw = 21

    # Braço direito
    RightShoulderPitch = 22
    RightShoulderRoll = 23
    RightShoulderYaw = 24
    RightElbow = 25
    RightWristRoll = 26
    RightWristPitch = 27
    RightWristYaw = 28

    # Índice especial usado para habilitar/liberar o arm_sdk
    kNotUsedJoint = 29


LEFT_ARM_JOINTS = [
    G1JointIndex.LeftShoulderPitch,
    G1JointIndex.LeftShoulderRoll,
    G1JointIndex.LeftShoulderYaw,
    G1JointIndex.LeftElbow,
    G1JointIndex.LeftWristRoll,
    G1JointIndex.LeftWristPitch,
    G1JointIndex.LeftWristYaw,
]

RIGHT_ARM_JOINTS = [
    G1JointIndex.RightShoulderPitch,
    G1JointIndex.RightShoulderRoll,
    G1JointIndex.RightShoulderYaw,
    G1JointIndex.RightElbow,
    G1JointIndex.RightWristRoll,
    G1JointIndex.RightWristPitch,
    G1JointIndex.RightWristYaw,
]

WAIST_JOINTS = [
    G1JointIndex.WaistYaw,
    G1JointIndex.WaistRoll,
    G1JointIndex.WaistPitch,
]

ALL_ARM_JOINTS = LEFT_ARM_JOINTS + RIGHT_ARM_JOINTS
CONTROLLED_UPPER_BODY_JOINTS = WAIST_JOINTS + ALL_ARM_JOINTS

RIGHT_JOINT_NAMES = {
    "RightShoulderPitch": G1JointIndex.RightShoulderPitch,
    "RightShoulderRoll": G1JointIndex.RightShoulderRoll,
    "RightShoulderYaw": G1JointIndex.RightShoulderYaw,
    "RightElbow": G1JointIndex.RightElbow,
    "RightWristRoll": G1JointIndex.RightWristRoll,
    "RightWristPitch": G1JointIndex.RightWristPitch,
    "RightWristYaw": G1JointIndex.RightWristYaw,
}

LEFT_JOINT_NAMES = {
    "LeftShoulderPitch": G1JointIndex.LeftShoulderPitch,
    "LeftShoulderRoll": G1JointIndex.LeftShoulderRoll,
    "LeftShoulderYaw": G1JointIndex.LeftShoulderYaw,
    "LeftElbow": G1JointIndex.LeftElbow,
    "LeftWristRoll": G1JointIndex.LeftWristRoll,
    "LeftWristPitch": G1JointIndex.LeftWristPitch,
    "LeftWristYaw": G1JointIndex.LeftWristYaw,
}

# Correspondência usada para espelhar no braço direito a postura já correta
# observada no braço esquerdo. Os sinais invertidos correspondem aos eixos
# laterais/rotacionais entre os lados esquerdo e direito.
ATTENTION_MIRROR = {
    G1JointIndex.RightShoulderPitch: (G1JointIndex.LeftShoulderPitch, 1.0),
    G1JointIndex.RightShoulderRoll: (G1JointIndex.LeftShoulderRoll, -1.0),
    G1JointIndex.RightShoulderYaw: (G1JointIndex.LeftShoulderYaw, -1.0),
    G1JointIndex.RightElbow: (G1JointIndex.LeftElbow, 1.0),
    G1JointIndex.RightWristRoll: (G1JointIndex.LeftWristRoll, -1.0),
    G1JointIndex.RightWristPitch: (G1JointIndex.LeftWristPitch, 1.0),
    G1JointIndex.RightWristYaw: (G1JointIndex.LeftWristYaw, -1.0),
}

# Faixas deliberadamente conservadoras para a interface.
# Ajuste-as somente depois de confirmar os limites aplicáveis ao seu G1.
SLIDER_LIMITS = {
    "LeftShoulderPitch": (-1.50, 1.50),
    "LeftShoulderRoll": (-1.00, 1.80),
    "LeftShoulderYaw": (-1.50, 1.50),
    "LeftElbow": (-1.50, 1.50),
    "LeftWristRoll": (-1.20, 1.20),
    "LeftWristPitch": (-1.00, 1.00),
    "LeftWristYaw": (-1.00, 1.00),
    "RightShoulderPitch": (-1.50, 1.50),
    "RightShoulderRoll": (-1.80, 1.00),
    "RightShoulderYaw": (-1.50, 1.50),
    "RightElbow": (-1.50, 1.50),
    "RightWristRoll": (-1.20, 1.20),
    "RightWristPitch": (-1.00, 1.00),
    "RightWristYaw": (-1.00, 1.00),
}


HAND_MOTOR_NAMES = {
    "little": 0,
    "ring": 1,
    "middle": 2,
    "index": 3,
    "thumb_bend": 4,
    "thumb_rotation": 5,
}

HAND_DISPLAY_NAMES = {
    "little": "Dedo mínimo",
    "ring": "Dedo anelar",
    "middle": "Dedo médio",
    "index": "Dedo indicador",
    "thumb_bend": "Flexão do polegar",
    "thumb_rotation": "Rotação do polegar",
}

LEFT_HAND_IP = "192.168.123.210"
RIGHT_HAND_IP = "192.168.123.211"
HAND_PORT = 6000
HAND_ANGLE_SET_REGISTER = 1486
HAND_ANGLE_ACT_REGISTER = 1546
HAND_FORCE_ACT_REGISTER = 1582
HAND_ERROR_REGISTER = 1606
HAND_TEMP_REGISTER = 1618
# Valores reais usados pelo controlador Inspire Hand:
#   0    = totalmente fechado/dobrado
#   1000 = totalmente aberto
LEFT_HAND_LIMITS = {name: (0.0, 1000.0) for name in HAND_MOTOR_NAMES}
RIGHT_HAND_LIMITS = {name: (0.0, 1000.0) for name in HAND_MOTOR_NAMES}

# Convenção visual dos sliders da interface (mais intuitiva):
#   0    = mão aberta / sem fechamento
#   1000 = fechamento máximo
HAND_SLIDER_MIN = 0.0
HAND_SLIDER_MAX = 1000.0

def hand_slider_to_hardware(value: float) -> float:
    """Converte fechamento visual (0 aberto) em ângulo Inspire (1000 aberto)."""
    slider = float(np.clip(value, HAND_SLIDER_MIN, HAND_SLIDER_MAX))
    return HAND_SLIDER_MAX - slider

def hand_hardware_to_slider(value: float) -> float:
    """Converte ângulo Inspire em fechamento visual da interface."""
    hardware = float(np.clip(value, HAND_SLIDER_MIN, HAND_SLIDER_MAX))
    return HAND_SLIDER_MAX - hardware

# [ipe-2-code] As poses vêm do repositório (robot_reaction_ros/poses), não do ~/hhhh. O body_worker
# define G1_POSE_DIR antes de importar este módulo.
DEFAULT_POSE_DIRECTORY = Path(os.environ.get("G1_POSE_DIR") or Path(__file__).resolve().parent.parent / "poses")
SALUTE_POSE_FILE = DEFAULT_POSE_DIRECTORY / "continencia1.json"
ATTENTION_STAGE1_FILE = DEFAULT_POSE_DIRECTORY / "sentido_1estagio.json"
ATTENTION_STAGE2_FILE = DEFAULT_POSE_DIRECTORY / "sentido_2estagio.json"
REST_STAGE1_FILE = DEFAULT_POSE_DIRECTORY / "descansar1.json"
REST_STAGE2_FILE = DEFAULT_POSE_DIRECTORY / "descansar2.json"
REST_STAGE3_FILE = DEFAULT_POSE_DIRECTORY / "descansar3.json"
REST_STAGE4_FILE = DEFAULT_POSE_DIRECTORY / "descansar4.json"
REST_EXIT_STAGE0_FILE = DEFAULT_POSE_DIRECTORY / "u_descansar0.json"
REST_EXIT_STAGE1_FILE = DEFAULT_POSE_DIRECTORY / "u_descansar1.json"
REST_EXIT_STAGE2_FILE = DEFAULT_POSE_DIRECTORY / "u_descansar2.json"
HAND_BALANCE_POSE_FILE = DEFAULT_POSE_DIRECTORY / "maos0.json"
HAND_ATTENTION_POSE_FILE = DEFAULT_POSE_DIRECTORY / "maos_sentido.json"
HAND_REST_POSE_FILE = DEFAULT_POSE_DIRECTORY / "maos_descansar.json"

# Compensação temporária do tronco durante a transição do primeiro para o
# segundo estágio de Descansar. Valor em radianos: 0.08 rad ≈ 4.6 graus.
# Nesta configuração do G1, a compensação para frente usa valor negativo de WaistPitch.
# Amplitude aumentada em relação à v18 para reforçar o equilíbrio durante o Descansar.
REST_FORWARD_WAIST_PITCH_OFFSET = 0.20

# Compensação dinâmica adicional durante a transição descansar1 -> descansar2.
# O comando de avanço é reenviado em tentativas curtas para aumentar a chance
# de ser aceito pelo controlador de locomoção antes do movimento dos braços.
REST_FORWARD_VELOCITY = 0.12
REST_FORWARD_VELOCITY_DURATION = 1.00
REST_FORWARD_PULSE_LEAD_TIME = 0.30
REST_FORWARD_PULSE_ATTEMPTS = 3
REST_FORWARD_RETRY_INTERVAL = 0.10
REST_ACTION_MAX_JOINT_SPEED = 0.40
DESC_ARMA_MAX_JOINT_SPEED = 1.40


class G1ArmController:
    def __init__(
        self,
        iface: str,
        kp: float = 35.0,
        kd: float = 1.2,
        max_joint_speed: float = 0.35,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.iface = iface
        self.kp = kp
        self.kd = kd
        self.max_joint_speed = max_joint_speed
        self.log_callback = log_callback

        self.low_state: Optional[LowState_] = None
        self.crc = CRC()

        self.initialized_801 = False
        # [ipe-2-code] False = Descansar sem o pulso de SetVelocity para frente (o robô não anda).
        self.rest_forward_pulse = True
        self.arm_enabled = False
        self.releasing = False
        self.shutdown_event = threading.Event()

        self.pose_lock = threading.RLock()
        self.action_lock = threading.Lock()

        self.balance_pose: Optional[Dict[int, float]] = None
        self.command_pose: Optional[Dict[int, float]] = None
        self.target_pose: Optional[Dict[int, float]] = None
        self.left_hand_target = {i: 0.0 for i in range(6)}
        self.right_hand_target = {i: 0.0 for i in range(6)}
        self.hand_lock = threading.RLock()
        self.left_hand_client: Optional[ModbusTcpClient] = None
        self.right_hand_client: Optional[ModbusTcpClient] = None
        self.left_hand_modbus_lock = threading.RLock()
        self.right_hand_modbus_lock = threading.RLock()

        # Registro simples da última postura comandada pela interface.
        # Usado para preservar explicitamente o braço esquerdo ao alternar
        # de "Desc arma" para "Continência".
        self.posture_state = "unknown"

        ChannelFactoryInitialize(0, self.iface)

        self.loco = LocoClient()
        self.loco.SetTimeout(5.0)
        self.loco.Init()

        self.wireless_pub = ChannelPublisher(
            "rt/wirelesscontroller",
            WirelessController_,
        )
        self.wireless_pub.Init()

        self.arm_pub = ChannelPublisher("rt/arm_sdk", LowCmd_)
        self.arm_pub.Init()

        self.lowstate_sub = ChannelSubscriber("rt/lowstate", LowState_)
        self.lowstate_sub.Init(self._low_state_handler, 10)

        self.control_thread = threading.Thread(
            target=self._arm_control_loop,
            name="g1-arm-control",
            daemon=True,
        )
        self.control_thread.start()


    def log(self, text: str) -> None:
        print(text)
        if self.log_callback:
            self.log_callback(text)

    def _low_state_handler(self, msg: LowState_) -> None:
        self.low_state = msg

    @staticmethod
    def _hand_ip(side: str) -> str:
        if side == "left":
            return LEFT_HAND_IP
        if side == "right":
            return RIGHT_HAND_IP
        raise ValueError("Lado da mão inválido.")

    def _hand_client_and_lock(self, side: str):
        if side == "left":
            return self.left_hand_client, self.left_hand_modbus_lock
        if side == "right":
            return self.right_hand_client, self.right_hand_modbus_lock
        raise ValueError("Lado da mão inválido.")

    def _set_hand_client(self, side: str, client: Optional[ModbusTcpClient]) -> None:
        if side == "left":
            self.left_hand_client = client
        elif side == "right":
            self.right_hand_client = client
        else:
            raise ValueError("Lado da mão inválido.")

    def _connect_hand(self, side: str) -> ModbusTcpClient:
        client, lock = self._hand_client_and_lock(side)
        with lock:
            if client is not None:
                try:
                    if getattr(client, "connected", False):
                        return client
                except Exception:
                    pass
                try:
                    client.close()
                except Exception:
                    pass

            ip = self._hand_ip(side)
            client = ModbusTcpClient(ip, port=HAND_PORT, timeout=2.0)
            if not client.connect():
                client.close()
                raise ConnectionError(
                    f"Não foi possível conectar à mão {side} em {ip}:{HAND_PORT}."
                )
            self._set_hand_client(side, client)
            self.log(f"Mão {side} conectada em {ip}:{HAND_PORT}.")
            return client

    @staticmethod
    def _check_modbus_response(response, operation: str) -> None:
        if response is None:
            raise RuntimeError(f"Sem resposta Modbus ao {operation}.")
        if response.isError():
            raise RuntimeError(f"Erro Modbus ao {operation}: {response}")

    def _read_hand_registers(
        self,
        side: str,
        address: int,
        count: int = 6,
    ) -> list[int]:
        """Lê registradores usando exatamente o protocolo já validado."""
        client = self._connect_hand(side)
        _, lock = self._hand_client_and_lock(side)
        with lock:
            try:
                response = client.read_holding_registers(
                    address=address,
                    count=count,
                )
                self._check_modbus_response(response, "ler registradores")
                return list(response.registers)
            except Exception:
                try:
                    client.close()
                finally:
                    self._set_hand_client(side, None)
                raise

    def _write_hand_angles(self, side: str, values: list[int]) -> None:
        """Escreve o grupo ANGLE_SET de seis DOFs."""
        if len(values) != 6:
            raise ValueError("A pose da mão deve conter exatamente seis valores.")

        # -1 significa não movimentar o DOF. O pymodbus recebe a
        # representação unsigned do short negativo, como no script validado.
        unsigned_values = [int(value) & 0xFFFF for value in values]

        client = self._connect_hand(side)
        _, lock = self._hand_client_and_lock(side)
        with lock:
            try:
                response = client.write_registers(
                    address=HAND_ANGLE_SET_REGISTER,
                    values=unsigned_values,
                )
                self._check_modbus_response(response, "escrever ângulos")
            except Exception:
                try:
                    client.close()
                finally:
                    self._set_hand_client(side, None)
                raise

    def set_hand_target(self, side: str, target: Dict[int, float]) -> bool:
        if side not in ("left", "right"):
            raise ValueError("Lado da mão inválido.")

        limits = LEFT_HAND_LIMITS if side == "left" else RIGHT_HAND_LIMITS
        validated: Dict[int, int] = {}
        for name, dof in HAND_MOTOR_NAMES.items():
            if dof not in target:
                raise ValueError(f"Alvo ausente para {side} {name}.")
            minimum, maximum = limits[name]
            validated[dof] = int(
                round(float(np.clip(target[dof], minimum, maximum)))
            )

        ordered_values = [validated[dof] for dof in range(6)]
        self._write_hand_angles(side, ordered_values)

        with self.hand_lock:
            if side == "left":
                self.left_hand_target = {
                    dof: float(value) for dof, value in validated.items()
                }
            else:
                self.right_hand_target = {
                    dof: float(value) for dof, value in validated.items()
                }

        self.log(
            f"Pose da mão {side} aplicada por Modbus TCP em "
            f"{self._hand_ip(side)}:{HAND_PORT}."
        )
        return True

    def set_hand_dof(self, side: str, dof: int, angle: float) -> bool:
        """Move somente um DOF; os outros recebem -1 e permanecem imóveis."""
        if side not in ("left", "right"):
            raise ValueError("Lado da mão inválido.")
        if dof not in range(6):
            raise ValueError(f"DOF inválido: {dof}")

        value = int(round(float(np.clip(angle, 0.0, 1000.0))))
        values = [-1] * 6
        values[dof] = value
        self._write_hand_angles(side, values)

        with self.hand_lock:
            target = (
                self.left_hand_target
                if side == "left"
                else self.right_hand_target
            )
            target[dof] = float(value)

        dof_name = next(
            name for name, index in HAND_MOTOR_NAMES.items() if index == dof
        )
        self.log(f"Mão {side}: {dof_name} ajustado para {value}.")
        return True

    def set_both_hands_target(
        self,
        left: Dict[int, float],
        right: Dict[int, float],
    ) -> bool:
        self.set_hand_target("left", left)
        self.set_hand_target("right", right)
        return True

    def stop_hand_control(self, side: str = "both") -> None:
        # Modbus envia comandos pontuais; não existe publicação contínua.
        self.log(f"Comandos Modbus das mãos são pontuais: {side}.")

    def current_hand_by_name(self, side: str) -> Optional[Dict[str, float]]:
        registers = self._read_hand_registers(
            side,
            HAND_ANGLE_ACT_REGISTER,
            count=6,
        )
        return {
            name: float(registers[dof])
            for name, dof in HAND_MOTOR_NAMES.items()
        }

    def load_both_hands_pose_file(
        self,
        filename: Path,
    ) -> Optional[tuple[Dict[int, float], Dict[int, float]]]:
        """Carrega de um JSON as poses completas das mãos esquerda e direita."""
        try:
            data = json.loads(filename.read_text(encoding="utf-8"))
            if "left_hand" not in data or "right_hand" not in data:
                raise ValueError(
                    "O arquivo deve conter as seções left_hand e right_hand."
                )

            left_data = data["left_hand"]
            right_data = data["right_hand"]
            missing_left = [
                name for name in HAND_MOTOR_NAMES if name not in left_data
            ]
            missing_right = [
                name for name in HAND_MOTOR_NAMES if name not in right_data
            ]
            if missing_left:
                raise ValueError(
                    "DOFs ausentes na mão esquerda: " + ", ".join(missing_left)
                )
            if missing_right:
                raise ValueError(
                    "DOFs ausentes na mão direita: " + ", ".join(missing_right)
                )

            left = {
                dof: float(left_data[name])
                for name, dof in HAND_MOTOR_NAMES.items()
            }
            right = {
                dof: float(right_data[name])
                for name, dof in HAND_MOTOR_NAMES.items()
            }
            return left, right

        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.log(f"ERRO ao carregar a pose das mãos {filename}: {exc}")
            return None

    def apply_both_hands_pose_file(self, filename: Path, label: str) -> bool:
        """Carrega e aplica uma pose bilateral das mãos por Modbus TCP."""
        pose = self.load_both_hands_pose_file(filename)
        if pose is None:
            return False
        left, right = pose
        try:
            self.set_both_hands_target(left, right)
            self.log(f"Mãos em {label}: {filename.name}")
            return True
        except Exception as exc:
            self.log(
                f"ERRO ao aplicar a pose das mãos {filename.name}: {exc}"
            )
            return False

    def wait_low_state(self, timeout: float = 5.0) -> bool:
        self.log("Aguardando LowState...")
        start = time.time()

        while time.time() - start < timeout:
            if self.low_state is not None:
                self.log("LowState recebido.")
                return True
            time.sleep(0.05)

        self.log("ERRO: LowState não recebido.")
        return False

    def get_fsm_value(self, api_id: int):
        code, data = self.loco._Call(api_id, "{}")
        if code != 0 or data is None:
            return None

        try:
            return json.loads(data)["data"]
        except (KeyError, TypeError, json.JSONDecodeError):
            return None

    def state(self, label: str):
        fsm_id = self.get_fsm_value(ROBOT_API_ID_LOCO_GET_FSM_ID)
        fsm_mode = self.get_fsm_value(ROBOT_API_ID_LOCO_GET_FSM_MODE)
        self.log(f"{label}: FSM_ID={fsm_id}, FSM_MODE={fsm_mode}")
        return fsm_id, fsm_mode

    def wait_fsm4_transition_complete(self, timeout: float = 30.0) -> bool:
        """[ipe-2-code] Versão do ~/hhhh/movimentos_militares.py (a que o F1+UP usa), não a da v29.

        Cobre o caso em que MODE=1 passa rápido demais para ser observado. Aceita MODE 1 -> MODE 0
        ou FSM 4 / MODE 0 estável por três leituras seguidas.
        """
        self.log("Esperando a transição completa do FSM 4...")
        start = time.time()
        saw_mode_1 = False
        stable_4_0 = 0

        while time.time() - start < timeout:
            fsm_id, fsm_mode = self.state("Aguardando FSM 4")

            if fsm_id == 4 and fsm_mode == 1:
                saw_mode_1 = True
                stable_4_0 = 0
            elif fsm_id == 4 and fsm_mode == 0:
                if saw_mode_1:
                    self.log("FSM 4 pronto: MODE=1 -> MODE=0.")
                    return True
                stable_4_0 += 1
                self.log(f"FSM 4 / MODE 0 observado {stable_4_0}/3.")
                if stable_4_0 >= 3:
                    self.log("FSM 4 / MODE 0 estável. Transição considerada concluída.")
                    return True
            elif fsm_id not in (4, None):
                # Respostas None da API não zeram a evidência já obtida de FSM 4 / MODE 0.
                stable_4_0 = 0

            time.sleep(0.5)

        self.log("ERRO: FSM 4 não completou a transição esperada.")
        return False

    def publish_keys(self, keys: int, duration: float = 0.4) -> None:
        cmd = unitree_go_msg_dds__WirelessController_()
        cmd.lx = 0.0
        cmd.ly = 0.0
        cmd.rx = 0.0
        cmd.ry = 0.0
        cmd.keys = keys

        start = time.time()
        while time.time() - start < duration:
            self.wireless_pub.Write(cmd)
            time.sleep(0.02)

    def virtual_r2_a(self) -> None:
        self.log("R2 virtual / keys=0x10")
        self.publish_keys(0x10, 0.20)

        self.log("R2+A virtual / keys=0x110")
        self.publish_keys(0x110, 0.80)

        self.log("R2 virtual / keys=0x10")
        self.publish_keys(0x10, 0.20)

        self.log("Soltar botões / keys=0x0")
        self.publish_keys(0x0, 0.40)

    def enter_801_with_retry(self, attempts: int = 3) -> bool:
        for attempt in range(1, attempts + 1):
            self.log(f"Tentativa {attempt} para entrar em FSM 801")
            self.virtual_r2_a()

            start = time.time()
            while time.time() - start < 5.0:
                fsm_id, fsm_mode = self.state("Aguardando FSM 801")
                if fsm_id == 801 and fsm_mode == 0:
                    self.log("Entrou em FSM 801.")
                    return True
                time.sleep(0.5)

            self.log("Ainda não entrou em FSM 801.")

        self.log("ERRO: não chegou ao FSM 801 após as tentativas.")
        return False

    def initialize_to_balance(self, permitir_damp: bool = True) -> bool:
        """
        Coloca o robô em FSM 801 e captura a postura equilibrada dos braços.
        Esta operação é protegida para não executar simultaneamente com outra.

        [ipe-2-code] permitir_damp=False: o robô está em pé; se ele não confirmar FSM 801/0 aqui
        (leitura falhou, modo de transição), recusa em vez de cair no damp abaixo, que o derrubaria
        fora do suporte. Em 2026-11-05 o robô caiu em damp numa partida "só em equilíbrio".
        """
        if not self.action_lock.acquire(blocking=False):
            self.log("Outra operação já está em andamento.")
            return False

        try:
            if self.initialized_801 or not permitir_damp:
                fsm_id, fsm_mode = self.state("Estado atual")
                # [ipe-2-code] em pé: relê por até 5 s (leitura que falha/MODE mudando).
                # MODE 3 (arm_sdk ativo) só com a postura já capturada: capturar agora guardaria
                # braços que podem estar fora do equilíbrio, e o à vontade voltaria para eles.
                # MODE None (o RPC do MODE não respondeu) com FSM 801 também é equilíbrio.
                def equilibrio() -> bool:
                    return fsm_id == 801 and (
                        fsm_mode == 0
                        or (fsm_mode == 3 and self.balance_pose is not None)
                        or (not permitir_damp and fsm_mode is None)
                    )

                fim = time.time() + (0.0 if permitir_damp else 5.0)
                while not equilibrio() and time.time() < fim:
                    time.sleep(0.5)
                    fsm_id, fsm_mode = self.state("Estado atual")
                if equilibrio():
                    self.log("O robô já está em FSM 801 / equilíbrio.")
                    self.initialized_801 = True
                    if self.balance_pose is None and self.wait_low_state():
                        self.balance_pose = self.current_all_arm_position()
                    return True
                if not permitir_damp:
                    self.log(
                        f"ERRO: FSM_ID={fsm_id}, FSM_MODE={fsm_mode} ao confirmar o equilíbrio: "
                        "não inicializo (o damp derrubaria o robô em pé)."
                    )
                    return False

            if not self.wait_low_state(timeout=8.0):
                return False

            self.state("Estado inicial")

            self.log("1) Damp")
            self.log(f"Retorno: {self.loco.SetFsmId(1)}")
            time.sleep(2.0)
            self.state("Depois do Damp")

            self.log("2) FSM 4 / equivalente a L2+Up")
            self.log(f"Retorno: {self.loco.SetFsmId(4)}")

            if not self.wait_fsm4_transition_complete(timeout=30.0):
                return False

            self.log("3) R2+A virtual para entrar em FSM 801")
            if not self.enter_801_with_retry(attempts=3):
                return False

            self.log(
                "StopMove por segurança: "
                f"{self.loco.SetVelocity(0.0, 0.0, 0.0, 1.0)}"
            )
            time.sleep(1.0)

            pose = self.current_all_arm_position()
            if pose is None:
                self.log("ERRO: não foi possível capturar a postura dos braços.")
                return False

            with self.pose_lock:
                self.balance_pose = dict(pose)
                self.command_pose = dict(pose)
                self.target_pose = dict(pose)

            self.initialized_801 = True
            self.arm_enabled = False
            self.posture_state = "equilibrio"
            if not self.apply_both_hands_pose_file(
                HAND_BALANCE_POSE_FILE,
                "posição de equilíbrio",
            ):
                self.log(
                    "ERRO: não foi possível colocar as mãos na pose de equilíbrio."
                )
                return False
            self.log(
                "Robô em FSM 801. Postura equilibrada capturada. "
                f"Cintura fixada em yaw={pose[G1JointIndex.WaistYaw]:.3f}, "
                f"roll={pose[G1JointIndex.WaistRoll]:.3f}, "
                f"pitch={pose[G1JointIndex.WaistPitch]:.3f}."
            )
            return True

        except Exception:
            self.log("ERRO durante a inicialização:")
            self.log(traceback.format_exc())
            return False
        finally:
            self.action_lock.release()

    def current_all_arm_position(self) -> Optional[Dict[int, float]]:
        if self.low_state is None:
            return None

        try:
            return {
                joint: float(self.low_state.motor_state[joint].q)
                for joint in CONTROLLED_UPPER_BODY_JOINTS
            }
        except (IndexError, AttributeError, TypeError):
            return None

    def current_right_arm_position(self) -> Optional[Dict[int, float]]:
        pose = self.current_all_arm_position()
        if pose is None:
            return None
        return {joint: pose[joint] for joint in RIGHT_ARM_JOINTS}

    def current_left_arm_position(self) -> Optional[Dict[int, float]]:
        pose = self.current_all_arm_position()
        if pose is None:
            return None
        return {joint: pose[joint] for joint in LEFT_ARM_JOINTS}

    def _build_arm_command(
        self,
        pose: Dict[int, float],
        enable_arm_sdk: float,
    ) -> LowCmd_:
        cmd = unitree_hg_msg_dds__LowCmd_()

        cmd.motor_cmd[G1JointIndex.kNotUsedJoint].q = float(enable_arm_sdk)

        for joint in CONTROLLED_UPPER_BODY_JOINTS:
            cmd.motor_cmd[joint].tau = 0.0
            cmd.motor_cmd[joint].q = float(pose[joint])
            cmd.motor_cmd[joint].dq = 0.0
            cmd.motor_cmd[joint].kp = self.kp
            cmd.motor_cmd[joint].kd = self.kd

        cmd.crc = self.crc.Crc(cmd)
        return cmd

    def _write_arm_pose(
        self,
        pose: Dict[int, float],
        enable_arm_sdk: float = 1.0,
    ) -> None:
        self.arm_pub.Write(
            self._build_arm_command(pose, enable_arm_sdk)
        )

    def _arm_control_loop(self) -> None:
        """
        Publica continuamente a postura e limita a velocidade da mudança.
        O slider altera apenas target_pose; esta thread faz a aproximação suave.
        """
        frequency = 50.0
        period = 1.0 / frequency
        last_time = time.monotonic()

        while not self.shutdown_event.is_set():
            now = time.monotonic()
            dt = max(0.001, min(now - last_time, 0.1))
            last_time = now

            if self.arm_enabled and not self.releasing:
                with self.pose_lock:
                    if self.command_pose is not None and self.target_pose is not None:
                        arm_max_step = self.max_joint_speed * dt
                        # A cintura é corrigida mais lentamente, mesmo quando
                        # os braços estão configurados para velocidades altas.
                        waist_max_step = min(self.max_joint_speed, 0.30) * dt

                        for joint in CONTROLLED_UPPER_BODY_JOINTS:
                            current = self.command_pose[joint]
                            target = self.target_pose[joint]
                            max_step = (
                                waist_max_step
                                if joint in WAIST_JOINTS
                                else arm_max_step
                            )
                            delta = float(
                                np.clip(target - current, -max_step, max_step)
                            )
                            self.command_pose[joint] = current + delta

                        pose_to_send = dict(self.command_pose)
                    else:
                        pose_to_send = None

                if pose_to_send is not None:
                    try:
                        self._write_arm_pose(
                            pose_to_send,
                            enable_arm_sdk=1.0,
                        )
                    except Exception:
                        self.log("ERRO na publicação do arm_sdk:")
                        self.log(traceback.format_exc())
                        self.arm_enabled = False

            time.sleep(period)

    def enable_arm_control(self) -> bool:
        if not self.initialized_801:
            self.log("Inicialize o robô antes de controlar os braços.")
            return False

        fsm_id, fsm_mode = self.state("Verificando equilíbrio")

        # MODE 0: FSM 801 equilibrado, antes de assumir o controle dos braços.
        # MODE 3: FSM 801 com o arm_sdk ativo. Esse modo aparece normalmente
        # depois que começamos a publicar em rt/arm_sdk.
        if fsm_id != 801 or fsm_mode not in (0, 3):
            self.log(
                "ERRO: o robô não está em FSM 801 compatível "
                f"(FSM_ID={fsm_id}, FSM_MODE={fsm_mode})."
            )
            return False

        current = self.current_all_arm_position()
        if current is None:
            self.log("ERRO: postura atual indisponível.")
            return False

        with self.pose_lock:
            if self.command_pose is None:
                self.command_pose = dict(current)
            if self.target_pose is None:
                self.target_pose = dict(current)

        if not self.arm_enabled:
            self.log("arm_sdk habilitado para controle dos braços.")

        self.arm_enabled = True
        return True

    def set_both_arms_target(
        self,
        left_target: Dict[int, float],
        right_target: Dict[int, float],
    ) -> bool:
        if not self.leave_rest_if_needed():
            return False

        if not self.enable_arm_control():
            return False

        with self.pose_lock:
            if self.target_pose is None:
                return False

            for joint in LEFT_ARM_JOINTS:
                if joint not in left_target:
                    raise ValueError(f"Alvo esquerdo ausente para a junta {joint}.")
                self.target_pose[joint] = float(left_target[joint])

            for joint in RIGHT_ARM_JOINTS:
                if joint not in right_target:
                    raise ValueError(f"Alvo direito ausente para a junta {joint}.")
                self.target_pose[joint] = float(right_target[joint])

            if self.balance_pose is not None:
                for joint in WAIST_JOINTS:
                    self.target_pose[joint] = self.balance_pose[joint]

        return True

    def set_right_arm_target(self, right_target: Dict[int, float]) -> bool:
        if not self.enable_arm_control():
            return False

        with self.pose_lock:
            if self.target_pose is None:
                return False

            for joint in RIGHT_ARM_JOINTS:
                if joint not in right_target:
                    raise ValueError(f"Alvo ausente para a junta {joint}.")
                self.target_pose[joint] = float(right_target[joint])

            # O braço esquerdo permanece na postura equilibrada capturada.
            # A cintura também fica presa à orientação inicial, impedindo que
            # compensações sucessivas dos braços acumulem rotação do tronco.
            if self.balance_pose is not None:
                for joint in LEFT_ARM_JOINTS:
                    self.target_pose[joint] = self.balance_pose[joint]
                for joint in WAIST_JOINTS:
                    self.target_pose[joint] = self.balance_pose[joint]

        return True

    def build_bilateral_pose_from_right(
        self,
        right_pose: Dict[int, float],
    ) -> Optional[Dict[int, float]]:
        """
        Cria uma pose para os dois braços a partir de uma pose do braço
        direito. O braço esquerdo recebe a pose espelhada de forma análoga.
        """
        if self.balance_pose is None:
            return None

        bilateral = dict(self.balance_pose)

        for right_joint in RIGHT_ARM_JOINTS:
            if right_joint not in right_pose:
                raise ValueError(f"Alvo ausente para a junta {right_joint}.")
            bilateral[right_joint] = float(right_pose[right_joint])

        for right_joint, (left_joint, sign) in ATTENTION_MIRROR.items():
            bilateral[left_joint] = sign * float(right_pose[right_joint])

        return bilateral

    def set_all_arm_target(self, target: Dict[int, float]) -> bool:
        if not self.enable_arm_control():
            return False

        with self.pose_lock:
            self.target_pose = {
                joint: float(target[joint])
                for joint in CONTROLLED_UPPER_BODY_JOINTS
            }

        return True

    def build_left_attention_from_right(
        self,
        right_reference: Dict[int, float],
    ) -> Dict[int, float]:
        """Converte uma pose direita na pose análoga do braço esquerdo."""
        return {
            left_joint: sign * float(right_reference[right_joint])
            for right_joint, (left_joint, sign) in ATTENTION_MIRROR.items()
        }

    def is_left_at_attention(
        self,
        right_stage2: Dict[int, float],
        tolerance: float = 0.06,
    ) -> bool:
        """Verifica a postura física do braço esquerdo contra o sentido final."""
        current = self.current_all_arm_position()
        if current is None:
            return False

        expected = self.build_left_attention_from_right(right_stage2)
        max_error = max(
            abs(current[joint] - expected[joint])
            for joint in LEFT_ARM_JOINTS
        )
        self.log(f"Erro máximo do braço esquerdo para sentido: {max_error:.3f} rad")
        return max_error <= tolerance

    def build_target_preserving_left(
        self,
        right_pose: Dict[int, float],
    ) -> Optional[Dict[int, float]]:
        """Cria alvo para o braço direito mantendo o esquerdo onde está."""
        current = self.current_all_arm_position()
        if current is None:
            return None

        target = dict(current)
        for joint in RIGHT_ARM_JOINTS:
            target[joint] = float(right_pose[joint])
        return target

    def move_to_attention(self) -> bool:
        """
        Executa a posição de sentido em dois estágios. Se o braço esquerdo
        já estiver na posição final de sentido, ele é preservado e somente
        o braço direito passa pelos estágios 1 e 2.
        """
        if not self.leave_rest_if_needed():
            return False

        if not self.apply_both_hands_pose_file(
            HAND_ATTENTION_POSE_FILE,
            "posição de sentido",
        ):
            return False

        right_stage1 = self.load_right_arm_pose_file(ATTENTION_STAGE1_FILE)
        right_stage2 = self.load_right_arm_pose_file(ATTENTION_STAGE2_FILE)

        if right_stage1 is None or right_stage2 is None:
            return False

        left_already_ready = self.is_left_at_attention(right_stage2)

        if left_already_ready:
            stage1 = self.build_target_preserving_left(right_stage1)
            stage2 = self.build_target_preserving_left(right_stage2)
            self.log(
                "Braço esquerdo já está em sentido; "
                "somente o braço direito será movimentado."
            )
        else:
            stage1 = self.build_bilateral_pose_from_right(right_stage1)
            stage2 = self.build_bilateral_pose_from_right(right_stage2)

        if stage1 is None or stage2 is None:
            self.log("Não foi possível construir a postura de sentido.")
            return False

        if not self.set_all_arm_target(stage1):
            return False

        self.log(f"Posição de sentido — estágio 1: {ATTENTION_STAGE1_FILE}")
        if not self.wait_until_target(timeout=15.0, tolerance=0.035):
            self.log("AVISO: o estágio 1 não convergiu completamente.")

        # Reconstrói o estágio final para preservar a posição física atual
        # do braço esquerdo após o primeiro estágio.
        if left_already_ready:
            stage2 = self.build_target_preserving_left(right_stage2)
            if stage2 is None:
                return False

        if not self.set_all_arm_target(stage2):
            return False

        self.log(f"Posição de sentido — estágio 2: {ATTENTION_STAGE2_FILE}")
        if self.wait_until_target(timeout=15.0, tolerance=0.035):
            self.posture_state = "sentido"
            self.log("Posição de sentido alcançada.")
            return True

        self.posture_state = "sentido"
        self.log("AVISO: o estágio 2 não convergiu completamente.")
        return True

    def build_bilateral_pose(
        self,
        left_pose: Dict[int, float],
        right_pose: Dict[int, float],
    ) -> Optional[Dict[int, float]]:
        """Combina poses explícitas dos dois braços e fixa a cintura."""
        current = self.current_all_arm_position()
        if current is None:
            return None

        target = dict(current)

        for joint in LEFT_ARM_JOINTS:
            if joint not in left_pose:
                raise ValueError(f"Alvo esquerdo ausente para a junta {joint}.")
            target[joint] = float(left_pose[joint])

        for joint in RIGHT_ARM_JOINTS:
            if joint not in right_pose:
                raise ValueError(f"Alvo direito ausente para a junta {joint}.")
            target[joint] = float(right_pose[joint])

        if self.balance_pose is not None:
            for joint in WAIST_JOINTS:
                target[joint] = float(self.balance_pose[joint])

        return target

    def move_to_rest(self) -> bool:
        """
        Executa a postura de descansar em quatro estágios bilaterais:
        descansar1.json, descansar2.json, descansar3.json e descansar4.json.

        A partir do segundo estágio, aplica uma pequena inclinação do tronco
        para frente para compensar o deslocamento dos braços para trás. Essa
        inclinação é mantida também na posição final descansar4.json.
        """
        stage_files = (
            REST_STAGE1_FILE,
            REST_STAGE2_FILE,
            REST_STAGE3_FILE,
            REST_STAGE4_FILE,
        )

        stages = [self.load_bilateral_pose_file(path) for path in stage_files]
        if any(stage is None for stage in stages):
            self.log("Não foi possível carregar os quatro estágios de Descansar.")
            return False

        # A compensação começa no segundo estágio e permanece até o quarto.
        # Ela só será retirada durante a saída de Descansar, na transição
        # entre u_descansar1.json e u_descansar2.json.
        if self.balance_pose is not None:
            balance_pitch = float(
                self.balance_pose[G1JointIndex.WaistPitch]
            )
            compensated_pitch = (
                balance_pitch + REST_FORWARD_WAIST_PITCH_OFFSET
            )

            for stage_number in (1, 2, 3):
                stage = stages[stage_number]
                if stage is not None:
                    stage[G1JointIndex.WaistPitch] = compensated_pitch

            self.log(
                "Compensação de equilíbrio mantida nos estágios 2, 3 e 4: "
                f"WaistPitch={compensated_pitch:.3f} rad "
                f"(compensação de {REST_FORWARD_WAIST_PITCH_OFFSET:.3f} rad)."
            )

        previous_speed = self.max_joint_speed
        forward_pulse_active = False
        self.max_joint_speed = REST_ACTION_MAX_JOINT_SPEED
        self.log(
            "Descansar — velocidade fixa para todos os estágios: "
            f"{REST_ACTION_MAX_JOINT_SPEED:.2f} rad/s."
        )

        try:
            for number, (path, target) in enumerate(
                zip(stage_files, stages),
                start=1,
            ):
                if number == 2 and self.rest_forward_pulse:  # [ipe-2-code] desligável
                    # A passagem para descansar2 leva os braços para trás.
                    # O pulso começa um pouco antes do movimento dos braços e
                    # permanece ativo durante a transição para ficar perceptível.
                    try:
                        # Reenvia o impulso por SetVelocity para aumentar a
                        # probabilidade de o controlador aceitar o avanço.
                        # Cada chamada solicita o mesmo pulso temporizado;
                        # StopMove() permanece como parada explícita de segurança.
                        for attempt in range(
                            1, REST_FORWARD_PULSE_ATTEMPTS + 1
                        ):
                            response = self.loco.SetVelocity(
                                REST_FORWARD_VELOCITY,
                                0.0,
                                0.0,
                                REST_FORWARD_VELOCITY_DURATION,
                            )
                            forward_pulse_active = True
                            self.log(
                                "Tentativa de impulso para frente "
                                f"{attempt}/{REST_FORWARD_PULSE_ATTEMPTS}: "
                                f"vx={REST_FORWARD_VELOCITY:.3f} m/s por "
                                f"{REST_FORWARD_VELOCITY_DURATION:.2f} s; "
                                f"resposta={response}."
                            )
                            if attempt < REST_FORWARD_PULSE_ATTEMPTS:
                                time.sleep(REST_FORWARD_RETRY_INTERVAL)

                        time.sleep(REST_FORWARD_PULSE_LEAD_TIME)
                    except Exception as exc:
                        self.log(
                            "AVISO: não foi possível aplicar o impulso de "
                            f"compensação para frente: {exc}"
                        )

                if number == 3:
                    self.log(
                        "Transição descansar2 -> descansar3: "
                        "aplicando a pose das mãos de Descansar."
                    )
                    if not self.apply_both_hands_pose_file(
                        HAND_REST_POSE_FILE,
                        "posição de Descansar",
                    ):
                        return False

                if target is None or not self.set_all_arm_target(target):
                    return False

                self.log(f"Descansar — estágio {number}: {path.name}")
                if not self.wait_until_target(timeout=15.0, tolerance=0.035):
                    self.log(
                        f"AVISO: o estágio {number} de Descansar "
                        "não convergiu completamente."
                    )

                if number == 2 and forward_pulse_active:
                    try:
                        self.loco.StopMove()
                        forward_pulse_active = False
                        self.log(
                            "Pulso para frente encerrado após descansar2."
                        )
                    except Exception as exc:
                        self.log(
                            "AVISO: falha ao encerrar o pulso de "
                            f"locomoção: {exc}"
                        )
        finally:
            self.max_joint_speed = previous_speed
            if forward_pulse_active:
                try:
                    self.loco.StopMove()
                except Exception as exc:
                    self.log(
                        "AVISO: falha ao encerrar o pulso de locomoção "
                        f"durante a finalização: {exc}"
                    )

        self.posture_state = "descansar"
        self.log("Posição de Descansar alcançada.")
        return True

    def stop_arm_motion(self) -> bool:
        """
        Interrompe a trajetória, mantendo a posição física atual.
        Não libera o arm_sdk; apenas congela o alvo na posição atual.
        """
        if not self.arm_enabled:
            self.log("O controle dos braços não está ativo.")
            return False

        current = self.current_all_arm_position()
        if current is None:
            self.log("Não foi possível ler a postura atual.")
            return False

        with self.pose_lock:
            self.command_pose = dict(current)
            self.target_pose = dict(current)

        self.log("Trajetória interrompida; braços mantidos na posição atual.")
        return True

    def wait_until_target(
        self,
        timeout: float = 8.0,
        tolerance: float = 0.035,
    ) -> bool:
        start = time.time()

        while time.time() - start < timeout:
            with self.pose_lock:
                if self.command_pose is None or self.target_pose is None:
                    return False

                max_error = max(
                    abs(self.target_pose[j] - self.command_pose[j])
                    for j in CONTROLLED_UPPER_BODY_JOINTS
                )

            if max_error <= tolerance:
                return True

            time.sleep(0.05)

        return False

    def return_to_balance_and_release(self) -> bool:
        """
        Retorna os dois braços à postura capturada na inicialização,
        reduz gradualmente a habilitação do arm_sdk e permanece em FSM 801.
        """
        if not self.action_lock.acquire(blocking=False):
            self.log("Outra operação já está em andamento.")
            return False

        try:
            if not self.leave_rest_if_needed():
                return False

            if self.balance_pose is None:
                self.log("A postura equilibrada não está disponível.")
                return False

            if not self.enable_arm_control():
                return False

            self.log("Retornando os braços à postura equilibrada...")
            with self.pose_lock:
                self.target_pose = dict(self.balance_pose)

            if not self.wait_until_target(timeout=12.0, tolerance=0.035):
                self.log(
                    "AVISO: tempo de retorno excedido; iniciando liberação "
                    "a partir da postura comandada atual."
                )

            self.releasing = True

            with self.pose_lock:
                final_pose = (
                    dict(self.command_pose)
                    if self.command_pose is not None
                    else dict(self.balance_pose)
                )

            self.log("Liberando arm_sdk suavemente...")
            duration = 1.5
            start = time.time()

            while True:
                ratio = float(
                    np.clip((time.time() - start) / duration, 0.0, 1.0)
                )
                enable = 1.0 - ratio
                self._write_arm_pose(final_pose, enable_arm_sdk=enable)

                if ratio >= 1.0:
                    break

                time.sleep(0.02)

            self.arm_enabled = False
            self.releasing = False

            self.log(
                "StopMove: "
                f"{self.loco.SetVelocity(0.0, 0.0, 0.0, 1.0)}"
            )
            time.sleep(0.5)
            self.state("Estado final")
            if not self.apply_both_hands_pose_file(
                HAND_BALANCE_POSE_FILE,
                "posição de equilíbrio",
            ):
                self.log(
                    "ERRO: braços retornaram ao equilíbrio, mas as mãos não."
                )
                return False
            self.posture_state = "equilibrio"
            self.log(
                "Braços liberados e mãos em maos0.json; "
                "robô permanece em FSM 801."
            )
            return True

        except Exception:
            self.arm_enabled = False
            self.releasing = False
            self.log("ERRO ao retornar ao equilíbrio:")
            self.log(traceback.format_exc())
            return False
        finally:
            self.action_lock.release()

    def enter_damp(self) -> bool:
        """Retorna os braços com segurança e coloca o robô em Damp."""
        try:
            if self.arm_enabled:
                if not self.return_to_balance_and_release():
                    self.log("ERRO: não foi possível liberar os braços antes do Damp.")
                    return False

            self.log("Parando qualquer movimento antes de entrar em Damp...")
            self.loco.SetVelocity(0.0, 0.0, 0.0, 1.0)
            time.sleep(0.5)

            self.log("Entrando em Damp...")
            ret = self.loco.SetFsmId(1)
            self.log(f"Retorno SetFsmId(1): {ret}")

            start = time.time()
            while time.time() - start < 10.0:
                fsm_id, fsm_mode = self.state("Aguardando Damp")
                if fsm_id == 1 and fsm_mode == 0:
                    with self.pose_lock:
                        self.initialized_801 = False
                        self.arm_enabled = False
                        self.releasing = False
                        self.balance_pose = None
                        self.command_pose = None
                        self.target_pose = None
                    self.posture_state = "damp"
                    self.log("Robô em Damp.")
                    return True
                time.sleep(0.5)

            self.log("ERRO: o robô não confirmou Damp.")
            return False

        except Exception:
            self.log("ERRO ao entrar em Damp:")
            self.log(traceback.format_exc())
            return False

    def load_left_arm_pose_file(
        self,
        filename: Path,
    ) -> Optional[Dict[int, float]]:
        """
        Carrega um JSON de pose do braço esquerdo e converte os nomes
        das juntas para os índices usados pelo controlador.
        """
        try:
            data = json.loads(filename.read_text(encoding="utf-8"))
            pose = data.get("left_arm", data)

            missing = [
                name for name in LEFT_JOINT_NAMES
                if name not in pose
            ]
            if missing:
                raise ValueError(
                    "Juntas ausentes no arquivo: " + ", ".join(missing)
                )

            return {
                LEFT_JOINT_NAMES[name]: float(pose[name])
                for name in LEFT_JOINT_NAMES
            }

        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.log(f"ERRO ao carregar a pose {filename}: {exc}")
            return None

    def load_right_arm_pose_file(
        self,
        filename: Path,
    ) -> Optional[Dict[int, float]]:
        """Carrega uma pose JSON e converte nomes para índices de juntas."""
        try:
            data = json.loads(filename.read_text(encoding="utf-8"))
            pose = data.get("right_arm", data)

            missing = [
                name for name in RIGHT_JOINT_NAMES
                if name not in pose
            ]
            if missing:
                raise ValueError(
                    "Juntas ausentes no arquivo: " + ", ".join(missing)
                )

            return {
                RIGHT_JOINT_NAMES[name]: float(pose[name])
                for name in RIGHT_JOINT_NAMES
            }

        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.log(f"ERRO ao carregar a pose {filename}: {exc}")
            return None

    def load_bilateral_pose_file(
        self,
        filename: Path,
    ) -> Optional[Dict[int, float]]:
        """Carrega de um único JSON as poses explícitas dos dois braços."""
        left_pose = self.load_left_arm_pose_file(filename)
        right_pose = self.load_right_arm_pose_file(filename)

        if left_pose is None or right_pose is None:
            return None

        return self.build_bilateral_pose(left_pose, right_pose)

    def leave_rest_if_needed(self) -> bool:
        """
        Se o robô estiver em Descansar, executa obrigatoriamente os três
        estágios de saída antes de aceitar a próxima pose comandada.
        """
        if self.posture_state != "descansar":
            return True

        self.log(
            "Robô em Descansar; executando os três estágios obrigatórios de saída."
        )

        stage_files = (
            REST_EXIT_STAGE0_FILE,
            REST_EXIT_STAGE1_FILE,
            REST_EXIT_STAGE2_FILE,
        )
        stages = [self.load_bilateral_pose_file(path) for path in stage_files]

        if any(stage is None for stage in stages):
            self.log("Não foi possível carregar os três estágios de saída de Descansar.")
            return False

        # u_descansar0.json e u_descansar1.json mantêm a inclinação usada em
        # Descansar. u_descansar2.json restaura o WaistPitch da postura
        # equilibrada, desfazendo a compensação somente na última transição.
        if self.balance_pose is not None:
            balance_pitch = float(
                self.balance_pose[G1JointIndex.WaistPitch]
            )
            compensated_pitch = (
                balance_pitch + REST_FORWARD_WAIST_PITCH_OFFSET
            )
            stages[0][G1JointIndex.WaistPitch] = compensated_pitch
            stages[1][G1JointIndex.WaistPitch] = compensated_pitch
            stages[2][G1JointIndex.WaistPitch] = balance_pitch
            self.log(
                "Saída de Descansar: inclinação mantida em u_descansar0 e "
                "u_descansar1, e restaurada em u_descansar2."
            )

        for number, (path, target) in enumerate(
            zip(stage_files, stages),
            start=0,
        ):
            if target is None or not self.set_all_arm_target(target):
                return False

            self.log(
                f"Saída de Descansar — estágio {number}: {path.name}"
            )
            if not self.wait_until_target(timeout=15.0, tolerance=0.035):
                self.log(
                    f"AVISO: o estágio {number} da saída de Descansar "
                    "não convergiu completamente."
                )

        self.posture_state = "saida_descansar"
        self.log("Saída da posição de Descansar concluída.")
        return True

    def build_salute_with_left_attention(
        self,
        right_salute: Dict[int, float],
        right_attention_reference: Dict[int, float],
    ) -> Optional[Dict[int, float]]:
        """
        Cria uma pose bilateral na qual o braço direito permanece na
        continência e o braço esquerdo assume a posição de sentido espelhada
        a partir de um arquivo de pose criado para o braço direito.
        """
        if self.balance_pose is None:
            return None

        target = dict(self.balance_pose)

        for joint in RIGHT_ARM_JOINTS:
            if joint not in right_salute:
                raise ValueError(f"Alvo de continência ausente para a junta {joint}.")
            target[joint] = float(right_salute[joint])

        for right_joint, (left_joint, sign) in ATTENTION_MIRROR.items():
            if right_joint not in right_attention_reference:
                raise ValueError(
                    f"Referência de sentido ausente para a junta {right_joint}."
                )
            target[left_joint] = sign * float(
                right_attention_reference[right_joint]
            )

        return target

    def lower_salute_to_attention(self) -> bool:
        """
        Desfaz a continência movendo somente o braço direito para a
        posição final de sentido. O braço esquerdo permanece exatamente
        na posição física atual, e as mãos permanecem em maos_sentido.json.
        """
        if not self.leave_rest_if_needed():
            return False

        if not self.apply_both_hands_pose_file(
            HAND_ATTENTION_POSE_FILE,
            "Desc arma / sentido",
        ):
            return False

        right_attention = self.load_right_arm_pose_file(ATTENTION_STAGE2_FILE)
        if right_attention is None:
            return False

        target = self.build_target_preserving_left(right_attention)
        if target is None:
            self.log("Não foi possível construir a posição de Desc arma.")
            return False

        if not self.set_all_arm_target(target):
            return False

        self.log(
            "Desc arma — movendo somente o braço direito para sentido; "
            "braço esquerdo preservado."
        )

        if self.wait_until_target(timeout=15.0, tolerance=0.035):
            self.posture_state = "desc_arma"
            self.log("Desc arma concluído; braço direito em sentido.")
            return True

        # Mesmo que a tolerância final não seja atingida integralmente, a
        # próxima continência deve preservar o braço esquerdo, pois o comando
        # anterior foi explicitamente Desc arma.
        self.posture_state = "desc_arma"
        self.log("AVISO: o movimento de Desc arma não convergiu completamente.")
        return True

    def move_to_saved_salute(self) -> bool:
        """
        Executa a continência. Se o braço esquerdo já estiver fisicamente
        na posição final de sentido, sua posição atual é preservada e somente
        o braço direito se desloca para a continência. Caso contrário, o braço
        esquerdo passa normalmente pelos estágios 1 e 2 de sentido.
        """
        if not self.leave_rest_if_needed():
            return False

        if not self.apply_both_hands_pose_file(
            HAND_ATTENTION_POSE_FILE,
            "posição de continência",
        ):
            return False

        right_salute = self.load_right_arm_pose_file(SALUTE_POSE_FILE)
        right_stage1 = self.load_right_arm_pose_file(ATTENTION_STAGE1_FILE)
        right_stage2 = self.load_right_arm_pose_file(ATTENTION_STAGE2_FILE)

        if right_salute is None or right_stage1 is None or right_stage2 is None:
            return False

        preserve_left = (
            self.posture_state == "desc_arma"
            or self.is_left_at_attention(right_stage2)
        )

        if preserve_left:
            target = self.build_target_preserving_left(right_salute)
            if target is None or not self.set_all_arm_target(target):
                return False

            if self.posture_state == "desc_arma":
                self.log(
                    "Robô em Desc arma; braço esquerdo preservado e somente "
                    "o braço direito será movido para a continência."
                )
            else:
                self.log(
                    "Braço esquerdo já está fisicamente em sentido; "
                    "posição esquerda preservada e somente o braço direito "
                    "será movido para a continência."
                )

            if self.wait_until_target(timeout=15.0, tolerance=0.035):
                self.posture_state = "continencia"
                self.log("Pose de continência alcançada; braço esquerdo preservado.")
                return True

            self.posture_state = "continencia"
            self.log("AVISO: a continência não convergiu completamente.")
            return True

        salute_stage1 = self.build_salute_with_left_attention(
            right_salute, right_stage1
        )
        salute_stage2 = self.build_salute_with_left_attention(
            right_salute, right_stage2
        )

        if salute_stage1 is None or salute_stage2 is None:
            self.log("A postura equilibrada ainda não foi capturada.")
            return False

        if not self.set_all_arm_target(salute_stage1):
            return False

        self.log(
            "Continência — braço direito na pose salva; "
            f"braço esquerdo no estágio 1: {ATTENTION_STAGE1_FILE}"
        )
        if not self.wait_until_target(timeout=15.0, tolerance=0.035):
            self.log("AVISO: o primeiro estágio da continência não convergiu completamente.")

        if not self.set_all_arm_target(salute_stage2):
            return False

        self.log(
            "Continência — braço direito mantido; "
            f"braço esquerdo no estágio 2: {ATTENTION_STAGE2_FILE}"
        )
        if self.wait_until_target(timeout=15.0, tolerance=0.035):
            self.posture_state = "continencia"
            self.log("Pose de continência alcançada com o braço esquerdo em sentido.")
            return True

        self.posture_state = "continencia"
        self.log(
            "AVISO: o segundo estágio da continência não convergiu completamente."
        )
        return True

    def right_balance_pose_by_name(self) -> Optional[Dict[str, float]]:
        if self.balance_pose is None:
            return None

        return {
            name: float(self.balance_pose[joint])
            for name, joint in RIGHT_JOINT_NAMES.items()
        }

    def left_balance_pose_by_name(self) -> Optional[Dict[str, float]]:
        if self.balance_pose is None:
            return None

        return {
            name: float(self.balance_pose[joint])
            for name, joint in LEFT_JOINT_NAMES.items()
        }

    def current_both_arms_by_name(self) -> Optional[Dict[str, Dict[str, float]]]:
        current = self.current_all_arm_position()
        if current is None:
            return None
        return {
            "left_arm": {name: float(current[joint]) for name, joint in LEFT_JOINT_NAMES.items()},
            "right_arm": {name: float(current[joint]) for name, joint in RIGHT_JOINT_NAMES.items()},
        }

    def current_target_by_name(self) -> Optional[Dict[str, float]]:
        with self.pose_lock:
            if self.target_pose is None:
                return None

            return {
                name: float(self.target_pose[joint])
                for name, joint in RIGHT_JOINT_NAMES.items()
            }

    def shutdown(self) -> None:
        # Tenta liberar o braço apenas se o controle estava ativo.
        if self.arm_enabled and self.balance_pose is not None:
            try:
                self.return_to_balance_and_release()
            except Exception:
                self.log("Falha ao liberar os braços durante o encerramento.")

        # [ipe-2-code] Só depois do retorno: é a thread de controle que leva os braços ao alvo.
        self.shutdown_event.set()

        self.stop_hand_control("both")

        for side in ("left", "right"):
            client, lock = self._hand_client_and_lock(side)
            with lock:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
                    self._set_hand_client(side, None)

        if self.control_thread.is_alive():
            self.control_thread.join(timeout=1.0)
