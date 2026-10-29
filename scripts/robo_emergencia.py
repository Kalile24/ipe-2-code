"""Parada de emergência pelo computador: põe o robô em damp (motores soltos) e mata o corpo.

Com o robô no suporte, damp é o estado mais seguro: ele fica pendurado, sem torque.
Uso, no robô (venv do projeto, sem ROS):
    ~/ipe-2-code/.venv/bin/python ~/ipe-2-code/scripts/robo_emergencia.py           # pronto: Enter = DAMP
    ~/ipe-2-code/.venv/bin/python ~/ipe-2-code/scripts/robo_emergencia.py --agora   # damp já
O modo "pronto" deixa a conexão com o robô aberta antes, para o damp sair sem atraso; o
robo_rotina_cumprimento.sh --armado o abre na janela "emergencia" do tmux.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time

DAMP = 1


def connect(network_interface: str) -> object:
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient

    ChannelFactoryInitialize(0, network_interface)
    loco = LocoClient()
    loco.SetTimeout(3.0)
    loco.Init()
    return loco


def fsm_id(loco: object) -> int | None:
    from unitree_sdk2py.g1.loco.g1_loco_api import ROBOT_API_ID_LOCO_GET_FSM_ID

    code, data = loco._Call(ROBOT_API_ID_LOCO_GET_FSM_ID, "{}")
    if code != 0 or data is None:
        return None
    try:
        return json.loads(data)["data"]
    except (KeyError, TypeError, ValueError):
        return None


def emergency(loco: object) -> bool:
    print("EMERGÊNCIA: damp", flush=True)
    print(f"SetFsmId(1): {loco.SetFsmId(DAMP)}", flush=True)
    # O body_worker publica no arm_sdk a 50 Hz; morto, ninguém mais comanda os braços. Ele
    # primeiro: se o body_node morresse antes, o worker veria a entrada fechar e devolveria os
    # braços ao equilíbrio (movimento) em vez de ficar parado em damp.
    subprocess.run(["pkill", "-9", "-f", "robot_reaction_ros.body_worker"], check=False)
    subprocess.run(["pkill", "-9", "-f", "robot_reaction_ros/body_node"], check=False)
    print("body_worker e body_node encerrados (se estavam rodando)", flush=True)
    for _ in range(10):
        atual = fsm_id(loco)
        if atual == DAMP:
            print("confirmado: robô em damp (FSM 1)", flush=True)
            return True
        print(f"FSM atual: {atual}; repetindo damp", flush=True)
        loco.SetFsmId(DAMP)
        time.sleep(0.5)
    print("ATENÇÃO: o robô não confirmou damp", flush=True)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agora", action="store_true", help="damp imediato, sem esperar Enter")
    parser.add_argument("--estado", action="store_true", help="só mostra o FSM atual (não mexe em nada)")
    parser.add_argument("--iface", default="eth0", help="interface da rede do robô (default: eth0)")
    args = parser.parse_args()

    loco = connect(args.iface)
    if args.estado:
        print(f"FSM atual: {fsm_id(loco)}")
        return 0
    if not args.agora:
        print(f"Conectado (FSM atual: {fsm_id(loco)}). Aperte Enter para DAMP (motores soltos).", flush=True)
        input()
    return 0 if emergency(loco) else 1


if __name__ == "__main__":
    raise SystemExit(main())
