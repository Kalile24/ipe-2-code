"""Processo SEM ROS que fala com o robô pelo G1ArmController do ~/hhhh.

Por que um processo à parte: o rclpy e o SDK da Unitree usam o CycloneDDS com configurações
diferentes, e no mesmo processo o `ChannelFactoryInitialize` falha ("channel factory init
error"; testado no robô em 2026-10-29). O body_node (ROS) abre este processo e conversa com ele
por linhas JSON: uma ordem na entrada padrão, uma resposta no stdout de protocolo.

    → {"cmd": "initialize"} | {"cmd": "posture", "nome": "sentido"} | {"cmd": "shutdown"}
    ← {"ok": true} | {"ok": false, "erro": "..."}

Ao subir, ele cria o controlador e responde uma vez ({"ok": ...}) antes de qualquer ordem.
Entrada fechada (o body_node morreu) = shutdown: braços de volta ao equilíbrio.
"""
from __future__ import annotations

import functools
import json
import os
import signal
import sys
import time
from types import SimpleNamespace
from typing import IO


class HhhhBody:
    """As posturas do ~/hhhh, chamadas como o movimentos_militares.py chama (F1+...).

    Importa o G1ArmController de ~/hhhh/g1_arm_calibration_gui_v29.py SEM editar nada lá, com as
    mesmas velocidades e a mesma espera do FSM 4 do movimentos_militares.py. O movimentos_militares.py
    não pode estar rodando junto: seriam dois processos publicando em rt/arm_sdk.
    """

    def __init__(self, hhhh_dir: str, network_interface: str) -> None:
        if hhhh_dir not in sys.path:
            sys.path.insert(0, hhhh_dir)
        from g1_arm_calibration_gui_v29 import DESC_ARMA_MAX_JOINT_SPEED, G1ArmController
        from movimentos_militares import MovimentosMilitares

        self.robot = G1ArmController(iface=network_interface, kp=35.0, kd=1.2, max_joint_speed=0.35)
        # A espera do FSM 4 mais tolerante do movimentos_militares.py (a que o F1+UP usa hoje).
        casca = SimpleNamespace(robot=self.robot)
        self.robot.wait_fsm4_transition_complete = functools.partial(
            MovimentosMilitares.wait_fsm4_transition_complete, casca
        )
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
        """F1+UP: damp → em pé (FSM 4) → equilíbrio (FSM 801). Robô no suporte."""
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
        if self.robot.arm_enabled:
            self.robot.return_to_balance_and_release()
        self.robot.shutdown()


def serve(body: object, inp: IO[str], out: IO[str]) -> None:
    """Atende ordens até `shutdown` ou até a entrada fechar (que também vira shutdown)."""

    def reply(ok: bool, erro: str = "") -> None:
        out.write(json.dumps({"ok": ok, "erro": erro} if erro else {"ok": ok}) + "\n")
        out.flush()

    for line in inp:
        try:
            ordem = json.loads(line)
            cmd = ordem["cmd"]
            if cmd == "initialize":
                reply(bool(body.initialize()))
            elif cmd == "posture":
                reply(bool(body.posture(ordem["nome"])))
            elif cmd == "shutdown":
                break
            else:
                reply(False, f"ordem desconhecida {cmd!r}")
        except Exception as exc:  # erro do SDK numa ordem não derruba o processo
            reply(False, repr(exc))
    try:
        body.shutdown()
    finally:
        reply(True)


def main() -> int:
    hhhh_dir, network_interface = sys.argv[1], sys.argv[2]
    # O Ctrl+C do terminal chega a todo o grupo de processos; quem decide o encerramento é o
    # body_node (ele manda `shutdown` na hora certa).
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # O G1ArmController escreve o log com print(): o stdout real fica só para o protocolo e o
    # resto vai para o stderr (que aparece no log do launch).
    protocolo = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        body = HhhhBody(hhhh_dir, network_interface)
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
