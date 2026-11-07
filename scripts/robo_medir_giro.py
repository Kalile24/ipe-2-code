"""Mede o yaw do IMU do G1 (só leitura: NÃO envia nenhum comando ao robô).

Gire o robô pelo controle da Unitree e confira o ângulo acumulado: +180 depois de uma meia-volta à
esquerda, -180 à direita. Parado por 30 s o acumulado deve ficar bem abaixo de 10 graus.
Imprime ~10 Hz: yaw em graus e girado acumulado em graus (+ = esquerda). Ctrl+C para sair.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from core.meia_volta import acumular


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interface", default="eth0", help="interface de rede do robô (padrão eth0)")
    args = parser.parse_args()

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_

    ultimo = [None]  # último yaw (rad) recebido
    ChannelFactoryInitialize(0, args.interface)
    sub = ChannelSubscriber("rt/lowstate", LowState_)
    sub.Init(lambda msg: ultimo.__setitem__(0, float(msg.imu_state.rpy[2])), 10)

    girado, anterior = 0.0, None
    try:
        while True:
            time.sleep(0.1)
            yaw = ultimo[0]
            if yaw is None:
                print("sem lowstate ainda...", flush=True)
                continue
            if anterior is not None:
                girado = acumular(girado, anterior, yaw)
            anterior = yaw
            print(f"yaw {math.degrees(yaw):8.1f} graus   girado {math.degrees(girado):8.1f} graus", flush=True)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
