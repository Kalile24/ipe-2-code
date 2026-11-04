"""Levanta o robô NO SUPORTE: damp → em pé (FSM 4) → equilíbrio (FSM 801), como o F1+UP do ~/hhhh.

Só começa com o robô mole (FSM 0 sem torque ou 1 damp): em pé, recusa (o damp do começo o
derrubaria). Usa o mesmo corpo da rotina (body_worker.G1Body, com a trava de um corpo por vez) e,
no fim, devolve os braços e solta o arm_sdk; o robô fica em equilíbrio. Chamado pelo combo
F2+A segurado (scripts/robo_controle.py); à mão, no robô:
    source ~/ipe-2-code/scripts/ambiente_robo.sh && python3 ~/ipe-2-code/scripts/robo_levantar.py
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSES = os.path.join(REPO, "ros2_ws", "src", "robot_reaction_ros", "poses")
SEM_TORQUE_OU_DAMP = (0, 1)


def main() -> int:
    from robot_reaction_ros.body_worker import G1Body, travar_corpo

    trava = travar_corpo(espera_s=0.0)
    if trava is None:
        print("levantar: outro processo já comanda o corpo (a rotina está de pé?)", flush=True)
        return 1
    body = G1Body(POSES, "eth0")
    try:
        fsm_id, fsm_mode = body.robot.state("Antes de levantar")
        if fsm_id not in SEM_TORQUE_OU_DAMP:
            print(f"levantar: robô em FSM {fsm_id}/{fsm_mode}, não está mole: recuso (em pé, o damp o derrubaria)",
                  flush=True)
            return 1
        ok = body.initialize()
        print(f"levantar: {'em equilíbrio (FSM 801)' if ok else 'FALHOU'}", flush=True)
        return 0 if ok else 1
    finally:
        body.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
