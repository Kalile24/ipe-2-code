"""Processo SEM ROS que fala com o robô pelo G1ArmController (g1_arm_controller.py).

Por que um processo à parte: o rclpy e o SDK da Unitree usam o CycloneDDS com configurações
diferentes, e no mesmo processo o `ChannelFactoryInitialize` falha ("channel factory init
error"; testado no robô em 2026-10-29). O body_node (ROS) abre este processo e conversa com ele
por linhas JSON: uma ordem na entrada padrão, uma resposta no stdout de protocolo.

    → {"id": 7, "cmd": "initialize"} | {"id": 8, "cmd": "posture", "nome": "sentido"} | {"id": 9, "cmd": "shutdown"}
    ← {"id": 7, "ok": true} | {"id": 8, "ok": false, "erro": "..."}

A resposta repete o `id` da ordem: se o body_node desistiu de esperar uma postura, a resposta
atrasada dela não é confundida com a da ordem seguinte.
Ao subir, ele cria o controlador e responde uma vez ({"ok": ...}, sem id) antes de qualquer ordem.
Entrada fechada (o body_node morreu) = shutdown: braços de volta ao equilíbrio.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from typing import IO

SEM_TORQUE_OU_DAMP = (0, 1)  # FSM_ID do G1 com os motores soltos: o damp não muda nada


class G1Body:
    """As posturas militares, chamadas como o ~/hhhh/movimentos_militares.py chama (F1+...).

    Usa a nossa cópia do G1ArmController (g1_arm_controller.py, com as poses do pacote), com as
    mesmas velocidades do movimentos_militares.py; nada do ~/hhhh é importado. O
    movimentos_militares.py não pode estar rodando junto: seriam dois processos publicando em
    rt/arm_sdk.
    """

    def __init__(self, poses_dir: str, network_interface: str, rest_forward_pulse: bool = True) -> None:
        # As constantes das poses são lidas na importação: G1_POSE_DIR tem que vir antes.
        if poses_dir:
            os.environ["G1_POSE_DIR"] = poses_dir
        from robot_reaction_ros.g1_arm_controller import DESC_ARMA_MAX_JOINT_SPEED, G1ArmController

        self.robot = G1ArmController(iface=network_interface, kp=35.0, kd=1.2, max_joint_speed=0.35)
        # True = o Descansar dá um passo curto para frente (SetVelocity 0,12 m/s) para compensar
        # os braços indo para trás, como no ~/hhhh.
        self.robot.rest_forward_pulse = rest_forward_pulse
        time.sleep(3.0)  # mesma espera do MovimentosMilitares: DDS e LocoClient estabilizarem
        # Postura -> (velocidade máxima das juntas ou None = a da própria rotina, função).
        self._posturas = {
            "sentido": (0.7, self.robot.move_to_attention),
            "descansar": (None, self.robot.move_to_rest),
            "continencia": (2.0, self.robot.move_to_saved_salute),
            "desc_arma": (DESC_ARMA_MAX_JOINT_SPEED, self.robot.lower_salute_to_attention),
            "a_vontade": (None, self.robot.return_to_balance_and_release),
        }

    def initialize(self) -> bool:
        """F1+UP: damp → em pé (FSM 4) → equilíbrio (FSM 801). Robô no suporte.

        O damp solta todos os motores: só começa por ele se o robô já está mole (FSM 0 ou 1).
        Já em equilíbrio (FSM 801, rodada anterior) aproveita sem passar pelo damp; em pé em
        qualquer outro modo, recusa — o damp derrubaria o robô fora do suporte.
        """
        fsm_id, fsm_mode = self.robot.state("Antes de inicializar")
        if fsm_id == 801 and fsm_mode == 0:
            self.robot.initialized_801 = True  # o initialize_to_balance só captura a postura
        elif fsm_id not in SEM_TORQUE_OU_DAMP:
            self.robot.log(
                f"ERRO: robô em FSM_ID={fsm_id}, FSM_MODE={fsm_mode}: não inicializo (o damp o derrubaria). "
                "No suporte, ponha-o em damp (controle ou scripts/robo_emergencia.py) e suba de novo."
            )
            return False
        return bool(self.robot.initialize_to_balance())

    def posture(self, nome: str) -> bool:
        velocidade, funcao = self._posturas[nome]
        if velocidade is None:
            return bool(funcao())
        anterior = self.robot.max_joint_speed
        try:
            self.robot.max_joint_speed = velocidade
            return bool(funcao())
        finally:
            self.robot.max_joint_speed = anterior

    def shutdown(self) -> None:
        """Braços de volta ao equilíbrio e arm_sdk solto; o robô continua em pé (FSM 801)."""
        self.robot.shutdown()


def serve(body: object, inp: IO[str], out: IO[str]) -> None:
    """Atende ordens até `shutdown` ou até a entrada fechar (que também vira shutdown)."""

    def reply(ordem: dict, ok: bool, erro: str = "") -> None:
        resposta = {"id": ordem["id"]} if "id" in ordem else {}
        resposta["ok"] = ok
        if erro:
            resposta["erro"] = erro
        out.write(json.dumps(resposta) + "\n")
        out.flush()

    ordem: dict = {}  # entrada fechada sem ordem de shutdown: a resposta final vai sem id
    for line in inp:
        ordem = {}
        try:
            ordem = json.loads(line)
            cmd = ordem["cmd"]
            if cmd == "initialize":
                reply(ordem, bool(body.initialize()))
            elif cmd == "posture":
                reply(ordem, bool(body.posture(ordem["nome"])))
            elif cmd == "shutdown":
                break
            else:
                reply(ordem, False, f"ordem desconhecida {cmd!r}")
        except Exception as exc:  # erro do SDK numa ordem não derruba o processo
            reply(ordem if isinstance(ordem, dict) else {}, False, repr(exc))
    else:
        ordem = {}
    try:
        body.shutdown()
    finally:
        reply(ordem, True)


def main() -> int:
    poses_dir, network_interface = sys.argv[1], sys.argv[2]
    rest_forward_pulse = len(sys.argv) < 4 or sys.argv[3] != "sem_passo"
    # O Ctrl+C do terminal chega a todo o grupo de processos; quem decide o encerramento é o
    # body_node (ele manda `shutdown` na hora certa).
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # O G1ArmController escreve o log com print(): o stdout real fica só para o protocolo e o
    # resto vai para o stderr (que aparece no log do launch).
    protocolo = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        body = G1Body(poses_dir, network_interface, rest_forward_pulse)
    except Exception as exc:
        protocolo.write(json.dumps({"ok": False, "erro": repr(exc)}) + "\n")
        protocolo.flush()
        return 1
    protocolo.write(json.dumps({"ok": True}) + "\n")
    protocolo.flush()
    serve(body, sys.stdin, protocolo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
